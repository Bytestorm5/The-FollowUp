import os
import sys
import re
import datetime
import logging
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

# Ensure service root is importable (matches existing scraper style)
_service_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

from models import ArticleLink, LinkAggregationStep, LinkAggregationResult
import util.scrape_utils as SU

BASE_URL = "https://www.eac.gov"
LISTING_URL_TEMPLATE = BASE_URL + "/news?page={{PAGE}}"

LOG = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Per user requirement (keep exact spelling provided by user)
AGENCY_TAG = "Agency // Election Assistrance Commission"

_DATE_TEXT_RE = re.compile(
    r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
    r"[A-Z][a-z]+\s+\d{1,2},\s+\d{4}\b"
)


def _abs_url(href: str) -> str:
    return urljoin(BASE_URL, (href or "").strip())


def _safe_get(url: str):
    """Fetch URL using scrape_utils.playwright_get (requests-first with JS fallback)."""
    resp = SU.playwright_get(url, timeout=25, headers=HEADERS)
    try:
        resp.raise_for_status()
    except Exception:
        # requests.Response has raise_for_status; Playwright fallback's is a no-op.
        pass
    return resp


def _parse_date(text: str) -> Optional[datetime.date]:
    text = (text or "").strip()
    if not text:
        return None

    # ISO-ish datetime strings (if present in <time datetime="...">)
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        if "T" in text:
            return datetime.datetime.fromisoformat(text).date()
    except Exception:
        pass

    # Visible format on EAC: "Tuesday, September 30, 2025"
    try:
        return datetime.datetime.strptime(text, "%A, %B %d, %Y").date()
    except Exception:
        return None


def _extract_date_from_row(row) -> Optional[datetime.date]:
    """Try to parse the visible date for a listing row."""
    time_el = row.find("time")
    if time_el:
        dt_attr = (time_el.get("datetime") or "").strip()
        if dt_attr:
            d = _parse_date(dt_attr)
            if d:
                return d
        d = _parse_date(time_el.get_text(" ", strip=True))
        if d:
            return d

    txt = row.get_text(" ", strip=True)
    m = _DATE_TEXT_RE.search(txt)
    if m:
        return _parse_date(m.group(0))

    return None


def _extract_category_from_row(row) -> str:
    """Extract the news category label (Press Releases, Alert, etc.)."""
    sel = row.select_one(
        ".views-field-field-news-category, .views-field-field-news-type, "
        ".field--name-field-news-category, .field--name-field-news-type, "
        ".news-category"
    )
    if sel:
        cat = sel.get_text(" ", strip=True)
        if cat:
            return cat

    known = [
        "Advisory Notice",
        "Alert",
        "Fact Sheet",
        "PCEA",
        "Press Releases",
        "Resolution",
        "Statement",
        "Testing & Certification",
    ]
    txt = row.get_text(" ", strip=True)
    for k in known:
        if k in txt:
            return k

    return "News"


def _extract_link_and_title_from_row(row) -> Optional[tuple[str, str]]:
    """Return (absolute_link, title) for a listing row, if present."""
    for a in row.select("h3 a[href], h2 a[href], a[href]"):
        href = (a.get("href") or "").strip()
        if not href:
            continue

        # Keep only actual news nodes (not pager links, not /news listing).
        if href.startswith("/news/") and href != "/news":
            title = a.get_text(" ", strip=True)
            if title:
                return _abs_url(href), title

        # Some templates may output full URLs
        if href.startswith(BASE_URL + "/news/"):
            title = a.get_text(" ", strip=True)
            if title:
                return href, title

    return None


def _extract_article(article_url: str) -> str:
    """Best-effort extraction: return main content HTML for an article page."""
    resp = _safe_get(article_url)
    soup = BeautifulSoup(resp.content, "html.parser")
    LOG.info("Scraped Content Page %s", article_url)

    main = soup.find("main") or soup.find("article") or soup.find("div", attrs={"role": "main"})
    if not main:
        main = soup.body or soup

    for tag in main.find_all(["script", "style", "noscript"]):
        tag.decompose()
    for tag in main.find_all(["header", "footer", "nav", "aside", "form"]):
        tag.decompose()

    return str(main)


def _has_next_page(soup: BeautifulSoup) -> bool:
    if soup.select_one('a[rel="next"]'):
        return True
    if soup.select_one("li.pager__item--next a"):
        return True

    for a in soup.select("a[href]"):
        if (a.get_text(" ", strip=True) or "").lower() == "next":
            href = (a.get("href") or "").strip()
            if "page=" in href:
                return True
    return False


def _scrape_page(url: str, scrape_date: datetime.date) -> LinkAggregationStep:
    resp = _safe_get(url)
    soup = BeautifulSoup(resp.content, "html.parser")
    LOG.info("Scraped %s", url)

    main = soup.find("main") or soup

    # Drupal view rows are the most likely structure.
    rows = main.select(".view-content .views-row") or main.select(".views-row")

    # Fallback: build pseudo-rows around each /news/ link if markup changes
    if not rows:
        rows = []
        for a in main.select('a[href^="/news/"]'):
            href = (a.get("href") or "").strip()
            if href and href != "/news" and a.parent is not None:
                rows.append(a.parent)

    articles: list[ArticleLink] = []
    seen: set[str] = set()
    reached_older = False

    for row in rows:
        row_date = _extract_date_from_row(row)
        if not row_date:
            continue

        # Listing is sorted newest-first; once we hit older-than-target, stop paging.
        if row_date < scrape_date:
            reached_older = True
            break

        if row_date > scrape_date:
            continue

        lt = _extract_link_and_title_from_row(row)
        if not lt:
            continue
        link, title = lt
        if link in seen:
            continue
        seen.add(link)

        category = _extract_category_from_row(row)
        tags = [AGENCY_TAG]
        if category and category not in tags:
            tags.append(category)

        articles.append(
            ArticleLink(
                title=title,
                link=link,
                date=row_date,
                tags=tags,
                process_posturing=True,
                raw_content=_extract_article(link),
            )
        )

    look_further = (not reached_older) and _has_next_page(soup)
    LOG.info("Processed %d articles from %s. Look further: %s", len(articles), url, look_further)
    return LinkAggregationStep(articles=articles, look_further=look_further)


def scrape(date: datetime.date) -> LinkAggregationResult:
    """
    Scrape EAC News listing pages and return items whose visible date equals `date`.
    Pages are 0-indexed via `?page=`.
    """
    steps: list[LinkAggregationStep] = []
    page = 0

    # Safety cap to avoid infinite loops if pager structure changes
    max_pages = 50

    while page < max_pages:
        url = LISTING_URL_TEMPLATE.replace("{{PAGE}}", str(page))
        step = _scrape_page(url, date)
        steps.append(step)

        if not step.look_further:
            break

        page += 1

    return LinkAggregationResult.from_steps(steps)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Example usage: scrape yesterday
    d = datetime.date.today() - datetime.timedelta(days=1)
    print(scrape(d))
