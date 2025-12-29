import json
import logging
import os
import sys
from typing import Any, Dict, List

from dotenv import load_dotenv

load_dotenv()

_HERE = os.path.dirname(__file__)
_SERVICE_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _SERVICE_ROOT)

from models import FollowupAnswer, FollowupAnswerMap, LMLogEntry  # noqa: E402
from util import locks as _locks  # noqa: E402
from util import mongo  # noqa: E402
from util.llm_web import run_with_search  # noqa: E402
from util.schema_outline import compact_outline_from_model  # noqa: E402

logger = logging.getLogger(__name__)


def _fmt_entities(entities: Dict[str, int]) -> str:
    if not entities:
        return "None detected"
    return "\n".join([f"- {k}: {v}" for k, v in entities.items()])


def _normalize_groups(groups: Any, question_count: int) -> List[List[int]]:
    if isinstance(groups, str):
        val = groups.strip().lower()
        if val == 'single':
            return [list(range(question_count))] if question_count else []
        if val == 'individual':
            return [[i] for i in range(question_count)]
    normalized: List[List[int]] = []
    if isinstance(groups, (list, tuple)):
        for group in groups:
            if not isinstance(group, (list, tuple)):
                continue
            cleaned_set: set[int] = set()
            for i in group:
                if isinstance(i, bool):
                    continue
                try:
                    idx = int(i)
                except Exception:
                    continue
                if 0 <= idx < question_count:
                    cleaned_set.add(idx)
            cleaned = sorted(cleaned_set)
            if cleaned:
                normalized.append(list(cleaned))
    return normalized


def _build_prompt(article: Dict[str, Any], questions: List[str], groups: List[List[int]]) -> str:
    title = article.get('title', '')
    date = article.get('date', '')
    link = article.get('link', '')
    summary = article.get('summary_paragraph', '')
    takeaways = [f"- {kt}" for kt in (article.get('key_takeaways') or [])]
    entities = _fmt_entities(article.get('entities') or {})
    md = (article.get('clean_markdown') or '')[:4000]
    questions_block = "\n".join([f"{idx}. {q}" for idx, q in enumerate(questions)])
    groups_block = ", ".join([str(g) for g in groups]) if groups else "[]"
    schema_hint = ""
    try:
        schema_hint = compact_outline_from_model(FollowupAnswerMap)
    except Exception:
        pass
    return (
        "You are answering follow-up questions to make this article understandable to a layperson.\n"
        "Use the article context below and web/news research to produce concise, sourced answers.\n"
        "Return ONLY the structured output requested.\n\n"
        "Instructions:\n"
        "- Provide a short answer for each question index, even if the article partially answers it.\n"
        "- Cite 1-3 high-quality sources per answer when possible; prefer sources that directly support the answer.\n"
        "- Reuse research across grouped questions to keep answers consistent.\n"
        "- If a question is unanswerable with available information, say so concisely and leave sources empty.\n\n"
        "Structured output required:\n"
        "A JSON object keyed by the question index (0-based). Each value must include:\n"
        '  - text: concise answer\n'
        '  - sources: list of URLs backing the answer\n'
        f"{schema_hint}"
        "Do not include prose outside the JSON object.\n"
        f"Article title: {title}\nDate: {date}\nLink: {link}\n"
        f"Summary: {summary}\n"
        f"Key takeaways:\n{chr(10).join(takeaways) if takeaways else '- None provided'}\n"
        f"Named entities with counts from the original text:\n{entities}\n"
        f"Question groups (0-based indexes of related questions): {groups_block}\n\n"
        "Questions (index: text):\n"
        f"{questions_block}\n\n"
        "\n\nArticle excerpt for grounding:\n"
        f"{md}"
    )


