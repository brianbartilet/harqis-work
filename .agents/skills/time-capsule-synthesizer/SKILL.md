---
name: time-capsule-synthesizer
description: >
  Turn a pile of files into one Homework-for-Life **time-capsule** entry for a period.
user-invocable: true
allowed-tools: Bash Read Glob Grep Edit Write
---

Turn a pile of files into one Homework-for-Life **time-capsule** entry for a period.
Given a directory and a flexible date period, this skill sweeps the tree by file date,
ingests every file's content/context, and synthesizes a single rollup `HflEntry` (the
notable events, actions, reminders, and artifacts) — dual-written to the Markdown corpus
and the `harqis-hfl-entries` Elasticsearch index, with the source files as `references`.

This is the **retrospective** arm of Homework for Life (`docs/MANIFESTO.md` §2). It serves
the three things the corpus is for: it **curates** the events/timeline of a past period by
looking *back* over it; it makes the corpus a **retrieval index** for that period's files
and artifacts (recorded as `references`); and it **enriches** the rollup with what was
already captured for the same window — prior HFL entries (the ES index) and live `apps/`
integration signal (Step 1.5).

The heavy lifting (walking the tree, reading text, captioning images/video with Haiku,
extracting document text) is done by `workflows/hfl/tasks/time_capsule.py`; **you**
(the active agent) do the synthesis from its compact digest. This keeps it scalable to the big
"start-date → today" backfill while keeping the synthesis high-quality.

## Arguments

`$ARGUMENTS` (parse left to right; the period is the only required token):

```
<period> [--root <dir>] [--max-files N] [--no-caption] [--dry-run]
```

| Token | Required | Description |
|---|---|---|
| `<period>` | Yes | A date or span. Flexible: `May 2020`, `August 1, 2002`, `June-July 2019`, `2019-06-01..2019-07-31`, `since 2020-01-01`, `2020-01-01 to today`, `last 90 days`. Quote multi-word periods. |
| `--root <dir>` | No | Directory to sweep. Default `/Volumes/harqis-data` (the harqis-server data root, per `machines.local.toml`). The dumps **inbox** (`machines.local.toml [dumps].harqis_server_inbox`, default `/Users/harqis-one/dumps`) is the other natural root — every machine's daily dumps land there. Must be reachable on the host you run this on. |
| `--max-files N` | No | Cap on files analyzed (most-recent-first). Default `500`. |
| `--no-caption` | No | Skip Haiku vision captions for images/video (faster, free; images become metadata-only). |
| `--no-enrich` | No | Skip Step 1.5 — synthesize from the file digest alone, without cross-referencing already-captured HFL entries or `apps/` integration signal. |
| `--dry-run` | No | Run COLLECT (+ ENRICH) only — produce the manifest + digest + enrichment, do NOT write an HFL entry. |

Pick the repo venv Python for every command below:
`.venv/Scripts/python.exe` on Windows, `.venv/bin/python` on macOS/Linux. (Referred to as `PY` here.)

---

## Step 0 — Read the module before running anything

Read `workflows/hfl/tasks/time_capsule.py` so you know the exact signatures of
`run_collect` / `run_write`, the manifest shape, and the synthesis-JSON keys. Do not
guess them.

---

## Step 1 — COLLECT (sweep + extract → digest)

Resolve `--root` (default `/Volumes/harqis-data`) and the period, then run:

```bash
PY -c "import sys,json; sys.path.insert(0,'scripts'); import launch; launch.setup_env(); from workflows.hfl.tasks.time_capsule import run_collect; print('JSON_RESULT='+json.dumps(run_collect(root=sys.argv[1], period=sys.argv[2], max_files=int(sys.argv[3]), do_caption=(sys.argv[4]=='1'))))" "<ROOT>" "<PERIOD>" "500" "1"
```

(Pass `0` as the last arg for `--no-caption`. `<ROOT>`/`<PERIOD>` are separate quoted
argv — never interpolate them into the code string.)

The command prints the **digest** (your synthesis input), the artifact paths, and a final
`JSON_RESULT={...}` summary line with `slug`, `window`, `counts`, `suggested_when_iso`,
`manifest_path`, `digest_path`.

