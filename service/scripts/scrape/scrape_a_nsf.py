# scrapers/scrape_nsf_releases.py

import os
import sys
import re
import datetime
import logging
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

# Ensure service root is importable (matches existing scraper layout)
_service_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

from models import ArticleLink, LinkAggregationStep, LinkAggregationResult
import util.scrape_utils as SU

LOG = logging.getLogger(__name__)

BASE = "https://www.nsf.gov"
# User requirement:
AGENCY_TAG = "Agency // National Science Foundation"

# Filtered releases page the user provided, with pagination appended
LIST_URL_TEMPLATE = (
    "https://www.nsf.gov/news/releases"
    "?f%5B0%5D=news_type%3ANSF%20News"
    "&page={{PAGE}}"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TheFollowUpBot/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Date like "December 17, 2025" anywhere in text
_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
)
_DATE_RE = re.compile(rf"\b(?:{_MONTHS})\s+\d{{1,2}},\s+\d{{4}}\b")


def _abs_url(href: str) -> str:
    href = (href or "").strip()
    if not href:
        return ""
    return urljoin(BASE, href)


def _parse_date_text(txt: str) -> datetime.date | None:
    txt = (txt or "").strip()
    if not txt:
        return None
    # Normalize whitespace
    txt = re.sub(r"\s+", " ", txt)
    try:
        return datetime.datetime.strptime(txt, "%B %d, %Y").date()
    except Exception:
        return None


def _date_from_container(node) -> datetime.date | None:
    """
    Try to find a publication date inside an item container.
    Prefer <time datetime="...">, otherwise scan for "Month D, YYYY".
    """
    if not node:
        return None

    # 1) <time datetime="...">
    t = node.find("time")
    if t:
        dt_attr = (t.get("datetime") or "").strip()
        if dt_attr:
            try:
                # Handle Z suffix if present
                dt_attr = dt_attr.replace("Z", "+00:00")
                return datetime.datetime.fromisoformat(dt_attr).date()
            except Exception:
                pass
        # 2) visible time text
        dt_txt = t.get_text(" ", strip=True)
        dt = _parse_date_text(dt_txt)
        if dt:
            return dt

    # 3) scan for Month Day, Year in the container text
    txt = node.get_text(" ", strip=True)
    m = _DATE_RE.search(txt or "")
    if m:
        return _parse_date_text(m.group(0))

    return None


def _is_article_link(href: str) -> bool:
    """
    Heuristic to keep us from pulling nav links.
    NSF article pages are usually under /news/<slug>.
    Exclude listing/landing pages like /news, /news/releases.
    """
    href = (href or "").strip()
    if not href:
        return False

    full = _abs_url(href)
    try:
        p = urlparse(full)
    except Exception:
        return False

    if p.netloc and "nsf.gov" not in p.netloc:
        return False

    path = (p.path or "").rstrip("/")
    if not path.startswith("/news/"):
        return False

    # Exclusions: not actual release items
    if path in ("/news", "/news/releases"):
        return False
    if path.startswith("/news/releases/"):
        return False

    # Most release items should be /news/<something>
    parts = [x for x in path.split("/") if x]
    return len(parts) >= 2  # e.g., ["news", "<slug>"]


def _fetch_soup(url: str) -> BeautifulSoup:
    """
    NSF pages often present a JS-required anti-bot interstitial to plain requests.
    Use SU.playwright_get with try_requests='last' so Playwright is attempted first.
    (Avoid SU.playwright_get default mode due to its current 'default' routing behavior.)
    """
    resp = SU.playwright_get(url, timeout=30, headers=HEADERS, try_requests="last")
    resp.raise_for_status()
    return BeautifulSoup(resp.content, "html.parser")


def _extract_article(url: str) -> str:
    """
    Fetch an NSF release and return main content HTML.
    Best-effort: <main> or <article> or body.
    """
    try:
        soup = _fetch_soup(url)
    except Exception:
        return ""

    main = soup.find("main") or soup.find("article") or soup.body or soup
    if not main:
        return ""

    # Light cleanup of obvious non-content
    for tag in main.find_all(["script", "style", "noscript"]):
        try:
            tag.decompose()
        except Exception:
            pass
    for sel in ["nav", "header", "footer", "aside", "form"]:
        for tag in main.find_all(sel):
            try:
                tag.decompose()
            except Exception:
                pass

    return str(main)


def _candidate_containers(soup: BeautifulSoup):
    """
    Try common Drupal/view containers first; fall back to generic.
    """
    # Drupal-ish listing containers
    for sel in [
        "div.view-content article",
        "div.view-content div.views-row",
        "div.views-row",
        "article",
        "li",
    ]:
        nodes = soup.select(sel)
        if nodes:
            return nodes
    return []


def _scrape_page(url: str, scrape_date: datetime.date) -> LinkAggregationStep:
    soup = _fetch_soup(url)
    LOG.info("Scraped NSF listing page: %s", url)

    containers = _candidate_containers(soup)
    LOG.info("NSF listing: %d candidate containers", len(containers))

    articles: list[ArticleLink] = []
    seen_links: set[str] = set()
    look_further = True

    for node in containers:
        # Find a plausible article link within this container
        a = None
        for candidate in node.find_all("a", href=True):
            if _is_article_link(candidate.get("href", "")):
                a = candidate
                break
        if not a:
            continue

        title = a.get_text(" ", strip=True)
        link = _abs_url(a.get("href", ""))
        if not title or not link or link in seen_links:
            continue

        dt = _date_from_container(node)
        if not dt:
            # Without a date, we can't reliably filter or paginate; skip.
            continue

        # Reverse chronological assumption: once we hit older than target date, stop paging.
        if dt < scrape_date:
            look_further = False
            break

        if dt != scrape_date:
            continue

        seen_links.add(link)
        articles.append(
            ArticleLink(
                title=title,
                link=link,
                date=dt,
                tags=[AGENCY_TAG],
                process_posturing=True,
                raw_content=_extract_article(link),
            )
        )

    LOG.info("Processed %d NSF articles from %s; look_further=%s", len(articles), url, look_further)
    return LinkAggregationStep(articles=articles, look_further=look_further)


def scrape(date: datetime.date) -> LinkAggregationResult:
    """
    Scrape NSF filtered releases list pages until we pass `date`.
    Pages are assumed to be zero-indexed via `page=0,1,2,...`.
    """
    res = SU.iter_scrape(LIST_URL_TEMPLATE, start_page=0, date=date, scrape_fn=_scrape_page)

    # Cross-page dedupe (iter_scrape aggregates blindly)
    uniq: list[ArticleLink] = []
    seen: set[str] = set()
    for a in res.articles or []:
        if a.link in seen:
            continue
        seen.add(a.link)
        uniq.append(a)
    res.articles = uniq
    return res


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Example: scrape yesterday
    d = datetime.date(2025, 12, 17)
    print(scrape(d))
