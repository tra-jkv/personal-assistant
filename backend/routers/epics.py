import os
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
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
    ctx = _epics_board_context(db, project_id=project_id, filter=filter)
    is_htmx = request.headers.get("HX-Request") == "true"
    template = "epics/list_content.html" if is_htmx else "epics/list.html"
    return templates.TemplateResponse(request, template, ctx)


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


def _epics_board_context(
    db: Session, project_id: Optional[int] = None, filter: Optional[str] = None
):
    """Build grouped epic data for kanban rendering (shared by list and move endpoints)."""
    query = db.query(Epic).options(
        joinedload(Epic.tasks),
        joinedload(Epic.project).joinedload(Project.goals),
    )
    if project_id is not None:
        query = query.filter(Epic.project_id == project_id)

    epics_list = query.order_by(Epic.position.asc().nullslast(), Epic.key.desc()).all()

    if filter == "unassigned":
        epics_list = [e for e in epics_list if e.project is None]
    elif filter == "assigned":
        epics_list = [e for e in epics_list if e.project is not None]

    epics_by_status = {}
    for col in EPIC_STATUS_COLUMNS:
        epics_by_status[col["key"]] = [e for e in epics_list if e.status in col["statuses"]]

    projects = (
        db.query(Project)
        .filter(Project.status != ProjectStatus.archived)
        .order_by(Project.name)
        .all()
    )

    current_project = None
    if project_id is not None:
        current_project = db.query(Project).filter(Project.id == project_id).first()

    return {
        "epics": epics_list,
        "epics_by_status": epics_by_status,
        "columns": EPIC_STATUS_COLUMNS,
        "projects": projects,
        "current_project": current_project,
        "project_id": project_id,
        "filter": filter,
        "total_epics": len(epics_list),
        "assigned_epics": sum(1 for e in epics_list if e.project is not None),
        "unassigned_epics": sum(1 for e in epics_list if e.project is None),
        "in_progress_epics": len(epics_by_status.get("in_development", [])),
        "done_epics": len(epics_by_status.get("done", [])),
        "current_user": CURRENT_USER_DISPLAY_NAME,
    }


@router.post("/{epic_key}/move", response_class=HTMLResponse)
def move_epic(
    epic_key: str,
    request: Request,
    status: str = Form(...),
    db: Session = Depends(get_db),
):
    """Move an epic to a different status column (local-only; does not push to Jira)."""
    epic = db.query(Epic).filter(Epic.key == epic_key).first()
    if not epic:
        raise HTTPException(status_code=404, detail="Epic not found")

    epic.status = status
    db.commit()

    ctx = _epics_board_context(db)
    template = (
        "epics/list_content.html"
        if request.headers.get("HX-Request") == "true"
        else "epics/list.html"
    )
    return templates.TemplateResponse(request, template, ctx)


@router.post("/{epic_key}/reorder", response_class=JSONResponse)
async def reorder_epic(
    epic_key: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Persist within-column DnD reorder for epics.

    Body: { "position": <int>, "status": "<status_string>" }
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    new_position = body.get("position")
    status_hint = body.get("status")

    epic = db.query(Epic).filter(Epic.key == epic_key).first()
    if not epic:
        return JSONResponse({"success": False, "error": "Epic not found"}, status_code=404)

    # Find which column this epic belongs to
    col_statuses: list[str] = []
    for col in EPIC_STATUS_COLUMNS:
        check_status = status_hint or epic.status
        if check_status in col["statuses"]:
            col_statuses = col["statuses"]
            break
    if not col_statuses:
        col_statuses = [status_hint or epic.status]

    col_epics = (
        db.query(Epic)
        .filter(Epic.status.in_(col_statuses))
        .order_by(Epic.position.asc().nullslast(), Epic.key.desc())
        .all()
    )

    col_epics = [e for e in col_epics if e.key != epic_key]
    if new_position is None:
        new_position = len(col_epics)
    new_position = max(0, min(new_position, len(col_epics)))
    col_epics.insert(new_position, epic)

    for idx, e in enumerate(col_epics):
        e.position = idx

    db.commit()
    return JSONResponse({"success": True, "epic_key": epic_key, "position": new_position})


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
