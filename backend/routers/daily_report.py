import os
from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import DailyActivity, DailySummary
from backend.services.daily_report_sync import DailyReportSync
from backend.services.github_service import get_gh_cli_token
from backend.services.sync_manager import SyncManager

router = APIRouter(prefix="/daily-report", tags=["daily-report"])
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))


def get_today_report_from_db(db: Session) -> dict:
    """Get today's report data from database"""
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # Get today's activities
    activities = db.query(DailyActivity).filter(DailyActivity.activity_date >= today).all()

    # Get today's summary
    summary = db.query(DailySummary).filter(DailySummary.summary_date >= today).first()

    if not activities and not summary:
        return None

    # Build report structure similar to sync results
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

    # Populate from activities
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

    # Populate summary
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


@router.get("/", response_class=HTMLResponse)
def daily_report_page(request: Request, db: Session = Depends(get_db)):
    """Display daily report page with sync status and today's data"""
    sync_manager = SyncManager(db)

    # Get sync status for both sources
    github_info = sync_manager.get_sync_info("github")
    jira_info = sync_manager.get_sync_info("jira")

    # Check if GitHub and Jira are configured
    github_configured = get_gh_cli_token() is not None or os.getenv("GITHUB_TOKEN") is not None
    jira_configured = all(
        [os.getenv("JIRA_SERVER"), os.getenv("JIRA_EMAIL"), os.getenv("JIRA_API_TOKEN")]
    )

    # Get today's report from database (if exists)
    today_report = get_today_report_from_db(db)

    return templates.TemplateResponse(
        request,
        "daily_report/index.html",
        {
            "github_info": github_info,
            "jira_info": jira_info,
            "github_configured": github_configured,
            "jira_configured": jira_configured,
            "today": date.today().strftime("%Y-%m-%d"),
            "report": today_report,  # Pass today's report if exists
        },
    )


@router.post("/sync", response_class=HTMLResponse)
async def sync_now(request: Request, force_full: bool = Form(False), db: Session = Depends(get_db)):
    """Perform incremental sync and return updated report"""
    sync_service = DailyReportSync(db)

    # Perform sync
    report = sync_service.sync_incremental(force_full=force_full)

    # Get updated sync status
    sync_manager = SyncManager(db)
    github_info = sync_manager.get_sync_info("github")
    jira_info = sync_manager.get_sync_info("jira")

    # Format the report for display
    formatted_report = sync_service.format_report_as_text(report)

    return templates.TemplateResponse(
        request,
        "daily_report/report_content.html",
        {
            "report": report,
            "formatted_report": formatted_report,
            "github_info": github_info,
            "jira_info": jira_info,
            "sync_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
    )


@router.get("/status", response_class=JSONResponse)
def get_sync_status(db: Session = Depends(get_db)):
    """Get current sync status as JSON"""
    sync_manager = SyncManager(db)

    return {
        "github": sync_manager.get_sync_info("github"),
        "jira": sync_manager.get_sync_info("jira"),
    }


@router.post("/reset/{source}", response_class=HTMLResponse)
def reset_sync_state(source: str, request: Request, db: Session = Depends(get_db)):
    """Reset sync state for a source (forces full sync next time)"""
    if source not in ["github", "jira"]:
        return HTMLResponse(content="Invalid source", status_code=400)

    sync_manager = SyncManager(db)
    sync_manager.reset_sync_state(source)

    # Redirect back to main page
    return templates.TemplateResponse(
        request,
        "daily_report/index.html",
        {
            "github_info": sync_manager.get_sync_info("github"),
            "jira_info": sync_manager.get_sync_info("jira"),
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
            "message": f"Reset {source.upper()} sync state. Next sync will be full.",
        },
    )
