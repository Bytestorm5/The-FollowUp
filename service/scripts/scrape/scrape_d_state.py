import os
import sys
import datetime
import logging
from typing import Dict, List, Optional, Tuple

# Ensure service root is importable
_service_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

from models import ArticleLink, LinkAggregationResult, LinkAggregationStep  # :contentReference[oaicite:0]{index=0}
import util.scrape_utils as SU  # :contentReference[oaicite:1]{index=1}


LOGGER = logging.getLogger(__name__)

STATE_RSS_FEEDS: List[Tuple[str, str]] = [
    ("https://www.state.gov/rss-feed/africa/feed/", "Africa"),
    ("https://www.state.gov/rss-feed/collected-department-releases/feed/", "Collected Department Releases"),
    ("https://www.state.gov/rss-feed/department-press-briefings/feed/", "Department Press Briefings"),
    ("https://www.state.gov/rss-feed/diplomatic-security/feed/", "Diplomatic Security"),
    ("https://www.state.gov/rss-feed/direct-line-to-american-business/feed/", "Direct Line to American Business"),
    ("https://www.state.gov/rss-feed/east-asia-and-the-pacific/feed/", "East Asia and the Pacific"),
    ("https://www.state.gov/rss-feed/europe-and-eurasia/feed/", "Europe and Eurasia"),
    ("https://www.state.gov/rss-feed/international-organizations/feed/", "International Organizations"),
    ("https://www.state.gov/rss-feed/near-east/feed/", "Near East"),
    ("https://www.state.gov/rss-feed/press-releases/feed/", "Press Releases"),
    ("https://www.state.gov/rss-feed/secretarys-remarks/feed/", "Secretary's Remarks"),
    ("https://www.state.gov/rss-feed/south-and-central-asia/feed/", "South and Central Asia"),
    ("https://www.state.gov/rss-feed/treaties-new/feed/", "Treaties"),
    ("https://www.state.gov/rss-feed/western-hemisphere/feed/", "Western Hemisphere"),
]


def _to_date(dt: Optional[datetime.datetime]) -> Optional[datetime.date]:
    if not dt:
        return None
    # If timezone-aware, normalize to UTC for stable date comparisons
    if dt.tzinfo is not None:
        try:
            return dt.astimezone(datetime.timezone.utc).date()
        except Exception:
            return dt.date()
    return dt.date()


def scrape(date: datetime.date) -> LinkAggregationResult:
    """
    Ingest State.gov RSS feeds, filter to `date`, and deduplicate by link.
    If an item appears in multiple feeds, it inherits all tags.
    """
    by_link: Dict[str, ArticleLink] = {}

    for feed_url, feed_tag in STATE_RSS_FEEDS:
        try:
            items = SU.read_rss_feed(feed_url)  # :contentReference[oaicite:2]{index=2}
        except Exception as e:
            LOGGER.exception(f"Failed to read RSS feed {feed_url}: {e}")
            continue

        LOGGER.info(f"Read {len(items)} items from {feed_url}")

        for it in items:
            title = (it.get("title") or "").strip()
            link = (it.get("link") or "").strip()
            pub_dt = it.get("published")
            summary = it.get("summary") or ""

            item_date = _to_date(pub_dt)
            if not title or not link or not item_date:
                continue

            if item_date != date:
                continue

            if link in by_link:
                # Merge tags for duplicates across feeds
                existing = by_link[link]
                merged = set(existing.tags or [])
                merged.add(feed_tag)
                existing.tags = sorted(merged)
            else:
                by_link[link] = ArticleLink(
                    title=title,
                    link=link,
                    date=item_date,
                    tags=["Department of State", feed_tag],
                    raw_content=summary,
                    process_posturing=True,
                )

    articles = list(by_link.values())
    articles.sort(key=lambda a: (a.date, a.title), reverse=True)

    step = LinkAggregationStep(articles=articles, look_further=False)  # :contentReference[oaicite:3]{index=3}
    LOGGER.info(f"State.gov RSS deduped to {len(articles)} articles for {date.isoformat()}")
    return LinkAggregationResult.from_steps([step])  # :contentReference[oaicite:4]{index=4}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_date = datetime.date(2025, 12, 18)
    res = scrape(test_date)
    print(res)
