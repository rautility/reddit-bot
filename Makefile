PY ?= .venv/bin/python

.PHONY: sync-skill check-skill test ui

# Mirror the reddit-bot skill from .claude/skills to .codex/skills.
sync-skill:
	$(PY) scripts/sync_skills.py

# Fail if the two skill copies have drifted (also enforced by the test suite).
check-skill:
	$(PY) scripts/sync_skills.py --check

test:
	$(PY) -m pytest tests/ -q

ui:
	$(PY) scripts/reddit_ui.py
