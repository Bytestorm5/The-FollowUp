# scrapers/scrape_fec.py

import os
import sys
import re
import datetime
import logging
from typing import Dict, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup

# Ensure service root is on path (matches existing scraper pattern)
_service_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

from models import ArticleLink, LinkAggregationStep, LinkAggregationResult
import util.scrape_utils as SU


LOGGER = logging.getLogger(__name__)

FEC_TAG = "Agency // Federal Election Commission"
BASE_URL = "https://www.fec.gov"

# These are the two sources you specified
SOURCE_TEMPLATES = [
    ("https://www.fec.gov/updates/?page={{PAGE}}&update_type=press-release", "Press release"),
    ("https://www.fec.gov/updates/?page={{PAGE}}&update_type=fec-record", "FEC Record"),
]

# Matches "September 29, 2025"
_DATE_RE = re.compile(
    r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}$"
)


def _fetch_soup(url: str, timeout: int = 25) -> BeautifulSoup:
    """
    Fetch page HTML. We explicitly set try_requests because scrape_utils.playwright_get's
    default mode can raise on 'default'.
    """
    resp = SU.playwright_get(url, timeout=timeout, try_requests="first")
    resp.raise_for_status()
    return BeautifulSoup(resp.content, "html.parser")


def _parse_date_from_container(container) -> Optional[datetime.date]:
    if not container:
        return None
    for s in container.stripped_strings:
        txt = (s or "").strip()
        if not txt:
            continue
        if _DATE_RE.match(txt):
            try:
                return datetime.datetime.strptime(txt, "%B %d, %Y").date()
            except Exception:
                continue
    return None


def _has_next_page(soup: BeautifulSoup) -> bool:
    """
    The listing pages include pagination with an anchor labeled 'Next' that points
    to /updates/?page=N&update_type=...
    """
    main = soup.find("main") or soup
    a = main.find("a", href=True, string=re.compile(r"^\s*Next\s*$", re.I))
    if not a:
        return False
    href = (a.get("href") or "").strip()
    return "/updates/" in href and "page=" in href


def _extract_main_html(article_url: str) -> str:
    soup = _fetch_soup(article_url)
    main = soup.find("main")
    if main:
        return str(main)
    body = soup.find("body")
    return str(body) if body else str(soup)


def _parse_article_kind_and_subject(article_url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Use the article page breadcrumbs to extract a stable (kind, subject) pair, e.g.
      ("Press release", "Campaign finance data summaries")
      ("FEC Record", "Reporting")
    """
    soup = _fetch_soup(article_url)
    main = soup.find("main") or soup

    # Prefer breadcrumb nav if present
    crumb_nav = main.find("nav", attrs={"aria-label": re.compile("breadcrumb", re.I)})
    search_root = crumb_nav or main

    kind = None
    subject = None

    for a in search_root.find_all("a"):
        t = a.get_text(" ", strip=True)
        if not t or ":" not in t:
            continue

        tl = t.lower()
        if tl.startswith("press releases"):
            kind = "Press release"
            subject = t.split(":", 1)[1].strip() or None
            break
        if tl.startswith("fec record"):
            kind = "FEC Record"
            subject = t.split(":", 1)[1].strip() or None
            break

    return kind, subject


def _scrape_listing_page(url: str, scrape_date: datetime.date, default_kind: str) -> LinkAggregationStep:
    soup = _fetch_soup(url)
    main = soup.find("main") or soup

    articles = []
    stop_because_older = False

    # Each update entry exposes a <h3> title with a link; the date appears in the same container.
    for h3 in main.find_all("h3"):
        a = h3.find("a", href=True)
        if not a:
            continue

        title = a.get_text(" ", strip=True)
        href = (a.get("href") or "").strip()
        if not title or not href:
            continue

        link = urljoin(BASE_URL, href)

        # Find a container likely holding the date + excerpt + footer (best-effort)
        container = h3.find_parent(["article", "li", "section", "div"]) or h3.parent
        item_date = _parse_date_from_container(container)
        if not item_date:
            # Fallback: sometimes the date is just above the <h3>
            item_date = _parse_date_from_container(h3.find_parent(["article", "li", "section"]) or h3)

        if not item_date:
            continue

        # Reverse chronological; once we pass older-than-target, we can stop paging.
        if item_date > scrape_date:
            continue
        if item_date < scrape_date:
            stop_because_older = True
            break

        kind, subject = _parse_article_kind_and_subject(link)
        kind = kind or default_kind

        tags = [FEC_TAG, kind]
        if subject:
            tags.append(subject)

        articles.append(
            ArticleLink(
                title=title,
                link=link,
                date=item_date,
                tags=tags,
                raw_content=_extract_main_html(link),
                process_posturing=True,
            )
        )

    look_further = (not stop_because_older) and _has_next_page(soup)
    return LinkAggregationStep(articles=articles, look_further=look_further)


def _add_or_merge(by_link: Dict[str, ArticleLink], article: ArticleLink) -> None:
    """
    Deduplicate by link; if a duplicate appears (e.g., same story in Press release + FEC Record),
    merge tags.
    """
    if article.link in by_link:
        existing = by_link[article.link]
        merged = list(dict.fromkeys((existing.tags or []) + (article.tags or [])))
        by_link[article.link] = existing.model_copy(update={"tags": merged})
    else:
        by_link[article.link] = article


def scrape(date: datetime.date) -> LinkAggregationResult:
    """
    Scrape FEC "Latest updates" for:
      - Press releases
      - FEC Record
    Filter to `date` and merge/dedupe by URL.
    """
    by_link: Dict[str, ArticleLink] = {}

    for url_template, default_kind in SOURCE_TEMPLATES:
        LOGGER.info("FEC updates: scraping kind=%s template=%s", default_kind, url_template)

        def _page_fn(url: str, dt: datetime.date) -> LinkAggregationStep:
            # iter_scrape passes a datetime; we store dates only.
            return _scrape_listing_page(url, dt, default_kind)

        res = SU.iter_scrape(url_template=url_template, start_page=1, date=date, scrape_fn=_page_fn)

        for art in res.articles:
            _add_or_merge(by_link, art)

    articles = list(by_link.values())
    articles.sort(key=lambda a: (a.date, a.title), reverse=True)

    step = LinkAggregationStep(articles=articles, look_further=False)
    LOGGER.info("FEC updates: returning %d deduped articles for %s", len(articles), date.isoformat())
    return LinkAggregationResult.from_steps([step])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Example date (adjust as needed):
    d = datetime.date.today() - datetime.timedelta(days=1)
    print(scrape(d))
