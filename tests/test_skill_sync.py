"""Guard: the .codex copy of the reddit-bot skill must match the .claude canonical."""

from bot import skills_sync


def test_codex_skill_matches_canonical():
    problems = skills_sync.diff()
    assert problems == [], (
        "reddit-bot skill copies drifted. Run `make sync-skill` "
        "(or python scripts/sync_skills.py). Differences: " + "; ".join(problems)
    )
