# Activity Corpus ideas and follow-ups

The heatmap remains a record of observed activity. Its timeline panel connects evidence, proposed ideas, manual actions, planned dates, and status history.

## Use

Select a heatmap day to open its existing popup, with Create entry, Pin dates, Show document, and Matching entries in their original order. **Ideas** and **Actions** are separate sections below Matching entries. All three use the same rotating caret; opening one closes the others, and the popup keeps a consistent width. Ideas and Actions start collapsed. Saving keeps the currently expanded section open, so Ideas can be browsed continuously. There is no separate timeline section below the heatmap; analysis supports periods up to 31 days. Suggestions cover all unprotected entries in those dates, independently of text/tag filters on document cards.

Open **Evidence & completion check** to inspect a cached suggestion. **Make actionable** opens a form for the expected outcome, optional Review on and Complete by dates. The **Prompt** field stores up to 20,000 characters of plain text or Markdown instructions for later LLM integration; saving does not execute it. Prompt edits are included in revision history. **Review on** marks when to revisit progress; **Complete by** is the completion target that determines overdue status. Neither sends notifications. An individual corpus entry also has a **Make actionable** link. Adoption creates one persistent action, even when two windows submit it together.

Dots on current Review on and Complete by dates aggregate all non-dismissed actions: yellow if any are Open/Active; otherwise blue if any are In Progress (including a mix with Done); green if all are Done. Dismissed items contribute no dot. An action scheduled twice on the same date counts once. Cyan outlines mean linked source or action history, including superseded planned dates. Neither modifies activity counts, intensity, or document totals. Markers are navigation aids, not notifications. Select a marked day to see its linked actions. Unscheduled actions remain accessible from their source date and action history dates.

Manually change Open → Active / In Progress → Done, or dismiss/reopen. Every edit records an immutable revision and uses optimistic concurrency. On completion, the app submits a deduplicated `hfl-followup-outcome` entry with the expected and actual outcome. Delivery failures remain pending and are retried by the daily job. This is a manual completion receipt, not an agent execution receipt or automated assessment.

## Cached analysis and scheduling

`generate_timeline_suggestions` runs at **04:15 in the configured Beat timezone (currently Asia/Manila, the same UTC+8 offset as Singapore)** for the previous Singapore calendar day. The active schedule takes effect when the canonical host deploys this branch and restarts Beat/worker. Local preview startup does not deploy or start Beat.

The bounded pass reads the canonical privacy-filtered corpus API, selects up to 200 entries (at most 400 scanned), fetches up to 60 related entries through today, including bounded context from the latest two days, and performs at most five model calls with 40 selected entries each. It reuses Activity Radar's redaction, compact evidence, and finding validation. Newer completion evidence can suppress resolved findings. Retrieval is bounded and does not prove that an unresolved item was missed; uncertain conclusions remain explicitly uncertain.

Browsing reads SQLite only and never dispatches analysis. **Explore** explicitly queues a refresh for 1–31 past/current days. Failed runs retain previous suggestions. A 15-minute lease prevents concurrent investigations; interrupted work can be retried explicitly. Identical category/title/evidence identities share suppression and adoption state across periods. Automatic creation also compares intended outcomes against all existing actions and dismissed ideas to catch paraphrases. Semantic matching is a model judgment: uncertain comparisons remain ideas for manual review. A successful refresh replaces that period's associations without erasing historical suppression.

High-confidence ideas can automatically become action records after a second completion and semantic duplicate review. No action prompts execute automatically. No reminders, messages, external calendar events, or Trello cards are sent.

## Persistence and deployment

The canonical frontend/API and HOST worker must share `HFL_TIMELINE_STORE_PATH`, defaulting to `<HARQIS_DATA_ROOT or repository/.harqis-data>/runtime/hfl-timeline.sqlite3`. Back up this database with the corpus. Owner routes `/hfl-corpus/timeline/*` proxy to the configured canonical `/api/hfl/timeline/*` API. Owner sessions protect browser routes; the existing HFL API bearer token protects canonical routes.

`HFL_TIMELINE_LOCAL_PREVIEW=1` keeps timeline writes in the local preview database and runs explicit exploration in a background thread, while evidence remains canonical. Preview completions remain local and do not submit corpus entries. This switch is for development only; production uses Celery on HOST. On this branch, localhost uses `.harqis-data/preview-followups/timeline.sqlite3`.

The earlier Second Brain agenda prototype has been removed. Second Brain remains unchanged; there is one action store in HFL.

## Automation Runtime Decision

**Classification:** celery. **Confidence:** high.

**Reasoning:** fixed, bounded, schema-driven evidence transformation with durable caching; no autonomous tool selection.

**Execution owner:** canonical HOST worker for analysis/retries; owner-authorized API for action mutations and completion submission. **Schedule owner:** Celery Beat only. **Agent responsibilities:** none.

**Required controls:** period lease/run ID; stable suggestion identity; transactional adoption; action revision check; completion dedup key `timeline:<id>:<version>`; owner/API authorization; privacy-filtered inputs and Radar redaction. The user requested a daily previous-day job and manual action lifecycle. Runtime decision skill SHA256: `388e5c5221c4b43a53bb6a41033534b6a49e2ef17da6b44f69f3da8b64a690af`.

**Review artifact:** cached run coverage/state, linked evidence, immutable action revisions, HFL delivery receipts, and existing Elasticsearch task logs. **Open questions:** none blocking this prototype. Agent proposals/receipts and suggested plan-versus-actual assessments remain future extensions.

Review on and Complete by are optional for manual actionables and can both be cleared. Clearing Complete by removes its current status dot and overdue status; the old date retains a history outline. Any remaining Review on date continues to show the aggregate status dot. Existing deadlines are preserved until manually edited.

