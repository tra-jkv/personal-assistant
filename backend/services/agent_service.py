"""
Agentic AI Service

Provides function calling capabilities for the AI assistant to perform actions
on behalf of the user. Supports two modes:
- Plan: AI returns a plan of actions for user confirmation
- Execute: AI directly performs actions and returns results
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, List

import httpx
from sqlalchemy.orm import Session

from backend.models import (
    ActionItem,
    Goal,
    MeetingNote,
    Note,
    Project,
    Reminder,
    Task,
)
from backend.models.models import GoalStatus, Priority, ProjectStatus

# Gemini API configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"


# ── Tool Definitions ──────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "create_note",
        "description": "Create a new note to capture information, ideas, or documentation",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Title of the note"},
                "content": {
                    "type": "string",
                    "description": "Content/body of the note",
                },
                "tags": {"type": "string", "description": "Comma-separated tags"},
                "project_id": {
                    "type": "integer",
                    "description": "Optional project ID to link to",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "create_reminder",
        "description": "Create a reminder for a future task or event",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Title of the reminder"},
                "description": {"type": "string", "description": "Additional details"},
                "due_at": {
                    "type": "string",
                    "description": "Due date/time in ISO format (e.g., 2026-04-15T10:00:00)",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "description": "Priority level",
                },
                "project_id": {
                    "type": "integer",
                    "description": "Optional project ID to link to",
                },
            },
            "required": ["title", "due_at"],
        },
    },
    {
        "name": "complete_reminder",
        "description": "Mark a reminder as done/completed",
        "parameters": {
            "type": "object",
            "properties": {
                "reminder_id": {
                    "type": "integer",
                    "description": "ID of the reminder to complete",
                },
            },
            "required": ["reminder_id"],
        },
    },
    {
        "name": "create_task",
        "description": "Create a new task in the task board",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Title of the task"},
                "description": {"type": "string", "description": "Task description"},
                "status": {
                    "type": "string",
                    "enum": ["Backlog", "To Do", "In Progress", "In Review", "Done"],
                    "description": "Initial status",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "description": "Priority level",
                },
                "assignee": {
                    "type": "string",
                    "description": "Person assigned to the task",
                },
                "due_date": {
                    "type": "string",
                    "description": "Due date in ISO format (e.g., 2026-04-15)",
                },
                "project_id": {
                    "type": "integer",
                    "description": "Optional project ID to link to",
                },
                "epic_key": {
                    "type": "string",
                    "description": "Optional Jira epic key to link to",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "update_task_status",
        "description": "Move a task to a different status/column on the board. Can identify task by ID or Jira key (e.g., DL-2952)",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "Internal ID of the task to update (use this OR jira_key)",
                },
                "jira_key": {
                    "type": "string",
                    "description": "Jira issue key like DL-2952 (use this OR task_id)",
                },
                "status": {
                    "type": "string",
                    "description": "New status for the task (e.g., To Do, In Progress, In Development, Ready To Develop, Done, Blocked, In Review, Waiting, To Refine, Ready for estimate, Cancelled)",
                },
            },
            "required": ["status"],
        },
    },
    {
        "name": "create_goal",
        "description": "Create a new yearly goal or objective",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Goal title"},
                "description": {"type": "string", "description": "Goal description"},
                "year": {
                    "type": "integer",
                    "description": "Year for the goal (e.g., 2026)",
                },
                "target_date": {
                    "type": "string",
                    "description": "Target completion date in ISO format",
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "achieved", "cancelled", "deferred"],
                    "description": "Goal status",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "update_goal_progress",
        "description": "Update the progress percentage of a goal",
        "parameters": {
            "type": "object",
            "properties": {
                "goal_id": {"type": "integer", "description": "ID of the goal"},
                "progress_pct": {
                    "type": "integer",
                    "description": "Progress percentage (0-100)",
                },
            },
            "required": ["goal_id", "progress_pct"],
        },
    },
    {
        "name": "create_project",
        "description": "Create a new project to organize work",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Project name"},
                "description": {"type": "string", "description": "Project description"},
                "status": {
                    "type": "string",
                    "enum": ["active", "paused", "completed", "archived"],
                    "description": "Project status",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "description": "Priority level",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date in ISO format",
                },
                "end_date": {"type": "string", "description": "End date in ISO format"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "link_project_to_goal",
        "description": "Link a project to a goal",
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "ID of the project"},
                "goal_id": {
                    "type": "integer",
                    "description": "ID of the goal to link to",
                },
            },
            "required": ["project_id", "goal_id"],
        },
    },
    {
        "name": "create_meeting",
        "description": "Create a meeting note to document a meeting",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Meeting title"},
                "meeting_date": {
                    "type": "string",
                    "description": "Meeting date in ISO format (e.g., 2026-04-15)",
                },
                "attendees": {
                    "type": "string",
                    "description": "Comma-separated list of attendees",
                },
                "summary": {"type": "string", "description": "Meeting summary"},
                "notes": {"type": "string", "description": "Detailed meeting notes"},
                "project_id": {
                    "type": "integer",
                    "description": "Optional project ID to link to",
                },
            },
            "required": ["title", "meeting_date"],
        },
    },
    {
        "name": "add_action_item",
        "description": "Add an action item to a meeting",
        "parameters": {
            "type": "object",
            "properties": {
                "meeting_id": {"type": "integer", "description": "ID of the meeting"},
                "description": {
                    "type": "string",
                    "description": "Action item description",
                },
                "owner": {"type": "string", "description": "Person responsible"},
                "due_date": {"type": "string", "description": "Due date in ISO format"},
            },
            "required": ["meeting_id", "description"],
        },
    },
    {
        "name": "search_tasks",
        "description": "Search for tasks by various criteria",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by status"},
                "project_id": {"type": "integer", "description": "Filter by project"},
                "epic_key": {"type": "string", "description": "Filter by epic"},
                "assignee": {"type": "string", "description": "Filter by assignee"},
            },
        },
    },
    {
        "name": "list_reminders",
        "description": "List open reminders, optionally filtered",
        "parameters": {
            "type": "object",
            "properties": {
                "include_done": {
                    "type": "boolean",
                    "description": "Include completed reminders",
                },
                "project_id": {"type": "integer", "description": "Filter by project"},
            },
        },
    },
    {
        "name": "list_goals",
        "description": "List goals, optionally filtered by year or status",
        "parameters": {
            "type": "object",
            "properties": {
                "year": {"type": "integer", "description": "Filter by year"},
                "status": {
                    "type": "string",
                    "enum": ["active", "achieved", "cancelled", "deferred"],
                    "description": "Filter by status",
                },
            },
        },
    },
]


# ── Action Executor ───────────────────────────────────────────────────────────


class ActionExecutor:
    """Executes actions requested by the AI agent"""

    def __init__(self, db: Session):
        self.db = db

    def execute(self, action_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single action and return the result"""
        method = getattr(self, f"_action_{action_name}", None)
        if not method:
            return {"success": False, "error": f"Unknown action: {action_name}"}

        try:
            return method(**params)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _action_create_note(
        self, title: str, content: str = "", tags: str = "", project_id: int = None
    ) -> Dict:
        note = Note(title=title, content=content, tags=tags, project_id=project_id)
        self.db.add(note)
        self.db.commit()
        self.db.refresh(note)
        return {
            "success": True,
            "note_id": note.id,
            "message": f"Created note: {title}",
        }

    def _action_create_reminder(
        self,
        title: str,
        due_at: str,
        description: str = "",
        priority: str = "medium",
        project_id: int = None,
    ) -> Dict:
        due_dt = datetime.fromisoformat(due_at)
        reminder = Reminder(
            title=title,
            description=description,
            due_at=due_dt,
            priority=Priority(priority),
            project_id=project_id,
        )
        self.db.add(reminder)
        self.db.commit()
        self.db.refresh(reminder)
        return {
            "success": True,
            "reminder_id": reminder.id,
            "message": f"Created reminder: {title} (due {due_at})",
        }

    def _action_complete_reminder(self, reminder_id: int) -> Dict:
        reminder = self.db.query(Reminder).filter(Reminder.id == reminder_id).first()
        if not reminder:
            return {"success": False, "error": f"Reminder {reminder_id} not found"}
        reminder.is_done = True
        self.db.commit()
        return {"success": True, "message": f"Completed reminder: {reminder.title}"}

    def _action_create_task(
        self,
        title: str,
        description: str = "",
        status: str = "To Do",
        priority: str = "medium",
        assignee: str = "",
        due_date: str = None,
        project_id: int = None,
        epic_key: str = None,
    ) -> Dict:
        from datetime import date

        task = Task(
            title=title,
            description=description,
            status=status,
            jira_status=status,
            priority=Priority(priority),
            assignee=assignee,
            due_date=date.fromisoformat(due_date) if due_date else None,
            project_id=project_id,
            epic_key=epic_key,
        )
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return {
            "success": True,
            "task_id": task.id,
            "message": f"Created task: {title}",
        }

    def _action_update_task_status(
        self, status: str, task_id: int = None, jira_key: str = None
    ) -> Dict:
        # Find task by ID or Jira key
        task = None
        if task_id:
            task = self.db.query(Task).filter(Task.id == task_id).first()
        elif jira_key:
            task = self.db.query(Task).filter(Task.jira_key == jira_key).first()

        if not task:
            identifier = jira_key or f"ID {task_id}"
            return {"success": False, "error": f"Task {identifier} not found"}

        old_status = task.status
        task.status = status
        task.jira_status = status
        self.db.commit()

        task_identifier = task.jira_key or f"#{task.id}"

        # If this is a Jira task, sync the status change to Jira immediately
        if task.jira_key:
            try:
                import os

                from backend.services.jira_service import JiraService

                jira_server = os.getenv("JIRA_SERVER")
                jira_email = os.getenv("JIRA_EMAIL")
                jira_token = os.getenv("JIRA_API_TOKEN")

                if not all([jira_server, jira_email, jira_token]):
                    task.needs_sync_back = True
                    self.db.commit()
                    return {
                        "success": True,
                        "message": f"Updated {task_identifier} locally to '{status}'. Jira credentials not configured for sync.",
                    }

                jira_service = JiraService(jira_server, jira_email, jira_token)
                result = jira_service.update_issue(task.jira_key, status=status)
                if result.get("success"):
                    return {
                        "success": True,
                        "message": f"Updated {task_identifier} from '{old_status}' to '{status}' (synced to Jira)",
                    }
                else:
                    # Local update succeeded but Jira sync failed
                    task.needs_sync_back = True
                    self.db.commit()
                    return {
                        "success": True,
                        "message": f"Updated {task_identifier} locally to '{status}', but Jira sync failed: {result.get('error', 'Unknown error')}. Will retry later.",
                    }
            except Exception as e:
                task.needs_sync_back = True
                self.db.commit()
                return {
                    "success": True,
                    "message": f"Updated {task_identifier} locally to '{status}', but Jira sync failed: {str(e)}. Will retry later.",
                }

        return {
            "success": True,
            "message": f"Moved task {task_identifier} '{task.title}' from {old_status} to {status}",
        }

    def _action_create_goal(
        self,
        title: str,
        description: str = "",
        year: int = None,
        target_date: str = None,
        status: str = "active",
    ) -> Dict:
        from datetime import date

        goal = Goal(
            title=title,
            description=description,
            year=year or date.today().year,
            target_date=date.fromisoformat(target_date) if target_date else None,
            status=GoalStatus(status),
        )
        self.db.add(goal)
        self.db.commit()
        self.db.refresh(goal)
        return {
            "success": True,
            "goal_id": goal.id,
            "message": f"Created goal: {title}",
        }

    def _action_update_goal_progress(self, goal_id: int, progress_pct: int) -> Dict:
        goal = self.db.query(Goal).filter(Goal.id == goal_id).first()
        if not goal:
            return {"success": False, "error": f"Goal {goal_id} not found"}
        goal.progress_pct = max(0, min(100, progress_pct))
        self.db.commit()
        return {
            "success": True,
            "message": f"Updated goal '{goal.title}' progress to {progress_pct}%",
        }

    def _action_create_project(
        self,
        name: str,
        description: str = "",
        status: str = "active",
        priority: str = "medium",
        start_date: str = None,
        end_date: str = None,
    ) -> Dict:
        from datetime import date

        project = Project(
            name=name,
            description=description,
            status=ProjectStatus(status),
            priority=Priority(priority),
            start_date=date.fromisoformat(start_date) if start_date else None,
            end_date=date.fromisoformat(end_date) if end_date else None,
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        return {
            "success": True,
            "project_id": project.id,
            "message": f"Created project: {name}",
        }

    def _action_link_project_to_goal(self, project_id: int, goal_id: int) -> Dict:
        project = self.db.query(Project).filter(Project.id == project_id).first()
        goal = self.db.query(Goal).filter(Goal.id == goal_id).first()
        if not project:
            return {"success": False, "error": f"Project {project_id} not found"}
        if not goal:
            return {"success": False, "error": f"Goal {goal_id} not found"}
        if goal not in project.goals:
            project.goals.append(goal)
            self.db.commit()
        return {
            "success": True,
            "message": f"Linked project '{project.name}' to goal '{goal.title}'",
        }

    def _action_create_meeting(
        self,
        title: str,
        meeting_date: str,
        attendees: str = "",
        summary: str = "",
        notes: str = "",
        project_id: int = None,
    ) -> Dict:
        meeting = MeetingNote(
            title=title,
            meeting_date=meeting_date,
            attendees=attendees,
            summary=summary,
            notes=notes,
            project_id=project_id,
        )
        self.db.add(meeting)
        self.db.commit()
        self.db.refresh(meeting)
        return {
            "success": True,
            "meeting_id": meeting.id,
            "message": f"Created meeting: {title}",
        }

    def _action_add_action_item(
        self, meeting_id: int, description: str, owner: str = "", due_date: str = ""
    ) -> Dict:
        meeting = self.db.query(MeetingNote).filter(MeetingNote.id == meeting_id).first()
        if not meeting:
            return {"success": False, "error": f"Meeting {meeting_id} not found"}
        item = ActionItem(
            description=description,
            owner=owner,
            due_date=due_date,
            meeting_id=meeting_id,
        )
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return {
            "success": True,
            "action_item_id": item.id,
            "message": f"Added action item to meeting '{meeting.title}'",
        }

    def _action_search_tasks(
        self,
        status: str = None,
        project_id: int = None,
        epic_key: str = None,
        assignee: str = None,
    ) -> Dict:
        query = self.db.query(Task)
        if status:
            query = query.filter(Task.status == status)
        if project_id:
            query = query.filter(Task.project_id == project_id)
        if epic_key:
            query = query.filter(Task.epic_key == epic_key)
        if assignee:
            query = query.filter(Task.assignee.contains(assignee))
        tasks = query.limit(20).all()
        return {
            "success": True,
            "tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "status": t.status,
                    "assignee": t.assignee,
                }
                for t in tasks
            ],
            "count": len(tasks),
        }

    def _action_list_reminders(self, include_done: bool = False, project_id: int = None) -> Dict:
        query = self.db.query(Reminder)
        if not include_done:
            query = query.filter(not Reminder.is_done)
        if project_id:
            query = query.filter(Reminder.project_id == project_id)
        reminders = query.order_by(Reminder.due_at).limit(20).all()
        return {
            "success": True,
            "reminders": [
                {
                    "id": r.id,
                    "title": r.title,
                    "due_at": r.due_at.isoformat() if r.due_at else None,
                    "is_done": r.is_done,
                }
                for r in reminders
            ],
            "count": len(reminders),
        }

    def _action_list_goals(self, year: int = None, status: str = None) -> Dict:
        query = self.db.query(Goal)
        if year:
            query = query.filter(Goal.year == year)
        if status:
            query = query.filter(Goal.status == GoalStatus(status))
        goals = query.order_by(Goal.progress_pct.desc()).all()
        return {
            "success": True,
            "goals": [
                {
                    "id": g.id,
                    "title": g.title,
                    "year": g.year,
                    "status": g.status.value,
                    "progress_pct": g.progress_pct,
                }
                for g in goals
            ],
            "count": len(goals),
        }


