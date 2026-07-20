# Looki L1 → HARQIS-work — wearable lifelog ingestion thesis

> Research and design captured 2026-07-19. **Review artifact only: not approved,
> not implemented, and not scheduled.** This document assesses the Looki L1
> wearable, the outputs currently exposed by its product and developer surfaces,
> and the smallest useful way to integrate those outputs with HARQIS-work.
>
> Vendor behavior, pricing, APIs, app capabilities, and privacy policies can
> change. Official claims are distinguished below from community-observed API
> behavior and unverified implementation assumptions.

---

## 1. Thesis

Looki L1 is unusually compatible with HARQIS-work because it produces the same
class of signal Homework for Life (HFL) is designed to retain: timestamped
moments, images and video, audio context, location, recurring activities,
AI-generated summaries, and searchable personal history.

The integration should not copy every captured file into HARQIS. That would
create an expensive, invasive archive with no proportional Express value.
Instead:

> **Looki captures the world; HARQIS decides what deserves to become durable
> memory.**

The recommended path is a small `apps/looki` adapter plus a bounded
`workflows/hfl/tasks/ingest_looki.py` task. The first version should ingest
moment metadata and selected highlights, while downloading raw media only when
it is needed for grounding, later recall, or an explicitly valuable output.

The first success criterion should be:

> After one day of wearing Looki, HARQIS produces a factual, source-linked HFL
> digest with no duplicates and can retrieve the underlying Looki moment on
> demand.

## 2. Express output

The useful output is not a raw Looki mirror. It is a set of grounded,
reviewable memory surfaces:

1. A compact daily HFL digest containing meaningful Looki moments.
2. Searchable entries in `harqis-hfl-entries`, backed by the Markdown corpus.
3. Stable references from every distilled entry to its Looki moment and any
   retained local artifact.
4. Read-only MCP tools for live Looki recall without automatically writing to
   HFL.
5. Selective access to source frames, clips, or transcripts when a memory needs
   verification.
6. Optional weekly/monthly outputs such as life-rhythm reviews, travel or family
   albums, project-context reconstruction, and time capsules.

This keeps the Capture accountable to an Express path instead of producing an
orphaned lifelog archive.

## 3. Product overview

### 3.1 Hardware

The official Looki L1 product page describes:

- Weight: 32 g.
- Dimensions: 50.53 × 16.84 × 48.02 mm.
- Wear styles: clip, pendant, or bag attachment.
- Water resistance: IP67.
- Photo resolution: 4K.
- Video: 1080p at 30 fps.
- Lens: 16 mm-equivalent, f/2.2, 109-degree field of view.
- Imaging support: EIS and HDR.
- Audio: three microphones with noise reduction and a 1 W speaker.
- Storage: 32 GB local storage.
- Connectivity: Bluetooth 5.0 and dual-band 2.4/5 GHz Wi-Fi.
- Motion sensing: six-axis gyroscope.
- Battery: 375 mAh; approximately 1.5 hours to charge.
- Current Singapore storefront price observed on 2026-07-19: S$329.

Pricing and availability are regional and should be rechecked before purchase.

### 3.2 Capture modes

Official material describes two broad capture patterns.

**Smart interval / Auto Mode**

- Five-second clip every minute: approximately nine hours.
- Nine-second clip every two minutes: approximately eleven hours.
- Eleven-second clip every three minutes: approximately thirteen hours.
- Product copy elsewhere describes AI Mode as lasting "up to 12 hours"; the
  detailed specification gives the more useful 9–13 hour range based on
  cadence.

**Continuous capture**

- Continuous video is stored as ten-minute clips.
- Continuous audio can run for up to two hours.
- Overall continuous audio/video battery life is described as approximately
  one to three hours.

Looki is therefore optimized for intermittent lifelog capture, not continuous
all-day body-camera video.

### 3.3 Native app and AI features

Across the official product page and iOS/Android listings, the Looki companion
app provides or advertises:

- A daily lifelog timeline.
- Automatically grouped Moments.
- Scene and activity tags.
- AI-created clips and story highlights.
- Daily personalized video recaps.
- Auto-generated vlogs.
- Comic-style stories.
- AI-generated event analysis, insights, reminders, and proactive suggestions.
- AI chat grounded in daily recordings.
- Voice notes.
- Media preview and upload.
- Captured-content review and deletion.
- Device status, capture settings, firmware update, and account management.
- Context involving people, objects, places, dates, and potentially precise
  geolocation.

