"""
GitHub Integration Service

Fetches user activity from GitHub:
- Commits
- Pull requests
- Issues
- Reviews

Supports two authentication methods:
1. GitHub CLI (gh) - Recommended, uses existing gh auth login
2. Personal Access Token - Fallback method
"""

from github import Github, GithubException
from datetime import datetime
from typing import List, Dict, Optional
import os
import subprocess


class GitHubService:
    """Service to fetch GitHub user activity"""

    def __init__(self, access_token: str):
        """
        Initialize GitHub service

        Args:
            access_token: GitHub personal access token
            Get from: https://github.com/settings/tokens
            Required scopes: repo, read:user
        """
        self.github = Github(access_token)
        self.user = self.github.get_user()

    def get_activity_since(self, since: datetime = None) -> Dict:
        """
        Get GitHub activity since a specific time (incremental sync)

        Args:
            since: DateTime to fetch from (default: start of today)

        Returns:
            {
                "commits": [...],
                "pull_requests": [...],
                "issues": [...],
                "reviews": [...],
                "sync_timestamp": "2026-04-11T14:30:00"
            }
        """
        if since is None:
            # Default to start of today
            today = datetime.now().date()
            since = datetime.combine(today, datetime.min.time())

        sync_time = datetime.utcnow()

        return {
            "commits": self.get_commits_since(since),
            "pull_requests": self.get_pull_requests_since(since),
            "issues": self.get_issues_updated_since(since),
            "reviews": self.get_reviews_since(since),
            "sync_timestamp": sync_time.isoformat(),
            "since": since.isoformat(),
        }

    def get_commits_since(self, since: datetime, limit: int = 500) -> List[Dict]:
        """Get commits authored by user since a specific time using Search API"""
        commits = []

        try:
            # Use Search API for commits - works with org repos too!
            since_str = since.strftime("%Y-%m-%d")
            query = f"author:{self.user.login} committer-date:>={since_str}"

            # Search commits
            search_results = self.github.search_commits(
                query=query, sort="committer-date"
            )

            for commit in search_results:
                commits.append(
                    {
                        "repo": commit.repository.full_name,
                        "message": commit.commit.message.split("\n")[
                            0
                        ],  # First line only
                        "sha": commit.sha[:7],
                        "url": commit.html_url,
                        "timestamp": commit.commit.committer.date,
                    }
                )
                if len(commits) >= limit:
                    break

        except GithubException as e:
            print(f"Error fetching commits: {e}")

        return commits

    def get_pull_requests_since(self, since: datetime, limit: int = 200) -> List[Dict]:
        """Get pull requests created or updated since a specific time"""
        prs = []

        try:
            # Search for PRs authored by user
            query = f"author:{self.user.login} updated:>={since.strftime('%Y-%m-%d')}"
            results = self.github.search_issues(query, sort="updated")

            for pr in results:
                if pr.pull_request:
                    prs.append(
                        {
                            "repo": pr.repository.full_name,
                            "title": pr.title,
                            "number": pr.number,
                            "state": pr.state,
                            "url": pr.html_url,
                            "created_at": pr.created_at,
                            "updated_at": pr.updated_at,
                        }
                    )
                    if len(prs) >= limit:
                        break

        except GithubException as e:
            print(f"Error fetching PRs: {e}")

        return prs

    def get_issues_updated_since(self, since: datetime, limit: int = 100) -> List[Dict]:
        """Get issues assigned to or created by user since a specific time"""
        issues = []

        try:
            # Search for issues involving user
            query = f"involves:{self.user.login} updated:>={since.strftime('%Y-%m-%d')} is:issue"
            results = self.github.search_issues(query, sort="updated")

            for issue in results:
                issues.append(
                    {
                        "repo": issue.repository.full_name,
                        "title": issue.title,
                        "number": issue.number,
                        "state": issue.state,
                        "url": issue.html_url,
                        "created_at": issue.created_at,
                        "updated_at": issue.updated_at,
                        "labels": [label.name for label in issue.labels],
                    }
                )
                if len(issues) >= limit:
                    break

        except GithubException as e:
            print(f"Error fetching issues: {e}")

        return issues

    def get_reviews_since(self, since: datetime, limit: int = 100) -> List[Dict]:
        """Get PR reviews submitted by user since a specific time"""
        reviews = []
        user_login = self.user.login

        try:
            # IMPORTANT: Use github.get_user(login).get_events() to get only YOUR events
            # self.user.get_events() returns events from repos you watch, not your events!
            events = self.github.get_user(user_login).get_events()

            for event in events:
                # Handle timezone comparison
                if event.created_at.replace(tzinfo=None) < since.replace(tzinfo=None):
                    break  # Events are sorted by time

                if event.type == "PullRequestReviewEvent":
                    # Double-check the actor is actually you
                    if event.actor.login != user_login:
                        continue

                    payload = event.payload
                    pr_data = payload.get("pull_request", {})
                    review_data = payload.get("review", {})

                    reviews.append(
                        {
                            "repo": event.repo.name,
                            "pr_title": pr_data.get("title", ""),
                            "pr_number": pr_data.get("number", ""),
                            "state": review_data.get("state", ""),
                            "url": pr_data.get("html_url", ""),
                            "timestamp": event.created_at,
                        }
                    )

                    if len(reviews) >= limit:
                        break

        except GithubException as e:
            print(f"Error fetching reviews: {e}")

        return reviews

    def get_username(self) -> str:
        """Get the authenticated user's username"""
        return self.user.login


def get_gh_cli_token() -> Optional[str]:
    """
    Get GitHub token from GitHub CLI (gh)

    Returns:
        GitHub token from gh CLI, or None if gh CLI not available/authenticated
    """
    try:
        # Check if gh CLI is installed
        result = subprocess.run(
            ["gh", "auth", "status"], capture_output=True, text=True, timeout=5
        )

        if result.returncode != 0:
            return None

        # Get token from gh CLI
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=5
        )

        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()

        return None

    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        # gh CLI not installed or not working
        return None


def create_github_service() -> Optional[GitHubService]:
    """
    Create GitHub service using available authentication method

    Tries in order:
    1. GitHub CLI (gh auth token) - Recommended
    2. GITHUB_TOKEN from .env file - Fallback

    Returns:
        GitHubService instance or None if no auth available
    """
    # Method 1: Try GitHub CLI first (recommended)
    gh_token = get_gh_cli_token()
    if gh_token:
        print("✓ Using GitHub CLI authentication")
        return GitHubService(gh_token)

    # Method 2: Fall back to GITHUB_TOKEN from .env
    env_token = os.getenv("GITHUB_TOKEN")
    if env_token:
        print("✓ Using GITHUB_TOKEN from .env")
        return GitHubService(env_token)

    # No authentication available
    print("Missing GitHub authentication")
    print("")
    print("Option 1 (Recommended): Use GitHub CLI")
    print("  1. Install: brew install gh")
    print("  2. Login: gh auth login")
    print("")
    print("Option 2 (Manual): Use Personal Access Token")
    print("  1. Get token from: https://github.com/settings/tokens")
    print("  2. Add to .env: GITHUB_TOKEN=your_token")
    print("  Required scopes: repo, read:user")

    return None
