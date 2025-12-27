import json
import os
import sys
import logging
from typing import Any, Dict, List, Tuple
from dotenv import load_dotenv

from openai import OpenAI
from bs4 import BeautifulSoup
from markitdown import MarkItDown

load_dotenv()

_HERE = os.path.dirname(__file__)
_SERVICE_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _SERVICE_ROOT)

from util import mongo
from models import ArticleEnrichment, MongoArticle, LMLogEntry
from util import openai_batch as obatch
from util.scrape_utils import playwright_get
from util import locks as _locks
from util.model_select import select_model, MODEL_TABLE

logger = logging.getLogger(__name__)

_OPENAI_CLIENT = OpenAI()

# Manually toggle to True to purge enrichment fields from all documents
RESET_ENRICHMENT_FIELDS: bool = False


def _load_template() -> str:
    path = os.path.join(_SERVICE_ROOT, 'prompts', 'article_enrich.md')
    with open(path, 'r', encoding='utf-8') as fh:
        return fh.read()


def _build_input(article: Dict[str, Any], markdown: str) -> str:
    title = article.get('title', '')
    date = article.get('date', '')
    link = article.get('link', '')
    tags = ','.join(article.get('tags', []) or [])
    body = f"Title: {title}\nDate: {date}\nTags: {tags}\nSource: {link}\n\nSource Content (markdown):\n{markdown}"
    return body


def _needs_enrichment(doc: Dict[str, Any]) -> bool:
    return not (doc.get('clean_markdown') and doc.get('summary_paragraph') and doc.get('key_takeaways'))


def _fetch_url_text(url: str) -> str:
    if not url:
        return ""
    # Basic fallback disabled; rely on MarkItDown above
    return ""

def _fetch_markdown(url: str, fallback_html_text: str = "") -> str:
    if not url:
        return fallback_html_text
    # Try MarkItDown direct URL conversion first
    try:
        md = MarkItDown(enable_plugins=False)
        res = md.convert(url)
        txt = getattr(res, 'text_content', None)
        if isinstance(txt, str) and txt.strip():
            return txt
    except Exception:
        pass
    # Fallback to basic text extraction if conversion fails
    basic = _fetch_url_text(url)
    return basic or fallback_html_text

def _get_article_markdown(article: Dict[str, Any]) -> str:
    link = article.get('link', '')
    raw = article.get('raw_content', '') or ''
    md = _fetch_markdown(link, fallback_html_text=raw)
    return md or raw
    try:
        resp = playwright_get(url, timeout=20)
        html = resp.content.decode("utf-8", errors="ignore")
        soup = BeautifulSoup(html, "html.parser")
        # Remove scripts/styles
        for tag in soup(["script", "style", "noscript", "header", "head", "footer"]):
            tag.decompose()
        # Prefer <article> content

        
        return soup.get_text("\n", strip=True)
        # Gather paragraphs and list items as lines
        lines: List[str] = []
        for el in container.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote"]):
            text = el.get_text(" ", strip=True)
            if text:
                lines.append(text)
        return "\n\n".join(lines) if lines else container.get_text("\n", strip=True)
    except Exception:
        logger.exception("Failed to fetch or parse article url: %s", url)
        return ""