The app listings and user reviews suggest that the creative recap layer is
currently more mature than factual meeting analysis or consistently reliable
voice interaction. User reviews are anecdotal, not product specifications, but
are useful as caution against treating the native AI output as ground truth.

## 4. Data ownership, storage, and privacy claims

### 4.1 Official claims

Looki states that:

- Captured content remains on the device by default.
- Users choose when to upload content for cloud AI processing.
- Cloud uploads happen with user permission rather than silently.
- Uploaded cloud data is automatically deleted after 24 hours.
- Content can be reviewed, managed, and deleted in the app.
- Personal content is not used to train public/general AI models.
- Cloud processing uses AWS infrastructure.
- Third-party AI providers may process content only to provide the requested
  AI functionality and are not permitted to train on personal information.
- Content is protected with encryption at rest and in transit; marketing pages
  additionally describe end-to-end encryption.
- Sensitive-environment filtering is intended to prevent some private material
  from being uploaded for cloud processing.
- Recording activity is communicated through a visual indicator and system
  sounds.
- Covering or turning the camera inward stops visual AI functions.
- Looki completed a SOC 2 Type I audit in 2026.

SOC 2 Type I assesses whether controls were suitably designed at a point in
time. It does not demonstrate that those controls operated effectively over an
extended period; that is the stronger Type II question.

### 4.2 Information the privacy policy says may be collected

Depending on enabled features, Looki may process:

- Images and video.
- Audio clips and voice content.
- Messages, notes, files, and links supplied through the app.
- Automatically captured limited/compressed visual, audio, and contextual
  signals.
- Geolocation, including map-related location services.
- Content metadata.
- Account, contact, purchase, device, network, usage, diagnostics, and unique
  identifier data.

The iOS disclosure additionally says the app may use location while it is not
open. App-store declarations include photos/video, audio, location, contact
information, identifiers, usage data, and diagnostics. These declarations are
provided by the developer and are not independently verified by Apple or
Google.

### 4.3 Important tensions and caveats

Several points need to be reviewed rather than accepted as simple marketing
claims:

1. The product and privacy pages describe end-to-end encryption, while the
   Terms of Service say operation of the service "may be unencrypted" and may
   involve network transformations and third-party hosting. These statements
   should be reconciled before treating the cloud path as appropriate for highly
   sensitive material.
2. Looki says uploaded processing data is deleted after 24 hours, while the
   broader privacy policy says uploaded content is retained as necessary for
   service purposes and under retention policies. The exact distinction between
   processing copies, account content, generated outputs, logs, and backups is
   not fully specified.
3. Looki does not use personal content to train public models, but it may create
   aggregated or de-identified data for research, product improvement, and other
   lawful business purposes.
4. Precise location can be highly identifying even if other account fields are
   described as not linked to identity.
5. The Terms of Service place responsibility for lawful recording, bystander
   consent, and necessary permissions on the user.

### 4.4 Recording boundaries

The policy expressly warns against use in high-risk or sensitive locations,
including:

- Dressing rooms and restrooms.
- Medical facilities.
- Government agencies.
- Military bases.
- Critical infrastructure.

Any HARQIS integration should add its own controls rather than assuming the
wearable's filtering is sufficient:

- Excluded locations and private-time windows.
- Location redaction or coarse-location mode.
- Configurable people/face suppression.
- Local-only retention for selected categories.
- A deletion workflow covering the HFL Markdown entry, ES projection, raw
  artifact, thumbnails/frames, transcript, and deduplication state.
- No storage of temporary signed URLs in durable records.

## 5. Developer and export surfaces

### 5.1 Looki-operated developer platform

A Looki-operated developer portal exists at:

- `https://web.looki.tech/api-keys`

It redirects unauthenticated users to a Looki login page. A public community
client reports that users must:

1. Log into the Looki app or web platform.
2. Open the API Keys page.
3. Apply for API access.
4. Wait for Looki approval.
5. Create a key with an `lk-...` prefix.

That approval flow has not been tested with Brian's account. It is an external
community report and remains a Phase 0 validation item.

### 5.2 API base and authentication

Community research identifies the developer API base as:

```text
https://open.looki.tech/api/v1
```

Authentication uses:

```http
X-API-Key: lk-...
```

