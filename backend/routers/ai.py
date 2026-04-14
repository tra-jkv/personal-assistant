import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.models import (
    ConversationMessage,
    ConversationSession,
    DailyActivity,
    DailySummary,
    Epic,
    ExternalLink,
    Goal,
    MeetingNote,
    Note,
    Project,
    Reminder,
    Task,
)

router = APIRouter(prefix="/ai", tags=["ai"])
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))

# Gemini API configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"


# ── Pydantic models for JSON API ──────────────────────────────────────────────


class AIQuestion(BaseModel):
    question: str
    session_id: Optional[int] = None
    include_context: bool = True


class AgentRequest(BaseModel):
    """Request for the agentic AI assistant"""

    message: str
    session_id: Optional[int] = None
    mode: str = "plan"  # "ask", "plan" or "execute"
    include_context: bool = True


class AgentPlanExecute(BaseModel):
    """Execute a previously generated plan"""

    plan: Dict[str, Any]
    session_id: Optional[int] = None


class SessionCreate(BaseModel):
    """Create a new conversation session"""

    title: Optional[str] = None
    mode: str = "ask"


# ── Session Management API ────────────────────────────────────────────────────


@router.post("/api/sessions", response_class=JSONResponse)
def create_session(
    session_data: SessionCreate,
    db: Session = Depends(get_db),
):
    """Create a new conversation session."""
    session = ConversationSession(
        title=session_data.title or "New Conversation",
        mode=session_data.mode,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return {
        "id": session.id,
        "title": session.title,
        "mode": session.mode,
        "created_at": session.created_at.isoformat(),
    }


@router.get("/api/sessions", response_class=JSONResponse)
def list_sessions(
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """List recent conversation sessions."""
    sessions = (
        db.query(ConversationSession)
        .filter(ConversationSession.is_active)
        .order_by(ConversationSession.updated_at.desc())
        .limit(limit)
        .all()
    )

    return {
        "sessions": [
            {
                "id": s.id,
                "title": s.title,
                "mode": s.mode,
                "message_count": len(s.messages),
                "created_at": s.created_at.isoformat(),
                "updated_at": s.updated_at.isoformat(),
            }
            for s in sessions
        ]
    }


@router.get("/api/sessions/{session_id}", response_class=JSONResponse)
def get_session(
    session_id: int,
    db: Session = Depends(get_db),
):
    """Get a conversation session with all messages."""
    session = (
        db.query(ConversationSession)
        .options(joinedload(ConversationSession.messages))
        .filter(ConversationSession.id == session_id)
        .first()
    )

    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    return {
        "id": session.id,
        "title": session.title,
        "mode": session.mode,
        "is_active": session.is_active,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "action_type": m.action_type,
                "action_data": json.loads(m.action_data) if m.action_data else None,
                "created_at": m.created_at.isoformat(),
            }
            for m in session.messages
        ],
    }


@router.delete("/api/sessions/{session_id}", response_class=JSONResponse)
def delete_session(
    session_id: int,
    db: Session = Depends(get_db),
):
    """Delete (archive) a conversation session."""
    session = db.query(ConversationSession).filter(ConversationSession.id == session_id).first()
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    session.is_active = False
    db.commit()

    return {"success": True, "message": "Session archived"}


@router.put("/api/sessions/{session_id}/title", response_class=JSONResponse)
def update_session_title(
    session_id: int,
    title: str,
    db: Session = Depends(get_db),
):
    """Update a session's title."""
    session = db.query(ConversationSession).filter(ConversationSession.id == session_id).first()
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    session.title = title
    db.commit()

    return {"success": True, "title": title}


# ── Helper functions ──────────────────────────────────────────────────────────


def _get_or_create_session(
    db: Session, session_id: Optional[int], mode: str = "ask"
) -> ConversationSession:
    """Get an existing session or create a new one."""
    if session_id:
        session = db.query(ConversationSession).filter(ConversationSession.id == session_id).first()
        if session:
            return session

    # Create new session
    session = ConversationSession(title="New Conversation", mode=mode)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _add_message(
    db: Session,
    session: ConversationSession,
    role: str,
    content: str,
    action_type: Optional[str] = None,
    action_data: Optional[Dict] = None,
) -> ConversationMessage:
    """Add a message to a session."""
    message = ConversationMessage(
        session_id=session.id,
        role=role,
        content=content,
        action_type=action_type,
        action_data=json.dumps(action_data) if action_data else None,
    )
    db.add(message)
    session.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(message)
    return message


