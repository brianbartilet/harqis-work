# Unified HARQIS API reference

Open **Build → Developer Resources** (`/developer-tools`) for the documentation hub, then
choose **Open Swagger**, or visit `/docs` directly. Sign in with
the existing owner account. `/openapi.json` downloads the same authenticated
OpenAPI document for API clients. The page generates its inventory from the
running dashboard's registered routes, including all mounted HFL Corpus routes.
Static assets and routes deliberately excluded from OpenAPI are not listed.
External Hermes, Nod, and n8n APIs retain their own documentation; HARQIS's
connector operations are included here.

The Swagger UI runs locally bundled, pinned assets. Operations are grouped by
capability, initially collapsed, and searchable by group. Models are collapsed
to keep the reference readable. Request durations and response bodies appear
after execution. Requests use the current origin, so the dashboard's HTTPS route
also serves Corpus requests without cross-origin browser configuration.

## Authentication and testing

- **Owner routes:** sign in normally. The browser sends its existing session
  cookie. Swagger adds the current owner's CSRF header to write requests, and a
  `csrf` field to URL-encoded or multipart form bodies.
- **Corpus routes:** select **Authorize → HTTPBearer** and supply an existing
  `HFL_CORPUS_API_TOKEN`. Entity routes also accept the owner session.
- **Worker protocol:** use **BridgeToken** with an existing
  `HFL_AGENT_BRIDGE_TOKEN`. This is separate from the Corpus token.
- **Guest routes:** open the intended share first to complete its recipient
  authentication. Owner login does not replace recipient access.

Start with `GET /health`, then `GET /agents/api/catalogue`. The fleet create and
update endpoints include editable example bodies. Workflow links come from the
catalogue; selecting them does not run workflows. Agent updates require the
current `version` returned by `GET /agents/api/items`.

**Try it out → Execute sends a live request.** Writes, task dispatch, sync and
deployment endpoints have their normal effects. Token authorization is held in
memory only and is cleared on reload. No server tokens are inserted into the
page or schema. A 401 usually requires sign-in/token authorization; a 403 on an
owner write may require reloading the page for a fresh CSRF token. HTML/form
routes retain their original request and response formats; handlers with
untyped bodies may require consulting their implementation for all fields.

The standalone Corpus service's `/docs` and `/openapi.json` remain compatible
with existing clients; the dashboard `/docs` is the complete reference.

## Quick Notes API

Expand **Activity · Quick Notes** in `/docs`. These routes belong to the dashboard
and use its owner session cookie; PUT and DELETE also require `X-CSRF-Token`.
Swagger supplies that header for the signed-in owner. They are not standalone
`/api/hfl/` bearer-token routes and store notes in this host's profile database.

| Method and path | Request | Successful response and behavior |
|---|---|---|
| `GET /hfl-corpus/quick-notes` | No body or Space-selection parameter | `200 {notes, active}`. Includes active and archived notes, excludes deleted notes, and applies the shared page Space context. |
| `PUT /hfl-corpus/quick-notes/{identity}` | Complete writable note state | `200` note snapshot. Create with a new identity (at most 80 characters) and revision `0`; update with the latest revision. Set `archived` to archive or restore. |
| `DELETE /hfl-corpus/quick-notes/{identity}` | Complete writable note state, including the latest revision, in a JSON body | `200` final note snapshot with incremented revision. Excludes the note from future listings; its identity cannot be reused. |

PUT is replacement, not a partial update: omitted fields reset to their defaults.
Editable fields are `title`, `items`, `workspace_ids`, `references`, `color`,
`pinned`, `archived`, `order`, and `revision`. Swagger includes create, archive,
and restore examples. Preserve the current state when adapting those examples.

| Field | Contract |
|---|---|
| `title` | Optional; up to 200 characters. |
| `items` | Up to 200 ordered rows with unique `id` (1–80 characters), `text` (up to 4,000 characters), `completed`, and nullable `parent`. Children immediately follow their top-level parent; nesting has one level. Clients submit the complete reordered or completion-toggled subtree. |
| `workspace_ids` | Up to 100 Space IDs. Empty means visible everywhere. Any matching active Space includes a linked note; no active Spaces means all notes. Linking does not switch the page context. |
| `references` | Up to 50 `{kind, id}` links; `kind` is `actionable` or `idea`, and ID length is 1–160. These links do not modify their source records. |
| `color` | `slate`, `blue`, `mint`, `plum`, or `amber`; defaults to `slate`. |
| `pinned`, `archived` | Booleans, both defaulting to false. Clients filter `archived` for active/archive views. |
| `order` | Finite number, default `0`. Listing sorts pinned first, then ascending order, then note ID. |
| `revision` | Nonnegative integer. `0` creates a new identity; subsequent writes require the latest returned value and increment it. |

Response notes also contain `id`, `updated_at` (UTC ISO 8601), and sanitized
`items[].html`. **Remove those response-only fields before sending a write.**
`active` in the list response contains the shared context's Space IDs.

Errors use the standard `detail` response: **401** requires owner sign-in;
**403** means a missing/invalid write CSRF token; **409** means a stale revision,
a missing identity with a nonzero revision, or an already-deleted note;
**422** reports body/identity validation errors. Deleting an unknown identity
with revision `0` returns **404**. On conflict, retrieve the latest state and
resolve changes before retrying; do not blindly increment the revision.

Creation, archive transitions, and deletion enqueue corpus snapshots. Edits and
restore do not. A successful note response does not guarantee corpus delivery
has completed: delivery uses a durable outbox, and later reads/writes retry
pending submissions. Deletion does not remove earlier corpus snapshots.
See [Quick Notes](QUICK-NOTES.md) for UI behavior and checklist controls.

## MCP documentation hub

Developer Resources uses the shared Integrations tab styling: HTTP API, MCP
server setup, and Tool catalogue are separate panels. Arrow keys, Home, and End
switch tabs; URL fragments preserve the selected panel. Tool apps appear in a
responsive card grid with descriptions, counts, and expandable tool details.

The hub also describes the `harqis-work` stdio MCP server, provides editable-path
client configuration examples for Windows and macOS/Linux, and lists discovery
commands for the shared CLI. App and tool documentation comes from
`tools/catalog.py` and the registered source files. Reading the page does not
import app integrations, start an MCP process, call tools, or check credentials.
Search by app, tool name, or description; expand tools for their declared Python
signature and docstring. Use `python -m tools schema <app> <tool>` for the runtime
JSON input schema. Dynamic registrations and the connected client's actual
availability must be checked through that client's tool discovery.

`MCP_ENABLED_APPS` can filter the stdio server's app registrations; unset/empty
attempts all apps. The server is launched on demand by its client and has no
HTTP/SSE listener. Do not use the Swagger URL as an MCP connection endpoint.
