import os
import threading
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from backend.database import SessionLocal, get_db
from backend.models import DailyActivity, DailySummary
from backend.services.github_service import get_gh_cli_token

router = APIRouter(prefix="/daily-report", tags=["daily-report"])
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))


def get_today_report_from_db(db: Session) -> dict:
    """Get today's report data from database (today only — bounded upper date)."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    activities = (
        db.query(DailyActivity)
        .filter(
            DailyActivity.activity_date >= today_start,
            DailyActivity.activity_date < today_end,
        )
        .all()
    )

    summary = (
        db.query(DailySummary)
        .filter(
            DailySummary.summary_date >= today_start,
            DailySummary.summary_date < today_end,
        )
        .first()
    )

    if not activities and not summary:
        return None

    report = {
        "date": date.today().isoformat(),
        "github": {
            "commits": [],
            "pull_requests": [],
            "issues": [],
            "reviews": [],
        },
        "jira": {
            "assigned_issues": [],
            "worked_issues": [],
            "transitions": [],
            "comments": [],
        },
        "summary": {},
        "errors": [],
    }

    for activity in activities:
        if activity.source == "github":
            if activity.activity_type == "commit":
                report["github"]["commits"].append(
                    {
                        "sha": activity.external_id,
                        "message": activity.title,
                        "url": activity.url,
                        "repo": activity.repository,
                    }
                )
            elif activity.activity_type == "pull_request":
                report["github"]["pull_requests"].append(
                    {
                        "number": activity.external_id,
                        "title": activity.title,
                        "state": activity.status,
                        "url": activity.url,
                        "repo": activity.repository,
                    }
                )
            elif activity.activity_type == "issue":
                report["github"]["issues"].append(
                    {
                        "number": activity.external_id,
                        "title": activity.title,
                        "state": activity.status,
                        "url": activity.url,
                        "repo": activity.repository,
                    }
                )
            elif activity.activity_type == "review":
                report["github"]["reviews"].append(
                    {
                        "pr_number": activity.external_id,
                        "pr_title": activity.title,
                        "state": activity.status,
                        "url": activity.url,
                        "repo": activity.repository,
                    }
                )
        elif activity.source == "jira":
            if activity.activity_type == "assigned_issue":
                report["jira"]["assigned_issues"].append(
                    {
                        "key": activity.external_id,
                        "summary": activity.title,
                        "status": activity.status,
                        "url": activity.url,
                    }
                )
            elif activity.activity_type == "transition":
                report["jira"]["transitions"].append(
                    {
                        "issue_key": activity.external_id,
                        "title": activity.title,
                        "to_status": activity.status,
                    }
                )

    if summary:
        report["summary"] = {
            "total_commits": summary.github_commits,
            "total_prs": summary.github_prs,
            "total_issues": summary.github_issues,
            "total_reviews": summary.github_reviews,
            "jira_assigned": summary.jira_assigned,
            "jira_worked": summary.jira_worked,
            "jira_transitions": summary.jira_transitions,
            "jira_comments": summary.jira_comments,
        }
    else:
        report["summary"] = {
            "total_commits": len(report["github"]["commits"]),
            "total_prs": len(report["github"]["pull_requests"]),
            "total_issues": len(report["github"]["issues"]),
            "total_reviews": len(report["github"]["reviews"]),
            "jira_assigned": len(report["jira"]["assigned_issues"]),
            "jira_worked": 0,
            "jira_transitions": len(report["jira"]["transitions"]),
            "jira_comments": 0,
        }

    return report


def _get_sync_info(db: Session) -> dict:
    """Return last-synced info from the single BackgroundSync SyncState row."""
    from backend.models import SyncState

    state = db.query(SyncState).filter(SyncState.source == "background").first()
    if state and state.last_sync_at:
        last_sync_at = state.last_sync_at
        return {
            "last_sync_at": last_sync_at.strftime("%Y-%m-%d %H:%M:%S"),
            "last_sync_date": last_sync_at.date().isoformat(),
            "total_syncs": state.total_syncs,
            "is_today": last_sync_at.date() == date.today(),
        }
    return {
        "last_sync_at": None,
        "last_sync_date": None,
        "total_syncs": 0,
        "is_today": False,
    }


@router.get("/", response_class=HTMLResponse)
def daily_report_page(request: Request, db: Session = Depends(get_db)):
    """Display daily report page with sync status and today's data."""
    sync_info = _get_sync_info(db)

    github_configured = get_gh_cli_token() is not None or os.getenv("GITHUB_TOKEN") is not None
    jira_configured = all(
        [os.getenv("JIRA_SERVER"), os.getenv("JIRA_EMAIL"), os.getenv("JIRA_API_TOKEN")]
    )

    today_report = get_today_report_from_db(db)

    return templates.TemplateResponse(
        request,
        "daily_report/index.html",
        {
            # Keep both keys so the template works without changes for now
            "github_info": sync_info,
            "jira_info": sync_info,
            "github_configured": github_configured,
            "jira_configured": jira_configured,
            "today": date.today().strftime("%Y-%m-%d"),
            "report": today_report,
        },
    )


