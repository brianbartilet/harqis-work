# `workflows/hfl/` — Homework for Life

> The manifesto's principle 2 made concrete: a workflow surface for the daily
> story-moment habit from Matthew Dicks' *Storyworthy*. Treats Homework for
> Life as a **first-class data source** — captured, retrievable, summarizable —
> not a journaling app.

This workflow is **active** — `workflows/config.py` merges `WORKFLOW_HFL` into
the beat schedule, so the ingest tasks run on the Beat host. Individual sources
stay clean no-ops until configured (a ChatGPT token, OwnTracks reporting, a
phone dumps-pull target); §Activation covers what each one needs.

---

## Why this workflow exists

`docs/MANIFESTO.md` calls Homework for Life out by name and specifies a
standard entry shape:

```text
## YYYY-MM-DD
Moment:
What happened:
Why it stayed with me:
Possible use:
Tags:  #work-story #debugging #automation …
```

The manifesto's promise is that the corpus becomes "queryable by prompt"
— *"What was I working on the week of 2026-04-12?"*, *"Show me debugging
stories tagged #root-cause."*, *"Reconstruct the timeline for the OANDA
forex agent rollout."* This workflow makes that promise honest.

The audit at `docs/thesis/MANIFESTO-REPO-UPDATES.md` §3.3 documents the gap
this scaffold closes.

---

## Tasks

| Task | What it does | Express target | Schedule (when active) |
| --- | --- | --- | --- |
| `capture_hfl_entry` | Appends one structured entry to today's corpus file. Empty `moment` is a no-op. | `file:hfl_corpus` | Adhoc — invoked via `.delay()`, an MCP tool, an agent, or a hotkey. The scheduled slot fires Sunday 03:33 with empty kwargs (i.e. is a no-op). |
| `retrieve_hfl_corpus` | Substring + tag scan over the corpus, optional date filter. Returns up to `k` entries, most recent first. | `es_log` (callers consume the return value) | Adhoc — same pattern as capture. |
| `summarize_hfl_week` | Weekly Haiku 4.5 rollup of the past N days; writes `_summary-YYYY-Www.md` alongside the daily files. | `file:hfl_summary+es_log` | Sundays 21:00 local. |
| `ingest_chatgpt_activity` | **Primary daily research log.** Auto-discovers the operator's ChatGPT conversations created/updated that day via the ChatGPT web app's private backend (no thread ids), distils the questions asked into ONE corpus entry. Haiku-distilled, raw fallback. No token / no prompts → no entry, no call. | `file:hfl_corpus` | Daily 23:00 local (active — no-op until `CHATGPT_WEB_ACCESS_TOKEN` is set). |
| `ingest_ai_activity` | Alternate source (OpenAI **Platform API** assistant threads, via `OPENAI_HFL_THREAD_IDS`). Superseded by `ingest_chatgpt_activity` — kept in code but its beat entry is **disabled** (commented-out) to avoid a nightly no-op. | `file:hfl_corpus` | Disabled (uncomment in `tasks_config.py` if you also want Platform-API threads). |
| `ingest_browsing_activity` | Daily web-browsing digest. Reads the Chrome + Edge `History` SQLite DBs directly (copy-to-temp to dodge the browser lock; no app/credential), distils the day's visits into ONE corpus entry with the most-visited pages as `references`. Haiku-distilled, raw fallback. No history DB / no visits → no entry, no call. No domain filtering by default (`exclude_domains` kwarg to redact). | `file:hfl_corpus+es:hfl-entries` | Daily 23:00 local (active — `os: windows`; no config needed). |
| `ingest_location_activity` | Daily location timeline. Pulls the day's GPS track from the local OwnTracks Recorder (`apps/own_tracks`), clusters fixes into **stay-points** (dwell ≥ N min), reverse-geocodes each via OpenStreetMap Nominatim (free, no key), and distils ONE "where I was today" timeline entry. Haiku-distilled, raw fallback. No device configured / Recorder unreachable / no fixes → no entry, no call; fixes with no qualifying stay write a movement-only breadcrumb. | `file:hfl_corpus+es:hfl-entries` | Daily 23:05 local (active — clean no-op until OwnTracks reports). |
| `ingest_spotify_activity` | Daily Spotify listening digest. Pulls the day's plays from the Spotify Web API (`apps/spotify`, OAuth2 refresh-token), with the operator's rolling top tracks/artists as context, and distils ONE "soundtrack of the day" entry — mood **inferred** by Haiku from track/artist/genre names (no audio-features; deprecated for new apps). Haiku-distilled, raw fallback. No credentials / no plays → no entry, no call. `recently-played` caps at 50/day. | `file:hfl_corpus+es:hfl-entries` | Daily 23:10 local (**shipped commented-out** — uncomment in `tasks_config.py` once `SPOTIFY_*` creds are set; `tenant_safe`). |
| `ingest_plaud_activity` | Daily **voice-recordings** ingest. Pulls the day's Plaud recordings via the `apps/plaud` adapter (cloud API → local export-folder fallback) and writes **ONE entry per recording** (not a daily digest). Transcript precedence: Plaud's own transcript, else OpenAI **Whisper** on the raw audio (bounded by `max_transcribe`). Raw recordings + a consolidated `YYYY-MM-DD-summary.md` are archived to `harqis-ones-mac-mini` over key-based SSH. Haiku-distilled, raw fallback. No `PLAUD_TOKEN`/`PLAUD_EXPORT_DIR` → no entry, no call; no recordings → no entry, no call. | `file:hfl_corpus+es:hfl-entries` | Daily 23:15 local (active — clean no-op until acquisition is configured; `tenant_safe`). |
| `ingest_looki_activity` | Metadata-first Looki L1 wearable ingest. Polls an overlapping date window and writes **ONE entry per moment** with `looki:<id>` provenance. Looki-generated descriptions remain explicitly unverified; no LLM, media download, coordinates, or signed URL persistence. | `file:hfl_corpus+es:hfl-entries` | **Shipped commented-out**; proposed daily 23:25 local after approved API access and a live schema smoke test. |
| `ingest_radar_activity` | Daily **HERMES RADAR digest.** Reads the day's compatibility-named `show_daily_radar` synthesis blocks back out of the shared desktop feed file (`<feed_dir>/hud-logs-YYYYMMDD.txt`) and distils them into ONE "what the day was about" entry. It does not ingest the 15-minute Telegram push rerenders or re-run the radar source sweep. The feed file is Drive-synced, so the Beat host reads briefings a Windows radar wrote; files read remain the entry references. Haiku-distilled, raw fallback. No feed dir / no synthesis blocks → no entry, no LLM call. | `file:hfl_corpus+es:hfl-entries` | Daily 23:20 local (active — clean no-op until `DESKTOP_PATH_FEED` is set and the radar has run). |
| `analyze_hfl_media` | **Daily media vision pass.** Walks the dumps inbox for recent images/videos (pulled from phones + machines by `workflows/dumps/`), reserves 10 of the 40 analysis slots for Android-origin media, then fills unused capacity by global recency. Each item is sent to Haiku vision for a story moment and **geo-tagged** — EXIF GPS, else the nearest OwnTracks fix by capture time → Nominatim place. One entry per story-worthy item; the source dump file + an OSM pin are the `references`. Already-referenced media is skipped before the model call. Passing `media_path=<inbox file>` targets one artifact directly. | `file:hfl_corpus+es:hfl-entries` | Daily 22:00 local (active). |
| `collect_time_capsule` | **On-demand, time-ranged archive ingest.** Sweeps a directory (and subdirs) for files dated within a period, extracts text / docs / Haiku vision captions into a bounded manifest + digest. The COLLECT half of the `/time-capsule-synthesizer` skill (Claude synthesizes ONE rollup entry from the digest, then dual-writes it via `capture_hfl_entry`). Not scheduled. | `file:hfl_corpus+es:hfl-entries` (via the skill) | Adhoc — driven by `/time-capsule-synthesizer`. |

