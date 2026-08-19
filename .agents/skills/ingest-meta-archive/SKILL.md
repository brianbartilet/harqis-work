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
   contains the complete event set.
3. Retain the returned `manifest_path` and `manifest_sha256`. Review the exact
   `plan.json`: platform, export roots, unique event count, work-item count,
   thread/week metadata, event counts, and every item `sha256`. Do not edit the
   manifest or work items after review.
4. Preview selected items with `meta_archive_preview`, passing the item path,
   its `expected_work_item_sha256`, and `work_item_root` equal to the manifest
   directory. Keep `synthesize=False` unless a bounded Haiku preview is wanted.
5. Dispatch only with both `manifest_path` and the reviewed
   `approved_manifest_sha256`. Keep `allow_cloud=False` unless media enrichment
   was explicitly approved. Even when true, Instagram conversation attachments
   must remain metadata-only; only authored Instagram media is eligible.
6. Require `ok=true` from dispatch and retain the task IDs. An integrity error,
   path-boundary error, malformed item, outbox delivery, or `indexed=false`
   stops the batch investigation; do not regenerate a hash to approve an
   unexplained mutation.
7. Review the resulting Markdown blocks and leaf results. Confirm one stable
   entry ID per platform/thread/ISO-week and exact `Source: facebook` or
   `Source: instagram` values.
8. Run `scripts/agents/hfl/reconcile_elasticsearch.py` without `--apply` using
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
