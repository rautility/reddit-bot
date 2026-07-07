# Weekly Log Maintenance

This checklist is for the scheduled Codex maintenance task for this repository.

## Read First

- `/Users/raulvecchione/MEGA/rvScripts/reddit-bot/logs/reddit-bot.log`
- `/Users/raulvecchione/MEGA/rvScripts/reddit-bot/logs/reddit-healer-debug.log`
- `/Users/raulvecchione/MEGA/rvScripts/reddit-bot/.selector-healing/diagnostics/`
- `/Users/raulvecchione/MEGA/rvScripts/reddit-bot/screenshots/`
- `/Users/raulvecchione/MEGA/rvScripts/reddit-bot/docs/chrome-debug-profiles.md`

## Routine

1. Inspect recent `ERROR` and `WARNING` records in the log files.
2. Group failures by root cause before editing code.
3. Use the Browser tool when a failure needs browser-visible verification, selector inspection, or a UI reproduction path.
4. Prefer saved Chrome debug profiles and `scripts/reddit_healer_debug.py` for local browser diagnostics.
5. Implement code, test, and documentation fixes that are clearly supported by the logs.
6. Run focused tests first, then broader tests when shared behavior changed.
7. Report the log findings, fixes made, tests run, and any remaining manual blocker.

## Authorization

The scheduled task is authorized to make local code, test, and documentation fixes or improvements in this repository when they are directly supported by the logs or browser diagnostics.

Do not perform live Reddit actions, publish content, send messages, vote, follow, join, or change account state unless Raul gives a separate exact instruction for that run.