An unauthenticated request to `/api/v1/me` was independently checked on
2026-07-19. The live Looki-operated endpoint returned HTTP 422 and explicitly
reported a missing `x-api-key` header. This confirms the service and header
requirement, but not account eligibility or the full endpoint contract.

No public Swagger/OpenAPI document was accessible at the usual `/docs` or
`/openapi.json` locations according to the community integration.

### 5.3 Community-documented endpoints

A working open-source client documents seven read endpoints:

```text
GET /me
GET /moments?on_date=YYYY-MM-DD
GET /moments/search?query=&start_date=&end_date=&page=&page_size=
GET /moments/calendar?start_date=&end_date=
GET /moments/{moment_id}
GET /moments/{moment_id}/files?highlight=&cursor_id=&limit=
GET /for_you/items?group=&liked=&recorded_from=&recorded_to=&cursor_id=&limit=&order_by=
```

These endpoints potentially expose:

- Account identity for connection verification.
- Moments for a specific day.
- Search over generated moment metadata/tags.
- Calendar summaries over a date range.
- Stable moment IDs and moment detail.
- Per-moment media files.
- Looki-generated comics, vlogs, moment posts, weekly color summaries, and event
  analyses.

The endpoint inventory and observed response behavior come from a small
community repository, not a Looki-published specification. Payload schemas must
be captured from an approved account before implementation.

### 5.4 Community-observed media behavior

The same client reports that:

- Moment files are commonly ten-second MP4 clips.
- The `thumbnail` field is often `null`.
- A file response can contain media type, size, duration, location, creation
  time, timezone, and a temporary download URL.
- Temporary URLs expire after approximately one hour.
- Calling the files endpoint again provides a refreshed URL.
- The observed API limit is approximately 60 requests per minute.
- Timestamps include a local ISO-8601 offset; the community user's data used
  `+08:00`, but HARQIS must not assume all Looki users or devices do.

Implications for HARQIS:

- Download a selected file immediately; never enqueue only the temporary URL for
  processing much later.
- Persist a stable Looki file/moment identifier, not the signed URL.
- Use bounded concurrency and explicit rate limiting.
- Extract representative frames with ffmpeg before vision analysis.
- Treat timezone as data from the source, not a global constant.

### 5.5 Search and generated-description quality

Community testing reports two limitations:

1. Semantic search appears to operate on Looki-generated labels and
   descriptions rather than raw visual/audio embeddings exposed to the API.
2. Looki's titles and descriptions can romanticize scenes or infer social
   activity that the underlying footage does not support.

HARQIS should therefore apply this rule:

> Looki-generated text is an index and a hypothesis, not a factual memory.

Use generated metadata for cheap discovery and ranking. Use raw frames, audio,
transcripts, and other personal context when accuracy matters.

### 5.6 Outputs not yet confirmed

The research did not find a documented:

- Webhook or event-push interface.
- Changes feed or incremental-sync cursor.
- Bulk ZIP/JSON/CSV account export.
- Dedicated transcript endpoint.
- Stable thumbnail endpoint.
- Public SDK maintained by Looki.
- Public OpenAPI schema.
- Documented USB mass-storage workflow.
- Automated Google Drive export.

The app can save/share media to cloud or social surfaces, but no reliable bulk
or scheduled export contract was found. A privacy/data-access request may yield
an account export, but that would be a one-off rights workflow, not a practical
continuous ingestion channel.

### 5.7 Terms and integration boundary

Looki's Terms of Service prohibit unauthorized bots, scraping, reverse
engineering, and access outside interfaces provided by the company. They also
limit the service to personal, non-commercial use.

Therefore:

- Use an approved developer API key.
- Do not scrape private mobile endpoints or intercept app traffic as the normal
  integration strategy.
- Keep the integration personal and read-only unless Looki explicitly permits
  additional use.
- Treat the community client as research evidence and a protocol sketch, not as
  permission to bypass access controls.

## 6. Existing HARQIS-work primitives to reuse

Habit 5 inspection found that HARQIS already has nearly every downstream stage.
A separate general-purpose wearable subsystem is unnecessary.

### 6.1 Canonical memory layer

Relevant paths:

- `workflows/hfl/README.md`
- `workflows/hfl/dto/entry.py`
- `workflows/hfl/tasks/capture.py`
- `workflows/hfl/es_store.py`
- `workflows/hfl/mcp.py`

`HflEntry` is the canonical distilled-memory DTO:

