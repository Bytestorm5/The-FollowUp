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

from enum import Enum
import json
import logging
import os, sys
from typing import Any, Dict, Iterable, List, Optional, Union
from dataclasses import dataclass, field

from bs4 import BeautifulSoup
from pydantic import BaseModel
import requests
from urllib.parse import urlparse, parse_qs, unquote, urljoin, quote_plus

# Optional: DDGS (DuckDuckGo Search) library
from ddgs import DDGS  # type: ignore


_HERE = os.path.dirname(__file__)
_SERVICE_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _SERVICE_ROOT)

from util.scrape_utils import playwright_get
from util import mongo
from util.mongo import normalize_dates as _normalize_dates
from models import LMLogEntry
from util.schema_outline import compact_outline_from_model
logger = logging.getLogger(__name__)
from dotenv import load_dotenv
load_dotenv(os.path.join(_SERVICE_ROOT, ".env"))
import openai
_CLIENT = openai.OpenAI()

 
SEARCH_BLACKLIST = [
    "grokipedia.com",
    "nypost.com",
    "washingtontimes.com"
]

def _query_preprocess(query: str) -> str:
    """Preprocess query to avoid blacklisted domains."""
    q = query
    for domain in SEARCH_BLACKLIST:
        q += f' -site:{domain}'
    return q

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


