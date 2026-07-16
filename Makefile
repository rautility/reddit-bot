PY ?= .venv/bin/python

.PHONY: sync-skill check-skill test test-cov ui

# Mirror the reddit-bot skill from .claude/skills to .codex/skills.
sync-skill:
	$(PY) scripts/sync_skills.py

# Fail if the two skill copies have drifted (also enforced by the test suite).
check-skill:
	$(PY) scripts/sync_skills.py --check

# Fast default test path (no coverage gate).
test:
	$(PY) -m pytest tests/ -q

# CI-aligned coverage run with fail-under gate (start at 60%, raise gradually).
test-cov:
	$(PY) -m pytest tests/ -q --cov=bot --cov=main --cov=args --cov-report=term-missing --cov-fail-under=60

ui:
	$(PY) scripts/reddit_ui.py
