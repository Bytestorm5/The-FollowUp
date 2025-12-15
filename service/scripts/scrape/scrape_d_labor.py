import os
import sys
import datetime
import logging
from typing import Set
from zoneinfo import ZoneInfo

# Ensure service root is on sys.path (matches existing scraper style) :contentReference[oaicite:2]{index=2}
_service_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

from models import ArticleLink, LinkAggregationStep, LinkAggregationResult  # :contentReference[oaicite:3]{index=3}
import util.scrape_utils as SU  # provides read_rss_feed :contentReference[oaicite:4]{index=4}

FEED_URL = "https://www.dol.gov/rss/releases.xml"
#LOCAL_TZ = ZoneInfo("America/New_York")


def _scrape_feed(feed_url: str, scrape_date: datetime.date) -> LinkAggregationStep:
    """
    Pull DOL releases RSS and return only items whose published date == scrape_date.
    Assumes feed is newest-first; once we see an item older than scrape_date, we stop.
    """
    items = SU.read_rss_feed(feed_url)  # :contentReference[oaicite:5]{index=5}
    articles = []
    look_further = True

    seen_links: Set[str] = set()

    for it in items:
        pub = it.get("published")
        if not pub:
            continue

        # Normalize to America/New_York before date comparison (pubDate is often tz-aware)
        #pub_local = pub.astimezone(LOCAL_TZ) if getattr(pub, "tzinfo", None) else pub
        item_date = pub.date()

        if item_date > scrape_date:
            # Future-dated (or later than target); ignore and keep scanning
            continue

        if item_date < scrape_date:
            # Older than target date; stop scanning further
            look_further = False
            break

        title = (it.get("title") or "").strip()
        link = (it.get("link") or "").strip()
        if not title or not link or link in seen_links:
            continue

        seen_links.add(link)

        summary = (it.get("summary") or "").strip()

        articles.append(
            ArticleLink(
                title=title,
                link=link,
                date=item_date,
                tags=["DOL", "Release"],
                raw_content=summary,          # RSS-provided content/description :contentReference[oaicite:6]{index=6}
                process_posturing=True,
            )
        )

    return LinkAggregationStep(articles=articles, look_further=look_further)  # :contentReference[oaicite:7]{index=7}


def scrape(date: datetime.date) -> LinkAggregationResult:
    step = _scrape_feed(FEED_URL, date)
    return LinkAggregationResult.from_steps([step])  # :contentReference[oaicite:8]{index=8}


if __name__ == "__main__":
    test_date = datetime.date(2025, 12, 12)
    print(scrape(test_date))