- `when`
- `moment`
- `what_happened`
- `why_it_stayed`
- `possible_use`
- `tags`
- `references`

The Markdown corpus is the durable source of truth; Elasticsearch is the
queryable projection. Looki should terminate in this path rather than introduce
a parallel memory schema.

Provenance can initially use references such as:

```text
looki:<moment-uuid>
looki-file:<file-id>
/retained/local/artifact/path
```

Temporary signed URLs must not be stored as durable references.

### 6.2 Plaud adapter and audio pipeline

Relevant paths:

- `apps/plaud/references/adapter.py`
- `apps/plaud/references/dto/recording.py`
- `workflows/hfl/tasks/ingest_plaud.py`
- `workflows/hfl/prompts/ingest_plaud.md`

Plaud provides the closest acquisition architecture:

- Backend interface.
- Cloud and folder implementations.
- Normalized DTOs.
- Vendor-transcript precedence.
- Audio download and Whisper fallback.
- ffmpeg chunking for oversized audio.
- Per-recording HFL distillation.
- Raw artifact archiving.
- Stable source references.

Looki should copy the adapter seam, not the product-specific code. If selected
Looki video needs speech analysis, its audio track can feed the same bounded
Whisper path.

One Plaud weakness should not be copied: stable ES upsert IDs do not by
themselves prevent duplicate Markdown appends. Looki must deduplicate before the
model call and before corpus append.

### 6.3 Media analysis

Relevant path:

- `workflows/hfl/tasks/analyze_media.py`

This task already provides:

- Bounded image sizing.
- Evenly sampled video frames.
- Story-worthiness filtering.
- Location and EXIF enrichment.
- Source references.
- Per-source quotas.
- Strong path confinement.
- Durable locking, completion markers, and retry behavior.

Selected Looki clips should be materialized into the canonical dumps inbox and
processed through this path, or reuse its internal frame-analysis primitives.
There is no reason to create a second vision pipeline.

### 6.4 Dumps acquisition and archive

Relevant paths:

- `workflows/dumps/README.md`
- `workflows/dumps/files.py`
- `workflows/dumps/tasks/pull.py`
- `workflows/dumps/tasks/transfer.py`

Dumps is the existing raw-artifact substrate. It offers date-aware inbox
organization, backfills, source provenance, remote-device pulls, confinement,
and downstream-compatible layouts.

Looki media acquired through the cloud API should land in a Looki-specific dumps
or archive subtree. HFL should reference the retained artifact rather than
embed raw content.

### 6.5 Time-capsule backfills

Relevant path:

- `workflows/hfl/tasks/time_capsule.py`

If Looki later supplies a one-off account archive, `collect_time_capsule` can
inventory and summarize the export. It already recognizes common text,
document, image, video, and audio formats. Audio is metadata-only in this path,
so a Looki export requiring transcription would still need the Plaud/Whisper
flow.

### 6.6 Google Drive as a possible transport

Relevant paths:

- `apps/google_drive/`
- `apps/google_apps/references/web/api/drive.py`

If Looki later gains a stable Drive export, HARQIS can poll a dedicated folder,
download new files into dumps, and preserve `drive:<file-id>` provenance.
Existing Drive support does not currently provide a scheduled Drive-to-HFL
workflow, change-token checkpoint, or downloaded-file ledger; those would need
to be added.

Drive would be an acquisition transport, not the HFL store.

### 6.7 MCP as the operator surface

Relevant paths:

- `mcp/server.py`
- `workflows/hfl/mcp.py`
- `apps/plaud/mcp.py`

MCP is appropriate for read-only operator tools and manual inspection. It is not
an inbound event bus. Looki's scheduled acquisition should remain a Celery task,
while MCP can expose live views and targeted manual operations.

## 7. Proposed architecture

### 7.1 Capture

Add an `apps/looki` adapter responsible for:

- `X-API-Key` authentication.
- Connection verification through `/me`.
- Date/calendar collection.
- Moment detail and pagination.
- `For You` generated-content collection.
- Immediate download of selected media before signed URLs expire.
- Rate limiting, retries, and bounded page/file caps.
- A clean no-op when credentials are missing or no data exists.

The API key belongs in HARQIS app-secret configuration and must never be written
to a tracked file or log.

### 7.2 Organize

Normalize each Looki item into a DTO containing at least:

