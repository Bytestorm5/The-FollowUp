from enum import Enum
import os
import sys
from typing import Any, List, Tuple, Optional
from dotenv import load_dotenv
import datetime
import json
import time
import logging

load_dotenv()
from openai import OpenAI

# OpenAI client (reads OPENAI_API_KEY, OPENAI_ORG, OPENAI_PROJECT from env)
_OPENAI_CLIENT = OpenAI()

import pymongo
from bson import ObjectId

_HERE = os.path.dirname(__file__)
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _REPO_ROOT not in sys.path:
	sys.path.insert(0, _REPO_ROOT)

from util import mongo
from models import MongoClaim, Date_Delta, SilverUpdate, MongoArticle, ModelResponseOutput, SilverFollowup, FactCheckResponseOutput

try:
    from pydantic_core._pydantic_core import ValidationError as PydanticCoreValidationError
except Exception:
    PydanticCoreValidationError = None

logger = logging.getLogger(__name__)

# Console logging to stdout
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

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
    # JSONL batch writing removed — Responses.parse is used instead.
    raise RuntimeError('_write_jsonl is deprecated; use Responses.parse directly')

def get_article_from_id(article_id: str) -> MongoArticle:
    article = mongo.bronze_links.find_one({'_id': ObjectId(article_id)})
    if not article:
        raise ValueError(f'No article found with id {article_id}')
    return MongoArticle(**article)
    

def _build_requests(claim_pairs: List[Tuple[Any, MongoClaim]], regular_tpl: str, endpoint_tpl: str, model: str = None):
    """Build a list of Batch API request lines (JSON-serializable dicts).

    claim_pairs: iterable of (raw_doc, MongoClaim)
    """
    model = model or os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')
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

        #article: MongoArticle = get_article_from_id(claim.article_id)
        
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
            "method": "POST",
            "url": "/v1/responses",
            "body": {
                "model": model,                  # consider a model shown in the web_search guide (e.g., o4-mini)
                "input": content,                # NOTE: input, not messages
                "tools": [{"type": "web_search"}],
                "tool_choice": "auto",
                "include": ["web_search_call.action.sources"],  # if you want source URLs
            },
        }
        requests.append(req)
        mapping[str(custom_id)] = (raw, claim, update_type)

    return requests, mapping





# _call_responses_for_requests removed — we now use Responses.parse with structured outputs.


def _read_file_text(file_id: str) -> str:
    file_response = _OPENAI_CLIENT.files.content(file_id)
    return getattr(file_response, 'text', None) or str(file_response)


