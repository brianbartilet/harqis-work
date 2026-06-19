---
name: dumps-summary
description: Summarize the daily dumps inbox to a per-day Markdown file (and the HUD feed). Walks <machine>-daily-dumps-<date> folders on harqis-server, writes <dir>/YYYY-MM-DD.md for each day with dumps to both the repo sink and the Drive-synced feed sink, and prints the per-day breakdown. Mirrors the /hfl corpus pattern. Trigger phrases — "dumps summary", "summarize dumps", "dump summary for <date>", "write the dumps md", "backfill dumps summaries".
---

Generate the per-day daily-dumps summary Markdown file(s) by invoking
`scripts/agents/dumps/run_dumps_summary_retro.py`, which calls the
`analyze_daily_dumps` task. Defaults to yesterday; accepts a date / range /
month, exactly like the nightly + weekly-catch-up beat runs.

⚠️ Runs on **harqis-server** only — the dumps inbox is a local path there
(`[dumps] harqis_server_inbox`). Off-host the task self-guards and exits 2
("Skipped: not harqis-server"). If this session isn't on harqis-server, tell the
user to run it on the host (or via `/sync-host` + an SSH session) rather than
forcing it.

## Where the summary lands

`analyze_daily_dumps` writes three artifacts (the first is what this skill is
for; the other two are existing, untouched):

1. **Per-day Markdown** — `<dir>/YYYY-MM-DD.md`, one file per day that has
   dumps, written to BOTH sinks (idempotent overwrite):
   - Repo sink: `DUMPS.summary.path` (apps_config) → `DUMPS_SUMMARY_PATH` env →
     `<repo>/logs/dumps/`.
   - Feed sink: `<resolved-feed-dir>/dumps/` when the feed dir exists on this
     host (rides the same Drive sync as the HUD feed). Skipped cleanly if no
     feed dir is configured/mounted here.
   - Logic lives in `workflows/dumps/summary_store.py`.
2. **HUD feed** — the rendered text, prepended to `hud-logs-YYYYMMDD.txt`
   (`@feed()`), as before.
3. **ES review trail** — the structured return (`@log_result()`), as before.

A day with **no** dumps writes no Markdown file — its absence is the signal, and
`--missing-only` reports gaps explicitly.

## Arguments

`$ARGUMENTS` maps 1:1 to the script flags (precedence: date → start/end → month
→ days → yesterday):

| Flag | Meaning |
|---|---|
| `--days N` | last N full days ending yesterday |
| `--date YYYY-MM-DD` | one specific day (not capped at yesterday) |
| `--start / --end` | inclusive YYYY-MM-DD window (capped at yesterday) |
| `--month YYYY-MM` | whole calendar month (capped at yesterday) |
| `--machine <name>` | limit to one machine/device dump prefix |
| `--missing-only` | gap report (days with NO dumps) instead of the breakdown |
| `--no-md` | skip the Markdown files (feed/ES summary only) |

No arguments → yesterday (same as the nightly beat).

## Steps

1. **Confirm the host.** If you can't tell whether this is harqis-server, run
   the script anyway — it self-guards and exits 2 with a clear message; relay
   that and stop.
2. **Run the script**, forwarding `$ARGUMENTS`:
   `python scripts/agents/dumps/run_dumps_summary_retro.py $ARGUMENTS`
3. **Report**: the printed per-day breakdown + grand total, and the list of
   summary file paths the script reports ("Wrote N summary file(s)"). Surface
   any gap days.

## Exit codes

`0` ok · `1` error (e.g. `harqis_server_inbox` unset, empty date range) · `2`
skipped (ran off harqis-server).

## Configuration (optional)

To override where the repo-side Markdown lands, set `[dumps] summary_path` in
`machines.local.toml` (the canonical home — right next to the inbox):

```toml
[dumps]
harqis_server_inbox = "/Users/harqis-one/dumps"
summary_path        = "/Volumes/harqis-data/dumps-summary"
```

Full precedence (first hit wins): `[dumps] summary_path` → `DUMPS.summary.path`
(apps_config) → `DUMPS_SUMMARY_PATH` env → `<repo>/logs/dumps/`. The feed sink
is derived from the existing `DESKTOP_PATH_FEED*` config — no extra setup.