- Stable moment UUID.
- Stable file/item IDs.
- Capture start/end time and timezone.
- Creation time.
- Looki title and description.
- Location, if available and permitted.
- Native generated-content type.
- Media type, duration, and size.
- Highlight status.
- Local retained-artifact path.
- Stable provenance references.
- Whether narrative text is Looki-generated, HARQIS-generated, or directly
  transcribed.

Deduplicate before any media download, model call, or corpus append. Prefer the
stable external moment/file ID. If a local-file fallback is ever used, combine
content hash, source-relative path, and capture time.

### 7.3 Distill

Use two levels.

#### Level 1 — lightweight daily ingest

- Pull daily moment metadata.
- Pull selected native event analyses or `For You` content.
- Rank by highlight state, novelty, duration, location change, and explicit user
  interest.
- Produce one bounded daily Looki digest or a small number of genuinely
  story-worthy entries.
- Mark native Looki narrative as synthesized and not independently verified.
- Avoid downloading routine raw clips.

#### Level 2 — selective multimodal verification

Trigger raw acquisition when a moment is:

- Marked as a highlight.
- Explicitly requested later.
- Associated with an unusual place or activity.
- Likely to be HFL-worthy.
- Needed to verify a questionable generated description.
- Selected for an album, retrospective, project record, or family/travel output.

Then:

1. Refresh the files response.
2. Download the clip immediately.
3. Persist the raw artifact in dumps/archive.
4. Extract representative frames with ffmpeg.
5. Run vision analysis through the existing media path.
6. Optionally extract audio and transcribe through the Plaud/Whisper path.
7. Compare raw evidence with Looki's generated narrative.
8. Build a grounded `HflEntry`.
9. Dual-write to Markdown and Elasticsearch.
10. Mark the stable item ID complete only after the durable write succeeds.

### 7.4 Express

Recommended outputs:

**Daily HFL entry**

- Meaningful moments only.
- Factual wording separated from generated interpretation.
- Location redacted or generalized according to policy.
- Stable Looki and local-artifact references.

**Read-only MCP tools**

Potential surface:

```text
looki_activity(date or range)
looki_calendar(start_date, end_date)
looki_search(query, optional range)
looki_moment(moment_id)
looki_files(moment_id)
looki_for_you(group, range)
```

These should support live/no-write inspection. Stored-memory retrieval remains
through existing HFL MCP tools.

**Daily or weekly memory digest**

- Meaningful moments.
- Movement and location patterns.
- Recurring activities or people.
- Candidate follow-ups.
- Differences between native Looki narrative and verified evidence.
- Links or stable handles for retained artifacts.

**On-demand recall examples**

- "What happened while I wore Looki last Tuesday?"
- "Find moments involving this project, place, or person."
- "Show the source frames behind this memory."
- "Compare Looki's description with what the footage actually shows."
- "Turn last month's Looki moments into an HFL retrospective."

## 8. Phased implementation

### Phase 0 — validate access and schemas

Before writing integration code:

1. Own and activate a Looki L1.
2. Log into `web.looki.tech/api-keys`.
3. Apply for developer access.
4. Generate an API key after approval.
5. Test `/me`.
6. Retrieve one date of moments.
7. Retrieve one moment detail.
8. Retrieve one files response and immediately download one approved sample.
9. Retrieve one `For You` response.
10. Save redacted response schemas and confirm pagination, timestamps, rate
    limits, location fields, and temporary-URL lifetime.
11. Review the developer-access terms supplied during approval.

This is the only unresolved prerequisite. Implementation should not be designed
against guessed payloads.

### Phase 1 — metadata MVP

Implement:

- `apps/looki` configuration, client, DTO, and adapter.
- Daily moment collection with strict caps.
- Stable pre-model deduplication.
- Read-only MCP tools.
- One daily HFL digest or selected moment entries.
- No automatic raw-media mirroring.
- Tests for no-credential, no-data, pagination, rate-limit, deduplication, and
  dual-write behavior.

Schedule on `WorkflowQueue.HFL`, staggered away from the existing Plaud and
Android HFL tasks. Approximately 23:35 is a candidate, not an approved schedule.

### Phase 2 — selective media acquisition

Add:

- Highlight-only or rule-selected download.
- Immediate materialization of expiring URLs.
- Dumps/archive retention.
- ffmpeg frame extraction.
- Optional audio extraction and Whisper transcription.
- Targeted backfill by date or moment ID.
- Configurable storage, file-count, duration, and model-cost budgets.
- Full deletion and retention handling.

