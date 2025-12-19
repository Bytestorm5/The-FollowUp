"""
Backfill missing slugs for bronze_links and silver_claims collections.

Usage (Windows cmd):
  python service\scripts\backfill_slugs.py --limit 1000
  python service\scripts\backfill_slugs.py --dry-run

Reads Mongo connection from util.mongo (MONGO_URI env).
Generates unique slugs using util.slug.generate_unique_slug.
"""

import os
import sys
import logging
from typing import Optional

_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from util import mongo  # type: ignore
from util.slug import generate_unique_slug  # type: ignore

logger = logging.getLogger(__name__)


def _as_date(val) -> Optional["datetime.date"]:
    import datetime as _dt
    if val is None:
        return None
    if isinstance(val, _dt.datetime):
        return val.date()
    if isinstance(val, _dt.date):
        return val
    if isinstance(val, str):
        s = val.strip()
        try:
            # Try ISO date or datetime
            if "T" in s or ":" in s:
                return _dt.datetime.fromisoformat(s.replace("Z", "+00:00")).date()
            return _dt.date.fromisoformat(s)
        except Exception:
            return None
    return None


def backfill_bronze(limit: Optional[int] = None, dry_run: bool = False) -> int:
    coll = getattr(mongo, "bronze_links", None)
    if coll is None:
        logger.error("bronze_links collection not available")
        return 0

    filter_missing = {"$or": [{"slug": {"$exists": False}}, {"slug": None}, {"slug": ""}]}
    cursor = coll.find(filter_missing).sort("inserted_at", 1)
    if limit:
        cursor = cursor.limit(limit)
    updated = 0
    for doc in cursor:
        try:
            base_text = doc.get("title") or doc.get("link") or "article"
            d = _as_date(doc.get("date"))
            slug = generate_unique_slug(coll, base_text, date=d)
            if dry_run:
                logger.info("[DRY-RUN] bronze_links _id=%s slug=%s", doc.get("_id"), slug)
            else:
                coll.update_one({"_id": doc.get("_id")}, {"$set": {"slug": slug}})
                updated += 1
        except Exception:
            logger.exception("Failed to backfill slug for bronze_links _id=%s", doc.get("_id"))
    return updated


def backfill_claims(limit: Optional[int] = None, dry_run: bool = False) -> int:
    coll = getattr(mongo, "silver_claims", None)
    if coll is None:
        logger.error("silver_claims collection not available")
        return 0

    filter_missing = {"$or": [{"slug": {"$exists": False}}, {"slug": None}, {"slug": ""}]}
    cursor = coll.find(filter_missing).sort("_id", 1)
    if limit:
        cursor = cursor.limit(limit)
    updated = 0
    for doc in cursor:
        try:
            base_text = doc.get("claim") or doc.get("verbatim_claim") or "claim"
            d = _as_date(doc.get("article_date"))
            slug = generate_unique_slug(coll, base_text, date=d)
            if dry_run:
                logger.info("[DRY-RUN] silver_claims _id=%s slug=%s", doc.get("_id"), slug)
            else:
                coll.update_one({"_id": doc.get("_id")}, {"$set": {"slug": slug}})
                updated += 1
        except Exception:
            logger.exception("Failed to backfill slug for silver_claims _id=%s", doc.get("_id"))
    return updated


def main():
    import argparse
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser(description="Backfill missing slugs for bronze_links and silver_claims")
    p.add_argument("--limit", type=int, default=None, help="Max documents per collection to process")
    p.add_argument("--dry-run", action="store_true", help="Do not write changes; only log actions")
    args = p.parse_args()

    b = backfill_bronze(limit=args.limit, dry_run=args.dry_run)
    c = backfill_claims(limit=args.limit, dry_run=args.dry_run)
    logger.info("Backfill complete: bronze_links updated=%s, silver_claims updated=%s", b, c)


if __name__ == "__main__":
    main()
