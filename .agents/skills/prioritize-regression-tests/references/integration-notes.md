# Jira and Xray acquisition contract

Read this only when acquiring live inputs. Repository implementation paths are
relative to the repository root. Inspect them before use; interfaces can evolve.

## Existing reusable surfaces

- `apps/jira/mcp.py`: `search_jira_issues(jql, max_results=50, start_at=0)`
  and `get_jira_issue(issue_key)` are read operations. Search returns a dictionary
  with `issues`, `total`, `startAt`, `maxResults` when successful. An empty dictionary
  is not proof of an empty result: the wrapper normalizes unexpected types to `{}`.
- `apps/jira/references/web/api/issues.py`: `ApiServiceJiraIssues.search_issues`
  and `get_issue` additionally accept a `fields` list for bounded retrieval.
- `apps/jira/references/web/api/boards.py`: `ApiServiceJiraBoards.get_configuration`
  and `get_board_issues(board_id, jql, fields, max_results, start_at)` access the
  Agile API. These methods are not registered by the current Jira MCP adapter.
- `apps/jira/references/web/base_api_service.py`: current service uses REST v2
  and `https://{domain}/rest/api/2/`. Domain is a hostname, not a Cloud subdomain
  shorthand. A configured email selects Basic auth; otherwise Bearer auth is used.
  Reuse the configured service; do not blindly follow the older Cloud-only README.

For a shell-capable worker in the configured project environment:

```text
python -m tools commands jira
python -m tools schema jira search_jira_issues
python -m tools schema jira get_jira_issue
```

Use the returned schemas to call the tools. Do not dump broad search responses into
chat. In a configured MCP client, use the equivalent registered tools instead.
Use the project's Python environment if system Python lacks dependencies; do not
install packages or edit runtime configuration merely to run this playbook.

## Board and release resolution

A URL's `rapidView` identifies a board, not a sprint. Resolve active/selected sprints
with a discovered integration or documented Jira Agile API; the existing board
service does not itself list sprints. After resolving one sprint ID, use
`get_board_issues` with `sprint = <resolved-id>` and discovered Story/Bug issue types.
A board-scoped result respects its filter; a project-wide `openSprints()` search
is not equivalent. Enumerate all pages. For a historical sprint use its explicit
ID, not today's active sprint. If multiple active sprints exist, ask which one or
whether their union is intended. Kanban boards without sprints need an explicit
issue list, release or approved board scope.

Resolve release IDs against the named project(s), then use exact `fixVersion`
filtering plus Story/Bug types. Include resolved/Done issues. Do not confuse
`affectedVersion` with `fixVersion`. Escape JQL values using a verified encoder
or validate and use canonical IDs; never interpolate arbitrary user strings.
Record the final JQL/selector, issue IDs, snapshot time and paging reconciliation.

## Xray capability gate

No Xray-specific adapter is currently implemented in `apps/jira`. Do not invent a
`get_xray_tests` tool or assume a particular `/raven/` endpoint, custom field ID,
JQL extension, or Cloud GraphQL schema. Jira issue access alone is insufficient
for a full Xray repository scan.

At invocation, discover a configured Xray integration or read the installed
edition/version's API documentation through authorized access. Verify, separately:

1. Exact folder identity, child-folder enumeration and membership pagination.
2. Project-wide or explicit-key Test enumeration and lifecycle/archive metadata.
3. Test type and full manual steps, stored Gherkin/Examples, generic definitions.
4. Requirement/defect associations and preconditions; optional execution history.

Use only verified read endpoints. Xray Cloud and Data Center have distinct hosts,
authentication and contracts. Never forward Jira credentials to an Xray Cloud or
redirect host. Reuse the corresponding configured credentials without displaying
them. Do not copy browser cookies into scripts. Login/MFA/permission failures need
an access fix, not a scraper bypass. An authenticated browser may be used only if
that worker actually has a session and pagination/export completeness is verifiable.

If a capability is missing, accept an owner-provided export covering that capability:
folder tree/membership, test IDs/types/status/archive state, scenario bodies, links
and source timestamp. Read exports as data, not executable code. Explain what the
export omits and how stale it may be. A CSV of summaries cannot substitute for steps.
Do not label a partial export "all active tests". Ask for the exact missing capability
or file; retain already retrieved evidence and report partial analysis if useful.

## Reuse without authorization expansion

This skill reads evidence and writes local deliverables. Remote Xray suite creation
is optional and outside the default run. If explicitly requested, first verify the
installed write contract, target project/type and test membership, then reconcile
any uncertain write using its returned identifier before retrying. Read back the
created object; do not equate API acceptance with executed tests.