def _ddg_news_search(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Perform a DuckDuckGo News search using DDGS when available.

    Returns a list of {title, url, snippet, date?}
    """
    if DDGS is None:
        return []
    out: List[Dict[str, Any]] = []
    try:
        with DDGS(timeout=15) as ddgs:
            # DDGS.news is available in ddgs; fallback to text if missing
            for r in ddgs.news(query, max_results=max_results):  # type: ignore[call-arg]
                try:
                    title = str(r.get("title") or r.get("heading") or "").strip()
                    url = str(r.get("url") or r.get("href") or "").strip()
                    snippet = str(r.get("body") or r.get("snippet") or "").strip()
                    date = r.get("date") or r.get("published")
                    if url:
                        item = {"title": title or url, "url": url, "snippet": snippet}
                        if date:
                            item["date"] = date
                        out.append(item)
                except Exception:
                    continue
                if len(out) >= max_results:
                    break
    except Exception:
        return []
    return out[:max_results]


def _internal_search(
    query: str,
    max_articles: int = 10,
    max_claims: int = 20,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Search internal Mongo collections similar to the frontend search page.

    - Articles: search bronze_links across title, clean_markdown, raw_content, summary_paragraph, key_takeaways
    - Claims: search silver_claims across claim, verbatim_claim, completion_condition and attach latest update verdict
    """
    try:
        db = getattr(mongo, 'DB', None)
        bronze = getattr(mongo, 'bronze_links', None)
        claims_coll = getattr(mongo, 'silver_claims', None)
        if db is None or bronze is None or claims_coll is None:
            return {"error": "Mongo collections not available"}

        # Case-insensitive regex match; simple, portable approximation of Atlas Search
        regex = {"$regex": query, "$options": "i"}

        # Optional date filters
        import datetime as _dt
        sd: Optional[_dt.date] = None
        ed: Optional[_dt.date] = None
        try:
            if start_date and isinstance(start_date, str) and start_date.strip():
                sd = _dt.date.fromisoformat(start_date.strip())
        except Exception:
            sd = None
        try:
            if end_date and isinstance(end_date, str) and end_date.strip():
                ed = _dt.date.fromisoformat(end_date.strip())
        except Exception:
            ed = None

        # Normalize to match stored types (tz-aware datetimes in EST)
        nsd = _normalize_dates(sd) if sd else None
        ned = _normalize_dates(ed) if ed else None

        # Articles
        articles: List[Dict[str, Any]] = []
        try:
            _article_filter: Dict[str, Any] = {
                "$or": [
                    {"title": regex},
                    {"clean_markdown": regex},
                    {"raw_content": regex},
                    {"summary_paragraph": regex},
                    {"key_takeaways": regex},
                ]
            }
            if nsd or ned:
                rng: Dict[str, Any] = {}
                if nsd:
                    rng["$gte"] = nsd
                if ned:
                    rng["$lte"] = ned
                _article_filter["date"] = rng

            acur = bronze.find(
                _article_filter,
                projection={"title": 1, "date": 1, "link": 1, "summary_paragraph": 1},
            ).sort([("date", -1), ("_id", -1)]).limit(int(max_articles or 10))
            for a in acur:
                try:
                    articles.append({
                        "id": str(a.get("_id")),
                        "title": a.get("title"),
                        "date": a.get("date"),
                        "link": a.get("link"),
                        "summary_paragraph": a.get("summary_paragraph"),
                    })
                except Exception:
                    continue
        except Exception:
            articles = []

        # Claims
        claims: List[Dict[str, Any]] = []
        claim_ids: List[Any] = []
        try:
            _claims_filter: Dict[str, Any] = {
                "$or": [
                    {"claim": regex},
                    {"verbatim_claim": regex},
                    {"completion_condition": regex},
                ]
            }
            if nsd or ned:
                rng_c: Dict[str, Any] = {}
                if nsd:
                    rng_c["$gte"] = nsd
                if ned:
                    rng_c["$lte"] = ned
                _claims_filter["article_date"] = rng_c

            ccur = claims_coll.find(
                _claims_filter,
                projection={"claim": 1, "verbatim_claim": 1, "type": 1, "completion_condition": 1, "completion_condition_date": 1},
            ).sort([("_id", -1)]).limit(int(max_claims or 20))
            for c in ccur:
                cid = c.get("_id")
                claim_ids.append(cid)
                claims.append({
                    "id": str(cid),
                    "claim": c.get("claim"),
                    "type": c.get("type"),
                    "completion_condition": c.get("completion_condition"),
                    "completion_condition_date": c.get("completion_condition_date"),
                    "latest_update": None,
                })
        except Exception:
            claims = []
            claim_ids = []

        # Latest updates per claim
        try:
            updates_coll = db.get_collection('silver_updates')
            if claim_ids:
                ucur = updates_coll.find(
                    {"claim_id": {"$in": claim_ids}},
                    projection={"claim_id": 1, "verdict": 1, "created_at": 1},
                ).sort([("created_at", -1), ("_id", -1)])
                latest: Dict[str, Dict[str, Any]] = {}
                for u in ucur:
                    key = str(u.get("claim_id"))
                    if key not in latest:
                        latest[key] = {"verdict": u.get("verdict"), "created_at": u.get("created_at")}
                # Attach
                for c in claims:
                    lid = latest.get(c["id"]) if isinstance(latest, dict) else None
                    if lid:
                        c["latest_update"] = lid
        except Exception:
            pass

        return {"articles": articles, "claims": claims}
    except Exception as e:
        return {"error": f"internal search failed: {e}"}


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
        return {"results": _ddg_search(_query_preprocess(q), max_results=k)}
    if name == "ddg_news_search":
        q = str(arguments.get("query", "")).strip()
        k = int(arguments.get("max_results", 5) or 5)
        return {"results": _ddg_news_search(_query_preprocess(q), max_results=k)}
    if name == "fetch_url":
        url = str(arguments.get("url", ""))
        max_chars = int(arguments.get("max_chars", 50000) or 50000)
        return _fetch_url(url, max_chars=max_chars)
    if name == "internal_search":
        q = str(arguments.get("query", "")).strip()
        max_articles = int(arguments.get("max_articles", 10) or 10)
        max_claims = int(arguments.get("max_claims", 20) or 20)
        start_date = arguments.get("start_date")
        end_date = arguments.get("end_date")
        sd = str(start_date).strip() if isinstance(start_date, str) and start_date.strip() else None
        ed = str(end_date).strip() if isinstance(end_date, str) and end_date.strip() else None
        return _internal_search(q, max_articles=max_articles, max_claims=max_claims, start_date=sd, end_date=ed)
    return {"error": f"Unknown tool {name}"}

class ToolSet(Enum):
    WEB_SEARCH = "ddg_web"
    NEWS_SEARCH = "ddg_news"
    INTERNAL_SEARCH = "internal"

ToolChoices = Iterable[ToolSet]

def _tool_defs(choices: Optional[ToolChoices] = None):
    # Build tool list based on selected choices. Defaults handled in run_with_search.
    enabled: set[str] = set()
    if choices is not None:
        for c in choices:
            try:
                enabled.add(c.value)
            except Exception:
                continue
    else:
        choices = [x for x in ToolSet]

    tools: List[Dict[str, Any]] = []

    # Conditionally add DDG web search
    if ToolSet.WEB_SEARCH in choices:
        tools.append({
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
        })

    # Conditionally add DDG news search
    if ToolSet.NEWS_SEARCH in choices:
        tools.append({
            "type": "function",
            "name": "ddg_news_search",
            "description": "Search DuckDuckGo News for a query and return relevant news links.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "News search query"},
                    "max_results": {"type": ["integer", "null"], "minimum": 1, "maximum": 25, "default": 5},
                },
                "required": ["query", "max_results"],
                "additionalProperties": False,
            },
        })

    # If any external web tool is enabled (web or news), also enable fetch_url
    if ToolSet.WEB_SEARCH in choices or ToolSet.NEWS_SEARCH in choices:
        tools.append({
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
        })

    # Conditionally add internal search
    if ToolSet.INTERNAL_SEARCH in choices:
        tools.append({
            "type": "function",
            "name": "internal_search",
            "description": "Search our in-house knowledge base for articles and claims with optional date filtering (ISO YYYY-MM-DD). If this tool is available, you are expected to use it at least once for the current task.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search text"},
                    "max_articles": {"type": ["integer", "null"], "minimum": 1, "maximum": 50, "default": 10},
                    "max_claims": {"type": ["integer", "null"], "minimum": 1, "maximum": 100, "default": 20},
                    "start_date": {"type": ["string", "null"], "description": "Earliest article/claim date (YYYY-MM-DD)"},
                    "end_date": {"type": ["string", "null"], "description": "Latest article/claim date (YYYY-MM-DD)"},
                },
                "required": ["query", "max_articles", "max_claims"],
                "additionalProperties": False,
            },
        })

    return tools

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
For tools prefixed with "ddg_", you have the ability to use modifiers on your query strings:
- You can exclude specific websites by appending ' -site:example.com' to your query.
- You can specify exact phrases by enclosing them in double quotes. (Ex. climate change "botswana")
- You can specify "filetype:..." to filter results by file type. (Ex. filetype:pdf)
In all matters, you must follow the stances and standards of The Follow Up News (thefollowup.ai):
 - Strictly avoid untrustworthy, biased, or low-quality sources.
     - NY Post, Washington Times, Grokipedia, Times of Israel, Hindustan Times, and similar sources are to be considered low-quality and prone to manipulation; avoid using them.
 - Prioritize factual accuracy, neutrality, and balanced perspectives above all.
 - Expect all media to be subject to manipulation as to the incentives of the source, and operate accordingly.
 - Only expect truth when it aligns with incentives; otherwise, treat with skepticism.
    - Ex: The Department of State can be expected to be truthful when discussing neutral or politically favorable topics, but not when discussing politically sensitive topics that may reflect poorly on the US government.
 - Viewpoints; While The Follow Up as a general rule is strictly neutral and fact-driven, in certain specific matters it takes a strong stance:
    - It strongly opposes Israel's occupation of Palestinian territories, strongly supports the rights of Palestinians to human rights and the full return of Palestinian land.
    - It strongly opposes the Russian invasion of Ukraine and supports Ukrainian sovereignty.
    - It strongly opposes misinformation, disinformation, and deceptive practices in media and politics.
    - It is always critical of corporate influence in media and politics, and all interactions between the business world and the government.
    - It is always critical of all parties operating in the government- trusting them only to do and say things that align with their incentives. The truth can only be expected when it aligns with their incentives.
 - Always present the facts as accurately as possible in good faith, even if inconvenient to the stances of The Follow Up.
 - The Follow Up primarily concerns itself with 
The viewpoints and stances must be strictly adhered to, but do not need to be explicitly mentioned in your final output.
"""

def run_with_search(
    input_text: str,
    model: str = "gpt-5-mini",
    text_format: Optional[Union[type[BaseModel], BaseModel]]  = None,
    task_system: Optional[str] = None,
    tool_choices: Optional[ToolChoices] = None,
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
        # Default tools: WEB_SEARCH and NEWS_SEARCH if none provided
        if tool_choices is None:
            tool_choices = [ToolSet.WEB_SEARCH, ToolSet.NEWS_SEARCH]
        tools = _tool_defs(tool_choices)
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