"""
Reports Router

Unified reports page with calendar navigation for daily/monthly/quarterly views
"""

import calendar
import os
from datetime import date, datetime, timedelta
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import DailyActivity, DailySummary
from backend.services.github_service import get_gh_cli_token
from backend.services.sync_manager import SyncManager

router = APIRouter(prefix="/reports", tags=["reports"])
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))

# AI provider config
AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini")  # gemini, ollama
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")


def get_report_for_date(db: Session, target_date: date) -> dict:
    """Get report data for a specific date"""
    start = datetime.combine(target_date, datetime.min.time())
    end = start + timedelta(days=1)

    activities = (
        db.query(DailyActivity)
        .filter(DailyActivity.activity_date >= start, DailyActivity.activity_date < end)
        .all()
    )

    summary = (
        db.query(DailySummary)
        .filter(DailySummary.summary_date >= start, DailySummary.summary_date < end)
        .first()
    )

    return _build_report(activities, summary, target_date)


def get_report_for_month(db: Session, year: int, month: int) -> dict:
    """Get report data for a specific month"""
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)

    activities = (
        db.query(DailyActivity)
        .filter(DailyActivity.activity_date >= start, DailyActivity.activity_date < end)
        .all()
    )

    summaries = (
        db.query(DailySummary)
        .filter(DailySummary.summary_date >= start, DailySummary.summary_date < end)
        .all()
    )

    return _build_report_from_summaries(activities, summaries, f"{year}-{month:02d}")


def get_report_for_quarter(db: Session, year: int, quarter: int) -> dict:
    """Get report data for a specific quarter"""
    start_month = (quarter - 1) * 3 + 1
    start = datetime(year, start_month, 1)

    end_month = start_month + 3
    if end_month > 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, end_month, 1)

    activities = (
        db.query(DailyActivity)
        .filter(DailyActivity.activity_date >= start, DailyActivity.activity_date < end)
        .all()
    )

    summaries = (
        db.query(DailySummary)
        .filter(DailySummary.summary_date >= start, DailySummary.summary_date < end)
        .all()
    )

    return _build_report_from_summaries(activities, summaries, f"Q{quarter} {year}")


