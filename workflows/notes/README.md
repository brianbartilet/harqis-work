# Repository-backed notes workflow

This workflow synchronizes one or more Git-backed note collections from their
editing machines to a canonical checkout on `harqis-server`. The HFL workflow
then turns changed material into searchable Activity Corpus entries.

It is intentionally repository-agnostic: Markdown notes, text files, images,
spreadsheets, and other media may coexist. Text notes and common images can be
distilled individually; unsupported binaries are preserved as references in a
bounded summary rather than uploaded to a model.

## Daily flow

| Time | Task | Queue | Behavior |
| --- | --- | --- | --- |
| 22:30 | `broadcast_push_note_repositories` | `default_broadcast` | On each editing worker, stage all changes, create one timestamped commit when needed, and push the configured branch. |
| 22:40 | `pull_note_repositories` | `host` | On `harqis-server`, clone a missing checkout or fetch and merge with `--ff-only`. Record the exact successful HEAD. |
| 22:50 | `ingest_notes_activity` | `hfl` | Diff the saved cursor against that HEAD and dual-write granular Activity Corpus entries plus an overflow/reference summary. |

The first successful ingest stores the current HEAD as its baseline and writes
nothing. Existing repository history is therefore not backfilled. The cursor
advances only after every entry has been durably accepted.

## Configuration

Repository definitions and machine bindings are merged from `machines.toml`
and the gitignored `machines.local.toml`:

```toml
[notes]
state_dir = "/Volumes/harqis-one/GIT/.harqis-notes-state"

[notes.repositories.notes]
remote = "git@github.com:owner/notes.git"
branch = "master"
host_path = "/Volumes/harqis-one/GIT/notes"
tags = ["notes", "dsm"]
include_globs = []
exclude_globs = [".git/**", ".idea/**", "**/.DS_Store"]
max_entries = 25
max_media = 10
max_text_chars = 20000

[windows-work-all.notes.repositories]
notes = "C:/Users/name/GIT/notes"
```

`state_dir` must be outside the clone. Each repository gets separate pull
status and ingest-cursor JSON files. A machine only pushes repositories bound
under its own machine key.

## Entry shape

Each qualifying changed text note or common image becomes one normal HFL entry
with:

- source `notes` and tags `#notes #dsm #repo-<name> #<core-topic>`;
- a GitHub blob reference pinned to the ingested commit;
- the host-local file path for downstream retrieval;
- a concise moment, change description, retention reason, and possible use.

The total per-run entry cap defaults to 25. When a summary is required, it
reserves the final slot. Deleted files, unsupported binaries, images beyond the
media cap, and all overflow changes are grouped into that summary, whose
reference points to the GitHub commit comparison and host clone.

## Safety and failure behavior

- Pushes never force, pull, rebase, or resolve conflicts automatically.
- Host updates require a clean checkout, the configured branch, and a
  fast-forward merge. A dirty/diverged checkout is an error and blocks ingest.
- Git authentication comes from each machine's existing SSH agent or credential
  helper; terminal prompts are disabled in scheduled pushes.
- A missing binding/configuration is a clean no-op.
- HFL ingest requires a recent successful pull record for the exact current
  HEAD, preventing stale or partially synchronized content from being indexed.
- Note contents are private repository data. Only bounded text and selected
  common images are sent to Anthropic when synthesis is enabled.

For a read-only view, use the MCP `notes_activity` tool. It lists changed paths
since the ingest cursor and can optionally synthesize bounded previews without
writing the corpus.

## Manifesto alignment

| Task | CODE role | PARA | Express target | HFL signal |
| --- | --- | --- | --- | --- |
| `broadcast_push_note_repositories` | organize | area | Git remote + run log | no |
| `pull_note_repositories` | organize | area | canonical host checkout + run log | no |
| `ingest_notes_activity` | capture + distill + express | area | Activity Corpus file + Elasticsearch | yes |