def _build_conversation_history(session: ConversationSession, max_messages: int = 20) -> List[Dict]:
    """Build conversation history for Gemini API from session messages."""
    history = []
    messages = session.messages[-max_messages:]  # Last N messages

    for msg in messages:
        if msg.role == "user":
            history.append({"role": "user", "parts": [{"text": msg.content}]})
        elif msg.role == "assistant":
            history.append({"role": "model", "parts": [{"text": msg.content}]})
        # Skip system messages in history as they're part of system prompt

    return history


def _auto_title_session(db: Session, session: ConversationSession, first_message: str):
    """Auto-generate a title from the first message if title is default."""
    if session.title == "New Conversation" and first_message:
        # Take first 50 chars of the message as title
        title = first_message[:50].strip()
        if len(first_message) > 50:
            title += "..."
        session.title = title
        db.commit()


# ── Agentic API endpoints (with session support) ──────────────────────────────


@router.post("/api/agent", response_class=JSONResponse)
async def agent_request(
    request_data: AgentRequest,
    db: Session = Depends(get_db),
):
    """
    Agentic AI assistant that can plan and execute actions.
    Supports multi-turn conversations with session tracking.

    **Modes:**
    - `ask`: Read-only Q&A mode
    - `plan`: AI analyzes your request and returns a plan of actions for confirmation
    - `execute`: AI directly performs actions and returns results

    **Session support:**
    - Include `session_id` to continue an existing conversation
    - Omit `session_id` to start a new conversation (returns new session_id)
    """
    from backend.services.agent_service import AgentService

    if not GEMINI_API_KEY:
        return JSONResponse(
            {"success": False, "error": "GEMINI_API_KEY not configured"},
            status_code=500,
        )

    # Get or create session
    session = _get_or_create_session(db, request_data.session_id, request_data.mode)

    # Auto-title if this is the first message
    if len(session.messages) == 0:
        _auto_title_session(db, session, request_data.message)

    # Add user message to session
    _add_message(db, session, "user", request_data.message)

    # Build context if requested
    context = ""
    if request_data.include_context:
        context = build_context(db)

    # Build conversation history
    conversation_history = _build_conversation_history(session)

    # Handle different modes
    if request_data.mode == "ask":
        # Simple Q&A mode - use conversation history
        result = await _handle_ask_mode(
            db, session, request_data.message, context, conversation_history
        )
    else:
        # Agent mode (plan/execute)
        agent = AgentService(db)
        result = await agent.process(
            user_message=request_data.message,
            mode=request_data.mode,
            context=context,
            conversation_history=conversation_history,
        )

        # Store assistant response
        if result.get("success"):
            response_content = result.get("message", "") or result.get("response", "")
            action_type = request_data.mode
            action_data = None

            if request_data.mode == "plan" and result.get("plan"):
                action_data = result.get("plan")
                response_content = response_content or "Here's my plan for your request."
            elif request_data.mode == "execute" and result.get("actions_executed"):
                action_data = {
                    "actions_executed": result.get("actions_executed"),
                    "summary": result.get("summary"),
                }
                response_content = result.get("summary", "Actions executed.")

            _add_message(db, session, "assistant", response_content, action_type, action_data)

    # Add session_id to result
    result["session_id"] = session.id
    result["session_title"] = session.title

    return result


