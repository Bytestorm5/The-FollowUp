import os
import sys
import re
import datetime
import logging
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

# Match existing scraper layout: this file typically lives under a scraper subdir.
_service_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

from models import ArticleLink, LinkAggregationStep, LinkAggregationResult
import util.scrape_utils as SU


DOE_BASE = "https://www.energy.gov"


def _abs_url(href: str) -> str:
    if not href:
        return ""
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return DOE_BASE + href
    return DOE_BASE.rstrip("/") + "/" + href


_DATE_RE = re.compile(r"^[A-Z][a-z]+\s+\d{1,2},\s+\d{4}$")


def _parse_date(txt: str) -> Optional[datetime.date]:
    txt = (txt or "").strip()
    if not txt:
        return None
    try:
        return datetime.datetime.strptime(txt, "%B %d, %Y").date()
    except Exception:
        return None


def _extract(url: str) -> str:
    """Fetch and return a best-effort HTML snippet for the article content."""
    hdrs = {"User-Agent": "Mozilla/5.0 (compatible; TheFollowUpBot/1.0)"}
    resp = requests.get(url, headers=hdrs, timeout=25, allow_redirects=True)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "html.parser")

    # Prefer <main>, fallback to first <article>, else body.
    root = soup.find("main") or soup.find("article") or soup.body
    if not root:
        return ""

    # Remove obvious boilerplate.
    for tag in root.find_all(["script", "style", "noscript"]):
        tag.decompose()
    for sel in ["header", "footer", "nav", "form", "aside"]:
        for tag in root.find_all(sel):
            tag.decompose()

    return str(root)


def _extract_tags(li: BeautifulSoup) -> List[str]:
    tags: List[str] = []

    # Primary type tags
    for t in li.select("span.usa-tag"):
        val = t.get_text(strip=True)
        if val:
            tags.append(val)

    # Secondary chips (site / office labels)
    for t in li.select("span.MuiChip-label"):
        val = t.get_text(strip=True)
        if val:
            tags.append(val)

    # Dedupe while preserving order
    seen = set()
    out = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _find_result_items(soup: BeautifulSoup):
    """Locate the search result <li> blocks.

    The DOE search page is rendered as a React app, but the HTML includes
    the result list as <ul class="MuiList-root ..."> with <li class="MuiListItem-root ...">.
    """
    # Prefer the obvious list container.
    ul = soup.find("ul", class_=re.compile(r"MuiList-root"))
    if ul:
        return ul.find_all("li", class_=re.compile(r"MuiListItem-root"))

    # Fallback: scan for list items that contain a usa-tag and a link.
    candidates = []
    for li in soup.find_all("li"):
        if li.select_one("span.usa-tag") and li.find("a", href=True):
            candidates.append(li)
    return candidates


def _scrape_page(url: str, scrape_date: datetime.date) -> LinkAggregationStep:
    hdrs = {
        "User-Agent": "Mozilla/5.0 (compatible; TheFollowUpBot/1.0)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    resp = requests.get(url, headers=hdrs, timeout=25, allow_redirects=True)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "html.parser")

    items = _find_result_items(soup)
    logging.getLogger(__name__).info(f"Scraped {url} - found {len(items)} result items")

    articles: List[ArticleLink] = []
    seen_links = set()

    # Strategy for a descending-by-date feed:
    # - ignore items newer than scrape_date
    # - collect items exactly on scrape_date
    # - once we hit an item older than scrape_date, stop (and stop paging)
    look_further = True
    for li in items:
        a = li.find("a", href=True)
        if not a:
            continue

        title = a.get_text(strip=True)
        link = _abs_url(a.get("href", ""))
        if not title or not link:
            continue

        # Find a date string like "December 10, 2025" inside the list item.
        date_str = None
        for node in li.find_all(["span", "p"], string=True):
            txt = (node.get_text(strip=True) or "").strip()
            if _DATE_RE.match(txt):
                date_str = txt
                break
        item_date = _parse_date(date_str or "")
        if not item_date:
            # If DOE changes markup, we still want the link, but date is required by our model.
            # Skip rather than guessing.
            continue

        if item_date > scrape_date:
            continue
        if item_date < scrape_date:
            look_further = False
            break

        if link in seen_links:
            continue
        seen_links.add(link)

        tags = _extract_tags(li)
        raw_content = _extract(link)

        articles.append(
            ArticleLink(
                title=title,
                link=link,
                date=item_date,
                tags=tags + ['Department of Energy'],
                raw_content=raw_content,
                process_posturing=True,
            )
        )

    return LinkAggregationStep(articles=articles, look_further=look_further)


def scrape(date: datetime.date) -> LinkAggregationResult:
    """Scrape the DOE search page using the provided filters.

    NOTE: The URL below mirrors the filtered search page and only varies `page=`.
    """

    url_template = (
        "https://www.energy.gov/search?page={{PAGE}}&sort_by=date"
        "&f%5B0%5D=article_type%3A1"
        "&f%5B1%5D=article_type%3A430933"
        "&f%5B2%5D=article_type%3A430939"
        "&f%5B3%5D=article_type%3A1380643"
        "&f%5B4%5D=content_type_rest%3Aarticle"
    )

    res = SU.iter_scrape(url_template, 0, date, _scrape_page)

    # Cross-page dedupe (iter_scrape aggregates blindly).
    uniq = []
    seen = set()
    for a in res.articles:
        if a.link in seen:
            continue
        seen.add(a.link)
        uniq.append(a)
    res.articles = uniq
    return res


if __name__ == "__main__":
    # Example: scrape yesterday in America/New_York.
    d = datetime.date.today() - datetime.timedelta(days=1)
    print(scrape(d))
