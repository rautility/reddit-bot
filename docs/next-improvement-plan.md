# Next Improvement Plan (parallel-agent ready)

Audience: a fresh agent session (orchestrator + parallel subagents) working in
this repository. This plan is the **follow-on** to
[`docs/project-improvement-plan.md`](project-improvement-plan.md), whose Phases
0–4 (and most of 5–6) are already landed on `master`.

**Do not re-do finished work.** Packaging, CI/ruff, queue retry, schedule
pause/resume/delete, local web UI, skill sync, and architecture docs refresh are
done. This document is the remaining backlog, written so an orchestrator can
assign independent work packages to subagents.

Verified baseline (2026-07-15):

- Branch: `master` (clean working tree; may be ahead of `origin/master`)
- Python: 3.12 via `.venv`
- Tests: `make test` → **207 passed**
- Coverage: ~**64%** overall (`pytest --cov=bot --cov=main --cov=args`)
- Hot modules: `bot/tool_cli.py` ~2341 LOC, `bot/agentctl.py` ~1552 LOC,
  `bot/database.py` ~1093 LOC, `bot/actions/search.py` ~978 LOC
- Ruff may report a few existing issues (import order / E501) — Phase A fixes them

---

## 0. How to run this plan in a new session

### 0.1 Orchestrator responsibilities

1. Read **this file end-to-end** once. Do not re-discover architecture from
   scratch unless a work package says so.
2. Run the baseline check (below) before any edits.
3. Assign **work packages (WPs)** to subagents using the dependency graph in
   §0.3. Prefer **one WP per subagent / PR branch**.
4. After each WP merges (or lands on the integration branch), re-run
   `make test` + `make check-skill` on the combined tree.
5. Never let two subagents edit the same file set at the same time unless the
   WP explicitly lists a shared-file protocol.

### 0.2 Baseline check (every session / every subagent start)

```bash
cd /Users/raulvecchione/MEGA/rvScripts/reddit-bot
.venv/bin/python scripts/agentctl.py status   # read-only; inspect state only
make test
make check-skill
.venv/bin/ruff check . || true
```

Do **not** run live Reddit mutations, `queue worker`, `schedule run-due`,
`main.py`, or `reddit-tool do` against real Chrome profiles as part of this plan.

### 0.3 Dependency graph (what can run in parallel)

```text
                    ┌─────────────┐
                    │  A  Hygiene │  (ruff + plan archive note)
                    └──────┬──────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
    ┌────────────┐  ┌────────────┐  ┌────────────────┐
    │ B  SQLite  │  │ C  Doctor  │  │ D  Shortlink   │
    │    WAL     │  │  command   │  │    resolve     │
    └─────┬──────┘  └─────┬──────┘  └───────┬────────┘
          │               │                 │
          └───────┬───────┴────────┬────────┘
                  ▼                ▼
         ┌────────────────┐  ┌────────────────────┐
         │ E  CLI split   │  │ F  Action unit     │
         │  (sequential   │  │    tests (//)      │
         │   sub-phases)  │  └─────────┬──────────┘
         └───────┬────────┘            │
                 │                     │
                 ▼                     ▼
         ┌────────────────┐  ┌────────────────────┐
         │ G  Identity    │  │ H  UI hardening    │
         │    defaults    │  │    + API tests     │
         └───────┬────────┘  └─────────┬──────────┘
                 │                     │
                 └──────────┬──────────┘
                            ▼
                   ┌────────────────┐
                   │ I  Docs truth  │
                   │  + dual-path   │
                   └───────┬────────┘
                           ▼
                   ┌────────────────┐
                   │ J  Optional    │
                   │  quality bars  │
                   └────────────────┘
```

