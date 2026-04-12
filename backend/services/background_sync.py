"""
Background Sync Service

Syncs data one day at a time to avoid timeouts.
Saves progress so it can be resumed if interrupted.
"""

import json
import os
import threading
from datetime import date, datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy.orm import Session

load_dotenv()

from backend.database import SessionLocal  # noqa: E402
from backend.models import DailyActivity, DailySummary, Epic, SyncState, Task  # noqa: E402

from .github_service import create_github_service  # noqa: E402
from .jira_service import create_jira_service  # noqa: E402

# Default start date — read from SYNC_START_DATE env var, fallback to 2025-01-01
_sync_start_env = os.getenv("SYNC_START_DATE", "2025-01-01")
try:
    DEFAULT_START = date.fromisoformat(_sync_start_env)
except ValueError:
    DEFAULT_START = date(2025, 1, 1)

# Global sync state — prevents concurrent syncs

_sync_lock = threading.Lock()
_sync_status = {"running": False, "progress": "", "started_at": None}


def json_serial(obj):
    """JSON serializer for datetime objects"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


class BackgroundSync:
    """Syncs data one day at a time"""

    def __init__(self, db: Session):
        self.db = db
        self.github = create_github_service()
        self.jira = create_jira_service()

        # Cache for bulk fetched data
        self._github_commits_cache = None
        self._github_prs_cache = None
        self._github_reviews_cache = None
        self._jira_issues_cache = None

    def get_last_synced_date(self) -> Optional[date]:
        """Get the last date that was successfully synced"""
        state = self.db.query(SyncState).filter(SyncState.source == "background").first()
        if state and state.last_sync_at:
            return state.last_sync_at.date()
        return None

    def set_last_synced_date(self, d: date):
        """Save the last synced date"""
        state = self.db.query(SyncState).filter(SyncState.source == "background").first()
        if state:
            state.last_sync_at = datetime.combine(d, datetime.min.time())
            state.total_syncs += 1
        else:
            state = SyncState(
                source="background",
                last_sync_at=datetime.combine(d, datetime.min.time()),
                last_sync_success=True,
                total_syncs=1,
            )
            self.db.add(state)
        self.db.commit()

    def prefetch_all_data(self, start_date: date, end_date: date):
        """Fetch all data at once, then distribute to days"""
        print("Prefetching all data from APIs...")

        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")
        # GitHub commits - fetch from all repos (no org filter)
        if self.github:
            print("  Fetching GitHub commits...", end=" ", flush=True)
            try:
                query = f"author:{self.github.user.login} committer-date:{start_str}..{end_str}"
                results = list(
                    self.github.github.search_commits(query=query, sort="committer-date")
                )
                self._github_commits_cache = []
                for c in results:
                    commit_date = c.commit.committer.date
                    if commit_date:
                        # Handle timezone - convert to date
                        if hasattr(commit_date, "date"):
                            d = commit_date.date()
                        else:
                            d = commit_date
                    else:
                        d = None
                    self._github_commits_cache.append(
                        {
                            "date": d,
                            "sha": c.sha[:7],
                            "message": c.commit.message.split("\n")[0],
                            "url": c.html_url,
                            "repo": c.repository.full_name,
                        }
                    )
                print(f"{len(self._github_commits_cache)} commits")
            except Exception as e:
                print(f"Error: {e}")
                self._github_commits_cache = []

            # GitHub PRs - fetch from all repos
            print("  Fetching GitHub PRs...", end=" ", flush=True)
            try:
                query = f"author:{self.github.user.login} created:{start_str}..{end_str} is:pr"
                results = list(self.github.github.search_issues(query=query, sort="created"))
                self._github_prs_cache = []
                for pr in results:
                    pr_date = pr.created_at
                    if pr_date:
                        if hasattr(pr_date, "date"):
                            d = pr_date.date()
                        else:
                            d = pr_date
                    else:
                        d = None
                    self._github_prs_cache.append(
                        {
                            "date": d,
                            "number": pr.number,
                            "title": pr.title,
                            "url": pr.html_url,
                            "repo": pr.repository.full_name,
                            "state": pr.state,
                        }
                    )
                print(f"{len(self._github_prs_cache)} PRs")
            except Exception as e:
                print(f"Error: {e}")
                self._github_prs_cache = []

            # GitHub reviews (using Search API for better coverage)
            print("  Fetching GitHub reviews...", end=" ", flush=True)
            try:
                user_login = self.github.user.login
                self._github_reviews_cache = []

                # Filter by updated date server-side to avoid paginating all history
                # GITHUB_ORGS: comma-separated list of GitHub org names to search for reviews
                # e.g. GITHUB_ORGS=mycompany,mycompany-internal
                github_orgs_env = os.getenv("GITHUB_ORGS", "")
                github_orgs = [o.strip() for o in github_orgs_env.split(",") if o.strip()]
                for org in github_orgs:
                    query = (
                        f"reviewed-by:{user_login} org:{org} is:pr updated:{start_str}..{end_str}"
                    )
                    results = self.github.github.search_issues(query, sort="updated", order="desc")

                    for pr in results:
                        pr_date = pr.updated_at.date() if pr.updated_at else None

                        # Extract repo name from repository_url
                        repo_name = pr.repository_url.split("/")[-1] if pr.repository_url else ""
                        repo_full = f"{org}/{repo_name}"

                        self._github_reviews_cache.append(
                            {
                                "date": pr_date,
                                "repo": repo_full,
                                "pr_title": pr.title or "",
                                "pr_number": pr.number,
                                "state": "approved",
                                "url": pr.html_url or "",
                            }
                        )

                print(f"{len(self._github_reviews_cache)} reviews")
            except Exception as e:
                print(f"Error: {e}")
                self._github_reviews_cache = []

        # Jira issues
        if self.jira:
            print("  Fetching Jira issues...", end=" ", flush=True)
            try:
                jql = f'assignee = currentUser() AND updated >= "{start_str}" ORDER BY updated ASC'
                results = self.jira.jira.search_issues(jql, maxResults=500)
                self._jira_issues_cache = []
                for issue in results:
                    updated = issue.fields.updated[:10] if issue.fields.updated else None
                    self._jira_issues_cache.append(
                        {
                            "date": datetime.strptime(updated, "%Y-%m-%d").date()
                            if updated
                            else None,
                            "key": issue.key,
                            "summary": issue.fields.summary,
                            "status": str(issue.fields.status),
                            "url": f"{self.jira.jira.server_url}/browse/{issue.key}",
                        }
                    )
                print(f"{len(self._jira_issues_cache)} issues")
            except Exception as e:
                print(f"Error: {e}")
                self._jira_issues_cache = []

        print()

    def sync_single_day(self, target_date: date) -> dict:
        """Sync a single day's data from cache"""
        start = datetime.combine(target_date, datetime.min.time())
        end = datetime.combine(target_date + timedelta(days=1), datetime.min.time())

        result = {
            "date": target_date.isoformat(),
            "commits": 0,
            "prs": 0,
            "reviews": 0,
            "jira_assigned": 0,
        }

        # Clear existing data for this day
        self.db.query(DailyActivity).filter(
            DailyActivity.activity_date >= start, DailyActivity.activity_date < end
        ).delete()
        self.db.query(DailySummary).filter(
            DailySummary.summary_date >= start, DailySummary.summary_date < end
        ).delete()

        # GitHub commits from cache
        if self._github_commits_cache:
            for commit in self._github_commits_cache:
                if commit["date"] == target_date:
                    activity = DailyActivity(
                        activity_date=start,
                        source="github",
                        activity_type="commit",
                        external_id=commit["sha"],
                        title=commit["message"],
                        url=commit["url"],
                        repository=commit["repo"],
                    )
                    self.db.add(activity)
                    result["commits"] += 1

        # GitHub PRs from cache
        if self._github_prs_cache:
            for pr in self._github_prs_cache:
                if pr["date"] == target_date:
                    activity = DailyActivity(
                        activity_date=start,
                        source="github",
                        activity_type="pull_request",
                        external_id=str(pr["number"]),
                        title=pr["title"],
                        url=pr["url"],
                        repository=pr["repo"],
                        status=pr["state"],
                    )
                    self.db.add(activity)
                    result["prs"] += 1

        # GitHub reviews from cache
        if self._github_reviews_cache:
            for review in self._github_reviews_cache:
                if review["date"] == target_date:
                    activity = DailyActivity(
                        activity_date=start,
                        source="github",
                        activity_type="review",
                        external_id=str(review["pr_number"]),
                        title=review["pr_title"],
                        url=review["url"],
                        repository=review["repo"],
                        status=review["state"],
                    )
                    self.db.add(activity)
                    result["reviews"] += 1

        # Jira from cache
        if self._jira_issues_cache:
            for issue in self._jira_issues_cache:
                if issue["date"] == target_date:
                    activity = DailyActivity(
                        activity_date=start,
                        source="jira",
                        activity_type="assigned_issue",
                        external_id=issue["key"],
                        title=issue["summary"],
                        url=issue["url"],
                        status=issue["status"],
                    )
                    self.db.add(activity)
                    result["jira_assigned"] += 1

        # Save daily summary
        summary = DailySummary(
            summary_date=start,
            github_commits=result["commits"],
            github_prs=result["prs"],
            github_issues=0,
            github_reviews=result["reviews"],
            jira_assigned=result["jira_assigned"],
            jira_worked=0,
            jira_transitions=0,
        )
        self.db.add(summary)
        self.db.commit()

        return result

    def run_full_sync(self, start_date: date = None, end_date: date = None):
        """Run a full sync month-by-month to avoid GitHub rate limits.

        Fetches one month of data at a time, commits progress after each month
        so the app stays responsive and sync can be resumed if interrupted.
        Skips if a sync is already running.
        """
        if not _sync_lock.acquire(blocking=False):
            print("Sync already in progress — skipping.")
            return

        try:
            _sync_status["running"] = True
            _sync_status["started_at"] = datetime.now().isoformat()

            if start_date is None:
                last_synced = self.get_last_synced_date()
                if last_synced and last_synced >= DEFAULT_START:
                    start_date = last_synced + timedelta(days=1)
                else:
                    start_date = DEFAULT_START

            if end_date is None:
                end_date = date.today()

            if start_date > end_date:
                print("Already up to date!")
                _sync_status["progress"] = "Up to date"
                return

            total_days = (end_date - start_date).days + 1
            print(f"Syncing {total_days} days: {start_date} to {end_date} (month by month)")

            totals = {"commits": 0, "prs": 0, "reviews": 0, "jira": 0}

            # Build list of month chunks
            chunks = []
            chunk_start = start_date
            while chunk_start <= end_date:
                if chunk_start.month == 12:
                    chunk_end = date(chunk_start.year + 1, 1, 1) - timedelta(days=1)
                else:
                    chunk_end = date(chunk_start.year, chunk_start.month + 1, 1) - timedelta(days=1)
                chunk_end = min(chunk_end, end_date)
                chunks.append((chunk_start, chunk_end))
                chunk_start = chunk_end + timedelta(days=1)

            for i, (chunk_start, chunk_end) in enumerate(chunks, 1):
                _sync_status["progress"] = (
                    f"Month {i}/{len(chunks)}: {chunk_start.strftime('%b %Y')}"
                )
                print(f"\n[{i}/{len(chunks)}] {chunk_start} → {chunk_end}")

                # Prefetch just this month's data
                self.prefetch_all_data(chunk_start, chunk_end)

                # Distribute to individual days
                current = chunk_start
                while current <= chunk_end:
                    result = self.sync_single_day(current)
                    self.set_last_synced_date(current)

                    totals["commits"] += result["commits"]
                    totals["prs"] += result["prs"]
                    totals["reviews"] += result["reviews"]
                    totals["jira"] += result["jira_assigned"]

                    activity = (
                        result["commits"]
                        + result["prs"]
                        + result["reviews"]
                        + result["jira_assigned"]
                    )
                    if activity > 0:
                        print(
                            f"  {current}: commits={result['commits']}, prs={result['prs']}, "
                            f"reviews={result['reviews']}, jira={result['jira_assigned']}"
                        )
                    current += timedelta(days=1)

            _sync_status["progress"] = "Complete"
            print()
            print("=" * 50)
            print("Sync complete!")
            print(f"  Total commits: {totals['commits']}")
            print(f"  Total PRs: {totals['prs']}")
            print(f"  Total reviews: {totals['reviews']}")
            print(f"  Total Jira issues: {totals['jira']}")

        finally:
            _sync_status["running"] = False
            _sync_lock.release()