Each carries the manifesto metadata block on the beat entry — see
`workflows/hfl/tasks_config.py`.

---

## Android phone → HFL (the two streams)

A phone feeds HFL through **two independent streams that meet on a shared key —
the timestamp**. Nothing custom runs on the phone beyond the OwnTracks app and a
Termux SSH daemon.

**1. Location (OwnTracks).** The app publishes GPS fixes (MQTT or HTTP) to the
`mosquitto` broker → `owntracks-recorder` on harqis-server (see
[`apps/own_tracks/README.md`](../../apps/own_tracks/README.md)). Two consumers:
- `ingest_location_activity` (23:05) turns the day's track into a "where I was
  today" timeline entry.
- `ingest_location.nearest_fix()` answers "where was the phone at time T?" —
  used to geo-tag photos (below).

**2. Media (photos / videos / screenshots).** `pull_daily_dumps_from_remotes`
(`workflows/dumps/`, 00:05) **copies** the phone's `DCIM/Camera` +
`Pictures/Screenshots` over Tailscale (Termux SSHD) into the harqis-server dumps
inbox. The originals stay on the phone; the **copies are retained as files** —
one dated folder per day, never auto-deleted:

```
<harqis_server_inbox>/nothing-phone-daily-dumps-2026-05-25/
  Camera/…   Screenshots/…
```

`analyze_hfl_media` (22:00) then *reads* (never moves/deletes) each selected
new file, captioning it with Haiku vision and **geo-tagging** it — EXIF GPS first, else the
nearest OwnTracks fix to its capture time → Nominatim place — writing one entry
per story-worthy item with the file path + an OSM pin as `references`. Android
media receives a reserved quota so desktop screenshot volume cannot starve the
phone stream; unused phone slots flow back to the globally newest media. Android
classification requires the exact configured `nothing-phone-daily-dumps-YYYY-MM-DD`
source identity plus a canonical Camera/DCIM/Screenshots/Screenrecord folder;
generic desktop folders and prefix-like source names are not treated as Android.

