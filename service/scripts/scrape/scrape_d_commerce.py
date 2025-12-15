import os
import sys
import datetime
import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup

# Match your existing repo structure (same idea as scrape_wh.py)
_service_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

from models import ArticleLink, LinkAggregationStep, LinkAggregationResult  # :contentReference[oaicite:5]{index=5}
import util.scrape_utils as SU  # :contentReference[oaicite:6]{index=6}


BASE = "https://www.commerce.gov"
LOG = logging.getLogger(__name__)

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def _safe_get(url: str):
    """Thin wrapper that calls the shared `SU.playwright_get` utility.

    Keeping a local `_safe_get` preserves the existing scraper interface.
    """
    return SU.playwright_get(url, timeout=15, headers=_DEFAULT_HEADERS)


def _extract(article_url: str) -> str:
    """Fetch and return the main content HTML of an article page."""
    resp = _safe_get(article_url)
    soup = BeautifulSoup(resp.content, "html.parser")
    LOG.info(f"Scraped Content Page {article_url}")

    main = soup.find("main")
    if not main:
        # Fallback: return full document if structure changes
        return str(soup)

    return str(main)


def _parse_list_date(article: BeautifulSoup) -> datetime.date | None:
    """
    Commerce.gov listing pages usually have:
      <div class="field--name-field-release-datetime"> <time class="datetime">Month DD, YYYY</time>
    but some 'Blog / tweets' entries may have an empty <time> in listings.
    """
    # Preferred: release datetime field
    time_tag = article.select_one("div.field--name-field-release-datetime time.datetime")
    if time_tag and time_tag.get_text(strip=True):
        txt = time_tag.get_text(strip=True)
        try:
            return datetime.datetime.strptime(txt, "%B %d, %Y").date()
        except ValueError:
            return None

    # Fallback: any time.datetime with actual text (some templates may differ)
    time_tag = article.select_one("time.datetime")
    if time_tag and time_tag.get_text(strip=True):
        txt = time_tag.get_text(strip=True)
        try:
            return datetime.datetime.strptime(txt, "%B %d, %Y").date()
        except ValueError:
            return None

    return None


def _scrape_page(url: str, min_date: datetime.date) -> LinkAggregationStep:
    """
    min_date is the *previous day* (input).
    max_date is computed as min_date + 1 day (the present day), per your requirement.
    """
    max_date = min_date + datetime.timedelta(days=1)

    resp = _safe_get(url)
    soup = BeautifulSoup(resp.content, "html.parser")
    LOG.info(f"Scraped {url}")

    articles_out: list[ArticleLink] = []

    nodes = soup.select("div.view-content div.views-row article")
    LOG.info(f"Found {len(nodes)} posts on {url}")

    if not nodes:
        return LinkAggregationStep(articles=articles_out, look_further=False)

    look_further = True

    for node in nodes:
        a = node.select_one("h2 a")
        if not a:
            continue

        title = a.get_text(strip=True)
        href = a.get("href", "").strip()
        link = urljoin(BASE, href)

        news_type_el = node.select_one("div.field--name-field-news-type")
        news_type = news_type_el.get_text(strip=True) if news_type_el else "News"

        # Optional: collect issues/tags shown on the card (Press Releases usually have these)
        tag_texts: list[str] = []
        tag_texts.append(news_type)

        for t in node.select("div.field--name-field-issues a, div.field--name-field-tags a"):
            txt = t.get_text(strip=True)
            if txt:
                tag_texts.append(txt)

        # De-dupe while preserving order
        seen = set()
        tags = []
        for t in tag_texts:
            if t not in seen:
                seen.add(t)
                tags.append(t)

        date_val = _parse_list_date(node)
        # If listing omits the date (some Blog/tweets cards), assume it's within the filtered range.
        if date_val is None:
            date_val = max_date

        # Safety stop: if pagination ever leaks older posts, stop once we drop below min_date.
        # (Listing is typically in reverse chronological order.)
        if date_val < min_date:
            look_further = False
            break

        # Keep only articles within [min_date, max_date]
        if min_date <= date_val <= max_date:
            articles_out.append(
                ArticleLink(
                    title=title,
                    link=link,
                    date=date_val,
                    tags=tags,
                    process_posturing=True,
                    raw_content=_extract(link),
                )
            )

    return LinkAggregationStep(articles=articles_out, look_further=look_further)


def scrape(date: datetime.date) -> LinkAggregationResult:
    """
    date: expected to be the previous day (min).
    We automatically set max = date + 1 day (present day).
    """
    min_str = date.isoformat()
    max_str = (date + datetime.timedelta(days=1)).isoformat()

    # Params match the site's filter names: field_release_datetime_value[min/max]:contentReference[oaicite:7]{index=7}
    # Commerce.gov pagination is Drupal-style and usually starts at page=0.
    url_template = (
        "https://www.commerce.gov/news"
        f"?field_release_datetime_value%5Bmin%5D={min_str}"
        f"&field_release_datetime_value%5Bmax%5D={max_str}"
        "&page={{PAGE}}"
    )

    # SU.iter_scrape replaces {{PAGE}} and keeps going while look_further is True:contentReference[oaicite:8]{index=8}
    return SU.iter_scrape(url_template, start_page=0, date=date, scrape_fn=_scrape_page)


if __name__ == "__main__":
    # Example: input is the previous day => max automatically becomes +1 day (today)
    d = datetime.date(2025, 12, 12)
    res = scrape(d)
    print(res)
