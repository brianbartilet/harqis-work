# HFL Ingest Candidates — Future Source Backlog

> Brainstorm captured 2026-05-29. **Not approved. Not scheduled. Not committed
> work.** This is a parked menu of future `workflows/hfl/tasks/ingest_*` sources
> to evaluate when the appetite is there, ranked so the obvious wins are easy
> to find again. Items move from here into a real PR via `/clarify-feature`.

The goal of the HFL workflow is **personal-signal capture** in service of
`docs/MANIFESTO.md` §2 (Homework for Life). Every new source should produce
**one structured corpus entry per day per source** (the existing pattern
established by `ingest_chatgpt_activity`, `ingest_browsing_activity`,
`ingest_location_activity`, etc.). No source warrants more than one entry per
day unless the volume genuinely demands it.

---

## What "friction" means in this doc

Throughout, **friction = implementation cost**:

1. **Effort** — engineering hours to ship (auth, parsing, error handling).
2. **Operational tax** — ongoing cost (quotas, secret rotation, broken-API maintenance).
3. **Integration distance** — whether the app already exists in `apps/`, whether auth is solved, whether there's a precedent task to copy.

A task that's easy to ship but breaks every month is *high friction overall*,
not low. The estimates below collapse those three into a single rough hour
count — "ship + first month of operating it."

---

## Already shipped (do not re-propose)

| Task | Source |
|---|---|
| `capture_hfl_entry` | Manual capture |
| `analyze_hfl_media` | Vision pass over dumps inbox (images/videos) |
| `ingest_git_activity` | Daily git/GitHub commits |
| `ingest_chatgpt_activity` | ChatGPT conversation distillation |
| `ingest_ai_activity` | OpenAI Platform threads (disabled, superseded by chatgpt) |
| `ingest_browsing_activity` | Chrome/Edge SQLite history |
| `ingest_location_activity` | OwnTracks GPS → stay-points → Nominatim |
| `summarize_hfl_week` | Weekly Haiku rollup |
| `retrieve_hfl_corpus` | Substring + tag scan (mailed weekly) |
| `collect_time_capsule` | Bounded archive ingest (driven by skill) |
| `build_hfl_knowledge_graph` | Graphify-based weekly graph (Phase 1, adhoc) |

---

## Candidates — by category

### Communication (highest signal gap)

| Candidate | What it captures | Reuses | Friction | Notes |
|---|---|---|---|---|
| `ingest_calendar_activity` | Today's Google Calendar meetings: attendees, agenda, your description block | `apps/google_apps/` | **~2 h** | Captures "what did I actually do today" better than any other single source. **Strongest single candidate.** |
| `ingest_email_activity` | Daily Gmail triage: senders contacted, threads replied to, decisions made | `apps/google_apps/` | **~3 h** | Pair with calendar. Use existing `label:important` + `is:unread today` to pre-filter noise. |
| `ingest_slack_activity` | DM + channel summaries: per-channel daily one-liner of what got discussed | (new) `apps/slack/` | ~6 h | Needs a new app. Significant ongoing maintenance — Slack scope rotation is annoying. |
| `ingest_telegram_activity` | Conversations mirrored into HFL the way ChatGPT activity already is | `apps/telegram/` | ~3 h | App already exists; only personal DMs / important groups worth ingesting (not bot noise). |

### Work signal (already tracked elsewhere — not yet in HFL)

| Candidate | What it captures | Reuses | Friction | Notes |
|---|---|---|---|---|
| `ingest_jira_activity` | Tickets touched, comments made, status transitions today | `apps/jira/` | ~2 h | Distinct from `workflows/knowledge/ingest_jira_issues` (bulk RAG). This is "what I worked on today." |
| `ingest_trello_activity` | Cards moved, comments added today | `apps/trello/` + Kanban orchestrator | ~2 h | Trello signal is already pulled by the orchestrator for agent work — different shape, different purpose. |
| `ingest_pr_activity` | GitHub PRs opened, reviewed, or merged today; review comments given/received | `apps/github/` | ~2 h | Conversation layer that `ingest_git_activity` misses. |

### Reading & learning (low effort, high signal)

| Candidate | What it captures | Reuses | Friction | Notes |
|---|---|---|---|---|
| `ingest_kindle_highlights` | Weekly Kindle highlights export — what stuck enough to underline | (new) `apps/kindle/` | ~4 h | What you highlight = literal future story material. Weekly schedule, not daily. |
| `ingest_spotify_activity` | Daily listening history — duration, top tracks, mood proxy | (new) `apps/spotify/` | ~3 h | "Listened to X for 2h while debugging" is a real HFL beat. Adds emotional tone layer. |
| `ingest_podcast_activity` | Pocket Casts / Apple Podcasts listening + auto-bookmarked timestamps | (new) `apps/pocketcasts/` | ~4 h | Bookmarks are higher-signal than full listening; consider bookmarks-only mode. |

