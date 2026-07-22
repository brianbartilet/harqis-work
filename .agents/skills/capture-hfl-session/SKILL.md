---
name: capture-hfl-session
description: Capture one user prompt and its visible assistant outcome as a sanitized, deduplicated Homework-for-Life audit event. Use when a Codex, Claude Code, Hermes, or OpenClaw surface lacks an automatic lifecycle hook, when automatic capture failed, or when the user explicitly asks to archive or capture the current session or prompt in HFL.
---

# Capture HFL Session

Capture the pair only after the requested work has reached a user-visible
outcome. The platform retains a sanitized local audit artifact, then dual-writes
one entry to the HFL Markdown corpus and Elasticsearch.

## Procedure

1. Determine the surface: `codex`, `claude-code`, `hermes`, or `openclaw`.
2. Prepare the common envelope below. Include the original user prompt and a
   concise, factual summary of the response and actions actually completed.
   Keep the HFL `Moment` as a brief task phrase (120 characters maximum). Render
   `What happened` with `### Request` and `### Outcome` headings. Preserve useful
   Markdown such as bullets, tables, links, emphasis, and fenced code, but never
   emit H1 or H2 inside this field; demote nested headings to H4 so they cannot
   collide with HFL entry navigation. For
   long outcomes, keep a bounded, line-safe summary (about 900 characters): the
   conclusion, key totals, and ranked findings. Never truncate raw outcome text
   mid-line; the complete sanitized outcome remains in the audit artifact.
3. Never include hidden reasoning, environment contents, credentials, or full
   tool output. The capture script applies a second redaction pass.
4. Run the repository script with `--json -`; use its virtual-environment
   Python when present. It attempts immediate HFL enqueue and retains a local
   event if delivery is unavailable.
5. Report the event ID and whether a task ID was issued. Do not create a second
   event when an automatic hook already captured the same turn.

```json
{
  "schema_version": 1,
  "surface": "hermes",
  "session_id": "stable-session-id",
  "prompt_id": "stable-turn-id",
  "timestamp": "2026-07-22T12:53:00+08:00",
  "original_prompt": "the user's prompt",
  "assistant_outcome": "what was actually done and the result",
  "result_status": "completed",
  "artifacts": [
    {"kind": "file", "value": "/path/to/changed-file"},
    {"kind": "pr", "value": "https://github.com/org/repo/pull/123"}
  ]
}
```

PowerShell:

```powershell
$envelope | ConvertTo-Json -Depth 5 | .venv\Scripts\python.exe scripts\agents\hfl\capture_session_event.py --surface hermes --json -
```

macOS/Linux:

```bash
printf '%s' "$HFL_CAPTURE_ENVELOPE" | .venv/bin/python scripts/agents/hfl/capture_session_event.py --surface openclaw --json -
```

## Historical Hermes migration

For a historical backfill from Hermes, use the repository migration adapter
instead of manually replaying envelopes:

1. Read `~/.hermes/state.db` in SQLite read-only mode.
2. Include only closed `cli` and `telegram` sessions by default. Exclude cron,
   subagents, tool messages, compacted/inactive messages, open sessions, and
   reasoning fields. Treat active compaction handoffs, system reminders,
   delegation-completion notices, task-list notices, and iteration-limit notices
   as internal context: merge their useful visible result into the nearest real
   user turn, or discard them when orphaned. Discard explicit low-value control
   turns such as `stop` and confirmation-only replies such as `yes`, `approve`,
   `yes approve`, `proceed`, or `go ahead` rather than creating standalone HFL
   entries. A longer reply that adds requirements remains a real prompt.
3. Run `scripts/agents/hfl/migrate_hermes_sessions.py --dry-run` first and
   record the eligible count.
4. Migrate a small deterministic canary with `--start` and `--limit`, then
   replay it once. Every replay must report duplicate Markdown writes with zero
   bytes while safely upserting the same Elasticsearch document IDs.
5. Backfill the remaining range in bounded batches. `--no-synthesize` is the
   cost-safe historical default; live hook events may still use Haiku
   distillation.
6. Keep commit hashes and similar provenance in the JSON audit artifact, but do
   not emit bare hashes as HFL `References`. HFL references must be navigable
   URLs or file/path artifacts; the audit artifact itself remains the canonical
   reference.
7. Verify canonical JSON artifact count, `#prompt-audit` Markdown count, and
   Elasticsearch `source.keyword=agent-session` count agree. Also verify Corpus
   Index previews never expose Markdown headings such as `### Request`, never
   render blank `Moment`/`What happened` values, and preserve an incoming entry
   hash when tag navigation initializes.

On macOS/external volumes, ignore AppleDouble `._*.json` companions and any
non-UTF-8/malformed audit artifacts during event collection. Do not delete
companions without explicit approval.

## Status values

Use `completed`, `partial`, `blocked`, `failed`, or `unknown`. Do not claim
completion merely because a response was produced.
