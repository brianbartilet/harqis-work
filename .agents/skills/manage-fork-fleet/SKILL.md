---
name: manage-fork-fleet
description: Discover, compare, test, deploy, and safely synchronize harqis-work derivatives, GitHub forks, and registered clones. Use when asked about fork drift, missing or fork-only commits, skills/apps/workflows differences, fork branches or pull requests, cherry-picking changes across forks, fork regression tests, isolated fork deployments, or fleet HFL reports.
---

# Manage the harqis-work fork fleet

Use the bundled CLI. It calls `apps.git.fleet`, the same engine exposed through
MCP, Celery, and the frontend.

## Safety model

- Run `scan` freely; it only fetches remote references, writes the ignored JSON
  report/cache, and creates HFL entries only when `--hfl` is explicit.
- Require explicit repository names, commit SHAs, and a new branch for writes.
- Create an isolated worktree for cherry-picks, tests, conflict resolution, and
  deployment. Never reuse a dirty checkout.
- Never force-push, merge a protected branch, auto-resolve a conflict, or delete
  a diagnostic worktree.
- Treat manifest exclusions as informational, not failures.
- Allow partial fleet success and report every target independently.

## Commands

```powershell
python .agents/skills/manage-fork-fleet/scripts/fork_fleet.py scan
python .agents/skills/manage-fork-fleet/scripts/fork_fleet.py scan --hfl
python .agents/skills/manage-fork-fleet/scripts/fork_fleet.py show
python .agents/skills/manage-fork-fleet/scripts/fork_fleet.py sync `
  --repository owner/fork --branch sync/topic --commit <sha> --test-path tests/path
python .agents/skills/manage-fork-fleet/scripts/fork_fleet.py test `
  --repository owner/fork --branch main --test-path tests/path
python .agents/skills/manage-fork-fleet/scripts/fork_fleet.py deploy `
  --repository owner/fork --branch feature/topic --role host
```

Add `--publish-pr --pr-title ... --pr-body ...` to `sync` only after the user
explicitly requests publication. Repeat `sync` per fork so every target receives
its own branch, regression result, and PR.

Configuration is hybrid: `fork-fleet.toml` is authoritative,
`fork-fleet.local.toml` supplies ignored local paths, and GitHub discovery is the
fallback. Read [configuration.md](references/configuration.md) when adding or
debugging fleet membership.

## Reporting

Summarize missing/fork-only commits, patch-equivalent changes, file and skill
drift, manifest exclusions, branches, PRs, CI, and HARQIS capabilities under
`apps/`, `workflows/`, `.agents/skills/`, `frontend/modules/`, and `mcp/`.
When HFL output is requested, write one source `git`, tag `git-forks` entry per
fork plus one fleet summary, all with repository/run/PR references.
