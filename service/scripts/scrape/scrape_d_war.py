import os
import sys
import datetime
import logging
from typing import Dict, List

# Keep consistent with other scrapers: add service root to path so we can import models + utils.
_service_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

from models import ArticleLink, LinkAggregationStep, LinkAggregationResult
import util.scrape_utils as SU


# Manually extracted from https://www.war.gov/News/RSS/
# (See "Current RSS Feeds" section.)
RSS_FEEDS: Dict[str, str] = {
    "News": "https://www.war.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945&max=50",
    "Transcripts": "https://www.war.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=13&Site=945&max=50",
    "Advisories": "https://www.war.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=2&Site=945&max=50",
    "Speeches": "https://www.war.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=11&Site=945&max=50",
    "Releases": "https://www.war.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=9&Site=945&max=50",
    "Contract Announcements": "https://www.war.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=400&Site=945&max=50",
}


def _published_to_date(pub_dt, fallback: datetime.date) -> datetime.date:
    """Convert an RSS/Atom published datetime to a date, with a safe fallback."""
    if pub_dt is None:
        return fallback
    try:
        return pub_dt.date()
    except Exception:
        return fallback


def scrape(date: datetime.date) -> LinkAggregationResult:
    """Aggregate several Department of War RSS feeds for the given date.

    - Reads a fixed set of RSS endpoints.
    - Filters items to those published on `date` (when the feed provides a publish time).
    - Deduplicates across feeds by canonical link, merging tags.
    """

    logger = logging.getLogger(__name__)
    logger.info(f"Scraping War.gov RSS feeds for date={date.isoformat()}")

    by_link: Dict[str, ArticleLink] = {}

    for category, feed_url in RSS_FEEDS.items():
        try:
            items = SU.read_rss_feed(feed_url)
        except Exception as e:
            logger.exception(f"Failed to read RSS feed {category}: {feed_url} ({e})")
            continue

        for it in items:
            title = (it.get("title") or "").strip()
            link = (it.get("link") or "").strip()
            pub_dt = it.get("published")
            summary = (it.get("summary") or "").strip()

            if not title or not link:
                continue

            pub_date = _published_to_date(pub_dt, date)

            # Only include items that match the requested date when we can determine it.
            # If no publish date is provided by the feed, we keep the item but stamp with `date`.
            if pub_dt is not None and pub_date != date:
                continue

            if link in by_link:
                existing = by_link[link]
                # Merge tags (dedupe while preserving stable order).
                merged = list(dict.fromkeys([*existing.tags, category]))
                by_link[link] = existing.copy(update={"tags": merged})
                continue

            by_link[link] = ArticleLink(
                title=title,
                link=link,
                date=pub_date,
                tags=["Department of War", category],
                raw_content=summary,
                process_posturing=True,
            )

    articles: List[ArticleLink] = list(by_link.values())
    # Deterministic ordering: newest first, then title.
    articles = sorted(articles, key=lambda a: (a.date, a.title), reverse=True)

    step = LinkAggregationStep(articles=articles, look_further=False)
    logger.info(f"Returning {len(articles)} unique articles from War.gov RSS feeds")
    return LinkAggregationResult.from_steps([step])


if __name__ == "__main__":
    d = datetime.date.today() - datetime.timedelta(days=1)
    print(scrape(d))
