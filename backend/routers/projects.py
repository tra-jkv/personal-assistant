import os
from typing import List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.models import (
    Epic,
    ExternalLink,
    Goal,
    MeetingNote,
    Note,
    Project,
    Reminder,
)
from backend.models.models import GoalStatus, LinkType, Priority, ProjectStatus

router = APIRouter(prefix="/projects", tags=["projects"])
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))


# ── Pydantic models for JSON API ──────────────────────────────────────────────


class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    status: str = "active"  # active, paused, completed, archived
    priority: str = "medium"  # low, medium, high, critical
    start_date: Optional[str] = None  # ISO format
    end_date: Optional[str] = None
    goal_ids: List[int] = []
    epic_keys: List[str] = []


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class ProjectLinkGoal(BaseModel):
    goal_id: int


class ProjectLinkEpic(BaseModel):
    epic_key: str


def _project_to_dict(project: Project) -> dict:
    """Convert Project model to dictionary for JSON response"""
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "status": project.status.value if project.status else "active",
        "priority": project.priority.value if project.priority else "medium",
        "start_date": project.start_date.isoformat() if project.start_date else None,
        "end_date": project.end_date.isoformat() if project.end_date else None,
        "goals": [{"id": g.id, "title": g.title} for g in project.goals] if project.goals else [],
        "epics": [{"key": e.key, "title": e.title} for e in project.epics] if project.epics else [],
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }


# ── JSON API endpoints ────────────────────────────────────────────────────────


