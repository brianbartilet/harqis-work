# Thinking Second Brain

## Workspace navigation

**Express → Second Brain** opens Kanban at `/hfl-corpus/actions`.
Compact icon links in each view's existing toolbar connect **Kanban / Dashboard / Fleet**.
Each toolbar shows only the other two destinations, with tooltips and accessible
labels; there is no separate navigation row.
Dashboard remains at `/second-brain`; Fleet and agent deep links remain at
`/agents`. Activity Graph stays under Distill for memory retrieval.

Fleet's **Agent work** drawer replaces its embedded HUD. Its agent picker is
available on desktop and mobile. It shows attention,
running, queued, assigned and recent work from the filtered graph, narrowed to
a selected agent. Execution state is separate from canonical action status;
missing execution records never imply that an agent is idle. At mobile widths,
selection replaces the drawer with the existing inspector; **All agent work**
returns to the overview. HUD widgets, layouts and collectors remain in Dashboard.

Butler owns scheduled briefings and attributed recorded agent updates. The
existing schedule owner is unchanged, and its prompts receive a bounded set of
attributed recorded agent results. Updates deduplicate attempts by source,
exclude existing Butler delivery runs, and link back to their records. Agent
filtering and per-owner browser-local Reviewed state reduce repeat noise. A steady
cyan dot on the Butler launcher indicates unread completed results or attention
updates. Pending, queued and running items do not light it. Opening the panel
does not mark items reviewed; Reviewed and Mark unread update the dot across
tabs. Visible pages check for updates every 30 seconds while the panel is closed. The
feed shows at most 30 agent updates from bounded execution and observation
snapshots; it is not a complete audit history. **Ask Butler** attaches visible
agent/action and Space context and prepares text without sending a message.

Activity Corpus, Activity Graph, Kanban, Fleet and Dashboard share saved Space
preferences, including multiple Spaces, All activity and Dynamic mode. Individual
view filters and graph layouts remain local to their view. Space transitions do
not reset Fleet filters. Temporary Butler context is explicit and removable; it
does not modify saved Space preferences. Related memory shows up to five currently visible linked entries, artifacts or
evidence links, with their source and relationship. Activity Graph opens
separately, preserving the work view. Run artifacts and evidence explicitly
link back to their action rather than only to their producing agent.

The product workspace and the advisory engine below share the Second Brain
name but have different responsibilities. Work navigation does not change the
advisory feed's categories, allowlist, clients or execution schedules.

The Thinking Second Brain is an advisory, context-aware feed that activates
allowlisted read-only operations for the user's current categories. Categories
are owner-configurable; a fresh store contains only the non-archivable `default`
category. Stable IDs survive display-name changes and historical items from a
removed category remain visibly labelled as an archived source.

The authenticated web module is enabled by default. Telegram, Rainmeter, and
the CLI are presentation adapters over the same canonical feed and remain
disabled until an owner enables them.

## Architecture

```text
calendar / command / desktop / location / voice transcript
                         |
                  typed ContextEvent
                         |
        SQLite canonical store + optional Redis notice
                         |
      deterministic resolver ---- optional Hermes candidate
                         |
             effective ModeDecision
                         |
        allowlisted, read-only Celery operations
                         |
      ranked and deduplicated FeedItem revisions
                         |
       web | Telegram | Rainmeter | CLI adapters
```

This is a hybrid runtime with one schedule owner:

- Celery Beat owns the 15-minute reconciliation schedule. Celery also owns
  persistence, retries, rate limits, collectors, delivery, and failure state.
- Hermes is optional and only proposes a schema-validated mode candidate for
  ambiguous context. It has no tools or authority to invoke workflows.
- Manual overrides, source controls, disclosure, operation allowlists, and
  client enablement are always deterministic.
- SQLite in WAL mode is the transactional source of truth. Redis Streams only
  provides low-latency change notices; reconnecting clients recover from the
  SQLite revision cursor.

This extends the existing HUD and RADAR model. Rainmeter becomes one adapter;
it is not the state owner and can be migrated gradually.

## Runtime behavior

`reconcile_second_brain` runs every 15 minutes and is also dispatched by input,
category, selection, and delivery changes. It resolves the active modes, selects operations
from `workflows/second_brain/registry.py`, and runs each operation in isolation.
One collector failure therefore produces a visible failure item without
discarding successful items or the last canonical snapshot.

The initial operation is `jira.changed`, a read-only Jira collector.
Operation IDs are code-owned and allowlisted; configuration cannot import an
arbitrary task or grant new authority. Workflows should normalize their result
to `FeedItem`, including provenance, freshness, sensitivity, eligible clients,
and a stable logical key. The store uses that key and a content hash to suppress
unchanged revisions.

Suggested service objectives are:

| Trigger | Target | Implementation note |
| --- | --- | --- |
| Voice or manual command | 2–5 seconds | Persist immediately, dispatch reconciliation, acknowledge before collection completes. |
| Context/category change | 15–60 seconds | Event dispatch is primary; the 15-minute Beat run repairs missed events. |
| Background refresh | 1–15 minutes | Use source webhooks where available and source-specific reconciliation intervals. |

## Data and privacy

Persist structured context and derived summaries. Raw screenshots and audio
should be converted locally to a bounded event, then deleted or placed under a
short source-specific retention policy. Each future source must be independently
disableable.

Never include credentials, bearer tokens, full account identifiers, or raw
financial identifiers in events, prompts, feed items, logs, or delivery errors.
Hermes receives only bounded structured fields and is accepted only through a
configured loopback HTTP endpoint. Client disclosure is structural:

