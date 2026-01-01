# util/scrape_utils.py

import os
import sys
import datetime
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

import requests
import logging
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from email.utils import parsedate_to_datetime
from rss_parser import RSSParser, AtomParser
try:
    from playwright.sync_api import sync_playwright
except Exception:
    sync_playwright = None

_service_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

from models import LinkAggregationStep, LinkAggregationResult
from functools import cache

def read_rss_feed(
    url: str,
    timeout: int = 20,
    headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """
    Read an RSS/Atom feed and return a normalized list of items.

    This is intentionally site-agnostic; scrapers can layer on date filtering,
    tagging, and deduplication.

    Returned dict keys:
      - title: str
      - link: str
      - published: Optional[datetime.datetime]
      - summary: str
    """
    # hdrs = {
    #     "User-Agent": "Mozilla/5.0 (compatible; TheFollowUpBot/1.0)",
    #     "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
    # }
    logger = logging.getLogger(__name__)

    # Default headers; user-agent helps some sites avoid slow responses or blocks
    hdrs = {
        "User-Agent": "Mozilla/5.0 (compatible; TheFollowUpBot/1.0)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
    }
    if headers:
        hdrs.update(headers)

    # Create a session with retries to handle transient network issues/timeouts.
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "HEAD"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    # Try a few header profiles if the default request times out or is blocked.
    header_profiles = []
    # 1) default "bot" headers (above)
    header_profiles.append(hdrs)
    # 2) Postman-like headers (useful if Postman succeeds)
    header_profiles.append({
        "User-Agent": "PostmanRuntime/7.32.4",
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    })
    # 3) Common browser headers
    header_profiles.append({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    })

    # Use tuple timeout: (connect_timeout, read_timeout) to fail fast on connects
    connect_timeout = 5
    read_timeout = timeout

    last_exc = None
    for idx, prof in enumerate(header_profiles, start=1):
        try:
            resp = session.get(url, headers=prof, timeout=(connect_timeout, read_timeout), allow_redirects=True)
            # Log quick diagnostics
            try:
                elapsed = resp.elapsed.total_seconds()
            except Exception:
                elapsed = None
            logger.info("read_rss_feed: attempt=%d url=%s status=%s elapsed=%s headers_profile=%s", idx, url, resp.status_code, elapsed, prof.get("User-Agent"))
            resp.raise_for_status()
            text = resp.text
            break
        except requests.exceptions.ReadTimeout as e:
            logger.warning("read_rss_feed: read timeout on profile %d (%s): %s", idx, prof.get("User-Agent"), e)
            last_exc = e
            continue
        except requests.exceptions.RequestException as e:
            logger.warning("read_rss_feed: request exception on profile %d (%s): %s", idx, prof.get("User-Agent"), e)
            last_exc = e
            continue

    else:
        # All profiles exhausted
        logger.warning("read_rss_feed: all header profiles failed for %s; last_exc=%s", url, last_exc)
        return []

    def _unwrap_tag(val: Any) -> str:
        # rss_parser Tag types or nested models may expose content, or be simple strings.
        if val is None:
            return ""
        if isinstance(val, str):
            return val
        if hasattr(val, "content"):
            try:
                return val.content or ""
            except Exception:
                pass
        if isinstance(val, dict):
            return val.get("#text") or val.get("text") or ""
        try:
            return str(val)
        except Exception:
            return ""

    def _to_datetime(raw: Any) -> Optional[datetime.datetime]:
        if raw is None:
            return None
        if isinstance(raw, datetime.datetime):
            return raw
        try:
            if isinstance(raw, str):
                try:
                    return datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except Exception:
                    pass
                try:
                    return parsedate_to_datetime(raw)
                except Exception:
                    return None
        except Exception:
            return None

    items: List[Dict[str, Any]] = []

    # Try RSSParser first
    try:
        rss = RSSParser.parse(text)
        channel = getattr(rss, "channel", None)
        rss_items = []
        if channel is not None and getattr(channel, "items", None):
            rss_items = list(channel.items)
        if rss_items:
            for it in rss_items:
                title = _unwrap_tag(getattr(it, "title", None))
                link = _unwrap_tag(getattr(it, "link", None))
                # Some rss_parser models place link as a list or a Tag wrapper
                if not link:
                    guid = getattr(it, "guid", None)
                    link = _unwrap_tag(guid)

                pub_dt = _to_datetime(getattr(it, "pubDate", None) or getattr(it, "pubdate", None) or getattr(it, "dc_date", None) or getattr(it, "date", None))
                if not pub_dt:
                    try:
                        pub_dt = _to_datetime(it.content.pub_date.content)
                        # If has timezone, convert to local
                        if pub_dt and pub_dt.tzinfo is not None:
                            pub_dt = pub_dt.astimezone(datetime.timezone.utc).astimezone()
                    except:
                        continue
                # description/content
                summary = _unwrap_tag(getattr(it, "content", None) or getattr(it, "description", None) or getattr(it, "summary", None))

                if title and link:
                    items.append({"title": title, "link": link, "published": pub_dt, "summary": summary})
            return items
    except Exception:
        # Fall back to Atom parsing below
        pass

    # Try Atom
    try:
        atom = AtomParser.parse(text)
        entries = getattr(atom, "entries", None) or getattr(atom, "feed", None) and getattr(atom.feed, "entries", None) or []
        if entries:
            for ent in entries:
                title = _unwrap_tag(getattr(ent, "title", None))

                # Atom links may be list-like or models with href
                link_val = getattr(ent, "link", None)
                link = ""
                if link_val:
                    if isinstance(link_val, str):
                        link = link_val
                    elif isinstance(link_val, (list, tuple)):
                        # prefer alternate rel or first available
                        chosen = None
                        for l in link_val:
                            if getattr(l, "rel", None) == "alternate" or (hasattr(l, "rel") and (getattr(l, "rel") or "").lower() == "alternate"):
                                chosen = l
                                break
                        chosen = chosen or link_val[0]
                        link = _unwrap_tag(getattr(chosen, "href", None) or chosen)
                    else:
                        link = _unwrap_tag(getattr(link_val, "href", None) or link_val)

                pub_dt = _to_datetime(getattr(ent, "published", None) or getattr(ent, "updated", None))
                summary = _unwrap_tag(getattr(ent, "content", None) or getattr(ent, "summary", None) or getattr(ent, "description", None))

                if title and link:
                    items.append({"title": title, "link": link, "published": pub_dt, "summary": summary})
            return items
    except Exception:
        pass

    # As a last resort, return an empty list
    return items


def iter_scrape(
    url_template: str,
    start_page: int,
    date: datetime.date,
    scrape_fn: Callable[[str, datetime.datetime], LinkAggregationStep],
) -> LinkAggregationResult:
    i = start_page
    look_further = True
    results = []
    while look_further:
        url = url_template.replace("{{PAGE}}", str(i))
        result = scrape_fn(url, date)
        results.append(result)
        if not result.look_further or len(result.articles) == 0:
            break
        i += 1
    return LinkAggregationResult.from_steps(results)

@cache
def playwright_get(url: str, timeout: int = 20, headers: Optional[Dict[str, str]] = None, try_requests: Literal['first', 'last', 'dont', 'default'] = 'default'):
    """Try a few requests header profiles, then fall back to Playwright to render JS.

    Returns an object with `.content` (bytes), `.status_code` and `.raise_for_status()`.
    """
    logger = logging.getLogger(__name__)

    hdrs = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if headers:
        hdrs.update(headers)

    if try_requests == 'default':
        playwright_domains = [
            "state.gov",
            "defense.gov",
        ]
        requests_domains = [
            
        ]
        try_requests = 'last' if any(x in url for x in playwright_domains) else 'first'
        try_requests = 'first' if any(x in url for x in requests_domains) else try_requests
        
    
    # Define request logic
    def _try_requests():
        session = requests.Session()
        retry_strategy = Retry(total=2, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",), raise_on_status=False)
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        profiles = [{}, hdrs, {"User-Agent": "PostmanRuntime/7.32.4"}, {"User-Agent": hdrs["User-Agent"], "Accept-Language": "en-US,en;q=0.9"}]
        last_exc = None
        for prof in profiles:
            try:
                resp = session.get(url, headers=prof, timeout=(5, timeout), allow_redirects=True)
                logger.info("playwright_get: tried requests profile=%s status=%s url=%s", prof.get("User-Agent"), getattr(resp, "status_code", None), url)
                if getattr(resp, "status_code", None):
                    resp.raise_for_status()
                    return resp
                last_exc = resp
            except requests.RequestException as e:
                logger.warning("playwright_get: requests profile failed %s: %s", prof.get("User-Agent"), e)
                last_exc = e
        return last_exc

    # Define Playwright logic
    def _do_playwright():
        if sync_playwright is None:
            raise RuntimeError("playwright_get: Playwright is not installed; install with `pip install playwright` and run `python -m playwright install chromium`")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({k.lower(): v for k, v in hdrs.items()})
            page.goto(url, wait_until="networkidle", timeout=20000)
            html = page.content()
            browser.close()
        class _Resp:
            def __init__(self, text: str):
                self.content = text.encode("utf-8")
                self.status_code = 200
            def raise_for_status(self):
                return None
        logger.info("playwright_get: fetched with Playwright %s", url)
        return _Resp(html)

    # Control flow based on try_requests
    if try_requests == 'first':
        result = _try_requests()
        if hasattr(result, 'status_code'):
            return result
        return _do_playwright()
    elif try_requests == 'last':
        try:
            return _do_playwright()
        except Exception:
            result = _try_requests()
            if hasattr(result, 'status_code'):
                return result
            raise RuntimeError(f"playwright_get: both Playwright and requests failed; last exception={result}")
    elif try_requests == 'dont':
        return _do_playwright()
    else:
        raise ValueError(f"playwright_get: invalid try_requests value: {try_requests}")

if __name__ == "__main__":
    resp = playwright_get('https://www.war.gov/News/News-Stories/Article/Article/4369500/army-surgery-resident-develops-groundbreaking-life-support-system-named-to-forb/')
    print(resp)