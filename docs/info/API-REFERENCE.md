# Unified HARQIS API reference

Open **Build → API & MCP** (`/developer-tools`) for the documentation hub, then
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

## MCP documentation hub

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
