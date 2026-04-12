import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import case
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Goal, Project, Reminder
from backend.models.models import Priority

router = APIRouter(prefix="/reminders", tags=["reminders"])
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))

# Priority order for sorting (critical first)
PRIORITY_ORDER = {
    Priority.critical: 1,
    Priority.high: 2,
    Priority.medium: 3,
    Priority.low: 4,
}


# ── Pydantic models for JSON API ──────────────────────────────────────────────


class ReminderCreate(BaseModel):
    title: str
    description: str = ""
    due_at: str  # ISO format: "2026-04-15T10:00:00"
    priority: str = "medium"  # low, medium, high, critical
    project_id: Optional[int] = None
    task_id: Optional[int] = None


class ReminderUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_at: Optional[str] = None
    priority: Optional[str] = None
    project_id: Optional[int] = None
    task_id: Optional[int] = None
    is_done: Optional[bool] = None


# ── JSON API endpoints ────────────────────────────────────────────────────────


@router.post("/api", response_class=JSONResponse)
def create_reminder_api(
    reminder_data: ReminderCreate,
    db: Session = Depends(get_db),
):
    """
    Create a new reminder via JSON API.

    Request body:
    {
        "title": "Reminder title",
        "description": "Description (optional)",
        "due_at": "2026-04-15T10:00:00",
        "priority": "medium" (low/medium/high/critical),
        "project_id": 1 (optional)
    }
    """
    try:
        due_dt = datetime.fromisoformat(reminder_data.due_at)
    except ValueError:
        return JSONResponse(
            {
                "success": False,
                "error": "Invalid due_at format. Use ISO format: 2026-04-15T10:00:00",
            },
            status_code=400,
        )

    try:
        priority = Priority(reminder_data.priority)
    except ValueError:
        priority = Priority.medium

    reminder = Reminder(
        title=reminder_data.title,
        description=reminder_data.description,
        due_at=due_dt,
        priority=priority,
        project_id=reminder_data.project_id,
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)

    return {
        "success": True,
        "reminder": {
            "id": reminder.id,
            "title": reminder.title,
            "description": reminder.description,
            "due_at": reminder.due_at.isoformat() if reminder.due_at else None,
            "priority": reminder.priority.value if reminder.priority else "medium",
            "is_done": reminder.is_done,
            "project_id": reminder.project_id,
            "created_at": reminder.created_at.isoformat() if reminder.created_at else None,
        },
    }


