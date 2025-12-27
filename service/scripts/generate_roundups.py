import os
import sys
import datetime
import logging
from typing import Any, Dict, List, Optional, Tuple

_HERE = os.path.dirname(__file__)
_SERVICE_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _SERVICE_ROOT)

from util import mongo
from util.slug import generate_unique_slug
from util.llm_web import run_with_search, ToolSet
from util.model_select import MODEL_TABLE
from util.timezone import pipeline_today
from models import SilverRoundup, RoundupSeedArticle, RoundupResponseOutput

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

CUTOFF_DATE = datetime.date(2025, 12, 15)


def _prev_day(today: datetime.date) -> Tuple[datetime.date, datetime.date]:
    end = today - datetime.timedelta(days=1)
    start = end
    return start, end


def _prev_week(today: datetime.date) -> Tuple[datetime.date, datetime.date]:
    # Define week as Monday..Sunday; previous week is the one ending last Sunday
    # weekday: Monday=0..Sunday=6
    weekday = today.weekday()
    last_sunday = today - datetime.timedelta(days=weekday + 1)
    start = last_sunday - datetime.timedelta(days=6)
    end = last_sunday
    return start, end


def _prev_month(today: datetime.date) -> Tuple[datetime.date, datetime.date]:
    first_of_month = today.replace(day=1)
    last_day_prev = first_of_month - datetime.timedelta(days=1)
    start = last_day_prev.replace(day=1)
    end = last_day_prev
    return start, end


def _prev_year(today: datetime.date) -> Tuple[datetime.date, datetime.date]:
    start = today.replace(month=1, day=1) - datetime.timedelta(days=1)
    start = start.replace(month=1, day=1)
    end = start.replace(month=12, day=31)
    return start, end


def _exists_roundup(coll, rtype: str, start: datetime.date, end: datetime.date) -> bool:
    try:
        q = { 'roundup_type': rtype, 'period_start': start, 'period_end': end }
        try:
            q = mongo.normalize_dates(q)
        except Exception:
            pass
        return coll.count_documents(q, limit=1) > 0
    except Exception:
        logger.exception('Existence check failed for roundup %s %s..%s', rtype, start, end)
        return False


def _collect_news_seed_articles(start: datetime.date, end: datetime.date, limit: int = 20) -> List[RoundupSeedArticle]:
    bronze = getattr(mongo, 'bronze_links', None)
    claims = getattr(mongo, 'silver_claims', None)
    if bronze is None or claims is None:
        return []
    # Set TZ of start and end to UTC
    start = datetime.datetime.combine(start, datetime.time.min).replace(tzinfo=datetime.timezone.utc)
    end = datetime.datetime.combine(end, datetime.time.max).replace(tzinfo=datetime.timezone.utc)
    try:
        f = { 'date': { '$gte': start, '$lte': end } }
        cur = bronze.find(f)
    except Exception:
        logger.exception('Failed querying articles for period %s..%s', start, end)
        return []

    items: List[Tuple[int, Dict[str, Any]]] = []
    for a in cur:
        try:
            aid = a.get('_id')
            kt = a.get('key_takeaways') or []
            kt_len = len(kt) if isinstance(kt, list) else 0
            pr = int(a.get('priority') or 0)
            # number of claims referencing this article
            try:
                ccount = claims.count_documents({ 'article_id': str(aid) })
            except Exception:
                ccount = 0
            score = kt_len + ccount + pr
            items.append((score, a))
        except Exception:
            continue

    items.sort(key=lambda x: x[0], reverse=True)
    top = items[:limit]

    out: List[RoundupSeedArticle] = []
    for score, a in top:
        try:
            aid = a.get('_id')
            art_claims: List[str] = []
            try:
                ccur = claims.find({ 'article_id': str(aid) }, { 'claim': 1 }).limit(100)
                art_claims = [str(c.get('claim') or '') for c in ccur if c.get('claim')]
            except Exception:
                art_claims = []
            seed = RoundupSeedArticle(
                article_id=aid,
                title=a.get('title', ''),
                link=a.get('link', ''),
                score=score,
                key_takeaways=list(kt) if isinstance(kt, list) else None,
                claims=art_claims or None,
            )
            out.append(seed)
        except Exception:
            logger.exception('Failed to build seed article entry for %s', a.get('_id'))
            continue

    return out


