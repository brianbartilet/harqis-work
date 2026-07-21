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

Arguments are validated before they reach the CLI. Authentication, remotes,
signing, and author identity come from the host's Git configuration. Mutating
tools must only be used with explicit authorization and after checking status
and the intended branch.

The tools are registered by `register_git_tools()` in `mcp/server.py`. No
`apps_config.yaml` block is required.
