---
name: add-script
description: >
  You are the **/scripts organization** skill for `harqis-work`.
user-invocable: true
allowed-tools: Bash Read Glob Grep Edit Write
---

You are the **/scripts organization** skill for `harqis-work`.

Any time a script is added to, created in, or moved within `scripts/`, it must land in the
right place and stay wired up. This skill is the rulebook.

---

## The two top-level buckets

| Bucket | Location | What belongs here |
|---|---|---|
| **Deploy / runtime** | `scripts/` (root) | Bringing the stack up/down, launching daemons, syncing config between machines, network/infra policy. Examples: `deploy.py`, `launch.py`, `sync-to-host.ps1`, `tailscale/`. |
| **Agent-support** | `scripts/agents/<bucket>/` | agent-driven automation, the repo-quality / health / test tooling those agents drive, the HFL learning loop, and the worktree/window cleanup that keeps the fleet tidy. Always lives inside a **context subfolder** (below) — never loose at `scripts/agents/` root. |

**Top-level decision rule:** if the script's primary job is *deploying or running the
platform*, it's root. If it *exists to support the agent system or repo automation* (even
indirectly, like cleaning up agent worktrees or auditing repo metadata), it goes under
`agents/<bucket>/`. When genuinely ambiguous, ask the user with the two buckets laid out.

## The agents/ context subfolders

Every `scripts/agents/` script lives in exactly one context folder. Pick by what the
script is *for*:

| Subfolder | Context | Examples |
|---|---|---|
| `repo-quality/` | Audits, scans, and agent-driven repo maintenance / improvement / PRs | `manifesto_audit{,_agent}.py`, `daily_improvement_scout.py`, `weekly_claude_pr.py`, `run_agent_prompt.py`, `migrate_to_core_{scan,agent}.py` |
| `learning/` | Agent reasoning capture + the HFL lessons loop | `reasoning_capture.py`, `agent_learning_hook.py`, `lessons_extractor.py`, `weekly_lessons_extraction.py` |
| `testing/` | Test execution + reporting | `run_test_suite.py`, `daily_test_farm_email.py`, `smoke-tests.sh` |
| `diagnostics/` | Environment + credential health checks / re-auth | `check_env_health.py`, `check_plaud_token.py`, `reauth_gmail_send.py` |
| `dumps/` | Device dump ops (pull/back-fill/summarize) | `pull_dumps.py`, `run_dumps_summary_retro.py` |
| `fleet/` | Agent worktree / terminal-window / process cleanup | `cleanup-worktrees.sh`, `close-completed-windows.sh`, `cleanup-loop.sh`, `install-cleanup-job.sh`, `launchd/` |

**Subfolder decision rule:** match the script's *domain* to a row above. Keep tightly
coupled pairs together (a deterministic tool and its agent-delegated runner — e.g.
`migrate_to_core_scan.py` + `migrate_to_core_agent.py` — live in the same folder). If a
new script fits none of these cleanly, propose a new subfolder name to the user with a
one-line rationale rather than dropping it loose at `agents/` root or forcing a bad fit.

---

## Rules for a NEW script

1. **Place it by bucket, then by context subfolder** (above). New agent/automation tooling
   goes to `scripts/agents/<bucket>/`, never loose at `scripts/agents/` root.

2. **REPO_ROOT depth — this is the #1 thing that breaks on a move.** A script computes the
   repo root from its own depth:
   - At `scripts/<name>.py` → `Path(__file__).resolve().parents[1]`
   - At `scripts/agents/<bucket>/<name>.py` → `Path(__file__).resolve().parents[3]`

   Use `parents[N]` (explicit), not `.parent.parent`, so the depth is obvious and greppable.

3. **Cross-platform.** Python scripts use `pathlib`; require Python 3.11+ (stdlib `tomllib`).
   Prefer Python over shell for anything non-trivial so it runs on Windows + macOS + Linux.

