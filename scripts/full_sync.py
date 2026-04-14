#!/usr/bin/env python3
"""
Full history sync CLI.

Usage:
    uv run python scripts/full_sync.py                  # Sync from DEFAULT_START to today
    uv run python scripts/full_sync.py --start 2025-06-01   # Custom start date
    uv run python scripts/full_sync.py --start 2025-06-01 --end 2025-09-30  # Custom range
    uv run python scripts/full_sync.py --jira-only      # Only Jira epics/tasks
    uv run python scripts/full_sync.py --activity-only  # Only daily activity (commits/PRs/reviews)

This wipes and rebuilds the selected date range — existing DailyActivity rows for
the range are deleted and reinserted.
"""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

# Make sure the project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()


def parse_date(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        print(f"Invalid date format '{s}' — expected YYYY-MM-DD")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Rebuild daily activity history from APIs.")
    parser.add_argument(
        "--start",
        metavar="YYYY-MM-DD",
        help="Start date (default: SYNC_START_DATE env var or 2025-01-01)",
    )
    parser.add_argument(
        "--end",
        metavar="YYYY-MM-DD",
        help="End date (default: today)",
    )
    parser.add_argument(
        "--jira-only",
        action="store_true",
        help="Only sync Jira epics and tasks (skip daily activity)",
    )
    parser.add_argument(
        "--activity-only",
        action="store_true",
        help="Only sync daily activity (skip Jira epics and tasks)",
    )
    args = parser.parse_args()

    from backend.database import SessionLocal
    from backend.services.background_sync import (
        DEFAULT_START,
        BackgroundSync,
        sync_jira_epics_and_stories,
    )

    start_date = parse_date(args.start) if args.start else DEFAULT_START
    end_date = parse_date(args.end) if args.end else date.today()

    if start_date > end_date:
        print(f"Start date {start_date} is after end date {end_date} — nothing to do.")
        sys.exit(1)

    print(f"Full sync: {start_date} → {end_date}")
    print()

    if not args.jira_only:
        db = SessionLocal()
        try:
            sync = BackgroundSync(db)
            sync.run_full_sync(start_date=start_date, end_date=end_date)
        finally:
            db.close()

    if not args.activity_only:
        print()
        print("Syncing Jira epics and tasks...")
        sync_jira_epics_and_stories(full=True)

    print()
    print("Done.")


if __name__ == "__main__":
    main()
