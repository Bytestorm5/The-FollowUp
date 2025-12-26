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

BASE_URL = "https://home.treasury.gov"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TheFollowUpBot/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _abs_url(href: str) -> str:
    return urljoin(BASE_URL, href or "")


def _parse_iso_date(dt_str: str) -> datetime.date:
    # Example: "2025-12-11T22:15:00Z"
    dt_str = (dt_str or "").strip()
    if not dt_str:
        raise ValueError("Empty datetime string")
    if dt_str.endswith("Z"):
        dt_str = dt_str.replace("Z", "+00:00")
    return datetime.datetime.fromisoformat(dt_str).date()


def _extract(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "html.parser")

    logging.getLogger(__name__).info(f"Scraped Content Page {url}")

    # Prefer the main content area used on the site.
    main = soup.select_one("div#content-area div.region.region-content")
    if not main:
        main = soup.find("main")
    if not main:
        main = soup.body or soup

    # Light cleanup: remove nav/aside if present within selected main
    for sel in ["nav", "aside"]:
        for tag in main.select(sel):
            tag.decompose()

    return str(main)


def _scrape_page(url: str, scrape_date: datetime.date) -> LinkAggregationStep:
    # Defensive fix in case someone provides "...?x=y?page=0" (double '?')
    if "?page=" in url and "&page=" not in url:
        url = url.replace("?page=", "&page=")

    resp = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "html.parser")

    logging.getLogger(__name__).info(f"Scraped {url}")

    container = soup.select_one("div.featured-stories.content--2col div.content--2col__body")
    if not container:
        container = soup.select_one("div.content--2col__body")

    if not container:
        logging.getLogger(__name__).warning(f"No listing container found on {url}")
        return LinkAggregationStep(articles=[], look_further=False)

    # Each result is a direct child <div> containing:
    # - <time class="datetime" datetime="...">Month Day, Year</time>
    # - <h3 class="featured-stories__headline"><a href="...">Title</a></h3>
    items = container.find_all("div", recursive=False)

    articles = []
    seen = set()
    look_further = True

    for item in items:
        a = item.select_one("h3.featured-stories__headline a")
        t = item.select_one("time.datetime")

        if not a or not t:
            continue

        title = a.get_text(strip=True)
        link = _abs_url(a.get("href", "").strip())
        if not title or not link or link in seen:
            continue
        seen.add(link)

        dt_attr = t.get("datetime", "").strip()
        try:
            item_date = _parse_iso_date(dt_attr) if dt_attr else datetime.datetime.strptime(
                t.get_text(strip=True), "%B %d, %Y"
            ).date()
        except Exception:
            # If date parsing fails, skip item rather than breaking the whole scrape
            logging.getLogger(__name__).warning(f"Could not parse date for {link}")
            continue

        # If we’ve paged into older content than the target date, stop pagination.
        if item_date < scrape_date:
            look_further = False
            break

        # Only keep items for the requested date
        if item_date != scrape_date:
            continue

        subcat = item.select_one("span.subcategory a")
        tag = subcat.get_text(strip=True) if subcat else "Press Releases"

        articles.append(
            ArticleLink(
                title=title,
                link=link,
                date=item_date,
                tags=["Department of the Treasury", tag],
                process_posturing=True,
                raw_content=_extract(link),
            )
        )

    if not articles:
        # With a date-filtered query, no results usually means no reason to keep paginating.
        look_further = False

    logging.getLogger(__name__).info(
        f"Processed {len(articles)} articles from {url}. Look Further: {look_further}"
    )
    return LinkAggregationStep(articles=articles, look_further=look_further)


def scrape(date: datetime.date) -> LinkAggregationResult:
    # Pages are zero-indexed per your note.
    url_template = (
        "https://home.treasury.gov/news/press-releases"
        f"?title=&publication-start-date={date.isoformat()}"
        f"&publication-end-date={date.isoformat()}"
        "&page={{PAGE}}"
    )
    return SU.iter_scrape(url_template, 0, date, _scrape_page)


if __name__ == "__main__":
    d = datetime.date(2025, 12, 11)
    print(scrape(d))
