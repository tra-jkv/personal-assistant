# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.7] - 2026-04-14

### Fixed
- **Sync architecture overhaul** — eliminated dual sync systems (`DailyReportSync` and `SyncManager`); all sync paths (startup, daily-report Sync Now, reports page) now route through a single `BackgroundSync` pipeline
- **"Already up to date" short-circuit** in `main.py` permanently blocked re-syncing today after any sync had run — removed; startup always calls `run_full_sync` which falls through to `_sync_today_via_events`
- **Chart vs stat-cards mismatch** — `_sync_today_via_events()` now upserts `DailySummary` after writing `DailyActivity` rows; the trend chart (reads `DailySummary`) now matches the stat cards (reads `DailyActivity`)
- **PR query** — changed from `created:` to `updated:` so PRs merged or updated today always appear, not just PRs opened today
- **Historical reviews** — Events API used for months within the 90-day window (exact submission timestamps); Search API retained for older history
- **Jira transitions silently discarded** — `issues.append` → `transitions.append` in `get_transitions_since`; transitions were never saved since v0.1.0
- **Today query upper bound** — `get_today_report_from_db` now has a `< tomorrow` filter so future rows don't bleed into today's view

### Added
- Auto full-history sync on startup when `DailyActivity` table is empty (fresh install or wiped DB)
- `scripts/full_sync.py` — CLI for manual history rebuilds (`--start`, `--end`, `--jira-only`, `--activity-only`)

## [0.2.6] - 2026-04-14

### Fixed
- **GitHub reviews missing from dashboard** — the Sync button used the Search API (`reviewed-by:` + `updated:{date}`) which matches PRs by `updated_at`, silently skipping reviews on PRs last updated before today. Added `_sync_today_via_events()` which re-syncs today's reviews via the Events API (exact review submission timestamps) at the end of every sync run

## [0.2.5] - 2026-04-14

### Fixed
- **GitHub review title and URL empty** — `PullRequestReviewEvent` payload returns a stripped `pull_request` object that omits `title` and `html_url`. PR URL is now constructed from `repo + pr_number`; branch ref (`head.ref`) is used as title fallback

## [0.2.4] - 2026-04-14

### Added
- **Drag-and-drop kanban boards** for tasks and epics — drag cards between columns to update status, drag within a column to reorder; order is persisted to the database
- Drag handle (⠿) appears on card hover; ghost/dragging visual states for both card types
- `POST /tasks/{id}/reorder` — persist within-column task order
- `POST /epics/{key}/move` — move epic to a different status column
- `POST /epics/{key}/reorder` — persist within-column epic order

### Changed
- Kanban board ordering now respects saved drag position before falling back to `jira_updated_at`

### DB
- Added `position` column to `epics` table (auto-migrated on startup)

## [0.2.3] - 2026-04-14

### Fixed
- **Subtask sync broken for next-gen Jira projects** — switched all API calls from deprecated `search_issues` to `enhanced_search_issues`; batches were silently failing and dropping subtasks
- **Arbitrary result caps** — removed hardcoded `maxResults` limits; now fetches all results (`maxResults=False`). Previously capped at 100 epics and 200 stories
- **AI missing subtask details for stories outside current sprint** — context builder now includes full subtask details for all stories, not just current sprint
- **Reminder filter bug** — `not Reminder.is_done` was always `True` in Python; fixed to `Reminder.is_done == False`

### Added
- **Incremental Jira sync** — only fetches epics/stories/subtasks updated since the last sync (5-min overlap buffer); full sync available via `sync_jira_epics_and_stories(full=True)`
- **Richer AI context** — full Project → Epic → Story → Subtask hierarchy with all subtasks (done marked ✓), full note content, all meetings and links

### Changed
- Kanban board sorted by `jira_updated_at DESC` so recently active work appears on top

## [0.2.2] - 2026-04-14

### Fixed
- **AI assistant ignoring subtask requests** — the system prompt hardcoded `never list subtasks`; AI now shows subtasks grouped under their parent story when explicitly asked

## [0.2.1] - 2026-04-14

### Fixed
- **Subtasks not syncing for next-gen Jira stories** — story-type children (next-gen Epic → Story → Story hierarchy) were silently dropped because the `parent` field was not requested in the Jira API call; added `fields=summary,status,assignee,parent,issuetype` to `get_subtasks_for_stories`

### Added
- **Refresh from Jira** button on story detail pages — re-fetches subtasks on demand without a full sync
- `POST /tasks/{task_id}/sync-subtasks` API endpoint for per-story subtask refresh

## [0.2.0] - 2026-04-13

### Fixed
- **HTMX partial injection bug** — clicking Save on Notes, Meetings, Projects, and Standup forms caused the full page (including sidebar) to be injected into `#main-content`, duplicating the navigation. All POST handlers now detect the `HX-Request` header and return content-only partial templates

### Removed
- **Standup feature** — router, templates, `StandupLog` model, DB table, and all references removed; superseded by the Daily Report feature

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
- Seed script (`scripts/seed.py`) with realistic dummy data for local dev