def sync_jira_epics_and_stories(projects: list = None):
    """
    Sync Jira epics and their stories/tasks to the database.

    Stories from Jira are stored in the unified Task model with:
    - is_synced=True
    - jira_key set to the Jira issue key
    - jira_status tracking the original Jira status

    Args:
        projects: List of project keys (e.g., ['DL', 'KS']).
                  If None, defaults to JIRA_PROJECT_KEY from env.
    """
    # Always default to the configured project key — never sync all projects
    if projects is None:
        project_key = os.getenv("JIRA_PROJECT_KEY", "").strip()
        projects = [project_key] if project_key else []

    if not projects:
        print("No JIRA_PROJECT_KEY configured. Skipping epic sync.")
        return

    db = SessionLocal()
    jira = create_jira_service()

    if not jira:
        print("Jira service not configured. Skipping epic sync.")
        return

    try:
        print("Syncing Jira epics and tasks...")

        # Fetch all epics and stories from Jira
        result = jira.sync_epics_and_stories(projects=projects)

        epics_synced = 0
        tasks_synced = 0
        tasks_created = 0
        tasks_updated = 0
        now = datetime.utcnow()

        # Sync epics
        for epic_data in result["epics"]:
            # Check if epic exists
            epic = db.query(Epic).filter(Epic.key == epic_data["key"]).first()

            if epic:
                # Update existing
                epic.title = epic_data["title"]
                epic.status = epic_data["status"]
                epic.jira_url = epic_data["url"]
                epic.last_synced = now
            else:
                # Create new
                epic = Epic(
                    key=epic_data["key"],
                    title=epic_data["title"],
                    status=epic_data["status"],
                    jira_url=epic_data["url"],
                    last_synced=now,
                )
                db.add(epic)

            epics_synced += 1

        db.commit()

        # Build epic -> project_id lookup from already-synced epics
        epic_project_map = {
            e.key: e.project_id for e in db.query(Epic).filter(Epic.project_id.isnot(None)).all()
        }

        # Sync stories as Tasks
        for story_data in result["stories"]:
            epic_key = story_data["epic_key"]
            project_id = epic_project_map.get(epic_key)

            # Parse the actual Jira updated timestamp
            jira_updated_at = None
            raw_updated = story_data.get("updated")
            if raw_updated:
                try:
                    # Jira returns ISO format: "2026-01-15T09:23:44.000+0100"
                    jira_updated_at = datetime.fromisoformat(
                        raw_updated[:19]  # strip timezone suffix for naive datetime
                    )
                except (ValueError, TypeError):
                    pass

            # Check if task exists (by jira_key)
            task = db.query(Task).filter(Task.jira_key == story_data["key"]).first()

            if task:
                # Update existing task (only if not pending sync-back)
                if not task.needs_sync_back:
                    task.epic_key = epic_key
                    task.title = story_data["title"]
                    task.status = story_data["status"]
                    task.jira_status = story_data["status"]
                    task.assignee = story_data["assignee"]
                    task.jira_url = story_data["url"]
                    task.sprint_id = story_data.get("sprint_id")
                    task.sprint_name = story_data.get("sprint_name", "")
                    task.last_synced = now
                    if jira_updated_at:
                        task.jira_updated_at = jira_updated_at
                    if project_id:
                        task.project_id = project_id
                else:
                    print(f"    Skipping {story_data['key']} - has pending local changes")
                tasks_updated += 1
            else:
                # Create new task
                task = Task(
                    title=story_data["title"],
                    status=story_data["status"],
                    jira_key=story_data["key"],
                    jira_status=story_data["status"],
                    jira_url=story_data["url"],
                    epic_key=epic_key,
                    project_id=project_id,
                    assignee=story_data["assignee"],
                    sprint_id=story_data.get("sprint_id"),
                    sprint_name=story_data.get("sprint_name", ""),
                    is_synced=True,
                    last_synced=now,
                    jira_updated_at=jira_updated_at,
                    needs_sync_back=False,
                )
                db.add(task)
                tasks_created += 1

            tasks_synced += 1

        db.commit()

        # Fetch subtasks for all synced stories
        print("  Fetching subtasks for stories...")
        story_keys = [s["key"] for s in result["stories"]]
        subtasks_by_story = jira.get_subtasks_for_stories(story_keys)

        subtasks_updated = 0
        for story_key, subtasks in subtasks_by_story.items():
            task = db.query(Task).filter(Task.jira_key == story_key).first()
            if task:
                task.subtasks_json = json.dumps(subtasks)
                subtasks_updated += 1

        db.commit()
        print(f"  Updated subtasks for {subtasks_updated} stories")

        print(
            f"Synced {epics_synced} epics and {tasks_synced} tasks ({tasks_created} new, {tasks_updated} updated)"
        )

        # Update sync state
        state = db.query(SyncState).filter(SyncState.source == "jira_epics").first()
        if state:
            state.last_sync_at = now
            state.total_syncs += 1
        else:
            state = SyncState(
                source="jira_epics",
                last_sync_at=now,
                last_sync_success=True,
                total_syncs=1,
            )
            db.add(state)
        db.commit()

    except Exception as e:
        print(f"Error syncing epics: {e}")
        import traceback

        traceback.print_exc()
        db.rollback()
    finally:
        db.close()