def _enrich(article: Dict[str, Any], template: str) -> tuple[ArticleEnrichment | None, dict | None]:
    md_text = _get_article_markdown(article)
    user_body = _build_input(article, md_text)
    try:
        # Select model/effort for enrichment (non-batch). Fallback to table [process][medium].
        try:
            model, effort = select_model('process', 'Enrich article into markdown, summary, key takeaways with strict schema.')
        except Exception:
            model, effort = MODEL_TABLE['process']['medium']
        kwargs = {
            "model": model,
            "input": [
                {"role": "system", "content": template},
                {"role": "user", "content": user_body},
            ],
            "text_format": ArticleEnrichment,
        }
        if effort and effort != 'none':
            try:
                kwargs["reasoning"] = {"effort": effort}
            except Exception:
                pass
        resp = _OPENAI_CLIENT.responses.parse(**kwargs)
        parsed = getattr(resp, 'output_parsed', None) or (resp.get('output_parsed') if isinstance(resp, dict) else None)
        if parsed is None:
            logger.error('No parsed output while enriching article %s', article.get('_id'))
            return None, None
        if not isinstance(parsed, ArticleEnrichment):
            # pydantic v1 compatibility: attempt coercion
            try:
                if hasattr(ArticleEnrichment, 'model_validate'):
                    parsed = ArticleEnrichment.model_validate(parsed)  # type: ignore[attr-defined]
                else:
                    parsed = ArticleEnrichment.parse_obj(parsed)  # type: ignore[attr-defined]
            except Exception:
                logger.exception('Failed to coerce parsed enrichment for article %s', article.get('_id'))
                return None, None
        # Overwrite LLM-derived clean_markdown with deterministic MarkItDown result
        try:
            parsed.clean_markdown = md_text
        except Exception:
            pass
        # Build LM log entry
        try:
            call_id = getattr(resp, 'id', None) or (resp.get('id') if isinstance(resp, dict) else None)
            usage = getattr(resp, 'usage', None) or (resp.get('usage') if isinstance(resp, dict) else None)
            prompt_tokens = 0
            completion_tokens = 0
            if usage is not None:
                try:
                    prompt_tokens = int(getattr(usage, 'input_tokens', None) or usage.get('prompt_tokens') or 0)
                except Exception:
                    prompt_tokens = 0
                try:
                    completion_tokens = int(getattr(usage, 'output_tokens', None) or usage.get('completion_tokens') or 0)
                except Exception:
                    completion_tokens = 0
            lm = LMLogEntry(
                api_type='responses',
                call_id=str(call_id or ''),
                called_from='scripts.enrich_articles._enrich',
                model_name=model,
                system_tokens=0,
                user_tokens=prompt_tokens,
                response_tokens=completion_tokens,
            )
            lm_dict = lm.model_dump() if hasattr(lm, 'model_dump') else lm.dict()
        except Exception:
            lm_dict = None
        return parsed, lm_dict
    except Exception:
        logger.exception('OpenAI enrichment failed for article %s', article.get('_id'))
        return None, None


def _fallback_enrich(docs: list[Dict[str, Any]], template: str) -> None:
    for art in docs:
        try:
            enr, lm_dict = _enrich(art, template)
            if enr is None:
                continue
            update = {
                '$set': {
                    'clean_markdown': enr.clean_markdown,
                    'summary_paragraph': enr.summary_paragraph,
                    'key_takeaways': list(enr.key_takeaways or []),
                    'priority': int(getattr(enr, 'priority', 5)),
                    'enrichment_lm_log': lm_dict,
                }
            }
            mongo.bronze_links.update_one({'_id': art.get('_id')}, update)
        except Exception:
            logger.exception('Fallback enrichment failed for article %s', art.get('_id'))


