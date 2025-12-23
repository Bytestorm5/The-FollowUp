from enum import Enum
import os
import sys
from typing import Any, List, Tuple, Optional
from dotenv import load_dotenv
import datetime
import json
import time
import logging



import pymongo
from bson import ObjectId

_HERE = os.path.dirname(__file__)
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _REPO_ROOT not in sys.path:
	sys.path.insert(0, _REPO_ROOT)

load_dotenv(os.path.join(_REPO_ROOT, ".env"))

from util import mongo
from util.llm_web import run_with_search
from models import MongoClaim, Date_Delta, SilverUpdate, MongoArticle, ModelResponseOutput, SilverFollowup, FactCheckResponseOutput

try:
    from pydantic_core._pydantic_core import ValidationError as PydanticCoreValidationError
except Exception:
    PydanticCoreValidationError = None

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

def _is_terminal_verdict(v: Optional[str]) -> bool:
    if not v:
        return False
    s = str(v).strip().lower()
    # New categories
    if s in ("true", "false"):
        return True
    # Legacy categories
    if s in ("complete", "failed"):
        return True
    return False

def get_claim_groups() -> Tuple[List[Tuple[Any, MongoClaim]], List[Tuple[Any, MongoClaim]], List[Tuple[Any, MongoClaim]]]:
    """Return (promises, goals_fu, statements_fu) groups.

    - promises: always included when not past
    - goals_fu: type=goal and follow_up_worthy=True
    - statements_fu: type=statement and follow_up_worthy=True
    """
    promises_cur = mongo.silver_claims.find({
        '$and': [
            {'$or': [{'date_past': False}, {'date_past': {'$exists': False}}]},
            {'type': 'promise'},
        ]
    })
    goals_cur = mongo.silver_claims.find({'type': 'goal', 'follow_up_worthy': True})
    statements_cur = mongo.silver_claims.find({'type': 'statement', 'follow_up_worthy': True})

    def _collect(cur):
        out: List[Tuple[Any, MongoClaim]] = []
        for raw in cur:
            try:
                out.append((raw, MongoClaim(**raw)))
            except Exception:
                logger.exception(f'Invalid MongoClaim in DB: {raw.get("_id")}')
        return out

    promises = _collect(promises_cur)
    goals_fu = _collect(goals_cur)
    statements_fu = _collect(statements_cur)
    logger.info(f'Found {len(promises)} promises, {len(goals_fu)} goals(follow_up_worthy), {len(statements_fu)} statements(follow_up_worthy).')
    return promises, goals_fu, statements_fu


def _get_pipeline_today():
    """Return pipeline 'today' in fixed UTC-5 unless overridden by env."""
    try:
        from util.timezone import pipeline_today
        return pipeline_today()
    except Exception:
        import os as _os
        import datetime as _dt
        v = _os.environ.get('PIPELINE_RUN_DATE')
        if v:
            try:
                return _dt.date.fromisoformat(v)
            except Exception:
                pass
        return _dt.date.today()


def _write_jsonl(path: str, lines):
    # Deprecated legacy helper
    raise RuntimeError('_write_jsonl is deprecated; use run_with_search directly')

def get_article_from_id(article_id: str) -> MongoArticle:
    article = mongo.bronze_links.find_one({'_id': ObjectId(article_id)})
    if not article:
        raise ValueError(f'No article found with id {article_id}')
    return MongoArticle(**article)
    