- web: authenticated owner detail;
- Telegram: redacted owner summary;
- Rainmeter: redacted local summary;
- CLI: redacted owner summary and a separate session token.

Feed items declare both their sensitivity and eligible clients. A client that
is disabled or absent from an item's allowlist cannot fetch that item.

## Configuration

The current config is versioned in the canonical SQLite store. The settings
dialog creates, edits, orders, disables, and archives categories. Creation only
asks for the user-facing name and pill color; the server generates a unique,
immutable key used by saved selections and history. Existing category editors
autosave changes. Calendar mappings and operations use bounded scrollable lists.
All current HUD panels have explicit read-only projection adapters: successful
HUD results are redacted, size-bounded, and written to the dedicated
`harqis-second-brain-hud` Elasticsearch index. Second Brain reads those cached
projections and never executes a Rainmeter task; Windows-local panels show an
awaiting-source state until their next normal HUD run. Newly inventoried HUD
tasks remain unavailable until they receive the same explicit adapter. Each
category
owns its pill color, keywords, `ScheduleCategory` calendar mappings, refresh
interval, eligible clients, optional time fallback, and registered operations.
Calendar matches are additive with other signals. Automatic Feed locks the
category pills; turning it off enables multi-select for 30 minutes to 12 hours,
then returns to automatic resolution. The web client cannot be disabled; all
other clients and Hermes are opt-in and autosave.

| Variable | Default | Purpose |
| --- | --- | --- |
| `SECOND_BRAIN_STORE_PATH` | `.harqis-data/second-brain.sqlite3` | Canonical SQLite path. |
| `SECOND_BRAIN_REDIS_URL` | empty | Optional Redis URL for capped `second-brain:feed:v1` notices. |
| `SECOND_BRAIN_HERMES_BASE_URL` | `http://127.0.0.1:8643/v1` | Dedicated loopback Hermes API. |
| `SECOND_BRAIN_HERMES_API_KEY` | empty | Server-side bearer; required when Hermes is enabled. |
| `SECOND_BRAIN_HERMES_MODEL` | `second-brain` | Dedicated no-tools model/profile alias. |
| `SECOND_BRAIN_API_TOKEN` | empty | Scoped bearer shared by the canonical API, CLI, and remote Rainmeter adapter. |
| `SECOND_BRAIN_CANONICAL_URL` | empty | Canonical frontend base URL used by a remote Rainmeter worker. |
| `SECOND_BRAIN_TELEGRAM_CHAT_ID` | empty | Destination used only after Telegram is enabled. |

Existing Jira and Telegram app credentials remain in the app configuration;
they are never copied into the Second Brain store.

## Interfaces

- Web UI: `/second-brain`
- Snapshot: `GET /second-brain/api/feed?client=web`
- Resumable change stream: `GET /second-brain/api/events`
- Typed command: `POST /second-brain/api/commands`
- CLI: `python scripts/second_brain_feed.py --base-url http://127.0.0.1:8080`
- Rainmeter: `workflows.hud.tasks.second_brain.render_second_brain_rainmeter`

Browser routes use the existing signed owner session. Feed and event APIs also
accept `Authorization: Bearer $SECOND_BRAIN_API_TOKEN` for configured CLI and
remote Rainmeter clients. Telegram uses silent redacted digests. Enabling a
delivery immediately projects the current snapshot; later material revisions
are pushed automatically.

The web feed receives updates over authenticated SSE and replaces only its feed
fragment. The main page keeps context management and advisory chat visible; a
`View feed` control opens the cards in a dismissible dialog. Inside that dialog,
sanitized Markdown cards move through a continuously looping ticker viewport on
desktop and mobile. The viewport uses native scrolling: touch or wheel input
temporarily overrides the ticker, which resumes after inactivity. Automatic
motion is disabled for reduced-motion preferences. The collapsed context panel is sticky
beside chat on desktop and appears before it on mobile. The advisory Hermes chat
stores history for eight hours by default
(configurable from one to 168 hours) and cites feed logical keys. Hermes failure
never prevents deterministic context capture or collection.

## Adding a workflow

1. Build a read-only collector with a bounded timeout and source-side rate
   limit behavior.
2. Normalize output to `FeedItem`; supply stable `logical_key`, provenance,
   expiry, sensitivity, and eligible clients.
3. Add a fixed operation entry to `registry.py`, then attach it to categories in Settings.
4. Add deterministic and failure-isolation tests.
5. Regenerate the frontend task catalogue and run the manifesto audit.

Do not add a second scheduler. Webhooks and new input adapters should append a
typed event and dispatch the canonical reconciler with a correlation ID.

## Future consequential actions

Version 1 is advisory-only. A future action plane may update Jira, send a
message, or place a financial order only after a separate design adds:

- a typed intent distinct from feed content;
- policy evaluation and least-privilege credentials per action;
- an owner-visible preview and explicit, expiring approval;
- idempotency keys, amount/scope limits, and a durable audit record;
- step-up confirmation for financial or otherwise high-impact actions;
- a kill switch and reconciliation of the external result.

No feed item, model output, Telegram message, or voice transcript should become
an executable action by itself.

The `manage-second-brain` repository skill can inspect health, validate
mappings, preview or apply category configuration, attach registered operations,
change delivery opt-ins, reconcile, and run focused tests. It cannot register
arbitrary import paths or cross the advisory-only boundary.
