import os
import sys
import datetime
import logging
import re
import tempfile
import subprocess
import shutil
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode

import requests
from bs4 import BeautifulSoup

# Ensure service root is on sys.path (mirrors existing scraper layout)
_service_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

from models import ArticleLink, LinkAggregationStep, LinkAggregationResult
import util.scrape_utils as SU

LOGGER = logging.getLogger(__name__)

AGENCY_TAG = "Agency // Federal Trade Commission"

FEEDS: List[Tuple[str, str]] = [
    ("https://www.ftc.gov/feeds/press-release.xml", "Press Release"),
    ("https://www.ftc.gov/feeds/press-release-competition.xml", "Press Release (Competition)"),
    ("https://www.ftc.gov/feeds/press-release-consumer-protection.xml", "Press Release (Consumer Protection)"),
]

UA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TheFollowUpBot/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _to_date(dt: Optional[datetime.datetime]) -> Optional[datetime.date]:
    if not dt:
        return None
    try:
        if dt.tzinfo is not None:
            return dt.astimezone(datetime.timezone.utc).date()
        return dt.date()
    except Exception:
        return None


def _canonicalize_url(url: str) -> str:
    """Deduplicate aggressively: strip fragment + common tracking params."""
    url = (url or "").strip()
    if not url:
        return ""
    try:
        p = urlparse(url)
        q = parse_qsl(p.query, keep_blank_values=True)

        drop_prefixes = ("utm_",)
        drop_keys = {
            "fbclid",
            "gclid",
            "mc_cid",
            "mc_eid",
            "mkt_tok",
            "ref",
            "cmpid",
            "cid",
            "src",
        }
        q2 = []
        for k, v in q:
            lk = (k or "").lower()
            if any(lk.startswith(pref) for pref in drop_prefixes):
                continue
            if lk in drop_keys:
                continue
            q2.append((k, v))

        p2 = p._replace(query=urlencode(q2, doseq=True), fragment="")
        return urlunparse(p2)
    except Exception:
        return url


def _fetch_html(url: str) -> str:
    """Fetch HTML (requests and/or playwright fallback via shared util)."""
    try:
        resp = SU.playwright_get(url, timeout=30, headers=UA_HEADERS)
        resp.raise_for_status()
        return resp.content.decode("utf-8", errors="replace")
    except Exception as e:
        LOGGER.warning("FTC: failed to fetch html url=%s err=%s", url, e)
        return ""


def _extract_main_html(html: str) -> str:
    """Best-effort content region extraction for FTC pages."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")

    main = soup.find("main") or soup.find("article") or soup.find("div", attrs={"role": "main"}) or soup.body
    if not main:
        return str(soup)

    # Light cleanup inside the chosen container.
    for tag in main.find_all(["script", "style", "noscript"]):
        try:
            tag.decompose()
        except Exception:
            pass
    for tag in main.find_all(["header", "footer", "nav", "aside", "form"]):
        try:
            tag.decompose()
        except Exception:
            pass

    return str(main)


_ATTACH_EXT_RE = re.compile(r"\.(pdf|docx?|pptx?|xlsx?|csv|txt)$", re.IGNORECASE)


def _find_attachments_from_html(html: str, base_url: str) -> List[Tuple[str, str]]:
    """
    Return list of (title, absolute_url) for likely attachment files.
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out: List[Tuple[str, str]] = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        abs_url = urljoin(base_url, href)
        if not abs_url:
            continue

        # Heuristic: file extension or explicit download-ish URLs
        if _ATTACH_EXT_RE.search(abs_url) or "/files/" in abs_url or "/system/files/" in abs_url:
            title = a.get_text(" ", strip=True) or os.path.basename(urlparse(abs_url).path) or "Attachment"
            key = _canonicalize_url(abs_url)
            if key in seen:
                continue
            seen.add(key)
            out.append((title, abs_url))

    return out


def _download_bytes(url: str, timeout: int = 40, max_bytes: int = 25 * 1024 * 1024) -> Optional[bytes]:
    try:
        with requests.get(url, headers=UA_HEADERS, timeout=timeout, allow_redirects=True, stream=True) as r:
            r.raise_for_status()
            chunks = []
            total = 0
            for chunk in r.iter_content(chunk_size=1024 * 64):
                if not chunk:
                    continue
                chunks.append(chunk)
                total += len(chunk)
                if total > max_bytes:
                    LOGGER.warning("FTC: attachment too large, skipping url=%s bytes=%d", url, total)
                    return None
            return b"".join(chunks)
    except Exception as e:
        LOGGER.warning("FTC: failed to download attachment url=%s err=%s", url, e)
        return None


