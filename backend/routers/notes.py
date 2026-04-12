import os
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import ExternalLink, Note, Project
from backend.models.models import LinkType

router = APIRouter(prefix="/notes", tags=["notes"])
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))


# ── Pydantic models for JSON API ──────────────────────────────────────────────


class NoteCreate(BaseModel):
    title: str
    content: str = ""
    tags: str = ""
    project_id: Optional[int] = None
    task_id: Optional[int] = None


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[str] = None
    project_id: Optional[int] = None
    task_id: Optional[int] = None


# ── JSON API endpoints ────────────────────────────────────────────────────────


@router.post("/api", response_class=JSONResponse)
def create_note_api(
    note_data: NoteCreate,
    db: Session = Depends(get_db),
):
    """
    Create a new note via JSON API.

    Request body:
    {
        "title": "Note title",
        "content": "Note content (optional)",
        "tags": "comma,separated,tags (optional)",
        "project_id": 1 (optional)
    }
    """
    note = Note(
        title=note_data.title,
        content=note_data.content,
        tags=note_data.tags,
        project_id=note_data.project_id,
    )
    db.add(note)
    db.commit()
    db.refresh(note)

    return {
        "success": True,
        "note": {
            "id": note.id,
            "title": note.title,
            "content": note.content,
            "tags": note.tags,
            "project_id": note.project_id,
            "created_at": note.created_at.isoformat() if note.created_at else None,
            "updated_at": note.updated_at.isoformat() if note.updated_at else None,
        },
    }


