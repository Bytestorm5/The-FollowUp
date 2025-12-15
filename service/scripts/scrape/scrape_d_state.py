import os
import sys
import datetime
import logging
from typing import List, Optional, Tuple, Set

import requests
from bs4 import BeautifulSoup

# Ensure service root is importable (matches pattern used in other scrapers)
_service_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

from models import ArticleLink, LinkAggregationResult, LinkAggregationStep
import util.scrape_utils as SU

LOG = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TheFollowUpBot/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

COLLECTIONS: List[Tuple[str, str]] = [
    ("Press Releases", "https://www.state.gov/press-releases/page/{{PAGE}}/"),
    ("Remarks (Secretary Rubio)", "https://www.state.gov/remarks-secretary-rubio/page/{{PAGE}}/"),
    ("Department Press Briefings", "https://www.state.gov/department-press-briefings/page/{{PAGE}}/"),
]


def _get(url: str, timeout: int = 25) -> requests.Response:
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return resp


def _extract_article(url: str) -> str:
    """
    Extract the primary article content for a DoS item.
    We keep this fairly generic and resilient across post types.
    """
    resp = _get(url)
    soup = BeautifulSoup(resp.content, "html.parser")

    main = soup.find("main")
    if not main:
        return str(soup)

    # Remove obvious non-content noise
    for tag in main.find_all(["script", "style", "noscript"]):
        tag.decompose()

    # Prefer the article node if present
    article = main.find("article")
    if article:
        return str(article)

    # Fallback to main
    return str(main)


def _parse_listing_items(soup: BeautifulSoup) -> List[Tuple[str, str, Optional[str], Optional[datetime.date]]]:
    """
    Returns tuples of: (title, link, item_type, date)
    """
    ul = soup.find("ul", class_="collection-results")
    if not ul:
        return []

    items = []
    for li in ul.find_all("li", class_="collection-result"):
        a = li.find("a", class_="collection-result__link") or li.find("a")
        if not a:
            continue

        title = a.get_text(" ", strip=True)
        link = a.get("href", "").strip()
        if not title or not link:
            continue

        item_type = None
        p_type = li.find("p", class_="collection-result__date")
        if p_type:
            item_type = p_type.get_text(" ", strip=True) or None

        parsed_date = None
        meta = li.find("div", class_="collection-result-meta")
        if meta:
            spans = meta.find_all("span")
            # Date is commonly one of the spans (sometimes the only span)
            for sp in reversed(spans):
                txt = sp.get_text(" ", strip=True)
                try:
                    parsed_date = datetime.datetime.strptime(txt, "%B %d, %Y").date()
                    break
                except Exception:
                    continue
        else:
            # Some variants might put the date elsewhere; try any time-like node
            time_tag = li.find("time")
            if time_tag:
                txt = time_tag.get_text(" ", strip=True)
                try:
                    parsed_date = datetime.datetime.strptime(txt, "%B %d, %Y").date()
                except Exception:
                    parsed_date = None

        items.append((title, link, item_type, parsed_date))

    return items


def _scrape_page_factory(collection_tag: str):
    """
    Builds a scrape_page(url, scrape_date) function bound to a specific collection tag.
    """

    def _scrape_page(url: str, scrape_date: datetime.date) -> LinkAggregationStep:
        resp = _get(url)
        soup = BeautifulSoup(resp.content, "html.parser")
        LOG.info(f"[DoS] Scraped listing page: {url}")

        rows = _parse_listing_items(soup)
        LOG.info(f"[DoS] Found {len(rows)} items on {url}")

        articles: List[ArticleLink] = []
        look_further = True

        for title, link, item_type, item_date in rows:
            if not item_date:
                # If we can't parse a date, skip (don't let it kill pagination)
                continue

            # Listings are newest->oldest. Skip newer than target.
            if item_date > scrape_date:
                continue

            # Once we pass the target date, we can stop paginating.
            if item_date < scrape_date:
                look_further = False
                break

            tags = [collection_tag]
            if item_type:
                tags.append(item_type)

            articles.append(
                ArticleLink(
                    title=title,
                    link=link,
                    date=item_date,
                    tags=tags,
                    process_posturing=True,
                    raw_content=_extract_article(link),
                )
            )

        LOG.info(f"[DoS] Kept {len(articles)} items from {url}. Look Further: {look_further}")
        return LinkAggregationStep(articles=articles, look_further=look_further)

    return _scrape_page


def scrape(date: datetime.date) -> LinkAggregationResult:
    """
    Aggregate all three Department of State collections for a given date.
    """
    all_articles: List[ArticleLink] = []
    seen: Set[str] = set()

    for collection_tag, url_template in COLLECTIONS:
        scrape_fn = _scrape_page_factory(collection_tag)
        res = SU.iter_scrape(url_template, 1, date, scrape_fn)

        for a in res.articles:
            if a.link in seen:
                continue
            seen.add(a.link)
            all_articles.append(a)

    all_articles = sorted(all_articles, key=lambda x: x.date, reverse=True)
    return LinkAggregationResult(articles=all_articles)


if __name__ == "__main__":
    d = datetime.date(2025, 12, 14)
    out = scrape(d)
    print(out)