def _coerce_answers_map(data: Any) -> Dict[int, FollowupAnswer]:
    if isinstance(data, FollowupAnswerMap):
        raw_map = getattr(data, "root", None) or getattr(data, "__root__", {})  # type: ignore[attr-defined]
    else:
        raw_map = data
    if not isinstance(raw_map, dict):
        return {}

    out: Dict[int, FollowupAnswer] = {}
    for k, v in raw_map.items():
        try:
            idx = int(k)
        except Exception:
            continue
        try:
            if isinstance(v, FollowupAnswer):
                ans = v
            elif hasattr(FollowupAnswer, 'model_validate'):
                ans = FollowupAnswer.model_validate(v)  # type: ignore[attr-defined]
            else:
                ans = FollowupAnswer.parse_obj(v)  # type: ignore[attr-defined]
        except Exception:
            continue
        out[idx] = ans
    return out


def _answers_to_list(mapping: Dict[int, FollowupAnswer], questions: List[str]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for idx, q in enumerate(questions):
        ans = mapping.get(idx)
        if ans is None:
            continue
        ans_dict = ans.model_dump() if hasattr(ans, 'model_dump') else ans.dict()
        ans_dict['index'] = idx
        ans_dict['question'] = q
        items.append(ans_dict)
    return items


def run(batch: int = 10) -> None:
    logging.basicConfig(level=logging.INFO)
    coll = getattr(mongo, 'bronze_links', None)
    if coll is None:
        logger.error('bronze_links collection not available')
        return

    query = {
        'follow_up_questions': {'$exists': True, '$ne': []},
        '$or': [
            {'follow_up_answers': {'$exists': False}},
            {'follow_up_answers': []},
            {'follow_up_answers': None},
        ]
    }
    candidates = coll.find(query).sort('inserted_at', 1)

    docs: List[Dict[str, Any]] = []
    owner = os.environ.get('HOSTNAME') or f"pid-{os.getpid()}"
    for doc in candidates:
        if len(docs) >= batch:
            break
        try:
            if _locks.acquire_lock(coll, doc.get('_id'), 'followup_answer_lock', owner, ttl_seconds=3600):
                docs.append(doc)
        except Exception:
            logger.exception('Failed to acquire followup answer lock for %s', doc.get('_id'))
    if not docs:
        logger.info('No articles require follow-up answers')
        return

    updated = 0
    for doc in docs:
        doc_id = doc.get('_id')
        try:
            questions = list(doc.get('follow_up_questions') or [])
            if not questions:
                continue
            groups = _normalize_groups(doc.get('follow_up_question_groups'), len(questions))
            prompt = _build_prompt(doc, questions, groups)
            result = run_with_search(prompt, text_format=FollowupAnswerMap)

            mapping = _coerce_answers_map(getattr(result, 'parsed', None))
            if not mapping and getattr(result, 'text', None):
                try:
                    mapping = _coerce_answers_map(json.loads(result.text))
                except Exception:
                    mapping = {}
            answers = _answers_to_list(mapping, questions)
            lm_log = getattr(result, 'lm_log', None)
            lm_dict = None
            if isinstance(lm_log, LMLogEntry):
                lm_dict = lm_log.model_dump() if hasattr(lm_log, 'model_dump') else lm_log.dict()
            elif lm_log is not None:
                try:
                    lm_dict = lm_log.model_dump() if hasattr(lm_log, 'model_dump') else lm_log.dict()
                except Exception:
                    lm_dict = None

            coll.update_one(
                {'_id': doc_id},
                {
                    '$set': {
                        'follow_up_answers': answers,
                        'follow_up_answers_lm_log': lm_dict,
                    },
                    '$unset': {'followup_answer_lock': ""},
                }
            )
            updated += 1
            logger.info("Stored follow-up answers for article %s", doc_id)
        except Exception:
            logger.exception('Failed answering follow-up questions for %s', doc_id)
            try:
                _locks.release_lock(coll, doc_id, 'followup_answer_lock')
            except Exception:
                pass

    logger.info('Answered follow-up questions for %d article(s)', updated)


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description='Answer follow-up questions for enriched articles')
    p.add_argument('--batch', type=int, default=10)
    args = p.parse_args()
    run(args.batch)
