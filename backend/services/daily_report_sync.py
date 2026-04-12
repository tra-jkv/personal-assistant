"""
Daily Report Sync Service

Aggregates activity from GitHub and Jira to generate daily reports
Uses incremental syncing to only fetch new data since last sync
"""

import json
from datetime import date, datetime
from typing import Dict

from sqlalchemy.orm import Session

from backend.models import DailyActivity, DailySummary

from .github_service import create_github_service
from .jira_service import create_jira_service
from .sync_manager import DEFAULT_SYNC_START, SyncManager


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


class DailyReportSync:
    """Service to sync and aggregate daily activity from GitHub and Jira"""

    def __init__(self, db: Session = None):
        self.github = create_github_service()
        self.jira = create_jira_service()
        self.sync_manager = SyncManager(db) if db else None
        self.db = db

    def sync_incremental(self, force_full: bool = False) -> Dict:
        """
        Perform incremental sync - only fetch data since last sync

        Args:
            force_full: If True, ignore last sync and fetch all data from Jan 1, 2026

        Returns:
            {
                "date": "2026-04-11",
                "github": {...},
                "jira": {...},
                "summary": {...},
                "sync_info": {
                    "github_since": "2026-04-11 10:30:00",
                    "jira_since": "2026-04-11 10:30:00"
                }
            }
        """
        report = {
            "date": date.today().isoformat(),
            "github": {},
            "jira": {},
            "summary": {},
            "sync_info": {},
            "errors": [],
        }

        # Determine sync times
        if self.sync_manager and not force_full:
            github_since = self.sync_manager.get_sync_since_time("github")
            jira_since = self.sync_manager.get_sync_since_time("jira")
        else:
            # Force full sync from default start date (Jan 1, 2026)
            github_since = DEFAULT_SYNC_START
            jira_since = DEFAULT_SYNC_START

        report["sync_info"]["github_since"] = github_since.isoformat()
        report["sync_info"]["jira_since"] = jira_since.isoformat()

        # Fetch GitHub activity incrementally
        if self.github:
            try:
                gh_activity = self.github.get_activity_since(github_since)
                report["github"] = gh_activity
                report["summary"]["total_commits"] = len(gh_activity.get("commits", []))
                report["summary"]["total_prs"] = len(gh_activity.get("pull_requests", []))
                report["summary"]["total_issues"] = len(gh_activity.get("issues", []))
                report["summary"]["total_reviews"] = len(gh_activity.get("reviews", []))

                # Update sync state
                if self.sync_manager:
                    self.sync_manager.update_sync_state("github", success=True)
            except Exception as e:
                report["errors"].append(f"GitHub error: {str(e)}")
                report["github"] = {"error": str(e)}
                if self.sync_manager:
                    self.sync_manager.update_sync_state("github", success=False, error=str(e))
        else:
            report["errors"].append("GitHub not configured")

        # Fetch Jira activity incrementally
        if self.jira:
            try:
                jira_activity = self.jira.get_activity_since(jira_since)
                report["jira"] = jira_activity
                report["summary"]["jira_assigned"] = len(jira_activity.get("assigned_issues", []))
                report["summary"]["jira_worked"] = len(jira_activity.get("worked_issues", []))
                report["summary"]["jira_comments"] = len(jira_activity.get("comments", []))
                report["summary"]["jira_transitions"] = len(jira_activity.get("transitions", []))

                # Update sync state
                if self.sync_manager:
                    self.sync_manager.update_sync_state("jira", success=True)
            except Exception as e:
                report["errors"].append(f"Jira error: {str(e)}")
                report["jira"] = {"error": str(e)}
                if self.sync_manager:
                    self.sync_manager.update_sync_state("jira", success=False, error=str(e))
        else:
            report["errors"].append("Jira not configured")

        # Save activity to database for historical reporting
        if self.db:
            self._save_activity_to_db(report)

        return report

    def _save_activity_to_db(self, report: Dict):
        """Save synced activity to database for monthly/quarterly reports"""
        try:
            today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

            # Save GitHub activities
            if "github" in report and "error" not in report["github"]:
                gh = report["github"]

                # Save commits
                for commit in gh.get("commits", []):
                    activity = DailyActivity(
                        activity_date=today,
                        source="github",
                        activity_type="commit",
                        external_id=commit.get("sha", ""),
                        title=commit.get("message", ""),
                        url=commit.get("url", ""),
                        repository=commit.get("repo", ""),
                        extra_data=json.dumps(commit, default=json_serial),
                    )
                    self.db.add(activity)

                # Save pull requests
                for pr in gh.get("pull_requests", []):
                    activity = DailyActivity(
                        activity_date=today,
                        source="github",
                        activity_type="pull_request",
                        external_id=str(pr.get("number", "")),
                        title=pr.get("title", ""),
                        url=pr.get("url", ""),
                        repository=pr.get("repo", ""),
                        status=pr.get("state", ""),
                        extra_data=json.dumps(pr, default=json_serial),
                    )
                    self.db.add(activity)

                # Save issues
                for issue in gh.get("issues", []):
                    activity = DailyActivity(
                        activity_date=today,
                        source="github",
                        activity_type="issue",
                        external_id=str(issue.get("number", "")),
                        title=issue.get("title", ""),
                        url=issue.get("url", ""),
                        repository=issue.get("repo", ""),
                        status=issue.get("state", ""),
                        extra_data=json.dumps(issue, default=json_serial),
                    )
                    self.db.add(activity)

                # Save reviews
                for review in gh.get("reviews", []):
                    activity = DailyActivity(
                        activity_date=today,
                        source="github",
                        activity_type="review",
                        external_id=str(review.get("pr_number", "")),
                        title=review.get("pr_title", ""),
                        url=review.get("url", ""),
                        repository=review.get("repo", ""),
                        status=review.get("state", ""),
                        extra_data=json.dumps(review, default=json_serial),
                    )
                    self.db.add(activity)

            # Save Jira activities
            if "jira" in report and "error" not in report["jira"]:
                jira = report["jira"]

                # Save assigned issues
                for issue in jira.get("assigned_issues", []):
                    activity = DailyActivity(
                        activity_date=today,
                        source="jira",
                        activity_type="assigned_issue",
                        external_id=issue.get("key", ""),
                        title=issue.get("summary", ""),
                        url=issue.get("url", ""),
                        status=issue.get("status", ""),
                        extra_data=json.dumps(issue, default=json_serial),
                    )
                    self.db.add(activity)

                # Save transitions
                for trans in jira.get("transitions", []):
                    activity = DailyActivity(
                        activity_date=today,
                        source="jira",
                        activity_type="transition",
                        external_id=trans.get("issue_key", ""),
                        title=f"{trans.get('from_status')} → {trans.get('to_status')}",
                        status=trans.get("to_status", ""),
                        extra_data=json.dumps(trans, default=json_serial),
                    )
                    self.db.add(activity)

            # Save daily summary
            summary = report.get("summary", {})
            daily_summary = (
                self.db.query(DailySummary).filter(DailySummary.summary_date == today).first()
            )

            if daily_summary:
                # Update existing summary
                daily_summary.github_commits = summary.get("total_commits", 0)
                daily_summary.github_prs = summary.get("total_prs", 0)
                daily_summary.github_issues = summary.get("total_issues", 0)
                daily_summary.github_reviews = summary.get("total_reviews", 0)
                daily_summary.jira_assigned = summary.get("jira_assigned", 0)
                daily_summary.jira_worked = summary.get("jira_worked", 0)
                daily_summary.jira_transitions = summary.get("jira_transitions", 0)
                daily_summary.jira_comments = summary.get("jira_comments", 0)
            else:
                # Create new summary
                daily_summary = DailySummary(
                    summary_date=today,
                    github_commits=summary.get("total_commits", 0),
                    github_prs=summary.get("total_prs", 0),
                    github_issues=summary.get("total_issues", 0),
                    github_reviews=summary.get("total_reviews", 0),
                    jira_assigned=summary.get("jira_assigned", 0),
                    jira_worked=summary.get("jira_worked", 0),
                    jira_transitions=summary.get("jira_transitions", 0),
                    jira_comments=summary.get("jira_comments", 0),
                )
                self.db.add(daily_summary)

            self.db.commit()

        except Exception as e:
            print(f"Error saving activity to database: {e}")
            self.db.rollback()

    def format_report_as_text(self, report: Dict) -> str:
        """
        Format the report as readable text

        Returns:
            Formatted text report
        """
        lines = [f"Daily Report - {report['date']}", "=" * 50, ""]

        # GitHub section
        if "github" in report and "error" not in report["github"]:
            gh = report["github"]
            lines.append("📦 GitHub Activity:")

            if gh.get("commits"):
                lines.append(f"\n  Commits ({len(gh['commits'])}):")
                for commit in gh["commits"][:10]:  # Limit to 10
                    lines.append(f"    • [{commit['repo']}] {commit['message']}")

            if gh.get("pull_requests"):
                lines.append(f"\n  Pull Requests ({len(gh['pull_requests'])}):")
                for pr in gh["pull_requests"][:5]:
                    lines.append(f"    • [{pr['repo']}] {pr['title']} ({pr['state']})")

            if gh.get("issues"):
                lines.append(f"\n  Issues ({len(gh['issues'])}):")
                for issue in gh["issues"][:5]:
                    lines.append(f"    • [{issue['repo']}] {issue['title']} ({issue['state']})")

            lines.append("")

        # Jira section
        if "jira" in report and "error" not in report["jira"]:
            jira = report["jira"]
            lines.append("🎯 Jira Activity:")

            if jira.get("assigned_issues"):
                lines.append(f"\n  Assigned Issues ({len(jira['assigned_issues'])}):")
                for issue in jira["assigned_issues"][:10]:
                    lines.append(f"    • [{issue['key']}] {issue['summary']} ({issue['status']})")

            if jira.get("transitions"):
                lines.append(f"\n  Status Changes ({len(jira['transitions'])}):")
                for trans in jira["transitions"][:5]:
                    lines.append(
                        f"    • [{trans['issue_key']}] {trans['from_status']} → {trans['to_status']}"
                    )

            lines.append("")

        # Summary
        if report.get("summary"):
            summary = report["summary"]
            lines.append("📊 Summary:")
            lines.append(f"  • GitHub Commits: {summary.get('total_commits', 0)}")
            lines.append(f"  • GitHub PRs: {summary.get('total_prs', 0)}")
            lines.append(f"  • Jira Issues Worked: {summary.get('jira_worked', 0)}")
            lines.append(f"  • Jira Status Changes: {summary.get('jira_transitions', 0)}")

        # Errors
        if report.get("errors"):
            lines.append("\n⚠️  Errors:")
            for error in report["errors"]:
                lines.append(f"  • {error}")

        return "\n".join(lines)
