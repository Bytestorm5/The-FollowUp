# scrapers/scrape_va.py

import os
import sys
import datetime
import logging
from typing import Dict

# Ensure service root is on path (matches existing scraper pattern)
_service_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

from models import ArticleLink, LinkAggregationStep, LinkAggregationResult
import util.scrape_utils as SU


FEEDS = [
    ("https://news.va.gov/news-release-sections/news-release/feed/", "VA News Release"),
    ("https://news.va.gov/news-release-sections/speech/feed/", "VA Speech"),
    ("https://news.va.gov/news-release-sections/press-statement/feed/", "VA Press Statement"),
]


def _add_or_merge(by_link: Dict[str, ArticleLink], article: ArticleLink) -> None:
    """
    Deduplicate by link; if a duplicate appears, merge tags.
    """
    if article.link in by_link:
        existing = by_link[article.link]
        merged = list(dict.fromkeys(existing.tags + article.tags))
        by_link[article.link] = existing.model_copy(update={"tags": merged})
    else:
        by_link[article.link] = article


def scrape(date: datetime.date) -> LinkAggregationResult:
    """
    Scrape VA RSS feeds for items whose published date matches `date`.
    Raw content is taken from the RSS item's summary/encoded content.
    """
    logger = logging.getLogger(__name__)
    by_link: Dict[str, ArticleLink] = {}

    for feed_url, tag in FEEDS:
        items = SU.read_rss_feed(feed_url)
        logger.info(f"VA RSS: {feed_url} -> {len(items)} items")

        for it in items:
            pub = it.get("published")
            if not pub:
                continue

            pub_date = pub.date()
            if pub_date != date:
                continue

            title = (it.get("title") or "").strip()
            link = (it.get("link") or "").strip()
            summary = (it.get("summary") or "").strip()

            if not title or not link:
                continue

            art = ArticleLink(
                title=title,
                link=link,
                date=pub_date,
                tags=["Department of Veterans Affairs", tag],
                raw_content=summary,
                process_posturing=True,
            )
            _add_or_merge(by_link, art)

    step = LinkAggregationStep(articles=list(by_link.values()), look_further=False)
    logger.info(f"VA RSS: returning {len(step.articles)} deduped articles for {date.isoformat()}")

    return LinkAggregationResult.from_steps([step])


if __name__ == "__main__":
    d = datetime.date(2025, 12, 11)
    print(scrape(d))