### Health & rhythm (great context for everything else)

| Candidate | What it captures | Reuses | Friction | Notes |
|---|---|---|---|---|
| `ingest_health_activity` | Apple Health / Google Fit daily summary: sleep, steps, workouts | (new) `apps/apple_health/` or `apps/google_fit/` | ~5 h | Cross-references location and mood beautifully. **Highest-leverage novel candidate** — makes every other source more interpretable. |
| `ingest_sleep_activity` | Whoop / Oura ring recovery score per day | (new) `apps/whoop/` or `apps/oura/` | ~4 h | Only worth it if Brian wears the ring consistently. |

### Notes & writing (capture-adjacent)

| Candidate | What it captures | Reuses | Friction | Notes |
|---|---|---|---|---|
| `ingest_notes_activity` | Obsidian vault / Apple Notes / Bear: notes created or edited today | (varies — local Obsidian = filesystem; Apple Notes = harder) | ~3 h (Obsidian) / ~8 h (Apple Notes) | Personal-notes counterpart to `workflows/knowledge/ingest_notion`. |
| `ingest_voice_memo_activity` | Voice Memos folder → Whisper transcripts → distillation | (new) Whisper integration or `apps/open_ai/` audio | ~6 h | Captures stuff said but not written. Whisper cost is real — bound it. |

### Novel angles (less obvious, surprisingly rich)

| Candidate | What it captures | Reuses | Friction | Notes |
|---|---|---|---|---|
| `ingest_shell_history` | bash/zsh/PowerShell history per machine — what commands I ran | filesystem | ~3 h | "Today I learned about `ip neigh`" beats. Per-machine source key (like browsing). Privacy: log location + script names, not arguments. |
| `ingest_weather_activity` | Weather + air quality at each stay-point | `ingest_location_activity` output + open-meteo API | ~3 h | Cheap join — location already produces stay-points. |
| `ingest_print_queue` | What was printed today | OS-specific (CUPS / print spooler) | ~5 h | Surprisingly story-rich: what I printed = what I was prepping for in meatspace. |

### High-friction (mention, defer indefinitely)

| Candidate | Why it's hard |
|---|---|
| WhatsApp | E2E encryption makes export gymnastics required; breaks every WhatsApp update. |
| Apple Screen Time | No clean API; would require plist scraping that breaks on macOS updates. |
| Camera roll OCR for whiteboards | `analyze_hfl_media` already does vision; this would be a text-specialized variant. Marginal gain over what exists. |
| Tesla / car telematics | Vendor-specific APIs that change without notice; only valuable for owners. |
| Phone call logs | Needs deeper Android / iOS access; legally fraught in some jurisdictions. |

---

## Recommended next batch (when work resumes)

In priority order:

1. **`ingest_calendar_activity`** — captures "what did I actually do today" better than any other source. ~2 h.
2. **`ingest_email_activity`** — pairs with calendar to close ~80% of the work-day signal gap. ~3 h.
3. **`ingest_health_activity`** — adds a physical/emotional tone layer to the corpus. Highest-leverage *novel* source. ~5 h.

After those three, the next decision point is whether to go **wide** (more sources for breadth) or **deep** (richer summarization / cross-source correlation via the knowledge graph from PR #29).

---

## Cross-cutting concerns to settle once

Decisions made when the first new source ships should hold for the rest of the batch:

- **Source key naming** — already established (`source="browsing"`, `source="location"`, etc.). Continue the pattern.
- **Multi-tenant readiness** — every new ingest task gets `manifesto.tenant_safe: True` if it reads tenant-scoped credentials (PR #27 hook).
- **Privacy redaction** — at minimum: `exclude_domains` (browsing precedent), redact email recipients, redact phone numbers. Document per-source defaults.
- **Skip-on-no-data** — every new task must no-op cleanly when there's nothing to ingest (no LLM call, no entry, no ES write). The HFL ingest pattern is non-negotiable here.
- **Model pin** — always pass `model="claude-haiku-4-5-20251001"` from `tasks_config.py`. Never touch `BaseApiServiceAnthropic.DEFAULT_MODEL`.
- **Dual write** — `file:hfl_corpus + es:hfl-entries` is the established express target. Source-specific exceptions need a documented reason.

---

## See also

- `docs/MANIFESTO.md` §2 — Homework for Life as a first-class data source
- `docs/thesis/MANIFESTO-REPO-UPDATES.md` §3.3 — gap analysis that scaffolded HFL
- `workflows/hfl/README.md` — current ingest surface + activation matrix
- `workflows/hfl/KNOWLEDGE_GRAPH.md` — Graphify rollout that makes "queryable by prompt" real
- PR #27 (`feat/aaas-tenant-foundation`) — `manifesto.tenant_safe` hook future ingests should opt into
- PR #29 (`feat/hfl-knowledge-graph`) — Phase 1 of the graph pipeline