### Phase 3 — higher-level memory products

Only after signal quality and privacy controls are proven:

- Weekly life-rhythm synthesis.
- Location/activity maps.
- People and relationship timelines.
- Project-context reconstruction.
- Family and travel albums.
- HFL-versus-Looki narrative comparison.
- Automatic candidate selection for time capsules or photo albums.

## 9. Idempotency and provenance requirements

The integration must be stricter than a simple ES upsert.

1. Use `looki:<moment-id>` and/or stable file IDs as the primary source identity.
2. Check completed state before the model call.
3. Check corpus references before append.
4. Use a caller-supplied deterministic ES document ID.
5. Persist a claim/done state comparable to `analyze_hfl_media` for overlapping
   workers and retries.
6. Never let a refreshed signed URL create a new logical item.
7. Mark explicit model skip as terminal only when the response schema is valid.
8. Leave decode, download, network, malformed-model, or partial-write failures
   retryable.
9. Preserve references to the stable source item and retained local artifact.
10. Distinguish Looki-generated text, direct transcript, and HARQIS inference.

## 10. Cost and volume controls

Looki's interval capture can create hundreds of short clips in a day. A naive
mirror would waste bandwidth, storage, transcription, and vision tokens.

Required bounds:

- Maximum moments per day.
- Maximum files per moment.
- Maximum total bytes and media duration per run.
- Highlight-only default for raw downloads.
- Maximum vision frames per clip.
- Maximum clips transcribed per day.
- No LLM call on missing credentials, empty windows, or already-completed items.
- Daily or source-level aggregation for routine moments.
- Separate retention policies for raw clips, extracted frames, transcripts, and
  HFL entries.

The default should retain story-level memory while allowing targeted retrieval
of raw evidence—not preserve every second indefinitely.

## 11. Alternatives considered

### 11.1 Approved developer API — recommended

Advantages:

- Looki-operated access boundary.
- Stable moment/file identifiers.
- Search, calendar, detail, files, and generated-content surfaces.
- Better legal and operational footing than mobile-app interception.

Risks:

- Approval requirement.
- Sparse public documentation.
- Endpoint and schema drift.
- Rate limits and temporary file URLs.

### 11.2 Manual app save/share or folder ingest — fallback

If the app can reliably save selected media to a local or Drive folder, HARQIS
could use scheduled polling and the existing dumps/Plaud patterns. This is
appropriate for manual highlights, but no stable automated bulk export has been
confirmed.

### 11.3 One-off privacy/account export — backfill only

A data-access request may provide historical files. If available, use the time
capsule collector. This is not suitable for continuous ingest.

### 11.4 Android/ADB extraction — diagnostics, not primary ingestion

ADB or Android automation could help inspect app behavior on a test device, but
it is brittle and unnecessary if approved API access works. Do not make mobile
filesystem scraping the production path.

### 11.5 Reverse-engineered private API — reject

Private endpoint scraping or app-traffic interception conflicts with the
service terms, is fragile, and creates avoidable account and privacy risk. It
should not be the planned HARQIS integration.

### 11.6 Webhook ingestion — unavailable today

No signed webhook surface was found. If Looki adds one, it should authenticate
and enqueue the same canonical Celery ingest task rather than write directly to
HFL.

## 12. Risks and open questions for review

### Product and API

- Will Brian's region/account receive developer access?
- Are API keys intended for durable personal automation?
- What additional developer terms appear during approval?
- What are the exact response schemas and pagination semantics?
- Is `highlight` reliable enough to control raw downloads?
- Are voice notes exposed by the documented endpoints?
- Do files include raw audio, audio-bearing video, or separate audio objects?
- Can generated comics/vlogs be downloaded as stable files?
- Is the approximately 60 requests/minute limit enforced per key, account, or
  IP?
- Is there an unpublished changes cursor or webhook roadmap?

### Grounding and quality

- How often does Looki's description disagree with source media?
- What selection rules yield a useful daily digest without routine noise?
- Is one HFL entry per day sufficient, or should explicitly highlighted moments
  receive per-item entries?
- Should native `For You` content be retained as reference material or only used
  as a ranking signal?

### Privacy

- Can precise location be disabled independently of core capture?
- What exactly is deleted after 24 hours: processing copies, source uploads,
  derived outputs, logs, and/or backups?