def get_report_for_year(db: Session, year: int) -> dict:
    """Aggregate all data needed for the yearly recap."""
    from sqlalchemy import extract, func

    from backend.models import Goal, Task
    from backend.routers.goals import calculate_goal_progress

    start = datetime(year, 1, 1)
    end = datetime(year + 1, 1, 1)

    # ── Activity stats ────────────────────────────────────────────────────────
    activities = (
        db.query(DailyActivity)
        .filter(DailyActivity.activity_date >= start, DailyActivity.activity_date < end)
        .all()
    )

    commits = [a for a in activities if a.activity_type == "commit"]
    prs = [a for a in activities if a.activity_type == "pull_request"]
    reviews = [a for a in activities if a.activity_type == "review"]

    # Unique repos from commits + PRs
    repos = sorted({a.repository for a in commits + prs if a.repository})

    # Month-by-month breakdown
    monthly = {}
    for m in range(1, 13):
        monthly[m] = {
            "commits": 0,
            "prs": 0,
            "reviews": 0,
            "label": calendar.month_abbr[m],
        }
    for a in activities:
        if not a.activity_date:
            continue
        m = a.activity_date.month
        if a.activity_type == "commit":
            monthly[m]["commits"] += 1
        elif a.activity_type == "pull_request":
            monthly[m]["prs"] += 1
        elif a.activity_type == "review":
            monthly[m]["reviews"] += 1

    # Busiest month
    busiest_month = max(
        monthly.items(),
        key=lambda x: x[1]["commits"] + x[1]["prs"] + x[1]["reviews"],
        default=(None, None),
    )

    # ── Task stats ────────────────────────────────────────────────────────────
    cancelled_statuses = ["cancelled", "Cancelled"]
    done_statuses = ["done", "Done", "closed", "Closed", "resolved", "Resolved"]

    year_filter = (
        extract(
            "year",
            func.coalesce(Task.jira_updated_at, Task.updated_at),
        )
        == year
    )

    all_tasks = db.query(Task).filter(Task.status.notin_(cancelled_statuses), year_filter).all()
    done_tasks = [t for t in all_tasks if t.status in done_statuses]

    # Tasks by project
    tasks_by_project = {}
    for t in all_tasks:
        proj = t.project.name if t.project else "Unlinked"
        tasks_by_project.setdefault(proj, {"total": 0, "done": 0})
        tasks_by_project[proj]["total"] += 1
        if t.status in done_statuses:
            tasks_by_project[proj]["done"] += 1
    tasks_by_project = dict(
        sorted(tasks_by_project.items(), key=lambda x: x[1]["total"], reverse=True)
    )

    # ── Goal stats ────────────────────────────────────────────────────────────
    goals = db.query(Goal).filter(Goal.year == year).all()

    goals_data = []
    for g in goals:
        pct, done_t, total_t = calculate_goal_progress(g, db)
        goals_data.append(
            {
                "id": g.id,
                "title": g.title,
                "status": g.status.value if g.status else "active",
                "progress_pct": pct,
                "done_tasks": done_t,
                "total_tasks": total_t,
                "projects": [p.name for p in g.projects],
            }
        )

    achieved = sum(1 for g in goals_data if g["status"] == "achieved")
    active = sum(1 for g in goals_data if g["status"] == "active")
    deferred = sum(1 for g in goals_data if g["status"] in ("deferred", "cancelled"))

    # Goal alignment
    goal_project_ids = list({p.id for g in goals for p in g.projects})
    aligned_tasks = sum(1 for t in all_tasks if t.project_id and t.project_id in goal_project_ids)
    alignment_pct = round(aligned_tasks / len(all_tasks) * 100) if all_tasks else 0

    return {
        "year": year,
        # Activity
        "total_commits": len(commits),
        "total_prs": len(prs),
        "total_reviews": len(reviews),
        "total_repos": len(repos),
        "repos": repos,
        "monthly": monthly,
        "busiest_month": busiest_month[0],
        "busiest_month_label": calendar.month_name[busiest_month[0]] if busiest_month[0] else "—",
        # Tasks
        "total_tasks": len(all_tasks),
        "done_tasks": len(done_tasks),
        "tasks_by_project": tasks_by_project,
        # Goals
        "goals": goals_data,
        "goals_achieved": achieved,
        "goals_active": active,
        "goals_deferred": deferred,
        "goals_total": len(goals_data),
        "alignment_pct": alignment_pct,
    }


def _build_report(activities, summary, report_date) -> dict:
    """Build report structure from activities and summary"""
    report = {
        "date": report_date.isoformat() if hasattr(report_date, "isoformat") else str(report_date),
        "github": {"commits": [], "pull_requests": [], "issues": [], "reviews": []},
        "jira": {"assigned_issues": [], "transitions": []},
        "summary": {},
    }

    for activity in activities:
        if activity.source == "github":
            item = {
                "id": activity.external_id,
                "title": activity.title,
                "url": activity.url,
                "repo": activity.repository,
                "status": activity.status,
            }
            if activity.activity_type == "commit":
                report["github"]["commits"].append(item)
            elif activity.activity_type == "pull_request":
                report["github"]["pull_requests"].append(item)
            elif activity.activity_type == "issue":
                report["github"]["issues"].append(item)
            elif activity.activity_type == "review":
                report["github"]["reviews"].append(item)
        elif activity.source == "jira":
            item = {
                "key": activity.external_id,
                "summary": activity.title,
                "status": activity.status,
                "url": activity.url,
            }
            if activity.activity_type == "assigned_issue":
                report["jira"]["assigned_issues"].append(item)
            elif activity.activity_type == "transition":
                report["jira"]["transitions"].append(item)

    # Always calculate from actual data, not cached summary
    report["summary"] = {
        "commits": len(report["github"]["commits"]),
        "prs": len(report["github"]["pull_requests"]),
        "issues": len(report["github"]["issues"]),
        "reviews": len(report["github"]["reviews"]),
        "jira_issues": len(report["jira"]["assigned_issues"]),
        "jira_transitions": len(report["jira"]["transitions"]),
    }

    return report