# ── Agentic AI Service ────────────────────────────────────────────────────────


class AgentService:
    """
    Agentic AI service that can plan and execute actions.

    Two modes:
    - plan: Returns a plan of actions for user confirmation
    - execute: Directly executes actions and returns results
    """

    def __init__(self, db: Session):
        self.db = db
        self.executor = ActionExecutor(db)

    async def process(
        self,
        user_message: str,
        mode: str = "plan",
        context: str = "",
        conversation_history: List[Dict] = None,
    ) -> Dict:
        """
        Process a user message in the specified mode.

        Args:
            user_message: The user's request
            mode: "plan" or "execute"
            context: Optional context about current state
            conversation_history: Optional list of previous messages for multi-turn conversations

        Returns:
            Dictionary with response and any actions taken/planned
        """
        if not GEMINI_API_KEY:
            return {"success": False, "error": "GEMINI_API_KEY not configured"}

        # Build the system prompt based on mode
        if mode == "plan":
            system_prompt = self._build_plan_prompt(context)
        else:
            system_prompt = self._build_execute_prompt(context)

        # Call Gemini with conversation history
        try:
            response = await self._call_gemini(
                system_prompt, user_message, conversation_history or []
            )

            if "error" in response:
                return response

            # Parse the response
            if mode == "plan":
                return self._process_plan_response(response)
            else:
                return await self._process_execute_response(response, user_message)

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _build_plan_prompt(self, context: str) -> str:
        tools_desc = "\n".join([f"- {t['name']}: {t['description']}" for t in TOOLS])

        return f"""You are an AI assistant that helps users manage their work.
You can perform actions like creating notes, reminders, tasks, goals, projects, and meetings.

Available actions:
{tools_desc}

When the user makes a request, analyze what actions would be needed and respond with a JSON plan.
Format your response as:
{{
    "understanding": "Brief summary of what the user wants",
    "actions": [
        {{"action": "action_name", "params": {{...}}, "reason": "why this action"}}
    ],
    "summary": "What will happen if this plan is executed"
}}

Current context:
{context if context else "No additional context provided."}

Be helpful and suggest appropriate actions. If the request is unclear, ask for clarification.
Only suggest actions that make sense for the request."""

    def _build_execute_prompt(self, context: str) -> str:
        tools_desc = "\n".join(
            [
                f"- {t['name']}: {t['description']}\n  Parameters: {json.dumps(t['parameters']['properties'], indent=2)}"
                for t in TOOLS
            ]
        )

        return f"""You are an AI assistant that helps users manage their work by executing actions.
You can perform actions like creating notes, reminders, tasks, goals, projects, and meetings.

Available actions:
{tools_desc}

When the user makes a request that requires action, determine the actions needed and respond with JSON.
Format your response as:
{{
    "actions": [
        {{"action": "action_name", "params": {{...}}}}
    ],
    "message": "Brief message to the user about what you're doing"
}}

Current context:
{context if context else "No additional context provided."}

Execute appropriate actions based on the user's request. Be precise with parameters.
If you need to read data first (like searching), do that before taking action.

If the user is asking a question or having a conversation (not requesting an action), respond with:
{{"actions": [], "message": "Your helpful conversational response here"}}

If the request is unclear or you cannot fulfill it, respond with:
{{"actions": [], "message": "Explanation of why you cannot proceed"}}"""

    async def _call_gemini(
        self,
        system_prompt: str,
        user_message: str,
        conversation_history: List[Dict] = None,
    ) -> Dict:
        """Call Gemini API with conversation history support"""
        # Build contents with conversation history
        contents = []

        # Add conversation history if provided
        if conversation_history:
            contents.extend(conversation_history)

        # Add current user message
        contents.append({"role": "user", "parts": [{"text": user_message}]})

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{GEMINI_API_URL}/{GEMINI_MODEL}:generateContent",
                params={"key": GEMINI_API_KEY},
                json={
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "contents": contents,
                    "generationConfig": {
                        "temperature": 0.2,  # Lower temperature for more precise actions
                        "maxOutputTokens": 2048,
                    },
                },
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()

            if "candidates" in data and len(data["candidates"]) > 0:
                text = data["candidates"][0]["content"]["parts"][0].get("text", "")
                return {"success": True, "text": text}

            return {"success": False, "error": "Empty response from AI"}

    def _process_plan_response(self, response: Dict) -> Dict:
        """Process the AI response in plan mode"""
        text = response.get("text", "")

        # Try to extract JSON from the response
        try:
            # Find JSON in the response
            json_start = text.find("{")
            json_end = text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                json_str = text[json_start:json_end]
                plan = json.loads(json_str)
                return {
                    "success": True,
                    "mode": "plan",
                    "plan": plan,
                    "raw_response": text,
                }
        except json.JSONDecodeError:
            pass

        # If no valid JSON, return the text as a message
        return {
            "success": True,
            "mode": "plan",
            "message": text,
            "plan": None,
        }

    async def _process_execute_response(self, response: Dict, original_request: str) -> Dict:
        """Process the AI response in execute mode and run actions"""
        text = response.get("text", "")

        # Try to extract JSON from the response
        try:
            json_start = text.find("{")
            json_end = text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                json_str = text[json_start:json_end]
                plan = json.loads(json_str)

                actions = plan.get("actions", [])
                message = plan.get("message", "")

                if not actions:
                    return {
                        "success": True,
                        "mode": "execute",
                        "message": message or text,
                        "actions_executed": [],
                    }

                # Execute all actions
                results = []
                for action in actions:
                    action_name = action.get("action")
                    params = action.get("params", {})
                    result = self.executor.execute(action_name, params)
                    results.append(
                        {
                            "action": action_name,
                            "params": params,
                            "result": result,
                        }
                    )

                # Summarize results
                successful = sum(1 for r in results if r["result"].get("success"))
                failed = len(results) - successful

                return {
                    "success": True,
                    "mode": "execute",
                    "message": message,
                    "actions_executed": results,
                    "summary": f"Executed {len(results)} action(s): {successful} successful, {failed} failed",
                }

        except json.JSONDecodeError:
            pass

        # If no valid JSON, return the text as a message
        return {
            "success": True,
            "mode": "execute",
            "message": text,
            "actions_executed": [],
        }

    async def execute_plan(self, plan: Dict) -> Dict:
        """Execute a previously generated plan"""
        actions = plan.get("actions", [])

        if not actions:
            return {"success": False, "error": "No actions in plan"}

        results = []
        for action in actions:
            action_name = action.get("action")
            params = action.get("params", {})
            result = self.executor.execute(action_name, params)
            results.append(
                {
                    "action": action_name,
                    "params": params,
                    "result": result,
                }
            )

        successful = sum(1 for r in results if r["result"].get("success"))
        failed = len(results) - successful

        return {
            "success": True,
            "actions_executed": results,
            "summary": f"Executed {len(results)} action(s): {successful} successful, {failed} failed",
        }