def _convert_with_markitdown(file_path: str) -> str:
    """
    Convert a downloaded attachment to markdown/text using markitdown if available.
    We try:
      1) Python library 'markitdown' (if present in runtime)
      2) CLI 'markitdown' (if present in PATH)
    Returns empty string if conversion fails.
    """
    # 1) Python library
    try:
        from markitdown import MarkItDown  # type: ignore

        md = MarkItDown()
        res = md.convert(file_path)

        # Be flexible about return shape
        if isinstance(res, str):
            return res
        for attr in ("text_content", "markdown", "text", "content"):
            if hasattr(res, attr):
                val = getattr(res, attr)
                if isinstance(val, str) and val.strip():
                    return val
        return str(res) if res is not None else ""
    except Exception:
        pass

    # 2) CLI
    try:
        exe = shutil.which("markitdown")
        if not exe:
            return ""
        out = subprocess.check_output([exe, file_path], stderr=subprocess.STDOUT, text=True)
        return out or ""
    except Exception:
        return ""


def _attachments_to_markdown(attachments: List[Tuple[str, str]]) -> str:
    """
    Download attachments and concatenate their markitdown outputs with headings.
    """
    parts: List[str] = []
    for title, url in attachments:
        b = _download_bytes(url)
        if not b:
            continue

        # Make an extension-preserving temp file so converters can infer type.
        suffix = os.path.splitext(urlparse(url).path)[1] or ""
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
                f.write(b)
                tmp_path = f.name
        except Exception:
            continue

        try:
            converted = _convert_with_markitdown(tmp_path).strip()
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

        if not converted:
            continue

        safe_title = title.strip() if title else "Attachment"
        parts.append(f"# {safe_title}\n\n{converted}\n")

    return "\n\n".join(parts).strip()


def _build_article_raw_content(article_url: str, rss_summary: str) -> str:
    """
    Policy:
      - If files are attached on the page, process them with markitdown and concatenate.
      - If not, only then fetch and extract text/html from the article page.
      - If all else fails, fall back to RSS summary.
    """
    html = _fetch_html(article_url)
    if html:
        attachments = _find_attachments_from_html(html, base_url=article_url)
        if attachments:
            md = _attachments_to_markdown(attachments)
            if md:
                return md
            # If attachments exist but conversion fails, fall back to page extraction.
        extracted = _extract_main_html(html)
        if extracted:
            return extracted

    return (rss_summary or "").strip()


def _add_or_merge(by_link: Dict[str, ArticleLink], art: ArticleLink) -> None:
    """
    Deduplicate by canonical link; if duplicate, merge tags (stable order).
    """
    if art.link in by_link:
        existing = by_link[art.link]
        merged = list(dict.fromkeys((existing.tags or []) + (art.tags or [])))
        try:
            by_link[art.link] = existing.model_copy(update={"tags": merged})
        except Exception:
            by_link[art.link] = existing.copy(update={"tags": merged})
        return
    by_link[art.link] = art


def scrape(date: datetime.date) -> LinkAggregationResult:
    """
    Scrape FTC press release RSS feeds (general + competition + consumer protection),
    filter to items published on `date`, and deduplicate across feeds.
    """
    logger = LOGGER
    logger.info("FTC RSS scrape date=%s feeds=%d", date.isoformat(), len(FEEDS))

    by_link: Dict[str, ArticleLink] = {}

    for feed_url, feed_tag in FEEDS:
        items = SU.read_rss_feed(feed_url)
        logger.info("FTC RSS: %s -> %d items", feed_url, len(items))

        # Feeds are typically newest-first; once we pass older than target date, we can stop scanning this feed.
        for it in items:
            title = (it.get("title") or "").strip()
            link_raw = (it.get("link") or "").strip()
            if not title or not link_raw:
                continue

            pub_date = _to_date(it.get("published"))
            if pub_date and pub_date > date:
                continue
            if pub_date and pub_date < date:
                break  # older than target; stop this feed early

            if pub_date and pub_date != date:
                continue

            link = _canonicalize_url(link_raw)
            if not link:
                continue

            summary = (it.get("summary") or "").strip()
            raw = _build_article_raw_content(link, summary)

            art = ArticleLink(
                title=title,
                link=link,
                date=pub_date or date,
                tags=[AGENCY_TAG, feed_tag],
                raw_content=raw,
                process_posturing=True,
            )
            _add_or_merge(by_link, art)

    articles = sorted(by_link.values(), key=lambda a: (a.date, a.title), reverse=True)
    step = LinkAggregationStep(articles=articles, look_further=False)
    logger.info("FTC RSS: returning %d deduped articles for %s", len(articles), date.isoformat())
    return LinkAggregationResult.from_steps([step])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    d = datetime.date(2025, 12, 22)
    print(scrape(d))
