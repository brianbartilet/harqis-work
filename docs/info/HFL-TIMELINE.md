# Activity Corpus ideas and follow-ups

The heatmap remains a record of observed activity. Its timeline panel connects evidence, proposed ideas, manual actions, planned dates, and status history.

## Use

Select a heatmap day, then **Ideas & actions** to reach the panel. Pinned ranges also select the period; the date inputs support up to 31 days. The panel initially shows yesterday, or dates from the current corpus URL. Suggestions cover all unprotected entries in those dates, independently of text/tag filters on document cards.

Open **Evidence & completion check** to inspect a cached suggestion. **Make actionable** opens a form for the expected outcome, optional review date and deadline. An individual corpus entry also has a **Make actionable** link. Adoption creates one persistent action, even when two windows submit it together.

Amber dots mean current planned review/deadline dates. Cyan outlines mean linked source or action history, including superseded planned dates. Neither modifies activity counts, intensity, or document totals. Markers are navigation aids, not notifications. Select a marked day to see its linked actions. Use **Show actions from all dates** when looking for an unscheduled action.

Manually change Open → Active / Waiting → Done, or dismiss/reopen. Every edit records an immutable revision and uses optimistic concurrency. On completion, the app submits a deduplicated `hfl-followup-outcome` entry with the expected and actual outcome. Delivery failures remain pending and are retried by the daily job. This is a manual completion receipt, not an agent execution receipt or automated assessment.

## Cached analysis and scheduling

`generate_timeline_suggestions` runs at **04:15 in the configured Beat timezone (currently Asia/Manila, the same UTC+8 offset as Singapore)** for the previous Singapore calendar day. The active schedule takes effect when the canonical host deploys this branch and restarts Beat/worker. Local preview startup does not deploy or start Beat.

The bounded pass reads the canonical privacy-filtered corpus API, selects up to 200 entries (at most 400 scanned), fetches up to 60 related entries through today, including bounded context from the latest two days, and performs at most five model calls with 40 selected entries each. It reuses Activity Radar's redaction, compact evidence, and finding validation. Newer completion evidence can suppress resolved findings. Retrieval is bounded and does not prove that an unresolved item was missed; uncertain conclusions remain explicitly uncertain.

Browsing reads SQLite only and never dispatches analysis. **Explore this period** explicitly queues a refresh for 1–31 past/current days. Failed runs retain previous suggestions. A 15-minute lease prevents concurrent investigations; interrupted work can be retried explicitly. Identical category/title/evidence identities share suppression and adoption state across periods. Semantically similar rewordings can still appear separately; this version does not promise semantic deduplication. A successful refresh replaces that period's associations without erasing historical suppression.

No proposals execute automatically. No reminders, messages, external calendar events, or Trello cards are sent.

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