4. **No secrets.** Read credentials from `.env/apps.env` (gitignored), never hardcode tokens.
   Per-machine paths/targets belong in `machines.local.toml` (gitignored), with schema docs
   in the tracked `machines.toml`.

5. **Document it.** Add a row to the correct table in [`scripts/README.md`](../../../scripts/README.md)
   — the root table, or the `### <bucket>/` sub-table under "scripts/agents/" — with a
   one-line purpose. If the script has a CLI, add a short usage section.

6. **Docstring / header usage lines** must show the real invocation path
   (`python scripts/agents/<bucket>/<name>.py …`, not a bare `<name>.py`).

---

## Rules for MOVING a script (root ↔ agents/<bucket>/, or between buckets)

Moving is higher-risk than adding because absolute paths and `__file__` depth break silently.
Run this checklist every time:

1. **`git mv`** (preserves history) — don't delete + recreate.

2. **Fix `REPO_ROOT` depth** to match the new location: `parents[1]` at `scripts/` root,
   `parents[3]` at `scripts/agents/<bucket>/`. Update both the `parents[N]` call and any
   `# … → repo root is parents[N]` comment. Also fix any pathlib cross-call that names the
   old location (e.g. `SCRIPTS_DIR / "agents" / "x.py"` → `… / "agents" / "<bucket>" / "x.py"`)
   — these are NOT plain `scripts/agents/x.py` strings, so a path sweep won't catch them.

3. **Sweep for references** across the whole repo (exclude `.venv`, `__pycache__`):
   ```
   Grep: scripts/(<oldname>|<other moved names>)
   Grep: <bare script basenames>          # catches different path prefixes
   ```
   Update every hit. The usual suspects:
   - `scripts/deploy.py` — calls cleanup scripts via `SCRIPTS_DIR / …`
   - `scripts/agents/launchd/*.plist` — **absolute** `ProgramArguments` paths
   - `*.sh` that shell out to siblings (relative `$(dirname "$0")/…` is safe if both move)
   - `.github/workflows/*.yml` — CI invocations
   - cross-script calls (e.g. `weekly_claude_pr.py` → `daily_improvement_scout.py`)
   - docs: `scripts/README.md`, `docs/**`, `workflows/**/README.md`, `workflows/.template/`
   - `.gitignore` comments that name a script

4. **Move companion dirs together** (e.g. `launchd/` moves with the script that installs it,
   so the install script's relative `$(dirname "$0")/launchd/…` keeps resolving).

5. **Update `scripts/README.md`** tables + section anchors. Escape literal `|` inside table
   cells as `\|` (e.g. `tar \| ssh`).

6. **Verify.** Run the moved script (or a path-resolution one-liner) to confirm `REPO_ROOT`
   still points at the repo root, and grep that no un-bucketed path survives:
   ```
   python -c "from pathlib import Path; print(Path('scripts/agents/<bucket>/<name>.py').resolve().parents[3].name)"  # → harqis-work
   # expect NO hits at scripts/agents/<name> without a bucket:
   git grep -nE "scripts/agents/[a-z_]+[-a-z_]*\.(py|sh|ps1)" | grep -vE "scripts/agents/(repo-quality|learning|testing|diagnostics|dumps|fleet)/"
   ```

---

## What does NOT move

Runtime artifacts at `scripts/` root are not scripts — leave them: `*.log`, `pid.*`,
`__pycache__/`. `machines.toml` stays at the **repo root** (not under `scripts/`), with
`machines.local.toml` (gitignored) beside it.

---

## Hard rules

1. **Never break `REPO_ROOT`.** Every move adjusts `parents[N]`. Verify before declaring done.
2. **Always sweep + update references.** A move that leaves a stale `scripts/<old>` path in
   deploy.py, a launchd plist, or CI is a broken move — fix all of them in the same change.
3. **README is part of the change**, not a follow-up. Update the right table in the same edit.
4. **Ask when the bucket is ambiguous.** Lay out the deploy-vs-agents distinction and let the
   user decide rather than guessing.