def _build_requests(claim_pairs: List[Tuple[Any, MongoClaim]], regular_tpl: str, endpoint_tpl: str, model: Optional[str] = None):
    """Build a list of request descriptors for in-house web search pipeline.

    claim_pairs: iterable of (raw_doc, MongoClaim)
    Each request contains: {custom_id, model, input}
    """
    model = model or os.environ.get('OPENAI_MODEL', 'gpt-5-nano')
    requests = []
    mapping = {}
    for idx, (raw, claim) in enumerate(claim_pairs):
        try:
            update_type = claim_needs_update(claim)
        except Exception:
            logger.exception('Failed to determine update type for claim; skipping')
            continue

        if update_type == UpdateType.ENDPOINT:
            tpl = endpoint_tpl
        elif update_type == UpdateType.REGULAR_INTERVAL:
            tpl = regular_tpl
        else:
            logger.info(f'No update needed for claim {raw.get("_id")} ("{claim.completion_condition}"); skipping')
            continue

        claim_id = raw.get('_id')
        custom_id = f"{claim_id}:{idx}"

        article_date = getattr(claim, 'article_date', None)
        article_date_str = str(article_date) if article_date is not None else ''

        content_parts = [tpl.strip(), "", "-- Article Metadata --"]
        content_parts.append(f"Source Article Link: {getattr(claim, 'article_link', '')}")
        content_parts.append(f"Source Article Date: {article_date_str}")
        content_parts.append(f"Claim: {getattr(claim, 'claim', '')}")
        content_parts.append(f"Verbatim Quote from Article: {getattr(claim, 'verbatim_claim', '')}")
        content_parts.append(f"Completion Condition: {getattr(claim, 'completion_condition', '')}")
        content_parts.append(f"Projected Completion Date: {getattr(claim, 'completion_condition_date', '')}")
        # Use pipeline 'today' (fixed UTC-5) for consistency
        try:
            from util.timezone import pipeline_today as _pt
            _today = _pt()
        except Exception:
            _today = _get_pipeline_today()
        content_parts.append(f"Current Date: {_today}")

        content = "\n".join(content_parts)

        req = {
            "custom_id": str(custom_id),
            "model": model,
            "input": content,
        }
        requests.append(req)
        mapping[str(custom_id)] = (raw, claim, update_type)

    return requests, mapping





# Legacy OpenAI helper code removed — we now use run_with_search with structured outputs.


def _classify_verdict(text: str) -> str:
    t = (text or '').lower()
    if any(k in t for k in ('complete', 'fulfilled', 'succeeded', 'met')):
        return 'complete'
    if any(k in t for k in ('in progress', 'in_progress', 'progress', 'ongoing')):
        return 'in_progress'
    if any(k in t for k in ('fail', 'failed', 'not met', 'not fulfilled', 'did not')):
        return 'failed'
    return 'in_progress'


class UpdateType(Enum):
    ENDPOINT = 1
    REGULAR_INTERVAL = 2
    NO_UPDATE = 3

def claim_needs_update(claim: MongoClaim) -> UpdateType:
    today = _get_pipeline_today()
    if isinstance(claim.completion_condition_date, Date_Delta):
        claim.completion_condition_date = claim.completion_condition_date._resolve_date()
    assert isinstance(claim.completion_condition_date, datetime.date), f'Unexpected date type: {type(claim.completion_condition_date)} - {claim.completion_condition_date}'
    
    if today >= claim.completion_condition_date:
        # Since date_past is not set or false, we've passed the date without updating.
        return UpdateType.ENDPOINT
    
    timespan = claim.completion_condition_date - claim.article_date
    if timespan.days > 90:
        # 30 day interval
        update_date = claim.article_date + datetime.timedelta(days=30)
        while update_date < today:
            update_date += datetime.timedelta(days=30)
            if update_date == today:
                return UpdateType.REGULAR_INTERVAL
        return UpdateType.NO_UPDATE
    elif timespan.days <= 14:
        # Only at the end
        return UpdateType.ENDPOINT if claim.completion_condition_date == today else UpdateType.NO_UPDATE  
    else:
        # Only at midpoint
        update_date = claim.article_date + datetime.timedelta(days=timespan.days / 2)
        return UpdateType.REGULAR_INTERVAL if update_date == today else UpdateType.NO_UPDATE

