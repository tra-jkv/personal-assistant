import os
from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import StandupLog

router = APIRouter(prefix="/standup", tags=["standup"])
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))


def _render(request, db, saved=False):
    today = date.today().isoformat()
    log = db.query(StandupLog).filter(StandupLog.log_date == today).first()
    history = (
        db.query(StandupLog)
        .filter(StandupLog.log_date != today)
        .order_by(StandupLog.log_date.desc())
        .limit(14)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "standup/index.html",
        {
            "today": today,
            "log": log,
            "history": history,
            "saved": saved,
        },
    )


@router.get("/", response_class=HTMLResponse)
def standup_page(request: Request, db: Session = Depends(get_db)):
    return _render(request, db)


@router.post("/save", response_class=HTMLResponse)
def save_standup(
    request: Request,
    log_date: str = Form(...),
    did: str = Form(""),
    doing: str = Form(""),
    blockers: str = Form(""),
    db: Session = Depends(get_db),
):
    log = db.query(StandupLog).filter(StandupLog.log_date == log_date).first()
    if log:
        log.did = did
        log.doing = doing
        log.blockers = blockers
    else:
        log = StandupLog(log_date=log_date, did=did, doing=doing, blockers=blockers)
        db.add(log)
    db.commit()
    return _render(request, db, saved=True)
