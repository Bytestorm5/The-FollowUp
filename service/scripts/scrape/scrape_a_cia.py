# scrapers/scrape_cia_press_releases_and_statements.py

import os
import sys
import re
import datetime
import logging
from typing import Optional, Tuple, Set
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# Ensure service root is importable (matches existing scraper pattern)
_service_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

from models import ArticleLink, LinkAggregationStep, LinkAggregationResult  # noqa: E402
import util.scrape_utils as SU  # noqa: E402

LOGGER = logging.getLogger(__name__)

BASE_URL = "https://www.cia.gov"
START_URL = "https://www.cia.gov/stories/press-releases-and-statements/"

# Requirement: every post from this source must always have this tag
SOURCE_TAG = "Agency // CIA"
SECTION_TAG = "Press Releases and Statements"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TheFollowUpBot/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Examples seen:
# "CIA’s Latest Declassified Documents Published October 7, 2025"
_PUBLISHED_RE = re.compile(
    r"^(?P<title>.*?)\s+Published\s+(?P<date>[A-Za-z]+\s+\d{1,2},\s+\d{4})\s*$"
)
_MONTH_DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}"
)


def _abs_url(href: str) -> str:
    return urljoin(BASE_URL, (href or "").strip())


def _get(url: str, timeout: int = 30) -> requests.Response:
    # Use requests directly (CIA pages are typically server-rendered).
    resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return resp


def _parse_date_str(date_str: str) -> Optional[datetime.date]:
    s = (date_str or "").strip()
    if not s:
        return None
    try:
        return datetime.datetime.strptime(s, "%B %d, %Y").date()
    except Exception:
        return None


def _extract_from_listing_anchor(a) -> Optional[Tuple[str, datetime.date]]:
    """
    Try to parse "TITLE Published Month Day, Year" from the anchor's visible text.
    Returns (title, date) or None.
    """
    txt = a.get_text(" ", strip=True)
    if not txt:
        return None

    m = _PUBLISHED_RE.match(txt)
    if m:
        title = (m.group("title") or "").strip()
        d = _parse_date_str(m.group("date"))
        if title and d:
            return title, d

    # Fallback: find a month-date anywhere in the anchor text; assume remainder is title.
    m2 = _MONTH_DATE_RE.search(txt)
    if m2:
        d = _parse_date_str(m2.group(0))
        if d:
            # Heuristic: title is everything before the date match, minus trailing "Published"
            title_part = txt[: m2.start()].strip()
            title_part = re.sub(r"\bPublished\s*$", "", title_part).strip()
            if title_part:
                return title_part, d

    return None


def _find_next_page_url(soup: BeautifulSoup, current_url: str) -> Optional[str]:
    """
    Best-effort "next page" discovery:
      - <link rel="next" href="...">
      - <a rel="next" href="...">
      - <a aria-label*="Next" href="...">
      - <a>Next</a> (or contains "Next Page")
    """
    # <link rel="next">
    ln = soup.find("link", rel=lambda v: v and "next" in v)
    if ln and ln.get("href"):
        return urljoin(current_url, ln["href"])

    # <a rel="next">
    a = soup.find("a", rel=lambda v: v and "next" in v)
    if a and a.get("href"):
        return urljoin(current_url, a["href"])

    # aria-label includes "Next"
    a = soup.find("a", attrs={"aria-label": re.compile(r"\bnext\b", re.I)})
    if a and a.get("href"):
        return urljoin(current_url, a["href"])

    # Text-based
    for cand in soup.find_all("a", href=True):
        t = cand.get_text(" ", strip=True)
        if not t:
            continue
        if re.search(r"\bnext\b", t, re.I) or re.search(r"\bnext page\b", t, re.I):
            return urljoin(current_url, cand["href"])

    return None


def _extract_article_content(url: str) -> str:
    """
    Best-effort content extraction:
      - Prefer <main>, else <article>, else body.
      - Remove obvious noise tags within extracted node.
    """
    try:
        resp = _get(url, timeout=30)
        soup = BeautifulSoup(resp.content, "html.parser")
    except Exception as e:
        LOGGER.warning("CIA extract failed url=%s err=%s", url, e)
        return ""

    root = soup.find("main") or soup.find("article") or soup.body or soup
    if not root:
        return ""

    for tag in root.find_all(["script", "style", "noscript"]):
        try:
            tag.decompose()
        except Exception:
            pass

    # Light cleanup (keep conservative)
    for sel in ["nav", "header", "footer"]:
        for n in root.select(sel):
            try:
                n.decompose()
            except Exception:
                pass

    return str(root)


def _scrape_page(url: str, scrape_date: datetime.date) -> Tuple[LinkAggregationStep, Optional[str]]:
    resp = _get(url, timeout=30)
    soup = BeautifulSoup(resp.content, "html.parser")
    LOGGER.info("Scraped CIA listing page: %s", url)

    main = soup.find("main") or soup
    anchors = [
        a for a in main.find_all("a", href=True)
        if "/stories/story/" in (a.get("href") or "")
    ]
    LOGGER.info("Found %d candidate story anchors on %s", len(anchors), url)

    articles = []
    seen_links: Set[str] = set()
    encountered_older = False
    any_dates: list[datetime.date] = []

    # Listing is newest-first. We:
    # - ignore items newer than scrape_date
    # - collect items matching scrape_date
    # - once we see an older item, stop scanning and stop pagination
    for a in anchors:
        href = a.get("href") or ""
        link = _abs_url(href)
        if not link or link in seen_links:
            continue

        parsed = _extract_from_listing_anchor(a)
        if not parsed:
            continue

        title, item_date = parsed
        any_dates.append(item_date)

        if item_date > scrape_date:
            continue

        if item_date < scrape_date:
            encountered_older = True
            break

        # item_date == scrape_date
        seen_links.add(link)

        articles.append(
            ArticleLink(
                title=title,
                link=link,
                date=item_date,
                tags=[SOURCE_TAG, SECTION_TAG],
                process_posturing=True,
                raw_content=_extract_article_content(link),
            )
        )

    next_url = _find_next_page_url(soup, url)

    # Decide whether to keep paging:
    # - If we encountered older-than-target, stop.
    # - Else if min date on page is still >= target and there's a next URL, keep going.
    look_further = False
    if not encountered_older and next_url:
        if any_dates:
            if min(any_dates) >= scrape_date:
                look_further = True
        else:
            # If we failed to parse any dates, don't loop forever.
            look_further = False

    step = LinkAggregationStep(articles=articles, look_further=look_further)
    LOGGER.info(
        "CIA page processed: url=%s date=%s articles=%d look_further=%s next=%s",
        url,
        scrape_date.isoformat(),
        len(articles),
        look_further,
        next_url,
    )
    return step, (next_url if look_further else None)


def scrape(date: datetime.date) -> LinkAggregationResult:
    """
    Scrape CIA "Press Releases and Statements" listing pages for items published on `date`.
    Pagination is discovered from the page markup (rel=next / Next links).
    """
    steps = []
    url = START_URL
    seen_pages: Set[str] = set()

    while url and url not in seen_pages:
        seen_pages.add(url)
        step, next_url = _scrape_page(url, date)
        steps.append(step)

        if not step.look_further or not next_url:
            break

        url = next_url

    return LinkAggregationResult.from_steps(steps)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Example usage: scrape yesterday
    d = datetime.date.today() - datetime.timedelta(days=1)
    print(scrape(d))
