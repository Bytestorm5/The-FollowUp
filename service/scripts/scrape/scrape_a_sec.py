import os
import sys
import datetime
import logging
from typing import Dict, List, Optional, Tuple

# Ensure service root is on sys.path (mirrors existing scraper layout)
_service_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

from models import ArticleLink, LinkAggregationStep, LinkAggregationResult
import util.scrape_utils as SU

LOGGER = logging.getLogger(__name__)

SEC_TAG = "Agency // Securities and Exchange Commission"

FEEDS: List[Tuple[str, str]] = [
    ("https://www.sec.gov/news/pressreleases.rss", "Press Release"),
    ("https://www.sec.gov/news/speeches-statements.rss", "Speech/Statement"),
]


def _to_date(dt: Optional[datetime.datetime]) -> Optional[datetime.date]:
    if not dt:
        return None
    try:
        # Normalize tz-aware datetimes to UTC for stable comparisons
        if dt.tzinfo is not None:
            return dt.astimezone(datetime.timezone.utc).date()
        return dt.date()
    except Exception:
        return None


def _merge_tags(existing: List[str], new_tags: List[str]) -> List[str]:
    # Dedupe while preserving order
    out: List[str] = []
    seen = set()
    for t in (existing or []) + (new_tags or []):
        t = (t or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _add_or_merge(by_link: Dict[str, ArticleLink], article: ArticleLink) -> None:
    """
    Deduplicate by link; if a duplicate appears across feeds, merge tags and keep
    the more informative raw_content when possible.
    """
    if article.link in by_link:
        existing = by_link[article.link]
        merged_tags = _merge_tags(existing.tags, article.tags)

        raw = existing.raw_content or ""
        incoming_raw = article.raw_content or ""
        if len(incoming_raw) > len(raw):
            raw = incoming_raw

        by_link[article.link] = existing.model_copy(update={"tags": merged_tags, "raw_content": raw})
    else:
        by_link[article.link] = article


def scrape(date: datetime.date) -> LinkAggregationResult:
    """
    Scrape SEC RSS feeds and return items whose published date matches `date`.

    Notes:
    - RSS feeds typically include only recent items; no pagination.
    - We filter by published date when present; items with no published date are skipped.
    - All items include the required SEC tag.
    """
    LOGGER.info("Scraping SEC RSS feeds for date=%s", date.isoformat())

    by_link: Dict[str, ArticleLink] = {}

    for feed_url, feed_kind in FEEDS:
        try:
            items = SU.read_rss_feed(feed_url)
        except Exception as e:
            LOGGER.exception("Failed to read SEC RSS feed %s: %s", feed_url, e)
            continue

        LOGGER.info("SEC RSS: %s -> %d items", feed_url, len(items))

        for it in items:
            title = (it.get("title") or "").strip()
            link = (it.get("link") or "").strip()
            pub_dt = it.get("published")
            summary = (it.get("summary") or "").strip()

            if not title or not link:
                continue

            item_date = _to_date(pub_dt)
            if not item_date:
                # SEC feeds should include pubDate, but if missing, skip rather than guessing.
                continue

            if item_date != date:
                continue

            tags = [SEC_TAG, feed_kind]

            art = ArticleLink(
                title=title,
                link=link,
                date=item_date,
                tags=tags,
                raw_content=summary,
                process_posturing=True,
            )
            _add_or_merge(by_link, art)

    articles = list(by_link.values())
    # Deterministic ordering: newest first, then title.
    articles.sort(key=lambda a: (a.date, a.title), reverse=True)

    step = LinkAggregationStep(articles=articles, look_further=False)
    LOGGER.info("SEC RSS: returning %d deduped articles for %s", len(articles), date.isoformat())
    return LinkAggregationResult.from_steps([step])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Example: scrape yesterday (adjust as needed)
    d = datetime.date(2025, 12, 17)
    print(scrape(d))
