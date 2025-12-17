import copy
import json
import os
import time
from typing import Any, Dict, Iterable, Optional, Callable

# Utilities shared by claim/enrich pipelines for OpenAI Batch workflows


def sanitize_schema_for_strict(schema: Any) -> Any:
    """Make a JSON Schema compatible with structured strict mode.

    For every object: set additionalProperties=false and require all properties.
    """
    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            for k in ("properties", "$defs", "definitions"):
                if k in node and isinstance(node[k], dict):
                    node[k] = {kk: walk(vv) for kk, vv in node[k].items()}
            for k in ("items", "additionalItems", "contains"):
                if k in node:
                    node[k] = walk(node[k])
            for k in ("anyOf", "oneOf", "allOf"):
                if k in node and isinstance(node[k], list):
                    node[k] = [walk(v) for v in node[k]]
            if node.get("type") == "object":
                node["additionalProperties"] = False
                if isinstance(node.get("properties"), dict):
                    node["required"] = list(node["properties"].keys())
                else:
                    node["properties"] = {}
                    node["required"] = []
            return node
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(copy.deepcopy(schema))


def write_jsonl(path: str, lines: Iterable[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False))
            f.write("\n")


def create_batch(openai_client, request_lines: Iterable[Dict[str, Any]], endpoint: str = "/v1/chat/completions"):
    tmp_dir = os.path.join(os.path.dirname(__file__), "..", "scripts", ".tmp")
    tmp_dir = os.path.abspath(tmp_dir)
    os.makedirs(tmp_dir, exist_ok=True)
    jsonl_path = os.path.join(tmp_dir, f"batch_{int(time.time())}.jsonl")
    write_jsonl(jsonl_path, request_lines)
    input_file = openai_client.files.create(file=open(jsonl_path, "rb"), purpose="batch")
    batch = openai_client.batches.create(
        input_file_id=input_file.id,
        endpoint=endpoint,
        completion_window="24h",
        metadata={"job": "pipeline"},
    )
    return batch


def poll_batch(openai_client, batch_id: str, poll_interval: int = 5, timeout: int = 60 * 30, expected_total: Optional[int] = None):
    def _extract_progress(b: Any, default_total: Optional[int]):
        rc = getattr(b, "request_counts", None) or (b.get("request_counts") if isinstance(b, dict) else None)
        total = None
        completed = None
        if rc is not None:
            total = getattr(rc, "total", None) or (rc.get("total") if isinstance(rc, dict) else None)
            completed = (
                getattr(rc, "completed", None)
                or (rc.get("completed") if isinstance(rc, dict) else None)
                or getattr(rc, "succeeded", None)
                or (rc.get("succeeded") if isinstance(rc, dict) else None)
            )
        if total is None:
            total = default_total
        if completed is None:
            completed = 0
        ratio = None
        try:
            if total and total > 0:
                ratio = completed / total
        except Exception:
            ratio = None
        return int(completed or 0), int(total or 0), ratio

    start = time.time()
    last_progress_ts = start
    hard_stop_ts = start + 60 * 60 * 4
    last_ratio = -1.0

    while True:
        batch = openai_client.batches.retrieve(batch_id)
        status = getattr(batch, "status", None) or (batch.get("status") if isinstance(batch, dict) else None)
        completed, total, ratio = _extract_progress(batch, expected_total)
        if status in ("completed", "expired", "cancelled"):
            return batch
        if status in ("failed",):
            raise RuntimeError(f"Batch {batch_id} failed: {batch}")
        if ratio is not None and ratio > last_ratio:
            last_ratio = ratio
            last_progress_ts = time.time()
        now = time.time()
        if now > hard_stop_ts or (now - last_progress_ts) > timeout:
            try:
                openai_client.batches.cancel(batch_id)
            except Exception:
                pass
            raise TimeoutError(f"Timeout while waiting for batch {batch_id}")
        time.sleep(poll_interval)


def poll_batch_with_fallback(openai_client, batch_id: str, *, poll_interval: int, timeout: int, expected_total: Optional[int], on_timeout: Callable[[], None]):
    try:
        return poll_batch(openai_client, batch_id, poll_interval=poll_interval, timeout=timeout, expected_total=expected_total)
    except TimeoutError:
        on_timeout()
        return None


def read_file_text(openai_client, file_id: str) -> str:
    file_response = openai_client.files.content(file_id)
    return getattr(file_response, "text", None) or str(file_response)


def iter_jsonl(text: str):
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        yield json.loads(line)