@router.get("/api", response_class=JSONResponse)
def list_reminders_api(
    project_id: Optional[int] = None,
    include_done: bool = False,
    db: Session = Depends(get_db),
):
    """
    List reminders via JSON API with optional project filter.
    """
    query = db.query(Reminder)

    if project_id:
        query = query.filter(Reminder.project_id == project_id)

    if not include_done:
        query = query.filter(not Reminder.is_done)

    reminders = query.order_by(Reminder.due_at).all()

    return {
        "reminders": [
            {
                "id": r.id,
                "title": r.title,
                "description": r.description,
                "due_at": r.due_at.isoformat() if r.due_at else None,
                "priority": r.priority.value if r.priority else "medium",
                "is_done": r.is_done,
                "project_id": r.project_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reminders
        ]
    }


@router.post("/api/{reminder_id}/toggle", response_class=JSONResponse)
def toggle_reminder_api(
    reminder_id: int,
    db: Session = Depends(get_db),
):
    """Toggle reminder done status via JSON API."""
    reminder = db.query(Reminder).filter(Reminder.id == reminder_id).first()
    if not reminder:
        return JSONResponse(
            {"success": False, "error": "Reminder not found"},
            status_code=404,
        )

    reminder.is_done = not reminder.is_done
    db.commit()

    return {
        "success": True,
        "reminder": {
            "id": reminder.id,
            "is_done": reminder.is_done,
        },
    }


@router.get("/api/{reminder_id}", response_class=JSONResponse)
def get_reminder_api(
    reminder_id: int,
    db: Session = Depends(get_db),
):
    """Get a single reminder by ID."""
    reminder = db.query(Reminder).filter(Reminder.id == reminder_id).first()
    if not reminder:
        return JSONResponse({"success": False, "error": "Reminder not found"}, status_code=404)

    return {
        "success": True,
        "reminder": {
            "id": reminder.id,
            "title": reminder.title,
            "description": reminder.description,
            "due_at": reminder.due_at.isoformat() if reminder.due_at else None,
            "priority": reminder.priority.value if reminder.priority else "medium",
            "is_done": reminder.is_done,
            "project_id": reminder.project_id,
            "task_id": reminder.task_id,
            "created_at": reminder.created_at.isoformat() if reminder.created_at else None,
        },
    }


@router.put("/api/{reminder_id}", response_class=JSONResponse)
def update_reminder_api(
    reminder_id: int,
    reminder_data: ReminderUpdate,
    db: Session = Depends(get_db),
):
    """Update an existing reminder. Only provided fields will be updated."""
    reminder = db.query(Reminder).filter(Reminder.id == reminder_id).first()
    if not reminder:
        return JSONResponse({"success": False, "error": "Reminder not found"}, status_code=404)

    if reminder_data.title is not None:
        reminder.title = reminder_data.title
    if reminder_data.description is not None:
        reminder.description = reminder_data.description
    if reminder_data.due_at is not None:
        try:
            reminder.due_at = datetime.fromisoformat(reminder_data.due_at)
        except ValueError:
            return JSONResponse(
                {"success": False, "error": "Invalid due_at format"},
                status_code=400,
            )
    if reminder_data.priority is not None:
        try:
            reminder.priority = Priority(reminder_data.priority)
        except ValueError:
            pass
    if reminder_data.project_id is not None:
        reminder.project_id = reminder_data.project_id if reminder_data.project_id else None
    if reminder_data.task_id is not None:
        reminder.task_id = reminder_data.task_id if reminder_data.task_id else None
    if reminder_data.is_done is not None:
        reminder.is_done = reminder_data.is_done

    db.commit()
    db.refresh(reminder)

    return {
        "success": True,
        "reminder": {
            "id": reminder.id,
            "title": reminder.title,
            "description": reminder.description,
            "due_at": reminder.due_at.isoformat() if reminder.due_at else None,
            "priority": reminder.priority.value if reminder.priority else "medium",
            "is_done": reminder.is_done,
            "project_id": reminder.project_id,
            "task_id": reminder.task_id,
            "created_at": reminder.created_at.isoformat() if reminder.created_at else None,
        },
    }


@router.delete("/api/{reminder_id}", response_class=JSONResponse)
def delete_reminder_api(
    reminder_id: int,
    db: Session = Depends(get_db),
):
    """Delete a reminder by ID."""
    reminder = db.query(Reminder).filter(Reminder.id == reminder_id).first()
    if not reminder:
        return JSONResponse({"success": False, "error": "Reminder not found"}, status_code=404)

    db.delete(reminder)
    db.commit()

    return {"success": True, "message": f"Reminder {reminder_id} deleted"}


# ── HTML helper ───────────────────────────────────────────────────────────────


def _render_list(
    request: Request,
    db: Session,
    project_id: Optional[int] = None,
    goal_id: Optional[int] = None,
    sort_by: str = "due_date",
):
    # Base query
    query = db.query(Reminder)

    # Filter by project
    if project_id:
        query = query.filter(Reminder.project_id == project_id)

    # Filter by goal (reminders linked to projects under that goal)
    if goal_id:
        goal = db.query(Goal).filter(Goal.id == goal_id).first()
        if goal:
            project_ids = [p.id for p in goal.projects]
            if project_ids:
                query = query.filter(Reminder.project_id.in_(project_ids))
            else:
                # Goal has no projects, return empty
                query = query.filter(Reminder.id == -1)

    # Sorting
    if sort_by == "priority":
        # Sort by priority (critical first), then due date
        priority_case = case(PRIORITY_ORDER, value=Reminder.priority, else_=99)
        query = query.order_by(Reminder.is_done, priority_case, Reminder.due_at)
    else:
        # Default: sort by due date
        query = query.order_by(Reminder.is_done, Reminder.due_at)

    reminders = query.all()
    projects = db.query(Project).order_by(Project.name).all()
    goals = db.query(Goal).order_by(Goal.title).all()
    now = datetime.utcnow()

    ctx = {
        "reminders": reminders,
        "projects": projects,
        "goals": goals,
        "priorities": list(Priority),
        "now": now,
        "active_project_id": project_id,
        "active_goal_id": goal_id,
        "sort_by": sort_by,
    }

    is_htmx = request.headers.get("HX-Request") == "true"
    template = "reminders/list_content.html" if is_htmx else "reminders/list.html"
    return templates.TemplateResponse(request, template, ctx)


@router.get("/", response_class=HTMLResponse)
def list_reminders(
    request: Request,
    project_id: Optional[int] = None,
    goal_id: Optional[int] = None,
    sort_by: str = "due_date",
    db: Session = Depends(get_db),
):
    return _render_list(request, db, project_id, goal_id, sort_by)


@router.post("/new", response_class=HTMLResponse)
def create_reminder(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    due_at: str = Form(...),
    priority: Priority = Form(Priority.medium),
    project_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    due_dt = datetime.fromisoformat(due_at)
    reminder = Reminder(
        title=title,
        description=description,
        due_at=due_dt,
        priority=priority,
        project_id=project_id or None,
    )
    db.add(reminder)
    db.commit()
    return _render_list(request, db)


@router.post("/{reminder_id}/toggle", response_class=HTMLResponse)
def toggle_reminder(reminder_id: int, request: Request, db: Session = Depends(get_db)):
    reminder = db.query(Reminder).filter(Reminder.id == reminder_id).first()
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")
    reminder.is_done = not reminder.is_done
    db.commit()
    return _render_list(request, db)


@router.post("/{reminder_id}/delete", response_class=HTMLResponse)
def delete_reminder(reminder_id: int, request: Request, db: Session = Depends(get_db)):
    reminder = db.query(Reminder).filter(Reminder.id == reminder_id).first()
    if reminder:
        db.delete(reminder)
        db.commit()
    return _render_list(request, db)