For an individual screenshot/photo, invoke the same task with
`media_path=<absolute path inside the dumps inbox>`. Paths outside the inbox are
rejected. Corpus references plus atomic per-path state in
`.media-ingest-state/` make retries and overlapping worker runs idempotent; a
completed path does not append duplicate Markdown or spend another vision call.
Claims use descriptor-bound advisory locks, so ownership cannot change between
validation and finalization and a killed worker releases its claim automatically.
Explicit story-worthiness skips become terminal; malformed model output,
read/decode errors, API failures, and incomplete append failures release the
claim for retry. Persistent `.lock` files are harmless lock targets and do not
mean a worker still owns the media path.

**The join.** A photo carries a capture *time*; OwnTracks carries a timestamped
*track*. Matching the two locates even screenshots and EXIF-stripped media — so a
screenshot taken downtown comes out tagged with the place.

**Daily cadence (harqis-server):**

| Time | Task | Result |
| --- | --- | --- |
| 00:05 | `pull_daily_dumps_from_remotes` | phone photos/screenshots → dumps inbox (retained) |
| 22:00 | `analyze_hfl_media` | each story-worthy photo → geo-tagged entry |
| 23:00 | `ingest_browsing_activity` / `ingest_chatgpt_activity` | browsing + research → entries |
| 23:05 | `ingest_location_activity` | day's movement → one timeline entry |
| 23:10 | `ingest_spotify_activity` | day's plays → one soundtrack entry |
| 23:15 | `ingest_plaud_activity` | day's voice recordings → one entry each + Mac-mini archive |

**Setup** (one-time): the OwnTracks app + `OWN_TRACKS_DEFAULT_USER/DEVICE` (the
location stream — §Activation); a `[dumps.pull_targets.<phone>]` block in
`machines.local.toml` pointing at the phone's Termux SSHD over Tailscale (the
media stream — see [`workflows/dumps/README.md`](../dumps/README.md)). Set the
camera to **JPEG, not HEIC** — `analyze_hfl_media` only reads
`jpg/jpeg/png/webp/gif` (+ `mp4/mov/mkv/webm`), and Pillow can't read HEIC EXIF
without `pillow-heif`. (Termux's sshd must be alive at 00:05 — a `termux-wake-lock`
plus the Termux:Boot addon keeps it up across sleeps/reboots.)

**Querying it (MCP tools in `workflows/hfl/mcp.py`):** `memory_recall` /
`memory_recall_es` (what happened in a window), `location_activity` (live
timeline), `memory_list_media` (photos/videos in a window). The weekly
`summarize_hfl_week` rollup is emailed each Sunday.

---

## Corpus layout

```
<corpus_root>/
  2026-05-13.md              # one file per day, entries appended
  2026-05-14.md
  _summary-2026-W20.md       # weekly summary written by summarize_hfl_week
```

### Corpus path resolution (first hit wins)

1. `apps_config.yaml::HFL.corpus.path` — preferred for distributed/worker
   nodes that load config remotely.
2. Env var `HFL_CORPUS_PATH` — convenient for local dev.
3. Fallback: `<repo>/logs/hfl/`.

A future activation step adds an `HFL:` section to `apps_config.yaml` and
the matching env var to `.env/apps.env`. The scaffold does not require
either to be present — the fallback path works on day one.

---

## Entry format

Capture writes plain Markdown, one block per call, appended to the day's
file. Multiple captures on the same day stack:

```markdown
## 2026-05-13 09:14
Moment:          Almost ignored a small bug in the feed decorator.
What happened:   The ${VAR} folder appearing at repo root turned out to be
                 an unresolved env var leaking into Path().resolve().
Why it stayed:   Small details reveal big problems.
Possible use:    #lesson  #linkedin-idea
Tags:            #debugging #root-cause #python
References:
                 - https://github.com/owner/repo/commit/abc1234
                 - C:\dump\2026-05-13\screenshot.png
```

The format is the formal `HflEntry` DTO (`workflows/hfl/dto/entry.py`) —
`_render_entry` delegates to it, so every producer emits an identical,
round-trippable block. Retrieval splits files on `## ` headers, so the
format must be preserved if entries are hand-edited.

**`References:` (optional).** URLs or host file paths pointing at the
source material behind the moment. The block is rendered **only when
present** — entries without references are byte-identical to the
pre-DTO format. References are searchable via `retrieve` and, on the
weekly run, `summarize_hfl_week` resolves them (bounded HTTP/file fetch,
text-only, size/timeout caps) and injects the excerpts into the rollup
prompt so the summary is grounded in the source — see
`workflows/hfl/references.py`. `analyze_hfl_media` auto-sets this to the
source dump file path (the dumps→media→corpus provenance loop), and — when
the media can be geo-located — also appends an OpenStreetMap pin for where it
was captured.

