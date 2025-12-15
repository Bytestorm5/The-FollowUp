import copy
import os
import sys
import time
import json
import logging
from typing import List, Dict, Any, Optional, Iterable
from dotenv import load_dotenv
load_dotenv()
from openai import OpenAI

# OpenAI client (reads OPENAI_API_KEY, OPENAI_ORG, OPENAI_PROJECT from env)
_OPENAI_CLIENT = OpenAI()
_HERE = os.path.dirname(__file__)
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from models import ClaimProcessingResult, Date_Delta, MongoClaim
from util import mongo
from util.mongo import normalize_dates as _normalize_dates

logger = logging.getLogger(__name__)


def _get_pipeline_today():
    """Return the pipeline 'today' date. If `PIPELINE_RUN_DATE` env var is set (YYYY-MM-DD),
    parse and return it, otherwise fall back to the real today."""
    import os as _os
    import datetime as _dt

    v = _os.environ.get('PIPELINE_RUN_DATE')
    if v:
        try:
            return _dt.date.fromisoformat(v)
        except Exception:
            pass
    return _dt.date.today()


def _sanitize_schema_for_strict(schema: Any) -> Any:
    """Make a JSON Schema compatible with Structured Outputs strict mode.

    Structured Outputs `strict:true` requires:
      - For every object schema: `additionalProperties` must be `false`
      - For every object schema: all keys in `properties` must be listed in `required`

    This function recursively enforces those rules on a best-effort basis.
    """
    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            # Recurse into common schema containers
            for k in ("properties", "$defs", "definitions"):
                if k in node and isinstance(node[k], dict):
                    node[k] = {kk: walk(vv) for kk, vv in node[k].items()}

            for k in ("items", "additionalItems", "contains"):
                if k in node:
                    node[k] = walk(node[k])

            for k in ("anyOf", "oneOf", "allOf"):
                if k in node and isinstance(node[k], list):
                    node[k] = [walk(v) for v in node[k]]

            # Enforce object strictness
            if node.get("type") == "object":
                node["additionalProperties"] = False
                if isinstance(node.get("properties"), dict):
                    node["required"] = list(node["properties"].keys())
                else:
                    node["properties"] = {}
                    node["required"] = []

            return node

        if isinstance(node, list):
            return [walk(v) for v in node]

        return node

    return walk(copy.deepcopy(schema))

def _load_prompt_template() -> str:
    tpl_path = os.path.join(_REPO_ROOT, 'prompts', 'claim_processing.md')
    with open(tpl_path, 'r', encoding='utf-8') as fh:
        return fh.read()


def _build_requests(
    docs: List[dict],
    schema: Dict[str, Any],
    schema_json: str,
    template: str,
    model: str,
) -> List[Dict[str, Any]]:
    """Build Batch API request lines (JSONL).

    Each line must be shaped like:
      {"custom_id": "...", "method": "POST", "url": "/v1/chat/completions", "body": {...}}
    """
    requests: List[Dict[str, Any]] = []
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "ClaimProcessingResult",
            "schema": schema,
            "strict": True,
        },
    }

    for doc in docs:
        article_id = str(doc.get('_id'))
        
        doc_format = f"""Title: {doc.get('title', 'Unknown Title')}\nTimestamp: {doc.get('date')}\nTags: {','.join(doc.get('tags', []))}\nSource: {doc.get('link', 'Unknown Source')}\n\nContent: {doc.get('raw_content', 'Unknown Content')}"""
        
        content = template.replace('{{SCHEMA}}', schema_json).replace('{{ARTICLE}}', doc_format)
        requests.append(
            {
                "custom_id": article_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": model,
                    "messages": [
                        {"role": "user", "content": content},
                    ],
                    "temperature": 0,
                    "response_format": response_format,
                },
            }
        )
    return requests


def _write_jsonl(path: str, lines: Iterable[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False))
            f.write('\n')


def _create_batch(request_lines: List[Dict[str, Any]], endpoint: str) -> Dict[str, Any]:
    """Create a Batch job.

    Batch API requires uploading a JSONL file of request lines first, then creating
    the batch with that uploaded file id.
    """
    tmp_dir = os.path.join(_HERE, '.tmp')
    jsonl_path = os.path.join(tmp_dir, f'claim_batch_{int(time.time())}.jsonl')
    _write_jsonl(jsonl_path, request_lines)

    logger.info(f"Uploading batch input file with {len(request_lines)} lines")
    input_file = _OPENAI_CLIENT.files.create(
        file=open(jsonl_path, 'rb'),
        purpose='batch',
    )

    logger.info(f"Creating batch for endpoint {endpoint} using input_file_id={input_file.id}")
    batch = _OPENAI_CLIENT.batches.create(
        input_file_id=input_file.id,
        endpoint=endpoint,
        completion_window='24h',
        metadata={"job": "claim_process"},
    )
    # Return as dict-like for easier downstream handling
    return batch


