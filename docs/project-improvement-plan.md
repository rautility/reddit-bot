# Project Improvement Plan (for Codex)

> **Status: COMPLETE (Phases 0–4 landed).** Remaining work lives in
> [`docs/next-improvement-plan.md`](next-improvement-plan.md).

Audience: an autonomous coding agent (Codex) working in this repository.
Goal: land in-flight work, fix packaging/CI/hygiene debt, close pre-spec'd
control-plane gaps, then build the local UI. Work the phases **in order** —
later phases depend on earlier ones.

All findings below were verified against the working tree on 2026-07-07
(branch `search-upvote-reliability`, `.venv` Python 3.12.12, 188 tests passing).

---

## Ground rules (apply to every phase)

- **Never perform live Reddit actions** during this work. `AGENTS.md` is the
  policy of record. Do not run `main.py`, `agentctl queue worker`, or
  `schedule run-due` against real Chrome profiles as part of development or
  testing. Unit tests only.
- Test/verify loop: `make test` (i.e. `.venv/bin/python -m pytest tests/ -q`)
  and `make check-skill` must be green before every commit.
- If you touch anything the skill references, run `make sync-skill` —
  `.claude/skills/reddit-bot/` and `.codex/skills/reddit-bot/` must not drift
  (enforced by `tests/test_skill_sync.py`).
- Do not commit `reddit_bot.db`, `config.yaml`, `accounts.*`, links files,
  cookies, or anything under `logs/`, `screenshots/`, `.sessions/`,
  `.selector-healing/`.
- The `reddit-tool`/`agentctl` JSON envelope (`{ok, schemaVersion, command,
  data, error}`) is a stable contract — additive changes only; bump
  `schemaVersion` if you must change shape.
- One phase per PR (or per merge to `master`), each independently green.

---

## Phase 0 — Land the in-flight work (do this first)

**Problem.** The repository's entire agent control plane exists only as
*uncommitted* files in the `search-upvote-reliability` working tree. Untracked:
`bot/agentctl.py` (1,601 lines), `bot/action_schema.py`, `bot/skills_sync.py`,
`bot/utils/chromedriver.py`, `bot/utils/visible_vote.py`,
`scripts/agentctl.py`, `scripts/reddit_tool.py`, `scripts/sync_skills.py`,
`Makefile`, `AGENTS.md`, `docs/agentic-operations.md`,
`docs/scheduler-and-rate-limits.md`, `docs/weekly-log-maintenance.md`,
`docs/local-ui-plan.md`, `.claude/skills/`, `.codex/skills/reddit-bot/`, and
seven test files. On top of that, 27 tracked files carry uncommitted
modifications. A `git clean`/reclone loses all of it, and other branches can't
see it: the `codex/local-ui` worktree (historically at `.worktrees/local-ui`,
based on an older `master`) was missing the backend the UI plan builds on.
**Note (2026-07):** the local UI has landed on `master` (`bot/web/`, `web/`,
`docs/local-ui.md`, `make ui`). Any leftover `.worktrees/local-ui` directory is
stale historical context only — do not treat it as the source of truth, and do
not delete worktrees unless Raul confirms.

**Tasks.**

1. Review `git status` and split the work into logical commits on
   `search-upvote-reliability`. Suggested grouping:
   - `.gitignore` fixes (see below) — commit first so runtime dirs stop
     showing up as untracked.
   - Control plane: `bot/agentctl.py`, `bot/action_schema.py`,
     `bot/skills_sync.py`, `scripts/agentctl.py`, `scripts/reddit_tool.py`,
     `scripts/sync_skills.py`, `Makefile` + their tests
     (`tests/test_agentctl.py`, `tests/test_action_schema.py`,
     `tests/test_skill_sync.py`, `tests/test_tool_cli_do.py`).
   - Chrome/driver utilities: `bot/utils/chromedriver.py`,
     `bot/utils/visible_vote.py` + `tests/test_chromedriver.py`,
     `tests/test_visible_vote.py`, `tests/test_reddit_healer_debug.py`.
   - Docs & skills: `AGENTS.md`, `AGENT.md`, `docs/*.md`, `.claude/skills/`,
     `.codex/skills/reddit-bot/`, deletion of
     `.codex/skills/reddit-bot-debug-chrome/`, `README.md`.
   - Remaining modified source/tests (the search_upvote reliability
     follow-ons): `bot/actions/*`, `bot/bot.py`, `bot/database.py`,
     `bot/reporting.py`, `bot/utils/*`, `chrome_extension/reddit_healer/*`,
     `main.py`, `args.py`, `config.example.yaml`, `pyproject.toml` + tests.
   - `uv.lock` (keep it — see Phase 1).