@router.get("/api", response_class=JSONResponse)
def list_notes_api(
    q: str = "",
    project_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """
    List notes via JSON API with optional search and project filter.
    """
    query = db.query(Note)
    if q:
        query = query.filter(
            Note.title.contains(q) | Note.content.contains(q) | Note.tags.contains(q)
        )
    if project_id:
        query = query.filter(Note.project_id == project_id)

    notes = query.order_by(Note.updated_at.desc()).all()

    return {
        "notes": [
            {
                "id": n.id,
                "title": n.title,
                "content": n.content,
                "tags": n.tags,
                "project_id": n.project_id,
                "task_id": n.task_id,
                "created_at": n.created_at.isoformat() if n.created_at else None,
                "updated_at": n.updated_at.isoformat() if n.updated_at else None,
            }
            for n in notes
        ]
    }


@router.get("/api/{note_id}", response_class=JSONResponse)
def get_note_api(
    note_id: int,
    db: Session = Depends(get_db),
):
    """Get a single note by ID."""
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        return JSONResponse({"success": False, "error": "Note not found"}, status_code=404)

    return {
        "success": True,
        "note": {
            "id": note.id,
            "title": note.title,
            "content": note.content,
            "tags": note.tags,
            "project_id": note.project_id,
            "task_id": note.task_id,
            "created_at": note.created_at.isoformat() if note.created_at else None,
            "updated_at": note.updated_at.isoformat() if note.updated_at else None,
        },
    }


@router.put("/api/{note_id}", response_class=JSONResponse)
def update_note_api(
    note_id: int,
    note_data: NoteUpdate,
    db: Session = Depends(get_db),
):
    """Update an existing note. Only provided fields will be updated."""
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        return JSONResponse({"success": False, "error": "Note not found"}, status_code=404)

    if note_data.title is not None:
        note.title = note_data.title
    if note_data.content is not None:
        note.content = note_data.content
    if note_data.tags is not None:
        note.tags = note_data.tags
    if note_data.project_id is not None:
        note.project_id = note_data.project_id if note_data.project_id else None
    if note_data.task_id is not None:
        note.task_id = note_data.task_id if note_data.task_id else None

    db.commit()
    db.refresh(note)

    return {
        "success": True,
        "note": {
            "id": note.id,
            "title": note.title,
            "content": note.content,
            "tags": note.tags,
            "project_id": note.project_id,
            "task_id": note.task_id,
            "created_at": note.created_at.isoformat() if note.created_at else None,
            "updated_at": note.updated_at.isoformat() if note.updated_at else None,
        },
    }


@router.delete("/api/{note_id}", response_class=JSONResponse)
def delete_note_api(
    note_id: int,
    db: Session = Depends(get_db),
):
    """Delete a note by ID."""
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        return JSONResponse({"success": False, "error": "Note not found"}, status_code=404)

    db.delete(note)
    db.commit()

    return {"success": True, "message": f"Note {note_id} deleted"}


# ── HTML endpoints (existing) ─────────────────────────────────────────────────


@router.get("/", response_class=HTMLResponse)
def list_notes(request: Request, q: str = "", db: Session = Depends(get_db)):
    query = db.query(Note)
    if q:
        query = query.filter(
            Note.title.contains(q) | Note.content.contains(q) | Note.tags.contains(q)
        )
    notes = query.order_by(Note.updated_at.desc()).all()
    projects = db.query(Project).order_by(Project.name).all()
    return templates.TemplateResponse(
        request, "notes/list.html", {"notes": notes, "projects": projects, "q": q}
    )


@router.get("/new", response_class=HTMLResponse)
def new_note_form(
    request: Request, project_id: Optional[int] = None, db: Session = Depends(get_db)
):
    projects = db.query(Project).order_by(Project.name).all()
    return templates.TemplateResponse(
        request,
        "notes/form.html",
        {
            "note": None,
            "projects": projects,
            "preselected_project_id": project_id,
        },
    )


@router.post("/new", response_class=HTMLResponse)
def create_note(
    request: Request,
    title: str = Form(...),
    content: str = Form(""),
    tags: str = Form(""),
    project_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    note = Note(title=title, content=content, tags=tags, project_id=project_id or None)
    db.add(note)
    db.commit()
    db.refresh(note)
    notes = db.query(Note).order_by(Note.updated_at.desc()).all()
    projects = db.query(Project).order_by(Project.name).all()
    return templates.TemplateResponse(
        request, "notes/list.html", {"notes": notes, "projects": projects, "q": ""}
    )


@router.get("/{note_id}", response_class=HTMLResponse)
def get_note(note_id: int, request: Request, db: Session = Depends(get_db)):
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    projects = db.query(Project).order_by(Project.name).all()
    links = (
        db.query(ExternalLink)
        .filter(ExternalLink.note_id == note_id)
        .order_by(ExternalLink.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        request,
        "notes/detail.html",
        {
            "note": note,
            "projects": projects,
            "links": links,
            "link_types": list(LinkType),
        },
    )


@router.post("/{note_id}/edit", response_class=HTMLResponse)
def edit_note(
    note_id: int,
    request: Request,
    title: str = Form(...),
    content: str = Form(""),
    tags: str = Form(""),
    project_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    note.title = title
    note.content = content
    note.tags = tags
    note.project_id = project_id or None
    db.commit()
    db.refresh(note)
    projects = db.query(Project).order_by(Project.name).all()
    links = (
        db.query(ExternalLink)
        .filter(ExternalLink.note_id == note_id)
        .order_by(ExternalLink.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        request,
        "notes/detail.html",
        {
            "note": note,
            "projects": projects,
            "links": links,
            "link_types": list(LinkType),
        },
    )


@router.post("/{note_id}/delete", response_class=HTMLResponse)
def delete_note(note_id: int, request: Request, db: Session = Depends(get_db)):
    note = db.query(Note).filter(Note.id == note_id).first()
    if note:
        db.delete(note)
        db.commit()
    notes = db.query(Note).order_by(Note.updated_at.desc()).all()
    projects = db.query(Project).order_by(Project.name).all()
    return templates.TemplateResponse(
        request, "notes/list.html", {"notes": notes, "projects": projects, "q": ""}
    )