def _poll_batch(batch_id: str, poll_interval: int = 5, timeout: int = 60 * 30):
    start = time.time()
    while True:
        batch = _OPENAI_CLIENT.batches.retrieve(batch_id)
        status = getattr(batch, 'status', None) or (batch.get('status') if isinstance(batch, dict) else None)
        logger.info(f"Batch {batch_id} status: {status}")
        # Terminal statuses per Batch docs: validating/failed/in_progress/finalizing/completed/expired/cancelling/cancelled
        if status in ('completed', 'expired', 'cancelled'):
            return batch
        if status in ('failed',):
            raise RuntimeError(f"Batch {batch_id} failed: {batch}")
        if time.time() - start > timeout:
            raise TimeoutError(f"Timed out waiting for batch {batch_id}")
        time.sleep(poll_interval)


def _read_file_text(file_id: str) -> str:
    # Official SDK returns a FileContent response with a `.text` property.
    file_response = _OPENAI_CLIENT.files.content(file_id)
    return getattr(file_response, 'text', None) or str(file_response)


def _iter_jsonl(text: str) -> Iterable[Dict[str, Any]]:
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        yield json.loads(line)


def _pydantic_parse_result(payload: Dict[str, Any]) -> ClaimProcessingResult:
    # Support both Pydantic v1 and v2
    if hasattr(ClaimProcessingResult, 'model_validate'):
        return ClaimProcessingResult.model_validate(payload)  # type: ignore[attr-defined]
    return ClaimProcessingResult.parse_obj(payload)  # type: ignore[attr-defined]


def _pydantic_dump(obj: Any) -> Dict[str, Any]:
    if hasattr(obj, 'model_dump'):
        return obj.model_dump()  # type: ignore[attr-defined]
    return obj.dict()  # type: ignore[attr-defined]


# `_normalize_dates` is provided by `util.mongo.normalize_dates` and imported above.


def _resolve_date_like(val: Any) -> Optional['datetime.date']:
    """Resolve various date-like inputs to a `datetime.date` or return None.

    Accepts: datetime.date / datetime.datetime / ISO date string / dict representing Date_Delta
    """
    import datetime as _dt

    if val is None:
        return None
    if isinstance(val, _dt.datetime):
        return val.date()
    if isinstance(val, _dt.date):
        return val
    if isinstance(val, str):
        try:
            return _dt.date.fromisoformat(val)
        except Exception:
            return None
    if isinstance(val, dict):
        # Try to instantiate Date_Delta model if possible
        try:
            # If it's already serialised Date_Delta, this will construct it
            dd = Date_Delta(**val)
            return dd._resolve_date()
        except Exception:
            # Attempt to parse from a dict with from_date and deltas
            try:
                fd = val.get('from_date')
                if isinstance(fd, str):
                    fd = _dt.date.fromisoformat(fd)
                dd = Date_Delta(from_date=fd,
                                days_delta=val.get('days_delta'),
                                weeks_delta=val.get('weeks_delta'),
                                months_delta=val.get('months_delta'),
                                years_delta=val.get('years_delta'))
                return dd._resolve_date()
            except Exception:
                return None
    return None