**Location-enriched media.** `analyze_hfl_media` resolves *where* each photo/
video was taken and folds the place into the entry: it reads **EXIF GPS** first
(the camera's own fix), and otherwise matches the capture time to the nearest
**OwnTracks** fix (`ingest_location.nearest_fix`) — so screenshots and
EXIF-stripped media get located too. The coordinate is reverse-geocoded
(OpenStreetMap Nominatim, the shared `_reverse_geocode` helper), and the place
is passed to the Haiku prompt, added as a tag, and pinned in `References`. All
best-effort: no EXIF, no OwnTracks device, or an unreachable Recorder/geocoder
just yields a place-less entry (the media is still analyzed). Requires Pillow
for EXIF (optional); see `apps/own_tracks` for the location source.

> Privacy/cost note: resolved file and URL content is sent to Anthropic
> in the weekly prompt. v1 bounds it (existence check, text-only,
> per-ref + total byte caps) but does **not** path-allowlist — any
> readable text file referenced will be resolvable.

---

## Activation

The beat wiring (step 2 below) is **already in place** on `main`; this section
is the reference for what each source still needs — and for bringing the
workflow up on a fresh fork:

1. **Wire the corpus path.** Either add an `HFL:` block to
   `apps_config.yaml`:
   ```yaml
   HFL:
     corpus:
       path: ${HFL_CORPUS_PATH}
   ```
   and set `HFL_CORPUS_PATH` in `.env/apps.env`, or rely on the
   `<repo>/logs/hfl/` fallback (fine for a single-host setup).

2. **Add to the beat schedule.** In `workflows/config.py`:
   ```python
   from workflows.hfl.tasks_config import WORKFLOW_HFL
   ...
   CONFIG_DICTIONARY = (
       WORKFLOW_PURCHASES | WORKFLOWS_HUD | WORKFLOWS_DESKTOP
       | WORKFLOW_SOCIAL | WORKFLOW_KNOWLEDGE | WORKFLOW_DUMPS
       | WORKFLOW_HFL
   )
   ```

3. **Restart Beat + an `adhoc`-subscribed worker and an `agent`-subscribed
   worker.** Capture and retrieve land on `adhoc`; the weekly summarizer
   lands on `agent`.

4. **Optional: drop a hotkey or n8n trigger** that prompts for the daily
   entry and calls `capture_hfl_entry.delay(moment=..., ...)`. The scheduled
   capture slot is a no-op safety net, not the real entry point.

5. **Optional: pipe the corpus into the existing `knowledge` RAG**
   workflow once it has critical mass — see
   `docs/thesis/MANIFESTO-REPO-UPDATES.md` §7.

### Activating `ingest_chatgpt_activity` (primary daily research log)

This task is **active** in `tasks_config.py` and is a clean no-op until
you give it a ChatGPT session token. It auto-discovers every ChatGPT
conversation you created/updated that day — no thread ids to manage.

> ⚠️ **Unofficial backend.** OpenAI's official Platform API cannot list
> threads or see ChatGPT-app chats at all. The only thing that can is the
> ChatGPT **web app's own private backend** (`chatgpt.com/backend-api`),
> which this task calls. It is undocumented and can change/break with any
> web deploy (the task degrades to a no-op, never a broken beat).
> Automating it is your own account + your own data for a personal log —
> the defensible case — but it is a grey area vs. the sanctioned API.

To make it produce entries:

1. **Grab a session token.** While logged in to chatgpt.com, open
   `https://chatgpt.com/api/auth/session` and copy the `accessToken`
   value.
2. **Set it** in `.env/apps.env`:
   ```
   CHATGPT_WEB_ACCESS_TOKEN=<accessToken>
   # Optional — only if Cloudflare blocks scripted requests:
   CHATGPT_WEB_COOKIE=cf_clearance=...; __Secure-next-auth.session-token=...
   CHATGPT_WEB_USER_AGENT=<the exact UA string from your browser>
   ```
3. **Restart Beat + an `hfl`-subscribed worker.** The
   `run-job--ingest_chatgpt_activity` entry is already active; it runs
   daily at 23:00 local, distils that day's prompts with Haiku, and
   appends one entry to the day's corpus file.

The token **expires** (days). When it does the task logs an HTTP 401 and
no-ops — re-grab it from `/api/auth/session` and re-paste. Only your own
(`role == "user"`) messages are read — the questions you asked, not
ChatGPT's answers. Claude (Haiku) is used solely as the distiller.

### Alternate: `ingest_ai_activity` (OpenAI Platform-API threads)

Disabled by default (commented-out beat entry). Reads specific Platform-API
assistant threads listed in `OPENAI_HFL_THREAD_IDS` — only useful if you
drive research through the official API rather than the ChatGPT app.
Uncomment its block in `tasks_config.py` and set the env var to enable it
alongside the ChatGPT-web task.

### `ingest_browsing_activity` (daily browsing digest)

**Active by default, no configuration.** Reads the *Default* profile
`History` SQLite DB for Chrome and Edge on the Windows worker (the beat
entry is `os: windows`), copies each DB (+ `-wal`/`-shm` sidecars) to a
temp file to dodge the browser's exclusive lock, windows by visit time,
distils with Haiku, and **dual-writes** corpus + the `harqis-hfl-entries`
ES index. The most-visited pages are stored as the entry's `references`.

- No history DB found / no visits in the window → clean no-op (no LLM).
- No domain filtering by default — pass `exclude_domains=("host", …)` in
  the beat kwargs to redact specific hosts, or trim `max_visits` /
  `browsers` to bound volume.
- Non-default profiles or a non-Windows layout: set absolute paths in
  `HFL_BROWSING_CHROME_HISTORY` / `HFL_BROWSING_EDGE_HISTORY`.
- Recency caveat: visits still buffered in the browser's `-wal` sidecar
  (not yet checkpointed) may miss the very latest pages — fine for a
  once-a-day digest.
- Live view (no write): the `browsing_activity` MCP tool in
  `workflows/hfl/mcp.py`.

### `ingest_location_activity` (daily location timeline)

**Active by default; a clean no-op until OwnTracks is reporting.** Pulls the
day's GPS track from the local OwnTracks Recorder, clusters fixes into
**stay-points** (places where you dwelled), reverse-geocodes them via
OpenStreetMap **Nominatim** (free, no API key), distils ONE "where I was today"
timeline with Haiku, and **dual-writes** corpus + the `harqis-hfl-entries` ES
index. The longest-dwell stay is stored as the entry's `references` (an
OpenStreetMap pin).

