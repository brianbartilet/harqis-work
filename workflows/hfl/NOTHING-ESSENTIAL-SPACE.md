# Essential Space ingestion scaffold

The working acquisition backend reads operator-exported UTF-8 Markdown files.
Nothing's upstream MCP backend is **not implemented**: its endpoint, authentication,
pagination, transcript/media access, and background access still need verification.
Setting `NOTHING_ESSENTIAL_SPACE_BACKEND=mcp` returns an explicit unavailable result;
it never guesses an endpoint or falls back to unrelated data.

Official research:
- [Read-only MCP announcement](https://nothing.community/d/61730-nothing-os-50-new-features-explained)
- [Markdown and audio export announcement](https://nothing.community/d/39251-essential-space-is-growing-up)

## Setup

1. Share/save selected Essential Space captures as Markdown into a retained,
   flat inbox on the HFL worker. Finish syncing files before ingestion.
2. Set `NOTHING_ESSENTIAL_SPACE_EXPORT_DIR` to that directory in the worker's
   private environment. `NOTHING_ESSENTIAL_SPACE_BACKEND=export` is the default.
   No Nothing credentials are needed for exported files.
3. Preview using HARQIS MCP `nothing_essential_space_activity(period="last-week")`.
   This tool reads local exports; it is not Nothing's upstream MCP server.
4. Invoke `ingest_nothing_essential_space_activity(synthesize=False)` manually.
   Explicit `since="YYYY-MM-DD", until="YYYY-MM-DD"` supports backfills. The default
   window is seven calendar days inclusive, using capture-local dates where supplied.
5. Optional `synthesize=True` enables configured Anthropic Haiku
   `claude-haiku-4-5-20251001`. Invalid responses/API failures fall back to labelled
   export text. No model call occurs for empty or already receipted captures.
6. After checking delivery, uncomment the disabled 23:25 schedule in
   `tasks_config.py` and regenerate the frontend registry. Use one inbox owner on
   the `hfl` queue. No schedule or live ingestion is activated by this branch.

## Optional metadata sidecar (our schema)

For `meeting.md`, create `meeting.metadata.json`:

```json
{
  "capture_id": "optional-original-id",
  "captured_at": "2026-10-20T09:30:00+08:00",
  "title": "Planning meeting",
  "attachments": ["meeting.m4a", "whiteboard.png"]
}
```

This is a HARQIS convention, not a claimed Nothing export format. Sidecars are
optional. Without `captured_at`, the entry uses and explicitly labels export file
mtime; it does not claim to know the original capture time. An invalid sidecar
causes a surfaced per-file error instead of silently substituting a timestamp.
Attachment paths must exist inside the inbox, including after resolving symlinks.
No audio, images, PDFs, or Markdown links are opened by the distiller. Attachments
are references only; audio transcription/OCR and separate transcript extraction
are follow-up work. The complete original export stays in the inbox.

## Persistence and limits

- Source: `nothing-essential-space`; default HFL index: `harqis-hfl-entries`.
- Every capture revision submits once through `submit_hfl_entry`, which owns
  Markdown, Elasticsearch projection, canonical-host forwarding, and the outbox.
- `entries_submitted` counts durable acknowledgements; `entries_written` counts
  confirmed nonduplicate local persistence only. Inspect `outcomes[].delivery` for
  `persisted`, `forwarded`, or `outbox`; forwarding is not confirmed indexing.
- Receipts live beside the HFL outbox in `nothing-essential-space/*.done`, behind
  a local file lock. Receipted captures are excluded before the per-run model cap.
  Outbox delivery is retried by the existing HFL outbox flusher. Failed submissions
  without an acknowledgement remain eligible; model-declared skips are receipted.
- Identity is SHA-256 of exact Markdown bytes plus canonical sidecar JSON.
  Filename changes alone do not duplicate an export. Edits create separate revision
  entries, not destructive replacements. Distinct identical files without unique
  metadata collapse; future export/MCP identity reconciliation is not implemented.
- Receipts and persistence identity are host-scoped: use one execution owner.
  Removing receipts can repeat model calls, but the same host/source dedup key
  still protects persistence. Keep the inbox and runtime state backed up.
- Default caps: 25 new captures, 5,000 directory entries scanned, 1 MB per Markdown
  file, 64 KB per sidecar, 20 attachment references. Model/raw entry text is capped
  at 24,000 characters; MCP preview text at 4,000 per capture. Original files remain
  intact. `truncated=true` signals more work; increase `max_scan` or partition the
  inbox when the scan limit hides later files. Rerunning drains capture-cap overflow.
- Keep the originals at their referenced paths. No automatic archive, file move,
  deletion, action execution, or meeting scheduling is performed.

## Automation runtime decision

Classification: **celery** (high confidence). Fixed bounded collection, optional
schema-constrained synthesis, and durable submission fit Celery. The HFL worker
owns collection/distillation/submission; canonical persistence owns delivery;
Celery Beat is the sole future schedule owner (currently manual/disabled).
No adaptive agent is required. Controls are bounded local reads, stable revision
dedup keys, locked atomic receipts, existing outbox retries, and content-free
error reporting. Review evidence is the task result, ES log, and HFL entry with
source references. Nothing MCP authentication/schema remains an open question
only for that unimplemented acquisition backend.

Scaffold skill provenance: `create-new-ingest-source-hfl`, SHA-256
`7030261a9c7d7d12cfa7aab8da82230af594719d9634e0bff9a9959bdb4c097d`.
The persistence receipt carries the canonical entry ID and forwarding task ID
when applicable, linking the local acknowledgement to downstream review evidence.

## Verification

Use the repository virtual environment and machine environment bootstrap before
imports/tests. Offline tests mock models and persistence; the live test is skipped.

```text
python -m pytest -o addopts= workflows/hfl/tests/test_ingest_nothing_essential_space.py -q
python -m py_compile workflows/hfl/tasks/ingest_nothing_essential_space.py workflows/hfl/mcp.py workflows/hfl/tasks_config.py workflows/hfl/__init__.py
```

After environment bootstrap, importing `workflows.hfl` must register
`workflows.hfl.tasks.ingest_nothing_essential_space.ingest_nothing_essential_space_activity`
in `SPROUT.tasks`.