Handle the result:
- **`ok: false, reason: "root-unreachable"`** → the directory isn't mounted on this host.
  The default `/Volumes/harqis-data` only exists on **harqis-server** (the Mac mini).
  Tell the user to run the skill on that host, or pass a `--root` reachable here. (Advanced
  alternative: dispatch — see "Running against a remote directory" below.)
- **`ok: true` but `counts.total_in_window == 0`** → no files in that period. Report the
  empty window and stop. Do NOT write an entry, do NOT call the model.
- Otherwise read the digest from the command output (or open `digest_path` with Read if
  it's long). It has per-day counts, per-kind totals, and one line per file
  (`[kind] mtime path — snippet/caption/note`).

(If `--dry-run`, still run Step 1.5 next, then report the digest + enrichment + artifact
paths and stop — do NOT write an entry.)

---

## Step 1.5 — ENRICH (cross-reference what's already captured)

Skip if `--no-enrich`. Otherwise, before synthesizing, pull the signal the corpus
*already* holds for the same window so the rollup builds on it rather than ignoring or
duplicating it. Use the date parts (`YYYY-MM-DD`) of `JSON_RESULT.window.start` /
`.window.end` from Step 1 (the end is exclusive — fine for these bounded queries).

**(a) Existing HFL entries (Elasticsearch).** Query the `harqis-hfl-entries` index for
entries already captured in this window by the daily ingest sources (chatgpt, git,
browsing, dumps) or a prior capsule:

```bash
PY -c "import sys,json; sys.path.insert(0,'scripts'); import launch; launch.setup_env(); from workflows.hfl.es_store import query_hfl_entries; print('JSON_RESULT='+json.dumps(query_hfl_entries(since=sys.argv[1], until=sys.argv[2], limit=50), default=str))" "<START>" "<END>"
```

**(b) App-integration signal.** Pull live context from an `apps/` integration for the
same dates. GitHub commits are the canonical example and work for any historical window:

```bash
PY -c "import sys,json; sys.path.insert(0,'scripts'); import launch; launch.setup_env(); from datetime import date; from workflows.hfl.tasks.ingest_git import collect_github_activity; print('JSON_RESULT='+json.dumps(collect_github_activity(since=date.fromisoformat(sys.argv[1]), until=date.fromisoformat(sys.argv[2])), default=str))" "<START>" "<END>"
```

This call is **best-effort**: if it errors (no GitHub token, offline) or returns
`commit_count: 0`, note that and proceed without it. The same pattern fits any `apps/`
integration that has a windowed collector — the read-only MCP live-view tools in
`workflows/hfl/mcp.py` mirror these (`memory_recall_es`, `git_activity`,
`browsing_activity`). `browsing_activity` only helps for *recent* windows (browser
history doesn't reach back years) — skip it for old backfills.

Carry the results into Step 2 as **cross-reference context** — not new files to ingest,
and never something to fabricate from.

---

## Step 2 — SYNTHESIZE (you compose the rollup)

From the digest, write ONE period rollup. Be concrete and grounded — name the actual
projects, places, people, documents, errors, milestones the files reveal. Do not invent
anything not supported by a file.

If Step 1.5 returned anything, fold it in: let **existing HFL entries** anchor the
narrative (synthesize a higher-level rollup that *references* them — don't restate them
verbatim), and let **app-integration signal** (commits, etc.) corroborate the files or
fill gaps they don't show. Enrichment is grounding, not licence to invent: a claim
sourced from git/ES must trace to that result just as a file claim traces to the digest.

Fields:

- **moment** — a one-line headline for the period (≤120 chars, present tense).
- **what_happened** — 3–8 sentences: the notable **events, actions, and artifacts** of
  the period, drawn across the files. Group by theme or chronology; cite specifics.
- **why_it_stayed** — why this period is worth remembering (the throughline / what it
  reveals).
- **possible_use** — e.g. `retro`, `portfolio`, `linkedin-idea`, `mentoring`, `timeline`.
- **reminders** — fold any open loops / follow-ups / "remember to" signals into
  `what_happened` (no separate field exists).
- **tags** — 3–8 short tags (no `#`): projects, clients, places, themes.
- **references** — the most notable contributing **file paths** from the manifest
  (cap ~15: pick the artifacts that anchor the story, not every file). You may also
  include a few enrichment anchors — a key commit URL from Step 1.5(b), or a prior
  entry's source — when they're part of the story's provenance.
- **when_iso** — use the `suggested_when_iso` from Step 1 (the period's last day, clamped
  to today) unless a specific day is clearly the centre of gravity.

Write these to the synthesis JSON using the **Write** tool (path = `digest_path` with
`.digest.md` → `.synthesis.json`, i.e. `logs/time-capsule/<slug>.synthesis.json`):

```json
{
  "moment": "...",
  "what_happened": "...",
  "why_it_stayed": "...",
  "possible_use": "...",
  "tags": ["...", "..."],
  "references": ["/abs/path/one", "/abs/path/two"],
  "when_iso": "2020-05-31T00:00:00"
}
```

---

## Step 3 — WRITE (dual-write the entry)

```bash
PY -c "import sys,json; sys.path.insert(0,'scripts'); import launch; launch.setup_env(); from workflows.hfl.tasks.time_capsule import run_write; print('JSON_RESULT='+json.dumps(run_write(synthesis_path=sys.argv[1])))" "<SYNTHESIS_JSON_PATH>"
```

`run_write` appends the entry to `<corpus>/YYYY-MM-DD.md` and indexes it in Elasticsearch
(`source="time-capsule"`, `synthesized=True`). It prints the entry path + ES doc id and
returns `{ok, path, doc_id, indexed, references}`.

---

## Step 4 — Report

Print a short summary to the user:
- the period + root swept, files analyzed (and per-kind breakdown),
- the **moment** headline + a 1–2 line gist of what was synthesized,
- the corpus path the entry landed in + whether it was ES-indexed,
- the manifest/digest artifact paths (for provenance).

---

## Running against a remote directory (advanced)

The default `/Volumes/harqis-data` lives on **harqis-server**. The simplest, most reliable
path is to run this skill **on that host** (the corpus lives there too). If you must drive
it from another machine, dispatch the collect task to the HFL queue and read the manifest
back — this needs a Celery **result backend** configured (`CELERY_RESULT_BACKEND`), which
the client SPROUT app does not set by default:

```bash
PY -c "import os,sys,json; sys.path.insert(0,'scripts'); import launch; launch.setup_env(); from core.apps.sprout.app.celery import SPROUT; from workflows.queues import WorkflowQueue; b=os.environ.get('CELERY_RESULT_BACKEND'); SPROUT.conf.result_backend=b; assert b, 'set CELERY_RESULT_BACKEND'; from workflows.hfl.tasks.time_capsule import collect_time_capsule; r=collect_time_capsule.apply_async(kwargs={'root':sys.argv[1],'period':sys.argv[2]}, queue=WorkflowQueue.HFL); print(json.dumps(r.get(timeout=3600)))" "<ROOT>" "<PERIOD>"
```

Then synthesize from the returned manifest and write via `capture_hfl_entry` on the same
queue. If no result backend is available, fall back to running on harqis-server.

---

## Hard rules — never break these

1. **No entry on an empty/zero-file window.** Report and stop — never fabricate a moment.
2. **Grounded synthesis only.** Every claim in the rollup must trace to a file in the
   digest/manifest. Say "appears to" for uncertainty; never invent events.
3. **Haiku for captions.** The collect task captions with `claude-haiku-4-5-20251001`.
   Never raise `BaseApiServiceAnthropic.DEFAULT_MODEL`. Bound spend with `--max-files` /
   `--no-caption`.
4. **One rollup per run.** This skill produces a single synthesized `HflEntry` for the
   period (with file metadata in `references`) — not per-file or per-day entries.
5. **Dual-write only via the task.** Write the entry through `run_write` (which uses
   `capture.append_entry`) so the corpus + ES projection stay in lockstep. Never write the
   corpus file by hand.
6. **Reachable root or stop.** If `--root` isn't mounted on the host, surface the
   `root-unreachable` guidance — do not silently produce an empty capsule.
7. **Provenance artifacts are kept.** Leave the `logs/time-capsule/<slug>.{manifest.json,
   digest.md,synthesis.json}` files in place; they are the run's audit trail.
8. **Enrichment is cross-reference, not re-ingest.** Step 1.5 pulls already-captured
   signal (ES entries + `apps/` integration data) only to ground and de-duplicate the
   rollup — never to fabricate. Skip it cleanly (`--no-enrich`, an empty result, or a
   failed best-effort call) without aborting the run.
