# Thinking Second Brain Workflow

## Runtime decision

**Classification:** hybrid
**Schedule owner:** Celery Beat
**Agent owner:** the optional loopback Hermes `second-brain` profile interprets
ambiguous context and returns a schema-validated candidate only.
**Celery owner:** context persistence, override precedence, reconciliation,
read-only collection, feed projection, retries, and review evidence.

Manual selections and privacy/configuration controls are deterministic and never
delegated to an LLM. Keywords and current `ScheduleCategory` calendar blocks are
additive signals. When Hermes or Calendar is unavailable, the resolver continues
from remaining typed context and the configured time-window/default fallback.

### `reconcile_second_brain`

**Goal:** resolve owner-configured categories and refresh each due, allowlisted
advisory operation attached to those categories.

**Runtime:** `hybrid` — Hermes may propose modes; Celery owns execution.
**Schedule owner:** `Celery Beat`
**Apps chained:** `apps/jira` supplies recent owner-relevant issue changes;
results are normalized into the canonical feed.
**Schedule:** every 15 minutes plus event-triggered runs; category refresh
intervals suppress collection that is still fresh
**Queue:** `WorkflowQueue.HOST`
**OS:** cross-platform canonical host
**Required config keys:** `JIRA`
**Required env vars:** existing Jira variables; optional
`SECOND_BRAIN_HERMES_BASE_URL`, `SECOND_BRAIN_HERMES_API_KEY`, and
`SECOND_BRAIN_HERMES_MODEL` when Hermes is enabled.
**Data flow:** typed context + current calendar blocks → deterministic/Hermes
category candidate → allowlisted operation → normalized category projections →
SQLite revision + SSE/Redis notification.
**AI prompt:** `workflows/second_brain/prompts/context_interpreter.md`
**Outputs / side effects:** advisory feed state and Elasticsearch task review;
no external system mutation.
**Failure behavior:** each operation records an isolated failure while other
operations and the canonical snapshot remain available.

## Client defaults

The authenticated web client is enabled by default. Telegram, Rainmeter, and
CLI disclosure are disabled until enabled in the frontend settings. Redis
Streams are an optional low-latency notification layer; SQLite remains the
transactional source of truth.

## Manifesto alignment

| Task | CODE role | PARA bucket | Express target | Review artifact | HFL signal |
| --- | --- | --- | --- | --- | --- |
| `reconcile_second_brain` | capture + organize + distill + express | area | `api:second-brain-feed` | Elasticsearch log + canonical store | yes |

Architecture, privacy controls, interfaces, operational targets, and the future
approval-gated action plane are documented in
[`docs/info/SECOND-BRAIN.md`](../../docs/info/SECOND-BRAIN.md).
