---
name: activity-radar
description: Analyze recent Homework-for-Life corpus entries against relevant historical activity to surface missed commitments, current focus, risks, contradictions, recommendations, and evidence. Use when the user invokes $activity-radar, asks for an HFL activity watchdog/retrospective, wants radar feedback recorded, or wants a radar report saved to HFL.
allowed-tools: Bash Read
---

# Activity Radar

Run the checked-in helper to produce an evidence-grounded Markdown review of recent HFL activity. The workflow includes protected HFL entries when the locally authorized corpus/query layer exposes them, but must never print credentials, tokens, or configuration secrets.

## Run

From the repository root, use the repository virtual environment when available:

```powershell
$python = if (Test-Path .venv/Scripts/python.exe) { '.venv/Scripts/python.exe' } else { 'python' }
& $python .agents/skills/activity-radar/scripts/activity_radar.py run
```

Defaults are the last 8 hours against relevant entries from the last 90 days. Translate user wording into flags:

- `--recent-hours 4`
- `--retrospective-days 180`
- `--query "project alpha"`
- repeat `--tag project-alpha`
- `--source git`
- `--context "The release moved to Friday"`
- `--model ...` only when the user requests a model override
- `--save-to-hfl` only when the user explicitly asks to save the report; writeback uses source `activity-radar` and tags `#fyi #retrospective #activity-radar`
- `--dry-run` retrieves and analyzes without notification, marker updates, feedback mutation, or HFL writeback

The interactive command never sends Telegram notifications. Return its Markdown output directly. When no material insight exists, return `No new material findings.` Mention `Partial report` degradation notices without overstating completeness.

When a finding depends on a referenced local or HFL-hosted text/media artifact, inspect only the relevant artifact with the available file/OCR/visual tools and rerun with the derived facts in `--context`. Open an ordinary web reference only when needed to verify a specific claim. Do not authenticate, download implicitly, or take actions on referenced sites.

## Feedback

Finding headings expose stable fingerprints in the JSON result. Record explicit feedback with:

```powershell
& $python .agents/skills/activity-radar/scripts/activity_radar.py feedback <fingerprint> useful
& $python .agents/skills/activity-radar/scripts/activity_radar.py feedback <fingerprint> dismissed
& $python .agents/skills/activity-radar/scripts/activity_radar.py feedback <fingerprint> resolved
```

Do not infer dismissed or resolved feedback status without an explicit user instruction. Resolved/dismissed findings stay suppressed until materially different evidence appears; critical open findings can repeat only when current recent evidence directly supports the condition.

## Scheduled behavior

Hermes owns the waking-hours schedule at 08:00, 10:00, 12:00, 14:00, 16:00, 18:00, 20:00, and 22:00 Asia/Singapore. It dispatches the canonical `workflows.hfl.tasks.activity_radar.activity_radar` Celery task to the `hfl` queue; the corresponding Beat entry remains disabled to prevent duplicate runs. The task reads from the last successful marker, capped at 48 hours; the first run uses 48 hours. Before a risk or missed commitment can be critical/high, the analysis must compare timestamps, classify the newest relevant evidence as `open`, cite recent evidence that directly supports the current condition, and record a resolution check. Resolved or uncertain findings cannot reach Telegram. It sends Telegram only for new or changed high findings plus every unresolved critical finding, using a compact numbered plain-text summary with `WHAT`, `WHY`, `NEXT`, and human-readable `SOURCE` labels. Internal evidence IDs such as `H46` are expanded into dated source summaries, and bounded fields end at sentence or word boundaries instead of dangling ellipses. At most four findings are shown; the linked HFL entry retains the complete critical/high summary. Medium/low findings remain in analysis and state tracking but are not sent. Before Telegram delivery, the complete summary is submitted as an `activity-radar` HFL entry with a scheduled-window deduplication key, and the message appends a `CORPUS` link to the inserted daily document. An undelivered writeback blocks notification and marker advance. The marker advances only after complete analysis, accepted HFL writeback, and successful notification, or after a successful silent no-findings pass.
