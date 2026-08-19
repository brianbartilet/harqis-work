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

The planner and leaf writer are intentionally separate. Preparing an import is safe to repeat and writes only derived work files. Preparation returns a SHA-256 pin for `plan.json`, and the manifest pins every work item. Dispatch requires the reviewed manifest pin, checks every work-item pin and path boundary before enqueueing anything, and passes each pin to the leaf for a second check at consumption time. Each leaf owns one platform/thread/week and calls the durable persistence boundary at most once.

## Canonical event

Each normalized record keeps platform, platform-specific thread id/title, participants, sender, UTC timestamp, `Asia/Singapore` timestamp, event type, content, attachments, stable event id, and provenance references. Facebook and Instagram identities are not merged.

## Deduplication

Event identity is derived from platform, thread, sender, UTC timestamp, normalized content, event type, and attachment identities. Media identity is SHA-256 when the file is present. Repeated export roots, repeated message pages, and later overlapping exports therefore converge on the same canonical records. Raw duplicates are never deleted.

## Weekly projection

Weeks are ISO Monday–Sunday in `Asia/Singapore`. Only active thread-weeks generate work. Authored posts/stories use a platform-local `authored-content` pseudo-thread. Each projection uses ISO Monday midnight as its stable HFL timestamp. On an overlapping rerun, the stable platform/thread/week entry ID replaces its prior Markdown block atomically; Elasticsearch indexes that same winning entry under its stable document ID. This preserves conversational grouping, bounds each model request, and prevents Markdown/Elasticsearch narrative splits.

## Media enrichment and privacy

Cloud media enrichment is opt-in and dispatch defaults to `allow_cloud=False`. When enabled, Facebook private-message attachments from any participant are in scope. Images, stickers, GIFs, and sampled video frames may be described by Claude Haiku. Audio and video speech may be transcribed by OpenAI Whisper. Instagram conversation attachments are filtered before either cloud client is initialized and remain metadata-only even when `allow_cloud=True`; authored Instagram media is eligible.

Raw attachments remain immutable and are not embedded in the corpus. Only bounded derived text and stable provenance references enter a weekly narrative. Content hashes prevent repeated model charges for duplicate media. Missing or unsupported artifacts degrade to metadata-only records.

## References

Corpus entries render a `References:` list and Elasticsearch stores the same values. Stable references use `meta-archive://<platform>/<export>/<relative-path>` rather than machine-specific `G:` or `/Volumes/...` paths. A future resolver can map this scheme to the current archive root after data is moved.

## Operational sequence

1. Sync the immutable export directories to a harqis-server inbox (future work).
2. Run `prepare_meta_archive_import` separately for Facebook and Instagram.
3. Record the returned `manifest_sha256`; inspect that exact `plan.json`, its counts, and its per-item SHA-256 pins.
4. Optionally preview pinned work items through `meta_archive_preview`.
5. Run `dispatch_meta_archive_import` with `approved_manifest_sha256` from the completed review.
6. Review task results, HFL Markdown, Elasticsearch documents, and durable outbox status.
7. Run the read-only Markdown/Elasticsearch reconciliation and require no missing or stale documents.
8. Re-run safely when a later Meta export overlaps the earlier period, supplying all relevant export roots so the replacement narrative remains complete.

## Boundaries and future work

This feature does not sync files, mutate raw downloads, merge identities across platforms, activate a Beat schedule, or run the private import on a developer workstation. A later generic workflow may implement inbox synchronization and invoke the already idempotent HFL planner on the server. Period-level time capsules should consume normalized timestamps or the resulting HFL entries, not raw export mtimes.