def next_update_date(claim: MongoClaim, today: datetime.date) -> Optional[datetime.date]:
    """Compute the next planned update date strictly after or on `today`.

    Mirrors the scheduling semantics in `claim_needs_update`:
    - > 90 day window: 30-day cadence up to the completion date, then endpoint
    - <= 14 day window: only endpoint at completion date
    - else (<= 90 and > 14): midpoint, then endpoint at completion date
    Returns None when no sensible future date can be determined.
    """
    if isinstance(claim.completion_condition_date, Date_Delta):
        claim.completion_condition_date = claim.completion_condition_date._resolve_date()

    assert isinstance(claim.completion_condition_date, datetime.date), (
        f'Unexpected date type: {type(claim.completion_condition_date)} - {claim.completion_condition_date}'
    )

    completion = claim.completion_condition_date

    # If we're already at/past completion, endpoint is the intended next action.
    if today >= completion:
        return today

    timespan = completion - claim.article_date

    # Monthly cadence for long windows
    if timespan.days > 90:
        # First 30-day boundary strictly after today (or on today if exact)
        step = claim.article_date + datetime.timedelta(days=30)
        while step <= today:
            step += datetime.timedelta(days=30)
        # Do not schedule beyond completion; use endpoint on completion date
        return step if step <= completion else completion

    # Only endpoint for short windows
    if timespan.days <= 14:
        return completion

    # Single midpoint update, then endpoint
    midpoint_days = timespan.days // 2
    midpoint = claim.article_date + datetime.timedelta(days=midpoint_days)
    if today < midpoint:
        return midpoint
    # After midpoint but before completion, the next is the endpoint
    return completion

def compute_followup_schedule(claim: MongoClaim) -> List[datetime.date]:
    """Return the complete planned follow-up schedule for a claim.

    Rules:
    - > 90 days: every 30 days after `article_date` up to (but not beyond) completion, then the endpoint at completion
    - 14-90 days: single midpoint, then endpoint at completion
    - < 14 days: only the endpoint at completion
    """
    if isinstance(claim.completion_condition_date, Date_Delta):
        claim.completion_condition_date = claim.completion_condition_date._resolve_date()

    assert isinstance(claim.completion_condition_date, datetime.date), (
        f'Unexpected date type: {type(claim.completion_condition_date)} - {claim.completion_condition_date}'
    )

    completion = claim.completion_condition_date
    start = getattr(claim, 'article_date', completion)

    timespan = completion - start
    schedule: List[datetime.date] = []

    if timespan.days > 90:
        step = start + datetime.timedelta(days=30)
        while step < completion:
            schedule.append(step)
            step += datetime.timedelta(days=30)
        schedule.append(completion)
        if len(schedule) > 2 and schedule[-1] - schedule[-2] < datetime.timedelta(days=5):
            # If the last update is close enough to the final date, we can accept a slightly longer window.
            schedule.pop(-2)
    elif timespan.days <= 14:
        schedule.append(completion)
    else:
        midpoint_days = timespan.days // 2
        midpoint = start + datetime.timedelta(days=midpoint_days)
        if midpoint < completion:
            schedule.append(midpoint)
        schedule.append(completion)

    return schedule

