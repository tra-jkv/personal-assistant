# Engineering Hub

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

> **Your scrum board is for your team. This one is for you.**

Your goals live in Workday. Your notes are on a scratch pad. Your Jira board is your team's — not yours. And when performance review comes around, you're piecing together what you actually shipped from memory.

**Engineering Hub** is a local personal assistant for engineers. It pulls your work from the tools you already use, gives you your own context layer on top, and makes sure nothing slips through the cracks.

---

### What it does

#### 📦 It knows what you shipped
Syncs your GitHub commits, PRs, and code reviews. Pulls your Jira epics and stories. Stores everything locally — then lets you attach notes, reminders, and goals to the work that actually matters to you. Reports are built from real data: your actual commits, your actual tickets, summarised by day, week, month, or quarter.

#### 🎯 It keeps you aligned
Jira shows what your team is working on. Engineering Hub shows what *you* are working on — and whether it connects to your goals. The goal alignment view on the Epics board splits your active epics into two groups: those tied to a goal, and those that aren't. If you're spending time on work that doesn't map to anything you're being measured on, you can surface that in a 1:1 or check-in before it becomes a problem at review time.

#### 🤖 It has an AI that actually does things
Ask it anything about your work. It can create tasks, update statuses, log notes, set reminders, move things on the board, and track goal progress. In **Plan mode** it shows you what it's about to do before doing it. In **Execute mode** it just does it.

#### 🔌 It's programmable
Every feature is available via a full REST API — the same one the UI uses. Point an external agent at it, write a script, or build your own automations on top of your own data.

---

**Hierarchy:** `Goals` ↔ `Projects` → `Epics` → `Stories` → `Subtasks`

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone https://github.com/your-username/engineering-hub.git
cd engineering-hub
make install       # installs deps and creates .env from .env.example
```

Fill in your API keys in `.env`, then:

```bash
make run           # starts the app at http://localhost:8000
```

## Configuration (`.env`)

```bash
# AI Assistant (required)
GEMINI_API_KEY=your_key_here          # https://ai.google.dev

# Jira sync (required for epic/story sync)
JIRA_BASE_URL=https://yourcompany.atlassian.net
JIRA_EMAIL=you@company.com
JIRA_API_TOKEN=your_token_here        # https://id.atlassian.com/manage-profile/security/api-tokens
JIRA_PROJECT_KEY=ENG
USER_DISPLAY_NAME=Your Name           # used to filter stories assigned to you

# GitHub sync — uses gh CLI by default, no config needed if you run `gh auth login`
# GITHUB_TOKEN=ghp_...               # alternative if not using gh CLI
```

## Features

- **Goals** — yearly objectives with progress %
- **Projects** — kanban, linked to goals and epics
- **Epics** — synced from Jira, drill down to stories and subtasks
- **Tasks** — Jira stories + manual tasks; sync status back to Jira
- **Daily Report** — auto-syncs your GitHub commits/PRs and Jira activity each day
- **AI Assistant** — ask questions about your work; Plan or Execute mode
- **REST API** — every feature is exposed via a documented API; use it to build automations, connect external agents, or integrate with your own AI tooling

## GitHub Sync

```bash
gh auth login   # one-time setup
```

The app will auto-detect your credentials. Syncs commits, PRs, reviews, and Jira transitions incrementally (only new activity since last sync).

## Desktop App (optional)

Wraps the app in a native window via Tauri. Requires Rust:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source ~/.cargo/env   # or restart your terminal
cargo install tauri-cli
cargo tauri dev       # dev mode
cargo tauri build     # distributable
```

## Contributing

PRs welcome. Please:
- Format and lint with `make format && make check`
- Don't commit `.env` or `data/`

Report security issues via [GitHub Security Advisories](https://github.com/your-username/engineering-hub/security/advisories/new) — not public issues.


