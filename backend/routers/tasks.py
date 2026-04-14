import json
import os
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.models import Epic, Project, Task
from backend.models.models import Priority

router = APIRouter(prefix="/tasks", tags=["tasks"])
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))


# Add custom filter for parsing JSON in templates
def fromjson_filter(value):
    """Parse JSON string in Jinja2 template"""
    if not value or value == "":
        return []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


templates.env.filters["fromjson"] = fromjson_filter

# Map Jira statuses to Kanban columns
# Based on actual Jira workflow: To Refine -> Ready for estimate -> Ready To Develop -> In Development -> In Review -> In Test -> Done
JIRA_STATUS_MAP = {
    # Backlog/Refinement column - items needing refinement or estimation
    "To Refine": "backlog",
    "Ready for refinement": "backlog",
    "In Refinement": "backlog",
    "Ready for estimate": "backlog",
    "Backlog": "backlog",
    # To Do column - ready to be worked on
    "Ready To Develop": "todo",
    "To Do": "todo",
    "Open": "todo",
    "New": "todo",
    # In Progress column - actively being worked on
    "In Development": "in_progress",
    "In Progress": "in_progress",
    "Development": "in_progress",
    # Blocked/Waiting column
    "Waiting": "blocked",
    "Blocked": "blocked",
    "On Hold": "blocked",
    "parked": "blocked",
    # In Review/Test column
    "In Review": "in_review",
    "In Test": "in_review",
    "Code Review": "in_review",
    "Testing": "in_review",
    "QA": "in_review",
    # Done column
    "Done": "done",
    "Closed": "done",
    "Resolved": "done",
    # Cancelled column
    "Cancelled": "cancelled",
    "Won't Do": "cancelled",
    "Rejected": "cancelled",
    "nothing to do (2)": "cancelled",
}

# Reverse map for sync-back to Jira (use most common Jira status for each column)
KANBAN_TO_JIRA_MAP = {
    "backlog": "To Refine",
    "todo": "Ready To Develop",
    "in_progress": "In Development",
    "blocked": "Waiting",
    "in_review": "In Review",
    "done": "Done",
    "cancelled": "Cancelled",
}

# Ordered list of columns shown on the board
BOARD_COLUMNS = [
    "backlog",
    "todo",
    "in_progress",
    "blocked",
    "in_review",
    "done",
    "cancelled",
]

COLUMN_LABELS = {
    "backlog": "Backlog",
    "todo": "To Do",
    "in_progress": "In Progress",
    "blocked": "Blocked",
    "in_review": "In Review",
    "done": "Done",
    "cancelled": "Cancelled",
}


# ── Pydantic models for JSON API ──────────────────────────────────────────────


class TaskCreate(BaseModel):
    title: str
    description: str = ""
    status: str = "To Do"  # Jira status or kanban column
    priority: str = "medium"  # low, medium, high, critical
    assignee: str = ""
    due_date: Optional[str] = None  # ISO format
    jira_key: Optional[str] = None  # e.g., "DL-123"
    epic_key: Optional[str] = None  # Link to epic
    project_id: Optional[int] = None  # Link to project


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assignee: Optional[str] = None
    due_date: Optional[str] = None
    epic_key: Optional[str] = None
    project_id: Optional[int] = None


class TaskMove(BaseModel):
    status: str  # Target status/column


class TaskLinkJira(BaseModel):
    jira_key: str


def _task_to_dict(task: Task) -> dict:
    """Convert Task model to dictionary for JSON response"""
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "kanban_column": normalize_status(task.status),
        "priority": task.priority.value if task.priority else "medium",
        "assignee": task.assignee,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "jira_key": task.jira_key,
        "jira_url": task.jira_url,
        "jira_status": task.jira_status,
        "epic_key": task.epic_key,
        "project_id": task.project_id,
        "project_name": task.project.name if task.project else None,
        "epic_title": task.epic.title if task.epic else None,
        "is_synced": task.is_synced,
        "needs_sync_back": task.needs_sync_back,
        "position": task.position,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


# ── JSON API endpoints ────────────────────────────────────────────────────────


