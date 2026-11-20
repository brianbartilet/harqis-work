## Feature Spec — Grok Bot discovery

**Goal:** Connect a Grok Bot account and automatically display its Bots in the fleet.

**Trigger:** Successful browser sign-in or Cursor API-key connection; explicit refresh;
five-minute, server-throttled refresh while the fleet page is open.

**Automation runtime:**
- Classification: not applicable (deterministic connector requests).
- Execution owner: authenticated frontend connector service.
- Schedule owner: fleet-page refresh; no background scheduler.
- Decision record: discovery only, bounded requests, encrypted credentials,
  per-user serialization, no Bot execution or remote mutation.

**Primary files changed:**
- `frontend/modules/integrations/` — Grok Bot authentication and roster adapter.
- `frontend/modules/agents/` — provider/account visibility and external-agent states.
- `frontend/static/js/integrations.js` — reuse connector dialogs, switches, status,
  focus handling and credential setup patterns.
- `frontend/src/agent-fleet.jsx` — reuse orbs, inspector, Space and presentation editor.
- `frontend/tests/` — authentication, isolation, reconciliation and browser coverage.

**Files / components NOT touched:**
- Hermes execution, n8n dispatch, Celery schedules and public MCP server: discovery
  does not require execution changes or a new shared app service.

**Inputs:** Browser PKCE sign-in or Cursor user API key; authenticated remote roster.

**Outputs / side-effects:** Encrypted access/refresh tokens; stable account-scoped
fleet records with local presentation overrides and unavailable/reconnect states.

**Error handling:** Preserve the last roster on failure. Failed replacement leaves
the existing connection intact. Authentication rejection requests reconnection;
transient errors retain credentials. Only a valid complete roster marks absent Bots
unavailable. Disconnect hides records without deleting history.

**New dependencies:**
- Apps: none; extends the existing frontend connector layer.
- Packages: none.
- Env vars: none; uses existing connector encryption configuration.

**Edge cases addressed:** Empty/malformed rosters, rooms versus Bots, expired login,
token rotation, concurrent requests, account replacement, stale responses, local
overrides, network failures and remote deletion.

**Acceptance criteria:**
- [x] Both authentication options validate roster access before replacing a connection.
- [x] Connecting immediately imports Bots without manual registration.
- [x] Refresh preserves local customization and account isolation.
- [x] Tokens/verifiers never appear in frontend responses or logs.
- [x] Desktop/mobile interactions and connector/fleet regressions pass.

**Open questions / assumptions:**
- User approved discovery flow and both authentication methods in this conversation.
- Experimental: protocol derived from community implementation, not a supported
  public Grok Bot API. No extraction of desktop credentials, no password collection.
- Browser sign-in uses Cursor's login page. API-key mode exchanges a Cursor user
  API key; xAI inference keys are not accepted. The original API key is not saved.
- Live authentication requires the owner to complete sign-in; mocked tests cannot
  establish account eligibility or provider compatibility.

Protocol references reviewed 2026-10-27:
https://github.com/Nuncio-hq/grokbot-cli/tree/main/packages/grokbot-core/src
(`auth-pkce.ts`, `auth-poll.ts`, `auth-refresh.ts`, `agents.ts`, `server-transport.ts`).


## Validation and operating notes

- Thirteen Grok Bot connector checks pass, including both browser UI flows,
  PKCE expiry/cancellation (also during an upstream request), one-shot polling
  recovery, encrypted storage, token rotation, ownership, roster reconciliation,
  throttling and log redaction. Provider responses are simulated.
- Nineteen fleet regression checks pass. The broader connector/fleet run passed
  47 tests and reproduced the two previously documented GitHub Link-button
  browser failures. No new regression failure remains.
- Desktop/mobile screenshots were inspected. JavaScript syntax, bundle build and
  `git diff --check` pass.
- Live Grok Bot sign-in and roster access have NOT been verified. Complete either
  connection option in Build > Integrations to establish account compatibility.

The browser protocol starts at Cursor's `/loginDeepControl` with a PKCE challenge.
The server polls `/auth/poll`; verifiers and token pairs remain encrypted on the
server. Attempts expire after ten minutes and are bound to the HARQIS user.
API-key connection exchanges a Cursor user key at `/auth/exchange_user_api_key`;
the original key is discarded. Token refresh uses `/oauth/token`. All upstream
origins are fixed, redirects disabled, response sizes bounded, and error messages
exclude upstream bodies. A cross-process per-user lease serializes refresh and
connection changes. These routes are experimental implementation details and may
change without notice.

The returned JWT subject is used for account association only after authenticated
roster access succeeds. Roster reconciliation distinguishes Bots from rooms and
uses account-scoped stable IDs. No remote avatars, skills, live execution state,
model picker, direct Bot deep links, messaging or execution are claimed. The Open
Grok Bot control links to its product entry page. The user's own images, colors,
Space assignments and local text overrides remain in HARQIS.

Automatic refresh is page-driven (five-minute minimum upstream interval), not a
background schedule. A failed request retains the last roster. Reconnect-required
and delayed-sync states remain visible; disconnect/disable hides imported orbs
but retains their records. Missing Bots are marked unavailable only after a
validated complete roster. The connector count reflects the actual inventory.


## Fleet connector and entry points — 2026-11-20

Read-only discovery on the Mac mini returned Noa and HARQIS, both already imported
and active. The roster also includes `slackConnections`; additive metadata is
accepted without copying it into Fleet.

Successful connection or Refresh Bots now reconciles one connector entity per
owner/account/provider origin, with independent `connected through` relationships
from each Bot. Failed refresh retains identities and marks the connector stale.
Disable/disconnect update its state; existing visibility rules isolate accounts.
Existing connections acquire the entity on their next successful Refresh Bots.

The inspector opens `https://grok.com/bot/<validated UUID>` using the shared
interface-link control, with opener isolation and a normal link fallback.
View fleet opens a Grok-only view and clears saved search, Space and date filters,
then fits the graph. This does not duplicate or rename either agent. Selecting an
agent can dim the other orbs; it does not mean those agents were not imported.

No CLI runtime, task execution, or background scheduler is introduced. Grok owns
remote execution. These additions use explicit connector discovery; no second
schedule owner is installed. Validation uses isolated stores and simulated API
responses; local tests do not establish deployment of the new mapping.
