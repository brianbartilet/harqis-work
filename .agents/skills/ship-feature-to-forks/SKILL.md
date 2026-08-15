---
name: ship-feature-to-forks
description: Plan, validate, test, deploy, and publish one or more harqis-work commits across every accessible managed fork. Use when shipping a feature SHA, commit range, or source PR to derivatives; comparing mergeability, conflicts, drift, patch equivalence, manifest exclusions, capability or open-PR collisions; opening per-fork draft PRs; or explicitly delivering tested changes to selected default branches.
---

# Ship harqis-work features to managed forks

Use the `manage-fork-fleet` CLI and its shared `apps.git.fleet` engine. Keep planning and
shipping as separate user-approved phases.

## 1. Plan without remote mutations

Accept exactly one source form and preserve commit order by default:

```powershell
python .agents/skills/manage-fork-fleet/scripts/fork_fleet.py plan --commit <sha> --commit <sha>
python .agents/skills/manage-fork-fleet/scripts/fork_fleet.py plan --range <A..B>
python .agents/skills/manage-fork-fleet/scripts/fork_fleet.py plan --pull-request <number-or-url>
```

Treat ranges as contiguous `A..B` history, not symmetric `A...B` sets. Add
`--include owner/repo`, `--exclude owner/repo`, or `--squash` when requested. Planning
may fetch refs, write ignored reports/caches, and use disposable local preflight worktrees;
it must not create remote branches, push, deploy, or open PRs.

Present the plan ID and a per-fork table containing status, mergeability, target SHA,
missing/equivalent commits, drift, collisions, and diagnostic worktree paths. Explain these
statuses:

- `compatible`: clean trial application with no detected collision.
- `compatible-with-warnings`: mergeable, but fork paths, capabilities, or open PRs overlap.
- `blocked`: manifest exclusion, unavailable commit, or trial cherry-pick conflict.
- `already-applied`: every source patch is present or patch-equivalent.
- `unavailable`: discovery, access, fetch, or comparison failed.

Stop and ask the user to approve the exact `plan_id`. Never infer approval from the request
that initiated planning.

## 2. Ship only the approved plan

After exact approval, run:

```powershell
python .agents/skills/manage-fork-fleet/scripts/fork_fleet.py ship `
  --plan <plan-id> --approve <same-plan-id> `
  --repository owner/fork
```

Omit `--repository` to process every eligible target. Add repeatable `--test-path` values
when the user specifies targeted tests. Otherwise infer component test directories. Always
run targeted tests first and the full pytest suite second. Continue across forks after a
single target fails and report every result.

The engine must re-fetch and match the planned target SHA before creating the isolated
rollout branch, then re-check it immediately before publication. Treat a mismatch as a stale
plan and require a new plan. Never auto-resolve conflicts or delete a conflict diagnostic
worktree.

Use `--deploy owner/fork=host` or `=worker` only for forks the user selected for deployment.
Deployment failure blocks publication for that fork.

By default, push the rollout branch and open a draft PR. The CLI writes per-fork plus fleet
HFL rollout audit entries; use `--skip-hfl` only when the user explicitly declines auditing.

## 3. Guard direct default-branch delivery

Require all of the following:

- an explicit `--repository owner/fork` allowlist;
- the same repository in `--direct-main owner/fork`;
- zero blocking plan collisions and successful targeted/full tests;
- an exact `--confirm-direct-main DIRECT-MAIN:<plan-id>` token.

Push fast-forward only. Never force-push or bypass branch protection.

## 4. Promote a verified draft PR

Keep PRs draft until GitHub reports at least one check and every check has completed
successfully. Require a separate confirmation:

```powershell
python .agents/skills/manage-fork-fleet/scripts/fork_fleet.py promote `
  --repository owner/fork --pull-request <number> `
  --approve READY:owner/fork#<number>
```

Promotion marks the PR ready; it never merges it.

## Reporting and safety

- Summarize partial success rather than hiding failed or skipped forks.
- Link persisted plan/rollout reports, PRs, and retained diagnostic worktrees.
- Never expose copied fork secrets in output or HFL entries.
- Leave the weekly `git_forks` task read-only. It may report general readiness and HFL
  signals, but must never ship, push, deploy, or create PRs.
