import os
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.models import Epic, Project
from backend.models.models import ProjectStatus

router = APIRouter(prefix="/epics", tags=["epics"])
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))

# Get current user display name from environment
CURRENT_USER_DISPLAY_NAME = os.getenv("USER_DISPLAY_NAME", "Unknown")

# Define epic status columns for Kanban
EPIC_STATUS_COLUMNS = [
    {"key": "to_refine", "label": "To Refine", "statuses": ["To Refine"]},
    {"key": "in_refinement", "label": "In Refinement", "statuses": ["In Refinement"]},
    {
        "key": "in_development",
        "label": "In Development",
        "statuses": ["In Development"],
    },
    {"key": "done", "label": "Done", "statuses": ["Done"]},
    {"key": "cancelled", "label": "Cancelled", "statuses": ["Cancelled"]},
]


@router.get("/", response_class=HTMLResponse)
def list_epics(
    request: Request,
    filter: Optional[str] = None,  # "unassigned", "assigned", or None for all
    project_id: Optional[int] = None,  # Filter by project
    db: Session = Depends(get_db),
):
    """Epics Kanban board - organized by status"""

    # Get all epics with their tasks and project (one-to-many), including project's goals
    query = db.query(Epic).options(
        joinedload(Epic.tasks),
        joinedload(Epic.project).joinedload(Project.goals),
    )

    # Filter by project if provided
    if project_id is not None:
        query = query.filter(Epic.project_id == project_id)

    epics_list = query.order_by(Epic.key.desc()).all()

    # Filter if requested
    if filter == "unassigned":
        epics_list = [e for e in epics_list if e.project is None]
    elif filter == "assigned":
        epics_list = [e for e in epics_list if e.project is not None]

    # Group epics by status
    epics_by_status = {}
    for col in EPIC_STATUS_COLUMNS:
        epics_by_status[col["key"]] = [e for e in epics_list if e.status in col["statuses"]]

    # Get all active projects for the dropdown
    projects = (
        db.query(Project)
        .filter(Project.status != ProjectStatus.archived)
        .order_by(Project.name)
        .all()
    )

    # Get current project if filtering by project_id
    current_project = None
    if project_id is not None:
        current_project = db.query(Project).filter(Project.id == project_id).first()

    # Count stats
    total_epics = len(epics_list)
    assigned_epics = sum(1 for e in epics_list if e.project is not None)
    unassigned_epics = total_epics - assigned_epics
    in_progress_epics = len(epics_by_status.get("in_development", []))
    done_epics = len(epics_by_status.get("done", []))

    is_htmx = request.headers.get("HX-Request") == "true"
    template = "epics/list_content.html" if is_htmx else "epics/list.html"

    return templates.TemplateResponse(
        request,
        template,
        {
            "epics": epics_list,
            "epics_by_status": epics_by_status,
            "columns": EPIC_STATUS_COLUMNS,
            "projects": projects,
            "current_project": current_project,
            "project_id": project_id,
            "filter": filter,
            "total_epics": total_epics,
            "assigned_epics": assigned_epics,
            "unassigned_epics": unassigned_epics,
            "in_progress_epics": in_progress_epics,
            "done_epics": done_epics,
            "current_user": CURRENT_USER_DISPLAY_NAME,
        },
    )


@router.get("/{epic_key}", response_class=HTMLResponse)
def get_epic(
    epic_key: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """View epic details with tasks"""
    epic = (
        db.query(Epic)
        .options(
            joinedload(Epic.tasks),
            joinedload(Epic.project),
        )
        .filter(Epic.key == epic_key)
        .first()
    )
    if not epic:
        raise HTTPException(status_code=404, detail="Epic not found")

    # Get all active projects for linking
    all_projects = (
        db.query(Project)
        .filter(Project.status != ProjectStatus.archived)
        .order_by(Project.name)
        .all()
    )

    # Group tasks by status
    tasks_by_status = {}
    for task in epic.tasks:
        status = task.status or "Unknown"
        if status not in tasks_by_status:
            tasks_by_status[status] = []
        tasks_by_status[status].append(task)

    # Count task stats
    total_tasks = len(epic.tasks)
    done_tasks = sum(1 for t in epic.tasks if t.status and t.status.lower() in ("done", "closed"))

    return templates.TemplateResponse(
        request,
        "epics/detail.html",
        {
            "epic": epic,
            "all_projects": all_projects,
            "tasks_by_status": tasks_by_status,
            "total_tasks": total_tasks,
            "done_tasks": done_tasks,
        },
    )


@router.post("/{epic_key}/assign", response_class=HTMLResponse)
def assign_epic_to_project(
    epic_key: str,
    request: Request,
    project_id: int = Form(...),
    db: Session = Depends(get_db),
):
    """Assign an epic to a project (one-to-many: epic belongs to one project)"""
    epic = (
        db.query(Epic)
        .options(joinedload(Epic.project), joinedload(Epic.tasks))
        .filter(Epic.key == epic_key)
        .first()
    )
    if not epic:
        raise HTTPException(status_code=404, detail="Epic not found")

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # One-to-many: assign epic to single project
    epic.project_id = project.id
    epic.project = project
    db.commit()

    # Get all projects for dropdown
    projects = (
        db.query(Project)
        .filter(Project.status != ProjectStatus.archived)
        .order_by(Project.name)
        .all()
    )

    return templates.TemplateResponse(
        request,
        "epics/epic_card.html",
        {"epic": epic, "projects": projects, "current_user": CURRENT_USER_DISPLAY_NAME},
    )


@router.post("/{epic_key}/unassign/{project_id}", response_class=HTMLResponse)
def unassign_epic_from_project(
    epic_key: str,
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Remove an epic from its project"""
    epic = (
        db.query(Epic)
        .options(joinedload(Epic.project), joinedload(Epic.tasks))
        .filter(Epic.key == epic_key)
        .first()
    )
    if not epic:
        raise HTTPException(status_code=404, detail="Epic not found")

    # One-to-many: unassign epic from its project
    if epic.project_id == project_id:
        epic.project_id = None
        epic.project = None
        db.commit()

    # Get all projects for dropdown
    projects = (
        db.query(Project)
        .filter(Project.status != ProjectStatus.archived)
        .order_by(Project.name)
        .all()
    )

    return templates.TemplateResponse(
        request,
        "epics/epic_card.html",
        {"epic": epic, "projects": projects, "current_user": CURRENT_USER_DISPLAY_NAME},
    )