2. Before the first commit, fix `.gitignore` so runtime artifacts are excluded:
   add `.webdriver/`, `.worktrees/`, `.last30days/`, `.uv-cache/`,
   `.pytest_cache/`, `.venv/`. Do **not** commit those directories.
   (`.claude/` and `.codex/` skills SHOULD be committed — they're sources.)
3. Sanity-check every commit for secrets: no `accounts.*`, no `config.yaml`,
   no `*.db`, no cookie files. The global `*.txt` ignore rule currently hides
   links/accounts files — keep that behavior until Phase 1 replaces it
   deliberately.
4. Merge `search-upvote-reliability` into `master` (PR to
   `github.com/markmelnic/reddit-bot` if remote review is wanted; a local
   merge is acceptable — this is Raul's operational repo).
5. Rebase or recreate `codex/local-ui` on the new `master` so the UI work
   (Phase 4) starts from a tree that actually contains `bot/tool_cli.py`,
   `bot/agentctl.py`, and `docs/local-ui-plan.md`.

**Acceptance.** `git status` is clean except for genuinely local files;
`master` contains the control plane, docs, skills, and Makefile; `make test`
green on `master`; `codex/local-ui` is based on the new `master`.

---

## Phase 1 — Packaging, dependency, and ignore hygiene

**Problem 1: the package does not build.** `pip install .` / `uv sync` /
`uv run` fail with *"Multiple top-level packages discovered in a flat-layout:
['bot', 'logs', 'screenshots', 'chrome_extension']"* because `pyproject.toml`
relies on setuptools auto-discovery and the repo root contains non-package
directories. (Verified: `uv run pytest` dies at the build step.)

- Add explicit discovery to `pyproject.toml`:

  ```toml
  [tool.setuptools]
  py-modules = ["main", "args"]

  [tool.setuptools.packages.find]
  include = ["bot*"]
  ```

- Verify `pip install -e ".[dev]"` and `uv run pytest -q` both succeed, and
  the `reddit-bot` / `reddit-agentctl` / `reddit-tool` console scripts resolve.

**Problem 2: two dependency sources drift.** `requirements.txt` duplicates
`pyproject.toml` (currently in sync, kept so only by hand). Make
`pyproject.toml` canonical:

- Delete `requirements.txt`; update the Dockerfile, CI workflow, and README
  install instructions to `pip install -e ".[dev]"` (or `uv sync --extra dev`).
- Keep `uv.lock` committed and document uv as the preferred local workflow in
  README (the lock already exists; make it useful).

**Problem 3: the `.gitignore` is a ~400-line Visual Studio template** with
project rules appended, including a global `*.txt` / `*.exe` ignore that
silently hides any text file. Replace with a short, intentional Python
gitignore that preserves the effective project rules:
`__pycache__/`, `.venv/`, `.pytest_cache/`, `.uv-cache/`, `logs/`,
`screenshots/`, `.sessions/`, `.selector-healing/`, `.webdriver/`,
`.worktrees/`, `.last30days/`, `reddit_bot.db`, `config.yaml`,
`accounts.*`, `!config.example.yaml`, `*.cookies`, `*.bin`, `.env*` with
`!.env.example`, `.DS_Store`. Replace the blanket `*.txt` with explicit
patterns (`links*.txt`, `accounts*.txt`, `proxies*.txt`, `credentials.txt`)
so real docs/text fixtures are not silently unignorable. Verify with
`git status --ignored` that nothing sensitive becomes trackable.

**Acceptance.** `uv run pytest -q` passes from a clean checkout;
`pip install -e ".[dev]"` works; one dependency source; `.gitignore` under
~60 lines with all runtime dirs covered.

---

## Phase 2 — CI and quality gates

**Current state.** `.github/workflows/ci.yml` is named "lint-and-test" but has
no lint step, installs from the (to-be-deleted) `requirements.txt`, and only
triggers on `master`/`main` — so branch work is never CI-tested. There is no
linter or formatter configured anywhere. The suite passes with 108 warnings,
mostly `datetime.utcnow()` deprecations.

**Tasks.**

1. Update CI:
   - Trigger on pull requests to any branch plus pushes to `master`.
   - Install via `pip install -e ".[dev]"` (or uv).
   - Steps: `ruff check .`, `ruff format --check .`, `pytest tests/ -q`,
     `make check-skill`.
   - Keep the 3.9→3.12 matrix **only if** the 3.9 floor is real; the dev
     environment is 3.12 and nothing local tests 3.9. Recommended: bump
     `requires-python = ">=3.10"`, matrix `["3.10", "3.12"]`, and update the
     README badge. (Code already uses `from __future__ import annotations`
     consistently, so 3.9 likely works — but don't pay a 4-version matrix for
     a floor nobody uses.)
2. Add ruff to the `dev` extra with a minimal config in `pyproject.toml`
   (start with `E`, `F`, `I`, `UP`, `B`; line-length matching the existing
   style). Auto-fix mechanically; do not hand-refactor logic in this phase.
3. Kill the `datetime.utcnow()` deprecations in `bot/database.py`,
   `bot/agentctl.py`, `bot/reporting.py`, `bot/tool_cli.py`. **Caution:** DB
   rows and lease/schedule comparisons store ISO strings; switching to
   `datetime.now(timezone.utc)` changes `isoformat()` output (adds `+00:00`)
   and string-compares against old rows would break. Introduce one shared
   helper (e.g. `bot/utils/clock.py` with `utc_now()` / `utc_now_iso()`) that
   preserves the existing stored format (naive-UTC string) while using
   non-deprecated APIs, and use it everywhere. Add a regression test that new
   timestamps interleave correctly with pre-existing DB rows.
4. Add `filterwarnings` to pytest config to fail on *this repo's own*
   deprecation warnings once fixed, so they can't creep back.

**Acceptance.** CI green on a PR branch with lint + format + tests +
skill-drift check; `pytest -q` shows zero repo-originated warnings; ruff clean.

---

## Phase 3 — Control-plane gaps (pre-spec'd, UI-independent)

These are already specified in detail in
[docs/local-ui-plan.md §4](local-ui-plan.md) — implement them exactly as
written there. They are valuable from the terminal even if the UI never ships,
and they are hard prerequisites for Phase 4.

1. **Retry failed queue jobs** (§4.1): `BotDatabase.retry_queue_job(job_id)`,
   `BotDatabase.retry_failed_jobs(account)`, `agentctl queue retry --id|--all
   [--account]`, `reddit-tool queue retry ...`, plus tests (failed→queued
   transition, exhausted-attempts bump of `max_attempts`, `--all` filtering,
   no-op on non-failed jobs).
2. **Schedule pause / resume / delete** (§4.2): `agentctl schedules
   set-status --id --status`, `BotDatabase.delete_schedule(schedule_id)`,
   `agentctl schedules delete --id`, `reddit-tool` wrappers, tests.
3. **Daily history helper** (§4.3): `BotDatabase.get_daily_action_history(
   account, days)` returning zero-filled last-N-days rows, tests.

Mirror the test style of `tests/test_agentctl.py` / `tests/test_tool_cli.py`
(temp DB via `BotDatabase`, in-process `main([...])` calls, JSON assertions).
Update `AGENTS.md` and the skill references with the new subcommands, then
`make sync-skill`.

**Acceptance.** New subcommands emit the standard JSON envelope; a terminally
failed job can be flipped back to `queued` and picked up by a worker lease;
schedules can be paused/resumed/deleted without resending rrule/links;
`make test` green.

---

## Phase 4 — Local web UI

Execute [docs/local-ui-plan.md](local-ui-plan.md) end-to-end (its §4 backend
gaps are done by Phase 3, so start at its §6 step 2: server skeleton, read
endpoints, write endpoints, frontend, launcher, tests). Key constraints from
that plan, restated because they are safety-relevant:

- Bind `127.0.0.1` only; never `0.0.0.0`.
- All mutations go through `agentctl`/`tool_cli` in-process (the
  `_agentctl_payload` redirect pattern) — no hand-written INSERTs, no
  subprocesses, no new scheduler.
- Zero-build frontend (plain HTML/JS/CSS), stdlib `http.server` backend, no
  new runtime dependencies.
- Confirm-step in the UI before any live-action submission ("Now" mode and
  `run-due` perform real Reddit actions).

**Acceptance.** The plan's own §7 acceptance list, plus `make ui` documented
in README.

---

## Phase 5 — Code health (after features, not before)

Lower priority; do only after Phases 0–4 are merged.

1. **Split the two mega-modules.** `bot/tool_cli.py` (2,275 lines) and
   `bot/agentctl.py` (1,601 lines) each mix argument parsing, command logic,
   rendering, and the interactive menu. Extract by topic (queue / schedules /
   profiles / limits / menu) into submodules under `bot/cli/` while keeping
   `bot.tool_cli:main` and `bot.agentctl:main` entry points and the JSON
   envelope byte-compatible. The existing tests are the regression net — do
   not weaken them; refactor until they pass unchanged.
2. **Coverage baseline.** Add `pytest-cov` to the dev extra; record baseline
   in the README testing section. Priority gaps to close: `main.py`
   orchestration paths, `bot/bot.py` attach-mode flows, error paths in
   `bot/utils/chrome_extension_bridge.py`.
3. **Dead weight check.** `bot/ghost_logger.py` is a legacy no-op — delete it
   if nothing imports it. Audit `bot/utils/mouse.py`'s `bezier`/`numpy`
   dependency: it forces heavyweight installs for a rarely-used `--human-mouse`
   flag; consider making it an optional extra (`pip install ".[mouse]"`) with
   a clear runtime error when missing.

**Acceptance.** No module over ~800 lines in `bot/` except `bot/actions/search.py`
(recently stabilized — leave it alone); coverage reported in CI; unused code
removed or justified in a comment.

---

## Phase 6 — Documentation truth pass

1. README `Architecture` tree is stale: it omits `bot/actions/search.py`,
   `bot/action_schema.py`, `bot/agentctl.py`, `bot/tool_cli.py`,
   `bot/skills_sync.py`, `bot/utils/chromedriver.py`,
   `bot/utils/visible_vote.py`, `bot/utils/self_healing.py`,
   `bot/utils/chrome_extension_bridge.py`, `scripts/`, `chrome_extension/`,
   and `docs/`. Regenerate it from the actual tree.
2. Update README install/test instructions to match Phase 1 (pyproject/uv,
   no `requirements.txt`) and Phase 2 (Python floor, badge).
3. Verify every command shown in `AGENTS.md`, `AGENT.md`, and
   `docs/*.md` still runs (`--help` level check is fine — **no live actions**).
   Add the Phase 3 subcommands and Phase 4 UI to the relevant docs.
4. `make sync-skill` and commit the synced copies.

**Acceptance.** A new contributor (or agent) following README + AGENTS.md
verbatim hits zero broken commands; skill copies in sync.

---

## Suggested execution order & sizing

| Phase | Size | Depends on |
|---|---|---|
| 0 Land in-flight work | S (mostly git surgery) | — |
| 1 Packaging & hygiene | S | 0 |
| 2 CI & quality gates | M | 1 |
| 3 Control-plane gaps | M | 0 (2 recommended) |
| 4 Local web UI | L | 3 |
| 5 Code health | M | 0–4 |
| 6 Docs truth pass | S | all |

Phases 1+2 can be one PR if kept mechanical. Phase 3 and Phase 4 map cleanly
onto the existing `codex/local-ui` worktree once it is rebased in Phase 0.
