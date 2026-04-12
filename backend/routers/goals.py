from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from typing import Optional, List
from datetime import date
from pydantic import BaseModel
import os

from backend.database import get_db
from backend.models import Goal, Project, Task
from backend.models.models import GoalStatus, ProjectStatus

router = APIRouter(prefix="/goals", tags=["goals"])


def calculate_goal_progress(goal: Goal, db: Session) -> tuple[int, int, int]:
    """
    Calculate goal progress from tasks across all linked projects.
    Returns (progress_pct, done_tasks, total_tasks).
    Done = tasks with status 'done' or 'Done' (Jira). Cancelled tasks are excluded.
    Uses raw string matching to handle both enum values and raw Jira status strings.
    """
    if not goal.projects:
        return 0, 0, 0

    cancelled_statuses = ["cancelled", "Cancelled"]
    done_statuses = ["done", "Done", "closed", "Closed", "resolved", "Resolved"]

    project_ids = [p.id for p in goal.projects]
    total = (
        db.query(Task)
        .filter(
            Task.project_id.in_(project_ids),
            Task.status.notin_(cancelled_statuses),
        )
        .count()
    )
    done = (
        db.query(Task)
        .filter(
            Task.project_id.in_(project_ids),
            Task.status.in_(done_statuses),
        )
        .count()
    )

    pct = round(done / total * 100) if total > 0 else 0
    return pct, done, total


templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "..", "templates")
)


# ── Pydantic models for JSON API ──────────────────────────────────────────────


class GoalCreate(BaseModel):
    title: str
    description: str = ""
    year: Optional[int] = None
    target_date: Optional[str] = None  # ISO format: "2026-12-31"
    status: str = "active"  # active, achieved, cancelled, deferred
    progress_pct: int = 0
    project_ids: List[int] = []


class GoalUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    year: Optional[int] = None
    target_date: Optional[str] = None
    status: Optional[str] = None
    progress_pct: Optional[int] = None


class GoalLinkProject(BaseModel):
    project_id: int


def _goal_to_dict(goal: Goal) -> dict:
    """Convert Goal model to dictionary for JSON response"""
    return {
        "id": goal.id,
        "title": goal.title,
        "description": goal.description,
        "year": goal.year,
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
        "status": goal.status.value if goal.status else "active",
        "progress_pct": goal.progress_pct,
        "projects": [{"id": p.id, "name": p.name} for p in goal.projects]
        if goal.projects
        else [],
        "created_at": goal.created_at.isoformat() if goal.created_at else None,
        "updated_at": goal.updated_at.isoformat() if goal.updated_at else None,
    }


# ── JSON API endpoints ────────────────────────────────────────────────────────


