import os
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import ActionItem, ExternalLink, MeetingNote, Project
from backend.models.models import LinkType

router = APIRouter(prefix="/meetings", tags=["meetings"])
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))


# ── Pydantic models for JSON API ──────────────────────────────────────────────


class MeetingCreate(BaseModel):
    title: str
    meeting_date: str  # ISO format: "2026-04-15"
    attendees: str = ""
    summary: str = ""
    notes: str = ""
    project_id: Optional[int] = None


class MeetingUpdate(BaseModel):
    title: Optional[str] = None
    meeting_date: Optional[str] = None
    attendees: Optional[str] = None
    summary: Optional[str] = None
    notes: Optional[str] = None
    project_id: Optional[int] = None


class ActionItemCreate(BaseModel):
    description: str
    owner: str = ""
    due_date: str = ""  # ISO format


class ActionItemUpdate(BaseModel):
    description: Optional[str] = None
    owner: Optional[str] = None
    due_date: Optional[str] = None
    is_done: Optional[bool] = None


def _meeting_to_dict(meeting: MeetingNote) -> dict:
    """Convert MeetingNote model to dictionary for JSON response"""
    return {
        "id": meeting.id,
        "title": meeting.title,
        "meeting_date": meeting.meeting_date,
        "attendees": meeting.attendees,
        "summary": meeting.summary,
        "notes": meeting.notes,
        "project_id": meeting.project_id,
        "action_items": [
            {
                "id": item.id,
                "description": item.description,
                "owner": item.owner,
                "due_date": item.due_date,
                "is_done": item.is_done,
            }
            for item in meeting.action_items
        ]
        if meeting.action_items
        else [],
        "created_at": meeting.created_at.isoformat() if meeting.created_at else None,
        "updated_at": meeting.updated_at.isoformat() if meeting.updated_at else None,
    }


# ── JSON API endpoints ────────────────────────────────────────────────────────