@router.get("/api", response_class=JSONResponse)
def list_tasks_api(
    project_id: Optional[int] = None,
    epic_key: Optional[str] = None,
    status: Optional[str] = None,
    include_done: bool = True,
    db: Session = Depends(get_db),
):
    """
    List all tasks with optional filters.

    Query params:
    - project_id: Filter by project
    - epic_key: Filter by epic
    - status: Filter by status/column (e.g., "in_progress", "done")
    - include_done: Include done tasks (default true)
    """
    query = db.query(Task).options(joinedload(Task.epic), joinedload(Task.project))

    if project_id:
        query = query.filter(Task.project_id == project_id)
    if epic_key:
        query = query.filter(Task.epic_key == epic_key)
    if status:
        # Try to match both raw status and normalized column
        query = query.filter(
            (Task.status == status)
            | (Task.status.in_([k for k, v in JIRA_STATUS_MAP.items() if v == status]))
        )
    if not include_done:
        done_statuses = [k for k, v in JIRA_STATUS_MAP.items() if v == "done"]
        query = query.filter(~Task.status.in_(done_statuses))

    tasks = query.order_by(Task.jira_updated_at.desc().nullslast(), Task.created_at.desc()).all()

    return {"tasks": [_task_to_dict(t) for t in tasks]}


@router.get("/api/{task_id}", response_class=JSONResponse)
def get_task_api(
    task_id: int,
    db: Session = Depends(get_db),
):
    """Get a single task by ID."""
    task = (
        db.query(Task)
        .options(joinedload(Task.epic), joinedload(Task.project))
        .filter(Task.id == task_id)
        .first()
    )
    if not task:
        return JSONResponse({"success": False, "error": "Task not found"}, status_code=404)

    return {"success": True, "task": _task_to_dict(task)}


@router.post("/api", response_class=JSONResponse)
def create_task_api(
    task_data: TaskCreate,
    db: Session = Depends(get_db),
):
    """
    Create a new task.

    Request body:
    {
        "title": "Task title",
        "description": "Description",
        "status": "To Do",
        "priority": "high",
        "assignee": "John Doe",
        "due_date": "2026-04-30",
        "jira_key": "DL-123" (optional - links to Jira),
        "epic_key": "DL-100" (optional - links to epic),
        "project_id": 1 (optional)
    }
    """
    max_pos = db.query(Task).filter(Task.status == task_data.status).count()

    task = Task(
        title=task_data.title,
        description=task_data.description,
        status=task_data.status,
        jira_status=task_data.status,
        priority=Priority(task_data.priority) if task_data.priority else Priority.medium,
        assignee=task_data.assignee,
        due_date=date.fromisoformat(task_data.due_date) if task_data.due_date else None,
        jira_key=task_data.jira_key if task_data.jira_key else None,
        epic_key=task_data.epic_key if task_data.epic_key else None,
        project_id=task_data.project_id if task_data.project_id else None,
        is_synced=False,
        needs_sync_back=bool(task_data.jira_key),
        position=max_pos,
    )

    if task_data.jira_key:
        task.jira_url = f"{os.getenv('JIRA_SERVER', '').rstrip('/')}/browse/{task_data.jira_key}"

    db.add(task)
    db.commit()
    db.refresh(task)

    return {"success": True, "task": _task_to_dict(task)}


@router.put("/api/{task_id}", response_class=JSONResponse)
def update_task_api(
    task_id: int,
    task_data: TaskUpdate,
    db: Session = Depends(get_db),
):
    """Update an existing task. Only provided fields will be updated."""
    task = (
        db.query(Task)
        .options(joinedload(Task.epic), joinedload(Task.project))
        .filter(Task.id == task_id)
        .first()
    )
    if not task:
        return JSONResponse({"success": False, "error": "Task not found"}, status_code=404)

    if task_data.title is not None:
        task.title = task_data.title
    if task_data.description is not None:
        task.description = task_data.description
    if task_data.status is not None:
        task.status = task_data.status
        task.jira_status = task_data.status
        if task.jira_key:
            task.needs_sync_back = True
    if task_data.priority is not None:
        task.priority = Priority(task_data.priority)
    if task_data.assignee is not None:
        task.assignee = task_data.assignee
    if task_data.due_date is not None:
        task.due_date = date.fromisoformat(task_data.due_date) if task_data.due_date else None
    if task_data.epic_key is not None:
        task.epic_key = task_data.epic_key if task_data.epic_key else None
    if task_data.project_id is not None:
        task.project_id = task_data.project_id if task_data.project_id else None

    db.commit()
    db.refresh(task)

    return {"success": True, "task": _task_to_dict(task)}


