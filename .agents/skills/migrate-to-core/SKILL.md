---
name: migrate-to-core
description: >
  Harvest reusable, generic code from **harqis-work** into **harqis-core** (the `core`
user-invocable: true
allowed-tools: Bash Read Glob Grep Edit Write
---

Harvest reusable, generic code from **harqis-work** into **harqis-core** (the `core`
package) as a **pair of pull requests** the human reviews and merges — never an
auto-merge. harqis-work installs harqis-core from `main` (unpinned,
`git+https://github.com/brianbartilet/harqis-core.git`), so the only coordination
is **merge order: core PR first → reinstall → un-draft the harqis-work PR**.

The deterministic sweep (enumerate candidates, score coupling, map what's already
upstream) is done by `scripts/agents/repo-quality/migrate_to_core_scan.py`; **you** (the active agent) do
the *purpose* judgment and author the PRs. This keeps a monthly headless run cheap
and the synthesis high-quality.

## Arguments

`$ARGUMENTS` (parse left to right; all optional):

| Token | Description |
|---|---|
| `--max N` | Cap on candidate **pairs** to propose this run (default `3` — keep PRs reviewable). |
| `--candidate <path>` | Target one specific candidate (repo-relative, e.g. `apps/alpha_vantage`) instead of auto-selecting. |
| `--dry-run` | Run the scan + selection + write a candidate report only; open **no** PRs. |
| `--no-work-pr` | Open only the harqis-core PR per candidate (core-only harvest); skip the draft harqis-work PR. |
| `--core-path <dir>` | Path to the harqis-core checkout (else `$HARQIS_CORE_PATH`, a repo sibling, or `~/GIT/harqis-core`). |

Use the repo venv Python for every command: `.venv/Scripts/python.exe` (Windows) or
`.venv/bin/python` (macOS/Linux). Referred to as `PY` below.

---

## Step 0 — Preconditions + ingest harqis-core

This skill spans two repos. Before doing anything, confirm the run host can drive both:

1. **harqis-core clone reachable** — `migrate_to_core_scan.py` resolves it (Step 1
   prints the path). If it reports `NOT FOUND`, stop: tell the user to clone
   harqis-core or pass `--core-path`.
2. **`gh` authenticated** — `gh auth status`. PRs are created with `gh`.
3. **Push rights to both origins** — from this host, `git push` must work for
   harqis-work *and* harqis-core. (On the Mac mini / harqis-server both use SSH +
   gh; on a Windows box GitHub SSH may be denied — run the monthly job on
   harqis-server.)

Then **ingest harqis-core** so you propose the right thing in the right place and
never duplicate what's upstream: skim its `README.md`, `core/docs/FEATURES.md`, and
the `core/` subpackage list the scan returns (`core/web`, `core/config`,
`core/utilities`, `core/testing`, `core/apps`, `core/codegen`, …). Note its
**conventions**: package name `harqis-core`, Python 3.12, tests live in `*/tests/`
as `unit_*.py` (`core/pytest.ini` only collects `unit_*.py` and excludes `apps/`),
MIT-licensed, additive PRs to `main`.

> **harqis-core's charter (respect it):** a *generic automation / testing* utility
> library — fixtures, base service clients, config loaders, decorators, codegen.
> Its README states AI/agent code was **deliberately moved out** into harqis-work, so
> the AI scaffold is **not** a harvest target.

---

## Step 1 — Sweep harqis-work (deterministic scan)

```bash
PY scripts/agents/repo-quality/migrate_to_core_scan.py
```

Reads `apps/*` and `scripts/agents/*.py`; **never** `workflows/` or `apps/antropic`
(AI). Writes `.harqis-data/migrate_to_core_scan.json` and prints a ranked summary.
Each candidate carries the signals you'll judge on:

- `recommendation: "candidate"` — self-contained, or coupled **only** to
  `apps.config_loader` (harqis-work's thin config shim — liftable). The pool to pick from.
- `recommendation: "coupled"` — imports `workflows.` / `mcp.` / another app, or is a
  Celery task (`sprout_coupled`). **Skip** unless decoupling is trivial and in-scope.
- `flags`: `builds-on-core` (extends `core` already — ideal), `config-shim-only`
  (an app integration liftable by swapping the shim for core's loader),
  `maybe-upstream` (a same-named module already exists in `core` — verify before duplicating),
  `celery-task`, `repo-coupled`.
- `core_imports`, `external_deps` (must already be available in harqis-core too).

If `--candidate <path>` was given, restrict to that record.

---

## Step 2 — Select (the judgment the scan can't make)

The scan flags *structure*; you decide *purpose*. From the `candidate` pool, keep
only code that genuinely belongs in a **generic automation library**, and reject
harqis-work-specific code even when it's self-contained.

**Harvest-worthy (examples):**
- A generic **API-integration base** or reusable client pattern that extends
  `core.web.services` (e.g. an auth/header/retry helper, a paginator).
- A generic **helper/decorator/data util** with no harqis-work semantics.
- A reusable **scaffold** (e.g. the `apps/.template` shape, the service-app
  generator logic) that belongs alongside `core/codegen`.

**Reject (stays in harqis-work):**
- The agent-fleet scripts (`daily_improvement_scout`, `weekly_claude_pr`,
  `manifesto_audit`, `lessons_extractor`, `reasoning_capture`, this scanner, …) —
  self-contained but about *harqis-work's own* manifesto/HFL/Kanban operation.
- Anything HFL/Kanban/manifesto/MCP/workflow-specific, or the AI/agent scaffold.
- A candidate flagged `maybe-upstream` whose logic already exists in `core` — note
  it as "already upstream", don't re-add.

Cap the kept set at `--max` (default 3), smallest/cleanest first. For a
`config-shim-only` app, the migration includes swapping `apps.config_loader` for
`core`'s config loader (`core.config.loader` / `core.web.services.core.config.webservice`).

**Idempotency — never double-propose.** For each kept candidate, check both repos
for an existing open proposal before authoring:
```bash
gh pr list -R brianbartilet/harqis-core --state open  --search "harvest <name>"
gh pr list --state open --search "use-core <name>"
```
If a matching PR is already open, skip that candidate.

If `--dry-run`: write the kept-set rationale to
`.harqis-data/migrate_to_core_plan.md` and stop — open no PRs.

---

## Step 3 — harqis-core PR (ready) — for each kept candidate

Work in the harqis-core checkout (`CORE` = the resolved `--core-path`). Branch from a
fresh `main`:

```bash
git -C "<CORE>" checkout main && git -C "<CORE>" pull --ff-only
git -C "<CORE>" checkout -b feat/harvest-<name>-$(date +%Y%m%d)
```

1. **Place the module** under the right subpackage by purpose (`core/web/…`,
   `core/utilities/…`, `core/codegen/…`, `core/apps/…`). Adapt it to core: drop
   harqis-work imports, depend only on `core.*` + stdlib + packages already in
   core's `requirements.txt`.
2. **Add a unit test** as `…/tests/unit_<thing>.py` (core's pytest only collects
   `unit_*.py`). Keep it hermetic — no network, no harqis-work.
3. Commit (`feat(core): add <thing> harvested from harqis-work`), push, and open a
   **ready** PR:
   ```bash
   gh pr create -R brianbartilet/harqis-core --base main \
     --title "feat(core): add <thing> (harvested from harqis-work)" \
     --body "<what it is, why it's generic, the harqis-work origin path, test note>"
   ```
   Record the returned PR URL/number — the harqis-work PR links to it.

---

## Step 4 — harqis-work PR (DRAFT) — unless `--no-work-pr`

Back in harqis-work, on a fresh `main`:

```bash
git checkout main && git pull --ff-only
git checkout -b chore/use-core-<name>-$(date +%Y%m%d)
```

1. **Remove the local copy** and rewrite every usage to import from `core` (swap the
   `apps.config_loader` shim for core's loader where applicable). Run the relevant
   tests; they will not pass until the core PR is merged + reinstalled — that's
   expected, which is exactly why this PR is a **draft**.
2. Commit (`chore(<scope>): use core <thing> instead of the local copy`), push, and
   open a **draft** PR:
   ```bash
   gh pr create --draft --base main \
     --title "chore: use core <thing> (depends on harqis-core #<N>)" \
     --body "Pairs with brianbartilet/harqis-core#<N>. **Merge order:** merge the
     core PR → reinstall harqis-core (it tracks main) → un-draft + merge this. Until
     then this branch's import of \`from core…\` won't resolve."
   ```

---

## Step 5 — Link + report

- Cross-link the pair: leave a one-line comment on the core PR pointing at the
  harqis-work draft, and vice-versa (the bodies already reference each other).
- Print a summary to the user: per candidate, the two PR URLs, where the module
  landed in core, and the merge order. Note any candidates skipped
  (already-upstream / already-proposed) and why.

---

## Scheduling (monthly, headless)

This skill is built to run unattended. Two ways to schedule it on **harqis-server**
(the host with the core clone + push rights):

- The `/schedule` skill → a monthly routine running `claude -p "/migrate-to-core"`.
- A cron/launchd job mirroring `scripts/agents/repo-quality/weekly_claude_pr.py` (scan → local
  `claude -p` with `--max-turns` / `--max-budget-usd` / `--allowedTools` → PRs).

Either way it stays review-gated: the run only ever opens PRs.

---

## Hard rules — never break these

1. **Never auto-merge.** The skill only ever *opens* PRs. The harqis-core PR is
   ready; the harqis-work PR is a **draft** (unless `--no-work-pr`).
2. **Never delete harqis-work code outside its paired draft PR.** A removal only
   exists inside a `chore/use-core-*` draft that links a live core PR.
3. **Respect the exclusions.** Never harvest `workflows/` (service/chaining), the
   AI/agent scaffold (`apps/antropic` — core moved AI out on purpose), or anything
   HFL/Kanban/MCP/manifesto-specific.
4. **No duplicates.** Honour `maybe-upstream` + the open-PR idempotency check —
   verify against the live `core/` tree before adding anything.
5. **Match core's conventions.** Tests are `unit_*.py` under `*/tests/`; depend only
   on `core.*` + stdlib + packages already in core's requirements; additive PRs to `main`.
6. **Bound the blast radius.** Default `--max 3` pairs per run; smallest/cleanest
   first. A monthly cadence, not a big-bang relocation.
7. **Headless-safe.** No interactive prompts — on any precondition failure (no core
   clone, no `gh`, no push rights) stop with a clear message; on a single bad
   candidate, skip it and continue.