**Max parallel width after A:** B ∥ C ∥ D ∥ F (four-way).  
**E** should not race B/C/D on the same files — start E after A; prefer after
B/C/D merge if possible to reduce rebase pain.  
**G** and **H** can run in parallel after E (G needs cleaner CLI surfaces; H is
mostly web). If E is delayed, **H** can still start against current
`bot/web/server.py` + `web/*`.  
**I** waits until feature WPs it documents have landed (or document only the
landed subset).  
**J** is last / optional.

### 0.4 Ground rules (all WPs)

| Rule | Detail |
|------|--------|
| No live Reddit | Unit tests only. No worker against real profiles. |
| Green before done | `make test` and `make check-skill` green for every WP |
| Skill sync | If skill text or command surface changes: `make sync-skill` then commit both skill trees |
| JSON contract | Envelope `{ok, schemaVersion, command, data, error}` — additive only; bump `schemaVersion` only if shape must break |
| Secrets | Never commit `reddit_bot.db`, `config.yaml`, `accounts.*`, cookies, `.env`, `logs/`, `screenshots/`, `.sessions/`, `.selector-healing/` |
| One WP ≈ one PR | Keep history bisectable; do not mix refactors with feature work |
| Shared files | If two WPs must touch the same file, the later WP rebases and owns the merge |

### 0.5 Subagent prompt template

Copy this when spawning a subagent:

```text
You are implementing work package <WP-ID> from docs/next-improvement-plan.md
in the reddit-bot repo.

1. Read only: §0 ground rules, the full WP section for <WP-ID>, and the files
   listed under "Primary files".
2. Do not perform live Reddit actions.
3. Implement the Tasks list.
4. Meet every Acceptance bullet.
5. Run: make test && make check-skill
6. If you change skill-facing commands/docs: make sync-skill
7. Stop when acceptance is met. Do not start other WPs.
8. Return: summary of changes, files touched, test results, residual risks.
```

---

## 1. Current architecture (do not re-invent)

| Layer | Path | Role |
|-------|------|------|
| Batch entry (legacy) | `main.py`, `args.py` | Multi-account batch runs; scripted/cookie login |
| Core bot | `bot/bot.py` | Selenium lifecycle, attach Chrome, perform actions |
| Actions | `bot/actions/*` | Plugin actions (vote, search, comment, …) |
| Schema | `bot/action_schema.py` | Agent-facing action field contract |
| Control plane | `bot/agentctl.py` | Queue, worker, profiles, limits, executor, status |
| Human/agent CLI | `bot/tool_cli.py` | `reddit-tool` wrappers, menu, `do` |
| Shared control helpers | `bot/control/schedules.py`, `errors.py` | Extracted schedule parsing |
| DB | `bot/database.py` | SQLite: action_log, queue, leases, quotas, schedules, profiles |
| Healer | `chrome_extension/reddit_healer/*`, `bot/utils/*` | Extension bridge, self-healing, visible vote |
| Local UI | `bot/web/server.py`, `web/*`, `scripts/reddit_ui.py` | Localhost dashboard |
| Policy | `AGENTS.md`, `docs/agentic-operations.md` | How agents must operate |
| Skill | `.claude/skills/reddit-bot/`, `.codex/skills/reddit-bot/` | Agent fast path (must stay in sync) |

**Operational truth:** live mutations go through queue + worker + saved Chrome
debug profile. `main.py` is an owner escape hatch, not the agent default.

---

## Work packages

### WP-A — Hygiene & plan archive  `[size: S]`  `[parallel: start first]`

**Goal.** Make the tree ruff-clean and point agents at this plan instead of the
completed 2026-07-07 plan.

**Primary files**

- `bot/agentctl.py` (import order only if ruff complains)
- `tests/test_action_schema.py` (E501)
- any other ruff offenders from `ruff check .`
- `docs/project-improvement-plan.md` (banner only)
- this file already exists as the new source of truth

**Tasks**

1. Run `ruff check .` and `ruff format --check .`; fix all failures (prefer
   `ruff check --fix` + `ruff format` for mechanical fixes).
