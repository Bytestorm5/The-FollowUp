"""
Deduplicate scheduled follow-ups by (claim_id, follow_up_date).

Guarantee: At most one followup exists for a given claim at a given date.

Heuristics for keeping one:
- Prefer a document with processed_at (already handled) if present; keep the earliest created_at among processed
- Otherwise keep the earliest created_at among unprocessed

Usage (Windows cmd):
  python service\scripts\dedupe_followups.py --dry-run
  python service\scripts\dedupe_followups.py --limit 100
"""

import os
import sys
import logging
from typing import Any, Dict, List

_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from util import mongo  # type: ignore

logger = logging.getLogger(__name__)


def _flatten_docs(docs: List[Dict[str, Any]]):
    processed = [d for d in docs if d.get("processed_at")]
    unprocessed = [d for d in docs if not d.get("processed_at")]
    # sort by created_at ascending, then _id ascending to stabilize
    def _key(d):
        return (d.get("created_at"), str(d.get("_id")))
    processed.sort(key=_key)
    unprocessed.sort(key=_key)
    # choose keep
    keep = processed[0] if processed else unprocessed[0]
    delete_candidates = [d for d in docs if str(d.get("_id")) != str(keep.get("_id"))]
    return keep, delete_candidates


def find_duplicate_groups(limit: int | None = None):
    coll = mongo.DB.get_collection("silver_followups")
    pipeline = [
        {
            "$group": {
                "_id": {"claim_id": "$claim_id", "follow_up_date": "$follow_up_date"},
                "ids": {"$push": {"_id": "$_id", "created_at": "$created_at", "processed_at": "$processed_at"}},
                "count": {"$sum": 1},
            }
        },
        {"$match": {"count": {"$gt": 1}}},
        {"$limit": limit if isinstance(limit, int) and limit > 0 else 10_000},
    ]
    return list(coll.aggregate(pipeline))


def dedupe(limit: int | None = None, dry_run: bool = True) -> dict:
    coll = mongo.DB.get_collection("silver_followups")
    groups = find_duplicate_groups(limit=limit)
    total_groups = len(groups)
    deleted = 0
    kept = 0
    for g in groups:
        docs = g.get("ids", [])
        if len(docs) < 2:
            continue
        keep, del_list = _flatten_docs(docs)
        kept += 1
        if dry_run:
            logger.info("[DRY-RUN] keep=%s delete=%s for claim=%s date=%s", keep.get("_id"), [d.get("_id") for d in del_list], g.get("_id", {}))
            continue
        for d in del_list:
            try:
                coll.delete_one({"_id": d.get("_id")})
                deleted += 1
            except Exception:
                logger.exception("Failed to delete dup followup _id=%s", d.get("_id"))
    return {"groups": total_groups, "kept": kept, "deleted": deleted, "dry_run": dry_run}


def main():
    import argparse
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser(description="Deduplicate scheduled follow-ups by (claim_id, follow_up_date)")
    p.add_argument("--limit", type=int, default=None, help="Max duplicate groups to process")
    p.add_argument("--dry-run", action="store_true", help="Do not delete; only log actions")
    args = p.parse_args()
    res = dedupe(limit=args.limit, dry_run=args.dry_run)
    logger.info("Dedup result: %s", res)


if __name__ == "__main__":
    main()