To make it produce entries:

1. **Turn on OwnTracks.** Start the broker + recorder
   (`docker compose up -d mosquitto recorder`) and point the OwnTracks
   Android/iOS app at the broker — see
   [`apps/own_tracks/README.md`](../../apps/own_tracks/README.md).
2. **Name the device** in `.env/apps.env` so the task knows which track to read:
   ```
   OWN_TRACKS_DEFAULT_USER=brian
   OWN_TRACKS_DEFAULT_DEVICE=android
   ```
3. **Restart Beat + an `hfl`-subscribed worker.** It runs daily at 23:05 local,
   clusters the day's fixes, distils the timeline, and appends one entry to the
   day's corpus file.

- No device configured / Recorder unreachable / no stay-points → clean no-op
  (no LLM, no entry).
- Tuning kwargs: `radius_m` (stay cluster radius, default 150 m),
  `min_dwell_min` (default 15), `max_gap_min` (signal-gap split, default 90),
  `max_points` (cap, default 5000).
- Nominatim is best-effort and rate-limited (≤1 req/s, cached per run); a
  geocode miss degrades that stay to coordinates-only.
- Live view (no write): the `location_activity` MCP tool in
  `workflows/hfl/mcp.py`.

### `ingest_spotify_activity` (daily listening soundtrack)

**Shipped commented-out** in `tasks_config.py` (the `SPOTIFY_*` creds aren't set
yet). Pulls the day's plays from the Spotify Web API (`apps/spotify`), uses the
operator's rolling top tracks/artists as distillation context, and **dual-writes**
ONE "soundtrack of the day" entry — corpus + the `harqis-hfl-entries` ES index.
Mood is **inferred** by Haiku from track/artist/genre names (Spotify deprecated
`audio-features`/valence for new apps in Nov 2024).

To make it produce entries:

1. **Mint the credentials.** Create a Spotify app, request the
   `user-read-recently-played` + `user-top-read` scopes, and mint a long-lived
   refresh token once — see [`apps/spotify/README.md`](../../apps/spotify/README.md).
   Set in `.env/apps.env`:
   ```
   SPOTIFY_CLIENT_ID=
   SPOTIFY_CLIENT_SECRET=
   SPOTIFY_REFRESH_TOKEN=
   ```
2. **Uncomment** the `run-job--ingest_spotify_activity` block in
   `workflows/hfl/tasks_config.py`, then run `/generate-registry` so it appears
   in the dashboard.
3. **Restart Beat + an `hfl`-subscribed worker.** It runs daily at 23:10 local
   (alongside browsing 23:00 / location 23:05), centralized on the Beat host
   (one Spotify account — not a per-machine broadcast).

- No credentials / no plays in the window → clean no-op (no LLM, no entry).
- `recently-played` caps at the last 50 plays and is a time-cursor endpoint —
  a heavy listening day loses the earliest tracks; the top tracks/artists layer
  covers "what defined the period" regardless. `played_at` is UTC, mapped to the
  local calendar day.
