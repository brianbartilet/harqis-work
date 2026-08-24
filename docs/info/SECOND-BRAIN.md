# Thinking Second Brain

The Thinking Second Brain is an advisory, context-aware feed that activates a
small set of read-only workflows for the user's current mode. The first release
supports `work`, `play`, and `finance`, with automatic selection and a
time-bounded manual override such as `/mode work+finance for 2h`.

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

`reconcile_second_brain` runs every 15 minutes and can also be dispatched by an
input event or manual refresh. It resolves the active modes, selects operations
from `workflows/second_brain/registry.py`, and runs each operation in isolation.
One collector failure therefore produces a visible failure item without
discarding successful items or the last canonical snapshot.

The initial operation is `work.jira_changed`, a read-only Jira collector.
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

The current config is versioned in the canonical SQLite store. The web client
cannot be disabled from the UI; all other clients and Hermes are opt-in.

| Variable | Default | Purpose |
| --- | --- | --- |
| `SECOND_BRAIN_STORE_PATH` | `.harqis-data/second-brain.sqlite3` | Canonical SQLite path. |
| `SECOND_BRAIN_REDIS_URL` | empty | Optional Redis URL for capped `second-brain:feed:v1` notices. |
| `SECOND_BRAIN_HERMES_BASE_URL` | `http://127.0.0.1:8643/v1` | Dedicated loopback Hermes API. |
| `SECOND_BRAIN_HERMES_API_KEY` | empty | Server-side bearer; required when Hermes is enabled. |
| `SECOND_BRAIN_HERMES_MODEL` | `second-brain` | Dedicated no-tools model/profile alias. |
| `SECOND_BRAIN_SESSION_TOKEN` | empty | CLI bearer, sent only to the authenticated feed endpoint. |
| `SECOND_BRAIN_TELEGRAM_CHAT_ID` | empty | Destination used only after Telegram is enabled. |

Existing Jira and Telegram app credentials remain in the app configuration;
they are never copied into the Second Brain store.

## Interfaces

- Web UI: `/second-brain`
- Snapshot: `GET /second-brain/api/feed?client=web`
- Resumable change stream: `GET /second-brain/api/events`
- Typed command: `POST /second-brain/api/commands`
- CLI: `python scripts/second_brain_feed.py --base-url http://127.0.0.1:8080`
- Rainmeter: `workflows.hud.tasks.second_brain.show_second_brain`

All web routes require the existing signed owner session. The CLI additionally
requires its explicit opt-in and token. Telegram delivery uses silent digests
and the redacted projection.

## Adding a workflow

1. Build a read-only collector with a bounded timeout and source-side rate
   limit behavior.
2. Normalize output to `FeedItem`; supply stable `logical_key`, provenance,
   expiry, sensitivity, and eligible clients.
3. Add a fixed operation entry to `registry.py` for one or more modes.
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
