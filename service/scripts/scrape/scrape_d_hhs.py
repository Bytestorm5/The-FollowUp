import os
import sys
import datetime
import logging
from typing import Optional

import requests
from bs4 import BeautifulSoup

# Ensure service root is on sys.path (mirrors existing scraper layout)
_service_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

from models import ArticleLink, LinkAggregationStep, LinkAggregationResult
import util.scrape_utils as SU


_FEED_URL = "https://www.hhs.gov/rss/news.xml"


def _extract_fallback_html(url: str, timeout: int = 20) -> str:
    """
    Best-effort HTML extraction when the RSS item has no summary.
    We keep it conservative: grab <main> or <article> if present, else body.
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


def _to_date(dt: Optional[datetime.datetime]) -> Optional[datetime.date]:
    if not dt:
        return None
    try:
        # Normalize tz-aware datetimes to UTC before taking the date for consistency.
        if dt.tzinfo is not None:
            return dt.astimezone(datetime.timezone.utc).date()
        return dt.date()
    except Exception:
        return None


def scrape(date: datetime.date) -> LinkAggregationResult:
    """
    Scrape the HHS News RSS feed and return items published on `date`.

    Note: RSS feeds typically only include recent items; there is no pagination.
    """
    logging.getLogger(__name__).info(f"Reading RSS feed: {_FEED_URL}")
    items = SU.read_rss_feed(_FEED_URL)

    seen = set()
    articles = []

    for it in items:
        title = (it.get("title") or "").strip()
        link = (it.get("link") or "").strip()
        if not title or not link:
            continue

        # Deduplicate aggressively by canonical URL
        if link in seen:
            continue
        seen.add(link)

        pub_date = _to_date(it.get("published"))

        # Filter to the requested scrape date when we have a publication date.
        # If the feed provides no date, we still include the item and set date=scrape date.
        if pub_date and pub_date != date:
            continue

        raw = (it.get("summary") or "").strip()
        if not raw:
            raw = _extract_fallback_html(link)

        articles.append(
            ArticleLink(
                title=title,
                link=link,
                date=pub_date or date,
                tags=["Department of Health and Human Services"],
                raw_content=raw,
                process_posturing=True,
            )
        )

    step = LinkAggregationStep(articles=articles, look_further=False)
    logging.getLogger(__name__).info(f"Collected {len(articles)} HHS RSS items for {date.isoformat()}")
    return LinkAggregationResult.from_steps([step])


if __name__ == "__main__":
    # Example: scrape yesterday (adjust as needed)
    example_date = datetime.date.today() - datetime.timedelta(days=1)
    res = scrape(example_date)
    print(res)
