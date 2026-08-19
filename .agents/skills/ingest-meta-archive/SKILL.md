---
name: ingest-meta-archive
description: Safely operate the manual Facebook and Instagram archive backfill into Homework for Life. Use when preparing, reviewing, previewing, dispatching, replaying, or verifying private Meta export imports, especially when manifest integrity, Instagram media privacy, overlapping exports, or Markdown/Elasticsearch parity matter.
---

# Ingest Meta Archive

Operate this backfill only on the canonical HFL server. Keep it manual-only;
never enable its commented Beat example. Treat raw exports as immutable and do
not print private message or attachment content in logs or summaries.

## Procedure

1. Load `.env/apps.env` plus the current machine context before importing or
   running `workflows.*`. Confirm `HFL_META_WORK_DIR` and the archive roots
   resolve on the canonical server without displaying credential values.
2. Run `prepare_meta_archive_import` separately for `facebook` and `instagram`.
   Include every relevant overlapping export root so a later weekly projection
   contains the complete event set. Require schema 2, `complete=true`, and
   `truncated=false`, with `counts.parser_failures=0`. If the event cap is
   reached, inspect the exact count in `preparation-report.json`, then reprepare
   with a deliberately approved cap or `max_events=0`; a truncated run has no
   approvable manifest.
3. Review the pinned quarantine report before the manifest. Inspect the raw
   Meta timestamp and provenance of every future event; never silently adjust
   it. Retain the returned `manifest_path` and `manifest_sha256`, then review
   every count, path, metadata field, and item hash. Do not edit approved files.
4. Preview selected items with `meta_archive_preview`, passing the item path,
   its `expected_work_item_sha256`, and `work_item_root` equal to the manifest
   directory. Keep `synthesize=False` unless a bounded Haiku preview is wanted.
5. Dispatch only with both `manifest_path` and the reviewed
   `approved_manifest_sha256`. Keep `allow_cloud=False` unless media enrichment
   was explicitly approved. Even when true, Instagram conversation attachments
   must remain metadata-only; only authored Instagram media is eligible.
   Choose `synthesize=False` for local deterministic entries or
   `synthesize=True` for one bounded text-model call per dispatched item.
6. Before dispatch, run the read-only Elasticsearch reconciler and verify that
   the installed mapping resolves `entry_id` directly as `keyword`. A legacy
   `entry_id.keyword` fallback is valid only when `_mapping` declares that
   multifield.
7. Start with 25 explicit item IDs per platform, then 50, 250, and batches no
   larger than 500 while queue health is good. The run-local checkpoint skips
   completed and enqueued items on restart; set `retry_failed=True` only after
   investigating each failure.
8. Require `ok=true` from dispatch and retain the task IDs. An integrity error,
   path-boundary error, malformed item, outbox delivery, or `indexed=false`
   stops the batch investigation; do not regenerate a hash to approve an
   unexplained mutation.
9. Run `report_meta_archive_import` after each batch and preserve
   `dispatch.sqlite3` plus `final-report.json`. Require all enqueued tasks to be
   terminal and every item classified as succeeded, distilled-skip, failed, or
   still planned.
   Reservations and enqueued tasks have leases. Run
   `recover_meta_archive_import(reclaim_pending=False)` to reconcile Celery
   results and reclaim a crash before enqueue. A stale Celery `PENDING` result
   is ambiguous; confirm through Flower/worker state before deliberately using
   `reclaim_pending=True`, which marks it failed and makes it retryable.
10. Review the resulting Markdown blocks and leaf results. Confirm one stable
   entry ID per platform/thread/ISO-week and exact `Source: facebook` or
   `Source: instagram` values, canonical tag equality, and no duplicate IDs.
11. Run `scripts/agents/hfl/reconcile_elasticsearch.py` without `--apply` using
   the machine environment bootstrap. Require zero missing and zero stale
   documents. Investigate first; use `--apply` only with explicit authorization.

## Replay rules

- Re-run prepare from all relevant roots, perform a new review, and approve the
  newly returned manifest hash.
- Never reuse an old approval hash for regenerated artifacts.
- Expect an overlapping week to replace its stable Markdown entry and upsert
  the same ES document, not create a second entry.
- Keep media-cache directories with their work items to avoid repeated cloud
  calls for already-enriched content hashes.