def _collect_nested_roundups(rtype: str, start: datetime.date, end: datetime.date) -> List[RoundupSeedArticle]:
    """Return seed entries representing shorter-window roundups inside the period.

    - weekly: include up to 7 daily roundups
    - monthly: include up to 4 weekly roundups
    - yearly: include up to 12 monthly roundups
    """
    target_map = {
        'weekly': ('daily', 7),
        'monthly': ('weekly', 4),
        'yearly': ('monthly', 12),
    }
    if rtype not in target_map:
        return []

    sub_type, target_cnt = target_map[rtype]
    try:
        db = getattr(mongo, 'DB', None)
        if db is None:
            return []
        coll = db.get_collection('silver_roundups')
        q = {
            'roundup_type': sub_type,
            'period_start': {'$gte': start},
            'period_end': {'$lte': end},
        }
        try:
            q = mongo.normalize_dates(q)
        except Exception:
            pass
        cur = coll.find(q).sort('period_start', 1).limit(target_cnt)
        out: List[RoundupSeedArticle] = []
        for r in cur:
            try:
                rid = r.get('_id')
                title = r.get('title') or f"{sub_type.title()} Roundup ({r.get('period_start')}–{r.get('period_end')})"
                # Keep these first by giving a high score, though ordering preserves position
                seed = RoundupSeedArticle(
                    article_id=rid,
                    title=title,
                    link=None,
                    score=100000,
                    key_takeaways=None,
                    claims=None,
                )
                out.append(seed)
            except Exception:
                continue
        return out
    except Exception:
        logger.exception('Failed collecting nested roundups for %s %s..%s', rtype, start, end)
        return []


def _build_seed_markdown(seed_articles: List[RoundupSeedArticle]) -> str:
    lines: List[str] = []
    for s in seed_articles:
        try:
            title = s.title
            link = s.link or ''
            header = f"- {title} ({link})" if link else f"- {title}"
            lines.append(header)
            # key takeaways
            if s.key_takeaways:
                for kt in s.key_takeaways:
                    lines.append(f"  - {kt}")
            # claims
            if s.claims:
                lines.append("  - Claims:")
                for cl in s.claims:
                    lines.append(f"    - {cl}")
        except Exception:
            continue
    return "\n".join(lines)


def _load_roundup_template() -> str:
    path = os.path.join(_SERVICE_ROOT, 'prompts', 'roundup.md')
    with open(path, 'r', encoding='utf-8') as fh:
        return fh.read()


