# scrapers/scrape_nlrb_rss_press_releases.py

import os
import sys
import datetime
import logging
from typing import Set

import requests
from bs4 import BeautifulSoup

# Ensure service root is on sys.path (matches existing scraper style)
_service_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

from models import ArticleLink, LinkAggregationStep, LinkAggregationResult
import util.scrape_utils as SU


FEED_URL = "https://www.nlrb.gov/rss/rssPressReleases.xml"
NLRB_TAG = "Agency // Labor Relations Board"

LOGGER = logging.getLogger(__name__)


def _extract_fallback_html(url: str, timeout: int = 25) -> str:
    """
    Best-effort HTML extraction when the RSS item has no usable summary.
    Conservative: prefer <main> or <article>, else body.
    """
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            allow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; TheFollowUpBot/1.0)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")
        container = soup.find("main") or soup.find("article") or soup.body
        return str(container) if container else ""
    except Exception:
        return ""


def scrape(date: datetime.date) -> LinkAggregationResult:
    """
    Read the NLRB Press Releases RSS feed and return items published on `date`.
    Everything returned is labeled with tag: "Agency // Labor Relations Board".
    """
    LOGGER.info("Reading RSS feed: %s", FEED_URL)
    items = SU.read_rss_feed(FEED_URL)

    articles = []
    seen_links: Set[str] = set()

    for it in items:
        title = (it.get("title") or "").strip()
        link = (it.get("link") or "").strip()
        pub = it.get("published")

        if not title or not link or link in seen_links:
            continue

        # If the feed provides a published datetime, filter strictly to the requested date.
        # If not provided, include and stamp with `date`.
        if pub:
            try:
                item_date = pub.date()
            except Exception:
                item_date = date

            if item_date != date:
                continue
        else:
            item_date = date

        seen_links.add(link)

        raw = (it.get("summary") or "").strip()
        if not raw:
            raw = _extract_fallback_html(link)

        articles.append(
            ArticleLink(
                title=title,
                link=link,
                date=item_date,
                tags=[NLRB_TAG],
                raw_content=raw,
                process_posturing=True,
            )
        )

    step = LinkAggregationStep(articles=articles, look_further=False)
    LOGGER.info("Collected %d NLRB RSS items for %s", len(articles), date.isoformat())
    return LinkAggregationResult.from_steps([step])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Example: scrape yesterday
    d = datetime.date(2025, 9, 16)
    print(scrape(d))