@router.get("/api", response_class=JSONResponse)
def list_projects_api(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    List all projects with optional status and priority filters.

    Query params:
    - status: Filter by status (active, paused, completed, archived)
    - priority: Filter by priority (low, medium, high, critical)
    """
    query = db.query(Project).options(joinedload(Project.goals), joinedload(Project.epics))

    if status:
        try:
            query = query.filter(Project.status == ProjectStatus(status))
        except ValueError:
            pass

    if priority:
        try:
            query = query.filter(Project.priority == Priority(priority))
        except ValueError:
            pass

    projects = query.order_by(Project.priority.desc(), Project.updated_at.desc()).all()

    return {"projects": [_project_to_dict(p) for p in projects]}


@router.get("/api/{project_id}", response_class=JSONResponse)
def get_project_api(
    project_id: int,
    db: Session = Depends(get_db),
):
    """Get a single project by ID with all related entities."""
    project = (
        db.query(Project)
        .options(joinedload(Project.goals), joinedload(Project.epics))
        .filter(Project.id == project_id)
        .first()
    )
    if not project:
        return JSONResponse({"success": False, "error": "Project not found"}, status_code=404)

    return {"success": True, "project": _project_to_dict(project)}


@router.post("/api", response_class=JSONResponse)
def create_project_api(
    project_data: ProjectCreate,
    db: Session = Depends(get_db),
):
    """
    Create a new project.

    Request body:
    {
        "name": "Project name",
        "description": "Description",
        "status": "active",
        "priority": "high",
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
        "goal_ids": [1, 2],
        "epic_keys": ["DL-123"]
    }
    """
    from datetime import date

    project = Project(
        name=project_data.name,
        description=project_data.description,
        status=ProjectStatus(project_data.status) if project_data.status else ProjectStatus.active,
        priority=Priority(project_data.priority) if project_data.priority else Priority.medium,
        start_date=date.fromisoformat(project_data.start_date) if project_data.start_date else None,
        end_date=date.fromisoformat(project_data.end_date) if project_data.end_date else None,
    )

    if project_data.goal_ids:
        goals = db.query(Goal).filter(Goal.id.in_(project_data.goal_ids)).all()
        project.goals = goals

    if project_data.epic_keys:
        # One-to-many: update each epic's project_id
        epics = db.query(Epic).filter(Epic.key.in_(project_data.epic_keys)).all()
        for epic in epics:
            epic.project_id = project.id

    db.add(project)
    db.commit()
    db.refresh(project)

    return {"success": True, "project": _project_to_dict(project)}


@router.put("/api/{project_id}", response_class=JSONResponse)
def update_project_api(
    project_id: int,
    project_data: ProjectUpdate,
    db: Session = Depends(get_db),
):
    """Update an existing project. Only provided fields will be updated."""
    from datetime import date

    project = (
        db.query(Project)
        .options(joinedload(Project.goals), joinedload(Project.epics))
        .filter(Project.id == project_id)
        .first()
    )
    if not project:
        return JSONResponse({"success": False, "error": "Project not found"}, status_code=404)

    if project_data.name is not None:
        project.name = project_data.name
    if project_data.description is not None:
        project.description = project_data.description
    if project_data.status is not None:
        project.status = ProjectStatus(project_data.status)
    if project_data.priority is not None:
        project.priority = Priority(project_data.priority)
    if project_data.start_date is not None:
        project.start_date = (
            date.fromisoformat(project_data.start_date) if project_data.start_date else None
        )
    if project_data.end_date is not None:
        project.end_date = (
            date.fromisoformat(project_data.end_date) if project_data.end_date else None
        )

    db.commit()
    db.refresh(project)

    return {"success": True, "project": _project_to_dict(project)}


@router.delete("/api/{project_id}", response_class=JSONResponse)
def delete_project_api(
    project_id: int,
    db: Session = Depends(get_db),
):
    """Delete a project by ID."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return JSONResponse({"success": False, "error": "Project not found"}, status_code=404)

    db.delete(project)
    db.commit()

    return {"success": True, "message": f"Project {project_id} deleted"}


@router.post("/api/{project_id}/link-goal", response_class=JSONResponse)
def link_goal_to_project_api(
    project_id: int,
    link_data: ProjectLinkGoal,
    db: Session = Depends(get_db),
):
    """Link a goal to a project."""
    project = (
        db.query(Project)
        .options(joinedload(Project.goals))
        .filter(Project.id == project_id)
        .first()
    )
    if not project:
        return JSONResponse({"success": False, "error": "Project not found"}, status_code=404)

    goal = db.query(Goal).filter(Goal.id == link_data.goal_id).first()
    if not goal:
        return JSONResponse({"success": False, "error": "Goal not found"}, status_code=404)

    if goal not in project.goals:
        project.goals.append(goal)
        db.commit()

    return {"success": True, "project": _project_to_dict(project)}


@router.delete("/api/{project_id}/unlink-goal/{goal_id}", response_class=JSONResponse)
def unlink_goal_from_project_api(
    project_id: int,
    goal_id: int,
    db: Session = Depends(get_db),
):
    """Unlink a goal from a project."""
    project = (
        db.query(Project)
        .options(joinedload(Project.goals))
        .filter(Project.id == project_id)
        .first()
    )
    if not project:
        return JSONResponse({"success": False, "error": "Project not found"}, status_code=404)

    goal = db.query(Goal).filter(Goal.id == goal_id).first()
    if goal and goal in project.goals:
        project.goals.remove(goal)
        db.commit()

    return {"success": True, "project": _project_to_dict(project)}


@router.post("/api/{project_id}/link-epic", response_class=JSONResponse)
def link_epic_to_project_api(
    project_id: int,
    link_data: ProjectLinkEpic,
    db: Session = Depends(get_db),
):
    """Link a Jira epic to a project (one-to-many: epic belongs to one project)."""
    project = (
        db.query(Project)
        .options(joinedload(Project.epics))
        .filter(Project.id == project_id)
        .first()
    )
    if not project:
        return JSONResponse({"success": False, "error": "Project not found"}, status_code=404)

    epic = db.query(Epic).filter(Epic.key == link_data.epic_key).first()
    if not epic:
        return JSONResponse({"success": False, "error": "Epic not found"}, status_code=404)

    # One-to-many: set the epic's project_id
    epic.project_id = project.id
    db.commit()

    return {"success": True, "project": _project_to_dict(project)}


@router.delete("/api/{project_id}/unlink-epic/{epic_key}", response_class=JSONResponse)
def unlink_epic_from_project_api(
    project_id: int,
    epic_key: str,
    db: Session = Depends(get_db),
):
    """Unlink a Jira epic from a project."""
    project = (
        db.query(Project)
        .options(joinedload(Project.epics))
        .filter(Project.id == project_id)
        .first()
    )
    if not project:
        return JSONResponse({"success": False, "error": "Project not found"}, status_code=404)

    epic = db.query(Epic).filter(Epic.key == epic_key).first()
    if epic and epic.project_id == project_id:
        epic.project_id = None
        db.commit()

    return {"success": True, "project": _project_to_dict(project)}


# ── HTML endpoints ────────────────────────────────────────────────────────────


@router.get("/", response_class=HTMLResponse)
def list_projects(request: Request, db: Session = Depends(get_db)):
    """Kanban board view of projects grouped by status (default view)"""
    projects = (
        db.query(Project)
        .options(joinedload(Project.goals), joinedload(Project.epics))
        .order_by(Project.priority.desc(), Project.updated_at.desc())
        .all()
    )

    # Group projects by status
    columns = {
        ProjectStatus.active: [],
        ProjectStatus.paused: [],
        ProjectStatus.completed: [],
        ProjectStatus.archived: [],
    }

    for project in projects:
        columns[project.status].append(project)

    # Stats
    total_projects = len(projects)
    active_projects = len(columns[ProjectStatus.active])
    completed_projects = len(columns[ProjectStatus.completed])

    is_htmx = request.headers.get("HX-Request") == "true"
    template = "projects/board_content.html" if is_htmx else "projects/board.html"

    return templates.TemplateResponse(
        request,
        template,
        {
            "columns": columns,
            "statuses": list(ProjectStatus),
            "priorities": list(Priority),
            "total_projects": total_projects,
            "active_projects": active_projects,
            "completed_projects": completed_projects,
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_project_form(request: Request):
    return templates.TemplateResponse(
        request,
        "projects/form.html",
        {
            "project": None,
            "statuses": list(ProjectStatus),
            "priorities": list(Priority),
        },
    )


@router.post("/new", response_class=HTMLResponse)
def create_project(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    status: ProjectStatus = Form(ProjectStatus.active),
    priority: Priority = Form(Priority.medium),
    db: Session = Depends(get_db),
):
    project = Project(name=name, description=description, status=status, priority=priority)
    db.add(project)
    db.commit()
    db.refresh(project)
    projects = db.query(Project).order_by(Project.updated_at.desc()).all()
    is_htmx = request.headers.get("HX-Request") == "true"
    template = "projects/list_content.html" if is_htmx else "projects/list.html"
    return templates.TemplateResponse(request, template, {"projects": projects})


@router.get("/{project_id}", response_class=HTMLResponse)
def get_project(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = (
        db.query(Project)
        .options(
            joinedload(Project.goals),
            joinedload(Project.epics).joinedload(Epic.tasks),
        )
        .filter(Project.id == project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    notes = (
        db.query(Note).filter(Note.project_id == project_id).order_by(Note.updated_at.desc()).all()
    )
    reminders = (
        db.query(Reminder).filter(Reminder.project_id == project_id).order_by(Reminder.due_at).all()
    )
    meetings = (
        db.query(MeetingNote)
        .filter(MeetingNote.project_id == project_id)
        .order_by(MeetingNote.meeting_date.desc())
        .all()
    )
    links = (
        db.query(ExternalLink)
        .filter(ExternalLink.project_id == project_id)
        .order_by(ExternalLink.created_at.desc())
        .all()
    )
    # Get all goals for linking
    all_goals = (
        db.query(Goal)
        .filter(Goal.status != GoalStatus.cancelled)
        .order_by(Goal.year.desc(), Goal.title)
        .all()
    )
    # Get all epics for linking
    all_epics = db.query(Epic).order_by(Epic.key).all()

    return templates.TemplateResponse(
        request,
        "projects/detail.html",
        {
            "project": project,
            "notes": notes,
            "reminders": reminders,
            "meetings": meetings,
            "links": links,
            "all_goals": all_goals,
            "all_epics": all_epics,
            "statuses": list(ProjectStatus),
            "priorities": list(Priority),
            "link_types": list(LinkType),
        },
    )


@router.post("/{project_id}/edit", response_class=HTMLResponse)
def edit_project(
    project_id: int,
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    status: ProjectStatus = Form(ProjectStatus.active),
    priority: Priority = Form(Priority.medium),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project.name = name
    project.description = description
    project.status = status
    project.priority = priority
    db.commit()
    db.refresh(project)
    notes = (
        db.query(Note).filter(Note.project_id == project_id).order_by(Note.updated_at.desc()).all()
    )
    reminders = (
        db.query(Reminder).filter(Reminder.project_id == project_id).order_by(Reminder.due_at).all()
    )
    meetings = (
        db.query(MeetingNote)
        .filter(MeetingNote.project_id == project_id)
        .order_by(MeetingNote.meeting_date.desc())
        .all()
    )
    links = (
        db.query(ExternalLink)
        .filter(ExternalLink.project_id == project_id)
        .order_by(ExternalLink.created_at.desc())
        .all()
    )
    all_goals = (
        db.query(Goal)
        .filter(Goal.status != GoalStatus.cancelled)
        .order_by(Goal.year.desc(), Goal.title)
        .all()
    )
    all_epics = db.query(Epic).order_by(Epic.key).all()
    is_htmx = request.headers.get("HX-Request") == "true"
    template = "projects/detail_content.html" if is_htmx else "projects/detail.html"
    return templates.TemplateResponse(
        request,
        template,
        {
            "project": project,
            "notes": notes,
            "reminders": reminders,
            "meetings": meetings,
            "links": links,
            "all_goals": all_goals,
            "all_epics": all_epics,
            "statuses": list(ProjectStatus),
            "priorities": list(Priority),
            "link_types": list(LinkType),
        },
    )


@router.post("/{project_id}/delete", response_class=HTMLResponse)
def delete_project(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if project:
        db.delete(project)
        db.commit()
    projects = db.query(Project).order_by(Project.updated_at.desc()).all()
    is_htmx = request.headers.get("HX-Request") == "true"
    template = "projects/list_content.html" if is_htmx else "projects/list.html"
    return templates.TemplateResponse(request, template, {"projects": projects})


@router.post("/{project_id}/link-goal", response_class=HTMLResponse)
def link_goal(
    project_id: int,
    request: Request,
    goal_id: int = Form(...),
    db: Session = Depends(get_db),
):
    """Link a goal to this project"""
    project = (
        db.query(Project)
        .options(joinedload(Project.goals))
        .filter(Project.id == project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    goal = db.query(Goal).filter(Goal.id == goal_id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    if goal not in project.goals:
        project.goals.append(goal)
        db.commit()

    return templates.TemplateResponse(
        request,
        "projects/linked_goals.html",
        {"project": project},
    )


@router.post("/{project_id}/unlink-goal/{goal_id}", response_class=HTMLResponse)
def unlink_goal(
    project_id: int,
    goal_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Unlink a goal from this project"""
    project = (
        db.query(Project)
        .options(joinedload(Project.goals))
        .filter(Project.id == project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    goal = db.query(Goal).filter(Goal.id == goal_id).first()
    if goal and goal in project.goals:
        project.goals.remove(goal)
        db.commit()

    return templates.TemplateResponse(
        request,
        "projects/linked_goals.html",
        {"project": project},
    )


@router.post("/{project_id}/link-epic", response_class=HTMLResponse)
def link_epic(
    project_id: int,
    request: Request,
    epic_key: str = Form(...),
    db: Session = Depends(get_db),
):
    """Link an epic to this project (one-to-many: epic belongs to one project)"""
    project = (
        db.query(Project)
        .options(joinedload(Project.epics).joinedload(Epic.tasks))
        .filter(Project.id == project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    epic = db.query(Epic).filter(Epic.key == epic_key).first()
    if not epic:
        raise HTTPException(status_code=404, detail="Epic not found")

    # One-to-many: set the epic's project_id
    epic.project_id = project.id
    db.commit()

    # Refresh to get updated epics list
    db.refresh(project)

    return templates.TemplateResponse(
        request,
        "projects/linked_epics.html",
        {"project": project},
    )


@router.post("/{project_id}/unlink-epic/{epic_key}", response_class=HTMLResponse)
def unlink_epic(
    project_id: int,
    epic_key: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Unlink an epic from this project"""
    project = (
        db.query(Project)
        .options(joinedload(Project.epics).joinedload(Epic.tasks))
        .filter(Project.id == project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    epic = db.query(Epic).filter(Epic.key == epic_key).first()
    if epic and epic.project_id == project_id:
        epic.project_id = None
        db.commit()

    # Refresh to get updated epics list
    db.refresh(project)

    return templates.TemplateResponse(
        request,
        "projects/linked_epics.html",
        {"project": project},
    )
