#!/usr/bin/env python3
"""Run pipeline: scrape_all -> claim_process -> update_promises

Usage:
  python run_pipeline.py [--dry-run] [--stop-on-error]

By default it executes each script with the same Python interpreter used to run
this script. Use `--dry-run` to print the commands without executing them.
"""
from __future__ import annotations

import argparse
import datetime
import re
import os
import subprocess
import sys
from pathlib import Path

_HERE = os.path.dirname(__file__)
_SERVICE_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _SERVICE_ROOT)


# Enable DB logging at end of run
from util import mongo as _mongo


def main() -> int:
    parser = argparse.ArgumentParser(description="Run pipeline scripts in sequence")
    parser.add_argument("--dry-run", action="store_true", help="Print commands instead of running")
    parser.add_argument("--stop-on-error", action="store_true", help="Stop if a script exits with non-zero code")
    parser.add_argument("--date", help="Pipeline date to use (YYYY-MM-DD). Defaults to yesterday if not provided")
    args = parser.parse_args()

    # Determine date to run pipeline for. If not provided, default to yesterday in fixed UTC-5.
    if args.date:
        try:
            run_date = datetime.datetime.strptime(args.date, "%Y-%m-%d").date()
        except Exception:
            print("Error: --date must be in YYYY-MM-DD format")
            return 2
    else:
        try:
            # Prefer our fixed UTC-5 computation when available
            from util.timezone import pipeline_yesterday
            run_date = pipeline_yesterday()
        except Exception:
            # Fallback: system local yesterday
            run_date = datetime.date.today() - datetime.timedelta(days=1)

    print(f"\nRunning pipeline for date: {run_date}")
    date_str = run_date.isoformat()

    repo_root = Path(__file__).resolve().parent.parent
    run_started_at = datetime.datetime.utcnow()
    scripts_dir = repo_root / "service" / "scripts" if (repo_root / "service").exists() else repo_root / "scripts"
    # When running from repo root, scripts_dir should be service/scripts
    # If someone places this file elsewhere, fall back to sibling scripts dir

    scripts = [
        scripts_dir / "scrape_all.py",
        scripts_dir / "enrich_articles.py",
        scripts_dir / "claim_process.py",
        scripts_dir / "update_promises.py",
    ]

    python = sys.executable or "python"

    scrape_inserted = None
    scrape_updated = None
    ran_enrich = False
    ran_claims = False
    ran_updates = False

    for path in scripts:
        if not path.exists():
            print(f"Error: script not found: {path}")
            return 2

        # For the scraper, pass the date as positional arg. For all scripts, expose
        # the chosen date via env var `PIPELINE_RUN_DATE` so they can override "today".
        cmd = [python, str(path)]
        if path.name == 'scrape_all.py':
            cmd.append(date_str)

        print("\n-> Running:", " ".join(cmd))
        if args.dry_run:
            print(f"ENV PIPELINE_RUN_DATE={date_str}")
            continue

        env = os.environ.copy()
        env['PIPELINE_RUN_DATE'] = date_str
        # Optional hint for downstream (not required since we pass date explicitly)
        env['PIPELINE_TZ_OFFSET'] = '-05:00'

        # capture output so we can parse metrics when possible
        completed = subprocess.run(cmd, env=env, text=True, capture_output=True)
        if completed.stdout:
            print(completed.stdout)
        if completed.stderr:
            print(completed.stderr, file=sys.stderr)
        # parse scrape_all metrics
        if path.name == 'scrape_all.py' and completed.returncode == 0 and completed.stdout:
            m = re.search(r"Mongo: inserted=(\d+), updated=(\d+)", completed.stdout)
            if m:
                scrape_inserted = int(m.group(1))
                scrape_updated = int(m.group(2))
        if path.name == 'enrich_articles.py':
            ran_enrich = completed.returncode == 0
        if path.name == 'claim_process.py':
            ran_claims = completed.returncode == 0
        if path.name == 'update_promises.py':
            ran_updates = completed.returncode == 0
        if completed.returncode != 0:
            print(f"Script failed: {path} (exit {completed.returncode})")
            if args.stop_on_error:
                return completed.returncode

    # Build and insert silver_logs record regardless of individual step success
    log_doc = {
        'run_started_at': run_started_at,
        'run_finished_at': datetime.datetime.utcnow(),
        'pipeline_date': date_str,
        'scrape': {
            'inserted': scrape_inserted,
            'updated': scrape_updated,
        },
    }

    try:
        db = _mongo.DB
        # Enrichment priority counts (total across DB)
        if ran_enrich:
            try:
                bronze = db.get_collection('bronze_links')
                pipeline = [
                    { '$match': { 'priority': { '$exists': True } } },
                    { '$group': { '_id': '$priority', 'count': { '$sum': 1 } } },
                ]
                pri = {str(doc.get('_id')): doc.get('count') for doc in bronze.aggregate(pipeline)}
                log_doc['enrich'] = { 'priority_counts': pri }
            except Exception:
                log_doc['enrich'] = { 'error': 'priority_aggregate_failed' }

        # Claim totals by priority
        if ran_claims:
            try:
                claims = db.get_collection('silver_claims')
                pipeline = [
                    { '$group': { '_id': '$priority', 'count': { '$sum': 1 } } },
                ]
                pri = {str(doc.get('_id')): doc.get('count') for doc in claims.aggregate(pipeline)}
                log_doc['claims'] = { 'priority_counts': pri }
            except Exception:
                log_doc['claims'] = { 'error': 'claims_priority_aggregate_failed' }

        # Updates inserted this run: counts by verdict and by type (fact_check vs checkin)
        if ran_updates:
            try:
                updates = db.get_collection('silver_updates')
                run_end = datetime.datetime.utcnow()
                # window inclusive of start
                match = { 'created_at': { '$gte': run_started_at, '$lte': run_end } }
                # by verdict
                by_verdict = { }
                for d in updates.aggregate([
                    { '$match': match },
                    { '$group': { '_id': '$verdict', 'count': { '$sum': 1 } } },
                ]):
                    by_verdict[str(d.get('_id'))] = d.get('count')
                # by type via lookup to claims type
                by_type = { 'fact_check': 0, 'promise_checkin': 0, 'other': 0 }
                for d in updates.aggregate([
                    { '$match': match },
                    { '$lookup': { 'from': 'silver_claims', 'localField': 'claim_id', 'foreignField': '_id', 'as': 'claim' } },
                    { '$unwind': '$claim' },
                    { '$group': { '_id': '$claim.type', 'count': { '$sum': 1 } } },
                ]):
                    t = str(d.get('_id'))
                    if t == 'statement':
                        by_type['fact_check'] += d.get('count')
                    elif t in ('promise', 'goal'):
                        by_type['promise_checkin'] += d.get('count')
                    else:
                        by_type['other'] += d.get('count')
                total_updates = sum(by_verdict.values()) if by_verdict else 0
                log_doc['updates'] = {
                    'window': { 'from': run_started_at, 'to': run_end },
                    'total_inserted': total_updates,
                    'by_verdict': by_verdict,
                    'by_type': by_type,
                }
            except Exception:
                log_doc['updates'] = { 'error': 'update_aggregate_failed' }

        # Insert into silver_logs
        try:
            db.get_collection('silver_logs').insert_one(log_doc)
            print("Inserted silver_logs record.")
        except Exception as e:
            print(f"Failed to insert silver_logs record: {e}")
    except Exception as e:  # pragma: no cover
        print(f"Unexpected error building silver_logs: {e}")

    print("\nPipeline finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