@router.delete("/api/{task_id}", response_class=JSONResponse)
def delete_task_api(
    task_id: int,
    db: Session = Depends(get_db),
):
    """Delete a task by ID."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return JSONResponse({"success": False, "error": "Task not found"}, status_code=404)

    db.delete(task)
    db.commit()

    return {"success": True, "message": f"Task {task_id} deleted"}


@router.post("/api/{task_id}/move", response_class=JSONResponse)
def move_task_api(
    task_id: int,
    move_data: TaskMove,
    db: Session = Depends(get_db),
):
    """
    Move a task to a different status/column.

    Request body:
    {
        "status": "in_progress"
    }
    """
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return JSONResponse({"success": False, "error": "Task not found"}, status_code=404)

    # Convert kanban column to Jira status if needed
    new_status = move_data.status
    if new_status in KANBAN_TO_JIRA_MAP:
        new_status = KANBAN_TO_JIRA_MAP[new_status]

    task.status = new_status
    task.jira_status = new_status
    if task.jira_key:
        task.needs_sync_back = True

    db.commit()

    return {
        "success": True,
        "task_id": task_id,
        "new_status": task.status,
        "kanban_column": normalize_status(task.status),
        "needs_sync_back": task.needs_sync_back,
    }


@router.post("/api/{task_id}/link-jira", response_class=JSONResponse)
def link_jira_to_task_api(
    task_id: int,
    link_data: TaskLinkJira,
    db: Session = Depends(get_db),
):
    """Link a Jira issue to an existing task."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return JSONResponse({"success": False, "error": "Task not found"}, status_code=404)

    task.jira_key = link_data.jira_key
    task.jira_url = f"{os.getenv('JIRA_SERVER', '').rstrip('/')}/browse/{link_data.jira_key}"
    task.needs_sync_back = True

    db.commit()

    return {"success": True, "task": _task_to_dict(task)}


# ── Helper functions ──────────────────────────────────────────────────────────


def normalize_status(jira_status: str) -> str:
    """Convert Jira status to our kanban column key."""
    return JIRA_STATUS_MAP.get(jira_status, "todo")


def _board_context(db: Session, project_id: Optional[int] = None, epic_key: Optional[str] = None):
    """Build grouped task data for kanban rendering."""
    projects = db.query(Project).order_by(Project.name).all()
    epics = db.query(Epic).order_by(Epic.key.desc()).all()

    query = db.query(Task).options(joinedload(Task.epic), joinedload(Task.project))

    if project_id:
        query = query.filter(Task.project_id == project_id)
    if epic_key:
        query = query.filter(Task.epic_key == epic_key)

    # Sort by most recently updated in Jira first; fall back to created_at for local tasks
    tasks = query.order_by(Task.jira_updated_at.desc().nullslast(), Task.created_at.desc()).all()

    # Group tasks by normalized status
    columns = {col: [] for col in BOARD_COLUMNS}
    for t in tasks:
        col_key = normalize_status(t.status)
        columns[col_key].append(t)

    # Stats
    total_tasks = len(tasks)
    done_tasks = len(columns["done"])
    in_progress_tasks = len(columns["in_progress"])

    return {
        "projects": projects,
        "epics": epics,
        "columns": columns,
        "column_labels": COLUMN_LABELS,
        "board_columns": BOARD_COLUMNS,
        "kanban_to_jira": KANBAN_TO_JIRA_MAP,
        "priorities": list(Priority),
        "active_project_id": project_id,
        "active_epic_key": epic_key,
        "total_tasks": total_tasks,
        "done_tasks": done_tasks,
        "in_progress_tasks": in_progress_tasks,
    }


