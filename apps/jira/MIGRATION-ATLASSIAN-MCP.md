# Jira MCP — migration notes: custom core service → Atlassian Remote MCP Server

> **Status:** planning / future work. Nothing here is implemented yet.
> **Scope:** how (and whether) to migrate the Jira *MCP tool surface* from the
> repo's in-process custom implementation to Atlassian's hosted
> [Remote MCP Server (Rovo)](https://support.atlassian.com/atlassian-rovo-mcp-server/docs/getting-started-with-the-atlassian-remote-mcp-server/).
> **TL;DR:** the remote server can replace the *interactive agent* path, but it
> **cannot** replace the programmatic path the Celery workflows depend on. Plan
> for a hybrid, not a rip-and-replace.

---

## 1. Current state (what we have today)

A fully custom, in-process Jira integration built on `harqis-core`:

| Layer | File | Notes |
|---|---|---|
| Config | `apps/jira/config.py` → `apps_config.yaml` (`JIRA` block) | `domain`, `api_token`, `user` from env (`JIRA_DOMAIN`, `JIRA_API_TOKEN`, `JIRA_USER`). `client: rest`. |
| Base service | `apps/jira/references/web/base_api_service.py` | Extends `core.web.services.fixtures.rest.BaseFixtureServiceRest`. Talks **REST API v2**. Auth: **Basic** (`base64(email:token)`) when `email` present, else **Bearer** (PAT). Supports Cloud **and** Data Center/Server. |
| API services | `apps/jira/references/web/api/{issues,projects,boards,users}.py` | `search_issues` (JQL), `get_issue`, `create_issue`, `update_issue`, `get_issue_comments`, `add_comment`, `get_projects`, `get_project`, boards, `get_myself`, `search_users`. |
| MCP wrapper | `apps/jira/mcp.py` → `register_jira_tools(mcp)` | 10 `@mcp.tool()` functions that call the API services with the shared `CONFIG`. |
| Server registration | `mcp/server.py:46` | `("Jira", "apps.jira.mcp", "register_jira_tools")` — registered **in-process**, **stdio** transport, alongside every other app. |
| Tests | `apps/jira/tests/test_{issues,projects,users}.py` | pytest `@smoke`/`@sanity`. Fixtures (`given`, `first_project_key`, `first_issue_key`) instantiate the **live** service and skip when the instance is empty. No HTTP mocking — these are live smoke tests. |

### Current MCP tool inventory (the surface to migrate)

```
get_jira_projects        get_jira_issue          get_jira_issue_comments
get_jira_project         create_jira_issue       add_jira_comment
search_jira_issues       update_jira_issue       get_jira_myself
                                                 search_jira_users
```

### Who consumes the API service — the key constraint

The `ApiServiceJira*` classes are imported by **two independent consumers**:

1. **The MCP tools** (`apps/jira/mcp.py`) — interactive / agent use.
2. **Celery workflows** — e.g. `workflows/testing/tasks/test_farm.py` pulls
   active-sprint tickets from board `1790` via `cfg_id__jira='JIRA'`, headless,
   on a beat schedule. (This file/feature is what the daily BDD test-farm runs on.)

➡️ **Only consumer #1 can move to the Atlassian Remote MCP.** Consumer #2 runs
headless under Celery and authenticates with a static token — it cannot perform a
browser OAuth handshake. The custom REST service must stay for the workflows.

---

## 2. Target state (Atlassian Remote MCP Server / Rovo)

Source: the Atlassian getting-started doc linked above (read 2026-06-15).

| Aspect | Value |
|---|---|
| Endpoint | `https://mcp.atlassian.com/v1/mcp/authv2` |
| Deprecated endpoint | `https://mcp.atlassian.com/v1/sse` — **support ends 2026-06-30**, do not target it |
| Transport | Remote HTTP (successor to SSE). Local/IDE clients connect via the **`mcp-remote`** proxy (**Node.js v18+**). |
| Auth | **OAuth 2.1, 3-legged**, browser-based, **dynamic client registration** (no manual OAuth app). Optional **API-token** auth — admin-enabled, off by default. |
| Tools (Jira) | Search, create/update issues, bulk ticket generation. Also Confluence + Compass + cross-product linking. |
| Prerequisites | Atlassian **Cloud** site; modern browser for OAuth; Node 18+ for desktop/IDE; user must already hold the relevant Jira permissions. |
| Security | HTTPS/TLS 1.2+; respects the user's existing permissions; honours IP allowlists. |
| Hosting | Fully hosted by Atlassian — no code in this repo, no token storage here. |

---

## 3. Side-by-side

| Dimension | Custom (today) | Atlassian Remote MCP |
|---|---|---|
| Where it runs | In-process in `mcp/server.py` (stdio) | Atlassian-hosted, remote HTTP |
| Auth | Static config token (Basic email:token **or** Bearer PAT) | Interactive OAuth 2.1 (or admin API token) |
| Headless / cron friendly | ✅ yes (static token) | ❌ no (OAuth browser flow) |
| Deployment surface | We own/patch the code | Zero — Atlassian maintains it |
| Tool schema stability | We control it | Atlassian controls naming/shape |
| Cloud vs DC/Server | **Both** (Bearer = DC/Server) | **Cloud only** |
| Confluence/Compass | ✗ (Jira only) | ✅ included |
| Permission model | Whatever the token can do (often a service account) | Strictly the connected user's permissions |
| Maintenance burden | Ours (REST v2 drift, paging, etc.) | Atlassian's |
| Multi-tenant fork story | Pruned/redacted by `/create-new-fork-repository` | N/A — central service, per-user OAuth |

---

## 4. Tool mapping (custom → remote)

> Exact remote tool names/params must be confirmed against the live tool list
> after connecting (the doc summarises capabilities, not a frozen schema).

| Custom tool | Remote equivalent (capability) | Migration note |
|---|---|---|
| `search_jira_issues` (JQL) | Jira search | Confirm JQL is still first-class vs natural-language search. |
| `get_jira_issue` | Issue read | Likely covered. |
| `create_jira_issue` | Issue create (incl. bulk) | Remote adds bulk creation we don't have. |
| `update_jira_issue` | Issue update | Confirm field coverage (priority/labels/assignee). |
| `get_jira_issue_comments` / `add_jira_comment` | Comments | Verify both read + write exist. |
| `get_jira_projects` / `get_jira_project` | Project/space navigation | Verify. |
| `get_jira_myself` | Implicit in OAuth session | The connected user *is* "myself". |
| `search_jira_users` | ⚠️ unverified | User search may not be exposed — keep custom if a workflow needs it. |
| boards (`apps/jira/references/web/api/boards.py`) | ⚠️ unverified (Agile/board API) | `test_farm` reads board `1790`; if remote lacks board access, **must** stay on custom. |

---

## 5. Recommended approach — hybrid, phased

**Do not remove the custom service.** Target: let *interactive agents* use the
richer Atlassian Remote MCP, while *headless workflows* keep the custom
token-based service.

### Phase 0 — Spike / validation (no code changes)
- Connect a dev MCP client (Claude Desktop or `mcp-remote`) to
  `https://mcp.atlassian.com/v1/mcp/authv2`, complete the OAuth flow.
- Dump the **live tool list + schemas**; fill in the ⚠️ rows in §4.
- Confirm the target instance is **Cloud** (Bearer-PAT use today hints it could
  be Data Center — if so, **stop**: remote MCP is Cloud-only).
- Confirm JQL search and board/Agile access exist (the two things `test_farm`
  needs). Record findings back in this file.

### Phase 1 — Add the remote server alongside (additive, reversible)
- Register the remote server in the **client** config (e.g. `.mcp.json` /
  Claude config), not in `mcp/server.py`. It coexists with the in-process tools.
- Gate it behind config so it's opt-in per machine (cron hosts stay off — they
  can't OAuth).
- Validate agent flows (e.g. "show my closed tickets", "create a bug") through
  the remote tools.

### Phase 2 — Deprecate the *MCP wrapper only* (keep the API service)
- Once remote tools cover the interactive needs, stop registering Jira in
  `mcp/server.py:46` (or feature-flag it off).
- **Keep** `apps/jira/references/web/...` and `apps/jira/config.py` — Celery
  workflows and any non-agent caller still import them.
- Update agent profiles / skills that referenced the old tool names.

### Phase 3 — Revisit only if Atlassian ships a service-account/API-token path
- If the org enables the **admin API-token** auth for the remote server, a
  headless workflow *could* call it without OAuth. Only then consider retiring
  parts of the custom service. Until then, the custom service is load-bearing.

---

## 6. Test-fixture impact

Today's tests (`apps/jira/tests/`) are **live smoke/sanity tests** against the
custom service — no HTTP mocking. Migration implications:

- The custom-service tests stay relevant as long as the service exists (Phases
  0–3) — they protect the workflow path.
- For the remote MCP there is **nothing to unit-test in this repo** (it's
  hosted). Validation is a **connectivity/auth smoke check** (can we OAuth + list
  tools?), best run manually or as a lightweight, credential-gated check — not a
  pytest against our code.
- If a thin client wrapper is ever added for the remote server, mirror the
  existing fixture style: a `given` fixture that builds the client and **skips**
  when creds/OAuth session are absent (same pattern as `first_project_key`).
- Keep `@smoke`/`@sanity` marks consistent so `/run-tests` and the test-farm
  selection logic keep working.

---

## 7. Risks & decision factors

- **OAuth vs headless is the hard blocker.** The remote server's browser OAuth is
  fundamentally incompatible with Celery cron. This alone forces the hybrid.
- **Cloud-only.** If any target Jira is Data Center/Server, the remote server is a
  non-starter for that instance.
- **Schema drift / tool naming.** Atlassian owns the tool surface; agent prompts
  and skills must adapt, and could break without notice.
- **Permission narrowing.** Remote = the *user's* permissions (good for least
  privilege, but may surface *fewer* tickets than today's service-account token).
- **Endpoint deprecation.** Never wire the SSE endpoint — it dies 2026-06-30.
- **Fork/redaction story.** The custom path is redacted/pruned by
  `/create-new-fork-repository`; a centrally-hosted OAuth server changes that
  calculus for downstream forks.

---

## 8. Open questions (answer during Phase 0)

1. Is the production Jira instance **Cloud** or **Data Center/Server**?
2. Does the remote server expose **JQL search** and **board/Agile** reads (the
   `test_farm` dependencies)?
3. Is **`search_jira_users`** available remotely, or must it stay custom?
4. Will the org enable the **admin API-token** path (the only route to headless)?
5. Which agents/skills/profiles reference the current tool names and must be
   updated?

---

## 9. References

- Atlassian Remote MCP Server — getting started:
  <https://support.atlassian.com/atlassian-rovo-mcp-server/docs/getting-started-with-the-atlassian-remote-mcp-server/>
- Current implementation: `apps/jira/`, registered at `mcp/server.py:46`.
- Headless consumer to protect: `workflows/testing/tasks/test_farm.py`
  (board `1790`, `cfg_id__jira='JIRA'`).
