# Jira

## Description

- [Jira](https://www.atlassian.com/software/jira) is a project and issue tracking tool by Atlassian.
- REST API documentation: [Jira Cloud REST API v3](https://developer.atlassian.com/cloud/jira/platform/rest/v3/intro/)
- Authorization guide: [Basic Auth for REST APIs](https://developer.atlassian.com/cloud/jira/platform/basic-auth-for-rest-apis/)
- Integrates projects, issues, comments, and users into HARQIS workflows.

## Supported Automations

- [X] webservices
- [ ] browser
- [ ] desktop
- [ ] mobile
- [ ] internet of things

## Directory Structure

```
apps/jira/
├── config.py
├── mcp.py                              # 10 MCP tools
├── references/
│   ├── dto/
│   │   └── issue.py                   # DtoJiraProject, DtoJiraIssue, DtoJiraUser, DtoJiraComment
│   └── web/
│       ├── base_api_service.py        # HTTP Basic Auth (email + API token, base64 encoded)
│       └── api/
│           ├── projects.py            # get_projects, get_project
│           ├── issues.py              # search_issues, get_issue, create_issue, update_issue, get_issue_comments, add_comment
│           └── users.py               # get_myself, search_users
└── tests/
    ├── test_projects.py
    ├── test_issues.py
    └── test_users.py
```

## Authentication

Jira Cloud uses **HTTP Basic Auth** with your Atlassian account email and an API token:

```
Authorization: Basic base64(email:api_token)
```

The base service (`base_api_service.py`) handles the encoding automatically — you only need to supply `email` and `api_token` in config.

### Step 1 — Get your API Token

1. Go to **https://id.atlassian.com/manage-profile/security/api-tokens**
2. Click **"Create API token"**
3. Give it a label (e.g. `harqis-work`) and click **Create**
4. Copy the token — this is your `JIRA_API_TOKEN`

> The token is shown only once. Store it securely.

### Step 2 — Find your Jira domain

Your Jira domain is the subdomain of your Atlassian workspace:

```
https://{JIRA_DOMAIN}.atlassian.net
```

For example, if your Jira URL is `https://mycompany.atlassian.net`, your domain is `mycompany`.

### Step 3 — Add to `.env/apps.env`

```bash
# Jira
JIRA_DOMAIN=<your-subdomain>          # e.g. mycompany (no .atlassian.net)
JIRA_EMAIL=<your-atlassian-email>     # e.g. user@example.com
JIRA_API_TOKEN=<your-api-token>
```

---

## Configuration (`apps_config.yaml`)

```yaml
JIRA:
  app_id: 'jira'
  client: 'rest'
  parameters:
    base_url: 'https://placeholder.atlassian.net/rest/api/3/'
    response_encoding: 'utf-8'
    verify: True
    timeout: 60
    stream: True
  app_data:
    domain: ${JIRA_DOMAIN}
    email: ${JIRA_EMAIL}
    api_token: ${JIRA_API_TOKEN}
  return_data_only: True
```

> The `base_url` placeholder is overridden at runtime by `BaseApiServiceJira` using the `domain` value from `app_data`. This is required because the config loader only interpolates env vars in `app_data`, not in `parameters`.

---

## Available Services

### Projects (`references/web/api/projects.py`)

| Method | Args | Returns |
|--------|------|---------|
| `get_projects(max_results?)` | — | All accessible projects |
| `get_project(project_key)` | `project_key` | Single project details |

### Issues (`references/web/api/issues.py`)

| Method | Args | Returns |
|--------|------|---------|
| `search_issues(jql, max_results?, start_at?, fields?)` | `jql` required | Dict with `issues`, `total`, `startAt`, `maxResults` |
| `get_issue(issue_key, fields?)` | `issue_key` | Single issue with fields |
| `create_issue(project_key, summary, issue_type?, description?, assignee_account_id?, labels?, priority?)` | `project_key`, `summary` required | Created issue |
| `update_issue(issue_key, summary?, description?, assignee_account_id?, priority?, labels?)` | `issue_key` required | Updated issue |
| `get_issue_comments(issue_key, max_results?, start_at?)` | `issue_key` | Dict with `comments` list |
| `add_comment(issue_key, text)` | `issue_key`, `text` | Created comment |

**JQL examples:**
```
project=HARQIS AND status=Open
assignee=currentUser() ORDER BY updated DESC
project=HARQIS AND issuetype=Bug AND priority=High
created >= -7d ORDER BY created DESC
```

### Users (`references/web/api/users.py`)

| Method | Args | Returns |
|--------|------|---------|
| `get_myself()` | — | Authenticated user profile |
| `search_users(query, max_results?, start_at?)` | `query` | List of matching users |

---

## MCP Tools

Registered in `mcp/server.py` as `harqis-mcp.jira`. Available tools:

| Tool | Description |
|------|-------------|
| `get_jira_projects` | All accessible Jira projects |
| `get_jira_project` | Single project by key |
| `search_jira_issues` | Search issues via JQL |
| `get_jira_issue` | Single issue by key |
| `create_jira_issue` | Create a new issue |
| `update_jira_issue` | Update issue fields |
| `get_jira_issue_comments` | Comments on an issue |
| `add_jira_comment` | Add a comment to an issue |
| `get_jira_myself` | Authenticated user profile |
| `search_jira_users` | Search users by name or email |

---

## Running Tests

```sh
# All Jira tests
pytest apps/jira/tests/

# Smoke tests only
pytest apps/jira/tests/ -m smoke

# Sanity tests only
pytest apps/jira/tests/ -m sanity
```

All tests are live integration tests — valid credentials in `.env/apps.env` are required.
