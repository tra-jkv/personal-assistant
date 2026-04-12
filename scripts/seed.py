"""
Seed script — populates the database with realistic dummy data for screenshots.

Usage:
    uv run python scripts/seed.py          # seed
    uv run python scripts/seed.py --wipe   # wipe all data then seed
    uv run python scripts/seed.py --clear  # wipe only, no seed
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta

# Make sure backend is importable from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.database import SessionLocal, engine
from backend.models.models import (
    ActionItem,
    Base,
    DailyActivity,
    DailySummary,
    Epic,
    Goal,
    GoalStatus,
    MeetingNote,
    Note,
    Priority,
    Project,
    ProjectStatus,
    Reminder,
    Task,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def dt(days_offset=0, hour=9):
    """Return a datetime relative to today."""
    return datetime.now().replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(
        days=days_offset
    )


def d(days_offset=0):
    """Return a date relative to today."""
    return date.today() + timedelta(days=days_offset)


# ── Wipe ─────────────────────────────────────────────────────────────────────


def wipe(db):
    print("Wiping existing data...")
    for table in reversed(Base.metadata.sorted_tables):
        db.execute(table.delete())
    db.commit()
    print("Done.")


# ── Seed ─────────────────────────────────────────────────────────────────────


def seed(db):
    print("Seeding...")

    # ── Goals ─────────────────────────────────────────────────────────────────

    goal_platform = Goal(
        title="Improve data platform reliability to 99.9% uptime",
        description="Reduce pipeline failures, improve monitoring, and establish SLOs for all critical data flows.",
        status=GoalStatus.active,
        year=2026,
        target_date=d(180),
        progress_pct=62,
    )
    goal_ownership = Goal(
        title="Take ownership of the ingestion layer end-to-end",
        description="Become the go-to person for all ingestion pipelines. Document everything, reduce bus factor.",
        status=GoalStatus.active,
        year=2026,
        target_date=d(270),
        progress_pct=45,
    )
    goal_collab = Goal(
        title="Improve cross-team collaboration with analytics engineers",
        description="Establish shared standards for data contracts, testing, and documentation between data engineering and analytics.",
        status=GoalStatus.active,
        year=2026,
        target_date=d(365),
        progress_pct=30,
    )
    goal_done = Goal(
        title="Migrate legacy ETL jobs to dbt + Airflow",
        description="Retire the last 8 legacy Python ETL scripts and replace with dbt models orchestrated by Airflow.",
        status=GoalStatus.achieved,
        year=2026,
        target_date=d(-30),
        progress_pct=100,
    )
    db.add_all([goal_platform, goal_ownership, goal_collab, goal_done])
    db.flush()

    # ── Projects ──────────────────────────────────────────────────────────────

    proj_ingestion = Project(
        name="Ingestion Layer Overhaul",
        description="Rewrite the core ingestion layer to support schema evolution, dead letter queues, and per-source SLOs.",
        status=ProjectStatus.active,
        priority=Priority.high,
        start_date=d(-60),
        end_date=d(90),
    )
    proj_monitoring = Project(
        name="Data Platform Monitoring",
        description="Build out alerting, dashboards, and SLO tracking for all critical data pipelines.",
        status=ProjectStatus.active,
        priority=Priority.high,
        start_date=d(-30),
        end_date=d(60),
    )
    proj_contracts = Project(
        name="Data Contracts with Analytics",
        description="Define and enforce data contracts at the interface between data engineering and analytics.",
        status=ProjectStatus.active,
        priority=Priority.medium,
        start_date=d(-14),
        end_date=d(120),
    )
    proj_legacy = Project(
        name="Legacy ETL Migration",
        description="Migrate 8 legacy Python ETL scripts to dbt models orchestrated by Airflow.",
        status=ProjectStatus.completed,
        priority=Priority.medium,
        start_date=d(-180),
        end_date=d(-30),
    )
    proj_infra = Project(
        name="Kafka Infrastructure Upgrade",
        description="Upgrade Kafka cluster to 3.x, enable rack awareness, and migrate topics to new naming convention.",
        status=ProjectStatus.active,
        priority=Priority.medium,
        start_date=d(-7),
        end_date=d(45),
    )
    db.add_all([proj_ingestion, proj_monitoring, proj_contracts, proj_legacy, proj_infra])
    db.flush()

    # Link projects to goals
    goal_platform.projects.append(proj_monitoring)
    goal_platform.projects.append(proj_ingestion)
    goal_ownership.projects.append(proj_ingestion)
    goal_ownership.projects.append(proj_infra)
    goal_collab.projects.append(proj_contracts)
    goal_done.projects.append(proj_legacy)
    db.flush()

    # ── Epics ─────────────────────────────────────────────────────────────────

    epic_dlq = Epic(
        key="DL-101",
        title="Dead Letter Queue Implementation",
        status="In Development",
        jira_url="https://example.atlassian.net/browse/DL-101",
        project_id=proj_ingestion.id,
        last_synced=dt(-1),
    )
    epic_schema = Epic(
        key="DL-102",
        title="Schema Evolution Support in Ingestion",
        status="In Development",
        jira_url="https://example.atlassian.net/browse/DL-102",
        project_id=proj_ingestion.id,
        last_synced=dt(-1),
    )
    epic_slo = Epic(
        key="DL-103",
        title="SLO Monitoring & Alerting Framework",
        status="In Refinement",
        jira_url="https://example.atlassian.net/browse/DL-103",
        project_id=proj_monitoring.id,
        last_synced=dt(-1),
    )
    epic_contracts = Epic(
        key="DL-104",
        title="Data Contract Enforcement Layer",
        status="To Refine",
        jira_url="https://example.atlassian.net/browse/DL-104",
        project_id=proj_contracts.id,
        last_synced=dt(-1),
    )
    epic_kafka = Epic(
        key="DL-105",
        title="Kafka 3.x Migration",
        status="In Development",
        jira_url="https://example.atlassian.net/browse/DL-105",
        project_id=proj_infra.id,
        last_synced=dt(-1),
    )
    # Unlinked epic — intentionally not tied to any project (for alignment view demo)
    epic_unlinked = Epic(
        key="DL-106",
        title="Ad-hoc Reporting Pipeline for Finance",
        status="In Refinement",
        jira_url="https://example.atlassian.net/browse/DL-106",
        project_id=None,
        last_synced=dt(-1),
    )
    db.add_all([epic_dlq, epic_schema, epic_slo, epic_contracts, epic_kafka, epic_unlinked])
    db.flush()

    # ── Tasks ─────────────────────────────────────────────────────────────────

    tasks = [
        # DLQ epic tasks
        Task(
            title="Design DLQ schema and retention policy",
            status="Done",
            priority=Priority.high,
            jira_key="DL-201",
            jira_url="https://example.atlassian.net/browse/DL-201",
            epic_key="DL-101",
            project_id=proj_ingestion.id,
            is_synced=True,
            sprint_name="Sprint 12",
            position=1,
        ),
        Task(
            title="Implement DLQ producer in ingestion service",
            status="In Development",
            priority=Priority.high,
            jira_key="DL-202",
            jira_url="https://example.atlassian.net/browse/DL-202",
            epic_key="DL-101",
            project_id=proj_ingestion.id,
            is_synced=True,
            sprint_name="Sprint 12",
            position=2,
            subtasks_json=json.dumps(
                [
                    {
                        "key": "DL-202-1",
                        "title": "Add DLQ topic config",
                        "status": "Done",
                        "assignee": "You",
                    },
                    {
                        "key": "DL-202-2",
                        "title": "Implement retry logic",
                        "status": "In Development",
                        "assignee": "You",
                    },
                    {
                        "key": "DL-202-3",
                        "title": "Write unit tests",
                        "status": "To Do",
                        "assignee": "You",
                    },
                ]
            ),
        ),
        Task(
            title="Build DLQ consumer and reprocessing UI",
            status="To Do",
            priority=Priority.medium,
            jira_key="DL-203",
            jira_url="https://example.atlassian.net/browse/DL-203",
            epic_key="DL-101",
            project_id=proj_ingestion.id,
            is_synced=True,
            sprint_name="Sprint 13",
            position=3,
        ),
        # Schema evolution tasks
        Task(
            title="Evaluate schema registry options (Confluent vs AWS Glue)",
            status="Done",
            priority=Priority.high,
            jira_key="DL-204",
            jira_url="https://example.atlassian.net/browse/DL-204",
            epic_key="DL-102",
            project_id=proj_ingestion.id,
            is_synced=True,
            sprint_name="Sprint 11",
            position=4,
        ),
        Task(
            title="Integrate Confluent Schema Registry with ingestion service",
            status="In Review",
            priority=Priority.high,
            jira_key="DL-205",
            jira_url="https://example.atlassian.net/browse/DL-205",
            epic_key="DL-102",
            project_id=proj_ingestion.id,
            is_synced=True,
            sprint_name="Sprint 12",
            position=5,
        ),
        # SLO tasks
        Task(
            title="Define SLOs for top 10 critical pipelines",
            status="Done",
            priority=Priority.high,
            jira_key="DL-206",
            jira_url="https://example.atlassian.net/browse/DL-206",
            epic_key="DL-103",
            project_id=proj_monitoring.id,
            is_synced=True,
            sprint_name="Sprint 11",
            position=6,
        ),
        Task(
            title="Build Grafana SLO dashboard",
            status="In Development",
            priority=Priority.high,
            jira_key="DL-207",
            jira_url="https://example.atlassian.net/browse/DL-207",
            epic_key="DL-103",
            project_id=proj_monitoring.id,
            is_synced=True,
            sprint_name="Sprint 12",
            position=7,
        ),
        Task(
            title="Set up PagerDuty alerting for SLO breaches",
            status="Blocked",
            priority=Priority.high,
            jira_key="DL-208",
            jira_url="https://example.atlassian.net/browse/DL-208",
            epic_key="DL-103",
            project_id=proj_monitoring.id,
            is_synced=True,
            sprint_name="Sprint 12",
            position=8,
        ),
        # DL-104 tasks (Data Contracts epic)
        Task(
            title="Define schema for orders data contract",
            status="In Development",
            priority=Priority.high,
            jira_key="DL-209",
            jira_url="https://example.atlassian.net/browse/DL-209",
            epic_key="DL-104",
            project_id=proj_contracts.id,
            is_synced=True,
            sprint_name="Sprint 13",
            position=9,
        ),
        Task(
            title="Validate contract enforcement in CI pipeline",
            status="To Do",
            priority=Priority.medium,
            jira_key="DL-210",
            jira_url="https://example.atlassian.net/browse/DL-210",
            epic_key="DL-104",
            project_id=proj_contracts.id,
            is_synced=True,
            sprint_name="Sprint 13",
            position=10,
        ),
        # DL-105 tasks (Kafka epic)
        Task(
            title="Upgrade Kafka brokers to 3.6 in staging",
            status="In Development",
            priority=Priority.high,
            jira_key="DL-211",
            jira_url="https://example.atlassian.net/browse/DL-211",
            epic_key="DL-105",
            project_id=proj_infra.id,
            is_synced=True,
            sprint_name="Sprint 12",
            position=11,
        ),
        Task(
            title="Enable rack awareness on Kafka cluster",
            status="To Do",
            priority=Priority.medium,
            jira_key="DL-212",
            jira_url="https://example.atlassian.net/browse/DL-212",
            epic_key="DL-105",
            project_id=proj_infra.id,
            is_synced=True,
            sprint_name="Sprint 13",
            position=12,
        ),
        # DL-106 tasks (unlinked Finance epic — no project, no goal)
        Task(
            title="Scope ad-hoc reporting requirements with finance team",
            status="Done",
            priority=Priority.medium,
            jira_key="DL-213",
            jira_url="https://example.atlassian.net/browse/DL-213",
            epic_key="DL-106",
            is_synced=True,
            sprint_name="Sprint 11",
            position=13,
        ),
        Task(
            title="Build finance export pipeline (S3 → Redshift)",
            status="In Development",
            priority=Priority.high,
            jira_key="DL-214",
            jira_url="https://example.atlassian.net/browse/DL-214",
            epic_key="DL-106",
            is_synced=True,
            sprint_name="Sprint 12",
            position=14,
        ),
        Task(
            title="Schedule daily finance report job in Airflow",
            status="To Do",
            priority=Priority.medium,
            jira_key="DL-215",
            jira_url="https://example.atlassian.net/browse/DL-215",
            epic_key="DL-106",
            is_synced=True,
            sprint_name="Sprint 13",
            position=15,
        ),
        # Manual tasks (no Jira key, linked to projects)
        Task(
            title="Write ADR for schema registry decision",
            status="in_progress",
            priority=Priority.medium,
            project_id=proj_ingestion.id,
            is_synced=False,
            position=16,
        ),
        Task(
            title="Review Kafka upgrade runbook with infra team",
            status="todo",
            priority=Priority.medium,
            project_id=proj_infra.id,
            is_synced=False,
            due_date=d(3),
            position=17,
        ),
        Task(
            title="Document data contract template for analytics team",
            status="todo",
            priority=Priority.medium,
            project_id=proj_contracts.id,
            is_synced=False,
            position=18,
        ),
        # Standalone tasks — no project, no epic (general ad-hoc work)
        Task(
            title="Read Designing Data-Intensive Applications ch. 9",
            status="in_progress",
            priority=Priority.low,
            is_synced=False,
            position=19,
        ),
        Task(
            title="Prep questions for staff eng interview panel",
            status="todo",
            priority=Priority.high,
            due_date=d(6),
            is_synced=False,
            position=20,
        ),
        Task(
            title="Update personal brag doc with Q1 wins",
            status="todo",
            priority=Priority.medium,
            is_synced=False,
            position=21,
        ),
        Task(
            title="Review open source PRs on data-diff",
            status="todo",
            priority=Priority.low,
            is_synced=False,
            position=22,
        ),
        Task(
            title="Set up local Kafka dev environment",
            status="done",
            priority=Priority.medium,
            is_synced=False,
            position=23,
        ),
    ]
    db.add_all(tasks)
    db.flush()

    # ── Notes ─────────────────────────────────────────────────────────────────

    notes = [
        Note(
            title="Schema Registry — Decision Notes",
            content="Evaluated Confluent Schema Registry vs AWS Glue Schema Registry. Going with Confluent:\n\n- Already using Confluent Kafka\n- Better tooling for AVRO evolution\n- Team has existing familiarity\n\nGlue is tightly coupled to AWS Glue jobs which we're moving away from.",
            tags="architecture,schema,kafka",
            project_id=proj_ingestion.id,
        ),
        Note(
            title="SLO Definitions — v1",
            content="Critical pipelines SLOs:\n\n- Orders ingestion: 99.9% availability, < 5min latency\n- Inventory feed: 99.5% availability, < 15min latency\n- Finance export: 99.9% availability, < 1hr latency\n\nReview with stakeholders in Sprint 13.",
            tags="slo,monitoring,reliability",
            project_id=proj_monitoring.id,
        ),
        Note(
            title="Data Contract Template — Draft",
            content="Fields to include in every data contract:\n- Owner (team + individual)\n- Schema (link to registry)\n- SLO (availability + freshness)\n- Consumers (list of downstream users)\n- Breaking change process\n\nWill circulate to analytics team for feedback next week.",
            tags="contracts,analytics,standards",
            project_id=proj_contracts.id,
        ),
    ]
    db.add_all(notes)
    db.flush()

    # ── Reminders ─────────────────────────────────────────────────────────────

    reminders = [
        Reminder(
            title="Follow up on PagerDuty access request",
            description="IT raised a blocker on DL-208 — need PagerDuty team license. Follow up with ops.",
            due_at=dt(1, hour=10),
            priority=Priority.high,
            project_id=proj_monitoring.id,
        ),
        Reminder(
            title="Send data contract draft to analytics team",
            description="Share the draft template and ask for async feedback before the sync next Thursday.",
            due_at=dt(2, hour=14),
            priority=Priority.medium,
            project_id=proj_contracts.id,
        ),
        Reminder(
            title="Sprint 13 planning prep",
            description="Review backlog and have DL-203 story ready with acceptance criteria.",
            due_at=dt(4, hour=9),
            priority=Priority.medium,
        ),
        Reminder(
            title="Book 1:1 with tech lead — discuss Kafka upgrade timeline",
            description="Infra team needs a firm date. Align on Sprint 14 target.",
            due_at=dt(5, hour=11),
            priority=Priority.low,
            project_id=proj_infra.id,
        ),
        Reminder(
            title="Quarterly goal check-in with manager",
            description="Prepare progress update for all 4 goals. Use yearly recap from Engineering Hub.",
            due_at=dt(14, hour=14),
            priority=Priority.high,
            is_done=False,
        ),
    ]
    db.add_all(reminders)
    db.flush()

    # ── Meeting Notes ─────────────────────────────────────────────────────────

    meeting1 = MeetingNote(
        title="Architecture Review — Schema Registry",
        meeting_date=str(d(-5)),
        attendees="You, Sarah (Staff Engineer), Marco (Platform Lead)",
        summary="Reviewed schema registry options. Agreed to go with Confluent. Marco will provision the cluster by end of sprint.",
        notes="Sarah raised a concern about AVRO compatibility in the Python consumers — need to verify the `fastavro` version supports the compatibility mode we need.\n\nMarco flagged that the Confluent cluster will need a firewall rule change — estimated 2 days.",
        project_id=proj_ingestion.id,
    )
    db.add(meeting1)
    db.flush()
    db.add_all(
        [
            ActionItem(
                description="Verify fastavro compatibility mode support",
                owner="You",
                due_date=str(d(-2)),
                is_done=True,
                meeting_id=meeting1.id,
            ),
            ActionItem(
                description="Provision Confluent Schema Registry cluster",
                owner="Marco",
                due_date=str(d(-1)),
                is_done=True,
                meeting_id=meeting1.id,
            ),
            ActionItem(
                description="Raise firewall change request with infra",
                owner="Marco",
                due_date=str(d(2)),
                is_done=False,
                meeting_id=meeting1.id,
            ),
        ]
    )

    meeting2 = MeetingNote(
        title="Data Contracts Kickoff — Analytics Sync",
        meeting_date=str(d(-2)),
        attendees="You, Priya (Analytics Lead), Tom (Analytics Engineer), Lisa (Data Eng Manager)",
        summary="Kicked off the data contracts initiative. Agreed on scope: start with the top 5 most-used datasets. You will draft the template, Priya will identify consumer requirements.",
        notes="Tom asked about backward compatibility guarantees — good question, need to define what 'breaking change' means in the contract.\n\nLisa wants a monthly review cadence to track adoption.",
        project_id=proj_contracts.id,
    )
    db.add(meeting2)
    db.flush()
    db.add_all(
        [
            ActionItem(
                description="Draft data contract template",
                owner="You",
                due_date=str(d(2)),
                is_done=False,
                meeting_id=meeting2.id,
            ),
            ActionItem(
                description="Identify top 5 datasets to contract first",
                owner="Priya",
                due_date=str(d(3)),
                is_done=False,
                meeting_id=meeting2.id,
            ),
            ActionItem(
                description="Define 'breaking change' policy",
                owner="You",
                due_date=str(d(5)),
                is_done=False,
                meeting_id=meeting2.id,
            ),
        ]
    )

    # ── Daily Activity (last 30 days) ─────────────────────────────────────────

    repos = [
        "data-platform/ingestion-service",
        "data-platform/schema-registry-client",
        "data-platform/monitoring",
        "data-platform/kafka-infra",
    ]
    commit_messages = [
        "feat: add DLQ producer to ingestion service",
        "fix: handle null values in AVRO serializer",
        "feat: integrate Confluent Schema Registry client",
        "chore: bump fastavro to 1.9.4",
        "feat: add Grafana SLO dashboard config",
        "fix: correct retry backoff logic in consumer",
        "docs: update ingestion service README",
        "refactor: extract schema validation into separate module",
        "feat: add dead letter queue consumer",
        "test: add integration tests for schema evolution",
        "fix: handle schema not found error gracefully",
        "feat: add SLO breach alert rule to Grafana",
        "chore: update Kafka client to 3.6.0",
        "feat: add rack awareness config to Kafka brokers",
        "docs: add ADR for schema registry decision",
    ]
    pr_titles = [
        "feat: DLQ implementation — producer side",
        "feat: Schema Registry integration",
        "fix: retry logic improvements",
        "feat: Grafana SLO dashboard",
        "chore: Kafka 3.x client upgrade",
    ]
    jira_transitions = [
        ("DL-201", "In Progress", "Done"),
        ("DL-204", "In Progress", "Done"),
        ("DL-206", "In Progress", "Done"),
        ("DL-205", "To Do", "In Review"),
        ("DL-207", "To Do", "In Development"),
    ]

    activities = []
    summaries = []

    for day_offset in range(-30, 1):
        day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
            days=day_offset
        )
        weekday = day.weekday()
        if weekday >= 5:  # skip weekends
            continue

        n_commits = 2 if day_offset % 3 != 0 else 1
        n_reviews = 1 if day_offset % 4 == 0 else 0
        n_prs = 1 if day_offset % 7 == 0 else 0
        n_transitions = 1 if day_offset in (-25, -18, -10, -5, -2) else 0

        for i in range(n_commits):
            msg = commit_messages[(abs(day_offset) + i) % len(commit_messages)]
            repo = repos[(abs(day_offset) + i) % len(repos)]
            sha = f"{abs(day_offset):02x}{i:02x}abcdef"
            activities.append(
                DailyActivity(
                    activity_date=day,
                    source="github",
                    activity_type="commit",
                    external_id=sha,
                    title=msg,
                    url=f"https://github.com/{repo}/commit/{sha}",
                    repository=repo,
                    status="merged",
                )
            )

        for i in range(n_prs):
            title = pr_titles[(abs(day_offset) + i) % len(pr_titles)]
            repo = repos[abs(day_offset) % len(repos)]
            pr_num = 100 + abs(day_offset)
            activities.append(
                DailyActivity(
                    activity_date=day,
                    source="github",
                    activity_type="pr",
                    external_id=str(pr_num),
                    title=title,
                    url=f"https://github.com/{repo}/pull/{pr_num}",
                    repository=repo,
                    status="merged",
                )
            )

        for i in range(n_reviews):
            title = pr_titles[(abs(day_offset) + i + 1) % len(pr_titles)]
            repo = repos[(abs(day_offset) + 1) % len(repos)]
            pr_num = 200 + abs(day_offset)
            activities.append(
                DailyActivity(
                    activity_date=day,
                    source="github",
                    activity_type="review",
                    external_id=str(pr_num),
                    title=f"Reviewed: {title}",
                    url=f"https://github.com/{repo}/pull/{pr_num}",
                    repository=repo,
                    status="approved",
                )
            )

        if n_transitions:
            key, from_s, to_s = jira_transitions[abs(day_offset) % len(jira_transitions)]
            activities.append(
                DailyActivity(
                    activity_date=day,
                    source="jira",
                    activity_type="jira_transition",
                    external_id=key,
                    title=f"{key}: {from_s} → {to_s}",
                    url=f"https://example.atlassian.net/browse/{key}",
                    status=to_s,
                )
            )

        summaries.append(
            DailySummary(
                summary_date=day,
                github_commits=n_commits,
                github_prs=n_prs,
                github_reviews=n_reviews,
                jira_transitions=n_transitions,
                top_repo=repos[abs(day_offset) % len(repos)],
            )
        )

    db.add_all(activities)
    db.add_all(summaries)
    db.commit()
    print(
        f"Seeded: 4 goals, 5 projects, 6 epics, {len(tasks)} tasks "
        f"(8 epic-linked, 3 project-linked, 5 standalone), "
        f"3 notes, 5 reminders, 2 meetings, {len(activities)} activity records."
    )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--wipe", action="store_true", help="Wipe all data before seeding")
    parser.add_argument("--clear", action="store_true", help="Wipe all data and exit (no seed)")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        if args.wipe or args.clear:
            wipe(db)
        if not args.clear:
            seed(db)
    finally:
        db.close()
