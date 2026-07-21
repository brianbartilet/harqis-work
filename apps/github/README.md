# GitHub Integration

GitHub REST API services and MCP tools for repositories, issues, pull requests,
commits, branches, searches, and file content.

## Setup

Set `GITHUB_API_TOKEN` in `.env/apps.env`. The `GITHUB` block in
`apps_config.yaml` uses `https://api.github.com` and injects that token. Grant
only the scopes required for the intended repositories and write operations.

## MCP tools

The registered surface includes `github_get_me`, repository list/get/search,
issue list/get/create/search, pull-request list/get, commit and branch listing,
and `github_get_file_content`.

Tools are registered by `register_github_tools()` in `mcp/server.py` and use the
service implementation under `references/web/api/repos.py`.

## Testing

```powershell
pytest apps/github/tests
```

These are live API tests and require a valid token. Creating an issue is a
state-changing operation; use a designated test repository.