def _build_report_from_summaries(activities, summaries, period_label) -> dict:
    """Build aggregated report from activities (summaries ignored for counts)"""
    # Count directly from activities for accuracy
    commits = [a for a in activities if a.activity_type == "commit"]
    prs = [a for a in activities if a.activity_type == "pull_request"]
    reviews = [a for a in activities if a.activity_type == "review"]
    issues = [a for a in activities if a.activity_type == "issue"]
    jira_assigned = [a for a in activities if a.activity_type == "assigned_issue"]
    jira_transitions = [a for a in activities if a.activity_type == "transition"]

    report = {
        "date": period_label,
        "github": {"commits": [], "pull_requests": [], "issues": [], "reviews": []},
        "jira": {"assigned_issues": [], "transitions": []},
        "summary": {
            "commits": len(commits),
            "prs": len(prs),
            "issues": len(issues),
            "reviews": len(reviews),
            "jira_issues": len(jira_assigned),
            "jira_transitions": len(jira_transitions),
        },
    }

    # Build detailed lists from activities
    for activity in activities:
        if activity.source == "github":
            item = {
                "id": activity.external_id,
                "title": activity.title,
                "url": activity.url,
                "repo": activity.repository,
                "status": activity.status,
            }
            if activity.activity_type == "commit":
                report["github"]["commits"].append(item)
            elif activity.activity_type == "pull_request":
                report["github"]["pull_requests"].append(item)
            elif activity.activity_type == "issue":
                report["github"]["issues"].append(item)
            elif activity.activity_type == "review":
                report["github"]["reviews"].append(item)
        elif activity.source == "jira":
            item = {
                "key": activity.external_id,
                "summary": activity.title,
                "status": activity.status,
                "url": activity.url,
            }
            if activity.activity_type == "assigned_issue":
                report["jira"]["assigned_issues"].append(item)
            elif activity.activity_type == "transition":
                report["jira"]["transitions"].append(item)

    return report


