import datetime as _dt
from typing import Optional


def _now_utc() -> _dt.datetime:
    return _dt.datetime.utcnow().replace(tzinfo=None)


def acquire_lock(collection, doc_id, lock_field: str, owner: str, ttl_seconds: int = 3600) -> bool:
    """Attempt to acquire a time-based lock on a document.

    Lock succeeds if no lock present or the existing lock is expired.
    Creates/updates `{lock_field}: {locked_at, owner}`.
    Returns True if lock acquired, else False.
    """
    now = _now_utc()
    expire_before = now - _dt.timedelta(seconds=ttl_seconds)
    query = {
        "_id": doc_id,
        "$or": [
            {lock_field: {"$exists": False}},
            {f"{lock_field}.locked_at": {"$lt": expire_before}},
        ],
    }
    update = {
        "$set": {lock_field: {"locked_at": now, "owner": owner}},
    }
    res = collection.find_one_and_update(query, update)
    return res is not None


def release_lock(collection, doc_id, lock_field: str) -> None:
    try:
        collection.update_one({"_id": doc_id}, {"$unset": {lock_field: ""}})
    except Exception:
        pass
