# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-04-12

### Added
- Seed script (`scripts/seed.py`) with realistic dummy data for screenshots and local dev
- `make seed` and `make wipe` Makefile targets
- Screenshots in README (dashboard, goals, epics, tasks, reports, AI assistant)

### Fixed
- Tasks board `/tasks/` returning 500 due to invalid Jinja2 `sum()` filter call
- Tauri `beforeDevCommand` using system `python3` instead of `uv` venv
- PR review sync returning 0 — now requires `GITHUB_ORGS` env var and queries correctly
- Epic status values in seed data mismatched Kanban column definitions (epics not showing)

## [0.1.0] - 2026-04-12

### Added
- Goals — yearly objectives with progress tracking, linked to projects
- Projects — Kanban board, linked to goals and Jira epics
- Epics — synced from Jira, with goal alignment view
- Tasks — Jira stories + manual tasks, sync status back to Jira
- Daily Report — incremental sync of GitHub commits, PRs, reviews, and Jira activity
- Reports — daily, weekly, monthly, quarterly, and yearly views with AI narrative
- AI Assistant — Gemini-powered agent with Plan and Execute modes
- Reminders — priority-based, linked to projects
- Notes — free-form, linked to projects
- Meetings — meeting notes with action items
- REST API — all features exposed via API
- Tauri desktop app wrapper (optional)