- Tuning kwargs: `window_days` (default 1), `max_tracks` (cap, ≤50),
  `top_limit` (top tracks/artists pulled for context, default 10).
- Live view (no write): the `spotify_activity` MCP tool in
  `workflows/hfl/mcp.py`.

### `ingest_plaud_activity` (daily voice recordings)

**Shipped active** in `tasks_config.py` — a clean no-op until acquisition is
configured. Pulls the day's recordings via the `apps/plaud` adapter (cloud API
primary → local export-folder fallback) and **dual-writes ONE entry per
recording** (not a daily digest) — corpus + the `harqis-hfl-entries` ES index,
`source="plaud"`, with a per-recording deterministic doc id (`YYYYMMDD-plaud-<id>`)
so re-runs upsert instead of duplicating.

To make it produce entries:

1. **Configure acquisition** (either is enough) in `.env/apps.env`:
   ```
   PLAUD_TOKEN=          # cloud API (preferred) — see apps/plaud/README.md
   PLAUD_EXPORT_DIR=     # local export-folder fallback
   ```
2. **Transcription fallback (optional).** When Plaud has no transcript for a
   recording, the audio is transcribed with OpenAI **Whisper** — needs
   `OPENAI_API_KEY` (already set for other apps). Bounded by `max_transcribe`
   (default 20/run) to cap cost. Set `allow_whisper=False` to disable.
3. **Archive (optional).** Raw recordings + a consolidated `YYYY-MM-DD-summary.md`
   are pushed to the archive host over **key-based SSH**:
   ```
   PLAUD_ARCHIVE_HOST=harqis-ones-mac-mini
   PLAUD_ARCHIVE_PATH=          # remote base dir — unset → archive skipped
   ```
4. **Restart Beat + an `hfl`-subscribed worker.** Runs daily at 23:15 local,
   centralized on the Beat host (one Plaud account — not a per-machine broadcast).

- No `PLAUD_TOKEN`/`PLAUD_EXPORT_DIR` → no entry, no network call; no recordings
  in the window → no entry, no LLM call.
- A failed archive (host unreachable / `PLAUD_ARCHIVE_PATH` unset) never costs a
  captured entry — corpus + ES are written first, and the archive result is
  surfaced in the task return dict, not raised (HFL never breaks the beat).
- Tuning kwargs: `window_days` (1), `max_recordings` (50), `max_transcribe` (20),
  `whisper_model` (`whisper-1`), `allow_whisper`, `archive`.
- Live view (no write): the `plaud_activity` MCP tool in `workflows/hfl/mcp.py`.

### `ingest_looki_activity` (wearable lifelog moments)

**Shipped commented-out** in `tasks_config.py` until approved API access exists
and a one-day live schema smoke test passes. The task polls the Looki Open API
through `apps/looki`, then dual-writes **one entry per moment** with deterministic
provenance (`looki:<id>`) and a collision-resistant ES ID derived from the exact
source ID (`looki-<first 128 bits / 32 hex chars of SHA-256>`).

To activate:

1. Apply at <https://web.looki.tech/api-keys>, create a key after approval, and
   set `LOOKI_API_KEY` in `.env/apps.env`.
2. Call `looki_status`, then `list_looki_moments` for a known date. Confirm IDs,
   timestamps, titles, and generated descriptions match the adapter contract.
3. Run `ingest_looki_activity(window_days=1, max_moments=20)` manually and review
   the HFL Markdown + Elasticsearch projection.
4. Uncomment `run-job--ingest_looki_activity` in `tasks_config.py`, regenerate
   registry data if required, and restart Beat plus an `hfl` worker.

Privacy and truth boundary:

- Metadata only; no automatic video download, precise coordinates, or temporary
  signed URL persistence.
- Looki-generated text is tagged `unverified-ai` and treated as a recall index.
- Consequential memories require explicit source-media verification using the
  Looki MCP file tool; URLs are hidden by default.
- The two-day overlapping window, atomic claim/done state, and global exact
  `looki:<id>` corpus check make overlapping workers and retries idempotent.
  Completed items are re-upserted to ES during overlap polls so a transient
  projection failure self-repairs.

See [`apps/looki/README.md`](../../apps/looki/README.md) and the design thesis
[`LOOKI-L1-HARQIS-INGESTION.md`](../../docs/thesis/LOOKI-L1-HARQIS-INGESTION.md).

---

### `ingest_radar_activity` (daily HERMES RADAR digest)

**Shipped active** in `tasks_config.py` — a clean no-op until there's signal.
The HERMES RADAR HUD (`workflows/hud/tasks/hud_radar.py :: show_daily_radar`)
fires every few hours and writes its synthesized briefing to the shared desktop
feed file via `@feed()`. This task reads those briefings **back out** and
distils the day's runs into ONE entry — it does **not** re-run the radar (which
pulls ~9 live sources and synthesizes with Sonnet each tick). It **dual-writes**
corpus + the `harqis-hfl-entries` ES index, `source="radar"`, with the feed
file(s) read recorded as the entry's `references`.

