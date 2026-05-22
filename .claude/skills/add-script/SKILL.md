---
name: add-script
description: >
  Apply the harqis-work /scripts organization whenever a script is created, added, or
  moved under scripts/. Deploy/runtime scripts live at the root of scripts/; agent-support
  scripts (Claude-driven automation, repo-quality/health/test tooling, agent worktree/window
  cleanup) live under scripts/agents/. Enforces the REPO_ROOT depth convention, README
  upkeep, and a reference sweep so nothing breaks.

  Trigger phrases (non-exhaustive): "add a script", "create a script", "new script in
  scripts/", "put this in scripts", "build a script for the agent", "helper script",
  "move <x> into scripts", "organize scripts".

user-invocable: true
allowed-tools: Bash Read Glob Grep Edit Write
---

You are the **/scripts organization** skill for `harqis-work`.

Any time a script is added to, created in, or moved within `scripts/`, it must land in the
right place and stay wired up. This skill is the rulebook.

---

## The two buckets

| Bucket | Location | What belongs here |
|---|---|---|
| **Deploy / runtime** | `scripts/` (root) | Bringing the stack up/down, launching daemons, syncing config between machines, network/infra policy. Examples: `deploy.py`, `launch.py`, `sync-to-host.ps1`, `tailscale/`. |
| **Agent-support** | `scripts/agents/` | Claude-driven automation (docs regen, improvement scout, weekly PR), the repo-quality / health / test tooling those agents drive, and the worktree/terminal-window cleanup that keeps the agent fleet tidy. Examples: `run_agent_prompt.py`, `daily_improvement_scout.py`, `weekly_claude_pr.py`, `manifesto_audit.py`, `run_test_suite.py`, `check_env_health.py`, the `cleanup-*` / `close-completed-windows` scripts, `launchd/`. |

**Decision rule:** if the script's primary job is *deploying or running the platform*, it's
root. If it *exists to support the agent system or repo automation* (even indirectly, like
cleaning up agent worktrees or auditing repo metadata), it goes under `agents/`. When
genuinely ambiguous, ask the user with the two buckets laid out — don't guess silently.

---

## Rules for a NEW script

1. **Place it by bucket** (above). Default new agent/automation tooling to `scripts/agents/`.

2. **REPO_ROOT depth — this is the #1 thing that breaks on a move.** A script computes the
   repo root from its own depth:
   - At `scripts/<name>.py` → `Path(__file__).resolve().parents[1]`
   - At `scripts/agents/<name>.py` → `Path(__file__).resolve().parents[2]`

   Use `parents[N]` (explicit), not `.parent.parent`, so the depth is obvious and greppable.

3. **Cross-platform.** Python scripts use `pathlib`; require Python 3.11+ (stdlib `tomllib`).
   Prefer Python over shell for anything non-trivial so it runs on Windows + macOS + Linux.

4. **No secrets.** Read credentials from `.env/apps.env` (gitignored), never hardcode tokens.
   Per-machine paths/targets belong in `machines.local.toml` (gitignored), with schema docs
   in the tracked `machines.toml`.

5. **Document it.** Add a row to the correct table in [`scripts/README.md`](../../../scripts/README.md)
   ("Root — deploy & runtime" or "scripts/agents/") with a one-line purpose. If the script
   has a CLI, add a short usage section.

6. **Docstring / header usage lines** must show the real invocation path
   (`python scripts/agents/<name>.py …`, not a bare `<name>.py`).

---

## Rules for MOVING a script (root ↔ agents/, or in)

Moving is higher-risk than adding because absolute paths and `__file__` depth break silently.
Run this checklist every time:

1. **`git mv`** (preserves history) — don't delete + recreate.

2. **Fix `REPO_ROOT` depth** in the moved Python script (`parents[1]` ⇄ `parents[2]`). Same
   for any `Path(__file__).parent / "sibling.py"` — those stay correct only if the sibling
   moves too.

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
   still points at the repo root:
   ```
   python -c "from pathlib import Path; print(Path('scripts/agents/<name>.py').resolve().parents[2].name)"  # → harqis-work
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