def _generate_roundup(rtype: str, start: datetime.date, end: datetime.date, template: str) -> Optional[Dict[str, Any]]:
    nested = _collect_nested_roundups(rtype, start, end)
    remaining = max(0, 20 - len(nested))
    articles = _collect_news_seed_articles(start, end, limit=remaining) if remaining else []
    seed = list(nested) + list(articles)
    seed_md = _build_seed_markdown(seed)
    # Compute how many internal articles from the period are not represented in the seed list
    omitted_count: Optional[int] = None
    try:
        bronze = getattr(mongo, 'bronze_links', None)
        if bronze is not None:
            start_dt = datetime.datetime.combine(start, datetime.time.min).replace(tzinfo=datetime.timezone.utc)
            end_dt = datetime.datetime.combine(end, datetime.time.max).replace(tzinfo=datetime.timezone.utc)
            total_count = int(bronze.count_documents({'date': {'$gte': start_dt, '$lte': end_dt}}))
            omitted_count = max(0, total_count - len(seed))
    except Exception:
        omitted_count = None
    user_prompt = (
        f"Time period: {start} to {end} ({rtype})\n\n"
        f"Seed articles (representative sample):\n{seed_md}\n\n"
        f"Articles in internal knowledge base but not in this seed list: {omitted_count if omitted_count is not None else 'unknown'}\n\n"
        "Write the roundup."
    )

    try:
        # Yearly: force [agent][high] with high reasoning effort. Others: defer to select_model.
        if rtype == 'yearly':
            agent_high_model, agent_high_effort = MODEL_TABLE['agent']['high']
            out = run_with_search(
                user_prompt,
                model=agent_high_model,
                effort=agent_high_effort,
                text_format=RoundupResponseOutput,
                task_system=template,
                tool_choices=[ToolSet.WEB_SEARCH, ToolSet.NEWS_SEARCH, ToolSet.INTERNAL_SEARCH],
            )
        else:
            out = run_with_search(
                user_prompt,
                text_format=RoundupResponseOutput,
                task_system=template,
                tool_choices=[ToolSet.WEB_SEARCH, ToolSet.NEWS_SEARCH, ToolSet.INTERNAL_SEARCH],
            )
    except Exception:
        logger.exception('LLM call failed for roundup %s %s..%s', rtype, start, end)
        return None

    title = ''
    body = (out.text or '').strip()
    sources_list: Optional[List[str]] = None
    try:
        parsed = getattr(out, 'parsed', None)
        if parsed is not None:
            title = getattr(parsed, 'title', '') or ''
            ptext = getattr(parsed, 'text', '') or ''
            if ptext:
                body = ptext
            try:
                srcs = getattr(parsed, 'sources', None)
                if isinstance(srcs, list):
                    # ensure strings only
                    sources_list = [str(s) for s in srcs if isinstance(s, (str, bytes))]
            except Exception:
                pass
    except Exception:
        pass

    if not title:
        title = f"{rtype.title()} Roundup ({start}–{end})"

    try:
        doc = SilverRoundup(
            roundup_type=rtype,
            period_start=start,
            period_end=end,
            title=title,
            summary_markdown=body,
            sources=sources_list,
            seed_articles=seed,
            lm_log=getattr(out, 'lm_log', None),
        ) # type: ignore
        return doc.model_dump() if hasattr(doc, 'model_dump') else doc.dict()
    except Exception:
        logger.exception('Failed to construct SilverRoundup for %s %s..%s', rtype, start, end)
        return None


def main():
    logging.basicConfig(level=logging.INFO)
    db = getattr(mongo, 'DB', None)
    if db is None:
        logger.error('Mongo DB not available')
        return
    coll = db.get_collection('silver_roundups')

    today = pipeline_today()
    template = _load_roundup_template()

    periods = [
        ('daily',) + _prev_day(today),
        ('weekly',) + _prev_week(today),
        ('monthly',) + _prev_month(today),
        ('yearly',) + _prev_year(today),
    ]

    for rtype, start, end in periods:
        try:
            # Skip any period that starts prior to the cutoff
            if start < CUTOFF_DATE:
                logger.info('Skipping %s roundup for %s..%s due to cutoff (%s)', rtype, start, end, CUTOFF_DATE)
                continue
            if _exists_roundup(coll, rtype, start, end):
                logger.info('Roundup exists for %s %s..%s', rtype, start, end)
                continue
            logger.info('Generating roundup for %s %s..%s', rtype, start, end)
            payload = _generate_roundup(rtype, start, end, template)
            if not payload:
                continue
            try:
                payload = mongo.normalize_dates(payload)
            except Exception:
                pass
            # Ensure slug exists and is unique in silver_roundups
            try:
                if not payload.get('slug'):
                    payload['slug'] = generate_unique_slug(coll, payload.get('title', ''), date=payload.get('period_end'))
            except Exception:
                logger.exception('Failed generating slug for roundup %s %s..%s', rtype, start, end)
            coll.insert_one(payload)
            logger.info('Inserted roundup for %s %s..%s', rtype, start, end)
        except Exception:
            logger.exception('Failed processing roundup for %s %s..%s', rtype, start, end)


if __name__ == '__main__':
    # Allow overriding pipeline date via CLI for backfills
    import argparse
    parser = argparse.ArgumentParser(description='Generate daily/weekly/monthly/yearly roundups if missing')
    parser.add_argument('--date', help='Pipeline date to use (YYYY-MM-DD). If provided, sets PIPELINE_RUN_DATE')
    args = parser.parse_args()
    if args.date:
        os.environ['PIPELINE_RUN_DATE'] = args.date
    main()
