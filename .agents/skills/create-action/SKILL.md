---
name: create-action
description: Create a standalone or HFL entry-linked Activity Corpus action with optional dates, Markdown instructions, web links, notes, and multiple supporting files. Use when the user asks to save an action or invokes $create-action; this records intent without scheduling agent execution.
---

# Create an Activity Corpus action

Use the existing `hfl_corpus` tool adapter through the repository CLI or MCP.
The user's request to create the action authorizes saving it. A request for a
preview or draft does not authorize persistence.

## Prepare

- Supply `title` (up to 200 characters) and `expected_outcome` (up to 3,000).
  Infer a concise, faithful outcome from the user's task when clear; ask only
  if the intended result is missing or ambiguous.
- Optional fields: `review_date`, `due_date` (`YYYY-MM-DD` or empty), `prompt`
  (Markdown, up to 20,000 characters), `notes` (up to 6,000). Omit unspecified
  dates rather than inventing deadlines. Resolve relative dates in the user's
  timezone and state the resulting calendar date in the response.
- Standalone actions omit `source`. To link an entry, supply
  `source: {"path": "2026/Sep/2026-09-14.md", "entry_id": "hfl-..."}` using
  an actual corpus-relative document path and stable entry ID. An HTML anchor
  is not an entry ID. Use corpus search/read tools if the reference needs
  resolving; the API rejects unavailable or protected evidence.
- Generate one UUID `request_id` for this logical creation and preserve it
  with the prepared payload until the result is known. Reuse the identical
  ID and payload on a transport retry; a new ID can create a duplicate.

## Save and verify

Prefer the repository virtualenv and CLI when shell access is available:

```text
python -m tools schema hfl_corpus create_hfl_corpus_action
python -m tools call hfl_corpus create_hfl_corpus_action --input - --confirm-write
```

Use `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` on macOS/Linux.
Pass the prepared JSON through stdin using safe shell quoting. The CLI loads
the host environment itself. Do not print or copy bearer tokens. With MCP,
call `create_hfl_corpus_action` with the same fields.

The service calls `POST /api/hfl/actions`. A fresh action returns 201; a replay
returns 200 with `duplicate: true`. Inspect `item.id`, `item.version`, and
`item.agent_enabled` (false). If needed, verify with `get_hfl_corpus_action`.
Report the action title, ID, and any saved review/due dates. Say that it was
saved with scheduled agent execution disabled; saving a prompt does not run it.

When supporting files are supplied, create the action first, then call
`upload_hfl_corpus_attachments` with `resource: "actions"`, the saved ID as
`source_id`, and the user's local `file_paths`. Up to 10 attachments, 50 MB each,
200 MB total are supported. Check the returned manifest before reporting that
all files were attached. If upload fails, preserve the saved action ID and retry
the upload rather than creating another action. Identical filenames/content are
deduplicated. Agents receive verified local copies on their executing host;
removal excludes a file from future runs and preserves prior run evidence.

Preserve relevant user-provided web URLs in the prompt or notes. At execution,
agents try configured authenticated integrations and then available signed-in
browser sessions, within their execution mode. Do not claim remote workers have
access to the user's local browser or that an inaccessible link was read.

Retry a transient transport failure once with the same payload and ID. On a
second failure, report that persistence is unconfirmed and retain the ID for
reconciliation. For 409, inspect the conflict instead of changing the ID.
For validation or missing/protected evidence errors, correct the input from
available facts or ask for the missing information; do not silently drop the
requested link or switch to another document.

For a requested later edit, read the latest action and pass its `version` to
`update_hfl_corpus_action`. Set `changes.status` to `done` or `dismissed` only
when requested. On 409, reread before applying the requested edit. Completion
retains the existing HFL completion-receipt behavior.

The maintained REST contract and service details are in
[apps/hfl_corpus/README.md](../../../apps/hfl_corpus/README.md) and
[openapi.yaml](../../../apps/hfl_corpus/openapi.yaml). Runtime Swagger is at
`/docs` on the standalone HFL API host; obtain the configured host from the
repository environment rather than inventing one.
