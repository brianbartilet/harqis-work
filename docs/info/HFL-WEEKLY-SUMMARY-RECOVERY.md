# Weekly HFL summary: bounded historical recovery

`summarize_hfl_week(end_date="YYYY-MM-DD", window_days=7)` selects exactly seven
calendar dates ending on the supplied date (inclusive), using the worker's local
calendar. Omit `end_date` for today. The end date determines the ISO year/week of
the Markdown filename, tags, Elasticsearch document ID and historical timestamp.
Daily files in visible archive subdirectories are included; hidden backup and
AppleDouble files are excluded. This corrects the old inclusive eight-day lower
bound and missing upper bound. Existing callers still default to seven days.

## Cost and completeness boundary

The system prompt plus user text is limited to **120,000 UTF-8 bytes**. This is a
conservative application ceiling, not a tokenizer measurement or a guarantee for
arbitrary custom models. The complete entry body is retained: if it alone exceeds
the ceiling, the task raises a content-free `ValueError` **before reference fetching,
client creation, model calls or summary publication**. It does not silently sample
entries, drop dates, or publish an incomplete weekly summary.

Reference excerpts, headings and metadata share one global `ref_max_total` budget
(default 60,000 bytes), further reduced to remaining prompt space. Earlier code
reset this budget for every entry. References stop being visited when the budget
is spent. `references_seen` and `references_resolved` describe visited entries,
not total corpus reference coverage. The appendix explicitly labels excerpts as
potentially incomplete. This bounds prompt size, not total HTTP response download
size or the runtime of the underlying reference resolver.

## Recovery gates

1. Obtain deployment and paid-model/write authorization separately. Do not call the
   decorated task as a read-only probe: it changes task-health history.
2. Read the exact dated window with `_collect_window(7, end_date=date(...))` and
   measure `_format_for_prompt(entries)` locally. Do **not** call the reference
   resolver to estimate size. Include system and window framing in the final
   budget check. Check duplicate daily files/entry IDs in root and archives.
3. Inventory existing `YYYY-Www-rollup.md` files recursively and the matching
   `hfl-weekly-YYYY-Www` Elasticsearch document. The existing publication code
   replaces a root rollup; it is not a transactional archive-aware migration.
   Do not retry a week with an archived existing rollup without a reviewed
   replacement plan. Do not dispatch two overlapping same-week windows.
4. If the base prompt fits, and that exact week is absent, a conservative approved
   canary is `summarize_hfl_week` with `end_date="2026-09-27", window_days=7,
   resolve_references=False, max_tokens=1024`. Run **one** week at a time, only
   after preflight; this is an example contract, not authorization or an executed
   recovery. Then verify terminal outcome, exact summary filename and content,
   dated coverage and Elasticsearch identity before another week.
5. If the base prompt exceeds the budget, **stop**. Do not increase the ceiling,
   retry unchanged, or narrow `window_days` and label it a full-week recovery.
   A separately reviewed bounded multi-stage synthesis with explicit coverage,
   model-call/spend ceiling and final provenance is required. This patch does
   not implement that larger summarization redesign.

The October 2 investigation found both missed September weeks above the base
budget. Therefore this patch provides safe historical targeting and fail-closed
budget enforcement, **not completed recovery or proven resolution of the original
provider BadRequestError**. Historical provider response details were unavailable
in the bounded local logs inspected. See `results/hfl/repair-20261002/weekly-summary.md`.