@router.get("/api", response_class=JSONResponse)
def list_goals_api(
    year: Optional[int] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    List all goals with optional year and status filters.

    Query params:
    - year: Filter by year (e.g., 2026)
    - status: Filter by status (active, achieved, cancelled, deferred)
    """
    query = db.query(Goal).options(joinedload(Goal.projects))

    if year:
        query = query.filter(Goal.year == year)

    if status:
        try:
            query = query.filter(Goal.status == GoalStatus(status))
        except ValueError:
            pass

    goals = query.order_by(Goal.progress_pct.desc(), Goal.target_date.asc()).all()

    return {"goals": [_goal_to_dict(g) for g in goals]}


@router.get("/api/{goal_id}", response_class=JSONResponse)
def get_goal_api(
    goal_id: int,
    db: Session = Depends(get_db),
):
    """Get a single goal by ID."""
    goal = (
        db.query(Goal)
        .options(joinedload(Goal.projects))
        .filter(Goal.id == goal_id)
        .first()
    )
    if not goal:
        return JSONResponse(
            {"success": False, "error": "Goal not found"}, status_code=404
        )

    return {"success": True, "goal": _goal_to_dict(goal)}


@router.post("/api", response_class=JSONResponse)
def create_goal_api(
    goal_data: GoalCreate,
    db: Session = Depends(get_db),
):
    """
    Create a new goal.

    Request body:
    {
        "title": "Goal title",
        "description": "Description (optional)",
        "year": 2026,
        "target_date": "2026-12-31",
        "status": "active",
        "progress_pct": 0,
        "project_ids": [1, 2]
    }
    """
    goal = Goal(
        title=goal_data.title,
        description=goal_data.description,
        year=goal_data.year if goal_data.year else get_current_year(),
        target_date=date.fromisoformat(goal_data.target_date)
        if goal_data.target_date
        else None,
        status=GoalStatus(goal_data.status) if goal_data.status else GoalStatus.active,
        progress_pct=max(0, min(100, goal_data.progress_pct)),
    )

    if goal_data.project_ids:
        projects = db.query(Project).filter(Project.id.in_(goal_data.project_ids)).all()
        goal.projects = projects

    db.add(goal)
    db.commit()
    db.refresh(goal)

    return {"success": True, "goal": _goal_to_dict(goal)}


@router.put("/api/{goal_id}", response_class=JSONResponse)
def update_goal_api(
    goal_id: int,
    goal_data: GoalUpdate,
    db: Session = Depends(get_db),
):
    """
    Update an existing goal.

    Only provided fields will be updated.
    """
    goal = (
        db.query(Goal)
        .options(joinedload(Goal.projects))
        .filter(Goal.id == goal_id)
        .first()
    )
    if not goal:
        return JSONResponse(
            {"success": False, "error": "Goal not found"}, status_code=404
        )

    if goal_data.title is not None:
        goal.title = goal_data.title
    if goal_data.description is not None:
        goal.description = goal_data.description
    if goal_data.year is not None:
        goal.year = goal_data.year
    if goal_data.target_date is not None:
        goal.target_date = (
            date.fromisoformat(goal_data.target_date) if goal_data.target_date else None
        )
    if goal_data.status is not None:
        goal.status = GoalStatus(goal_data.status)
    if goal_data.progress_pct is not None:
        goal.progress_pct = max(0, min(100, goal_data.progress_pct))

    db.commit()
    db.refresh(goal)

    return {"success": True, "goal": _goal_to_dict(goal)}


@router.delete("/api/{goal_id}", response_class=JSONResponse)
def delete_goal_api(
    goal_id: int,
    db: Session = Depends(get_db),
):
    """Delete a goal by ID."""
    goal = db.query(Goal).filter(Goal.id == goal_id).first()
    if not goal:
        return JSONResponse(
            {"success": False, "error": "Goal not found"}, status_code=404
        )

    db.delete(goal)
    db.commit()

    return {"success": True, "message": f"Goal {goal_id} deleted"}


@router.post("/api/{goal_id}/progress", response_class=JSONResponse)
def update_goal_progress_api(
    goal_id: int,
    progress_pct: int,
    db: Session = Depends(get_db),
):
    """Update goal progress percentage (0-100)."""
    goal = db.query(Goal).filter(Goal.id == goal_id).first()
    if not goal:
        return JSONResponse(
            {"success": False, "error": "Goal not found"}, status_code=404
        )

    goal.progress_pct = max(0, min(100, progress_pct))
    db.commit()

    return {"success": True, "goal_id": goal_id, "progress_pct": goal.progress_pct}


@router.post("/api/{goal_id}/link-project", response_class=JSONResponse)
def link_project_to_goal_api(
    goal_id: int,
    link_data: GoalLinkProject,
    db: Session = Depends(get_db),
):
    """Link a project to a goal."""
    goal = (
        db.query(Goal)
        .options(joinedload(Goal.projects))
        .filter(Goal.id == goal_id)
        .first()
    )
    if not goal:
        return JSONResponse(
            {"success": False, "error": "Goal not found"}, status_code=404
        )

    project = db.query(Project).filter(Project.id == link_data.project_id).first()
    if not project:
        return JSONResponse(
            {"success": False, "error": "Project not found"}, status_code=404
        )

    if project not in goal.projects:
        goal.projects.append(project)
        db.commit()

    return {"success": True, "goal": _goal_to_dict(goal)}


@router.delete(
    "/api/{goal_id}/unlink-project/{project_id}", response_class=JSONResponse
)
def unlink_project_from_goal_api(
    goal_id: int,
    project_id: int,
    db: Session = Depends(get_db),
):
    """Unlink a project from a goal."""
    goal = (
        db.query(Goal)
        .options(joinedload(Goal.projects))
        .filter(Goal.id == goal_id)
        .first()
    )
    if not goal:
        return JSONResponse(
            {"success": False, "error": "Goal not found"}, status_code=404
        )

    project = db.query(Project).filter(Project.id == project_id).first()
    if project and project in goal.projects:
        goal.projects.remove(project)
        db.commit()

    return {"success": True, "goal": _goal_to_dict(goal)}


# ── HTML helper ───────────────────────────────────────────────────────────────


def get_current_year() -> int:
    """Return current year"""
    return date.today().year


@router.get("/", response_class=HTMLResponse)
def list_goals(
    request: Request,
    year: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Goals Kanban board - organized by status, filtered by year"""
    if not year:
        year = get_current_year()

    query = db.query(Goal).options(joinedload(Goal.projects))

    # Filter by year if specified
    if year:
        query = query.filter(Goal.year == year)

    goals = query.order_by(Goal.progress_pct.desc(), Goal.target_date.asc()).all()

    # Group goals by status
    goals_by_status = {
        "active": [g for g in goals if g.status == GoalStatus.active],
        "achieved": [g for g in goals if g.status == GoalStatus.achieved],
        "deferred": [g for g in goals if g.status == GoalStatus.deferred],
        "cancelled": [g for g in goals if g.status == GoalStatus.cancelled],
    }

    # Calculate stats
    total_goals = len(goals)
    achieved_goals = len(goals_by_status["achieved"])
    active_goals = len(goals_by_status["active"])
    avg_progress = (
        sum(g.progress_pct for g in goals) / total_goals if total_goals > 0 else 0
    )

    # Get available years from database
    years_query = db.query(Goal.year).filter(Goal.year.isnot(None)).distinct().all()
    years = sorted([y[0] for y in years_query if y[0]], reverse=True)

    # Ensure current year is in list
    current_year = get_current_year()
    if current_year not in years:
        years.insert(0, current_year)
    # Add next year for planning
    if current_year + 1 not in years:
        years.insert(0, current_year + 1)

    # Calculate task-based progress for each goal
    goal_progress = {}
    for g in goals:
        pct, done, total = calculate_goal_progress(g, db)
        goal_progress[g.id] = {"pct": pct, "done": done, "total": total}

    avg_progress = (
        sum(v["pct"] for v in goal_progress.values()) / total_goals
        if total_goals > 0
        else 0
    )

    # Goal alignment: % of ALL tasks this year (todo/in-progress/done) in projects linked to a goal
    # Excludes only cancelled tasks.
    # Uses jira_updated_at (actual Jira timestamp) for synced tasks,
    # falling back to updated_at for manually created tasks.
    cancelled_statuses = ["cancelled", "Cancelled"]
    from sqlalchemy import extract, case

    year_filter = (
        extract(
            "year",
            case(
                (Task.jira_updated_at.isnot(None), Task.jira_updated_at),
                else_=Task.updated_at,
            ),
        )
        == year
    )

    all_year_tasks = (
        db.query(Task)
        .filter(Task.status.notin_(cancelled_statuses), year_filter)
        .count()
    )
    goal_project_ids = list({p.id for g in goals for p in g.projects})
    aligned_tasks = (
        db.query(Task)
        .filter(
            Task.status.notin_(cancelled_statuses),
            year_filter,
            Task.project_id.in_(goal_project_ids),
        )
        .count()
        if goal_project_ids
        else 0
    )
    unaligned_tasks = all_year_tasks - aligned_tasks
    alignment_pct = (
        round(aligned_tasks / all_year_tasks * 100) if all_year_tasks > 0 else 0
    )

    is_htmx = request.headers.get("HX-Request") == "true"
    template = "goals/list_content.html" if is_htmx else "goals/list.html"

    return templates.TemplateResponse(
        request,
        template,
        {
            "goals": goals,
            "goals_by_status": goals_by_status,
            "goal_progress": goal_progress,
            "year": year,
            "years": years,
            "total_goals": total_goals,
            "achieved_goals": achieved_goals,
            "active_goals": active_goals,
            "avg_progress": round(avg_progress),
            "statuses": list(GoalStatus),
            "all_year_tasks": all_year_tasks,
            "aligned_tasks": aligned_tasks,
            "unaligned_tasks": unaligned_tasks,
            "alignment_pct": alignment_pct,
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_goal_form(request: Request, db: Session = Depends(get_db)):
    """Show form to create a new goal"""
    projects = (
        db.query(Project)
        .filter(Project.status != ProjectStatus.archived)
        .order_by(Project.name)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "goals/form.html",
        {
            "goal": None,
            "projects": projects,
            "statuses": list(GoalStatus),
            "current_year": get_current_year(),
        },
    )


@router.post("/new", response_class=HTMLResponse)
def create_goal(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    year: Optional[int] = Form(None),
    target_date: Optional[str] = Form(None),
    status: GoalStatus = Form(GoalStatus.active),
    progress_pct: int = Form(0),
    project_ids: List[int] = Form(default=[]),
    db: Session = Depends(get_db),
):
    """Create a new goal"""
    goal = Goal(
        title=title,
        description=description,
        year=year if year else get_current_year(),
        target_date=date.fromisoformat(target_date) if target_date else None,
        status=status,
        progress_pct=max(0, min(100, progress_pct)),
    )

    # Link projects
    if project_ids:
        projects = db.query(Project).filter(Project.id.in_(project_ids)).all()
        goal.projects = projects

    db.add(goal)
    db.commit()

    # Redirect to goals list
    return templates.TemplateResponse(
        request,
        "goals/created.html",
        {"goal": goal},
        headers={"HX-Redirect": "/goals/"},
    )


@router.get("/{goal_id}", response_class=HTMLResponse)
def get_goal(goal_id: int, request: Request, db: Session = Depends(get_db)):
    """View goal details with linked projects and epics"""
    goal = (
        db.query(Goal)
        .options(joinedload(Goal.projects).joinedload(Project.epics))
        .filter(Goal.id == goal_id)
        .first()
    )
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    # Get all projects for linking
    all_projects = (
        db.query(Project)
        .filter(Project.status != ProjectStatus.archived)
        .order_by(Project.name)
        .all()
    )

    # Calculate progress from tasks across linked projects
    progress_pct, done_tasks, total_tasks = calculate_goal_progress(goal, db)

    return templates.TemplateResponse(
        request,
        "goals/detail.html",
        {
            "goal": goal,
            "all_projects": all_projects,
            "statuses": list(GoalStatus),
            "progress_pct": progress_pct,
            "done_tasks": done_tasks,
            "total_tasks": total_tasks,
        },
    )


@router.get("/{goal_id}/edit", response_class=HTMLResponse)
def edit_goal_form(goal_id: int, request: Request, db: Session = Depends(get_db)):
    """Show form to edit a goal"""
    goal = (
        db.query(Goal)
        .options(joinedload(Goal.projects))
        .filter(Goal.id == goal_id)
        .first()
    )
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    projects = (
        db.query(Project)
        .filter(Project.status != ProjectStatus.archived)
        .order_by(Project.name)
        .all()
    )

    return templates.TemplateResponse(
        request,
        "goals/form.html",
        {
            "goal": goal,
            "projects": projects,
            "statuses": list(GoalStatus),
            "current_year": get_current_year(),
        },
    )


@router.post("/{goal_id}/edit", response_class=HTMLResponse)
def edit_goal(
    goal_id: int,
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    year: Optional[int] = Form(None),
    target_date: Optional[str] = Form(None),
    status: GoalStatus = Form(GoalStatus.active),
    progress_pct: int = Form(0),
    project_ids: List[int] = Form(default=[]),
    db: Session = Depends(get_db),
):
    """Update a goal"""
    goal = db.query(Goal).filter(Goal.id == goal_id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    goal.title = title
    goal.description = description
    goal.year = year if year else get_current_year()
    goal.target_date = date.fromisoformat(target_date) if target_date else None
    goal.status = status
    goal.progress_pct = max(0, min(100, progress_pct))

    # Update project links
    if project_ids:
        projects = db.query(Project).filter(Project.id.in_(project_ids)).all()
        goal.projects = projects
    else:
        goal.projects = []

    db.commit()
    db.refresh(goal)

    return templates.TemplateResponse(
        request,
        "goals/updated.html",
        {"goal": goal},
        headers={"HX-Redirect": f"/goals/{goal_id}"},
    )


@router.post("/{goal_id}/progress", response_class=HTMLResponse)
def update_progress(
    goal_id: int,
    request: Request,
    progress_pct: int = Form(...),
    db: Session = Depends(get_db),
):
    """Quick update goal progress (HTMX)"""
    goal = db.query(Goal).filter(Goal.id == goal_id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    goal.progress_pct = max(0, min(100, progress_pct))

    # Auto-mark as achieved if 100%
    if goal.progress_pct == 100 and goal.status == GoalStatus.active:
        goal.status = GoalStatus.achieved

    db.commit()
    db.refresh(goal)

    return templates.TemplateResponse(
        request,
        "goals/progress_bar.html",
        {"goal": goal},
    )


@router.post("/{goal_id}/link-project", response_class=HTMLResponse)
def link_project(
    goal_id: int,
    request: Request,
    project_id: int = Form(...),
    db: Session = Depends(get_db),
):
    """Link a project to a goal"""
    goal = (
        db.query(Goal)
        .options(joinedload(Goal.projects))
        .filter(Goal.id == goal_id)
        .first()
    )
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project not in goal.projects:
        goal.projects.append(project)
        db.commit()

    return templates.TemplateResponse(
        request,
        "goals/linked_projects.html",
        {"goal": goal},
    )


@router.post("/{goal_id}/unlink-project/{project_id}", response_class=HTMLResponse)
def unlink_project(
    goal_id: int,
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Unlink a project from a goal"""
    goal = (
        db.query(Goal)
        .options(joinedload(Goal.projects))
        .filter(Goal.id == goal_id)
        .first()
    )
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    project = db.query(Project).filter(Project.id == project_id).first()
    if project and project in goal.projects:
        goal.projects.remove(project)
        db.commit()

    return templates.TemplateResponse(
        request,
        "goals/linked_projects.html",
        {"goal": goal},
    )


@router.post("/{goal_id}/delete", response_class=HTMLResponse)
def delete_goal(goal_id: int, request: Request, db: Session = Depends(get_db)):
    """Delete a goal"""
    goal = db.query(Goal).filter(Goal.id == goal_id).first()
    if goal:
        db.delete(goal)
        db.commit()

    return templates.TemplateResponse(
        request,
        "goals/deleted.html",
        {},
        headers={"HX-Redirect": "/goals/"},
    )