def ensure_full_schedule_for_claim(raw: Any, claim: MongoClaim, today: datetime.date, db) -> int:
    """Insert the full future follow-up schedule for a claim if none are scheduled yet.

    - Only inserts dates >= `today`.
    - If any future follow-up already exists (on or after `today`), does nothing.
    - Returns the number of follow-ups inserted.
    """
    try:
        followups_coll = db.get_collection('silver_followups')
    except Exception:
        logger.exception('DB does not expose silver_followups collection')
        return 0

    # If the schedule window has already fully passed, nothing to do
    try:
        completion = claim.completion_condition_date
        if isinstance(completion, Date_Delta):
            completion = completion._resolve_date()
        if not isinstance(completion, datetime.date):
            return 0
        if today > completion:
            return 0
    except Exception:
        logger.exception('Failed to read completion date for claim %s', raw.get('_id'))
        return 0

    # If any future followup already exists, skip scheduling
    try:
        filter_q = { 'claim_id': raw.get('_id'), 'follow_up_date': { '$gte': today } }
        try:
            filter_q = mongo.normalize_dates(filter_q)
        except Exception:
            logger.exception('normalize_dates failed for future-followup existence check; using raw filter')
        if followups_coll.count_documents(filter_q, limit=1) > 0:
            return 0
    except Exception:
        logger.exception('Failed checking existing future followups for claim %s', raw.get('_id'))
        # If in doubt, continue to attempt scheduling rather than silently skipping

    # Build full schedule and filter to future
    try:
        full_schedule = compute_followup_schedule(claim)
    except Exception:
        logger.exception('Failed to compute schedule for claim %s', raw.get('_id'))
        return 0

    future_dates = [d for d in full_schedule if isinstance(d, datetime.date) and d >= today]
    if not future_dates:
        return 0

    inserted = 0
    for d in future_dates:
        follow_doc = {
            'claim_id': raw.get('_id'),
            'claim_text': getattr(claim, 'claim', ''),
            'follow_up_date': d,
            'article_id': getattr(claim, 'article_id', ''),
            'article_link': getattr(claim, 'article_link', ''),
            'model_output': f'Scheduled full plan on {today.isoformat()} (autoplan)',
            'created_at': datetime.datetime.utcnow(),
        }
        try:
            follow_obj = SilverFollowup(**follow_doc)
            final_follow = follow_obj.model_dump() if hasattr(follow_obj, 'model_dump') else follow_obj.dict()
            try:
                final_follow = mongo.normalize_dates(final_follow)
            except Exception:
                logger.exception('Failed to normalize dates for autoplan silver_followup; inserting raw doc')
            # Deduplicate by (claim_id, follow_up_date)
            try:
                if followups_coll.count_documents({ 'claim_id': final_follow.get('claim_id'), 'follow_up_date': final_follow.get('follow_up_date') }, limit=1) == 0:
                    followups_coll.insert_one(final_follow)
                    inserted += 1
            except Exception:
                followups_coll.insert_one(final_follow)
                inserted += 1
        except Exception:
            logger.exception('Failed inserting autoplan followup for claim %s on %s', raw.get('_id'), d)

    return inserted

def _checkin_template() -> str:
    tpl_path = os.path.join(_REPO_ROOT, 'prompts', 'regular_checkin.md')
    with open(tpl_path, 'r', encoding='utf-8') as fh:
        return fh.read()

def _endpoint_template() -> str:
    tpl_path = os.path.join(_REPO_ROOT, 'prompts', 'endpoint_checkin.md')
    with open(tpl_path, 'r', encoding='utf-8') as fh:
        return fh.read()

def _fact_check_template() -> str:
    tpl_path = os.path.join(_REPO_ROOT, 'prompts', 'fact_check.md')
    with open(tpl_path, 'r', encoding='utf-8') as fh:
        return fh.read()