- How is "end-to-end encryption" implemented when third-party AI providers must
  process content?
- Can selected moments be forced to remain fully local?
- What deletion semantics does the API expose, if any?
- What bystander-consent policy should HARQIS enforce for work, family, and
  public environments?

### Operations

- What is the raw daily file volume under Brian's preferred interval mode?
- How much should be archived locally, and for how long?
- Which host owns scheduled acquisition and raw storage?
- Should Looki archive paths live under the external HARQIS data volume?
- How should a Looki account outage or API schema change be surfaced without
  breaking Celery Beat?

## 13. Recommendation

Proceed only through the approved developer surface. The device appears worth
an integration experiment if API access is granted, but the experiment should
start metadata-first and prove signal quality before HARQIS stores raw media at
scale.

Recommended decision sequence:

1. Confirm that Looki's product itself is useful to wear regularly.
2. Obtain developer approval and inspect real payloads.
3. Build a read-only MCP/client spike.
4. Run a small manual date-range ingest with no permanent raw-media mirror.
5. Review one week of candidate HFL output.
6. Only then approve scheduled ingestion and selective media retention.

The architecture should preserve Looki as the capture device, HARQIS as the
memory curator, and the HFL corpus as the durable source of truth.

## 14. Evidence confidence

**High confidence — official sources**

- Hardware specifications and capture modes.
- App availability and broad feature set.
- Privacy-policy text, service terms, and SOC 2 Type I announcement.
- Presence of Looki-operated web and API domains.
- Live API requirement for an `X-API-Key` header.

**Medium confidence — working community implementation**

- API access-application flow.
- Seven endpoint paths and parameters.
- Approximate rate limit.
- Temporary URL lifetime.
- Typical ten-second MP4 file shape and missing thumbnails.
- Search and generated-description quality limitations.

**Unconfirmed until Phase 0**

- Brian's API eligibility.
- Exact current payload schemas.
- Stable transcript or voice-note access.
- Bulk export behavior.
- Production-safe retention and download volume.

## 15. Sources

### Official Looki sources

- [Looki L1 product page](https://www.looki.ai/products/looki-l1)
- [Looki app, manual, and APK downloads](https://www.looki.ai/pages/download)
- [Looki privacy overview](https://www.looki.ai/pages/privacy)
- [Looki privacy policy](https://www.looki.ai/policies/privacy-policy)
- [Looki privacy and data-security article](https://www.looki.ai/blogs/news/ai-wearable-privacy-and-data-security-how-looki-approaches-personal-ai)
- [Looki SOC 2 Type I announcement](https://www.looki.ai/blogs/news/looki-has-completed-soc-2-type-i-audit-strengthening-trust-for-personal-ai)
- [Looki Terms of Service](https://www.looki.ai/policies/terms-of-service)
- [Looki developer API-key portal](https://web.looki.tech/api-keys)
- [Looki iOS app listing](https://apps.apple.com/us/app/looki-ai-lifelog/id6742811867)
- [Looki Android app listing](https://play.google.com/store/apps/details?id=ai.looki.lifelog)

### Community implementation evidence

- [tongshu2023/looki-claude](https://github.com/tongshu2023/looki-claude)
- [Community API QuickStart](https://github.com/tongshu2023/looki-claude/blob/main/docs/QUICKSTART.md)
- [Community API gotchas](https://github.com/tongshu2023/looki-claude/blob/main/docs/API-GOTCHAS.md)
- [Community Python client](https://github.com/tongshu2023/looki-claude/blob/main/src/looki_client.py)

### HARQIS-work references

- `docs/MANIFESTO.md`
- `docs/thesis/HFL-INGEST-CANDIDATES.md`
- `workflows/hfl/README.md`
- `workflows/hfl/dto/entry.py`
- `workflows/hfl/tasks/capture.py`
- `workflows/hfl/es_store.py`
- `workflows/hfl/mcp.py`
- `apps/plaud/references/adapter.py`
- `workflows/hfl/tasks/ingest_plaud.py`
- `workflows/hfl/tasks/analyze_media.py`
- `workflows/hfl/tasks/time_capsule.py`
- `workflows/dumps/README.md`
- `apps/google_drive/`

---

## Review status

- Research captured: yes.
- Existing HARQIS primitives inspected: yes.
- Real Looki account/API payloads validated: no.
- Integration approved: no.
- Implementation started: no.
- Scheduled task created: no.
