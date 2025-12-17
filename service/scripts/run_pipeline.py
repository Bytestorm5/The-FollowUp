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
import os
import subprocess
import sys
from pathlib import Path


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

        completed = subprocess.run(cmd, env=env)
        if completed.returncode != 0:
            print(f"Script failed: {path} (exit {completed.returncode})")
            if args.stop_on_error:
                return completed.returncode

    print("\nPipeline finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