Existing Waiting statuses are migrated to In Progress without changing action IDs or rewriting immutable history. Old planned dates retain history outlines but no status dots after rescheduling.


## Automatic actions and manual deadlines

Both Explore and the daily previous-day job chain automatic creation after caching ideas. A second bounded Haiku 4.5 review evaluates high-confidence candidates against evidence, existing actions (including Done and Dismissed), and dismissed ideas. Concrete new recommendations may qualify without a previous commitment; specific doubts about completion or duplication defer creation. A create decision requires high confidence, a clear completion check, and an evidence-based reason. Confidence alone is insufficient.

An automatic action starts Open and carries its original HFL link and an Automatic badge with the creation rationale. Review on is the current Singapore date; Complete by is left blank so the owner can review the action and set a deadline manually. The review date gets a status dot; no future deadline dot is added until a Complete by date is set. The automatic deadline offset and its Profile settings section/API have been removed. Previously stored offsets are ignored and existing action dates are not rewritten.

Semantic duplicates link the new idea to the prior action without modifying its status, dates, notes, prompt, or history. Dismissed ideas suppress equivalent new recommendations too. Candidate batches are committed transactionally only if actions, suppressed ideas, and run ownership have not changed since review. Concurrent changes defer automatic creation rather than trusting a stale comparison.

At most 40 candidates are reviewed in batches of eight (up to five additional model calls). More than 500 existing action/suppression records, or a review payload over 250,000 characters, defers automatic creation; comparison history is never silently truncated. Model errors retain cached ideas and any previously committed actions. The run reports created, skipped-duplicate, and deferred counts, with failure detail when applicable. Explore retries unadopted ideas; adopted ideas remain deduplicated.

The running status includes the automatic review phase. Daily scheduling and model IDs are unchanged. This feature creates internal action records only; execution bridges, external notifications, and automatic completion remain out of scope.


## Pinned categories and date-block instructions

Memory Signal categories have optional **Agent guidance** (stored in the category `instructions` property), and date blocks have a required **Title**, optional **Notes**, and optional **Instructions** (stored in the pin `prompt` property). Both instruction fields store up to 20,000 characters of plain text or Markdown, preserving whitespace. Saved text opens in a sanitized Markdown preview; **Edit** switches to the text editor and **Preview** renders the current draft. Saving stores the raw text. These fields do not run agents, send messages, or register schedules. Category Agent guidance describes shared sources, tone, constraints, and output format. Pin Instructions describe the task and expected result for its date range. A future bridge may combine runtime rules, category guidance, pin instructions, and evidence; scheduling, recipients, and execution permissions still require explicit configuration. Both fields remain independent; no inheritance or execution bridge is implemented.

On first opening the upgraded pin store, existing Notes are copied into Title and retained in Notes. Blank notes become **Untitled pin**. Migration preserves IDs, category assignments, dates, and timestamps and does not overwrite later title edits. Titles allow 2,000 characters to retain existing notes without truncation; long labels truncate only visually in the pinned list.

For an explicit migration before upgrading a host, use the standalone script against
that host's frontend `PROFILE_STORE_PATH` (not `HFL_TIMELINE_STORE_PATH`):

```bash
python scripts/agents/hfl/migrate_pin_titles.py --database /path/to/profile.sqlite3
python scripts/agents/hfl/migrate_pin_titles.py --database /path/to/profile.sqlite3 --apply
```

The first command previews counts without changing data. Apply creates a consistent
SQLite backup beside the database, then adds and populates Title in one transaction.
Notes are retained verbatim. An existing Title column makes the migration a no-op,
including when the app already migrated it; edited titles are never overwritten.
The script migrates only Title/Notes; the app adds instruction fields on startup.
See the [script usage and recovery notes](../../scripts/README.md#scriptsagentshflmigrate_pin_titlespy).

The pinned list displays Title, with **ENDS DD MMM YYYY** on hover. The edit dialog continues to expose both dates on mobile. Memory Signal retains its original compact height, with a bounded scrolling pinned list so expanding categories does not grow the panel. **+ Category** remains below the list. Pin metadata remains private and uses the existing owner-authenticated, CSRF-protected memory-pins endpoint and store.

### Category agent history and archiving

The category editor has an **Agent history** button that opens a separate dialog with event cards. Each card lets you
read its sanitized Markdown output, recorded period, agent/model, outcome, timestamp,
and prompt snapshots. Events load newest first in pages of 20; output is not loaded
with the heatmap. Snapshots survive category/pin edits and pin removal.

History is an append-only collection in `memory_pin_agent_events`, not an editable
text property. The owner-authenticated, CSRF-protected `/hfl-corpus/memory-pins`
endpoint accepts `record_agent_event` with `category_id`, `range_id`, a unique
`event_key`, `agent`, `output`, optional `model`, `status` (completed/partial/failed),
and optional `system_prompt` (the actual runtime prompt). If omitted, system_prompt
snapshots current category guidance. The server snapshots the saved pin title,
dates, and instructions at recording time. Delayed receipts should be recorded before
editing the source pin; this is not a reconstruction of historical execution context.
Retries with the same category/event key retain the original receipt. Output supports
100,000 characters, prompt 20,000; do not include credentials or secrets in receipts.
`agent_history` accepts category_id and optional before_id for pagination. There is
no event edit/delete UI and no scheduler or external agent bridge.

**Archive category** replaces deletion, including legacy delete_category requests.
Pins and events remain stored but archived categories and their pins are excluded
from the heatmap and pin selection. **Archived categories** in the category dialog
lets you inspect history and restore the category. New events/pins require an active
category; existing retry receipts remain accessible. Archived names stay reserved.
Schema additions run automatically when the pin store opens.
