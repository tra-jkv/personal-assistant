"""
Jira Integration Service

Fetches user activity from Jira:
- Assigned issues
- Issues worked on
- Comments
- Transitions
"""

import os
from datetime import datetime
from typing import Dict, List, Optional

from jira import JIRA, JIRAError


class JiraService:
    """Service to fetch Jira user activity"""

    def __init__(self, server: str, email: str, api_token: str):
        """
        Initialize Jira service

        Args:
            server: Jira server URL (e.g., https://yourcompany.atlassian.net)
            email: Your Jira account email
            api_token: Jira API token
            Get from: https://id.atlassian.com/manage-profile/security/api-tokens
        """
        self.jira = JIRA(server=server, basic_auth=(email, api_token))
        self.current_user = email

    def get_activity_since(self, since: datetime = None) -> Dict:
        """
        Get Jira activity since a specific time (incremental sync)

        Args:
            since: DateTime to fetch from (default: start of today)

        Returns:
            {
                "assigned_issues": [...],
                "worked_issues": [...],
                "comments": [...],
                "transitions": [...],
                "sync_timestamp": "2026-04-11T14:30:00"
            }
        """
        if since is None:
            # Default to start of today
            since = datetime.combine(datetime.now().date(), datetime.min.time())

        sync_time = datetime.utcnow()

        return {
            "assigned_issues": self.get_assigned_issues(),
            "worked_issues": self.get_issues_worked_since(since),
            "comments": self.get_comments_since(since),
            "transitions": self.get_transitions_since(since),
            "sync_timestamp": sync_time.isoformat(),
            "since": since.isoformat(),
        }

    def get_assigned_issues(self) -> List[Dict]:
        """Get all issues currently assigned to user"""
        issues = []

        try:
            # JQL query for assigned issues
            jql = "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC"
            results = self.jira.search_issues(jql, maxResults=50)

            for issue in results:
                issues.append(
                    {
                        "key": issue.key,
                        "summary": issue.fields.summary,
                        "status": issue.fields.status.name,
                        "priority": issue.fields.priority.name if issue.fields.priority else "None",
                        "type": issue.fields.issuetype.name,
                        "url": f"{self.jira.server_url}/browse/{issue.key}",
                        "updated": issue.fields.updated,
                        "project": issue.fields.project.name,
                    }
                )

        except JIRAError as e:
            print(f"Error fetching assigned issues: {e}")

        return issues

    def get_issues_worked_since(self, since: datetime) -> List[Dict]:
        """Get issues updated/worked on since a specific time"""
        issues = []

        try:
            # JQL for issues updated since timestamp by current user
            since_str = since.strftime("%Y-%m-%d %H:%M")
            jql = f'updated >= "{since_str}" AND assignee = currentUser() ORDER BY updated DESC'
            results = self.jira.search_issues(jql, maxResults=50)

            for issue in results:
                issues.append(
                    {
                        "key": issue.key,
                        "summary": issue.fields.summary,
                        "status": issue.fields.status.name,
                        "type": issue.fields.issuetype.name,
                        "url": f"{self.jira.server_url}/browse/{issue.key}",
                        "updated": issue.fields.updated,
                    }
                )

        except JIRAError as e:
            print(f"Error fetching worked issues: {e}")

        return issues

    def get_comments_since(self, since: datetime) -> List[Dict]:
        """Get comments made since a specific time"""
        comments = []

        try:
            # Search issues with comments since timestamp
            since_str = since.strftime("%Y-%m-%d %H:%M")
            jql = f'commenter = currentUser() AND commented >= "{since_str}" ORDER BY updated DESC'
            results = self.jira.search_issues(jql, maxResults=20, expand="changelog")

            for issue in results:
                issue_comments = self.jira.comments(issue)

                for comment in issue_comments:
                    # Check if comment is from since timestamp
                    comment_datetime = datetime.strptime(comment.created, "%Y-%m-%dT%H:%M:%S.%f%z")
                    if comment_datetime.replace(tzinfo=None) >= since:
                        comments.append(
                            {
                                "issue_key": issue.key,
                                "issue_summary": issue.fields.summary,
                                "body": comment.body[:200],  # First 200 chars
                                "created": comment.created,
                                "url": f"{self.jira.server_url}/browse/{issue.key}",
                            }
                        )

        except JIRAError as e:
            print(f"Error fetching comments: {e}")

        return comments

    def get_transitions_since(self, since: datetime) -> List[Dict]:
        """Get status transitions made since a specific time"""
        transitions = []

        try:
            # JQL for issues where status changed since timestamp
            since_str = since.strftime("%Y-%m-%d %H:%M")
            jql = f'status CHANGED BY currentUser() AFTER "{since_str}" ORDER BY updated DESC'
            results = self.jira.search_issues(jql, maxResults=50, expand="changelog")

            for issue in results:
                # Get changelog
                changelog = issue.changelog

                for history in changelog.histories:
                    history_datetime = datetime.strptime(history.created, "%Y-%m-%dT%H:%M:%S.%f%z")

                    if history_datetime.replace(tzinfo=None) >= since:
                        for item in history.items:
                            if item.field == "status":
                                transitions.append(
                                    {
                                        "issue_key": issue.key,
                                        "issue_summary": issue.fields.summary,
                                        "from_status": item.fromString,
                                        "to_status": item.toString,
                                        "timestamp": history.created,
                                        "url": f"{self.jira.server_url}/browse/{issue.key}",
                                    }
                                )

        except JIRAError as e:
            print(f"Error fetching transitions: {e}")

        return transitions

    def get_user_email(self) -> str:
        """Get the current user's email"""
        return self.current_user

    def get_epics(self, projects: List[str] = None, max_results: int = 100) -> List[Dict]:
        """
        Get all epics from specified projects (or all accessible projects)

        Args:
            projects: List of project keys to fetch epics from (e.g., ['DL', 'KS'])
            max_results: Maximum number of epics to fetch

        Returns:
            List of epic dictionaries
        """
        epics = []

        try:
            # Build JQL query
            jql_parts = ["issuetype = Epic"]
            if projects:
                project_filter = ", ".join(f'"{p}"' for p in projects)
                jql_parts.append(f"project in ({project_filter})")

            jql = " AND ".join(jql_parts) + " ORDER BY updated DESC"
            results = self.jira.search_issues(jql, maxResults=max_results)

            for issue in results:
                epics.append(
                    {
                        "key": issue.key,
                        "title": issue.fields.summary,
                        "status": issue.fields.status.name,
                        "project": issue.fields.project.key,
                        "url": f"{self.jira.server_url}/browse/{issue.key}",
                        "updated": issue.fields.updated,
                    }
                )

        except JIRAError as e:
            print(f"Error fetching epics: {e}")

        return epics

    def get_my_stories_for_project(self, project_key: str) -> Dict[str, List[Dict]]:
        """
        Get all stories and subtasks where user is involved for a project.
        Returns items grouped by epic key.

        This is more efficient than querying per-epic as it uses fewer API calls.

        Args:
            project_key: Project key (e.g., 'DL')

        Returns:
            Dict mapping epic_key -> list of stories/subtasks
        """
        stories_by_epic = {}
        seen_keys = set()

        try:
            # Strategy 1: Stories directly assigned to me
            print(f"    Fetching stories assigned to me in {project_key}...")
            jql1 = f"project = {project_key} AND issuetype != Sub-task AND issuetype != Epic AND assignee = currentUser() ORDER BY updated DESC"
            results1 = self.jira.search_issues(jql1, maxResults=200)

            for issue in results1:
                if issue.key in seen_keys:
                    continue
                seen_keys.add(issue.key)

                # Get epic key from Epic Link field or parent
                epic_key = self._get_epic_key(issue)
                if epic_key:
                    if epic_key not in stories_by_epic:
                        stories_by_epic[epic_key] = []
                    stories_by_epic[epic_key].append(self._issue_to_story_dict(issue, epic_key))

            print(f"      Found {len(seen_keys)} stories directly assigned")

            # Strategy 2: Get parent stories from my subtasks (stories where I have subtasks assigned)
            print(f"    Fetching my subtasks in {project_key}...")
            jql_subtasks = (
                f"project = {project_key} AND issuetype = Sub-task AND assignee = currentUser()"
            )
            subtasks = self.jira.search_issues(jql_subtasks, maxResults=200)

            # Collect parent keys that we don't have yet
            parent_keys_to_fetch = set()
            for subtask in subtasks:
                parent = getattr(subtask.fields, "parent", None)
                if parent:
                    parent_key = parent.key
                    if parent_key not in seen_keys:
                        parent_keys_to_fetch.add(parent_key)

            print(
                f"      Found {len(subtasks)} subtasks, {len(parent_keys_to_fetch)} parent stories to fetch"
            )

            # Fetch parent stories in bulk to get their epic keys
            if parent_keys_to_fetch:
                parent_keys_str = ", ".join(parent_keys_to_fetch)
                jql_parents = f"key in ({parent_keys_str})"
                parent_issues = self.jira.search_issues(jql_parents, maxResults=200)

                for issue in parent_issues:
                    if issue.key in seen_keys:
                        continue
                    seen_keys.add(issue.key)

                    epic_key = self._get_epic_key(issue)
                    if epic_key:
                        if epic_key not in stories_by_epic:
                            stories_by_epic[epic_key] = []
                        stories_by_epic[epic_key].append(self._issue_to_story_dict(issue, epic_key))

            total_stories = sum(len(s) for s in stories_by_epic.values())
            print(f"    Total: {total_stories} stories across {len(stories_by_epic)} epics")

        except JIRAError as e:
            print(f"Error fetching stories for project {project_key}: {e}")

        return stories_by_epic

    def get_subtasks_for_story(self, story_key: str) -> List[Dict]:
        """
        Get all subtasks for a given story.

        Args:
            story_key: Parent story key (e.g., 'DL-2133')

        Returns:
            List of subtask dictionaries
        """
        subtasks = []

        try:
            jql = f"parent = {story_key} ORDER BY status ASC"
            results = self.jira.search_issues(jql, maxResults=50)

            for issue in results:
                assignee_name = ""
                if hasattr(issue.fields, "assignee") and issue.fields.assignee:
                    assignee_name = issue.fields.assignee.displayName

                subtasks.append(
                    {
                        "key": issue.key,
                        "title": issue.fields.summary,
                        "status": issue.fields.status.name,
                        "assignee": assignee_name,
                        "url": f"{self.jira.server_url}/browse/{issue.key}",
                    }
                )

        except JIRAError as e:
            print(f"Error fetching subtasks for {story_key}: {e}")

        return subtasks

    def get_transitions_for_issue(self, issue_key: str) -> List[Dict]:
        """
        Get available transitions for an issue (story or subtask).

        Args:
            issue_key: Jira issue key (e.g., 'DL-3212')

        Returns:
            List of transition dictionaries with 'id' and 'name'
        """
        try:
            transitions = self.jira.transitions(issue_key)
            return [{"id": t["id"], "name": t["name"]} for t in transitions]
        except JIRAError as e:
            print(f"Error fetching transitions for {issue_key}: {e}")
            return []

    def transition_issue(self, issue_key: str, target_status: str) -> Dict:
        """
        Transition an issue (story or subtask) to a new status.

        Args:
            issue_key: Jira issue key (e.g., 'DL-3212')
            target_status: Target status name (e.g., 'Done', 'In Development')

        Returns:
            Dict with 'success', 'new_status', and optional 'error'
        """
        try:
            # Get available transitions
            transitions = self.jira.transitions(issue_key)

            # Find the transition matching target status (case-insensitive)
            target_lower = target_status.lower()
            transition_id = None
            transition_name = None

            for t in transitions:
                if t["name"].lower() == target_lower:
                    transition_id = t["id"]
                    transition_name = t["name"]
                    break

            if not transition_id:
                # Try partial match
                for t in transitions:
                    if target_lower in t["name"].lower() or t["name"].lower() in target_lower:
                        transition_id = t["id"]
                        transition_name = t["name"]
                        break

            if not transition_id:
                available = [t["name"] for t in transitions]
                return {
                    "success": False,
                    "error": f"No transition found for '{target_status}'. Available: {available}",
                }

            # Execute transition
            self.jira.transition_issue(issue_key, transition_id)

            # Get updated status
            issue = self.jira.issue(issue_key)
            new_status = issue.fields.status.name

            return {
                "success": True,
                "new_status": new_status,
                "transition_used": transition_name,
            }

        except JIRAError as e:
            return {"success": False, "error": f"Jira error: {str(e)}"}

    def get_subtasks_for_stories(self, story_keys: List[str]) -> Dict[str, List[Dict]]:
        """
        Get subtasks for multiple stories in batched queries.

        Args:
            story_keys: List of parent story keys

        Returns:
            Dict mapping story_key -> list of subtasks
        """
        subtasks_by_story = {key: [] for key in story_keys}

        if not story_keys:
            return subtasks_by_story

        # Batch queries to avoid JQL length limits (max ~20 keys per query for safety)
        batch_size = 20
        for i in range(0, len(story_keys), batch_size):
            batch_keys = story_keys[i : i + batch_size]

            try:
                keys_str = ", ".join(batch_keys)
                jql = f"parent in ({keys_str}) ORDER BY parent ASC, status ASC"

                # Paginate through all results
                start_at = 0
                max_results = 100
                while True:
                    results = self.jira.search_issues(jql, startAt=start_at, maxResults=max_results)

                    if not results:
                        break

                    for issue in results:
                        parent = getattr(issue.fields, "parent", None)
                        if not parent:
                            continue

                        parent_key = parent.key
                        if parent_key not in subtasks_by_story:
                            subtasks_by_story[parent_key] = []

                        assignee_name = ""
                        if hasattr(issue.fields, "assignee") and issue.fields.assignee:
                            assignee_name = issue.fields.assignee.displayName

                        subtasks_by_story[parent_key].append(
                            {
                                "key": issue.key,
                                "title": issue.fields.summary,
                                "status": issue.fields.status.name,
                                "assignee": assignee_name,
                                "url": f"{self.jira.server_url}/browse/{issue.key}",
                            }
                        )

                    # Check if we got all results
                    if len(results) < max_results:
                        break
                    start_at += max_results

            except JIRAError as e:
                print(f"Error fetching subtasks batch: {e}")

        return subtasks_by_story

    def _get_epic_key(self, issue) -> Optional[str]:
        """Extract epic key from an issue (via parent field for next-gen projects)"""
        # For next-gen Jira projects, epics are linked via parent field
        parent = getattr(issue.fields, "parent", None)
        if parent:
            # The parent field contains an Issue object with basic info
            # Check if parent is an Epic by its issuetype
            parent_type = getattr(parent.fields, "issuetype", None)
            if parent_type and parent_type.name == "Epic":
                return parent.key

        # Fallback: Try Epic Link custom field (classic projects)
        for field_name in [
            "customfield_10014",
            "customfield_10008",
            "customfield_10000",
        ]:
            epic_link = getattr(issue.fields, field_name, None)
            if (
                epic_link
                and isinstance(epic_link, str)
                and epic_link.startswith(issue.key.split("-")[0])
            ):
                return epic_link

        return None

    def get_stories_for_epic(self, epic_key: str, assigned_to_me: bool = False) -> List[Dict]:
        """
        Get stories/issues belonging to an epic

        Args:
            epic_key: Epic issue key (e.g., 'DL-100')
            assigned_to_me: If True, only return stories assigned to current user

        Returns:
            List of story dictionaries
        """
        stories = []

        try:
            jql_parts = [f'("Epic Link" = {epic_key} OR parent = {epic_key})']

            if assigned_to_me:
                jql_parts.append("assignee = currentUser()")

            jql = " AND ".join(jql_parts) + " ORDER BY status ASC"
            results = self.jira.search_issues(jql, maxResults=100)

            for issue in results:
                stories.append(self._issue_to_story_dict(issue, epic_key))

        except JIRAError as e:
            print(f"Error fetching stories for epic {epic_key}: {e}")

        return stories

    def _issue_to_story_dict(self, issue, epic_key: str) -> Dict:
        """Convert a Jira issue to a story dictionary"""
        assignee_name = ""
        if hasattr(issue.fields, "assignee") and issue.fields.assignee:
            assignee_name = issue.fields.assignee.displayName

        # Extract sprint info
        sprint_id = None
        sprint_name = ""
        sprint_info = self._get_sprint_info(issue)
        if sprint_info:
            sprint_id = sprint_info.get("id")
            sprint_name = sprint_info.get("name", "")

        return {
            "key": issue.key,
            "epic_key": epic_key,
            "title": issue.fields.summary,
            "status": issue.fields.status.name,
            "assignee": assignee_name,
            "type": issue.fields.issuetype.name,
            "url": f"{self.jira.server_url}/browse/{issue.key}",
            "updated": issue.fields.updated,
            "sprint_id": sprint_id,
            "sprint_name": sprint_name,
        }

    def _get_sprint_info(self, issue) -> Optional[Dict]:
        """
        Extract sprint information from a Jira issue.
        Sprint field is typically a custom field (varies by instance).
        Returns the active sprint if available, otherwise the most recent sprint.
        """
        # Common sprint custom field names - order by most likely
        sprint_fields = [
            "customfield_10115",  # Sprint (most common in this instance)
            "customfield_10020",
            "customfield_10007",
            "customfield_10004",
            "customfield_10005",
        ]

        for field_name in sprint_fields:
            sprint_data = getattr(issue.fields, field_name, None)
            if sprint_data:
                # Sprint field can be a list of sprint objects or strings
                if isinstance(sprint_data, list) and len(sprint_data) > 0:
                    # First, try to find an active sprint
                    active_sprint = None
                    future_sprint = None
                    last_sprint = sprint_data[-1]

                    for sprint in sprint_data:
                        state = getattr(sprint, "state", "")
                        if state == "active":
                            active_sprint = sprint
                            break
                        elif state == "future" and not future_sprint:
                            future_sprint = sprint

                    # Prefer active > future > last in list
                    sprint = active_sprint or future_sprint or last_sprint

                    # Handle different formats
                    if hasattr(sprint, "id") and hasattr(sprint, "name"):
                        # Sprint object (PropertyHolder)
                        return {
                            "id": sprint.id,
                            "name": sprint.name,
                            "state": getattr(sprint, "state", ""),
                        }
                    elif isinstance(sprint, str):
                        # Parse sprint string format: "com.atlassian.greenhopper.service.sprint.Sprint@...[id=123,name=Sprint 42,...]"
                        import re

                        id_match = re.search(r"id=(\d+)", sprint)
                        name_match = re.search(r"name=([^,\]]+)", sprint)
                        state_match = re.search(r"state=([^,\]]+)", sprint)

                        if name_match:
                            return {
                                "id": int(id_match.group(1)) if id_match else None,
                                "name": name_match.group(1),
                                "state": state_match.group(1) if state_match else "",
                            }
                    elif isinstance(sprint, dict):
                        # Dict format
                        return {
                            "id": sprint.get("id"),
                            "name": sprint.get("name", ""),
                            "state": sprint.get("state", ""),
                        }

        return None

    def sync_epics_and_stories(
        self, projects: List[str] = None, stories_assigned_to_me: bool = True
    ) -> Dict:
        """
        Sync all epics and their stories from Jira

        Args:
            projects: List of project keys to sync (e.g., ['DL']). Defaults to ['DL'].
            stories_assigned_to_me: If True, only sync stories assigned to current user
                                   or stories where user has subtasks

        Returns:
            {
                "epics": [...],
                "stories": [...],
                "epic_count": int,
                "story_count": int,
                "sync_timestamp": str
            }
        """
        sync_time = datetime.utcnow()

        # Default to project key from environment
        if projects is None:
            project_key = os.getenv("JIRA_PROJECT_KEY", "")
            projects = [project_key] if project_key else []

        # Fetch all epics from specified projects
        print(f"  Fetching epics from projects: {projects}")
        epics = self.get_epics(projects=projects)
        print(f"  Found {len(epics)} epics")

        # Create a set of epic keys for filtering
        epic_keys = {e["key"] for e in epics}

        all_stories = []

        if stories_assigned_to_me:
            # Use efficient bulk fetch per project
            for project_key in projects:
                stories_by_epic = self.get_my_stories_for_project(project_key)

                # Only include stories from our epics
                for epic_key, stories in stories_by_epic.items():
                    if epic_key in epic_keys:
                        all_stories.extend(stories)
        else:
            # Fetch all stories for each epic
            for epic in epics:
                stories = self.get_stories_for_epic(epic["key"], assigned_to_me=False)
                all_stories.extend(stories)

        print(f"  Total: {len(all_stories)} stories for sync")

        return {
            "epics": epics,
            "stories": all_stories,
            "epic_count": len(epics),
            "story_count": len(all_stories),
            "sync_timestamp": sync_time.isoformat(),
        }

    def update_issue(
        self,
        issue_key: str,
        status: str = None,
        assignee: str = None,
        summary: str = None,
        description: str = None,
    ) -> Dict:
        """
        Update a Jira issue (for sync-back from local changes)

        Args:
            issue_key: Jira issue key (e.g., 'DL-1234')
            status: New status name to transition to (e.g., 'In Progress', 'Done')
            assignee: Assignee email or account ID (None = keep current, "" = unassign)
            summary: New summary/title
            description: New description

        Returns:
            {
                "success": bool,
                "key": str,
                "status": str,
                "message": str
            }
        """
        try:
            issue = self.jira.issue(issue_key)

            # Build fields to update
            fields = {}
            if summary is not None:
                fields["summary"] = summary
            if description is not None:
                fields["description"] = description

            # Update fields if any
            if fields:
                issue.update(fields=fields)

            # Handle status transition
            if status:
                # Get available transitions
                transitions = self.jira.transitions(issue)
                target_transition = None

                for t in transitions:
                    # Match by target status name (case-insensitive)
                    if t["to"]["name"].lower() == status.lower():
                        target_transition = t
                        break

                if target_transition:
                    self.jira.transition_issue(issue, target_transition["id"])
                else:
                    # List available transitions for debugging
                    available = [f"{t['name']} -> {t['to']['name']}" for t in transitions]
                    return {
                        "success": False,
                        "key": issue_key,
                        "status": issue.fields.status.name,
                        "message": f"Cannot transition to '{status}'. Available: {available}",
                    }

            # Handle assignee change
            if assignee is not None:
                if assignee == "":
                    # Unassign
                    self.jira.assign_issue(issue, None)
                else:
                    # Search for user by email or name
                    users = self.jira.search_users(query=assignee, maxResults=1)
                    if users:
                        self.jira.assign_issue(issue, users[0].accountId)
                    else:
                        return {
                            "success": False,
                            "key": issue_key,
                            "status": issue.fields.status.name,
                            "message": f"User not found: {assignee}",
                        }

            # Fetch updated issue
            updated_issue = self.jira.issue(issue_key)

            return {
                "success": True,
                "key": issue_key,
                "status": updated_issue.fields.status.name,
                "message": "Issue updated successfully",
            }

        except JIRAError as e:
            return {
                "success": False,
                "key": issue_key,
                "status": None,
                "message": f"Jira error: {e.text if hasattr(e, 'text') else str(e)}",
            }
        except Exception as e:
            return {
                "success": False,
                "key": issue_key,
                "status": None,
                "message": f"Error: {str(e)}",
            }


def create_jira_service() -> Optional[JiraService]:
    """
    Create Jira service from environment variables

    Requires .env file with:
        JIRA_SERVER=https://yourcompany.atlassian.net
        JIRA_EMAIL=your.email@company.com
        JIRA_API_TOKEN=your_api_token

    Returns:
        JiraService instance or None if credentials missing
    """
    server = os.getenv("JIRA_SERVER")
    email = os.getenv("JIRA_EMAIL")
    token = os.getenv("JIRA_API_TOKEN")

    if not all([server, email, token]):
        print("Missing Jira credentials in .env file")
        print("Required: JIRA_SERVER, JIRA_EMAIL, JIRA_API_TOKEN")
        print("Get API token from: https://id.atlassian.com/manage-profile/security/api-tokens")
        return None

    return JiraService(server, email, token)
