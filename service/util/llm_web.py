"""
Utilities for LLM calls with web-search via function calling.

- Defines function tools: ddg_web_search (DuckDuckGo) and fetch_url (Playwright-backed fetch)
- Runs a tool loop using the Responses API; falls back to Chat Completions if needed

Usage example:
    from util.llm_web import run_with_search
    out = run_with_search("Summarize latest actions on <topic> and include links.")
    print(out.text)
    print(out.sources)
"""
from __future__ import annotations

import json
import logging
import os, sys
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, field

from bs4 import BeautifulSoup
from pydantic import BaseModel
import requests
from urllib.parse import urlparse, parse_qs, unquote, urljoin, quote_plus

# Optional: DDGS (DuckDuckGo Search) library
try:
    from ddgs import DDGS  # type: ignore
except Exception:
    DDGS = None  # type: ignore


_HERE = os.path.dirname(__file__)
_SERVICE_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _SERVICE_ROOT)

from util.scrape_utils import playwright_get
from models import LMLogEntry
from util.schema_outline import compact_outline_from_model
logger = logging.getLogger(__name__)
from dotenv import load_dotenv
load_dotenv(os.path.join(_SERVICE_ROOT, ".env"))
import openai
_CLIENT = openai.OpenAI()

 

def _extract_ddg_href(href: str, base: str) -> Optional[str]:
    if not href:
        return None
    try:
        # Absolute http(s)
        if href.startswith("http://") or href.startswith("https://"):
            # Skip DuckDuckGo internal
            if "duckduckgo.com" in urlparse(href).netloc:
                # attempt uddg param
                q = parse_qs(urlparse(href).query)
                val = q.get("uddg", [None])[0]
                if val:
                    return unquote(val)
                return None
            return href
        # Relative /l/?uddg=...
        if href.startswith("/l/") or href.startswith("/lite/") or href.startswith("/"):
            full = urljoin(base, href)
            q = parse_qs(urlparse(full).query)
            val = q.get("uddg", [None])[0]
            if val:
                return unquote(val)
            return None
        # Any other relative: resolve then try uddg param
        full = urljoin(base, href)
        q = parse_qs(urlparse(full).query)
        val = q.get("uddg", [None])[0]
        if val:
            return unquote(val)
        if full.startswith("http"):
            return full
    except Exception:
        return None
    return None


