import json
import os
import sys
import logging
from typing import Any, Dict, List, Tuple
from dotenv import load_dotenv

from openai import OpenAI
from bs4 import BeautifulSoup

load_dotenv()

_HERE = os.path.dirname(__file__)
_SERVICE_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _SERVICE_ROOT)

from util import mongo
from models import ArticleEnrichment, MongoArticle
from util import openai_batch as obatch
from util.scrape_utils import playwright_get
from util import locks as _locks

logger = logging.getLogger(__name__)

_OPENAI_CLIENT = OpenAI()

# Manually toggle to True to purge enrichment fields from all documents
RESET_ENRICHMENT_FIELDS: bool = False


def _load_template() -> str:
    path = os.path.join(_SERVICE_ROOT, 'prompts', 'article_enrich.md')
    with open(path, 'r', encoding='utf-8') as fh:
        return fh.read()


def _build_input(article: Dict[str, Any], template: str) -> str:
    title = article.get('title', '')
    date = article.get('date', '')
    link = article.get('link', '')
    tags = ','.join(article.get('tags', []) or [])
    # Prefer fetching live content from the source link
    if link.startswith('https://www.state.gov'):
        fetched = article.get('raw_content', '')
    else:
        fetched = _fetch_url_text(link)
    if not fetched:
        fetched = article.get('raw_content', '')
    body = f"Title: {title}\nDate: {date}\nTags: {tags}\nSource: {link}\n\nSource Content (fetched):\n{fetched}"
    return template + "\n\n" + body


def _needs_enrichment(doc: Dict[str, Any]) -> bool:
    return not (doc.get('clean_markdown') and doc.get('summary_paragraph') and doc.get('key_takeaways'))


def _fetch_url_text(url: str) -> str:
    if not url:
        return ""
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


def _enrich(article: Dict[str, Any], template: str) -> ArticleEnrichment | None:
    content = _build_input(article, template)
    try:
        resp = _OPENAI_CLIENT.responses.parse(
            model=os.environ.get('OPENAI_MODEL', 'gpt-5-nano'),
            input=content,
            text_format=ArticleEnrichment,
        )
        parsed = getattr(resp, 'output_parsed', None) or (resp.get('output_parsed') if isinstance(resp, dict) else None)
        if parsed is None:
            logger.error('No parsed output while enriching article %s', article.get('_id'))
            return None
        if not isinstance(parsed, ArticleEnrichment):
            # pydantic v1 compatibility: attempt coercion
            try:
                if hasattr(ArticleEnrichment, 'model_validate'):
                    parsed = ArticleEnrichment.model_validate(parsed)  # type: ignore[attr-defined]
                else:
                    parsed = ArticleEnrichment.parse_obj(parsed)  # type: ignore[attr-defined]
            except Exception:
                logger.exception('Failed to coerce parsed enrichment for article %s', article.get('_id'))
                return None
        return parsed
    except Exception:
        logger.exception('OpenAI enrichment failed for article %s', article.get('_id'))
        return None


def _fallback_enrich(docs: list[Dict[str, Any]], template: str) -> None:
    for art in docs:
        try:
            enr = _enrich(art, template)
            if enr is None:
                continue
            update = {
                '$set': {
                    'clean_markdown': enr.clean_markdown,
                    'summary_paragraph': enr.summary_paragraph,
                    'key_takeaways': list(enr.key_takeaways or []),
                    'priority': int(getattr(enr, 'priority', 5)),
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

    # Build batch requests
    request_lines: List[Dict[str, Any]] = []
    for doc in docs:
        custom_id = str(doc.get('_id'))
        content = _build_input(doc, template)
        request_lines.append(
            {
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": os.environ.get('OPENAI_MODEL', 'gpt-5-nano'),
                    "messages": [{"role": "user", "content": content}],
                    "response_format": response_format,
                },
            }
        )

    # Create and poll batch with shared utility
    batch = obatch.create_batch(_OPENAI_CLIENT, request_lines, endpoint='/v1/chat/completions')
    batch_id = getattr(batch, 'id', None) or batch.get('id')
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
            mongo.bronze_links.update_one(
                {'_id': docs_by_id[custom_id]['_id']},
                {'$set': {
                    'clean_markdown': enr.clean_markdown,
                    'summary_paragraph': enr.summary_paragraph,
                    'key_takeaways': list(enr.key_takeaways or []),
                    'priority': int(getattr(enr, 'priority', 5)),
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