async def _handle_ask_mode(
    db: Session,
    session: ConversationSession,
    question: str,
    context: str,
    conversation_history: List[Dict],
) -> Dict:
    """Handle ask (read-only Q&A) mode with conversation history."""
    system_prompt = (
        "You are a personal assistant for an engineer. "
        "You help track goals, projects, Jira epics/stories, notes, reminders, and meetings.\n\n"
        "CRITICAL RULES:\n"
        "1. Stories are the main work items. Subtasks belong INSIDE stories.\n"
        "2. By default, list STORIES with subtask counts. If the user asks to dive deeper or "
        "list subtasks, show them grouped under their parent story.\n"
        "3. Format for stories: **DL-xxxx**: Story title - Status (X/Y subtasks remaining)\n"
        "4. Format for subtasks (when requested): indent under parent story with - DL-xxxx: title - status\n\n"
        "Be concise. Use markdown. This is a multi-turn conversation."
    )

    if context:
        system_prompt += f"\n\nCONTEXT:\n{context}"

    try:
        # Build contents with conversation history
        contents = conversation_history.copy()

        # Add current question if not already in history
        if not contents or contents[-1].get("parts", [{}])[0].get("text") != question:
            contents.append({"role": "user", "parts": [{"text": question}]})

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{GEMINI_API_URL}/{GEMINI_MODEL}:generateContent",
                params={"key": GEMINI_API_KEY},
                json={
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "contents": contents,
                    "generationConfig": {
                        "temperature": 0.7,
                        "maxOutputTokens": 2048,
                    },
                },
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()

            answer = ""
            if "candidates" in data and len(data["candidates"]) > 0:
                candidate = data["candidates"][0]
                if "content" in candidate and "parts" in candidate["content"]:
                    answer = candidate["content"]["parts"][0].get("text", "")

            if not answer:
                return {"success": False, "error": "Empty response from AI"}

            # Store assistant response
            _add_message(db, session, "assistant", answer)

            return {
                "success": True,
                "mode": "ask",
                "response": answer,
            }

    except httpx.HTTPStatusError as e:
        return {"success": False, "error": f"AI API error: {e.response.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/agent/execute-plan", response_class=JSONResponse)
async def execute_plan(
    plan_data: AgentPlanExecute,
    db: Session = Depends(get_db),
):
    """
    Execute a previously generated plan.
    """
    from backend.services.agent_service import AgentService

    agent = AgentService(db)
    result = await agent.execute_plan(plan_data.plan)

    # Update session if provided
    if plan_data.session_id:
        session = (
            db.query(ConversationSession)
            .filter(ConversationSession.id == plan_data.session_id)
            .first()
        )
        if session and result.get("success"):
            _add_message(
                db,
                session,
                "assistant",
                result.get("summary", "Plan executed."),
                "execute",
                {"actions_executed": result.get("actions_executed")},
            )
            result["session_id"] = session.id

    return result


@router.get("/api/agent/tools", response_class=JSONResponse)
def list_agent_tools():
    """
    List all available tools/actions the agent can perform.
    """
    from backend.services.agent_service import TOOLS

    return {
        "tools": TOOLS,
        "count": len(TOOLS),
    }


# ── Standard JSON API endpoints ───────────────────────────────────────────────


@router.post("/api/ask", response_class=JSONResponse)
async def ask_ai_api(
    question_data: AIQuestion,
    db: Session = Depends(get_db),
):
    """
    Ask the AI assistant a question via JSON API.
    Supports session-based conversations.
    """
    if not GEMINI_API_KEY:
        return JSONResponse(
            {"success": False, "error": "GEMINI_API_KEY not configured"},
            status_code=500,
        )

    # Get or create session
    session = _get_or_create_session(db, question_data.session_id, "ask")

    # Auto-title if first message
    if len(session.messages) == 0:
        _auto_title_session(db, session, question_data.question)

    # Add user message
    _add_message(db, session, "user", question_data.question)

    # Build context and history
    context = build_context(db) if question_data.include_context else ""
    conversation_history = _build_conversation_history(session)

    result = await _handle_ask_mode(
        db, session, question_data.question, context, conversation_history
    )

    result["session_id"] = session.id
    result["session_title"] = session.title

    return result


@router.get("/api/status", response_class=JSONResponse)
def ai_status_api():
    """Check if the AI service is configured and available."""
    return {
        "configured": bool(GEMINI_API_KEY),
        "model": GEMINI_MODEL,
        "provider": "gemini",
    }


# ── Context builder ───────────────────────────────────────────────────────────