@router.get("/api", response_class=JSONResponse)
def list_meetings_api(
    project_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """List all meetings with optional project filter."""
    query = db.query(MeetingNote)

    if project_id:
        query = query.filter(MeetingNote.project_id == project_id)

    meetings = query.order_by(MeetingNote.meeting_date.desc()).all()

    return {"meetings": [_meeting_to_dict(m) for m in meetings]}


@router.get("/api/{meeting_id}", response_class=JSONResponse)
def get_meeting_api(
    meeting_id: int,
    db: Session = Depends(get_db),
):
    """Get a single meeting by ID with action items."""
    meeting = db.query(MeetingNote).filter(MeetingNote.id == meeting_id).first()
    if not meeting:
        return JSONResponse({"success": False, "error": "Meeting not found"}, status_code=404)

    return {"success": True, "meeting": _meeting_to_dict(meeting)}


@router.post("/api", response_class=JSONResponse)
def create_meeting_api(
    meeting_data: MeetingCreate,
    db: Session = Depends(get_db),
):
    """
    Create a new meeting.

    Request body:
    {
        "title": "Meeting title",
        "meeting_date": "2026-04-15",
        "attendees": "John, Jane",
        "summary": "Summary",
        "notes": "Detailed notes",
        "project_id": 1 (optional)
    }
    """
    meeting = MeetingNote(
        title=meeting_data.title,
        meeting_date=meeting_data.meeting_date,
        attendees=meeting_data.attendees,
        summary=meeting_data.summary,
        notes=meeting_data.notes,
        project_id=meeting_data.project_id,
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    return {"success": True, "meeting": _meeting_to_dict(meeting)}


@router.put("/api/{meeting_id}", response_class=JSONResponse)
def update_meeting_api(
    meeting_id: int,
    meeting_data: MeetingUpdate,
    db: Session = Depends(get_db),
):
    """Update an existing meeting. Only provided fields will be updated."""
    meeting = db.query(MeetingNote).filter(MeetingNote.id == meeting_id).first()
    if not meeting:
        return JSONResponse({"success": False, "error": "Meeting not found"}, status_code=404)

    if meeting_data.title is not None:
        meeting.title = meeting_data.title
    if meeting_data.meeting_date is not None:
        meeting.meeting_date = meeting_data.meeting_date
    if meeting_data.attendees is not None:
        meeting.attendees = meeting_data.attendees
    if meeting_data.summary is not None:
        meeting.summary = meeting_data.summary
    if meeting_data.notes is not None:
        meeting.notes = meeting_data.notes
    if meeting_data.project_id is not None:
        meeting.project_id = meeting_data.project_id if meeting_data.project_id else None

    db.commit()
    db.refresh(meeting)

    return {"success": True, "meeting": _meeting_to_dict(meeting)}


@router.delete("/api/{meeting_id}", response_class=JSONResponse)
def delete_meeting_api(
    meeting_id: int,
    db: Session = Depends(get_db),
):
    """Delete a meeting by ID."""
    meeting = db.query(MeetingNote).filter(MeetingNote.id == meeting_id).first()
    if not meeting:
        return JSONResponse({"success": False, "error": "Meeting not found"}, status_code=404)

    db.delete(meeting)
    db.commit()

    return {"success": True, "message": f"Meeting {meeting_id} deleted"}


@router.post("/api/{meeting_id}/action-items", response_class=JSONResponse)
def add_action_item_api(
    meeting_id: int,
    item_data: ActionItemCreate,
    db: Session = Depends(get_db),
):
    """
    Add an action item to a meeting.

    Request body:
    {
        "description": "Action item description",
        "owner": "John",
        "due_date": "2026-04-20"
    }
    """
    meeting = db.query(MeetingNote).filter(MeetingNote.id == meeting_id).first()
    if not meeting:
        return JSONResponse({"success": False, "error": "Meeting not found"}, status_code=404)

    item = ActionItem(
        description=item_data.description,
        owner=item_data.owner,
        due_date=item_data.due_date,
        meeting_id=meeting_id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    return {
        "success": True,
        "action_item": {
            "id": item.id,
            "description": item.description,
            "owner": item.owner,
            "due_date": item.due_date,
            "is_done": item.is_done,
            "meeting_id": item.meeting_id,
        },
    }


@router.put("/api/{meeting_id}/action-items/{item_id}", response_class=JSONResponse)
def update_action_item_api(
    meeting_id: int,
    item_id: int,
    item_data: ActionItemUpdate,
    db: Session = Depends(get_db),
):
    """Update an action item."""
    item = (
        db.query(ActionItem)
        .filter(ActionItem.id == item_id, ActionItem.meeting_id == meeting_id)
        .first()
    )
    if not item:
        return JSONResponse({"success": False, "error": "Action item not found"}, status_code=404)

    if item_data.description is not None:
        item.description = item_data.description
    if item_data.owner is not None:
        item.owner = item_data.owner
    if item_data.due_date is not None:
        item.due_date = item_data.due_date
    if item_data.is_done is not None:
        item.is_done = item_data.is_done

    db.commit()
    db.refresh(item)

    return {
        "success": True,
        "action_item": {
            "id": item.id,
            "description": item.description,
            "owner": item.owner,
            "due_date": item.due_date,
            "is_done": item.is_done,
        },
    }


@router.post("/api/{meeting_id}/action-items/{item_id}/toggle", response_class=JSONResponse)
def toggle_action_item_api(
    meeting_id: int,
    item_id: int,
    db: Session = Depends(get_db),
):
    """Toggle action item done status."""
    item = (
        db.query(ActionItem)
        .filter(ActionItem.id == item_id, ActionItem.meeting_id == meeting_id)
        .first()
    )
    if not item:
        return JSONResponse({"success": False, "error": "Action item not found"}, status_code=404)

    item.is_done = not item.is_done
    db.commit()

    return {
        "success": True,
        "action_item": {
            "id": item.id,
            "is_done": item.is_done,
        },
    }


@router.delete("/api/{meeting_id}/action-items/{item_id}", response_class=JSONResponse)
def delete_action_item_api(
    meeting_id: int,
    item_id: int,
    db: Session = Depends(get_db),
):
    """Delete an action item."""
    item = (
        db.query(ActionItem)
        .filter(ActionItem.id == item_id, ActionItem.meeting_id == meeting_id)
        .first()
    )
    if not item:
        return JSONResponse({"success": False, "error": "Action item not found"}, status_code=404)

    db.delete(item)
    db.commit()

    return {"success": True, "message": f"Action item {item_id} deleted"}


# ── HTML helper ───────────────────────────────────────────────────────────────


def _list(request, db):
    meetings = db.query(MeetingNote).order_by(MeetingNote.meeting_date.desc()).all()
    projects = db.query(Project).order_by(Project.name).all()
    is_htmx = request.headers.get("HX-Request") == "true"
    template = "meetings/list_content.html" if is_htmx else "meetings/list.html"
    return templates.TemplateResponse(
        request,
        template,
        {
            "meetings": meetings,
            "projects": projects,
            "today": date.today().isoformat(),
        },
    )


def _detail(request, db, meeting):
    projects = db.query(Project).order_by(Project.name).all()
    links = (
        db.query(ExternalLink)
        .filter(ExternalLink.meeting_id == meeting.id)
        .order_by(ExternalLink.created_at.desc())
        .all()
    )
    is_htmx = request.headers.get("HX-Request") == "true"
    template = "meetings/detail_content.html" if is_htmx else "meetings/detail.html"
    return templates.TemplateResponse(
        request,
        template,
        {
            "meeting": meeting,
            "projects": projects,
            "links": links,
            "link_types": list(LinkType),
        },
    )


@router.get("/", response_class=HTMLResponse)
def list_meetings(request: Request, db: Session = Depends(get_db)):
    return _list(request, db)


@router.post("/new", response_class=HTMLResponse)
def create_meeting(
    request: Request,
    title: str = Form(...),
    meeting_date: str = Form(...),
    attendees: str = Form(""),
    summary: str = Form(""),
    notes: str = Form(""),
    project_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    meeting = MeetingNote(
        title=title,
        meeting_date=meeting_date,
        attendees=attendees,
        summary=summary,
        notes=notes,
        project_id=project_id or None,
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    return _detail(request, db, meeting)


@router.get("/{meeting_id}", response_class=HTMLResponse)
def get_meeting(meeting_id: int, request: Request, db: Session = Depends(get_db)):
    meeting = db.query(MeetingNote).filter(MeetingNote.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return _detail(request, db, meeting)


@router.post("/{meeting_id}/edit", response_class=HTMLResponse)
def edit_meeting(
    meeting_id: int,
    request: Request,
    title: str = Form(...),
    meeting_date: str = Form(...),
    attendees: str = Form(""),
    summary: str = Form(""),
    notes: str = Form(""),
    project_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    meeting = db.query(MeetingNote).filter(MeetingNote.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting.title = title
    meeting.meeting_date = meeting_date
    meeting.attendees = attendees
    meeting.summary = summary
    meeting.notes = notes
    meeting.project_id = project_id or None
    db.commit()
    db.refresh(meeting)
    return _detail(request, db, meeting)


@router.post("/{meeting_id}/delete", response_class=HTMLResponse)
def delete_meeting(meeting_id: int, request: Request, db: Session = Depends(get_db)):
    meeting = db.query(MeetingNote).filter(MeetingNote.id == meeting_id).first()
    if meeting:
        db.delete(meeting)
        db.commit()
    return _list(request, db)


@router.post("/{meeting_id}/action-items/new", response_class=HTMLResponse)
def add_action_item(
    meeting_id: int,
    request: Request,
    description: str = Form(...),
    owner: str = Form(""),
    due_date: str = Form(""),
    db: Session = Depends(get_db),
):
    meeting = db.query(MeetingNote).filter(MeetingNote.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    item = ActionItem(
        description=description, owner=owner, due_date=due_date, meeting_id=meeting_id
    )
    db.add(item)
    db.commit()
    db.refresh(meeting)
    return _detail(request, db, meeting)


@router.post("/{meeting_id}/action-items/{item_id}/toggle", response_class=HTMLResponse)
def toggle_action_item(
    meeting_id: int, item_id: int, request: Request, db: Session = Depends(get_db)
):
    item = db.query(ActionItem).filter(ActionItem.id == item_id).first()
    if item:
        item.is_done = not item.is_done
        db.commit()
    meeting = db.query(MeetingNote).filter(MeetingNote.id == meeting_id).first()
    return _detail(request, db, meeting)