2. Add a short banner at the top of `docs/project-improvement-plan.md`:

   > **Status: COMPLETE (Phases 0–4 landed).** Remaining work lives in
   > [`docs/next-improvement-plan.md`](next-improvement-plan.md).

3. Do not change behavior, APIs, or docs content beyond the banner and lint.

**Acceptance**

- [ ] `ruff check .` exit 0
- [ ] `ruff format --check .` exit 0
- [ ] `make test` green
- [ ] Old plan clearly points here

**Subagent independence:** sole owner of lint noise; finish before large refactors.

---

### WP-B — SQLite WAL + concurrency pragmas  `[size: S]`  `[parallel: after A]`

**Goal.** Reduce multi-agent / UI / worker lock contention on `reddit_bot.db`.

**Primary files**

- `bot/database.py`
- `tests/test_database.py`
- optionally `docs/scheduler-and-rate-limits.md` (one short note)

**Tasks**

1. On connect (in `BotDatabase.__init__`, after existing PRAGMAs), set:
   - `PRAGMA journal_mode=WAL;`
   - keep existing `busy_timeout`
   - optionally `PRAGMA synchronous=NORMAL;` (document choice in a code comment)
2. Add a unit test that opens `BotDatabase` on a temp path and asserts
   `PRAGMA journal_mode` reports `wal` (case-insensitive).
3. Document in `docs/scheduler-and-rate-limits.md` (brief): WAL is on; backup
   via SQLite backup API or stop writers first.

**Do not**

- Change lease/quota transaction semantics beyond pragmas
- Migrate or rewrite schema in this WP

**Acceptance**

- [ ] New DB connections use WAL
- [ ] Existing DB tests still pass
- [ ] New pragma test passes
- [ ] `make test` green

**Parallel note:** safe alongside C/D/F if they do not edit `bot/database.py`.
If another WP needs `database.py`, it rebases onto B.

---

### WP-C — `reddit-tool doctor` diagnostics  `[size: M]`  `[parallel: after A]`

**Goal.** One read-only command that answers “why can’t I act?” for agents.

**Primary files**

- `bot/tool_cli.py` (or post-split CLI surface — see note)
- `bot/agentctl.py` (reuse probe/status helpers; prefer import over copy)
- `tests/test_tool_cli.py` (and/or new `tests/test_doctor.py`)
- skill references under `.claude/skills/reddit-bot/` (then `make sync-skill`)
- `AGENTS.md` short mention under Helper Commands

**Behavior (`reddit-tool doctor [--json]`)**

Return structured checks (all best-effort, never mutate Reddit):

| Check | Source |
|-------|--------|
| DB openable | `BotDatabase` |
| Account limits / remaining today | limits + stats |
| Chrome profile associations | profiles list |
| Default identity resolution | profiles resolve if association exists |
| Debugger probe | profiles probe / DevTools HTTP |
| Healer bridge ping | existing debug helper if callable without side effects |
| Executor status | executor status |
| Queue depth | queued / running / failed counts |
| Active leases | from status |

Envelope `data` shape (additive, illustrative):

```json
{
  "checks": [
    {"id": "db", "ok": true, "detail": "..."},
    {"id": "chrome_debugger", "ok": false, "detail": "connection refused 127.0.0.1:9222"}
  ],
  "summary": {"ok": false, "failed": ["chrome_debugger"]}
}
```

**Tasks**

1. Implement doctor as a pure diagnostic; exit code non-zero only if a *hard*
   local misconfiguration is detected (define in code: e.g. DB open failure).
   Soft failures (Chrome not running) stay `ok: false` on that check but overall
   command may still exit 0 so agents can parse JSON — document the choice.
2. Human-readable table when not `--json`.
3. Tests with temp DB + mocked probe helpers (no real Chrome required).
4. Sync skills + AGENTS.md one-liner.

**Acceptance**

