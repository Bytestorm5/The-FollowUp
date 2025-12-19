import re
import unicodedata
import datetime as _dt
from typing import Optional


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text or "item"


def _date_suffix(d: Optional[_dt.date]) -> Optional[str]:
    if not d:
        return None
    try:
        return d.strftime("%Y-%m-%d")
    except Exception:
        return None


def generate_unique_slug(collection, base_text: str, *, date: Optional[_dt.date] = None) -> str:
    """Generate a unique slug for a Mongo collection.

    Tries:
    - base slug
    - base-YYYY-MM-DD (if date provided)
    - base-2, base-3, ... until unique
    """
    base = slugify(base_text or "")
    if not base:
        base = "item"

    # 1) Try bare base
    if collection.count_documents({"slug": base}, limit=1) == 0:
        return base

    # 2) Try with date suffix if given
    ds = _date_suffix(date)
    if ds:
        candidate = f"{base}-{ds}"
        if collection.count_documents({"slug": candidate}, limit=1) == 0:
            return candidate

    # 3) Iterate with numeric suffixes
    i = 2
    while True:
        candidate = f"{base}-{i}"
        if collection.count_documents({"slug": candidate}, limit=1) == 0:
            return candidate
        i += 1
