# Thesis: Meta archives as a durable HFL source

## Claim

Downloaded Facebook and Instagram archives should be treated as immutable evidence, not as an HFL corpus themselves. A source-aware normalization layer can recover their original chronology, deduplicate overlapping downloads, group activity by platform-specific conversation, enrich media with bounded transcription/captioning, and project useful weekly moments into Homework for Life without overwhelming the timeline.

## Evidence from the August 2026 exports

The Instagram download is HTML and split across five export directories. All five expose the same 218 conversation directory names, while the actual files are distributed across parts. The inspected data includes exact duplicate files. Instagram post and story timestamps span 2020–2026.

The Facebook download is mostly JSON and split across 43 directories. Its principal part exposes 1,286 inbox and 20 archived threads; the additional message-bearing parts contain overlapping subsets. Facebook message records have participant, sender, millisecond timestamp, content, share, sticker, and media fields.

Filesystem modification time reflects the August 2026 download, not the historical event. The generic time-capsule collector therefore cannot be the primary parser because its archive window is mtime-based.

## Architecture

```text
immutable Meta exports
  -> source discovery
  -> Facebook JSON / Instagram HTML parsing
  -> canonical MetaEvent records
  -> event and media hashing
  -> ISO thread-week work items
  -> optional attachment caption/transcription
  -> source-specific HflEntry
  -> submit_hfl_entry
  -> Markdown Activity Corpus + Elasticsearch
```

The planner and leaf writer are intentionally separate. Schema-v2 preparation streams parser batches into a per-run SQLite staging database, so exact counts and overlap deduplication do not require the whole archive in memory. A positive `max_events` is fail-closed: reaching the ceiling finishes the exact count and writes a non-approvable preparation report, but no `plan.json`. A complete preparation returns a SHA-256 pin for `plan.json`, its quarantine report, and every work item. Dispatch validates all artifacts before enqueueing anything and each leaf validates its pin again at consumption time.

## Canonical event

Each normalized record keeps platform, platform-specific thread id/title, participants, sender, raw Meta timestamp, UTC timestamp, `Asia/Singapore` timestamp, event type, content, attachments, stable event id, and provenance references. Records more than 24 hours beyond preparation time are excluded from work items and written to the pinned quarantine report without narrative content. Facebook and Instagram identities are not merged.

## Deduplication

Event identity is derived from platform, thread, sender, UTC timestamp, normalized content, event type, and attachment identities. Media identity is SHA-256 when the file is present. Repeated export roots, repeated message pages, and later overlapping exports therefore converge on the same canonical records. Raw duplicates are never deleted.

## Weekly projection

Weeks are ISO Monday–Sunday in `Asia/Singapore`. Only active thread-weeks generate work. Authored posts/stories use a platform-local `authored-content` pseudo-thread. Each projection uses ISO Monday midnight as its stable HFL timestamp. On an overlapping rerun, the stable platform/thread/week entry ID replaces its prior Markdown block atomically; Elasticsearch indexes that same winning entry under its stable document ID. This preserves conversational grouping, bounds each model request, and prevents Markdown/Elasticsearch narrative splits.

## Media enrichment and privacy

Cloud media enrichment is opt-in and dispatch defaults to `allow_cloud=False`. When enabled, Facebook private-message attachments from any participant are in scope. Images, stickers, GIFs, and sampled video frames may be described by Claude Haiku. Audio and video speech may be transcribed by OpenAI Whisper. Instagram conversation attachments are filtered before either cloud client is initialized and remain metadata-only even when `allow_cloud=True`; authored Instagram media is eligible.

Text synthesis is a separate opt-in. `synthesize=False` produces deterministic local entries and makes no text-model call. `synthesize=True` permits one bounded synthesis call per dispatched work item. Canonical tags are lower-case, deduplicated Markdown-safe slugs in deterministic order, and Elasticsearch receives the same normalized `HflEntry` that is rendered to Markdown.

## Resumption and audit

Each approved run owns `dispatch.sqlite3`, pinned to the manifest hash and the `allow_cloud`/`synthesize` policy. Items move through planned, dispatching, enqueued, succeeded, distilled-skip, or failed states. Restarts select only undispatched items; explicit item IDs and deliberate failed-item retries are supported. `report_meta_archive_import` writes `final-report.json` with planned, enqueued, succeeded, distilled-skip, failed, remaining, and already-completed totals. The generic reconciler resolves live projections by canonical `entry_id`, while preserving stable `meta-facebook-*` and `meta-instagram-*` Elasticsearch IDs.

Raw attachments remain immutable and are not embedded in the corpus. Only bounded derived text and stable provenance references enter a weekly narrative. Content hashes prevent repeated model charges for duplicate media. Missing or unsupported artifacts degrade to metadata-only records.

## References

Corpus entries render a `References:` list and Elasticsearch stores the same values. Stable references use `meta-archive://<platform>/<export>/<relative-path>` rather than machine-specific `G:` or `/Volumes/...` paths. A future resolver can map this scheme to the current archive root after data is moved.

## Operational sequence

1. Sync the immutable export directories to a harqis-server inbox (future work).
2. Run `prepare_meta_archive_import` separately for Facebook and Instagram.
3. Require a complete, untruncated schema-v2 result; review the quarantine report and inspect raw timestamp values for every quarantined record.
4. Record the new `manifest_sha256`; inspect that exact `plan.json`, counts, paths, metadata, and per-item SHA-256 pins. Calculate synthesis calls as the number of items that will be dispatched with `synthesize=true`.
5. Optionally preview pinned work items through `meta_archive_preview`.
6. Dispatch a 25-item canary per platform with `allow_cloud=false` and an explicit synthesis policy. Continue with 50, 250, then at most 500 items per controlled batch when queue health and parity remain clean.
7. Run `report_meta_archive_import` after each batch. Retry only investigated failures and retain `dispatch.sqlite3`, the manifest, hashes, and reports.
8. Require terminal tasks, zero unexplained failures, canonical tag parity, no duplicate IDs, and matching Markdown/Elasticsearch projections before continuing.
9. Re-run safely when a later Meta export overlaps the earlier period, supplying all relevant export roots and approving the newly generated manifest hash.

## Boundaries and future work

This feature does not sync files, mutate raw downloads, merge identities across platforms, activate a Beat schedule, or run the private import on a developer workstation. Broader corpus missing/stale projection cleanup remains a separate reconciliation operation. A later generic workflow may implement inbox synchronization and invoke the already idempotent HFL planner on the server. Period-level time capsules should consume normalized timestamps or the resulting HFL entries, not raw export mtimes.