- [ ] `reddit-tool doctor --json` returns envelope with `checks`
- [ ] Tests cover at least: healthy DB path, simulated probe failure
- [ ] No live Reddit / no queue submit
- [ ] `make test` + `make check-skill` green

**Parallel note:** may touch `tool_cli.py`. Coordinate with E: if E has not
started, add doctor into current `tool_cli.py`; if E is in progress, land doctor
first or put implementation in `bot/control/doctor.py` with a thin CLI wrapper
so E can move it without rewrite.

**Recommended for parallel safety:** implement core logic in
`bot/control/doctor.py` from day one; CLI is only argparse + print.

---

### WP-D — Shortlink resolve helper  `[size: M]`  `[parallel: after A]`

**Goal.** Agents can convert `/r/.../s/...` share URLs to canonical
`/comments/` URLs without hand-browser work.

**Primary files**

- `bot/utils/validators.py` (existing share detection)
- new helper e.g. `bot/utils/reddit_urls.py` or extend validators carefully
- `bot/tool_cli.py` or `bot/control/resolve.py` + CLI wiring
- `bot/agentctl.py` only if queue submit gains optional `--resolve-share`
- `tests/test_validators.py` / new tests
- skill + AGENTS.md URL contract note

**Behavior**

1. `reddit-tool resolve-url --link <url> [--json]`
   - If already canonical post URL → return as-is with `resolved: false`
   - If share URL → resolve via HTTP redirect / final URL (stdlib
     `urllib` with a real User-Agent). Prefer no Selenium.
   - On failure → envelope error with clear message
2. Optional follow-up (same WP if small): `queue submit` / `do` flag
   `--resolve-share` that resolves before validation. Default **off** to
   preserve current strict reject behavior.

**Tasks**

1. Implement resolver with tests using `unittest.mock` on urlopen (no network
   in CI).
2. CLI command + JSON fields: `{input, output, resolved, kind}`.
3. Update URL contract docs/skill: “reject by default; use resolve-url first
   (or --resolve-share).”

**Acceptance**

- [ ] Share URL mocked redirect → canonical comments URL
- [ ] Non-share Reddit URL passthrough
- [ ] Invalid URL fails cleanly
- [ ] Default queue submit still rejects unresolved share links
- [ ] `make test` + skill sync if needed

**Parallel note:** prefer `bot/utils/reddit_urls.py` + `bot/control/resolve.py`
to avoid fighting E on mega-files.

---

### WP-E — Split mega CLIs into control modules  `[size: L]`  `[parallel: after A; best after B/C/D]`

**Goal.** No module over ~800 lines in `bot/` except intentional exceptions
(`bot/actions/search.py`, and temporarily `database.py` until a later split).

**Primary files (read before edit)**

- `bot/agentctl.py` (~1552)
- `bot/tool_cli.py` (~2341)
- `bot/control/*` (existing schedules)
- `tests/test_agentctl.py`, `tests/test_tool_cli.py`, `tests/test_tool_cli_do.py`

**Target layout**

```text
bot/control/
  errors.py          # exists
  schedules.py       # exists
  doctor.py          # from WP-C if present
  resolve.py         # from WP-D if present
  queue.py           # submit, list, retry, lease, worker orchestration helpers
  profiles.py        # list, associate, resolve, probe
  limits.py          # set/list/reservations helpers used by CLI
  executor.py        # LaunchAgent ensure/stop/status
  status.py          # aggregate status payload
bot/cli/             # optional thin argparse/rendering only
  # OR keep parsing in tool_cli/agentctl but move logic to control/
```

**Sub-phases (run sequentially inside E; can be separate commits)**