def run_batch_process(batch_size: int = 20, poll_interval: int = 5):
    logging.basicConfig(level=logging.INFO)

    bronze = getattr(mongo, 'bronze_links')
    db = getattr(mongo, 'DB', None)
    if bronze is None or db is None:
        logger.error('Mongo DB or bronze_links collection not available in util.mongo')
        return

    claims_coll = mongo.silver_claims

    # Find documents that are not yet processed (missing or False)
    cursor = bronze.find({'claim_processed': {'$ne': True}}).limit(batch_size)
    docs = list(cursor)
    if not docs:
        logger.info('No unprocessed documents found')
        return

    # Ensure missing claim_processed fields are explicitly set to False
    ids_to_ensure = [d['_id'] for d in docs if 'claim_processed' not in d]
    if ids_to_ensure:
        bronze.update_many({'_id': {'$in': ids_to_ensure}}, {'$set': {'claim_processed': False}})

    # Load prompt template and JSON schema for ClaimProcessingResult
    template = _load_prompt_template()
    try:
        schema = ClaimProcessingResult.schema()
    except Exception:
        # fallback for pydantic v2
        schema = ClaimProcessingResult.model_json_schema()
    schema = _sanitize_schema_for_strict(schema)
    schema_json = json.dumps(schema, indent=2)

    model = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')
    endpoint = '/v1/chat/completions'
    request_lines = _build_requests(docs, schema, schema_json, template, model=model)

    # Create the OpenAI batch request
    try:
        batch = _create_batch(request_lines, endpoint=endpoint)
    except Exception:
        logger.exception('Failed to create OpenAI batch')
        return

    batch_id = getattr(batch, 'id', None) or batch.get('id')
    if not batch_id:
        logger.error('Batch did not return an id; aborting')
        return

    # Poll until completed
    try:
        finished = _poll_batch(batch_id, poll_interval=poll_interval)
    except Exception:
        logger.exception('Error while polling batch')
        return

    output_file_id = getattr(finished, 'output_file_id', None) or (finished.get('output_file_id') if isinstance(finished, dict) else None)
    error_file_id = getattr(finished, 'error_file_id', None) or (finished.get('error_file_id') if isinstance(finished, dict) else None)

    if not output_file_id:
        logger.error(f'Batch finished but has no output_file_id: {finished}')
        return

    # Batch results are stored as JSONL in the output file. Use custom_id to map back to docs.
    try:
        output_text = _read_file_text(output_file_id)
        output_lines = list(_iter_jsonl(output_text))
    except Exception:
        logger.exception('Failed to download/parse batch output file')
        return

    if error_file_id:
        try:
            err_text = _read_file_text(error_file_id)
            logger.warning(f'Batch produced errors (error_file_id={error_file_id}). First 5 lines:\n' + '\n'.join(err_text.splitlines()[:5]))
        except Exception:
            logger.exception('Failed to read batch error file')

    # Map article_id -> original doc
    docs_by_id = {str(d['_id']): d for d in docs}

    inserted_claims = 0
    processed_article_ids = set()

    for rec in output_lines:
        try:
            article_id = rec.get('custom_id')
            if not article_id:
                logger.warning(f'Output line missing custom_id: {rec}')
                continue

            if rec.get('error'):
                logger.error(f'Batch request failed for custom_id={article_id}: {rec.get("error")}')
                continue

            response = (rec.get('response') or {})
            status_code = response.get('status_code')
            body = response.get('body') or {}
            if status_code != 200:
                logger.error(f'Non-200 status for custom_id={article_id}: status={status_code} body={body}')
                continue

            # Chat Completions response JSON is in choices[0].message.content (as a JSON string)
            try:
                content = body['choices'][0]['message']['content']
                structured = json.loads(content)
            except Exception:
                logger.exception(f'Failed to extract/parse JSON content for custom_id={article_id}')
                continue

            try:
                result_obj = _pydantic_parse_result(structured)
            except Exception:
                logger.exception(f'Failed to validate structured output for custom_id={article_id}')
                continue

            article_link = (docs_by_id.get(article_id) or {}).get('link', '')

            # Insert each step as a claim document (validated as MongoClaim)
            for step in result_obj.steps:
                claim_doc = _pydantic_dump(step)

                # Original article metadata
                orig = docs_by_id.get(article_id, {})
                article_link = orig.get('link', article_link)
                article_date_raw = orig.get('date')
                resolved_article_date = _resolve_date_like(article_date_raw)

                # Resolve completion_condition_date (if any) to determine if it's past
                completion_raw = claim_doc.get('completion_condition_date')
                resolved_completion = _resolve_date_like(completion_raw)
                import datetime as _dt
                date_past = False
                if resolved_completion is not None:
                    date_past = resolved_completion < _get_pipeline_today()

                # Build payload for MongoClaim
                payload = claim_doc.copy()
                payload['article_id'] = article_id
                payload['article_link'] = article_link
                # MongoClaim requires an `article_date` field; fall back to today if missing
                payload['article_date'] = resolved_article_date or _get_pipeline_today()
                payload['date_past'] = date_past

                try:
                    mongo_claim = MongoClaim(**payload)
                except Exception:
                    logger.exception(f'Failed to construct MongoClaim for article {article_id}; payload={payload}')
                    continue

                # Convert to plain dict and normalize dates before inserting
                final_doc = _pydantic_dump(mongo_claim)
                final_doc = _normalize_dates(final_doc)
                try:
                    claims_coll.insert_one(final_doc)
                    inserted_claims += 1
                except Exception:
                    logger.exception('Failed to insert claim into collection.')

            # Mark original article as processed
            try:
                from bson import ObjectId
                bronze.update_one({'_id': ObjectId(article_id)}, {'$set': {'claim_processed': True}})
                processed_article_ids.add(article_id)
            except Exception:
                # maybe article_id is not an ObjectId string; try raw
                try:
                    bronze.update_one({'_id': article_id}, {'$set': {'claim_processed': True}})
                    processed_article_ids.add(article_id)
                except Exception:
                    logger.exception(f'Failed to set claim_processed for article {article_id}')
        except Exception:
            logger.exception('Error processing an output line')

    logger.info(f'Inserted {inserted_claims} claim documents. Marked {len(processed_article_ids)} articles processed.')


if __name__ == '__main__':
    import argparse
    import os

    parser = argparse.ArgumentParser(description='Run claim processing batch')
    parser.add_argument('--date', help='Pipeline date to use (YYYY-MM-DD). If provided, sets PIPELINE_RUN_DATE')
    parser.add_argument('--batch-size', type=int, default=100, help='Number of documents to process')
    parser.add_argument('--poll-interval', type=int, default=5, help='Poll interval for batch')
    args = parser.parse_args()
    if args.date:
        os.environ['PIPELINE_RUN_DATE'] = args.date
    run_batch_process(args.batch_size, args.poll_interval)