def run(batch: int = 50):
    logging.basicConfig(level=logging.INFO)

    coll = getattr(mongo, 'bronze_links', None)
    if coll is None:
        logger.error('bronze_links collection not available')
        return

    if RESET_ENRICHMENT_FIELDS:
        try:
            result = coll.update_many(
                {},
                {
                    '$unset': {
                        'clean_markdown': 1,
                        'summary_paragraph': 1,
                        'key_takeaways': 1,
                    }
                }
            )
            modified = getattr(result, 'modified_count', 0)
            logger.info('Purged enrichment fields from %d document(s)', modified)
        except Exception:
            logger.exception('Failed to purge enrichment fields from bronze_links')
        return

    template = _load_template()

    # Find candidates and acquire enrichment locks to avoid concurrent processing
    candidates = coll.find({
        '$or': [
            {'clean_markdown': {'$exists': False}},
            {'summary_paragraph': {'$exists': False}},
            {'key_takeaways': {'$exists': False}},
        ]
    }).sort('inserted_at', 1)

    docs = []
    owner = os.environ.get('HOSTNAME') or f"pid-{os.getpid()}"
    for art in candidates:
        if len(docs) >= batch:
            break
        try:
            if _locks.acquire_lock(coll, art.get('_id'), 'enrich_lock', owner, ttl_seconds=3600):
                docs.append(art)
        except Exception:
            logger.exception('Failed to acquire enrich lock for %s', art.get('_id'))
    if not docs:
        logger.info('No articles require enrichment')
        return

    # Build JSON schema for strict response
    try:
        schema = ArticleEnrichment.schema()
    except Exception:
        schema = ArticleEnrichment.model_json_schema()
    schema = obatch.sanitize_schema_for_strict(schema)
    schema_json = json.dumps(schema, indent=2)

    response_format = {
        "type": "json_schema",
        "json_schema": {"name": "ArticleEnrichment", "schema": schema, "strict": True},
    }

    # Precompute markdown per doc to avoid duplicate fetching and to store deterministically
    md_by_id: Dict[str, str] = {}
    for d in docs:
        try:
            md_by_id[str(d.get('_id'))] = _get_article_markdown(d)
        except Exception:
            md_by_id[str(d.get('_id'))] = d.get('raw_content', '') or ''

    # Build batch requests (batch API cannot use select_model or reasoning)
    request_lines: List[Dict[str, Any]] = []
    # Determine batch model: env override or static table default
    batch_model = MODEL_TABLE['process']['medium'][0]
    for doc in docs:
        custom_id = str(doc.get('_id'))
        md_text = md_by_id.get(custom_id, '')
        user_body = _build_input(doc, md_text)
        request_lines.append(
            {
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": batch_model,
                    "messages": [
                        {"role": "system", "content": template},
                        {"role": "user", "content": user_body},
                    ],
                    "response_format": response_format,
                },
            }
        )

    # Create and poll batch with shared utility
    batch_job = obatch.create_batch(_OPENAI_CLIENT, request_lines, endpoint='/v1/chat/completions')
    batch_id = getattr(batch_job, 'id', None) or (batch_job.get('id') if isinstance(batch_job, dict) else None)
    if not batch_id:
        logger.error('Batch did not return an id; aborting')
        return

    def _fallback():
        logger.warning('Enrichment batch timeout; falling back to single Responses.parse calls')
        _fallback_enrich(docs, template)

    finished = obatch.poll_batch_with_fallback(
        _OPENAI_CLIENT,
        batch_id,
        poll_interval=5,
        timeout=60 * 30,
        expected_total=len(request_lines),
        on_timeout=_fallback,
    )
    if finished is None:
        return

    # Read and apply outputs
    output_file_id = getattr(finished, 'output_file_id', None) or (finished.get('output_file_id') if isinstance(finished, dict) else None)
    if not output_file_id:
        logger.error('Batch finished without output file id')
        return

    output_text = obatch.read_file_text(_OPENAI_CLIENT, output_file_id)
    lines = list(obatch.iter_jsonl(output_text))

    docs_by_id = {str(d['_id']): d for d in docs}
    updated = 0
    for rec in lines:
        try:
            custom_id = rec.get('custom_id')
            if not custom_id:
                continue
            response = (rec.get('response') or {})
            if response.get('status_code') != 200:
                continue
            body = response.get('body') or {}
            content = body.get('choices', [{}])[0].get('message', {}).get('content')
            if not content:
                continue
            data = json.loads(content)
            # Validate/coerce
            if hasattr(ArticleEnrichment, 'model_validate'):
                enr = ArticleEnrichment.model_validate(data)  # type: ignore[attr-defined]
            else:
                enr = ArticleEnrichment.parse_obj(data)  # type: ignore[attr-defined]
            # Build LM log from chat completions body
            try:
                call_id = body.get('id')
                usage = body.get('usage') or {}
                prompt_tokens = int(usage.get('prompt_tokens') or 0)
                completion_tokens = int(usage.get('completion_tokens') or 0)
                model_name = body.get('model') or os.environ.get('OPENAI_MODEL', 'gpt-5-nano')
                lm = LMLogEntry(
                    api_type='completions',
                    call_id=str(call_id or ''),
                    called_from='scripts.enrich_articles.batch',
                    model_name=str(model_name),
                    system_tokens=0,
                    user_tokens=prompt_tokens,
                    response_tokens=completion_tokens,
                )
                lm_dict = lm.model_dump() if hasattr(lm, 'model_dump') else lm.dict()
            except Exception:
                lm_dict = None
            mongo.bronze_links.update_one(
                {'_id': docs_by_id[custom_id]['_id']},
                {'$set': {
                    # Overwrite with deterministic markitdown result
                    'clean_markdown': md_by_id.get(custom_id, enr.clean_markdown),
                    'summary_paragraph': enr.summary_paragraph,
                    'key_takeaways': list(enr.key_takeaways or []),
                    'priority': int(getattr(enr, 'priority', 5)),
                    'enrichment_lm_log': lm_dict,
                }, '$unset': {'enrich_lock': ""}}
            )
            updated += 1
        except Exception:
            logger.exception('Failed to apply enrichment output for custom_id=%s', rec.get('custom_id'))

    logger.info('Enriched %d article(s)', updated)


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description='Enrich new articles with clean markdown, summary, and takeaways')
    p.add_argument('--batch', type=int, default=50)
    args = p.parse_args()
    run(args.batch)