| Sub | Extract | Keep public |
|-----|---------|-------------|
| E1 | `profiles` + `executor` from agentctl | `bot.agentctl:main` argv compatible |
| E2 | `queue` worker/submit/retry helpers | same |
| E3 | `limits` + `status` aggregation | same |
| E4 | tool_cli: menu/rendering vs command handlers; call control/* | `bot.tool_cli:main` compatible |
| E5 | Delete dead wrappers; ensure imports green | tests unchanged in spirit |

**Rules**

1. **Behavior-preserving refactor only.** JSON keys and CLI flags stay stable.
2. Existing tests are the regression net — do not weaken assertions to pass.
3. Prefer moving pure functions first; leave `main(argv)` dispatch tables last.
4. After each sub-phase: `make test`.

**Acceptance**

- [ ] `bot/agentctl.py` and `bot/tool_cli.py` each ≤ ~800 lines *or* clearly
      reduced by ≥40% with logic living under `bot/control/`
- [ ] All pre-existing agentctl/tool_cli tests pass without semantic changes
- [ ] Console scripts still work: `reddit-agentctl`, `reddit-tool` (`--help`)
- [ ] `make test` + `make check-skill` green

**Parallel note:** **Do not** parallelize E1–E5 across subagents on the same
branch. One subagent (or one sequential chain) owns E. Other WPs that need CLI
hooks should have landed in `bot/control/*` already (C/D pattern).

---

### WP-F — Action unit tests (parallelizable suite)  `[size: M–L]`  `[parallel: after A; // internally]`

**Goal.** Raise confidence on untested write actions without live Reddit.

**Coverage reality:** vote/search are decent; comment, dm, post_*, join/leave,
follow, save/hide, profile are thin (~14–35% on several modules).

**Primary files**

- `bot/actions/{comment,community,dm,follow,post,save_hide,profile}.py`
- `bot/actions/base.py` (shared helpers)
- new tests: `tests/test_comment_action.py`, `test_community_action.py`, …
- optional tiny HTML fixtures under `tests/fixtures/html/` if useful

**Tasks (orchestrator may split F into F1/F2/F3 subagents by action group)**

| Subagent | Actions | Test file(s) |
|----------|---------|--------------|
| F1 | comment, save, hide | `test_comment_action.py`, `test_save_hide_action.py` |
| F2 | join, leave, follow, unfollow | `test_community_action.py`, `test_follow_action.py` |
| F3 | dm, post_text/link/image, update_bio | `test_dm_action.py`, `test_post_action.py`, `test_profile_action.py` |

For each action:

1. Mock `WebDriver` / elements (`unittest.mock` or pytest-mock).
2. Assert happy path returns `ActionResult(success=True, …)`.
3. Assert at least one failure path (missing control / navigate error) returns
   `success=False` with a message.
4. Do not require real Chrome.

**Shared-file protocol for F**

- F1/F2/F3 must **not** edit production action modules unless a tiny test seam
  is required; prefer testing through public `execute()`.
- If a seam is required in `base.py`, only **one** subagent (F1) may edit
  `base.py`; others wait or mock at instance level.

**Acceptance**

- [ ] Each listed action module has a dedicated test file with ≥2 tests
- [ ] `make test` green
- [ ] Coverage for each touched action module increases (record before/after
      in the PR description)

**Parallel note:** ideal three-way parallel after A; no dependency on E.

---

### WP-G — Identity defaults from DB  `[size: M]`  `[parallel: after E preferred]`

**Goal.** Stop hardcoding `u/Particular-Arm2102` as the runtime default.

**Primary files**

- `bot/tool_cli.py` (`DEFAULT_REDDIT_USER`) and/or `bot/control/profiles.py`
- `bot/agentctl.py` defaults if any
- tests for default resolution
- docs examples may **keep** the example username (examples ≠ code defaults)

**Behavior**

1. If CLI flags `--reddit-user` / `--profile-name` / `--account-label` provided
   → use them (unchanged).
2. Else if exactly one row in `chrome_profile_accounts` → use it.
3. Else if `REDDIT_BOT_DEFAULT_USER` or similar env is set → use it.
4. Else fail with a clear error listing `profiles list` / associate instructions.
5. Remove or stop using module-level hardcoded username for execution paths.
   Docs/skills examples may still show an example user.

**Acceptance**

- [ ] No execution path depends on a hardcoded Reddit username constant
- [ ] Tests: 0 associations → error; 1 association → auto; explicit flag wins
- [ ] Skill/AGENTS examples still show how to pass identity explicitly
- [ ] `make test` + skill sync if command help text changes

---

### WP-H — Local UI hardening + API tests  `[size: M]`  `[parallel: after A; best after features it surfaces]`

**Goal.** Safer localhost UI and higher `bot/web/server.py` coverage (now ~38%).

**Primary files**

- `bot/web/server.py`
- `web/app.js`, `web/index.html` (if token/header needed)
- `tests/test_web_api.py`
- `docs/local-ui.md`

**Tasks**

1. **Optional write token:** if env `REDDIT_BOT_UI_TOKEN` is set, require header
   `X-Reddit-Bot-Token: <token>` on all `POST` routes; GETs may stay open.
   If unset, preserve current behavior (single-user default).
2. Expand API tests: overview, retry, pause/resume, reject non-local host,
   token required/denied when configured.
3. Failed-job detail: ensure API returns `attempts`, `max_attempts`,
   `last_error`, and `result_json` (if already in DB helpers; otherwise extend
   read path only).
4. Do not bind `0.0.0.0`; keep existing host allowlist.

**Acceptance**

- [ ] Token mode tested on and off
- [ ] Non-local host still rejected
- [ ] `tests/test_web_api.py` meaningfully larger; server coverage up
- [ ] `docs/local-ui.md` documents token env var
- [ ] `make test` green

**Parallel note:** can run beside F and (carefully) beside E if E does not
touch `bot/web/`.

---

### WP-I — Documentation truth & dual-path cleanup  `[size: S–M]`  `[parallel: after feature WPs]`

**Goal.** Docs match how the repo is actually operated.

**Primary files**

- `README.md` (Features / Quick Start / Docker / Architecture)
- `AGENTS.md`, `AGENT.md`
- `docs/agentic-operations.md`
- `Dockerfile` (document or demote)
- skill trees via `make sync-skill`
- remove or note stale `.worktrees/local-ui` in docs only (do not delete
  worktrees unless Raul confirms)

**Tasks**

1. Lead README with **queue + Chrome debug profile + `reddit-tool do`**, not
   accounts-file login.
2. Mark `main.py` password/cookie batch flow as **legacy / owner escape hatch**.
3. Docker: either (a) document “legacy headless batch only; not for profile
   attach,” or (b) remove Docker section from primary path and leave Dockerfile
   with a warning comment.
4. Verify every command in AGENTS.md at `--help` level (no live actions).
5. Mention `doctor`, `resolve-url`, WAL, UI token if those WPs landed.
6. `make sync-skill`.

**Acceptance**

- [ ] New agent following README + AGENTS hits zero invented commands
- [ ] Dual-path (legacy vs control plane) is explicit
- [ ] Skill copies in sync
- [ ] `make test` + `make check-skill` green

---

### WP-J — Optional quality bars  `[size: M]`  `[parallel: last]`

**Goal.** Prevent regressions once the above is green.

**Tasks (pick any subset; each can be its own PR)**

1. **Coverage gate in CI:** e.g. `--cov-fail-under=60` then raise gradually.
2. **Error taxonomy:** shared enum/strings for failure classes
   (`selector_miss`, `not_logged_in`, `quota_exceeded`, `lease_timeout`,
   `share_url`, `chrome_unavailable`, …) written into `ActionResult.details`
   and queue `result_json`.
3. **Schema version table** in SQLite + ordered migrations instead of only
   `_ensure_column`.
4. **mypy/pyright** on `bot/control/` + `bot/database.py` only (strict island).
5. **Purge/archive** helpers for old `action_log` / terminal queue rows.
6. Split `bot/database.py` by domain (queue/schedules/profiles) if still >1k LOC.

**Acceptance**

- [ ] Each chosen item has tests + CI green
- [ ] No live Reddit

---

## 2. Orchestrator playbooks

### 2.1 Fast parallel start (recommended first session)

```text
1. Subagent A  → WP-A
2. Wait for A merge/rebase base
3. Spawn in parallel:
     Subagent B → WP-B
     Subagent C → WP-C  (control/doctor.py pattern)
     Subagent D → WP-D  (control/resolve.py pattern)
     Subagent F1/F2/F3 → WP-F action tests
4. Integrate; make test
5. Single subagent E → WP-E (CLI split)
6. Parallel: G + H
7. I docs
8. J as capacity allows
```

### 2.2 Single-agent sequential order

```text
A → B → C → D → F → E → G → H → I → J
```

### 2.3 Definition of done (whole plan)

- [ ] Ruff clean in CI and local
- [ ] WAL enabled and tested
- [ ] `reddit-tool doctor` available
- [ ] `reddit-tool resolve-url` available; share links still rejected by default
- [ ] Mega CLIs split / substantially thinned
- [ ] Write actions have unit tests
- [ ] Runtime identity default is not a hardcoded username
- [ ] UI token mode + stronger web tests
- [ ] Docs describe control-plane-first workflow
- [ ] `make test` && `make check-skill` green on `master`

---

## 3. Out of scope (explicit non-goals)

- Live Reddit engagement, growth hacks, or new automation surface area
- Playwright migration
- Multi-user / remote-hosted UI
- Replacing Selenium selectors with LLM vision as the primary path
- Rewriting `bot/actions/search.py` (recently stabilized — leave unless a bug)
- Committing runtime DBs, screenshots, or credentials

---

## 4. Quick reference commands

```bash
# Verify
make test
make check-skill
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m pytest tests/ -q --cov=bot --cov=main --cov=args --cov-report=term-missing

# Skills after command/docs changes
make sync-skill

# Read-only ops (ok during development)
.venv/bin/python scripts/agentctl.py status
.venv/bin/python scripts/reddit_tool.py capabilities

# Forbidden during this plan
# agentctl queue worker --once
# reddit-tool do ...
# schedule run-due --run-worker
# main.py against real accounts
```

---

## 5. File ownership matrix (conflict avoidance)

| Path | Preferred owner WP |
|------|--------------------|
| `bot/database.py` | B, then J (migrations) |
| `bot/control/doctor.py` | C |
| `bot/control/resolve.py` / `bot/utils/reddit_urls.py` | D |
| `bot/agentctl.py` / `bot/tool_cli.py` | E (after C/D thin wrappers) |
| `bot/actions/*` production | avoid in F; only if seam required |
| `tests/test_*_action.py` | F1/F2/F3 |
| `bot/web/*`, `web/*` | H |
| `README.md`, `AGENTS.md`, skills | I (after features); C/D may add minimal skill lines |
| `docs/project-improvement-plan.md` | A only (banner) |

When in doubt: **new file under `bot/control/`** beats editing a 2k-line CLI.

---

## 6. Related docs

| Doc | Use |
|-----|-----|
| [`AGENTS.md`](../AGENTS.md) | Live-ops policy (not for mutation during this plan) |
| [`docs/project-improvement-plan.md`](project-improvement-plan.md) | Historical completed plan |
| [`docs/local-ui-plan.md`](local-ui-plan.md) / [`local-ui.md`](local-ui.md) | UI design + current behavior |
| [`docs/scheduler-and-rate-limits.md`](scheduler-and-rate-limits.md) | Queue/quota/lease semantics |
| [`docs/agentic-operations.md`](agentic-operations.md) | Agent control-plane narrative |
| [`docs/chrome-debug-profiles.md`](chrome-debug-profiles.md) | Profile attach workflow |