def get_calendar_data(db: Session, year: int, month: int) -> dict:
    """Get calendar data with activity indicators for each day"""
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)

    # Get summaries for the month
    summaries = (
        db.query(DailySummary)
        .filter(DailySummary.summary_date >= start, DailySummary.summary_date < end)
        .all()
    )

    # Create a dict of date -> has_activity
    activity_by_day = {}
    for s in summaries:
        day = s.summary_date.day
        total = s.github_commits + s.github_prs + s.jira_assigned
        activity_by_day[day] = total

    # Build calendar
    cal = calendar.Calendar(firstweekday=0)  # Monday first
    weeks = []
    for week in cal.monthdayscalendar(year, month):
        week_data = []
        for day in week:
            if day == 0:
                week_data.append({"day": None, "activity": 0})
            else:
                week_data.append(
                    {
                        "day": day,
                        "activity": activity_by_day.get(day, 0),
                        "date": f"{year}-{month:02d}-{day:02d}",
                    }
                )
        weeks.append(week_data)

    return {
        "year": year,
        "month": month,
        "month_name": calendar.month_name[month],
        "weeks": weeks,
        "weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    }


def get_trend_data(db: Session, view: str, year: int, month: int, quarter: int) -> dict:
    """Get trend data for charts based on view type"""
    today = datetime.now().date()

    if view == "day":
        # Daily view: show last 30 days
        end_date = datetime.combine(today, datetime.max.time())
        start_date = datetime.combine(today - timedelta(days=29), datetime.min.time())

        summaries = (
            db.query(DailySummary)
            .filter(
                DailySummary.summary_date >= start_date,
                DailySummary.summary_date <= end_date,
            )
            .order_by(DailySummary.summary_date)
            .all()
        )

        # Build data for last 30 days
        labels = []
        commits = []
        prs = []
        jira = []

        summary_map = {s.summary_date.date(): s for s in summaries}

        for i in range(30):
            d = today - timedelta(days=29 - i)
            labels.append(d.strftime("%m/%d"))
            s = summary_map.get(d)
            if s:
                commits.append(s.github_commits)
                prs.append(s.github_prs)
                jira.append(s.jira_assigned)
            else:
                commits.append(0)
                prs.append(0)
                jira.append(0)

        return {
            "labels": labels,
            "datasets": [
                {"label": "Commits", "data": commits, "color": "#60a5fa"},
                {"label": "PRs", "data": prs, "color": "#22c55e"},
                {"label": "Jira Issues", "data": jira, "color": "#f97316"},
            ],
        }

    elif view == "month":
        # Monthly view: show last 12 months
        labels = []
        commits = []
        prs = []
        jira = []

        for i in range(12):
            # Calculate month offset
            m = month - 11 + i
            y = year
            while m <= 0:
                m += 12
                y -= 1
            while m > 12:
                m -= 12
                y += 1

            start = datetime(y, m, 1)
            if m == 12:
                end = datetime(y + 1, 1, 1)
            else:
                end = datetime(y, m + 1, 1)

            summaries = (
                db.query(DailySummary)
                .filter(DailySummary.summary_date >= start, DailySummary.summary_date < end)
                .all()
            )

            labels.append(f"{calendar.month_abbr[m]} {y}")
            commits.append(sum(s.github_commits for s in summaries))
            prs.append(sum(s.github_prs for s in summaries))
            jira.append(sum(s.jira_assigned for s in summaries))

        return {
            "labels": labels,
            "datasets": [
                {"label": "Commits", "data": commits, "color": "#60a5fa"},
                {"label": "PRs", "data": prs, "color": "#22c55e"},
                {"label": "Jira Issues", "data": jira, "color": "#f97316"},
            ],
        }

    else:  # quarter
        # Quarterly view: show last 8 quarters
        labels = []
        commits = []
        prs = []
        jira = []

        for i in range(8):
            q = quarter - 7 + i
            y = year
            while q <= 0:
                q += 4
                y -= 1
            while q > 4:
                q -= 4
                y += 1

            start_month = (q - 1) * 3 + 1
            start = datetime(y, start_month, 1)
            end_month = start_month + 3
            if end_month > 12:
                end = datetime(y + 1, 1, 1)
            else:
                end = datetime(y, end_month, 1)

            summaries = (
                db.query(DailySummary)
                .filter(DailySummary.summary_date >= start, DailySummary.summary_date < end)
                .all()
            )

            labels.append(f"Q{q} {y}")
            commits.append(sum(s.github_commits for s in summaries))
            prs.append(sum(s.github_prs for s in summaries))
            jira.append(sum(s.jira_assigned for s in summaries))

        return {
            "labels": labels,
            "datasets": [
                {"label": "Commits", "data": commits, "color": "#60a5fa"},
                {"label": "PRs", "data": prs, "color": "#22c55e"},
                {"label": "Jira Issues", "data": jira, "color": "#f97316"},
            ],
        }


@router.get("/", response_class=HTMLResponse)
def reports_page(
    request: Request,
    db: Session = Depends(get_db),
    view: str = Query("day", regex="^(day|month|quarter|year)$"),
    date: Optional[str] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
    quarter: Optional[int] = None,
):
    """Unified reports page with calendar navigation"""
    today = datetime.now().date()

    # Defaults
    if year is None:
        year = today.year
    if month is None:
        month = today.month
    if quarter is None:
        quarter = (month - 1) // 3 + 1

    # ── Year recap view ───────────────────────────────────────────────────────
    if view == "year":
        recap = get_report_for_year(db, year)
        available_years = list(range(today.year, 2024, -1))
        return templates.TemplateResponse(
            request,
            "reports/year.html",
            {
                "view": "year",
                "year": year,
                "recap": recap,
                "available_years": available_years,
                "today": today.isoformat(),
            },
        )

    # ── Day / Month / Quarter views ───────────────────────────────────────────
    # For day view, derive year/month from date if provided
    if view == "day" and date:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
        year = target_date.year
        month = target_date.month

    # Get calendar data for selected month
    calendar_data = get_calendar_data(db, year, month)

    if view == "day":
        target_date = datetime.strptime(date, "%Y-%m-%d").date() if date else today
        report = get_report_for_date(db, target_date)
        period_label = target_date.strftime("%A, %B %d, %Y")
        selected_date = target_date.isoformat()
    elif view == "month":
        report = get_report_for_month(db, year, month)
        period_label = f"{calendar.month_name[month]} {year}"
        selected_date = None
    else:  # quarter
        report = get_report_for_quarter(db, year, quarter)
        period_label = f"Q{quarter} {year}"
        selected_date = None

    trend_data = get_trend_data(db, view, year, month, quarter)

    github_configured = get_gh_cli_token() is not None or os.getenv("GITHUB_TOKEN") is not None
    jira_configured = all(
        [os.getenv("JIRA_SERVER"), os.getenv("JIRA_EMAIL"), os.getenv("JIRA_API_TOKEN")]
    )

    sync_manager = SyncManager(db)
    github_info = sync_manager.get_sync_info("github")
    jira_info = sync_manager.get_sync_info("jira")

    return templates.TemplateResponse(
        request,
        "reports/index.html",
        {
            "view": view,
            "report": report,
            "period_label": period_label,
            "calendar": calendar_data,
            "year": year,
            "month": month,
            "quarter": quarter,
            "selected_date": selected_date,
            "today": today.isoformat(),
            "trend_data": trend_data,
            "github_configured": github_configured,
            "jira_configured": jira_configured,
            "github_info": github_info,
            "jira_info": jira_info,
        },
    )


@router.get("/api/report", response_class=JSONResponse)
def get_report_api(
    db: Session = Depends(get_db),
    view: str = Query("day", regex="^(day|month|quarter)$"),
    date: Optional[str] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
    quarter: Optional[int] = None,
):
    """API endpoint to get report data"""
    today = datetime.now().date()

    if view == "day":
        if date:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
        else:
            target_date = today
        return get_report_for_date(db, target_date)
    elif view == "month":
        return get_report_for_month(db, year or today.year, month or today.month)
    else:
        q = quarter or ((today.month - 1) // 3 + 1)
        return get_report_for_quarter(db, year or today.year, q)


@router.get("/sync-status", response_class=JSONResponse)
def sync_status(db: Session = Depends(get_db)):
    """Check sync state — last synced date and whether a sync is currently running."""
    from backend.services.background_sync import (
        DEFAULT_START,
        BackgroundSync,
        _sync_status,
    )

    sync = BackgroundSync(db)
    last_synced = sync.get_last_synced_date()
    today = date.today()
    return JSONResponse(
        {
            "last_synced": last_synced.isoformat() if last_synced else None,
            "up_to_date": bool(last_synced and last_synced >= today),
            "default_start": DEFAULT_START.isoformat(),
            "running": _sync_status["running"],
            "progress": _sync_status["progress"],
            "started_at": _sync_status["started_at"],
        }
    )


@router.post("/sync", response_class=HTMLResponse)
async def sync_data(request: Request, db: Session = Depends(get_db)):
    """Full sync - GitHub/Jira daily activity (month-by-month) + Jira epics & tasks"""
    import asyncio

    from backend.services.background_sync import (
        BackgroundSync,
        sync_jira_epics_and_stories,
    )

    sync = BackgroundSync(db)
    today = date.today()

    try:
        # Run GitHub/Jira daily activity sync month-by-month in thread pool
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, sync.run_full_sync, None, today)

        last_synced = sync.get_last_synced_date()
        activity_msg = (
            f"Activity synced up to {last_synced}." if last_synced else "Activity sync complete."
        )

        # Sync Jira epics + tasks
        await loop.run_in_executor(None, sync_jira_epics_and_stories, None)

        from backend.models import Epic, Task

        epic_count = db.query(Epic).count()
        task_count = db.query(Task).count()
        epics_msg = f"Epics & tasks: {epic_count} epics, {task_count} tasks synced."

        return f"""<div class="sync-result success">
            {activity_msg}<br>{epics_msg}
        </div>"""

    except Exception as e:
        return f"""<div class="sync-result error">Sync failed: {str(e)}</div>"""


def build_activity_context(
    db: Session,
    view: str,
    target_date: date = None,
    year: int = None,
    month: int = None,
    quarter: int = None,
) -> str:
    """Build context from activities for AI summary"""
    today = datetime.now().date()

    if view == "day":
        if target_date is None:
            target_date = today
        start = datetime.combine(target_date, datetime.min.time())
        end = start + timedelta(days=1)
        period_label = target_date.strftime("%A, %B %d, %Y")
    elif view == "month":
        if year is None:
            year = today.year
        if month is None:
            month = today.month
        start = datetime(year, month, 1)
        if month == 12:
            end = datetime(year + 1, 1, 1)
        else:
            end = datetime(year, month + 1, 1)
        period_label = f"{calendar.month_name[month]} {year}"
    else:  # quarter
        if year is None:
            year = today.year
        if quarter is None:
            quarter = (today.month - 1) // 3 + 1
        start_month = (quarter - 1) * 3 + 1
        start = datetime(year, start_month, 1)
        end_month = start_month + 3
        if end_month > 12:
            end = datetime(year + 1, 1, 1)
        else:
            end = datetime(year, end_month, 1)
        period_label = f"Q{quarter} {year}"

    # Get activities for the period
    activities = (
        db.query(DailyActivity)
        .filter(DailyActivity.activity_date >= start, DailyActivity.activity_date < end)
        .order_by(DailyActivity.activity_date.desc())
        .all()
    )

    lines = [f"Period: {period_label}"]

    # Group all activities by repository/project
    projects = {}
    jira_issues = []

    for a in activities:
        if a.activity_type == "assigned_issue":
            jira_issues.append(a)
        else:
            repo = a.repository or "Other"
            if repo not in projects:
                projects[repo] = {"prs": [], "commits": [], "reviews": []}
            if a.activity_type == "pull_request":
                projects[repo]["prs"].append(a)
            elif a.activity_type == "commit":
                projects[repo]["commits"].append(a)
            elif a.activity_type == "review":
                projects[repo]["reviews"].append(a)

    # Calculate stats
    total_prs = sum(len(p["prs"]) for p in projects.values())
    total_reviews = sum(len(p["reviews"]) for p in projects.values())
    total_commits = sum(len(p["commits"]) for p in projects.values())

    # Send stats
    lines.append(
        f"\nStats: {total_prs} PRs, {total_reviews} reviews, {total_commits} commits, {len(jira_issues)} issues"
    )
    lines.append(f"Repos: {len(projects)}")

    # For day view: show individual PR titles (small volume, details matter)
    # For month/quarter: show repo-level summary to drive theme-based analysis
    if view == "day":
        top_repos = sorted(projects.items(), key=lambda x: len(x[1]["prs"]), reverse=True)[:10]
        if top_repos:
            lines.append("\nWork breakdown:")
            for repo, data in top_repos:
                for pr in data["prs"]:
                    lines.append(f"- [{repo}] {pr.title}")
                for commit in data["commits"][:3]:
                    lines.append(f"- [{repo}] commit: {commit.title}")
    else:
        # Month/quarter: repo-level activity counts + a few representative PR titles
        top_repos = sorted(
            projects.items(),
            key=lambda x: len(x[1]["prs"]) + len(x[1]["commits"]),
            reverse=True,
        )[:10]
        if top_repos:
            lines.append("\nMost active repos (PRs / commits / reviews):")
            for repo, data in top_repos:
                lines.append(
                    f"- {repo}: {len(data['prs'])} PRs, {len(data['commits'])} commits, {len(data['reviews'])} reviews"
                )
            # Sample PR titles for pattern recognition — not for individual callout
            lines.append("\nSample PR titles (for theme inference only):")
            for repo, data in top_repos[:5]:
                for pr in data["prs"][:2]:
                    lines.append(f"  [{repo}] {pr.title}")

    return "\n".join(lines)


@router.post("/ai-yearly-recap", response_class=HTMLResponse)
async def generate_yearly_recap(
    request: Request,
    db: Session = Depends(get_db),
    year: int = Query(default=None),
):
    """Generate AI narrative for the yearly recap."""
    if year is None:
        year = datetime.now().year

    recap = get_report_for_year(db, year)

    if recap["total_commits"] == 0 and recap["total_tasks"] == 0 and not recap["goals"]:
        return """<div class="ai-summary-content">
            <p class="text-muted">No data found for this year. Sync data first.</p>
        </div>"""

    # Build structured context for Gemini
    goal_lines = []
    for g in recap["goals"]:
        projects = ", ".join(g["projects"]) if g["projects"] else "no projects linked"
        goal_lines.append(
            f'- "{g["title"]}" — status: {g["status"]}, progress: {g["progress_pct"]}% '
            f"({g['done_tasks']}/{g['total_tasks']} tasks done), projects: {projects}"
        )

    monthly_lines = []
    for m, data in recap["monthly"].items():
        total = data["commits"] + data["prs"] + data["reviews"]
        if total > 0:
            monthly_lines.append(
                f"  {data['label']}: {data['commits']} commits, {data['prs']} PRs, {data['reviews']} reviews"
            )

    top_projects = list(recap["tasks_by_project"].items())[:5]
    project_lines = [f"  - {name}: {d['done']}/{d['total']} tasks done" for name, d in top_projects]

    context = f"""Year: {year}

GOALS ({recap["goals_total"]} total):
{chr(10).join(goal_lines) if goal_lines else "  No goals set for this year."}
Goal alignment: {recap["alignment_pct"]}% of tasks tied to a goal.

WORK OUTPUT:
- Commits: {recap["total_commits"]} across {recap["total_repos"]} repos
- Pull requests: {recap["total_prs"]}
- Code reviews: {recap["total_reviews"]}
- Tasks completed: {recap["done_tasks"]} of {recap["total_tasks"]}
- Busiest month: {recap["busiest_month_label"]}

Monthly activity:
{chr(10).join(monthly_lines) if monthly_lines else "  No activity data."}

Top projects by tasks:
{chr(10).join(project_lines) if project_lines else "  No project data."}

Repos worked in: {", ".join(recap["repos"][:15]) if recap["repos"] else "none"}"""

    system_prompt = f"""You are writing a yearly recap for an engineer covering {year}.
Be honest, direct, and insightful. Think like a thoughtful manager or mentor.

Output format (markdown):

## {year} in Review
2-3 sentences capturing the overall shape of the year — what was the dominant theme, what was delivered, what shifted mid-year?

## Goal Achievement
Honest assessment of goals. Which landed, which didn't, and what patterns explain it? Don't just restate the data — interpret it.

## Work Patterns
What does the monthly activity distribution reveal? Any notable peaks, slow periods, or shifts in focus across the year?

## Top Contributions
2-4 bullet points on the most impactful areas of work, grounded in the project and repo data.

## Looking Forward
1-2 sentences: based on this year's patterns, what's worth carrying forward or changing?

Be direct. No filler. No praise for the sake of it."""

    try:
        if AI_PROVIDER == "gemini" and GEMINI_API_KEY:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                    json={
                        "contents": [
                            {
                                "role": "user",
                                "parts": [{"text": f"{system_prompt}\n\n{context}"}],
                            }
                        ],
                        "generationConfig": {
                            "temperature": 0.4,
                            "maxOutputTokens": 2048,
                        },
                    },
                )
                response.raise_for_status()
                data = response.json()
                narrative = data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            return """<div class="ai-summary-content"><p class="text-muted">AI provider not configured.</p></div>"""

        # Convert markdown to basic HTML
        import re

        html = narrative
        html = re.sub(r"^## (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
        html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
        html = re.sub(r"^- (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)
        html = re.sub(r"(<li>.*</li>\n?)+", r"<ul>\g<0></ul>", html, flags=re.DOTALL)
        html = re.sub(r"\n\n+", "</p><p>", html)
        html = f"<p>{html}</p>"

        return f'<div class="ai-summary-content">{html}</div>'

    except Exception as e:
        return f'<div class="ai-summary-content"><p class="text-muted">Failed to generate recap: {e}</p></div>'


@router.post("/ai-summary", response_class=HTMLResponse)
async def generate_ai_summary(
    request: Request,
    db: Session = Depends(get_db),
    view: str = Query("day"),
    date: Optional[str] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
    quarter: Optional[int] = None,
):
    """Generate AI summary of work done"""
    datetime.now().date()

    # Parse date if provided
    target_date = None
    if date:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()

    # Build context from activities
    context = build_activity_context(db, view, target_date, year, month, quarter)

    # Check if there's any data
    if "Stats: 0 PRs, 0 reviews, 0 commits, 0 issues" in context:
        return """<div class="ai-summary-content">
            <p class="text-muted">No activity data found for this period. Sync data first.</p>
        </div>"""

    # Same simple format for all views
    if view == "day":
        period_type = "today"
    elif view == "month":
        period_type = "this month"
    else:
        period_type = "this quarter"

    system_prompt = f"""You are writing a performance summary for an engineer covering {period_type}.

Your job is to synthesize patterns across ALL the work — not spotlight individual PRs or commits.
Group the work into 2-4 themes based on what the repos and PR titles collectively suggest.
Think like a manager writing a review: what did this person actually deliver at a high level?

Output format (markdown):
## Summary
2-3 sentences. What were the major themes of work this period? What was the overall impact on the team or business? Avoid naming specific PRs or repos — speak to outcomes.

## Key Themes
- **Theme name**: one sentence on what was achieved in this area and why it matters
- (2-4 themes total, each grounded in patterns across multiple PRs/repos)

## By the numbers
Restate the stats naturally in one sentence (e.g. "X commits across Y repos, Z PRs merged").

Be direct. No filler. Do not list individual PRs."""

    try:
        if AI_PROVIDER == "gemini" and GEMINI_API_KEY:
            # Use Google Gemini
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                    json={
                        "contents": [
                            {
                                "role": "user",
                                "parts": [{"text": f"{system_prompt}\n\n{context}"}],
                            }
                        ],
                        "generationConfig": {
                            "temperature": 0.3,
                            "maxOutputTokens": 2048,
                        },
                    },
                )
                response.raise_for_status()
                data = response.json()
                summary = data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            # Use Ollama (local)
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{OLLAMA_URL}/api/chat",
                    json={
                        "model": OLLAMA_MODEL,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": context},
                        ],
                        "stream": False,
                    },
                )
                response.raise_for_status()
                data = response.json()
                summary = data["message"]["content"]

        # Convert markdown-style bullets to HTML
        lines = summary.split("\n")
        html_lines = []
        for line in lines:
            line = line.strip()
            if line.startswith("- ") or line.startswith("* "):
                html_lines.append(f"<li>{line[2:]}</li>")
            elif line.startswith("## ") or line.startswith("### "):
                html_lines.append(f"<h4>{line.lstrip('#').strip()}</h4>")
            elif line:
                html_lines.append(f"<p>{line}</p>")

        formatted = "\n".join(html_lines)
        # Wrap consecutive li elements in ul
        formatted = formatted.replace("</li>\n<li>", "</li><li>")
        formatted = formatted.replace("<li>", "<ul><li>", 1) if "<li>" in formatted else formatted
        formatted = (
            formatted.replace("</li></p>", "</li></ul></p>") if "</li>" in formatted else formatted
        )
        if formatted.count("<ul>") > formatted.count("</ul>"):
            formatted += "</ul>"

        return f"""<div class="ai-summary-content">{formatted}</div>"""

    except httpx.ConnectError:
        return """<div class="ai-summary-content error">
            <p>Cannot connect to AI service.</p>
        </div>"""
    except Exception as e:
        return f"""<div class="ai-summary-content error">
            <p>AI error: {str(e)}</p>
        </div>"""
