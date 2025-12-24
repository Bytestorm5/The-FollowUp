from __future__ import annotations

from typing import Any, Dict, List, Optional, Union, Tuple


def _get_schema_from_model(model: Any) -> Dict[str, Any]:
    """Return a JSON schema dict from a Pydantic model class or instance (v1/v2).

    Falls back to empty object schema when unavailable.
    """
    try:
        # Pydantic v2
        if hasattr(model, "model_json_schema"):
            return model.model_json_schema()  # type: ignore[attr-defined]
        # Pydantic v1
        if hasattr(model, "schema"):
            return model.schema()  # type: ignore[attr-defined]
    except Exception:
        pass
    return {"type": "object", "properties": {}}


def _type_of(node: Dict[str, Any]) -> str:
    t = node.get("type")
    if isinstance(t, list):
        # collapse e.g., ["string","null"] => "string|null"
        t = "|".join(str(x) for x in t if x)
    if not t:
        # enum without type
        if "enum" in node:
            return "enum"
        if "$ref" in node:
            return "ref"
        return "object" if "properties" in node else "any"
    # add helpful format hints
    fmt = node.get("format")
    if fmt in ("date", "date-time", "uri"):
        return f"{t}<{fmt}>"
    return str(t)


def _enum_values(node: Dict[str, Any], limit: int = 6) -> Optional[str]:
    vals = node.get("enum")
    if not isinstance(vals, list) or not vals:
        return None
    show = ", ".join(repr(v) for v in vals[:limit])
    if len(vals) > limit:
        show += ", …"
    return f"enum[{show}]"


def _array_type(node: Dict[str, Any], *, schema: Dict[str, Any]) -> Optional[str]:
    if node.get("type") != "array":
        return None
    it = node.get("items") or {}
    if isinstance(it, list):
        it = it[0] if it else {}
    return f"array[{_summarize_type(it, schema)}]"


def _resolve_ref(name: str, schema: Dict[str, Any]) -> Dict[str, Any]:
    defs = schema.get("$defs") or schema.get("definitions") or {}
    return defs.get(name, {}) if isinstance(defs, dict) else {}


def _strip_null_union(candidates: List[str]) -> List[str]:
    return [c for c in candidates if c and c.lower() != "null"]


def _format_basic_string(node: Dict[str, Any]) -> str:
    fmt = node.get("format")
    if fmt == "date":
        return "date"
    if fmt == "date-time":
        return "date-time"
    if fmt == "uri":
        return "uri"
    return "string"


def _summarize_type(node: Dict[str, Any], schema: Dict[str, Any]) -> str:
    # Handle enum
    ev = _enum_values(node)
    if ev:
        return ev

    # Handle anyOf/oneOf union types
    for key in ("anyOf", "oneOf"):
        if key in node and isinstance(node[key], list):
            parts: List[str] = []
            for sub in node[key]:
                if not isinstance(sub, dict):
                    continue
                parts.append(_summarize_type(sub, schema))
            parts = _strip_null_union(parts)
            # Deduplicate while preserving order
            seen = set()
            uniq = []
            for p in parts:
                if p not in seen:
                    seen.add(p)
                    uniq.append(p)
            return "|".join(uniq) if uniq else "any"

    # Handle $ref
    if "$ref" in node:
        ref = str(node["$ref"]).split("/")[-1]
        ref_node = _resolve_ref(ref, schema)
        if isinstance(ref_node, dict):
            # If referenced node is an enum, show enum; else object(Name)
            ev2 = _enum_values(ref_node)
            if ev2:
                return ev2
            if ref_node.get("type") == "object" or ref_node.get("properties"):
                return f"object({ref})"
        return f"object({ref})"

    # Handle arrays
    at = _array_type(node, schema=schema)
    if at:
        return at

    # Handle basic types (including nullable types list)
    t = node.get("type")
    if isinstance(t, list):
        parts = []
        for tp in t:
            if tp == "null":
                continue
            if tp == "string":
                parts.append(_format_basic_string(node))
            else:
                parts.append(str(tp))
        parts = _strip_null_union(parts)
        return "|".join(parts) if parts else "any"
    if t == "string":
        return _format_basic_string(node)
    if t:
        return str(t)

    # Object without explicit type
    if "properties" in node:
        return "object"
    return "any"


def _collect_objects(schema: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    out: List[Tuple[str, Dict[str, Any]]] = []
    # top-level
    out.append((schema.get("title") or "Root", schema))
    defs = schema.get("$defs") or schema.get("definitions") or {}
    if isinstance(defs, dict):
        for k, v in defs.items():
            if isinstance(v, dict):
                out.append((k, v))
    return out


def compact_outline_from_schema(schema: Dict[str, Any], *, max_desc_len: int = 0) -> str:
    """Produce a compact outline for a JSON Schema object.

    Example line format:
      ClaimProcessingStep:
      - claim: string (required)
      - type: enum['goal','promise','statement'] (required)
      - completion_condition_date: date | object(Date_Delta) (optional)
    """
    lines: List[str] = []
    for name, obj in _collect_objects(schema):
        if not isinstance(obj, dict):
            continue
        if obj.get("type") not in (None, "object") and not obj.get("properties"):
            # Non-object, skip
            continue
        lines.append(f"{name}:")
        props = obj.get("properties") or {}
        req = set(obj.get("required") or [])
        if not isinstance(props, dict) or not props:
            lines.append("- (no properties)")
            continue
        for key, spec in props.items():
            if not isinstance(spec, dict):
                continue
            required = "required" if key in req else "optional"
            type_hint = _summarize_type(spec, schema)
            lines.append(f"- {key}: {type_hint} ({required})")
    return "\n".join(lines)


def compact_outline_from_model(model: Any, *, max_desc_len: int = 0) -> str:
    schema = _get_schema_from_model(model)
    return compact_outline_from_schema(schema, max_desc_len=max_desc_len)
