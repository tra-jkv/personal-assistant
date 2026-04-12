"""
Period Report Service

Generates reports for different time periods (monthly, quarterly)
Reads from database instead of calling APIs (much faster!)
"""

from datetime import datetime, timedelta
from typing import Dict, List
from collections import Counter
from sqlalchemy.orm import Session
import json
from backend.models import DailyActivity, DailySummary


class PeriodReportService:
    """Service to generate period-based reports from database"""

    def __init__(self, db: Session):
        self.db = db

    def generate_monthly_report(self) -> Dict:
        """
        Generate report for the last 30 days

        Returns:
            Aggregated report with statistics and activity data
        """
        return self._generate_period_report(days=30, period_name="Monthly")

    def generate_quarterly_report(self) -> Dict:
        """
        Generate report for the last 90 days (quarter)

        Returns:
            Aggregated report with statistics and activity data
        """
        return self._generate_period_report(days=90, period_name="Quarterly")

    def _generate_period_report(self, days: int, period_name: str) -> Dict:
        """
        Generate report for a specific period by reading from database

        Args:
            days: Number of days to look back
            period_name: Name of the period (e.g., "Monthly", "Quarterly")

        Returns:
            Comprehensive report with stats and activity
        """
        since = datetime.utcnow() - timedelta(days=days)
        since = since.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = datetime.utcnow()

        report = {
            "period": period_name,
            "days": days,
            "start_date": since.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
            "github": {},
            "jira": {},
            "statistics": {},
            "insights": {},
            "errors": [],
        }

        try:
            # Get activities from database
            activities = (
                self.db.query(DailyActivity)
                .filter(DailyActivity.activity_date >= since)
                .all()
            )

            # Get daily summaries from database
            summaries = (
                self.db.query(DailySummary)
                .filter(DailySummary.summary_date >= since)
                .all()
            )

            # Separate GitHub and Jira activities
            github_activities = [a for a in activities if a.source == "github"]
            jira_activities = [a for a in activities if a.source == "jira"]

            # Build GitHub report from database
            report["github"] = self._build_github_report(github_activities)
            report["statistics"]["github"] = self._calculate_github_stats_from_db(
                github_activities
            )
            report["insights"]["github"] = self._generate_github_insights_from_db(
                github_activities, days
            )

            # Build Jira report from database
            report["jira"] = self._build_jira_report(jira_activities)
            report["statistics"]["jira"] = self._calculate_jira_stats_from_db(
                jira_activities
            )
            report["insights"]["jira"] = self._generate_jira_insights_from_db(
                jira_activities, summaries, days
            )

            # Calculate overall summary
            report["summary"] = self._calculate_summary_from_summaries(summaries)

        except Exception as e:
            report["errors"].append(f"Database error: {str(e)}")

        return report

    def _build_github_report(self, activities: List[DailyActivity]) -> Dict:
        """Build GitHub report section from database activities"""
        commits = []
        prs = []
        issues = []
        reviews = []

        for activity in activities:
            try:
                metadata = (
                    json.loads(activity.extra_data) if activity.extra_data else {}
                )
            except:
                metadata = {}

            if activity.activity_type == "commit":
                commits.append(
                    {
                        "sha": activity.external_id,
                        "message": activity.title,
                        "url": activity.url,
                        "repo": activity.repository,
                    }
                )
            elif activity.activity_type == "pull_request":
                prs.append(
                    {
                        "number": activity.external_id,
                        "title": activity.title,
                        "state": activity.status,
                        "url": activity.url,
                        "repo": activity.repository,
                    }
                )
            elif activity.activity_type == "issue":
                issues.append(
                    {
                        "number": activity.external_id,
                        "title": activity.title,
                        "state": activity.status,
                        "url": activity.url,
                        "repo": activity.repository,
                    }
                )
            elif activity.activity_type == "review":
                reviews.append(
                    {
                        "pr_number": activity.external_id,
                        "pr_title": activity.title,
                        "state": activity.status,
                        "url": activity.url,
                        "repo": activity.repository,
                    }
                )

        return {
            "commits": commits,
            "pull_requests": prs,
            "issues": issues,
            "reviews": reviews,
        }

    def _build_jira_report(self, activities: List[DailyActivity]) -> Dict:
        """Build Jira report section from database activities"""
        assigned_issues = []
        transitions = []

        for activity in activities:
            try:
                metadata = (
                    json.loads(activity.extra_data) if activity.extra_data else {}
                )
            except:
                metadata = {}

            if activity.activity_type == "assigned_issue":
                assigned_issues.append(
                    {
                        "key": activity.external_id,
                        "summary": activity.title,
                        "status": activity.status,
                        "url": activity.url,
                    }
                )
            elif activity.activity_type == "transition":
                assigned_issues.append(
                    {
                        "issue_key": activity.external_id,
                        "title": activity.title,
                        "to_status": activity.status,
                    }
                )

        return {
            "assigned_issues": assigned_issues,
            "worked_issues": [],
            "transitions": transitions,
            "comments": [],
        }

    def _calculate_github_stats_from_db(self, activities: List[DailyActivity]) -> Dict:
        """Calculate detailed GitHub statistics from database activities"""
        commits = [a for a in activities if a.activity_type == "commit"]
        prs = [a for a in activities if a.activity_type == "pull_request"]
        issues = [a for a in activities if a.activity_type == "issue"]
        reviews = [a for a in activities if a.activity_type == "review"]

        stats = {
            "total_commits": len(commits),
            "total_prs": len(prs),
            "total_issues": len(issues),
            "total_reviews": len(reviews),
            "prs_by_state": Counter(),
            "issues_by_state": Counter(),
            "top_repositories": Counter(),
            "commits_by_repo": Counter(),
        }

        # Analyze PRs
        for pr in prs:
            stats["prs_by_state"][pr.status or "unknown"] += 1
            if pr.repository:
                stats["top_repositories"][pr.repository] += 1

        # Analyze issues
        for issue in issues:
            stats["issues_by_state"][issue.status or "unknown"] += 1
            if issue.repository:
                stats["top_repositories"][issue.repository] += 1

        # Analyze commits
        for commit in commits:
            if commit.repository:
                stats["commits_by_repo"][commit.repository] += 1
                stats["top_repositories"][commit.repository] += 1

        # Convert Counters to sorted lists
        stats["top_repositories"] = stats["top_repositories"].most_common(10)
        stats["commits_by_repo"] = dict(stats["commits_by_repo"].most_common(10))
        stats["prs_by_state"] = dict(stats["prs_by_state"])
        stats["issues_by_state"] = dict(stats["issues_by_state"])

        return stats

    def _calculate_jira_stats_from_db(self, activities: List[DailyActivity]) -> Dict:
        """Calculate detailed Jira statistics from database"""
        assigned = [a for a in activities if a.activity_type == "assigned_issue"]
        transitions = [a for a in activities if a.activity_type == "transition"]

        stats = {
            "total_assigned": len(assigned),
            "total_worked": len(assigned),
            "total_comments": 0,
            "total_transitions": len(transitions),
            "issues_by_status": Counter(),
            "issues_by_type": Counter(),
            "issues_by_priority": Counter(),
            "transitions_by_status": Counter(),
        }

        # Analyze assigned issues
        for issue in assigned:
            if issue.status:
                stats["issues_by_status"][issue.status] += 1

        # Analyze transitions
        for trans in transitions:
            if trans.status:
                stats["transitions_by_status"][trans.status] += 1

        # Convert Counters to dicts
        stats["issues_by_status"] = dict(stats["issues_by_status"])
        stats["issues_by_type"] = dict(stats["issues_by_type"])
        stats["issues_by_priority"] = dict(stats["issues_by_priority"])
        stats["transitions_by_status"] = dict(stats["transitions_by_status"])

        return stats

    def _generate_github_insights_from_db(
        self, activities: List[DailyActivity], days: int
    ) -> Dict:
        """Generate insights from GitHub database activities"""
        commits = [a for a in activities if a.activity_type == "commit"]
        prs = [a for a in activities if a.activity_type == "pull_request"]
        reviews = [a for a in activities if a.activity_type == "review"]

        insights = {
            "daily_avg_commits": round(len(commits) / days, 1) if days > 0 else 0,
            "daily_avg_prs": round(len(prs) / days, 1) if days > 0 else 0,
            "most_active_repo": None,
            "productivity_score": 0,
        }

        # Find most active repo
        repo_counts = Counter()
        for activity in activities:
            if activity.repository:
                repo_counts[activity.repository] += 1

        if repo_counts:
            insights["most_active_repo"] = repo_counts.most_common(1)[0][0]

        # Calculate simple productivity score
        # Score = commits + (PRs * 3) + (reviews * 2)
        insights["productivity_score"] = (
            len(commits) + (len(prs) * 3) + (len(reviews) * 2)
        )

        return insights

    def _generate_jira_insights_from_db(
        self, activities: List[DailyActivity], summaries: List[DailySummary], days: int
    ) -> Dict:
        """Generate insights from Jira database activities"""
        assigned = [a for a in activities if a.activity_type == "assigned_issue"]
        transitions = [a for a in activities if a.activity_type == "transition"]

        insights = {
            "daily_avg_issues": round(len(assigned) / days, 1) if days > 0 else 0,
            "tickets_completed": 0,
            "completion_rate": 0,
        }

        # Count completed tickets (moved to Done/Closed)
        completed_statuses = {"Done", "Closed", "Resolved", "Complete"}
        for trans in transitions:
            if trans.status in completed_statuses:
                insights["tickets_completed"] += 1

        # Calculate completion rate
        if len(assigned) > 0:
            insights["completion_rate"] = round(
                (insights["tickets_completed"] / len(assigned)) * 100, 1
            )

        return insights

    def _calculate_summary_from_summaries(self, summaries: List[DailySummary]) -> Dict:
        """Calculate overall summary from daily summaries"""
        summary = {
            # GitHub totals
            "total_commits": sum(s.github_commits for s in summaries),
            "total_prs": sum(s.github_prs for s in summaries),
            "total_reviews": sum(s.github_reviews for s in summaries),
            # Jira totals
            "total_jira_issues": sum(s.jira_assigned for s in summaries),
            "total_jira_comments": sum(s.jira_comments for s in summaries),
            "total_jira_transitions": sum(s.jira_transitions for s in summaries),
            # Combined activity
            "total_activities": 0,
        }

        summary["total_activities"] = (
            summary["total_commits"]
            + summary["total_prs"]
            + summary["total_reviews"]
            + summary["total_jira_issues"]
        )

        return summary
