from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
import os

from backend.database import get_db
from backend.models import ExternalLink, Project, Note, MeetingNote, Task
from backend.models.models import LinkType

router = APIRouter(prefix="/links", tags=["links"])
templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "..", "templates")
)


# ── Standalone links list ─────────────────────────────────────────────────────


@router.get("/", response_class=HTMLResponse)
def list_links(
    request: Request,
    link_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(ExternalLink)
    if link_type:
        try:
            query = query.filter(ExternalLink.link_type == LinkType(link_type))
        except ValueError:
            pass
    links = query.order_by(ExternalLink.created_at.desc()).all()
    return templates.TemplateResponse(
        request,
        "links/list.html",
        {
            "links": links,
            "link_types": list(LinkType),
            "active_filter": link_type,
        },
    )


# ── Add link (generic, from standalone page) ──────────────────────────────────


@router.get("/new", response_class=HTMLResponse)
def new_link_form(
    request: Request,
    project_id: Optional[int] = None,
    note_id: Optional[int] = None,
    meeting_id: Optional[int] = None,
    task_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    projects = db.query(Project).order_by(Project.name).all()
    tasks = db.query(Task).order_by(Task.project_id, Task.title).all()
    return templates.TemplateResponse(
        request,
        "links/form.html",
        {
            "link": None,
            "link_types": list(LinkType),
            "projects": projects,
            "tasks": tasks,
            "prefill_project_id": project_id,
            "prefill_note_id": note_id,
            "prefill_meeting_id": meeting_id,
            "prefill_task_id": task_id,
        },
    )


@router.post("/new", response_class=HTMLResponse)
def create_link(
    request: Request,
    title: str = Form(...),
    url: str = Form(...),
    link_type: LinkType = Form(LinkType.other),
    description: str = Form(""),
    project_id: Optional[int] = Form(None),
    note_id: Optional[int] = Form(None),
    meeting_id: Optional[int] = Form(None),
    task_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    link = ExternalLink(
        title=title,
        url=url,
        link_type=link_type,
        description=description,
        project_id=project_id or None,
        note_id=note_id or None,
        meeting_id=meeting_id or None,
        task_id=task_id or None,
    )
    db.add(link)
    db.commit()

    # Redirect back to the parent entity if one was provided
    if task_id:
        return _task_detail(request, task_id, db)
    if project_id:
        return _project_detail(request, project_id, db)
    if note_id:
        return _note_detail(request, note_id, db)
    if meeting_id:
        return _meeting_detail(request, meeting_id, db)

    links = db.query(ExternalLink).order_by(ExternalLink.created_at.desc()).all()
    return templates.TemplateResponse(
        request,
        "links/list.html",
        {
            "links": links,
            "link_types": list(LinkType),
            "active_filter": None,
        },
    )


# ── Delete link ───────────────────────────────────────────────────────────────


@router.post("/{link_id}/delete", response_class=HTMLResponse)
def delete_link(
    link_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    link = db.query(ExternalLink).filter(ExternalLink.id == link_id).first()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    project_id = link.project_id
    note_id = link.note_id
    meeting_id = link.meeting_id
    task_id = link.task_id

    db.delete(link)
    db.commit()

    if task_id:
        return _task_detail(request, task_id, db)
    if project_id:
        return _project_detail(request, project_id, db)
    if note_id:
        return _note_detail(request, note_id, db)
    if meeting_id:
        return _meeting_detail(request, meeting_id, db)

    links = db.query(ExternalLink).order_by(ExternalLink.created_at.desc()).all()
    return templates.TemplateResponse(
        request,
        "links/list.html",
        {
            "links": links,
            "link_types": list(LinkType),
            "active_filter": None,
        },
    )


# ── Helpers to re-render parent detail pages after mutations ──────────────────


def _project_detail(request: Request, project_id: int, db: Session) -> HTMLResponse:
    from backend.models import Note, Reminder, MeetingNote
    from backend.models.models import ProjectStatus, Priority

    project = db.query(Project).filter(Project.id == project_id).first()
    notes = (
        db.query(Note)
        .filter(Note.project_id == project_id)
        .order_by(Note.updated_at.desc())
        .all()
    )
    reminders = (
        db.query(Reminder)
        .filter(Reminder.project_id == project_id)
        .order_by(Reminder.due_at)
        .all()
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
    return templates.TemplateResponse(
        request,
        "projects/detail.html",
        {
            "project": project,
            "notes": notes,
            "reminders": reminders,
            "meetings": meetings,
            "links": links,
            "statuses": list(ProjectStatus),
            "priorities": list(Priority),
            "link_types": list(LinkType),
        },
    )


def _note_detail(request: Request, note_id: int, db: Session) -> HTMLResponse:
    note = db.query(Note).filter(Note.id == note_id).first()
    links = (
        db.query(ExternalLink)
        .filter(ExternalLink.note_id == note_id)
        .order_by(ExternalLink.created_at.desc())
        .all()
    )
    projects = db.query(Project).order_by(Project.name).all()
    return templates.TemplateResponse(
        request,
        "notes/detail.html",
        {
            "note": note,
            "links": links,
            "projects": projects,
            "link_types": list(LinkType),
        },
    )


def _meeting_detail(request: Request, meeting_id: int, db: Session) -> HTMLResponse:
    meeting = db.query(MeetingNote).filter(MeetingNote.id == meeting_id).first()
    links = (
        db.query(ExternalLink)
        .filter(ExternalLink.meeting_id == meeting_id)
        .order_by(ExternalLink.created_at.desc())
        .all()
    )
    projects = db.query(Project).order_by(Project.name).all()
    return templates.TemplateResponse(
        request,
        "meetings/detail.html",
        {
            "meeting": meeting,
            "links": links,
            "projects": projects,
            "link_types": list(LinkType),
        },
    )


def _task_detail(request: Request, task_id: int, db: Session) -> HTMLResponse:
    """Return to task board filtered by the task's project"""

    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Redirect to the task board filtered by this task's project
    from backend.routers.tasks import _board_context

    ctx = _board_context(db, task.project_id)
    template = (
        "tasks/board_content.html"
        if request.headers.get("HX-Request") == "true"
        else "tasks/board.html"
    )
    return templates.TemplateResponse(request, template, ctx)
