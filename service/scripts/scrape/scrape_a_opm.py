# scrapers/scrape_opm_news_releases.py

import os
import sys
import re
import datetime
import logging
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

# Ensure service root is importable (matches existing scraper layout)
_service_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

from models import ArticleLink, LinkAggregationStep, LinkAggregationResult
import util.scrape_utils as SU

LOG = logging.getLogger(__name__)

BASE_URL = "https://www.opm.gov"
LIST_URL = "https://www.opm.gov/news/news-releases/"

# Per request: all articles should carry this exact tag
AGENCY_TAG = "Agency // Personnel Management"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TheFollowUpBot/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Listing shows: "Date: December 15, 2025"
_DATE_RE = re.compile(r"\bDate\s*:\s*([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})\b", re.IGNORECASE)


def _abs_url(href: str) -> str:
    return urljoin(BASE_URL, (href or "").strip())


def _get(url: str, timeout: int = 30):
    """
    Requests-first fetch with a conservative Playwright fallback.
    (Some .gov properties occasionally apply bot heuristics.)
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        return resp
    except Exception as e:
        LOG.warning("requests failed for %s (%s); trying playwright_get fallback", url, e)
        # Important: pass an explicit try_requests value to avoid relying on defaults.
        resp2 = SU.playwright_get(url, timeout=timeout, headers=HEADERS, try_requests="first")
        resp2.raise_for_status()
        return resp2


def _fetch_soup(url: str) -> BeautifulSoup:
    resp = _get(url)
    return BeautifulSoup(resp.content, "html.parser")


def _parse_date_from_text(text: str) -> Optional[datetime.date]:
    txt = re.sub(r"\s+", " ", (text or "")).strip()
    m = _DATE_RE.search(txt)
    if not m:
        return None
    month, day, year = m.group(1), m.group(2), m.group(3)
    try:
        return datetime.datetime.strptime(f"{month} {int(day)}, {year}", "%B %d, %Y").date()
    except Exception:
        return None


def _find_latest_news_list(main: Tag) -> Optional[Tag]:
    """
    Locate the UL/OL following the 'Latest News' header. If not found,
    the caller can fall back to broader heuristics.
    """
    # Find an h2 whose text is "Latest News"
    latest_h2 = None
    for h2 in main.find_all(["h2", "h3"]):
        if h2.get_text(" ", strip=True).lower() == "latest news":
            latest_h2 = h2
            break
    if not latest_h2:
        return None

    # Walk forward to find the first UL/OL container
    for sib in latest_h2.next_siblings:
        if isinstance(sib, Tag):
            if sib.name in ("ul", "ol"):
                return sib
            ul = sib.find(["ul", "ol"])
            if ul:
                return ul
    return None


def _extract_article_content(url: str) -> str:
    """
    Best-effort extraction of an OPM news release page body.
    Prefer <main>, then <article>, then <body>.
    """
    soup = _fetch_soup(url)

    node = soup.find("main") or soup.find("article") or soup.find("body") or soup
    if not node:
        return ""

    # Remove obvious boilerplate inside the chosen region
    for t in node.find_all(["script", "style", "noscript"]):
        try:
            t.decompose()
        except Exception:
            pass

    # Light cleanup if present
    for sel in ["nav", "header", "footer", "form"]:
        for t in node.select(sel):
            try:
                t.decompose()
            except Exception:
                pass

    return str(node)


def _scrape_listing_for_date(scrape_date: datetime.date) -> LinkAggregationStep:
    soup = _fetch_soup(LIST_URL)
    LOG.info("Scraped %s", LIST_URL)

    main = soup.find("main") or soup
    container = _find_latest_news_list(main)

    # Prefer list items within the Latest News list.
    items: list[Tag] = []
    if container:
        items = container.find_all("li", recursive=False) or container.find_all("li")
    else:
        # Fallback: treat each h3 (with an internal news-releases link) as an item.
        # We’ll parse date from the nearest reasonable parent block.
        for h3 in main.find_all("h3"):
            a = h3.find("a", href=True)
            if not a:
                continue
            href = a.get("href", "").strip()
            if "/news/news-releases/" not in href:
                continue
            # Walk up to a plausible container (li or section/div)
            block = h3.find_parent(["li", "div", "section"]) or h3
            items.append(block)

    articles: list[ArticleLink] = []
    seen_links = set()

    # Listing is reverse chronological. Once we pass below the target date, we can stop.
    for it in items:
        a = it.select_one("h3 a[href]") or it.find("a", href=True)
        if not a:
            continue

        href = a.get("href", "").strip()
        if "/news/news-releases/" not in href:
            continue

        link = _abs_url(href)
        if not link or link.rstrip("/") == LIST_URL.rstrip("/"):
            continue

        title = a.get_text(" ", strip=True)
        if not title:
            continue

        text_blob = it.get_text(" ", strip=True)
        item_date = _parse_date_from_text(text_blob)
        if not item_date:
            # If the listing format changes, we require a date for the pipeline model.
            continue

        if item_date > scrape_date:
            continue
        if item_date < scrape_date:
            break

        if link in seen_links:
            continue
        seen_links.add(link)

        articles.append(
            ArticleLink(
                title=title,
                link=link,
                date=item_date,
                tags=[AGENCY_TAG],
                process_posturing=True,
                raw_content=_extract_article_content(link),
            )
        )

    return LinkAggregationStep(articles=articles, look_further=False)


def scrape(date: datetime.date) -> LinkAggregationResult:
    """
    Scrape OPM News Releases and return items published on `date`.
    The listing page does not appear to paginate; we treat it as a single-page feed.
    """
    step = _scrape_listing_for_date(date)
    LOG.info("Collected %d OPM news releases for %s", len(step.articles), date.isoformat())
    return LinkAggregationResult.from_steps([step])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Example: scrape a specific day
    d = datetime.date(2025, 12, 15)
    print(scrape(d))
