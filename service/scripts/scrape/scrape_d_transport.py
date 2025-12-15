import os
import sys
import re
import logging
import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

_service_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

from models import ArticleLink, LinkAggregationStep, LinkAggregationResult
import util.scrape_utils as SU

LOGGER = logging.getLogger(__name__)
BASE = "https://www.transportation.gov"

UA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TheFollowUpBot/1.0; +https://example.invalid)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# -------------------------
# Helpers
# -------------------------

def _fetch_soup(url: str) -> BeautifulSoup:
    resp = SU.playwright_get(url, timeout=30, headers=UA_HEADERS)
    resp.raise_for_status()
    return BeautifulSoup(resp.content, "html.parser")


def _parse_dot_date(date_str: str) -> datetime.date:
    """
    DOT listings use: 'December 12, 2025' or 'September 23, 2025'
    """
    s = (date_str or "").strip()
    # Some pages might include extra whitespace/newlines.
    s = re.sub(r"\s+", " ", s)
    return datetime.datetime.strptime(s, "%B %d, %Y").date()


def _extract_article_content(url: str) -> str:
    """
    Best-effort extraction:
    Prefer <article>, else the main content region, else <main>.
    """
    soup = _fetch_soup(url)
    main = soup.find("main")
    if not main:
        return str(soup)

    # Remove common non-content blocks when present
    for sel in [
        ".region-breadcrumb",
        ".sidebar",
        "#sidenav",
        ".list_filter",
        ".list_pagination",
        "nav",
    ]:
        for n in main.select(sel):
            try:
                n.decompose()
            except Exception:
                pass

    # Prefer the actual article node if present
    article = main.find("article")
    if article:
        return str(article)

    # Fallback to main content column / region-content
    main_content = main.select_one("div.main-content") or main.select_one("section.region-content")
    if main_content:
        return str(main_content)

    return str(main)


def _normalize_link(href: str) -> str:
    href = (href or "").strip()
    if not href:
        return ""
    return urljoin(BASE, href)


# -------------------------
# Listing parsers
# -------------------------

def _parse_press_release_cards(soup: BeautifulSoup, scrape_date: datetime.date) -> LinkAggregationStep:
    """
    Press Releases page uses <article class="node__content view--item ..."> cards.
    Title link is inside an <h1> (sometimes h2/h3 variants) and date is in <time>.
    """
    view = soup.find("div", class_=re.compile(r"\bview-newsroom\b"))
    list_news = view.find("div", class_="list_news") if view else None
    if not list_news:
        return LinkAggregationStep(articles=[], look_further=False)

    cards = list_news.find_all("article", recursive=False) or list_news.find_all("article")
    if not cards:
        return LinkAggregationStep(articles=[], look_further=False)

    articles = []
    look_further = True

    for card in cards:
        # Title/link
        heading = card.find(["h1", "h2", "h3"])
        a = heading.find("a") if heading else None
        if not a or not a.get("href"):
            continue

        title = a.get_text(" ", strip=True)
        link = _normalize_link(a["href"])

        # Date
        t = card.find("time")
        if not t:
            continue
        date_text = t.get_text(" ", strip=True) or ""
        try:
            dt = _parse_dot_date(date_text)
        except Exception:
            # Try ISO-ish datetime attr as fallback
            dt_attr = (t.get("datetime") or "").strip()
            if dt_attr:
                try:
                    dt = datetime.datetime.fromisoformat(dt_attr.replace("Z", "+00:00")).date()
                except Exception:
                    continue
            else:
                continue

        # Type label (usually "Press Release")
        label = ""
        label_span = card.find("span", class_=re.compile(r"\blabel_format\b"))
        if label_span:
            label = label_span.get_text(" ", strip=True)

        # Stop condition: once we hit older than target date, later pages will be even older.
        if dt < scrape_date:
            look_further = False
            break

        # Only collect exact date matches (skip newer)
        if dt == scrape_date:
            tags = [label] if label else ["Press Release"]
            articles.append(
                ArticleLink(
                    title=title,
                    link=link,
                    date=dt,
                    tags=tags,
                    process_posturing=True,
                    raw_content=_extract_article_content(link),
                )
            )

    return LinkAggregationStep(articles=articles, look_further=look_further)


def _parse_speeches_table(soup: BeautifulSoup, scrape_date: datetime.date) -> LinkAggregationStep:
    """
    Speeches page uses a table:
      td.views-field-title a[href]
      td.views-field-field-effective-date (e.g. "March 27, 2025")
    """
    view = soup.find("div", class_=re.compile(r"\bview-newsroom\b"))
    list_news = view.find("div", class_="list_news") if view else None
    if not list_news:
        return LinkAggregationStep(articles=[], look_further=False)

    table = list_news.find("table")
    if not table:
        # If DOT ever switches speeches to cards, we can fall back to card parsing.
        return _parse_press_release_cards(soup, scrape_date)

    tbody = table.find("tbody")
    rows = tbody.find_all("tr") if tbody else []
    if not rows:
        return LinkAggregationStep(articles=[], look_further=False)

    articles = []
    look_further = True

    for tr in rows:
        a = tr.select_one("td.views-field-title a")
        dtd = tr.select_one("td.views-field-field-effective-date")
        if not a or not a.get("href") or not dtd:
            continue

        title = a.get_text(" ", strip=True)
        link = _normalize_link(a["href"])

        try:
            dt = _parse_dot_date(dtd.get_text(" ", strip=True))
        except Exception:
            continue

        if dt < scrape_date:
            look_further = False
            break

        if dt == scrape_date:
            articles.append(
                ArticleLink(
                    title=title,
                    link=link,
                    date=dt,
                    tags=["Speech"],
                    process_posturing=True,
                    raw_content=_extract_article_content(link),
                )
            )

    return LinkAggregationStep(articles=articles, look_further=look_further)


def _scrape_page(url: str, scrape_date: datetime.date, kind: str) -> LinkAggregationStep:
    soup = _fetch_soup(url)
    LOGGER.info(f"Scraped DOT listing page: {url}")

    if kind == "press_releases":
        return _parse_press_release_cards(soup, scrape_date)
    if kind == "speeches":
        return _parse_speeches_table(soup, scrape_date)

    raise ValueError(f"Unknown kind: {kind}")


# -------------------------
# Public entrypoint
# -------------------------

def scrape(date: datetime.date) -> LinkAggregationResult:
    """
    Scrape DOT Press Releases + Speeches for a single target date.
    Pages are zero-indexed.
    """
    press_template = "https://www.transportation.gov/newsroom/press-releases?page={{PAGE}}"
    speeches_template = "https://www.transportation.gov/newsroom/speeches?page={{PAGE}}"

    res_press = SU.iter_scrape(
        press_template,
        start_page=0,
        date=date,
        scrape_fn=lambda url, d: _scrape_page(url, d, "press_releases"),
    )
    res_speeches = SU.iter_scrape(
        speeches_template,
        start_page=0,
        date=date,
        scrape_fn=lambda url, d: _scrape_page(url, d, "speeches"),
    )

    combined = sorted(
        (res_press.articles or []) + (res_speeches.articles or []),
        key=lambda x: x.date,
        reverse=True,
    )
    return LinkAggregationResult(articles=combined)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_date = datetime.date(2025, 12, 12)
    out = scrape(test_date)
    print(out)
