import os
import sys
import re
import datetime
import logging
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

# Keep consistent with other scrapers: add service root to path so we can import models + utils.
_service_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

from models import ArticleLink, LinkAggregationResult, LinkAggregationStep
import util.scrape_utils as SU  # noqa: F401  (kept for consistency with other scrapers)

LOGGER = logging.getLogger(__name__)

BASE = "https://www.fhfa.gov"
AGENCY_TAG = "Agency // Federal Housing Finance"

UA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TheFollowUpBot/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

MONTH_DATE_RE = re.compile(
    r"\b("
    r"January|February|March|April|May|June|July|August|September|October|November|December"
    r")\s+\d{1,2},\s+\d{4}\b"
)
SLASH_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b")


# -------------------------
# Networking / soup
# -------------------------

def _get(url: str, timeout: int = 30) -> requests.Response:
    resp = requests.get(url, headers=UA_HEADERS, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return resp


def _fetch_soup(url: str) -> BeautifulSoup:
    return BeautifulSoup(_get(url).content, "html.parser")


def _abs_url(href: str) -> str:
    return urljoin(BASE, (href or "").strip())


# -------------------------
# Date parsing
# -------------------------

def _parse_date_str(s: str) -> Optional[datetime.date]:
    s = (s or "").strip()
    if not s:
        return None

    # Common list format: "December 23, 2025"
    try:
        return datetime.datetime.strptime(s, "%B %d, %Y").date()
    except Exception:
        pass

    # Common detail format: "12/23/2025"
    try:
        return datetime.datetime.strptime(s, "%m/%d/%Y").date()
    except Exception:
        pass

    # ISO-ish in datetime attrs
    try:
        s2 = s.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(s2).date()
    except Exception:
        return None


def _find_date_near(node: Tag, max_ancestor_hops: int = 6) -> Optional[datetime.date]:
    """Find a publish date near a link node by scanning nearby <time> or text."""
    cur: Optional[Tag] = node
    hops = 0

    while cur is not None and hops <= max_ancestor_hops:
        # 1) Prefer a <time> tag.
        t = cur.find("time")
        if t is not None:
            dt_attr = (t.get("datetime") or "").strip()
            if dt_attr:
                dt = _parse_date_str(dt_attr)
                if dt:
                    return dt
            dt_text = t.get_text(" ", strip=True)
            dt = _parse_date_str(dt_text)
            if dt:
                return dt

        # 2) Search for a month-name date in visible text.
        txt = cur.get_text(" ", strip=True)
        m = MONTH_DATE_RE.search(txt)
        if m:
            dt = _parse_date_str(m.group(0))
            if dt:
                return dt

        # 3) Fallback: slash date.
        m = SLASH_DATE_RE.search(txt)
        if m:
            dt = _parse_date_str(m.group(0))
            if dt:
                return dt

        cur = cur.parent if isinstance(cur.parent, Tag) else None
        hops += 1

    return None


# -------------------------
# Content extraction
# -------------------------

def _extract_article(url: str) -> str:
    """Best-effort extraction of the main article HTML."""
    soup = _fetch_soup(url)

    main = soup.find("main") or soup.find("article") or soup.find("div", attrs={"role": "main"})
    if not main:
        main = soup.body or soup

    # Light cleanup within the chosen region
    for tag_name in ["script", "style", "noscript"]:
        for t in main.find_all(tag_name):
            t.decompose()

    for sel in ["header", "footer", "nav", "aside", "form"]:
        for t in main.find_all(sel):
            t.decompose()

    return str(main)


# -------------------------
# Listing parsing
# -------------------------

def _is_item_link(href: str, slug: str) -> bool:
    """Return True if href looks like a listing item link for the given slug."""
    if not href:
        return False

    parsed = urlparse(href)
    path = parsed.path or ""

    # Must start with /news/<slug>/... (detail pages)
    prefix = f"/news/{slug}/"
    if not path.startswith(prefix):
        return False

    # Exclude /news/<slug>/ with no trailing segment
    if path.rstrip("/") == f"/news/{slug}":
        return False

    return True


def _has_next_page(soup: BeautifulSoup) -> bool:
    if soup.select_one('a[rel="next"]'):
        return True

    for a in soup.select("a"):
        txt = (a.get_text(" ", strip=True) or "").lower()
        if txt == "next" or txt.endswith(" next"):
            return True
        aria = (a.get("aria-label") or "").lower()
        if "next" in aria:
            return True
    return False


def _scrape_listing_page(url: str, scrape_date: datetime.date, slug: str, kind_label: str) -> Tuple[LinkAggregationStep, bool]:
    """Scrape one FHFA listing page.

    Returns (step, stop_pagination) where stop_pagination becomes True once we see an item older than scrape_date.
    """
    soup = _fetch_soup(url)
    LOGGER.info("Scraped FHFA listing page: %s", url)

    seen_links: set[str] = set()
    articles: List[ArticleLink] = []
    stop_pagination = False

    anchors = soup.find_all("a", href=True)
    LOGGER.info("Found %d anchors on %s", len(anchors), url)

    for a in anchors:
        href = (a.get("href") or "").strip()
        if not _is_item_link(href, slug):
            continue

        title = a.get_text(" ", strip=True)
        if not title or len(title) < 3:
            continue

        link = _abs_url(href)
        if link in seen_links:
            continue
        seen_links.add(link)

        item_date = _find_date_near(a)
        if not item_date:
            continue

        # Listing is reverse chronological: ignore newer, stop once older than target.
        if item_date > scrape_date:
            continue
        if item_date < scrape_date:
            stop_pagination = True
            break

        articles.append(
            ArticleLink(
                title=title,
                link=link,
                date=item_date,
                tags=[AGENCY_TAG, kind_label],
                process_posturing=True,
                raw_content=_extract_article(link),
            )
        )

    look_further = bool(articles) and (not stop_pagination) and _has_next_page(soup)
    return LinkAggregationStep(articles=articles, look_further=look_further), stop_pagination


# -------------------------
# Public entrypoint
# -------------------------

SOURCES: List[Tuple[str, str]] = [
    ("news-release", "News Release"),
    ("speech", "Speech"),
    ("statement", "Statement"),
    ("testimony", "Testimony"),
    ("fact-sheet", "Fact Sheet"),
]


def scrape(date: datetime.date) -> LinkAggregationResult:
    """Scrape FHFA Public Affairs pages for a single target date."""
    steps: List[LinkAggregationStep] = []
    by_link: Dict[str, ArticleLink] = {}

    for slug, kind_label in SOURCES:
        page = 0
        while True:
            url = f"{BASE}/news/{slug}?page={page}"
            step, stop_pagination = _scrape_listing_page(url, date, slug, kind_label)
            steps.append(step)

            # Merge / dedupe across pages (and across sources, just in case).
            for art in step.articles:
                if art.link in by_link:
                    existing = by_link[art.link]
                    merged = list(dict.fromkeys((existing.tags or []) + (art.tags or [])))
                    by_link[art.link] = existing.model_copy(update={"tags": merged})
                else:
                    by_link[art.link] = art

            if stop_pagination or not step.articles or not step.look_further:
                break

            page += 1
            if page > 200:  # safety cap
                LOGGER.warning("FHFA pagination safety cap reached for slug=%s", slug)
                break

    articles = list(by_link.values())
    articles.sort(key=lambda a: (a.date, a.title), reverse=True)

    res = LinkAggregationResult.from_steps(steps)
    res.articles = articles
    return res


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_date = datetime.date.today() - datetime.timedelta(days=1)
    out = scrape(test_date)
    print(out)