def _ddg_search_ddgs(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Use DDGS to perform a DuckDuckGo search and return a list of {title, url, snippet}."""
    if DDGS is None:
        return []
    out: List[Dict[str, Any]] = []
    try:
        with DDGS(timeout=15) as ddgs:
            for r in ddgs.text(query, region="wt-wt", safesearch="moderate", max_results=max_results):
                try:
                    title = str(r.get("title") or r.get("heading") or "").strip()
                    url = str(r.get("href") or r.get("url") or "").strip()
                    snippet = str(r.get("body") or r.get("snippet") or "").strip()
                    if url:
                        out.append({"title": title or url, "url": url, "snippet": snippet})
                except Exception:
                    continue
                if len(out) >= max_results:
                    break
    except Exception:
        return []
    return out[:max_results]


def _ddg_search_html(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Fallback HTML parsing for DuckDuckGo search returning {title, url, snippet}."""
    results: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def _parse_ddg_html(html: str, base: str):
        soup = BeautifulSoup(html, "html.parser")
        # Try common selectors first
        anchors = soup.select("a.result__a, a.result__url, a[href]")
        for a in anchors:
            try:
                title = a.get_text(strip=True) or ""
                href = str(a.get("href") or "")
                url = _extract_ddg_href(href, base)
                if not url or url in seen:
                    continue
                # Heuristically pull a nearby snippet
                snippet = ""
                parent = a.parent
                for _ in range(3):
                    if not parent:
                        break
                    # pick nearest text block sibling
                    sibs = list(parent.children) if hasattr(parent, "children") else []
                    for s in sibs:
                        if getattr(s, "name", "").lower() in ("p", "div", "span"):
                            txt = s.get_text(" ", strip=True)
                            if txt and len(txt) > 40:
                                snippet = txt
                                break
                    if snippet:
                        break
                    parent = getattr(parent, "parent", None)
                results.append({"title": title or url, "url": url, "snippet": snippet})
                seen.add(url)
                if len(results) >= max_results:
                    return
            except Exception:
                continue

    # Primary: /html endpoint
    try:
        resp = requests.get(
            f"https://duckduckgo.com/html/?q={quote_plus(query)}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        if resp.status_code == 200 and resp.text:
            _parse_ddg_html(resp.text, "https://duckduckgo.com")
    except Exception:
        pass

    # Fallback: lite endpoint
    if len(results) < max_results:
        try:
            resp2 = requests.get(
                f"https://lite.duckduckgo.com/lite/?q={quote_plus(query)}",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=15,
            )
            if resp2.status_code == 200 and resp2.text:
                _parse_ddg_html(resp2.text, "https://lite.duckduckgo.com")
        except Exception:
            pass

    return results[:max_results]


def _ddg_search(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Perform a DuckDuckGo search using DDGS when available, else fallback HTML parser."""
    via_ddgs = _ddg_search_ddgs(query, max_results=max_results)
    if via_ddgs:
        return via_ddgs
    return _ddg_search_html(query, max_results=max_results)


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for s in soup(["script", "style", "noscript"]):
        s.extract()
    text = soup.get_text(" ")
    # Normalize whitespace
    return " ".join(text.split())


def _fetch_url(url: str, max_chars: int = 50000) -> Dict[str, Any]:
    try:
        resp = playwright_get(url, timeout=20)
        resp.raise_for_status()
        html = resp.content.decode("utf-8", errors="ignore")
        text = _html_to_text(html)
        if max_chars and len(text) > max_chars:
            text = text[:max_chars]
        return {"url": url, "text": text}
    except Exception as e:
        return {"url": url, "error": str(e)}


def _handle_tool_call(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    if name == "ddg_web_search":
        q = str(arguments.get("query", "")).strip()
        k = int(arguments.get("max_results", 5) or 5)
        return {"results": _ddg_search(q, max_results=k)}
    if name == "fetch_url":
        url = str(arguments.get("url", ""))
        max_chars = int(arguments.get("max_chars", 50000) or 50000)
        return _fetch_url(url, max_chars=max_chars)
    return {"error": f"Unknown tool {name}"}

def _tool_defs():
    return [
        {
            "type": "function",
            "name": "ddg_web_search",
            "description": "Search the public web for a query and return relevant links with snippets.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language query"},
                    "max_results": {"type": ["integer", "null"], "minimum": 1, "maximum": 25, "default": 5},
                },
                "required": ["query", "max_results"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "fetch_url",
            "description": "Fetch the readable content of a URL (JS-rendered if needed) and return plain text.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"},
                    "max_chars": {"type": ["integer", "null"], "minimum": 500, "maximum": 200000, "default": 50000},
                },
                "required": ["url", "max_chars"],
                "additionalProperties": False,
            },
        },
    ]

@dataclass
class SearchOutput:
    text: str = ""
    sources: List[Dict[str, Any]] = field(default_factory=list)
    messages: List[Dict[str, Any]] = field(default_factory=list)
    parsed: Optional[Any] = None
    lm_log: Optional[LMLogEntry] = None
def _extract_response_text(response: Any) -> str:
    # New SDK often provides output_text
    try:
        txt = getattr(response, "output_text", None)
        if isinstance(txt, str) and txt.strip():
            return txt.strip()
    except Exception:
        pass
    # Fallback: scan content items
    chunks: List[str] = []
    try:
        for it in getattr(response, "output", []) or []:
            it_type = getattr(it, "type", None) or (isinstance(it, dict) and it.get("type"))
            if it_type in ("message", "assistant_message", "text", "output_text"):
                content = getattr(it, "content", None)
                if isinstance(content, list):
                    for c in content:
                        t = getattr(c, "text", None) if hasattr(c, "text") else (c.get("text") if isinstance(c, dict) else None)
                        if isinstance(t, str) and t:
                            chunks.append(t)
                elif isinstance(content, str):
                    chunks.append(content)
    except Exception:
        pass
    return "\n".join(chunks).strip()


def _dedupe_add_source(sources: List[Dict[str, Any]], src: Dict[str, Any]):
    url = (src or {}).get("url")
    if not url:
        return
    if any(s.get("url") == url for s in sources):
        return
    sources.append({
        "title": src.get("title") or url,
        "url": url,
        "snippet": src.get("snippet") or src.get("text", "")[:200],
    })


SYSTEM_PROMPT = """
You are an expert news analyst and researcher.
The system will give a well-defined task. Use your available tools to complete the task as described.
This task is automatic: do not ask clarifying questions, engage in further discussion, or prompt the system for more information.
Provide a comprehensive report that fully meets the instructions. Do not include suggestions for next steps or use conversational language.
"""

def run_with_search(
    input_text: str,
    model: str = "gpt-5-mini",
    text_format: Optional[Union[type[BaseModel], BaseModel]]  = None,
    task_system: Optional[str] = None,
) -> SearchOutput:
    def _make_log_from_response(resp: Any) -> Optional[LMLogEntry]:
        try:
            call_id = getattr(resp, "id", None)
            usage = getattr(resp, "usage", None)
            input_tokens = 0
            output_tokens = 0
            if usage is not None:
                try:
                    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
                except Exception:
                    input_tokens = 0
                try:
                    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
                except Exception:
                    output_tokens = 0
            return LMLogEntry(
                api_type='responses',
                call_id=str(call_id or ""),
                called_from='util.llm_web.run_with_search',
                model_name=model,
                system_tokens=0,
                user_tokens=input_tokens,
                response_tokens=output_tokens,
            )
        except Exception:
            return None
    # Up to 3 attempts if the response text is empty
    for attempt in range(1, 4):
        messages: List[Any] = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]
        if task_system and str(task_system).strip():
            messages = [
                {"role": "developer", "content": SYSTEM_PROMPT},
                {"role": "system", "content": str(task_system).strip()},
            ]
        messages.append({"role": "user", "content": input_text})
        tools = _tool_defs()
        sources: List[Dict[str, Any]] = []

        # Guard against infinite loops
        max_turns = 8
        last_response: Any = None
        primary_log: Optional[LMLogEntry] = None

        # Main loop: always run WITHOUT structured parsing so tools can iterate freely
        for _ in range(max_turns):
            response = _CLIENT.responses.create(  # type: ignore[arg-type]
                model=model,
                tools=tools,  # type: ignore[arg-type]
                input=messages,  # type: ignore[arg-type]
            )
            last_response = response
            if primary_log is None:
                primary_log = _make_log_from_response(response)

            # Accumulate output content for the conversation state
            messages += response.output

            # Handle tool calls, if any
            had_tool_call = False
            for item in response.output:
                if getattr(item, "type", None) == "function_call":
                    had_tool_call = True
                    name_any = getattr(item, "name", None)
                    name = name_any if isinstance(name_any, str) else str(name_any or "")
                    args_raw = getattr(item, "arguments", "{}")
                    try:
                        args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
                    except Exception:
                        args = {}
                    result = _handle_tool_call(name, args)

                    # Collect sources from tool outputs
                    if name == "ddg_web_search":
                        # Just web search alone isn't enough to count as a source.
                        pass
                        # for r in result.get("results", []) or []:
                        #     _dedupe_add_source(sources, r)
                    elif name == "fetch_url":
                        _dedupe_add_source(sources, result)

                    messages.append({
                        "type": "function_call_output",
                        "call_id": getattr(item, "call_id", None),
                        "output": json.dumps(result),
                    })

            # If no tool calls were made, we're done
            if not had_tool_call:
                break

        final_text = _extract_response_text(last_response) if last_response is not None else ""

        # Always attempt a parse-only pass when a schema is provided
        parsed_obj: Optional[Any] = None
        if text_format is not None:
            try:
                try:
                    schema_str = compact_outline_from_model(text_format)
                except Exception:
                    schema_str = ""
                parse_messages = list(messages) + [
                    {
                        "role": "user",
                        "content": (
                            "Return ONLY the requested structured output using the conversation above. "
                            "Match this structure and type hints; do not include prose outside it.\n" + schema_str
                        ),
                    }
                ]
                parse_resp = _CLIENT.responses.parse(
                    model=model,
                    input=parse_messages,  # type: ignore[arg-type]
                    text_format=text_format,  # type: ignore[arg-type]
                )
                parsed_obj = getattr(parse_resp, "output_parsed", None)
                # Prefer a parse call log when parsing succeeds
                pl = _make_log_from_response(parse_resp)
                if pl is not None:
                    primary_log = pl
            except Exception:
                logger.exception("Structured parsing failed; will fallback to text if available")

        # Prefer returning parsed structured data when a format is requested
        if text_format is not None and parsed_obj is not None:
            return SearchOutput(text=final_text.strip() or "", sources=sources, messages=messages, parsed=parsed_obj, lm_log=primary_log)

        if final_text.strip():
            if text_format is None:
                return SearchOutput(text=final_text, sources=sources, messages=messages, lm_log=primary_log)
            else:
                return SearchOutput(text=final_text, sources=sources, messages=messages, parsed=None, lm_log=primary_log)
        else:
            # Try one finalization step to elicit direct text, then re-parse if needed
            try:
                finalize_messages = list(messages) + [
                    {"role": "user", "content": "Provide the final answer now as text. Do not call tools."}
                ]
                finalize_resp = _CLIENT.responses.create(
                    model=model,
                    input=finalize_messages,  # type: ignore[arg-type]
                )
                messages += getattr(finalize_resp, "output", []) or []
                final_text2 = _extract_response_text(finalize_resp)
                # If finalize produced content, we can update log
                fl = _make_log_from_response(finalize_resp)
                if fl is not None:
                    primary_log = fl
                if text_format is not None:
                    # One more structured parse attempt using updated conversation
                    try:
                        try:
                            schema_str2 = compact_outline_from_model(text_format)
                        except Exception:
                            schema_str2 = ""
                        parse_messages2 = list(messages) + [
                            {
                                "role": "user",
                                "content": (
                                    "Return ONLY the requested structured output using the conversation above. "
                                    "Match this structure and type hints; do not include prose outside it.\n" + schema_str2
                                ),
                            }
                        ]
                        parse_resp2 = _CLIENT.responses.parse(
                            model=model,
                            input=parse_messages2,  # type: ignore[arg-type]
                            text_format=text_format,  # type: ignore[arg-type]
                        )
                        parsed2 = getattr(parse_resp2, "output_parsed", None)
                        pl2 = _make_log_from_response(parse_resp2)
                        if pl2 is not None:
                            primary_log = pl2
                        if parsed2 is not None:
                            return SearchOutput(text=final_text2.strip() or "", sources=sources, messages=messages, parsed=parsed2, lm_log=primary_log)
                    except Exception:
                        logger.exception("Second structured parsing attempt failed; falling back to text if present")
                if final_text2.strip():
                    if text_format is None:
                        return SearchOutput(text=final_text2, sources=sources, messages=messages, lm_log=primary_log)
                    else:
                        return SearchOutput(text=final_text2, sources=sources, messages=messages, parsed=None, lm_log=primary_log)
            except Exception:
                logger.exception("Finalization attempt failed")

            if attempt < 3:
                print(f"Error: empty response text; retrying ({attempt}/3)")
            else:
                # Final attempt, return whatever we have (may be empty text and no parsed)
                if text_format is None:
                    return SearchOutput(text=final_text, sources=sources, messages=messages, lm_log=primary_log)
                else:
                    return SearchOutput(text=final_text, sources=sources, messages=messages, parsed=None, lm_log=primary_log)

    # Fallback return to satisfy type checkers; should be unreachable
    return SearchOutput(text="", sources=[], messages=[], lm_log=None)

if __name__ == "__main__":
    class Test(BaseModel):
        report: str
        title: str
        key_takeaways: List[str]
        follow_up_questions: List[str]
    print(run_with_search(
        "Please retrieve the latest news about artificial intelligence.",
        text_format=Test
    ))