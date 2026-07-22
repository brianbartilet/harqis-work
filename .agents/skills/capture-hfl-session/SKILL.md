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

## Status values

Use `completed`, `partial`, `blocked`, `failed`, or `unknown`. Do not claim
completion merely because a response was produced.
