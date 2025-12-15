import os
import sys
import datetime
import logging
from typing import Optional, Tuple

import requests
from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString

# Ensure service root is on path (matches existing scraper pattern)
_service_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

from models import ArticleLink, LinkAggregationStep, LinkAggregationResult  # noqa: E402


BASE_URL = "https://www.hud.gov"
NEWS_URL = f"{BASE_URL}/news"  # anchor #PR doesn't change server response


def _abs_url(href: str) -> str:
    if not href:
        return ""
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("/"):
        return f"{BASE_URL}{href}"
    return f"{BASE_URL}/{href}"


def _fetch_soup(url: str, timeout: int = 30) -> BeautifulSoup:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TheFollowUpBot/1.0)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return BeautifulSoup(resp.content, "html.parser")


def _extract_article(url: str) -> str:
    """
    Fetch an individual HUD press release page and return a best-effort "main content" HTML.
    We intentionally keep this resilient (HUD templates can vary across years).
    """
    soup = _fetch_soup(url)

    # Prefer <main>, otherwise fall back to <article>, then body.
    main = soup.find("main")
    if main:
        # Many HUD pages have a single main container; return it as-is.
        return str(main)

    art = soup.find("article")
    if art:
        return str(art)

    body = soup.find("body")
    return str(body) if body else str(soup)


def _parse_press_release_paragraph(p: Tag) -> Optional[Tuple[datetime.date, str, str]]:
    """
    A press release entry looks like:
      <p>Thursday, December 11, 2025<br><a href="/news/hud-no-25-147">Title</a> - Optional Suffix</p>
    Returns (date, title, url) or None if the paragraph isn't a PR entry.
    """
    if not p or p.name != "p":
        return None

    a = p.find("a", href=True)
    if not a:
        return None

    # Date is the first text node before <br/>
    if not p.contents or not isinstance(p.contents[0], NavigableString):
        return None

    date_raw = str(p.contents[0]).strip()
    # Guard against footer links like "More Press Releases"
    if not date_raw or "," not in date_raw:
        return None

    try:
        dt = datetime.datetime.strptime(date_raw, "%A, %B %d, %Y").date()
    except Exception:
        return None

    title = a.get_text(strip=True)

    # Some entries include a trailing region suffix like " - Maryland" after the link.
    # Capture any trailing text nodes after the <a>.
    suffix_parts = []
    for node in a.next_siblings:
        if isinstance(node, NavigableString):
            s = str(node).strip()
            if s:
                suffix_parts.append(s)
        elif isinstance(node, Tag):
            # Rare, but if there's an <em> or similar outside the <a>
            s = node.get_text(" ", strip=True)
            if s:
                suffix_parts.append(s)

    if suffix_parts:
        title = f"{title} {' '.join(suffix_parts)}".strip()

    url = _abs_url(a["href"])
    if not url:
        return None

    return dt, title, url


def _scrape_page(url: str, scrape_date: datetime.date) -> LinkAggregationStep:
    soup = _fetch_soup(url)
    logging.getLogger(__name__).info(f"Scraped {url}")

    # The PR section is anchored by <h2 id="PR">Press Releases</h2>
    pr_h2 = soup.find("h2", id="PR")
    if not pr_h2:
        logging.getLogger(__name__).warning("Could not find PR section (h2#PR).")
        return LinkAggregationStep(articles=[], look_further=False)

    # Entries live under the first .newsbox .collapse after the PR header.
    newsbox = pr_h2.find_next("div", class_="newsbox")
    collapse = newsbox.find("div", class_="collapse") if newsbox else None
    if not collapse:
        logging.getLogger(__name__).warning("Could not find PR collapse container under PR section.")
        return LinkAggregationStep(articles=[], look_further=False)

    articles = []

    # Paragraphs are in reverse chronological order across months/years.
    for p in collapse.find_all("p"):
        parsed = _parse_press_release_paragraph(p)
        if not parsed:
            continue

        dt, title, link = parsed

        # Skip newer-than-target; stop once we pass older-than-target.
        if dt > scrape_date:
            continue
        if dt < scrape_date:
            break

        articles.append(
            ArticleLink(
                title=title,
                link=link,
                date=dt,
                tags=["Press Release", "HUD"],
                process_posturing=True,
                raw_content=_extract_article(link),
            )
        )

    # No pagination on HUD News: everything is on one page.
    return LinkAggregationStep(articles=articles, look_further=False)


def scrape(date: datetime.date) -> LinkAggregationResult:
    step = _scrape_page(NEWS_URL, date)
    return LinkAggregationResult.from_steps([step])


if __name__ == "__main__":
    # Example:
    d = datetime.date(2025, 12, 11)
    print(scrape(d))