def _run_sync_background(force_full: bool):
    """Run BackgroundSync in a background thread (fire-and-forget from the route)."""
    from backend.services.background_sync import BackgroundSync, DEFAULT_START

    db = SessionLocal()
    try:
        sync = BackgroundSync(db)
        today = date.today()
        if force_full:
            sync.run_full_sync(start_date=DEFAULT_START, end_date=today)
        else:
            sync.run_full_sync(end_date=today)
    except Exception as e:
        print(f"[daily-report sync] Failed: {e}")
    finally:
        db.close()


@router.post("/sync", response_class=HTMLResponse)
async def sync_now(request: Request, force_full: bool = Form(False), db: Session = Depends(get_db)):
    """Trigger BackgroundSync (incremental or full) and return updated report."""
    from backend.services.background_sync import _sync_lock

    # If a sync is already running, skip rather than queue a second one
    if _sync_lock.locked():
        sync_info = _get_sync_info(db)
        today_report = get_today_report_from_db(db)
        return templates.TemplateResponse(
            request,
            "daily_report/report_content.html",
            {
                "report": today_report,
                "formatted_report": "Sync already in progress — check back in a moment.",
                "github_info": sync_info,
                "jira_info": sync_info,
                "sync_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        )

    # Run sync synchronously on this request so the response reflects fresh data.
    # (The lock prevents concurrent syncs; startup sync runs in its own thread.)
    from backend.services.background_sync import BackgroundSync, DEFAULT_START

    sync = BackgroundSync(db)
    today = date.today()
    if force_full:
        sync.run_full_sync(start_date=DEFAULT_START, end_date=today)
    else:
        sync.run_full_sync(end_date=today)

    sync_info = _get_sync_info(db)
    today_report = get_today_report_from_db(db)

    return templates.TemplateResponse(
        request,
        "daily_report/report_content.html",
        {
            "report": today_report,
            "formatted_report": "",
            "github_info": sync_info,
            "jira_info": sync_info,
            "sync_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
    )


@router.get("/status", response_class=JSONResponse)
def get_sync_status(db: Session = Depends(get_db)):
    """Get current sync status as JSON."""
    sync_info = _get_sync_info(db)
    return {"github": sync_info, "jira": sync_info}


@router.post("/reset/{source}", response_class=HTMLResponse)
def reset_sync_state(source: str, request: Request, db: Session = Depends(get_db)):
    """Reset sync state (forces full re-sync next time)."""
    if source not in ["github", "jira", "background"]:
        return HTMLResponse(content="Invalid source", status_code=400)

    from backend.models import SyncState

    state = db.query(SyncState).filter(SyncState.source == "background").first()
    if state:
        state.last_sync_at = None
        state.total_syncs = 0
        db.commit()

    sync_info = _get_sync_info(db)

    return templates.TemplateResponse(
        request,
        "daily_report/index.html",
        {
            "github_info": sync_info,
            "jira_info": sync_info,
            "github_configured": get_gh_cli_token() is not None
            or os.getenv("GITHUB_TOKEN") is not None,
            "jira_configured": all(
                [
                    os.getenv("JIRA_SERVER"),
                    os.getenv("JIRA_EMAIL"),
                    os.getenv("JIRA_API_TOKEN"),
                ]
            ),
            "today": date.today().strftime("%Y-%m-%d"),
            "message": "Sync state reset. Next sync will be a full history rebuild.",
        },
    )
