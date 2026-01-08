import logging
import os
import sys
from typing import Any, Dict

from dotenv import load_dotenv

load_dotenv()

_HERE = os.path.dirname(__file__)
_SERVICE_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _SERVICE_ROOT)

from util import mongo

logger = logging.getLogger(__name__)


def _build_missing_filter(field: str) -> Dict[str, Any]:
    return {
        '$or': [
            {field: {'$exists': False}},
            {field: None},
            {field: ''},
        ]
    }


def backfill_articles() -> int:
    coll = getattr(mongo, 'bronze_links', None)
    if coll is None:
        logger.error('bronze_links collection not available')
        return 0
    result = coll.update_many(
        _build_missing_filter('neutral_headline'),
        [{'$set': {'neutral_headline': '$title'}}],
    )
    return int(getattr(result, 'modified_count', 0) or 0)


def backfill_claims() -> int:
    coll = getattr(mongo, 'silver_claims', None)
    if coll is None:
        logger.error('silver_claims collection not available')
        return 0
    result = coll.update_many(
        _build_missing_filter('neutral_headline'),
        [{'$set': {'neutral_headline': '$claim'}}],
    )
    return int(getattr(result, 'modified_count', 0) or 0)


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    articles_updated = backfill_articles()
    claims_updated = backfill_claims()
    logger.info('Backfilled neutral_headline on %d article(s) and %d claim(s)', articles_updated, claims_updated)


if __name__ == '__main__':
    run()
