# Frontend integrations

Build → Integrations contains two groups: **Connectors** (user accounts used by
frontend features) and **Workflows** (the existing host-configured `apps/` inventory).
Existing `/applications`, documentation, and test-run URLs remain valid.

## GitHub and Jira Cloud

Each signed-in username has one connection per provider. Connect and test first,
then enable. Disable retains the encrypted credential but gates all provider
operations and hides connector controls. Disconnect deletes the credential;
imported actions and resource associations remain. Reconnecting a different
account/site does not reuse the old account's associations.

- GitHub.com: fine-grained PAT, selected repositories, Contents read/write and
  Pull requests read/write for branch and draft PR creation. Organization
  approval and account access still apply. Connecting checks identity; each
  operation is independently authorized by GitHub. Classic PATs also work if
  permitted by GitHub, although the setup recommends fine-grained tokens.
- Jira Cloud: HTTPS `*.atlassian.net` site, account email, API token. A scoped
  token additionally needs its cloud ID and uses the fixed Atlassian API gateway.
  Required permissions include Browse Projects and Transition Issues. API tokens
  work with account MFA; no password or OTP is collected by HARQIS.
- Expiry is displayed as unknown when it is not supplied by the provider.
  Connection health reflects the last test; re-enabling tests again.

Setup links are in the connection dialogs. GitHub App installation and Atlassian
OAuth are future authentication adapters, not implemented login options.

## Card operations

Enable GitHub, then open **Integrations** on an action card. Select a repository,
base, and branch. Link an existing branch or create one. Link a PR by number or
create a draft PR from the linked head/base; GitHub requires actual differing
commits before it can create a PR. Existing head/base PRs are reconciled before
creation, including closed PRs. This flow never merges or pushes code.

**Explore branches and PRs** previews an idea before saving it. Repository and
resource lists offer pagination. Empty states and provider errors remain visible.

Enable Jira and choose **Import assigned issues**, a project, and optionally a
board. Imports process 50 issues at a time and expose a continuation button. Stable
IDs and persisted creation payloads make retries update the same actions, even
after an uncertain canonical API response. Existing imports retain board choices.
Only issues assigned to the connected Jira account are imported.

Jira status categories map to HARQIS **Ready**, **In Progress**, and **Done**. The
existing HARQIS “In Review” column is preserved. Card controls fetch Jira's valid
transitions; required-field transitions direct the user to Jira. Changes verify
both the local action version and the observed remote status. Explicit refresh
reconciles a remote change. Failed provider writes do not move the local card.
After a timeout, refresh before retrying. Generic frontend status edits on linked
cards return a conflict directing the user to the Jira controls.

Connectors are scoped to users, but imported actions use the existing shared
owner corpus/board model. This feature does not introduce private per-user boards
or change direct canonical service/agent authorization. Separate hosts have
separate connector databases; use the same frontend host for connector operations.

## Application development

Workflow cards retain documentation and test controls, with README descriptions,
documented authentication methods, test-file counts, and latest run state.
Descriptions/methods are catalogue hints, not credential-health checks.

Add Application validates a new app key and prepares a durable development action
with the supplied README description and relevant skill names. Existing apps have
an Agent CLI interface section. Both open the existing Hermes workspace with the
prepared action. Preparing does not create app files or enqueue execution: the
user starts a session explicitly. Work runs in the existing worker's isolated
checkout; completion does not automatically install an app into the live checkout.
The registry reserves Codex and Claude choices; they are unavailable until their
runtime adapters are implemented. Existing terminal configuration, history,
capacity, expiry, and artifact handling are reused.

## Persistence and security

`connectors.sqlite3` lives beside `PROFILE_STORE_PATH`; override with
`HARQIS_CONNECTORS_DB` for isolated previews/tests. Schema creation is additive.
Credentials use authenticated Fernet encryption with a purpose/user/provider key
derived from `HARQIS_CONNECTORS_KEY`, or the existing `APP_SECRET_KEY` by default.
The key must remain stable across restarts. Rotating it requires reconnecting;
back up the database and key securely together. No plaintext token is returned to
the browser, written into app configuration, or passed into agent prompts.

Mutations require session authentication and the existing CSRF token. Provider
URLs are fixed/validated; redirects and environment proxies are disabled for
credentialed provider requests. Provider response bodies are not used as error
messages. Canonical data requests use the existing service bearer independently.

All work is manually triggered. No new Beat schedule, worker process, or polling
integration is installed. The preview can run without provider credentials;
real authentication and live mutations require the user's own connections.

## Validation

`frontend/tests/test_integrations.py` covers encryption, user isolation, CSRF,
toggle/disconnect, connection failure, branch/PR reconciliation, Jira import and
transition consistency, unsafe host rejection, and deferred agent preparation.
Browser tests drive real rendered controls against deterministic provider doubles
at mobile and desktop widths. These do not claim a live provider or Hermes run.

API references: [GitHub refs](https://docs.github.com/en/rest/git/refs),
[GitHub PRs](https://docs.github.com/en/rest/pulls/pulls),
[Jira transitions](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issues/),
[Jira search](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/).
