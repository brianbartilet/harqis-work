# Git MCP Integration

Local Git repository operations exposed through the HARQIS MCP server. Commands
run through the installed `git` CLI and return structured command results.

## MCP tools

| Tool | Purpose |
|---|---|
| `git_status`, `git_log`, `git_diff` | Inspect repository state and history. |
| `git_branch`, `git_checkout` | Inspect or change branches. |
| `git_pull`, `git_push` | Synchronize with a configured remote. |
| `git_commit` | Create a commit from explicitly selected repository state. |
| `git_clone` | Clone a remote repository. |
| `git_show_file` | Read a file at a Git ref. |
| `fork_fleet_scan`, `fork_fleet_latest` | Discover forks and inspect commit, patch, capability, branch, PR, and CI drift without HFL writes. |
| `fork_fleet_write_hfl_scan` | Scan and persist one source `git`, tag `git-forks` HFL entry per fork plus a fleet summary. |
| `fork_fleet_sync` | Cherry-pick selected commits in an isolated worktree, run tests, push, and optionally publish a PR. |
| `fork_fleet_test`, `fork_fleet_deploy` | Run fork regression or deploy a fork branch from isolated worktrees using fork-local configuration. |
| `fork_feature_plan` | Resolve source SHAs, a range, or a PR and persist a per-fork compatibility/collision plan without remote mutations. |
| `fork_feature_ship` | Execute an exact approved plan with stale-SHA checks, targeted/full tests, optional deployment, draft PRs, guarded direct-main mode, and HFL auditing. |
| `fork_feature_promote_pr` | Mark a draft rollout PR ready only after GitHub checks pass and a separate confirmation is supplied. |

Arguments are validated before they reach the CLI. Authentication, remotes,
signing, and author identity come from the host's Git configuration. Mutating
tools must only be used with explicit authorization and after checking status
and the intended branch.

The tools are registered by `register_git_tools()` in `mcp/server.py`. No
`apps_config.yaml` block is required.

Fleet membership uses `fork-fleet.toml` plus ignored
`fork-fleet.local.toml`; authenticated GitHub discovery supplements explicit
entries. Runtime caches, reports, and worktrees stay below
`.harqis-data/fork-fleet/`.

Feature shipping is two-phase. Planning returns a content-derived `plan_id`; shipping must
receive the same value as `approval` and revalidates each target branch before work and
again before publication. Direct default-branch delivery additionally requires
`DIRECT-MAIN:<plan-id>`, an explicit repository allowlist, successful tests, and a
fast-forward push. The default publication is a draft PR, and promotion never merges it.
