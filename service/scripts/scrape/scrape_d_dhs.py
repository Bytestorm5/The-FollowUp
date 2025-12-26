# scrape_dhs_all_news_updates.py

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

BASE_URL = "https://www.dhs.gov"

log = logging.getLogger(__name__)


def _get(url: str, timeout: int = 30) -> requests.Response:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TheFollowUpBot/1.0)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return resp


def _parse_item_date(row) -> datetime.date | None:
    """
    DHS listing rows typically contain:
      <time datetime="2025-12-12T18:07:38-05:00">December 12, 2025</time>
    """
    time_tag = row.find("time")
    if time_tag:
        dt_attr = time_tag.get("datetime")
        if dt_attr:
            try:
                return datetime.datetime.fromisoformat(dt_attr).date()
            except Exception:
                pass
        txt = time_tag.get_text(strip=True)
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.datetime.strptime(txt, fmt).date()
            except Exception:
                continue
    return None


def _extract(url: str) -> str:
    """
    Best-effort content extraction for DHS nodes.
    We return the main/article region HTML with noisy tags stripped.
    """
    resp = _get(url)
    soup = BeautifulSoup(resp.content, "html.parser")

    main = (
        soup.find("main")
        or soup.find(id="main-content")
        or soup.find("article")
        or soup.find("div", attrs={"role": "main"})
    )
    if not main:
        main = soup.body or soup

    # Remove obvious noise inside the extracted region
    for tag in main.find_all(["script", "style", "noscript"]):
        tag.decompose()
    for tag in main.find_all(["header", "footer", "nav", "form"]):
        tag.decompose()

    return str(main)


def _scrape_page(url: str, scrape_date: datetime.date) -> LinkAggregationStep:
    resp = _get(url)
    soup = BeautifulSoup(resp.content, "html.parser")
    log.info(f"Scraped {url}")

    rows = soup.select("div.news-updates.views-row")
    log.info(f"Found {len(rows)} rows on {url}")

    articles: list[ArticleLink] = []
    look_further = True

    if not rows:
        return LinkAggregationStep(articles=[], look_further=False)

    for row in rows:
        date = _parse_item_date(row)
        if not date:
            # If we can't parse a date, skip the row but keep scanning.
            continue

        # Stop pagination once we hit anything outside the target date.
        if date != scrape_date:
            look_further = False
            break

        a = row.select_one("h3.news-updates-title a")
        if not a or not a.get("href"):
            continue

        title = a.get_text(strip=True)
        link = urljoin(BASE_URL, a["href"])

        type_a = row.select_one(".news-updates-date-type span.news-type a")
        news_type = [type_a.get_text(strip=True)] if type_a else []

        articles.append(
            ArticleLink(
                title=title,
                link=link,
                date=date,
                tags=["Department of Homeland Security"] + news_type,
                process_posturing=True,
                raw_content=_extract(link),
            )
        )

    log.info(f"Processed {len(articles)} articles from {url}. Look Further: {look_further}")
    return LinkAggregationStep(articles=articles, look_further=look_further)


def scrape(date: datetime.date) -> LinkAggregationResult:
    # Pages are zero-indexed.
    url_template = (
        "https://www.dhs.gov/all-news-updates"
        "?combine=&created=&field_news_type_target_id=All"
        "&field_taxonomy_topics_target_id=All"
        "&items_per_page=10"
        "&page={{PAGE}}"
    )
    return SU.iter_scrape(url_template, 0, date, _scrape_page)