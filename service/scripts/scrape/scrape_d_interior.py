import os
import sys
import datetime
import logging
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# Ensure project root is importable (matches existing scraper style)
_service_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

from models import ArticleLink, LinkAggregationStep, LinkAggregationResult
import util.scrape_utils as SU

BASE_URL = "https://www.doi.gov"
LIST_URL_TEMPLATE = "https://www.doi.gov/news?page={{PAGE}}"

_HDRS = {}


def _extract(article_url: str) -> str:
    """
    Fetch a DOI press release page and return the main article HTML as a string.
    We prefer the <article> node (press release body) when present; otherwise fall
    back to <main>.
    """
    resp = requests.get(article_url, headers=_HDRS, timeout=30, allow_redirects=True)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "html.parser")
    logging.getLogger(__name__).info(f"Scraped Content Page {article_url}")

    main = soup.find("main")
    # Try to grab the press release article body.
    art = None
    if main:
        art = main.find("article")
    if not art:
        art = soup.find("article")

    node = art or main or soup.body or soup
    return str(node)


def _parse_card_date(date_text: str) -> datetime.date:
    # DOI list cards use mm/dd/yyyy like "12/11/2025"
    return datetime.datetime.strptime(date_text.strip(), "%m/%d/%Y").date()


def _scrape_page(url: str, scrape_date: datetime.date) -> LinkAggregationStep:
    resp = requests.get(url, headers=_HDRS, timeout=30, allow_redirects=True)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "html.parser")
    logging.getLogger(__name__).info(f"Scraped {url}")

    # Each press release card is an <article> with node--type-press-release.
    cards = soup.select("article.node--type-press-release")
    logging.getLogger(__name__).info(f"Found {len(cards)} press release cards on {url}")

    if not cards:
        return LinkAggregationStep(articles=[], look_further=False)

    articles = []
    look_further = True

    for card in cards:
        date_el = card.select_one(".publication-info--date")
        if not date_el:
            # Skip malformed cards, but keep scanning.
            continue

        try:
            published = _parse_card_date(date_el.get_text(strip=True))
        except Exception:
            continue

        # Cards are in reverse-chronological order.
        # Stop paging once we pass below the target scrape_date.
        if published < scrape_date:
            look_further = False
            break

        if published != scrape_date:
            # Too new; ignore and continue looking on later pages.
            continue

        h3 = card.find("h3")
        a = h3.find("a") if h3 else None
        if not a or not a.get("href"):
            continue

        title = a.get_text(" ", strip=True)
        link = urljoin(BASE_URL, a["href"])

        articles.append(
            ArticleLink(
                title=title,
                link=link,
                date=published,
                tags=["DOI", "Press Release"],
                process_posturing=True,
                raw_content=_extract(link),
            )
        )

    logging.getLogger(__name__).info(
        f"Processed {len(articles)} articles from {url}. Look Further: {look_further}"
    )
    return LinkAggregationStep(articles=articles, look_further=look_further)


def scrape(date: datetime.date) -> LinkAggregationResult:
    """
    Scrape DOI Press Releases list pages until we go past `date`.
    Pages are zero-indexed (?page=0, ?page=1, ...).
    """
    return SU.iter_scrape(LIST_URL_TEMPLATE, 0, date, _scrape_page)


if __name__ == "__main__":
    # Example usage
    d = datetime.date(2025, 12, 11)
    print(scrape(d))