def build_context(db: Session) -> str:
    lines = []

    # Goals
    goals = db.query(Goal).all()
    lines.append("=== GOALS ===")
    for g in goals:
        projects_list = ", ".join([p.name for p in g.projects]) if g.projects else "none"
        lines.append(
            f"- [{g.status.value}] {g.title} (year: {g.year}, progress: {g.progress_pct}%): {g.description}"
            f"\n  Linked projects: {projects_list}"
        )

    # Projects
    projects = db.query(Project).all()
    lines.append("\n=== PROJECTS ===")
    for p in projects:
        lines.append(
            f"- [{p.status.value}] {p.name} (priority: {p.priority.value}): {p.description}"
        )

    # Epics
    epics = db.query(Epic).limit(20).all()
    lines.append("\n=== JIRA EPICS ===")
    for e in epics:
        lines.append(f"- [{e.status}] {e.key}: {e.title}")

    # Tasks - first identify current sprint
    all_tasks = (
        db.query(Task)
        .filter(Task.status.notin_(["Done", "done", "Cancelled", "cancelled"]))
        .order_by(Task.epic_key, Task.position)
        .limit(100)
        .all()
    )

    # Find current/active sprint by looking for sprints containing "active" indicators
    # or the most recent sprint pattern (highest number in sprint name)
    sprint_counts = {}
    for t in all_tasks:
        if t.sprint_name:
            sprint_counts[t.sprint_name] = sprint_counts.get(t.sprint_name, 0) + 1

    # Determine current sprint - look for highest DF number or most common active sprint
    current_sprint = None
    if sprint_counts:
        # Sort sprints and pick the most recent one (highest DF number)
        import re

        def sprint_sort_key(name):
            # Extract number from sprint name like "PI#1 -> DF 6"
            match = re.search(r"DF\s*(\d+)", name)
            return int(match.group(1)) if match else 0

        sorted_sprints = sorted(sprint_counts.keys(), key=sprint_sort_key, reverse=True)
        if sorted_sprints:
            current_sprint = sorted_sprints[0]

    # Current sprint section
    if current_sprint:
        lines.append(f"\n=== CURRENT SPRINT: {current_sprint} ===")
        current_sprint_tasks = [t for t in all_tasks if t.sprint_name == current_sprint]
        for t in current_sprint_tasks:
            jira = f"[{t.jira_key}]" if t.jira_key else ""
            assignee = f"@{t.assignee}" if t.assignee else ""
            epic = f"(epic: {t.epic_key})" if t.epic_key else ""

            # Calculate subtask progress inline
            subtask_info = ""
            subtasks = []
            if t.subtasks_json:
                try:
                    subtasks = json.loads(t.subtasks_json)
                    if subtasks:
                        done_count = sum(1 for st in subtasks if st.get("status") == "Done")
                        remaining = len(subtasks) - done_count
                        subtask_info = f" ({remaining}/{len(subtasks)} subtasks remaining)"
                except Exception:
                    pass

            lines.append(f"STORY {jira} {t.title} - {t.status}{subtask_info} {assignee} {epic}")

            # Show subtasks nested under story (only non-done ones for brevity)
            for st in subtasks:
                if st.get("status") != "Done":
                    st_assignee = f"@{st['assignee']}" if st.get("assignee") else ""
                    lines.append(f"  └─ [{st['key']}] {st['title']} - {st['status']} {st_assignee}")

        if not current_sprint_tasks:
            lines.append("- No tasks in current sprint")

    # All open stories (excluding current sprint to avoid duplication)
    other_stories = [t for t in all_tasks if t.sprint_name != current_sprint]
    if other_stories:
        lines.append("\n=== OTHER OPEN STORIES (not in current sprint) ===")
        for t in other_stories[:30]:
            jira = f"[{t.jira_key}]" if t.jira_key else ""
            assignee = f"@{t.assignee}" if t.assignee else ""
            epic = f"epic:{t.epic_key}" if t.epic_key else ""
            sprint = f"sprint:{t.sprint_name}" if t.sprint_name else "backlog"

            # Count subtasks
            subtask_info = ""
            if t.subtasks_json:
                try:
                    subtasks = json.loads(t.subtasks_json)
                    if subtasks:
                        done_count = sum(1 for st in subtasks if st.get("status") == "Done")
                        remaining = len(subtasks) - done_count
                        subtask_info = f" ({remaining}/{len(subtasks)} subtasks remaining)"
                except Exception:
                    pass

            lines.append(
                f"STORY {jira} {t.title} - {t.status} {assignee} {epic} {sprint}{subtask_info}"
            )

    # Notes
    notes = db.query(Note).order_by(Note.updated_at.desc()).limit(20).all()
    lines.append("\n=== RECENT NOTES ===")
    for n in notes:
        proj = f" [project: {n.project.name}]" if n.project else ""
        lines.append(f"### {n.title}{proj}\n{n.content[:500]}\ntags: {n.tags}")

    # Meetings
    meetings = db.query(MeetingNote).order_by(MeetingNote.meeting_date.desc()).limit(10).all()
    lines.append("\n=== RECENT MEETINGS ===")
    for m in meetings:
        items = "\n".join(
            f"  - [{'x' if i.is_done else ' '}] {i.description} (owner: {i.owner}, due: {i.due_date})"
            for i in m.action_items
        )
        lines.append(
            f"Meeting: {m.title} ({m.meeting_date})\nSummary: {m.summary}\nAction items:\n{items}"
        )

    # Daily Activities (last 14 days)
    two_weeks_ago = datetime.utcnow() - timedelta(days=14)
    activities = (
        db.query(DailyActivity)
        .filter(DailyActivity.activity_date >= two_weeks_ago)
        .order_by(DailyActivity.activity_date.desc())
        .limit(100)
        .all()
    )
    lines.append("\n=== RECENT WORK ACTIVITY (Last 14 days) ===")

    # Group by date
    activities_by_date = {}
    for a in activities:
        date_str = a.activity_date.strftime("%Y-%m-%d")
        if date_str not in activities_by_date:
            activities_by_date[date_str] = []
        activities_by_date[date_str].append(a)

    for date_str in sorted(activities_by_date.keys(), reverse=True):
        day_activities = activities_by_date[date_str]
        lines.append(f"\n{date_str}:")
        for a in day_activities:
            repo = f" ({a.repository})" if a.repository else ""
            lines.append(f"  - [{a.source}/{a.activity_type}]{repo} {a.title[:100]}")

    # Daily Summaries (last 14 days)
    summaries = (
        db.query(DailySummary)
        .filter(DailySummary.summary_date >= two_weeks_ago)
        .order_by(DailySummary.summary_date.desc())
        .all()
    )
    if summaries:
        lines.append("\n=== DAILY SUMMARY STATS (Last 14 days) ===")
        for s in summaries:
            date_str = s.summary_date.strftime("%Y-%m-%d")
            lines.append(
                f"{date_str}: {s.github_commits} commits, {s.github_prs} PRs, "
                f"{s.github_reviews} reviews, {s.jira_assigned} Jira issues"
            )

    # Reminders
    reminders = db.query(Reminder).filter(not Reminder.is_done).order_by(Reminder.due_at).all()
    lines.append("\n=== OPEN REMINDERS ===")
    for r in reminders:
        lines.append(
            f"- [{r.priority.value}] {r.title} due {r.due_at.strftime('%Y-%m-%d %H:%M')}: {r.description}"
        )

    # External Links
    ext_links = db.query(ExternalLink).order_by(ExternalLink.created_at.desc()).limit(30).all()
    lines.append("\n=== EXTERNAL LINKS ===")
    for lnk in ext_links:
        context_parts = []
        if lnk.project:
            context_parts.append(f"project: {lnk.project.name}")
        if lnk.note:
            context_parts.append(f"note: {lnk.note.title}")
        if lnk.meeting:
            context_parts.append(f"meeting: {lnk.meeting.title}")
        ctx = f" ({', '.join(context_parts)})" if context_parts else ""
        lines.append(
            f"- [{lnk.link_type.value}] {lnk.title}{ctx}: {lnk.url}"
            + (f" — {lnk.description}" if lnk.description else "")
        )

    return "\n".join(lines)


@router.get("/", response_class=HTMLResponse)
def ai_page(request: Request):
    has_api_key = bool(GEMINI_API_KEY)
    return templates.TemplateResponse(
        request, "ai/index.html", {"messages": [], "has_api_key": has_api_key}
    )
