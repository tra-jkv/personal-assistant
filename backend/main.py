import os
import threading
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Load environment variables from .env file
load_dotenv()

from backend.database import SessionLocal, engine  # noqa: E402
from backend.models.models import Base  # noqa: E402
from backend.routers import (  # noqa: E402
    ai,
    daily_report,
    epics,
    goals,
    links,
    meetings,
    notes,
    period_reports,
    projects,
    reminders,
    reports,
    tasks,
)

# Create all tables
Base.metadata.create_all(bind=engine)


def _run_startup_sync():
    """Run sync in a background thread on startup.

    Always calls run_full_sync — it handles the "already up to date" case
    internally by falling through to _sync_today_via_events, so today's
    activity is always refreshed.

    If the DailyActivity table is completely empty (fresh install or wiped DB),
    run_full_sync is called with start_date=DEFAULT_START to rebuild history.
    """
    from backend.models import DailyActivity
    from backend.services.background_sync import (
        DEFAULT_START,
        BackgroundSync,
        sync_jira_epics_and_stories,
    )

    db = SessionLocal()
    try:
        sync = BackgroundSync(db)
        today = date.today()

        # Fresh install: no rows at all — force rebuild from DEFAULT_START
        has_any_activity = db.query(DailyActivity).first() is not None
        if not has_any_activity:
            print("[startup sync] No activity data found — running full history sync...")
            sync.run_full_sync(start_date=DEFAULT_START, end_date=today)
        else:
            print("[startup sync] Starting activity sync...")
            sync.run_full_sync(end_date=today)

        print("[startup sync] Activity sync done.")

        print("[startup sync] Syncing Jira epics and tasks...")
        sync_jira_epics_and_stories()
        print("[startup sync] Epics sync done.")
    except Exception as e:
        print(f"[startup sync] Failed: {e}")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run sync in a background thread on startup
    thread = threading.Thread(target=_run_startup_sync, daemon=True)
    thread.start()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Personal Assistant API",
    description="""
## Engineering Hub Personal Assistant

A comprehensive workflow system for tracking:
- **Goals** - Yearly performance objectives
- **Projects** - Work initiatives linked to goals
- **Epics** - Jira epics synced and linked to projects  
- **Tasks** - Jira stories or manual tasks
- **Notes** - Freeform notes linked to projects/tasks
- **Reminders** - Time-based reminders with priorities
- **Meetings** - Meeting notes with action items

### API Endpoints

All `/api` endpoints accept and return JSON. Use these for programmatic access.

HTML endpoints (without `/api`) return rendered HTML for the web UI.
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {"name": "goals", "description": "Performance goals and objectives"},
        {"name": "projects", "description": "Work projects and initiatives"},
        {"name": "epics", "description": "Jira epics (synced from Jira)"},
        {"name": "tasks", "description": "Tasks/stories (Jira-synced or manual)"},
        {"name": "notes", "description": "Freeform notes"},
        {"name": "reminders", "description": "Time-based reminders"},
        {"name": "meetings", "description": "Meeting notes and action items"},
        {"name": "ai", "description": "AI assistant endpoints"},
        {"name": "reports", "description": "Activity reports and summaries"},
    ],
)

# Static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

# Include routers
app.include_router(projects.router)
app.include_router(notes.router)
app.include_router(reminders.router)
app.include_router(meetings.router)
app.include_router(ai.router)
app.include_router(links.router)
app.include_router(tasks.router)
app.include_router(daily_report.router)
app.include_router(period_reports.router)
app.include_router(reports.router)
app.include_router(goals.router)
app.include_router(epics.router)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    from backend.database import SessionLocal
    from backend.models import Goal, Project, Reminder, Task
    from backend.models.models import GoalStatus, ProjectStatus, TaskStatus

    db = SessionLocal()
    try:
        now = datetime.utcnow()

        # Projects
        active_projects = db.query(Project).filter(Project.status == ProjectStatus.active).count()
        recent_projects = (
            db.query(Project)
            .filter(Project.status == ProjectStatus.active)
            .order_by(Project.updated_at.desc())
            .limit(5)
            .all()
        )

        # Reminders
        open_reminders = (
            db.query(Reminder).filter(Reminder.is_done == False).count()  # noqa: E712
        )
        overdue_reminders = (
            db.query(Reminder)
            .filter(Reminder.is_done == False, Reminder.due_at < now)  # noqa: E712
            .order_by(Reminder.due_at)
            .all()
        )
        upcoming_reminders = (
            db.query(Reminder)
            .filter(Reminder.is_done == False, Reminder.due_at >= now)  # noqa: E712
            .order_by(Reminder.due_at)
            .limit(5)
            .all()
        )

        # Goals (eager-load projects to avoid DetachedInstanceError)
        from sqlalchemy.orm import joinedload

        from backend.routers.goals import calculate_goal_progress

        active_goals = (
            db.query(Goal)
            .options(joinedload(Goal.projects))
            .filter(Goal.status == GoalStatus.active)
            .all()
        )
        goal_progress = {
            g.id: dict(zip(("pct", "done", "total"), calculate_goal_progress(g, db)))
            for g in active_goals
        }

        # Unlinked projects (active + paused with no goals)
        all_active_paused = (
            db.query(Project)
            .options(joinedload(Project.goals))
            .filter(Project.status.in_([ProjectStatus.active, ProjectStatus.paused]))
            .all()
        )
        unlinked_projects_count = sum(1 for p in all_active_paused if not p.goals)

        # Tasks in progress
        tasks_in_progress = (
            db.query(Task)
            .filter(Task.status == TaskStatus.in_progress)
            .order_by(Task.updated_at.desc())
            .limit(5)
            .all()
        )
        tasks_in_progress_count = (
            db.query(Task).filter(Task.status == TaskStatus.in_progress).count()
        )

    finally:
        db.close()

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "active_projects": active_projects,
            "open_reminders": open_reminders,
            "overdue_reminders": overdue_reminders,
            "recent_projects": recent_projects,
            "upcoming_reminders": upcoming_reminders,
            "active_goals": active_goals,
            "goal_progress": goal_progress,
            "tasks_in_progress": tasks_in_progress,
            "tasks_in_progress_count": tasks_in_progress_count,
            "unlinked_projects_count": unlinked_projects_count,
            "now": now,
        },
    )


@app.get("/dashboard/briefing", response_class=HTMLResponse)
async def dashboard_briefing(request: Request):
    """AI daily briefing — called via HTMX on dashboard load."""
    from sqlalchemy.orm import joinedload

    from backend.database import SessionLocal
    from backend.models import DailyActivity, Goal, Reminder, Task
    from backend.models.models import GoalStatus, TaskStatus
    from backend.routers.goals import calculate_goal_progress

    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    USER_NAME = (
        os.getenv("USER_DISPLAY_NAME", "").split()[0] if os.getenv("USER_DISPLAY_NAME") else "there"
    )

    if not GEMINI_API_KEY:
        return HTMLResponse(
            '<p class="text-muted" style="font-size:.85rem">AI briefing unavailable — set GEMINI_API_KEY in .env</p>'
        )

    db = SessionLocal()
    try:
        now = datetime.utcnow()
        today = now.date()

        # Overdue reminders
        overdue = (
            db.query(Reminder)
            .filter(Reminder.is_done == False, Reminder.due_at < now)  # noqa: E712
            .order_by(Reminder.due_at)
            .all()
        )

        # Upcoming reminders (next 7 days)
        upcoming = (
            db.query(Reminder)
            .filter(
                Reminder.is_done == False,  # noqa: E712
                Reminder.due_at >= now,
                Reminder.due_at <= now + timedelta(days=7),
            )
            .order_by(Reminder.due_at)
            .limit(5)
            .all()
        )

        # In-progress tasks
        in_progress = (
            db.query(Task)
            .filter(Task.status == TaskStatus.in_progress)
            .order_by(Task.updated_at.desc())
            .limit(10)
            .all()
        )

        # Blocked tasks
        blocked = (
            db.query(Task)
            .filter(Task.status == TaskStatus.blocked)
            .order_by(Task.updated_at.desc())
            .limit(5)
            .all()
        )

        # Active goals with progress
        goals = (
            db.query(Goal)
            .options(joinedload(Goal.projects))
            .filter(Goal.status == GoalStatus.active)
            .all()
        )
        goals_context = []
        for g in goals:
            pct, done, total = calculate_goal_progress(g, db)
            goals_context.append(f"{g.title}: {pct}% ({done}/{total} tasks done)")

        # Today's synced activity
        today_start = datetime.combine(today, datetime.min.time())
        today_end = today_start + timedelta(days=1)
        today_activity = (
            db.query(DailyActivity)
            .filter(
                DailyActivity.activity_date >= today_start,
                DailyActivity.activity_date < today_end,
            )
            .all()
        )
        commits_today = sum(1 for a in today_activity if a.activity_type == "commit")
        prs_today = sum(1 for a in today_activity if a.activity_type == "pull_request")

    finally:
        db.close()

    # Build context
    lines = [f"Today is {today.strftime('%A, %B %d, %Y')}."]

    if goals_context:
        lines.append("\nActive goals:")
        for g in goals_context:
            lines.append(f"  - {g}")

    if in_progress:
        lines.append("\nTasks currently in progress:")
        for t in in_progress:
            key = f"[{t.jira_key}] " if t.jira_key else ""
            lines.append(f"  - {key}{t.title}")

    if blocked:
        lines.append("\nBlocked tasks (need attention):")
        for t in blocked:
            key = f"[{t.jira_key}] " if t.jira_key else ""
            lines.append(f"  - {key}{t.title}")

    if overdue:
        lines.append(f"\nOverdue reminders ({len(overdue)}):")
        for r in overdue[:5]:
            lines.append(f"  - {r.title} (was due {r.due_at.strftime('%b %d')})")

    if upcoming:
        lines.append("\nUpcoming reminders this week:")
        for r in upcoming:
            lines.append(f"  - {r.title} (due {r.due_at.strftime('%b %d')})")

    if commits_today or prs_today:
        lines.append(f"\nGitHub activity today: {commits_today} commits, {prs_today} PRs.")

    context = "\n".join(lines)

    prompt = f"""You are a personal assistant for a software engineer. Write a short, direct daily briefing.

Start with "Good {"morning" if now.hour < 12 else "afternoon" if now.hour < 18 else "evening"}, {USER_NAME}." then 1-2 sentences on what to focus on today based on the data below.

Then give 2-4 bullet points of the most important things to act on today — prioritise blocked tasks, overdue reminders, and in-progress work. Be specific and actionable. No filler, no pleasantries after the greeting. Max 120 words total.

{context}"""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.4, "maxOutputTokens": 300},
                },
            )
            response.raise_for_status()
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

        # Simple markdown → HTML
        html_parts = []
        in_ul = False
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("- ") or line.startswith("• "):
                if not in_ul:
                    html_parts.append("<ul>")
                    in_ul = True
                html_parts.append(f"<li>{line[2:]}</li>")
            else:
                if in_ul:
                    html_parts.append("</ul>")
                    in_ul = False
                html_parts.append(f"<p>{line}</p>")
        if in_ul:
            html_parts.append("</ul>")

        return HTMLResponse("\n".join(html_parts))

    except Exception as e:
        return HTMLResponse(
            f'<p class="text-muted" style="font-size:.85rem">Could not generate briefing: {e}</p>'
        )
