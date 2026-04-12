import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import relationship

from backend.database import Base


class LinkType(str, enum.Enum):
    github = "github"
    jira = "jira"
    confluence = "confluence"
    other = "other"


class TaskStatus(str, enum.Enum):
    backlog = "backlog"
    todo = "todo"
    in_progress = "in_progress"
    blocked = "blocked"
    in_review = "in_review"
    done = "done"
    cancelled = "cancelled"


class ProjectStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    completed = "completed"
    archived = "archived"


class GoalStatus(str, enum.Enum):
    active = "active"
    achieved = "achieved"
    cancelled = "cancelled"
    deferred = "deferred"


class Priority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Many-to-many association table: Goal <-> Project
goal_project = Table(
    "goal_project",
    Base.metadata,
    Column("goal_id", Integer, ForeignKey("goals.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "project_id",
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Goal(Base):
    """Performance goals / objectives - tracked per year"""

    __tablename__ = "goals"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(300), nullable=False)
    description = Column(Text, default="")
    status = Column(Enum(GoalStatus), default=GoalStatus.active)
    year = Column(Integer, nullable=True)  # e.g., 2026
    target_date = Column(Date, nullable=True)
    progress_pct = Column(Integer, default=0)  # 0-100
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Many-to-many relationship with Project
    projects = relationship("Project", secondary=goal_project, back_populates="goals")


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    status = Column(Enum(ProjectStatus), default=ProjectStatus.active)
    priority = Column(Enum(Priority), default=Priority.medium)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Many-to-many relationship with Goal
    goals = relationship("Goal", secondary=goal_project, back_populates="projects")

    # One-to-many relationship with Epic
    epics = relationship("Epic", back_populates="project", order_by="Epic.key")

    # One-to-many relationship with Task (new unified model)
    tasks = relationship("Task", back_populates="project", order_by="Task.position")

    notes = relationship("Note", back_populates="project", cascade="all, delete-orphan")
    reminders = relationship("Reminder", back_populates="project", cascade="all, delete-orphan")
    meeting_notes = relationship(
        "MeetingNote", back_populates="project", cascade="all, delete-orphan"
    )
    links = relationship(
        "ExternalLink",
        back_populates="project",
        cascade="all, delete-orphan",
        foreign_keys="ExternalLink.project_id",
    )


class Epic(Base):
    """Jira Epics (synced from Jira)"""

    __tablename__ = "epics"

    key = Column(String(50), primary_key=True)  # e.g., "DL-1234"
    title = Column(String(500), default="")
    status = Column(String(100), default="")
    jira_url = Column(String(500), default="")
    last_synced = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Foreign key to Project (one-to-many: Project has many Epics)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)

    # Many-to-one relationship with Project
    project = relationship("Project", back_populates="epics")

    # One-to-many relationship with Task (was Story)
    tasks = relationship("Task", back_populates="epic", cascade="all, delete-orphan")


class Task(Base):
    """
    Unified Task model - can be:
    - Synced from Jira (has jira_key)
    - Manually created (no jira_key)
    - Linked to Jira later (jira_key added manually)
    """

    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, default="")

    # Status - uses Jira status strings for synced tasks, or our enum values for manual
    status = Column(String(100), default="To Do")

    # Priority
    priority = Column(Enum(Priority), default=Priority.medium)

    # Assignee (Jira display name or manual entry)
    assignee = Column(String(200), default="")

    # Due date
    due_date = Column(Date, nullable=True)

    # Jira integration
    jira_key = Column(String(50), nullable=True, unique=True, index=True)  # e.g., "DL-1235"
    jira_url = Column(String(500), default="")
    jira_status = Column(String(100), default="")  # Original Jira status for sync-back

    # Sprint info (synced from Jira)
    sprint_id = Column(Integer, nullable=True)  # Jira sprint ID
    sprint_name = Column(String(200), default="")  # Sprint name (e.g., "Sprint 42")

    # Subtasks (stored as JSON for stories synced from Jira)
    # Format: [{"key": "DL-123", "title": "...", "status": "...", "assignee": "..."}]
    subtasks_json = Column(Text, default="")

    # Relationships
    epic_key = Column(String(50), ForeignKey("epics.key", ondelete="SET NULL"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)

    # Sync tracking
    is_synced = Column(Boolean, default=False)  # True if synced from Jira
    last_synced = Column(DateTime, nullable=True)
    jira_updated_at = Column(DateTime, nullable=True)  # Actual last-updated time from Jira
    needs_sync_back = Column(
        Boolean, default=False
    )  # True if local changes need to be pushed to Jira

    # Ordering
    position = Column(Integer, default=0)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    epic = relationship("Epic", back_populates="tasks")
    project = relationship("Project", back_populates="tasks")
    notes = relationship("Note", back_populates="task")
    reminders = relationship("Reminder", back_populates="task")
    links = relationship(
        "ExternalLink",
        back_populates="task",
        cascade="all, delete-orphan",
        foreign_keys="ExternalLink.task_id",
    )


class Note(Base):
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(300), nullable=False)
    content = Column(Text, default="")
    tags = Column(String(500), default="")  # comma-separated
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    project = relationship("Project", back_populates="notes")
    task = relationship("Task", back_populates="notes")
    links = relationship(
        "ExternalLink",
        back_populates="note",
        cascade="all, delete-orphan",
        foreign_keys="ExternalLink.note_id",
    )