Why read the feed instead of re-running the radar: the radar is the expensive
producer; re-running it at ingest time would re-pull everything and generate a
*new* briefing, not ingest the day's. The feed file the radar writes
(`<feed_dir>/hud-logs-YYYYMMDD.txt`) is the cheap, faithful record.

To make it produce entries:

1. **A feed dir must resolve on the Beat host** — set `DESKTOP_PATH_FEED`
   (or the OS-specific `DESKTOP_PATH_FEED_DARWIN` / `_WINDOWS` / `_LINUX`) to an
   **existing** directory, exactly as the HUD feed system already uses. The
   radar's feed is typically Google-Drive-synced, so the host reads the
   briefings a Windows radar wrote. No feed dir → no entry, no I/O.
2. **The radar must have run** — at least one `show_daily_radar` block in the
   window. No briefings → no entry, no LLM call.
3. **Restart Beat + an `hfl`-subscribed worker.** Runs daily at 23:20 local,
   centralized on the Beat host (one feed — not a per-machine broadcast).

- Tuning kwargs: `window_days` (1), `prefix` (`hud-logs`, the `@feed()` filename
  prefix the radar writes under), `max_briefings` (24).
- Live view (no write): the `radar_activity` MCP tool in `workflows/hfl/mcp.py`.

---

## Elasticsearch entry index (dual-write)

The Markdown corpus is the source of truth. Ingest sources scaffolded by
`/create-new-ingest-source-hfl` **dual-write**: they append the corpus
entry *and* index the structured `HflEntry` to a queryable Elasticsearch
index via `workflows/hfl/es_store.py`.

- **Write:** `index_hfl_entry(entry, *, source, synthesized)` →
  `core.apps.es_logging.app.elasticsearch.post`. Deterministic doc id
  (`<YYYYMMDD>-<source>-<moment-hash>`) so re-runs upsert, never
  duplicate. Best-effort: any ES failure is logged and swallowed — the
  corpus entry and the beat run are unaffected.
- **Read:** `query_hfl_entries(query, since, until, tags, source, limit)`
  → `get_index_data` (Query DSL). Returns `[]` on any failure.
- **Index name:** env `HFL_ES_INDEX` (default `harqis-hfl-entries`).
  Reuses the existing `ELASTIC_LOGGING` app config — no new credentials.
- **Retrieval (MCP):** `memory_recall_es` in `workflows/hfl/mcp.py` reads
  this index by window/query/tags/source (optional Haiku synthesis;
  `found=false` + no LLM on empty). The corpus-based `memory_recall`
  is unchanged and still serves the Markdown tiers.

> Status: `capture`, `ingest_git`, `ingest_ai`, `analyze_media`, and
> `summarize` now dual-write via the shared `append_entry` helper in
> `capture.py` (`append_entry` → corpus write + `index_hfl_entry`,
> returning `(bytes, doc_id)`). `ingest_browsing` and `ingest_location`
> dual-write the same way. **`ingest_chatgpt` is the one remaining gap** — it still uses the
> bare `_render_entry`+write path and is not yet ES-indexed; routing it
> through `append_entry` is the clean follow-up.

### Auto-express from `manifesto.hfl_express` (signal buffer)

A second capture source feeds this same index — not from a dedicated ingest
task, but from **any** scheduled task that opts in via its manifesto block.
A `task_success` handler (`workflows/hfl/express_signals.py`) watches for tasks
whose manifesto declares `hfl_express: 'buffer'` and appends one cheap, no-LLM
**signal** to a staging index `harqis-hfl-signals` (`workflows/hfl/signal_store.py`)
on each successful run. A daily `rollup_hfl_signals` task (planned — Phase 2)
groups the day's signals by source and distills them into proper entries via the
same `index_hfl_entry` funnel, so the corpus stays story-grained.

Self-expressing ingestors (everything above) set `hfl_express: 'self'` or omit
it, so the hook skips them — no double-write. Design + phasing:
[`docs/thesis/HFL-AUTO-EXPRESS.md`](../../docs/thesis/HFL-AUTO-EXPRESS.md).

### On-demand archive ingest (`/time-capsule-synthesizer`)

A retrospective, time-ranged complement to the recurring ingest sources above.
Point it at a directory and a flexible period — `May 2020`, `August 1, 2002`,
`June-July 2019`, `2019-06-01..2019-07-31`, `since 2020-01-01`, `last 90 days` —
and it sweeps the whole tree (by file `mtime`) for that window, ingests every
file's content, and synthesizes **one** "time capsule" rollup entry (the notable
events, actions, reminders, and artifacts of the period) with the contributing
files as `references`.

