import datetime
import json
import logging
import os
import re
import sys
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterable, List, Optional

import requests

_HERE = os.path.dirname(__file__)
_SERVICE_ROOT = os.path.abspath(os.path.join(_HERE, '..', '..'))
if _SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _SERVICE_ROOT)
from util.whisper_transcribe import extract_whisper_text
from models import ArticleLink, LinkAggregationResult

LOGGER = logging.getLogger(__name__)

#DEFAULT_CHANNELS: List[Dict[str, Any]] = []

_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


def _load_channels() -> List[Dict[str, Any]]:
    channels: List[Dict[str, Any]] = [
        {
            "name": "White House",
            "channel_url": "https://www.youtube.com/@WhiteHouse",
            #"channel_id": "UCYxRlFDqcWM4y7FfpiAN3KQ",
            "tags": ["White House", "YouTube"]
        }
    ]
    return channels


def _extract_channel_id_from_html(html: str) -> Optional[str]:
    for pattern in (
        r'channel_id=([a-zA-Z0-9_-]*)',
        r'"channelId":"(UC[\w-]+)"',
        r'itemprop="channelId"\s+content="(UC[\w-]+)"',
    ):
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    return None


def _resolve_feed_url(channel: Dict[str, Any]) -> Optional[str]:
    feed_url = channel.get("feed_url")
    if isinstance(feed_url, str) and feed_url.strip():
        return feed_url.strip()
    channel_id = channel.get("channel_id")
    if isinstance(channel_id, str) and channel_id.strip():
        return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id.strip()}"
    channel_url = channel.get("channel_url")
    if not isinstance(channel_url, str) or not channel_url.strip():
        return None
    channel_url = channel_url.strip()
    match = re.search(r"/channel/(UC[\w-]+)", channel_url)
    if match:
        return f"https://www.youtube.com/feeds/videos.xml?channel_id={match.group(1)}"
    try:
        resp = requests.get(channel_url, timeout=20)
        resp.raise_for_status()
        channel_id = _extract_channel_id_from_html(resp.text)
        if channel_id:
            return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    except Exception as exc:
        LOGGER.warning("Failed to resolve channel id for %s err=%s", channel_url, exc)
    return None


def _iter_feed_entries(xml_text: str) -> Iterable[Dict[str, str]]:
    root = ET.fromstring(xml_text)
    for entry in root.findall("atom:entry", _ATOM_NS):
        title = entry.findtext("atom:title", default="", namespaces=_ATOM_NS)
        link_el = entry.find("atom:link", _ATOM_NS)
        link = ""
        if link_el is not None:
            link = link_el.attrib.get("href", "") or ""
        published = entry.findtext("atom:published", default="", namespaces=_ATOM_NS)
        yield {
            "title": title.strip(),
            "link": link.strip(),
            "published": published.strip(),
        }


def _parse_published_date(published: str) -> Optional[datetime.date]:
    if not published:
        return None
    try:
        normalized = published.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(normalized).date()
    except Exception:
        return None


def _build_tags(channel: Dict[str, Any]) -> List[str]:
    tags: List[str] = ["YouTube"]
    channel_tags = channel.get("tags") or []
    if isinstance(channel_tags, list):
        tags.extend([str(tag) for tag in channel_tags if str(tag).strip()])
    name = channel.get("name")
    if isinstance(name, str) and name.strip():
        tags.append(name.strip())
    return tags


def _fetch_feed(feed_url: str) -> Optional[str]:
    try:
        resp = requests.get(feed_url, timeout=20)
        resp.raise_for_status()
        return resp.text
    except Exception as exc:
        LOGGER.warning("Failed to fetch feed %s err=%s", feed_url, exc)
        return None


def scrape(date: datetime.date, channels: Optional[List[Dict[str, Any]]] = None) -> LinkAggregationResult:
    if channels is None:
        channels = _load_channels()
    if not channels:
        LOGGER.info("No YouTube channels configured; returning empty result.")
        return LinkAggregationResult(articles=[])

    articles: List[ArticleLink] = []
    for channel in channels:
        feed_url = _resolve_feed_url(channel)
        if not feed_url:
            LOGGER.warning("Skipping channel with missing feed resolution: %s", channel)
            continue
        xml_text = _fetch_feed(feed_url)
        if not xml_text:
            continue
        for entry in _iter_feed_entries(xml_text):
            published_date = _parse_published_date(entry.get("published", ""))
            if published_date != date:
                continue
            link = entry.get("link", "")
            if not link:
                continue
            raw_content = extract_whisper_text(link)
            articles.append(
                ArticleLink(
                    title=entry.get("title", "") or link,
                    link=link,
                    date=published_date,
                    tags=_build_tags(channel),
                    raw_content=raw_content,
                    process_posturing=False,
                )
            )
        LOGGER.info("Processed YouTube feed %s", feed_url)
    return LinkAggregationResult(articles=articles)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    today = datetime.date.today() - datetime.timedelta(days=1)
    result = scrape(today)
    print(f"Found {len(result.articles)} videos for {today}")
    [print(x) for x in result.articles]