class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(300), nullable=False)
    description = Column(Text, default="")
    due_at = Column(DateTime, nullable=False)
    is_done = Column(Boolean, default=False)
    priority = Column(Enum(Priority), default=Priority.medium)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    project = relationship("Project", back_populates="reminders")
    task = relationship("Task", back_populates="reminders")


class StandupLog(Base):
    __tablename__ = "standup_logs"

    id = Column(Integer, primary_key=True, index=True)
    log_date = Column(String(10), nullable=False)  # YYYY-MM-DD
    did = Column(Text, default="")  # what I did
    doing = Column(Text, default="")  # what I'm doing today
    blockers = Column(Text, default="")  # blockers
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class MeetingNote(Base):
    __tablename__ = "meeting_notes"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(300), nullable=False)
    meeting_date = Column(String(10), nullable=False)  # YYYY-MM-DD
    attendees = Column(Text, default="")
    summary = Column(Text, default="")
    notes = Column(Text, default="")
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    project = relationship("Project", back_populates="meeting_notes")
    action_items = relationship(
        "ActionItem", back_populates="meeting", cascade="all, delete-orphan"
    )
    links = relationship(
        "ExternalLink",
        back_populates="meeting",
        cascade="all, delete-orphan",
        foreign_keys="ExternalLink.meeting_id",
    )


class ActionItem(Base):
    __tablename__ = "action_items"

    id = Column(Integer, primary_key=True, index=True)
    description = Column(Text, nullable=False)
    owner = Column(String(200), default="")
    due_date = Column(String(10), default="")  # YYYY-MM-DD
    is_done = Column(Boolean, default=False)
    meeting_id = Column(Integer, ForeignKey("meeting_notes.id"), nullable=False)
    created_at = Column(DateTime, default=utcnow)

    meeting = relationship("MeetingNote", back_populates="action_items")


class ExternalLink(Base):
    __tablename__ = "external_links"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(300), nullable=False)
    url = Column(Text, nullable=False)
    link_type = Column(Enum(LinkType), default=LinkType.other)
    description = Column(Text, default="")
    # Optional associations — at most one of these is set
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    note_id = Column(Integer, ForeignKey("notes.id", ondelete="CASCADE"), nullable=True)
    meeting_id = Column(Integer, ForeignKey("meeting_notes.id", ondelete="CASCADE"), nullable=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    project = relationship("Project", back_populates="links")
    note = relationship("Note", back_populates="links")
    meeting = relationship("MeetingNote", back_populates="links")
    task = relationship("Task", back_populates="links")


class SyncState(Base):
    """Track last sync time for incremental syncing"""

    __tablename__ = "sync_state"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(50), unique=True, nullable=False, index=True)  # 'github' or 'jira'
    last_sync_at = Column(DateTime, nullable=False)
    last_sync_success = Column(Boolean, default=True)
    last_sync_error = Column(Text, default="")
    total_syncs = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class DailyActivity(Base):
    """Store daily GitHub and Jira activity for historical reporting"""

    __tablename__ = "daily_activity"

    id = Column(Integer, primary_key=True, index=True)
    activity_date = Column(DateTime, nullable=False, index=True)  # Date of activity
    source = Column(String(50), nullable=False, index=True)  # 'github' or 'jira'
    activity_type = Column(
        String(50), nullable=False, index=True
    )  # 'commit', 'pr', 'issue', 'review', 'jira_issue', 'jira_transition', etc.
    external_id = Column(String(255), nullable=False)  # SHA, PR#, Issue key, etc.
    title = Column(Text)  # Commit message, PR title, Issue summary
    url = Column(Text)  # Link to GitHub/Jira
    repository = Column(String(255))  # GitHub repo name
    status = Column(String(100))  # PR state, issue status, etc.
    extra_data = Column(Text)  # JSON string for additional data
    created_at = Column(DateTime, default=utcnow)


class DailySummary(Base):
    """Store daily aggregated statistics for quick reporting"""

    __tablename__ = "daily_summary"

    id = Column(Integer, primary_key=True, index=True)
    summary_date = Column(DateTime, nullable=False, unique=True, index=True)
    # GitHub stats
    github_commits = Column(Integer, default=0)
    github_prs = Column(Integer, default=0)
    github_issues = Column(Integer, default=0)
    github_reviews = Column(Integer, default=0)
    # Jira stats
    jira_assigned = Column(Integer, default=0)
    jira_worked = Column(Integer, default=0)
    jira_transitions = Column(Integer, default=0)
    jira_comments = Column(Integer, default=0)
    # Metadata
    top_repo = Column(String(255))  # Most active repo
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


# ── AI Conversation Session ───────────────────────────────────────────────────


class ConversationSession(Base):
    """
    Represents an AI conversation session.
    Sessions allow for multi-turn conversations with context retention.
    """

    __tablename__ = "conversation_sessions"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), default="New Conversation")
    mode = Column(String(20), default="ask")  # ask, plan, execute
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationship to messages
    messages = relationship(
        "ConversationMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.created_at",
    )


class ConversationMessage(Base):
    """
    Individual message in a conversation session.
    """

    __tablename__ = "conversation_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("conversation_sessions.id"), nullable=False)
    role = Column(String(20), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    # For agent mode - store action details
    action_type = Column(String(50))  # plan, execute, or null for regular messages
    action_data = Column(Text)  # JSON string of action details
    created_at = Column(DateTime, default=utcnow)

    # Relationship back to session
    session = relationship("ConversationSession", back_populates="messages")