It's a **hybrid** (`workflows/hfl/tasks/time_capsule.py` + the skill):

1. **COLLECT** (`run_collect` / the `collect_time_capsule` task) — walks the tree
   via `workflows/dumps/files.iter_recent_files`, classifies each file, and
   extracts a bounded representation: a head snippet for text/logs/code; a short
   **Haiku** vision caption for images + sampled video frames (reuses
   `analyze_media`'s encoders); extracted text for documents. Writes
   `logs/time-capsule/<slug>.{manifest.json,digest.md}` and prints the digest.
2. **ENRICH** — cross-references the same window against already-captured signal:
   existing HFL entries (`es_store.query_hfl_entries`) and live `apps/` integration
   data (e.g. `ingest_git.collect_github_activity`) so the rollup builds on — and
   de-duplicates against — what the corpus already holds. Best-effort; `--no-enrich`
   skips it.
3. **SYNTHESIZE** — Claude reads the digest (+ enrichment) and composes the rollup
   fields (grounded in the files/signal; no invention), writing them to
   `<slug>.synthesis.json`.
4. **WRITE** (`run_write`) — dual-writes the entry through `capture.append_entry`
   (corpus + the `harqis-hfl-entries` ES index, `source="time-capsule"`).

- **Default root** is `/Volumes/harqis-data` (the harqis-server data volume, per
  `machines.local.toml`). The skill must run on a host where `--root` is mounted
  (harqis-server for the default); it reports `root-unreachable` otherwise, with a
  dispatch fallback for advanced cross-host use.
- **One rollup per run** (not per file/day); empty window → no entry, no LLM call.
- **Document parsers are optional** (`pypdf`, `python-docx`, `openpyxl`,
  `python-pptx` in `requirements.txt`). A missing parser, or missing `cv2`, or an
  unreadable file → that file degrades to metadata-only; the sweep never crashes.
- **Audio is metadata-only for now** — no transcriber is wired. Audio files are
  recorded (name, mtime, size) but not transcribed; choosing a transcriber
  (e.g. faster-whisper, or a cloud STT) is the clean follow-up.
- Cost is Haiku-only and bounded by `--max-files` / `--max-caption-files` /
  `--no-caption`.

## Adding a new ingest source

Run `/create-new-ingest-source-hfl <source_name> [<spec_or_url>]
[--app <name>] [--schedule "<cron>"] [--window-days N] [--no-mcp]`. It
scaffolds the task (the `ingest_chatgpt` template), prompt, `__init__`
registration, `tasks_config` beat entry, tests, and a paired read-only
MCP live-view tool — dual-writing corpus + ES. It composes with
`/create-new-service-app` for a missing source API and never uses
`/create-new-workflow`.

---

## Manifesto alignment

| Task | code_role | para_bucket | express_target | review_artifact | hfl_signal |
| --- | --- | --- | --- | --- | --- |
| `capture_hfl_entry` | capture | area | `file:hfl_corpus` | `es_log+file` | `True` |
| `retrieve_hfl_corpus` | distill+express | area | `es_log` | `es_log` | `True` |
| `summarize_hfl_week` | distill+express | area | `file:hfl_summary+es_log` | `es_log+file` | `True` |
| `ingest_browsing_activity` | capture+distill+express | area | `file:hfl_corpus+es:hfl-entries` | `es_log+file` | `True` |
| `ingest_location_activity` | capture+distill+express | area | `file:hfl_corpus+es:hfl-entries` | `es_log+file` | `True` |
| `ingest_spotify_activity` | capture+distill+express | area | `file:hfl_corpus+es:hfl-entries` | `es_log+file` | `True` (`tenant_safe`) |
| `ingest_plaud_activity` | capture+distill+express | area | `file:hfl_corpus+es:hfl-entries` | `es_log+file` | `True` (`tenant_safe`) |
| `ingest_radar_activity` | capture+distill+express | area | `file:hfl_corpus+es:hfl-entries` | `es_log+file` | `True` |

This block is also persisted on each beat entry's `'manifesto'` key — see
`workflows/hfl/tasks_config.py`. `scripts/agents/repo-quality/manifesto_audit.py` reads from
there.

---

## Related

- [`docs/MANIFESTO.md`](../../docs/MANIFESTO.md) §Homework for Life
- [`docs/thesis/MANIFESTO-REPO-UPDATES.md`](../../docs/thesis/MANIFESTO-REPO-UPDATES.md) §3.3, §4.4
- [`workflows/knowledge/`](../knowledge/README.md) — RAG path the corpus
  joins once it has mass
- `/create-new-ingest-source-hfl` —
  [`.claude/skills/create-new-ingest-source-hfl/SKILL.md`](../../.claude/skills/create-new-ingest-source-hfl/SKILL.md)
  scaffolds new dual-writing ingest sources