def _iter_jsonl(text: str):
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        yield json.loads(line)


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
            "method": "POST",
            "url": "/v1/responses",
            "body": {
                "model": os.environ.get('OPENAI_MODEL', 'gpt-4o-mini'),
                "input": content,
                "tools": [{"type": "web_search"}],
                "tool_choice": "auto",
                "include": ["web_search_call.action.sources"],
            },
        }
        goals_lines.append(req)
        goals_map[str(custom_id)] = (raw, claim, None)

    request_lines.extend(goals_lines)
    mapping.update(goals_map)

    # Statements: fact-check when follow_up_worthy
    stmt_lines = []
    stmt_map = {}
    for idx, (raw, claim) in enumerate(statements_fu):
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
            "method": "POST",
            "url": "/v1/responses",
            "body": {
                "model": os.environ.get('OPENAI_MODEL', 'gpt-4o-mini'),
                "input": content,
                "tools": [{"type": "web_search"}],
                "tool_choice": "auto",
                "include": ["web_search_call.action.sources"],
            },
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

    # Proactively schedule future follow-ups so the UI can display them.
    proactively_scheduled = 0
    try:
        followups_coll = db.get_collection('silver_followups')
        for raw, claim in promises:
            try:
                upd_type = claim_needs_update(claim)
            except Exception:
                logger.exception('Failed to evaluate update type for claim %s', raw.get('_id'))
                continue

            if upd_type != UpdateType.NO_UPDATE:
                continue

            try:
                nxt = next_update_date(claim, pipeline_today)
            except Exception:
                logger.exception('Failed computing next update date for claim %s', raw.get('_id'))
                nxt = None

            if nxt is None:
                continue

            # Skip if there's already an unprocessed followup in the future (or today)
            try:
                followup_filter = {
                    'claim_id': raw.get('_id'),
                    'processed_at': {'$exists': False},
                    'follow_up_date': {'$gte': pipeline_today},
                }
                try:
                    followup_filter = mongo.normalize_dates(followup_filter)
                except Exception:
                    logger.exception('normalize_dates failed for proactive followup filter; using raw filter')
                existing = followups_coll.count_documents(followup_filter)
            except Exception:
                logger.exception('Failed checking existing followups for claim %s', raw.get('_id'))
                existing = 0

            if existing:
                continue

            # Insert a proactive followup record
            follow_doc = {
                'claim_id': raw.get('_id'),
                'claim_text': getattr(claim, 'claim', ''),
                'follow_up_date': nxt,
                'article_id': getattr(claim, 'article_id', ''),
                'article_link': getattr(claim, 'article_link', ''),
                'model_output': f'Scheduled proactively on {pipeline_today.isoformat()} for next planned update',
                'created_at': datetime.datetime.utcnow(),
            }

            try:
                follow_obj = SilverFollowup(**follow_doc)
                final_follow = follow_obj.model_dump() if hasattr(follow_obj, 'model_dump') else follow_obj.dict()
                try:
                    final_follow = mongo.normalize_dates(final_follow)
                except Exception:
                    logger.exception('Failed to normalize dates for proactive silver_followup; inserting raw doc')
                followups_coll.insert_one(final_follow)
                proactively_scheduled += 1
            except Exception:
                logger.exception('Failed inserting proactive followup for claim %s', raw.get('_id'))

        if proactively_scheduled:
            logger.info(f'Proactively scheduled {proactively_scheduled} future follow-ups')
    except Exception:
        logger.exception('Unexpected error while proactively scheduling follow-ups')

    try:
        followup_filter = {
            'follow_up_date': pipeline_today,
            'processed_at': {'$exists': False}
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
                'method': 'POST',
                'url': '/v1/responses',
                'body': {
                    'model': os.environ.get('OPENAI_MODEL', 'gpt-5-mini'),
                    'input': content,
                    'tools': [{ 'type': 'web_search' }],
                    'tool_choice': 'auto',
                    'include': ['web_search_call.action.sources'],
                }
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

    # Call Responses.parse for each request and insert results directly
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

        body = req.get('body', {})
        model = body.get('model')
        input_arg = body.get('messages') or [{"role": "user", "content": body.get('input', '')}]

        parsed_obj = None
        model_text = ''
        verdict = 'in_progress'
        max_validation_retries = 3
        for attempt in range(1, max_validation_retries + 1):
            try:
                # Choose schema based on custom id
                use_factcheck = False
                try:
                    use_factcheck = str(custom_id).startswith("statement:")
                except Exception:
                    use_factcheck = False

                resp = _OPENAI_CLIENT.responses.parse(
                    model=model,
                    input=input_arg,
                    text_format=FactCheckResponseOutput if use_factcheck else ModelResponseOutput,
                    tools=body.get('tools'),
                    tool_choice=body.get('tool_choice'),
                    include=body.get('include'),
                )

                parsed_obj = getattr(resp, 'output_parsed', None) or (resp.get('output_parsed') if isinstance(resp, dict) else None)
                if parsed_obj is not None:
                    # Coerce parsed object to the expected Pydantic model if needed
                    if use_factcheck and not isinstance(parsed_obj, FactCheckResponseOutput):
                        try:
                            if hasattr(FactCheckResponseOutput, 'model_validate'):
                                parsed_obj = FactCheckResponseOutput.model_validate(parsed_obj)  # type: ignore[attr-defined]
                            else:
                                parsed_obj = FactCheckResponseOutput.parse_obj(parsed_obj)  # type: ignore[attr-defined]
                        except Exception as e:
                            if PydanticCoreValidationError is not None and isinstance(e, PydanticCoreValidationError):
                                logger.warning(f'ValidationError validating fact-check parsed response (attempt {attempt}/{max_validation_retries}) for custom_id={custom_id}; retrying')
                                parsed_obj = None
                                time.sleep(1)
                                continue
                            parsed_obj = None
                    if (not use_factcheck) and not isinstance(parsed_obj, ModelResponseOutput):
                        try:
                            if hasattr(ModelResponseOutput, 'model_validate'):
                                parsed_obj = ModelResponseOutput.model_validate(parsed_obj)  # type: ignore[attr-defined]
                            else:
                                parsed_obj = ModelResponseOutput.parse_obj(parsed_obj)  # type: ignore[attr-defined]
                        except Exception as e:
                            if PydanticCoreValidationError is not None and isinstance(e, PydanticCoreValidationError):
                                logger.warning(f'ValidationError validating parsed response (attempt {attempt}/{max_validation_retries}) for custom_id={custom_id}; retrying')
                                parsed_obj = None
                                time.sleep(1)
                                continue
                            parsed_obj = None

                if parsed_obj is not None:
                    # For fact checks store detailed verdict directly; for others keep legacy values
                    if use_factcheck:
                        fc_verdict = getattr(parsed_obj, 'verdict', '')
                        verdict = str(fc_verdict) or verdict
                    else:
                        verdict = getattr(parsed_obj, 'verdict', verdict)
                    model_text = getattr(parsed_obj, 'text', '') or model_text
                break
            except Exception:
                logger.exception(f'Error calling Responses.parse for custom_id={custom_id} (attempt {attempt})')
                model_text = 'error calling responses.parse'
                verdict = 'failed'
                parsed_obj = None
                break

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

        if is_followup and followup_doc is not None:
            doc = {
                'claim_id': followup_doc.get('claim_id'),
                'claim_text': followup_doc.get('claim_text', ''),
                'article_id': followup_doc.get('article_id', ''),
                'article_link': followup_doc.get('article_link', ''),
                'article_date': followup_doc.get('article_date', None),
                'model_output': parsed_obj if parsed_obj is not None else model_text,
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
                'model_output': parsed_obj if parsed_obj is not None else model_text,
                'verdict': verdict,
                'created_at': datetime.datetime.utcnow(),
            }

        if follow_date is not None and not is_followup:
            try:
                follow_doc = {
                    'claim_id': raw.get('_id'),
                    'claim_text': getattr(claim, 'claim', ''),
                    'follow_up_date': follow_date,
                    'article_id': getattr(claim, 'article_id', ''),
                    'article_link': getattr(claim, 'article_link', ''),
                    'model_output': parsed_obj if parsed_obj is not None else model_text,
                    'created_at': datetime.datetime.utcnow(),
                }
                try:
                    follow_obj = SilverFollowup(**follow_doc)
                except Exception:
                    logger.exception(f'Failed to construct SilverFollowup for claim {raw.get("_id")}; follow_doc={follow_doc}')
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
                        db.get_collection('silver_followups').insert_one(final_follow)
                        logger.info(f"Inserted follow-up for claim {raw.get('_id')} on {follow_date}")
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

    parser = argparse.ArgumentParser(description='Run update_promises main')
    parser.add_argument('--date', help='Pipeline date to use (YYYY-MM-DD). If provided, sets PIPELINE_RUN_DATE')
    args = parser.parse_args()
    if args.date:
        os.environ['PIPELINE_RUN_DATE'] = args.date
    main()