def main():
    # Chump check: convert 'promise' records with null completion_condition_date to 'goal'
    try:
        res = mongo.silver_claims.update_many(
            {"type": "promise", "completion_condition_date": None},
            {"$set": {"type": "goal"}},
        )
        if getattr(res, 'modified_count', None) is not None:
            logger.info(f"Chump check: updated {res.modified_count} records from 'promise'->'goal'")
        else:
            logger.info("Chump check: update_many executed")
    except Exception:
        logger.exception("Chump check: failed to update promise->goal records")

    # Build update requests per type
    promises, goals_fu, statements_fu = get_claim_groups()
    regular_checkin_template = _checkin_template()
    endpoint_checkin_template = _endpoint_template()
    fact_check_template = _fact_check_template()

    # Promises follow existing scheduling logic
    request_lines, mapping = _build_requests(promises, regular_checkin_template, endpoint_checkin_template)

    # Goals: follow same cadence template (regular/endpoint) but we do not gate on completion date logic;
    # include them for a regular check-in now so the model can propose next follow_up_date proactively.
    goals_lines = []
    goals_map = {}
    for idx, (raw, claim) in enumerate(goals_fu):
        claim_id = raw.get('_id')
        custom_id = f"goal:{claim_id}:{idx}"
        article_date = getattr(claim, 'article_date', None)
        article_date_str = str(article_date) if article_date is not None else ''
        content_parts = [regular_checkin_template.strip(), "", "-- Article Metadata --"]
        content_parts.append(f"Source Article Link: {getattr(claim, 'article_link', '')}")
        content_parts.append(f"Source Article Date: {article_date_str}")
        content_parts.append(f"Claim: {getattr(claim, 'claim', '')}")
        content_parts.append(f"Verbatim Quote from Article: {getattr(claim, 'verbatim_claim', '')}")
        content_parts.append(f"Completion Condition: {getattr(claim, 'completion_condition', '')}")
        content_parts.append(f"Projected Completion Date: {getattr(claim, 'completion_condition_date', '')}")
        try:
            from util.timezone import pipeline_today as _pt
            _today = _pt()
        except Exception:
            _today = _get_pipeline_today()
        content_parts.append(f"Current Date: {_today}")
        content = "\n".join(content_parts)
        req = {
            "custom_id": str(custom_id),
            "model": os.environ.get('OPENAI_MODEL', 'gpt-5-nano'),
            "input": content,
        }
        goals_lines.append(req)
        goals_map[str(custom_id)] = (raw, claim, None)

    request_lines.extend(goals_lines)
    mapping.update(goals_map)

    # Ensure DB is available before querying followups
    db = getattr(mongo, 'DB', None)
    if db is None:
        logger.error('Mongo DB not available in util.mongo')
        return []
    # Statements: do not revisit unless a follow-up date was given (handled by scheduled followups)
    # Therefore, only include statements that have never been fact-checked (no latest update)
    updates_coll = db.get_collection('silver_updates')
    filtered_statements: List[Tuple[Any, MongoClaim]] = []
    for raw, claim in statements_fu:
        try:
            latest = updates_coll.find({ 'claim_id': raw.get('_id') }, { 'projection': { 'verdict': 1, 'model_output': 1, 'created_at': 1 } })\
                                .sort([('created_at', -1), ('_id', -1)]).limit(1)
            latest_list = list(latest)
            if latest_list:
                # Already fact-checked at least once; rely on scheduled followups instead of revisiting now
                continue
            filtered_statements.append((raw, claim))
        except Exception:
            # If anything fails, keep it in to avoid missing checks
            filtered_statements.append((raw, claim))

    stmt_lines = []
    stmt_map = {}
    for idx, (raw, claim) in enumerate(filtered_statements):
        claim_id = raw.get('_id')
        custom_id = f"statement:{claim_id}:{idx}"
        article_date = getattr(claim, 'article_date', None)
        article_date_str = str(article_date) if article_date is not None else ''
        event_date = getattr(claim, 'event_date', None)
        event_date_str = str(event_date) if event_date is not None else ''
        parts = [fact_check_template.strip(), "", "-- Statement Metadata --"]
        parts.append(f"Source Article Link: {getattr(claim, 'article_link', '')}")
        parts.append(f"Source Article Date: {article_date_str}")
        parts.append(f"Claim (statement): {getattr(claim, 'claim', '')}")
        parts.append(f"Verbatim Quote: {getattr(claim, 'verbatim_claim', '')}")
        if event_date_str:
            parts.append(f"Event/Effective Date (if any): {event_date_str}")
        try:
            from util.timezone import pipeline_today as _pt
            _today = _pt()
        except Exception:
            _today = _get_pipeline_today()
        parts.append(f"Current Date: {_today}")
        content = "\n".join(parts)
        req = {
            "custom_id": str(custom_id),
            "model": os.environ.get('OPENAI_MODEL', 'gpt-5-nano'),
            "input": content,
        }
        stmt_lines.append(req)
        stmt_map[str(custom_id)] = (raw, claim, None)

    request_lines.extend(stmt_lines)
    mapping.update(stmt_map)

    # Also include any scheduled followups for today's pipeline date from `silver_followups`.
    pipeline_today = _get_pipeline_today()

    # Ensure DB is available before querying followups
    db = getattr(mongo, 'DB', None)
    if db is None:
        logger.error('Mongo DB not available in util.mongo')
        return []

    # Ensure a one-time full schedule is present for each promise with no upcoming followups.
    autoplan_inserted = 0
    try:
        for raw, claim in promises:
            try:
                inserted = ensure_full_schedule_for_claim(raw, claim, pipeline_today, db)
                autoplan_inserted += inserted
            except Exception:
                logger.exception('Autoplan scheduling failed for claim %s', raw.get('_id'))
                continue
        if autoplan_inserted:
            logger.info(f'Autoplan scheduled {autoplan_inserted} follow-ups across promises')
    except Exception:
        logger.exception('Unexpected error while autoplan scheduling follow-ups')

    try:
        followup_filter = {
            'follow_up_date': pipeline_today,
            '$or': [
                {'processed_at': {'$exists': False}},
                {'processed_at': None},
            ],
        }
        try:
            followup_filter = mongo.normalize_dates(followup_filter)
        except Exception:
            logger.exception('Failed to normalize followup filter; using original filter')

        # Only process today's followups on the last run of the day (EST, fixed UTC-5)
        try:
            from util.timezone import now_utc_minus_5 as _now_minus5
            if _now_minus5().hour < 23:
                followups_cursor = []
            else:
                followups_cursor = db.get_collection('silver_followups').find(followup_filter)
        except Exception:
            followups_cursor = db.get_collection('silver_followups').find(followup_filter)
    except Exception:
        followups_cursor = []

    # Construct followup requests (use endpoint template for followups)
    followup_count = 0
    for idx, f in enumerate(list(followups_cursor)):
        try:
            followup_id = f.get('_id')
            custom_id = f"followup:{followup_id}:{idx}"
            content_parts = [endpoint_checkin_template.strip(), "", "-- Followup Metadata --"]
            content_parts.append(f"Source Article Link: {f.get('article_link', '')}")
            content_parts.append(f"Source Article Date: {str(f.get('article_date', ''))}")
            content_parts.append(f"Claim: {f.get('claim_text', '')}")
            content_parts.append(f"Followup requested for: {str(f.get('follow_up_date', ''))}")
            content = "\n".join(content_parts)

            req = {
                'custom_id': str(custom_id),
                'model': os.environ.get('OPENAI_MODEL', 'gpt-5-mini'),
                'input': content,
            }
            request_lines.append(req)
            # Mark mapping entry specially so processing loop knows this is a followup
            mapping[str(custom_id)] = ('_followup', f)
            followup_count += 1
        except Exception:
            logger.exception('Failed to build followup request for followup id %s', f.get('_id'))

    if followup_count:
        logger.info(f'Added {followup_count} followup requests for pipeline date {pipeline_today}')

    if not request_lines:
        logger.info('No prompts to send in batch')
        return []

    # Call run_with_search for each request and insert results directly
    silver = db.get_collection('silver_updates')

    inserted = 0

    for req in request_lines:
        custom_id = req.get('custom_id')
        if not custom_id:
            logger.warning('Skipping request with no custom_id')
            continue

        mapping_entry = mapping.get(str(custom_id))
        if not mapping_entry:
            logger.warning(f'No mapping for custom_id {custom_id}; skipping')
            continue

        # mapping_entry is usually (raw, claim, update_type), but followups are ('_followup', followup_doc)
        is_followup = False
        followup_doc = None
        try:
            raw, claim, update_type = mapping_entry
        except Exception:
            try:
                raw, claim = mapping_entry
                update_type = None
            except Exception:
                logger.exception('Unexpected mapping_entry shape for custom_id %s: %s', custom_id, mapping_entry)
                continue

        if isinstance(raw, str) and raw == '_followup':
            is_followup = True
            followup_doc = claim
            claim = None
            update_type = None

        model = req.get('model')
        content_str = req.get('input', '')
        parsed_obj = None
        model_text = ''
        verdict = 'in_progress'
        try:
            # Choose schema based on custom id (statements use fact check schema)
            use_factcheck = False
            try:
                use_factcheck = str(custom_id).startswith("statement:")
            except Exception:
                use_factcheck = False
            schema = FactCheckResponseOutput if use_factcheck else ModelResponseOutput

            run_res = run_with_search(content_str, model=model, text_format=schema)
            model_text = (run_res.text or '').strip()
            parsed_obj = getattr(run_res, 'parsed', None)
            if run_res.sources:
                try:
                    src_lines = []
                    for s in run_res.sources:
                        if isinstance(s, dict):
                            url = s.get('url') or ''
                            title = s.get('title') or ''
                            if title and url:
                                src_lines.append(f"- {title} {url}")
                            else:
                                src_lines.append(f"- {url or title}")
                        else:
                            src_lines.append(f"- {str(s)}")
                    if src_lines:
                        model_text = model_text + "\n\nSources:\n" + "\n".join(src_lines)
                except Exception:
                    pass
            if parsed_obj is not None:
                try:
                    if use_factcheck:
                        fc_verdict = getattr(parsed_obj, 'verdict', '')
                        verdict = str(fc_verdict) or verdict
                    else:
                        verdict = getattr(parsed_obj, 'verdict', verdict)
                    # Prefer parsed text field when present
                    pt = getattr(parsed_obj, 'text', '')
                    if pt:
                        model_text = str(pt)
                except Exception:
                    pass
            else:
                verdict = _classify_verdict(model_text)
        except Exception:
            logger.exception(f'Error calling run_with_search for custom_id={custom_id}')
            model_text = 'error calling run_with_search'
            verdict = 'failed'

        def _coerce_date(val):
            if val is None:
                return None
            if isinstance(val, datetime.date):
                return val
            if isinstance(val, datetime.datetime):
                return val.date()
            if isinstance(val, str):
                s = val.strip()
                try:
                    return datetime.date.fromisoformat(s)
                except Exception:
                    try:
                        return datetime.datetime.fromisoformat(s.replace('Z', '+00:00')).date()
                    except Exception:
                        for fmt in ("%B %d, %Y", "%Y-%m-%d", "%m/%d/%Y"):
                            try:
                                return datetime.datetime.strptime(s, fmt).date()
                            except Exception:
                                continue
                return None
            return None

        follow_date_raw = None
        if parsed_obj is not None:
            follow_date_raw = getattr(parsed_obj, 'follow_up_date', None) if hasattr(parsed_obj, 'follow_up_date') else (parsed_obj.get('follow_up_date') if isinstance(parsed_obj, dict) else None)
        follow_date = _coerce_date(follow_date_raw)

        # Normalize parsed_obj for storage to avoid Pydantic model instances in model_output
        def _norm_model_output(po):
            try:
                if po is None:
                    return None
                if hasattr(po, 'model_dump'):
                    return po.model_dump()
                if isinstance(po, dict):
                    return po
                if isinstance(po, str):
                    return po
                # best-effort stringify
                return str(po)
            except Exception:
                return None

        if is_followup and followup_doc is not None:
            doc = {
                'claim_id': followup_doc.get('claim_id'),
                'claim_text': followup_doc.get('claim_text', ''),
                'article_id': followup_doc.get('article_id', ''),
                'article_link': followup_doc.get('article_link', ''),
                'article_date': followup_doc.get('article_date', None),
                'model_output': _norm_model_output(parsed_obj) if parsed_obj is not None else model_text,
                'verdict': verdict,
                'created_at': datetime.datetime.utcnow(),
            }
        else:
            doc = {
                'claim_id': raw.get('_id'),
                'claim_text': getattr(claim, 'claim', ''),
                'article_id': getattr(claim, 'article_id', ''),
                'article_link': getattr(claim, 'article_link', ''),
                'article_date': getattr(claim, 'article_date', None),
                'model_output': _norm_model_output(parsed_obj) if parsed_obj is not None else model_text,
                'verdict': verdict,
                'created_at': datetime.datetime.utcnow(),
            }

        if follow_date is not None:
            try:
                if is_followup and followup_doc is not None:
                    follow_doc = {
                        'claim_id': followup_doc.get('claim_id'),
                        'claim_text': followup_doc.get('claim_text', ''),
                        'follow_up_date': follow_date,
                        'article_id': followup_doc.get('article_id', ''),
                        'article_link': followup_doc.get('article_link', ''),
                        'model_output': _norm_model_output(parsed_obj) if parsed_obj is not None else model_text,
                        'created_at': datetime.datetime.utcnow(),
                    }
                else:
                    follow_doc = {
                        'claim_id': raw.get('_id'),
                        'claim_text': getattr(claim, 'claim', ''),
                        'follow_up_date': follow_date,
                        'article_id': getattr(claim, 'article_id', ''),
                        'article_link': getattr(claim, 'article_link', ''),
                        'model_output': _norm_model_output(parsed_obj) if parsed_obj is not None else model_text,
                        'created_at': datetime.datetime.utcnow(),
                    }
                try:
                    follow_obj = SilverFollowup(**follow_doc)
                except Exception:
                    logger.exception(
                        'Failed to construct SilverFollowup for %s; follow_doc=%s',
                        (followup_doc.get('_id') if is_followup and followup_doc else raw.get('_id')),
                        follow_doc,
                    )
                    follow_obj = None

                if follow_obj is not None:
                    if hasattr(follow_obj, 'model_dump'):
                        final_follow = follow_obj.model_dump()
                    else:
                        final_follow = follow_obj.dict()
                    try:
                        final_follow = mongo.normalize_dates(final_follow)
                    except Exception:
                        logger.exception('Failed to normalize dates for silver_followup; proceeding with original doc')
                    try:
                        fcoll = db.get_collection('silver_followups')
                        # Deduplicate by (claim_id, follow_up_date) regardless of processed state
                        if fcoll.count_documents({ 'claim_id': final_follow.get('claim_id'), 'follow_up_date': final_follow.get('follow_up_date') }, limit=1) == 0:
                            fcoll.insert_one(final_follow)
                            logger.info(
                                'Inserted follow-up for claim %s on %s',
                                (final_follow.get('claim_id')), follow_date,
                            )
                    except Exception:
                        logger.exception('Failed to insert into silver_followups')
            except Exception:
                logger.exception('Unexpected error while handling follow-up insertion')

        try:
            silver_obj = SilverUpdate(**doc)
        except Exception:
            logger.exception(f'Failed to construct SilverUpdate for claim {doc.get("claim_id")} ; doc={doc}')
            continue

        if hasattr(silver_obj, 'model_dump'):
            final_doc = silver_obj.model_dump()
        else:
            final_doc = silver_obj.dict()

        try:
            try:
                final_doc = mongo.normalize_dates(final_doc)
            except Exception:
                logger.exception('Failed to normalize dates for silver_update; proceeding with original doc')
            insert_res = silver.insert_one(final_doc)
            inserted += 1
        except Exception:
            logger.exception('Failed to insert into silver_updates')
            insert_res = None
        else:
            try:
                if (not is_followup) and update_type == UpdateType.ENDPOINT:
                    claim_id = raw.get('_id')
                    mongo.silver_claims.update_one({'_id': claim_id}, {'$set': {'date_past': True}})
            except Exception:
                logger.exception(f'Failed to update date_past for claim {raw.get("_id")}')

            try:
                if is_followup and insert_res is not None:
                    try:
                        db.get_collection('silver_followups').update_one(
                            {'_id': followup_doc.get('_id')},
                            {'$set': {'processed_at': datetime.datetime.utcnow(), 'processed_update_id': insert_res.inserted_id}}
                        )
                        logger.info(f"Marked followup {followup_doc.get('_id')} as processed")
                    except Exception:
                        logger.exception('Failed to mark followup as processed')
            except Exception:
                logger.exception('Error while post-processing followup mapping entry')


    logger.info(f'Inserted {inserted} documents into silver_updates')
    return []
    
if __name__ == "__main__":
    import argparse
    import os
    
    # Configure console logging only when executed as a script
    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        _console_handler = logging.StreamHandler(sys.stdout)
        _console_handler.setLevel(logging.INFO)
        _console_formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
        _console_handler.setFormatter(_console_formatter)
        logger.addHandler(_console_handler)

    parser = argparse.ArgumentParser(description='Run update_promises main')
    parser.add_argument('--date', help='Pipeline date to use (YYYY-MM-DD). If provided, sets PIPELINE_RUN_DATE')
    args = parser.parse_args()
    if args.date:
        os.environ['PIPELINE_RUN_DATE'] = args.date
    main()