@router.get("/", response_class=HTMLResponse)
def kanban_board(
    request: Request,
    project_id: Optional[int] = None,
    epic_key: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Tasks Kanban board - shows Jira stories and manual tasks."""
    ctx = _board_context(db, project_id, epic_key)
    is_htmx = request.headers.get("HX-Request") == "true"
    template = "tasks/board_content.html" if is_htmx else "tasks/board.html"
    return templates.TemplateResponse(request, template, ctx)


@router.get("/{task_id}", response_class=HTMLResponse)
def task_detail(
    task_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Task detail page with subtasks view."""
    task = (
        db.query(Task)
        .options(joinedload(Task.epic), joinedload(Task.project))
        .filter(Task.id == task_id)
        .first()
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Parse subtasks
    subtasks = []
    if task.subtasks_json:
        try:
            subtasks = json.loads(task.subtasks_json)
        except json.JSONDecodeError:
            pass

    # Group subtasks by status
    subtasks_by_status = {
        "todo": [],
        "in_progress": [],
        "done": [],
        "cancelled": [],
    }
    for st in subtasks:
        status = st.get("status", "").lower()
        if status in ["done", "closed", "resolved"]:
            subtasks_by_status["done"].append(st)
        elif status in [
            "cancelled",
            "won't do",
            "rejected",
            "nothing to do",
            "nothing to do (2)",
        ]:
            subtasks_by_status["cancelled"].append(st)
        elif status in ["in progress", "in development", "in review", "in test"]:
            subtasks_by_status["in_progress"].append(st)
        else:
            subtasks_by_status["todo"].append(st)

    # Count stats - exclude cancelled from total for progress calculation
    active_subtasks = [
        s
        for s in subtasks
        if s.get("status", "").lower()
        not in [
            "cancelled",
            "won't do",
            "rejected",
            "nothing to do",
            "nothing to do (2)",
        ]
    ]
    total_subtasks = len(active_subtasks)
    done_subtasks = len(subtasks_by_status["done"])

    return templates.TemplateResponse(
        request,
        "tasks/detail.html",
        {
            "task": task,
            "subtasks": subtasks,
            "subtasks_by_status": subtasks_by_status,
            "total_subtasks": total_subtasks,
            "done_subtasks": done_subtasks,
            "column_labels": COLUMN_LABELS,
            "jira_server": os.getenv("JIRA_SERVER", "").rstrip("/"),
        },
    )


@router.post("/new", response_class=HTMLResponse)
def create_task(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    status: str = Form("To Do"),
    priority: Priority = Form(Priority.medium),
    assignee: str = Form(""),
    due_date: Optional[str] = Form(None),
    jira_key: Optional[str] = Form(None),
    epic_key: Optional[str] = Form(None),
    project_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    """Create a new task (manual or with Jira key)."""
    # Get max position
    max_pos = db.query(Task).filter(Task.status == status).count()

    task = Task(
        title=title,
        description=description,
        status=status,
        jira_status=status,
        priority=priority,
        assignee=assignee,
        due_date=date.fromisoformat(due_date) if due_date else None,
        jira_key=jira_key if jira_key else None,
        epic_key=epic_key if epic_key else None,
        project_id=project_id if project_id else None,
        is_synced=False,
        needs_sync_back=bool(jira_key),  # If has jira_key, mark for sync-back
        position=max_pos,
    )

    # If jira_key provided, generate jira_url
    if jira_key:
        task.jira_url = f"{os.getenv('JIRA_SERVER', '').rstrip('/')}/browse/{jira_key}"

    db.add(task)
    db.commit()

    ctx = _board_context(db, project_id, epic_key)
    template = (
        "tasks/board_content.html"
        if request.headers.get("HX-Request") == "true"
        else "tasks/board.html"
    )
    return templates.TemplateResponse(request, template, ctx)


@router.post("/{task_id}/move", response_class=HTMLResponse)
def move_task(
    task_id: int,
    request: Request,
    status: str = Form(...),
    db: Session = Depends(get_db),
):
    """Move task to a different status column."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Update status
    old_status = task.status
    task.status = status
    task.jira_status = status

    # If synced task, sync to Jira immediately
    if task.jira_key and old_status != status:
        try:
            import os

            from backend.services.jira_service import JiraService

            jira_server = os.getenv("JIRA_SERVER")
            jira_email = os.getenv("JIRA_EMAIL")
            jira_token = os.getenv("JIRA_API_TOKEN")

            if all([jira_server, jira_email, jira_token]):
                jira_service = JiraService(jira_server, jira_email, jira_token)
                result = jira_service.update_issue(task.jira_key, status=status)
                if not result.get("success"):
                    task.needs_sync_back = True
            else:
                task.needs_sync_back = True
        except Exception:
            task.needs_sync_back = True

    db.commit()

    ctx = _board_context(db, task.project_id, task.epic_key)
    template = (
        "tasks/board_content.html"
        if request.headers.get("HX-Request") == "true"
        else "tasks/board.html"
    )
    return templates.TemplateResponse(request, template, ctx)


@router.post("/{task_id}/edit", response_class=HTMLResponse)
def edit_task(
    task_id: int,
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    status: str = Form("To Do"),
    priority: Priority = Form(Priority.medium),
    assignee: str = Form(""),
    due_date: Optional[str] = Form(None),
    jira_key: Optional[str] = Form(None),
    epic_key: Optional[str] = Form(None),
    project_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    """Edit a task."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Track if jira-synced fields changed
    jira_fields_changed = task.status != status or task.assignee != assignee or task.title != title

    task.title = title
    task.description = description
    task.status = status
    task.priority = priority
    task.assignee = assignee
    task.due_date = date.fromisoformat(due_date) if due_date else None
    task.epic_key = epic_key if epic_key else None
    task.project_id = project_id if project_id else None

    # Handle jira_key update
    if jira_key and jira_key != task.jira_key:
        task.jira_key = jira_key
        task.jira_url = f"{os.getenv('JIRA_SERVER', '').rstrip('/')}/browse/{jira_key}"
        task.needs_sync_back = True
    elif not jira_key:
        task.jira_key = None
        task.jira_url = ""

    # Mark for sync-back if Jira fields changed
    if task.jira_key and jira_fields_changed:
        task.needs_sync_back = True

    db.commit()

    ctx = _board_context(db, task.project_id, task.epic_key)
    template = (
        "tasks/board_content.html"
        if request.headers.get("HX-Request") == "true"
        else "tasks/board.html"
    )
    return templates.TemplateResponse(request, template, ctx)


@router.post("/{task_id}/delete", response_class=HTMLResponse)
def delete_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    """Delete a task."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    project_id = task.project_id
    epic_key = task.epic_key

    db.delete(task)
    db.commit()

    ctx = _board_context(db, project_id, epic_key)
    template = (
        "tasks/board_content.html"
        if request.headers.get("HX-Request") == "true"
        else "tasks/board.html"
    )
    return templates.TemplateResponse(request, template, ctx)


@router.post("/{task_id}/link-jira", response_class=HTMLResponse)
def link_jira(
    task_id: int,
    request: Request,
    jira_key: str = Form(...),
    db: Session = Depends(get_db),
):
    """Link a manual task to a Jira issue."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.jira_key = jira_key
    task.jira_url = f"{os.getenv('JIRA_SERVER', '').rstrip('/')}/browse/{jira_key}"
    task.needs_sync_back = True

    db.commit()

    ctx = _board_context(db, task.project_id, task.epic_key)
    template = (
        "tasks/board_content.html"
        if request.headers.get("HX-Request") == "true"
        else "tasks/board.html"
    )
    return templates.TemplateResponse(request, template, ctx)


@router.post("/sync-to-jira", response_class=JSONResponse)
async def sync_tasks_to_jira(request: Request, db: Session = Depends(get_db)):
    """Sync local task changes back to Jira."""
    from backend.services.jira_service import create_jira_service

    # Get tasks that need sync-back
    tasks_to_sync = db.query(Task).filter(Task.needs_sync_back, Task.jira_key.isnot(None)).all()

    if not tasks_to_sync:
        return JSONResponse({"success": True, "message": "No tasks to sync", "synced": 0})

    jira = create_jira_service()
    if not jira:
        return JSONResponse(
            {
                "success": False,
                "message": "Jira service not configured. Check JIRA_SERVER, JIRA_EMAIL, JIRA_API_TOKEN in .env",
                "synced": 0,
            }
        )

    synced = 0
    errors = []

    for task in tasks_to_sync:
        try:
            # Map our status to Jira status
            jira_status = KANBAN_TO_JIRA_MAP.get(normalize_status(task.status), task.status)

            # Update Jira issue
            result = jira.update_issue(
                task.jira_key,
                status=jira_status,
                assignee=task.assignee if task.assignee else None,
            )

            if result["success"]:
                task.needs_sync_back = False
                task.jira_status = result["status"]
                synced += 1
            else:
                errors.append(f"{task.jira_key}: {result['message']}")
        except Exception as e:
            errors.append(f"{task.jira_key}: {str(e)}")

    db.commit()

    if errors:
        return JSONResponse(
            {
                "success": False,
                "message": f"Synced {synced} tasks, {len(errors)} errors",
                "synced": synced,
                "errors": errors,
            }
        )

    return JSONResponse(
        {"success": True, "message": f"Synced {synced} tasks to Jira", "synced": synced}
    )


@router.post("/{task_id}/subtask/{subtask_key}/transition", response_class=JSONResponse)
async def transition_subtask(
    task_id: int,
    subtask_key: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Transition a subtask to a new status in Jira.

    Request body: {"status": "Done"} or {"status": "In Development"}
    """
    from backend.services.jira_service import create_jira_service

    # Get the parent task
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return JSONResponse({"success": False, "error": "Task not found"}, status_code=404)

    # Parse request body
    try:
        body = await request.json()
        target_status = body.get("status")
        if not target_status:
            return JSONResponse(
                {"success": False, "error": "Missing 'status' in request body"},
                status_code=400,
            )
    except Exception as e:
        return JSONResponse({"success": False, "error": f"Invalid JSON: {e}"}, status_code=400)

    # Create Jira service
    jira = create_jira_service()
    if not jira:
        return JSONResponse(
            {"success": False, "error": "Jira service not configured"}, status_code=500
        )

    # Transition the subtask in Jira
    result = jira.transition_issue(subtask_key, target_status)

    if not result["success"]:
        return JSONResponse({"success": False, "error": result["error"]}, status_code=400)

    # Update local subtasks_json
    if task.subtasks_json:
        try:
            subtasks = json.loads(task.subtasks_json)
            for st in subtasks:
                if st["key"] == subtask_key:
                    st["status"] = result["new_status"]
                    break
            task.subtasks_json = json.dumps(subtasks)
            db.commit()
        except json.JSONDecodeError:
            pass

    return JSONResponse(
        {
            "success": True,
            "subtask_key": subtask_key,
            "new_status": result["new_status"],
            "transition_used": result.get("transition_used"),
        }
    )


@router.post("/{task_id}/sync-subtasks", response_class=JSONResponse)
def sync_task_subtasks(
    task_id: int,
    db: Session = Depends(get_db),
):
    """Re-fetch subtasks from Jira for a single story and update the DB."""
    from backend.services.jira_service import create_jira_service

    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return JSONResponse({"success": False, "error": "Task not found"}, status_code=404)

    if not task.jira_key:
        return JSONResponse({"success": False, "error": "Task has no Jira key"}, status_code=400)

    jira = create_jira_service()
    if not jira:
        return JSONResponse(
            {"success": False, "error": "Jira service not configured"}, status_code=500
        )

    subtasks = jira.get_subtasks_for_story(task.jira_key)
    task.subtasks_json = json.dumps(subtasks)
    db.commit()

    return JSONResponse({"success": True, "subtask_count": len(subtasks)})


@router.get("/{task_id}/subtask/{subtask_key}/transitions", response_class=JSONResponse)
def get_subtask_transitions(
    task_id: int,
    subtask_key: str,
    db: Session = Depends(get_db),
):
    """Get available transitions for a subtask."""
    from backend.services.jira_service import create_jira_service

    jira = create_jira_service()
    if not jira:
        return JSONResponse(
            {"success": False, "error": "Jira service not configured"}, status_code=500
        )

    transitions = jira.get_transitions_for_issue(subtask_key)
    return JSONResponse({"success": True, "subtask_key": subtask_key, "transitions": transitions})
