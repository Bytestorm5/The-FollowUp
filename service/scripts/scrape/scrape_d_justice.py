import os
import sys
import datetime
import logging
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

_service_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

from models import ArticleLink, LinkAggregationStep, LinkAggregationResult
import util.scrape_utils as SU

BASE = "https://www.justice.gov"
LOGGER = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TheFollowUpBot/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _extract(article_url: str) -> str:
    """Fetch and return main content HTML for an individual DOJ news item."""
    resp = SU.playwright_get(article_url, timeout=30, headers=HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "html.parser")

    main = soup.find("main")
    if main:
        # remove obvious non-content blocks if present
        for sel in [
            ".usdoj_overlay",
            "nav",
            "header",
            "footer",
            "script",
            "style",
        ]:
            for t in main.select(sel):
                t.decompose()
        return str(main)

    # Fallback
    body = soup.find("body")
    return str(body) if body else resp.text


def _has_next_page(soup: BeautifulSoup) -> bool:
    # Be permissive: Drupal pagers can vary.
    if soup.select_one('a[rel="next"]'):
        return True
    if soup.select_one("li.pager__item--next a"):
        return True
    if soup.select_one('a[title*="next" i]'):
        return True
    return False


def _scrape_page(url: str, scrape_date: datetime.date) -> LinkAggregationStep:
    resp = SU.playwright_get(url, timeout=30, headers=HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "html.parser")
    LOGGER.info(f"Scraped {url}")

    rows = soup.select("div.rows-wrapper div.views-row article.news-content-listing")
    LOGGER.info(f"Found {len(rows)} rows on {url}")

    articles = []
    for art in rows:
        title_a = art.select_one("h2.news-title a")
        if not title_a:
            continue

        title = title_a.get_text(strip=True)
        href = title_a.get("href", "").strip()
        link = urljoin(BASE, href)

        node_type = art.select_one(".node-type")
        tag = node_type.get_text(strip=True) if node_type else "News"

        time_el = art.select_one(".node-date time")
        if not time_el or not time_el.get("datetime"):
            continue

        # Example in provided HTML: 2025-12-12T12:00:00Z
        dt_raw = time_el["datetime"].strip()
        try:
            item_date = datetime.datetime.fromisoformat(dt_raw.replace("Z", "+00:00")).date()
        except Exception:
            # Fallback: visible text like "December 12, 2025"
            try:
                item_date = datetime.datetime.strptime(time_el.get_text(strip=True), "%B %d, %Y").date()
            except Exception:
                continue

        # This query should already constrain dates, but keep a guardrail:
        if item_date != scrape_date:
            continue

        articles.append(
            ArticleLink(
                title=title,
                link=link,
                date=item_date,
                tags=["Department of Justice", tag],
                process_posturing=True,
                raw_content=_extract(link),
            )
        )

    # Keep paginating if site exposes a next link AND we got at least one result.
    look_further = bool(articles) and _has_next_page(soup)
    LOGGER.info(f"Processed {len(articles)} articles from {url}. Look further: {look_further}")
    return LinkAggregationStep(articles=articles, look_further=look_further)


def scrape(scrape_date: datetime.date) -> LinkAggregationResult:
    """
    DOJ uses start_date/end_date query params.
    Per requirement: end_date must be ticked +1 day from scrape_date.
    Pages are zero-indexed.
    """
    start_date = scrape_date.isoformat()
    end_date = (scrape_date + datetime.timedelta(days=1)).isoformat()

    url_template = (
        "https://www.justice.gov/news"
        "?search_api_fulltext=%20"
        f"&start_date={start_date}"
        f"&end_date={end_date}"
        "&sort_by=search_api_relevance"
        "&page={{PAGE}}"
    )

    # zero-indexed pages
    return SU.iter_scrape(url_template, 0, scrape_date, _scrape_page)


if __name__ == "__main__":
    # Example: scrape items published on 2025-12-12 by querying start_date=2025-12-12, end_date=2025-12-13
    d = datetime.date(2025, 12, 12)
    print(scrape(d))
