import os
import sys
import datetime
import logging
from typing import Optional

import requests
from bs4 import BeautifulSoup

# Ensure service root is on sys.path (mirrors existing scraper layout)
_service_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

from models import ArticleLink, LinkAggregationStep, LinkAggregationResult
import util.scrape_utils as SU


_FEED_URL = "https://www.consumerfinance.gov/about-us/newsroom/feed/"
_TAG = "Agency // Consumer Financial Protection Bureau"


def _extract_fallback_html(url: str, timeout: int = 25) -> str:
    '''
    Best-effort HTML extraction when the RSS item has no summary/content.
    Prefer <main> or <article> if present; otherwise fall back to <body>.
    '''
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
        if not container:
            return ""

        # Light cleanup: strip obvious non-content elements
        for tag in container.find_all(["script", "style", "noscript"]):
            try:
                tag.decompose()
            except Exception:
                pass
        for tag in container.find_all(["header", "footer", "nav", "aside", "form"]):
            try:
                tag.decompose()
            except Exception:
                pass

        return str(container)
    except Exception:
        return ""


def _to_date(dt: Optional[datetime.datetime]) -> Optional[datetime.date]:
    if not dt:
        return None
    try:
        # Keep consistent with other RSS scrapers in this repo: compare on the provided datetime's date.
        return dt.date()
    except Exception:
        return None


def scrape(date: datetime.date) -> LinkAggregationResult:
    '''
    Scrape the CFPB newsroom RSS feed and return items published on `date`.

    Notes:
    - RSS feeds typically only include recent items; there is no pagination.
    - Items without a publish date are skipped (to avoid pulling "all recent" on every run).
    '''
    logger = logging.getLogger(__name__)
    logger.info("Reading RSS feed: %s", _FEED_URL)

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
        if not pub_date:
            # Avoid pulling undated items repeatedly.
            continue

        if pub_date != date:
            continue

        raw = (it.get("summary") or "").strip()
        if not raw:
            raw = _extract_fallback_html(link)

        articles.append(
            ArticleLink(
                title=title,
                link=link,
                date=pub_date,
                tags=[_TAG],
                raw_content=raw,
                process_posturing=True,
            )
        )

    step = LinkAggregationStep(articles=articles, look_further=False)
    logger.info("Collected %d CFPB RSS items for %s", len(articles), date.isoformat())
    return LinkAggregationResult.from_steps([step])


if __name__ == "__main__":
    # Example: scrape yesterday (adjust as needed)
    example_date = datetime.date.today() - datetime.timedelta(days=1)
    res = scrape(example_date)
    print(res)
