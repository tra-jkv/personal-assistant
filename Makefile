.DEFAULT_GOAL := help
.PHONY: help install run seed wipe lint format check

# ── Config ────────────────────────────────────────────────────────────────────

PORT ?= 8000

# ── Help ──────────────────────────────────────────────────────────────────────

help:
	@echo "Engineering Hub"
	@echo ""
	@echo "Usage:"
	@echo "  make install   Install dependencies (requires uv)"
	@echo "  make run       Start the app on http://localhost:$(PORT)"
	@echo "  make seed      Populate DB with dummy data (for screenshots / dev)"
	@echo "  make wipe      Wipe all data from the database"
	@echo "  make lint      Check code with ruff"
	@echo "  make format    Format code with ruff"
	@echo "  make check     Run lint + format check together"

# ── Setup ─────────────────────────────────────────────────────────────────────

install:
	@which uv > /dev/null || (echo "uv not found. Install it: https://docs.astral.sh/uv/getting-started/installation/" && exit 1)
	uv sync
	@if [ ! -f .env ]; then cp .env.example .env && echo "Created .env from .env.example — fill in your API keys"; fi

# ── Dev ───────────────────────────────────────────────────────────────────────

run:
	uv run uvicorn backend.main:app --reload --port $(PORT)

# ── Data ─────────────────────────────────────────────────────────────────────

seed:
	uv run python scripts/seed.py --wipe

wipe:
	uv run python scripts/seed.py --clear

# ── Code quality ──────────────────────────────────────────────────────────────

lint:
	uv run ruff check backend/

format:
	uv run ruff format backend/

check: lint
	uv run ruff format --check backend/
