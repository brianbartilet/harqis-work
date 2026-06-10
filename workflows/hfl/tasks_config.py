"""
Beat schedule for the Homework-for-Life workflow.

Five tasks:
  - capture_hfl_entry    : adhoc — invoked manually or from an LLM/agent to
                           persist one daily story moment to the corpus.
  - analyze_hfl_media    : daily — vision pass over recent dumps-inbox
                           images/videos; appends one corpus entry per
                           story-worthy item (Haiku).
  - ingest_git_activity  : daily — distils the day's GitHub commits across
                           recently-updated repos into one corpus entry
                           (Haiku, raw fallback).
  - summarize_hfl_week   : weekly rollup of the past 7 days of entries (Haiku).
  - retrieve_hfl_corpus  : retrieval API + weekly digest. Beat fires Sundays
                           at 20:00 with email_to=brian.bartilet@gmail.com to
                           mail the past 7 days' raw entries (closes the
                           capture→ingest→retrieve loop). MCP / .delay()
                           callers can still invoke it with email_to=None for
                           pure programmatic recall.

This workflow is active — `WORKFLOW_HFL` is merged into
`workflows/config.py`'s beat schedule.
"""
from celery.schedules import crontab

from workflows.queues import WorkflowQueue


WORKFLOW_HFL = {

    # Adhoc capture — schedule is effectively disabled (Sunday 03:33). Real
    # invocation is via .delay() from an agent, an MCP tool, or a hotkey.
    'run-job--capture_hfl_entry': {
        'task': 'workflows.hfl.tasks.capture.capture_hfl_entry',
        'schedule': crontab(day_of_week='sun', hour=3, minute=33),
        'kwargs': {
            'moment': '',
            'what_happened': '',
            'why_it_stayed': '',
            'possible_use': '',
            'tags': [],
        },
        'options': {
            'queue': WorkflowQueue.HFL,
            'expires': 60 * 60,
        },
        'manifesto': {
            'code_role': 'capture',
            'para_bucket': 'area',
            'express_target': 'file:hfl_corpus',
            'review_artifact': 'es_log+file',
            'hfl_signal': True,
        },
    },

    # Daily vision pass — 22:00 local. Walks the last `window_days` of
    # dumps-inbox media and appends one HFL entry per story-worthy item.
    # AGENT queue (vision = LLM call); harqis-server consumes `agent` and
    # holds the inbox. Haiku only — cost-bounded by frame count + max_files.
    'run-job--analyze_hfl_media': {
        'task': 'workflows.hfl.tasks.analyze_media.analyze_hfl_media',
        'schedule': crontab(hour=22, minute=0),
        'kwargs': {
            'cfg_id__anthropic': 'ANTHROPIC',
            'model': 'claude-haiku-4-5-20251001',
            'window_days': 1,
            'max_files': 40,
            'frames_per_video': 4,
        },
        'options': {
            'queue': WorkflowQueue.HFL,
            'expires': 60 * 60 * 12,
        },
        'manifesto': {
            'code_role': 'capture+distill+express',
            'para_bucket': 'area',
            'express_target': 'file:hfl_corpus',
            'review_artifact': 'es_log+file',
            'hfl_signal': True,
        },
    },

    # Daily git activity — midnight 00:00 local (Beat runs only on
    # harqis-server, the canonical Beat host). window_days=1 means the
    # 00:00 run captures the day that just ended. Distils the day's GitHub
    # commits (recently-updated repos, bounded) into one corpus entry that
    # flows into summarize_hfl_week + the memory_recall MCP. AGENT queue
    # (Haiku); harqis-server consumes `agent` and holds the GitHub token.
    # Skipped entirely (no LLM, no entry) on a no-commit day.
    'run-job--ingest_git_activity': {
        'task': 'workflows.hfl.tasks.ingest_git.ingest_git_activity',
        'schedule': crontab(hour=0, minute=0),
        'kwargs': {
            'cfg_id__anthropic': 'ANTHROPIC',
            'model': 'claude-haiku-4-5-20251001',
            'window_days': 1,
            'max_repos': 30,
            'commits_per_repo': 50,
            'max_commits': 200,
        },
        'options': {
            'queue': WorkflowQueue.HFL,
            'expires': 60 * 60 * 12,
        },
        'manifesto': {
            'code_role': 'capture+distill+express',
            'para_bucket': 'area',
            'express_target': 'file:hfl_corpus',
            'review_artifact': 'es_log+file',
            'hfl_signal': True,
        },
    },

    # Weekly rollup — Sundays at 21:00 local, summarizes the past 7 days.
    'run-job--summarize_hfl_week': {
        'task': 'workflows.hfl.tasks.summarize.summarize_hfl_week',
        'schedule': crontab(day_of_week='sun', hour=21, minute=0),
        'kwargs': {
            'cfg_id__anthropic': 'ANTHROPIC',
            'model': 'claude-haiku-4-5-20251001',
            'window_days': 7,
        },
        'options': {
            'queue': WorkflowQueue.HFL,
            'expires': 60 * 60 * 12,
        },
        'manifesto': {
            'code_role': 'distill+express',
            'para_bucket': 'area',
            'express_target': 'file:hfl_summary+es_log',
            'review_artifact': 'es_log+file',
            'hfl_signal': True,
        },
    },

    # Retrieval — weekly Sunday digest at 20:00 local, one hour before
    # summarize_hfl_week. Mails the past 7 days of raw HFL entries to the
    # operator so the capture → ingest → retrieve → notify loop closes
    # automatically. MCP / .delay() callers can still hit this task with
    # email_to=None for pure programmatic recall (no mail). expires=23h so a
    # missed Sunday slot is dropped before the next week's tick lines up.
    'run-job--retrieve_hfl_corpus': {
        'task': 'workflows.hfl.tasks.retrieve.retrieve_hfl_corpus',
        'schedule': crontab(day_of_week='sun', hour=20, minute=0),
        'kwargs': {
            'query': '',
            'k': 50,
            'since': '-7d',
            'email_to': 'brian.bartilet@gmail.com',
            'cfg_id__gmail': 'GOOGLE_GMAIL_SEND',
        },
        'options': {
            'queue': WorkflowQueue.HFL,
            'expires': 60 * 60 * 23,
        },
        'manifesto': {
            'code_role': 'distill+express',
            'para_bucket': 'area',
            'express_target': 'es_log+email',
            'review_artifact': 'es_log',
            'hfl_signal': True,
        },
    },

    # Daily browsing digest — 23:00 local, same slot as the other ingest
    # sources. Reads the Chrome + Edge `History` SQLite DBs on the local
    # worker (no credential — local file access), distils the day's browsing
    # into ONE entry (Haiku) and dual-writes corpus + ES.
    #
    # Fanout via `hfl_broadcast`: every subscribed worker runs this at 23:00
    # against its own browser history, so each machine contributes one entry
    # per day. Workers with no history DB / no visits no-op cleanly (no LLM,
    # no entry). Each entry's ES doc id is deterministic on
    # (date, source="browsing", moment-hash) so two machines with distinct
    # browsing produce two docs; an unlikely identical moment-hash would
    # upsert, which is harmless. No domain filtering by default — pass
    # `exclude_domains` to redact specific hosts.
    'run-job--ingest_browsing_activity': {
        'task': 'workflows.hfl.tasks.ingest_browsing.ingest_browsing_activity',
        'schedule': crontab(hour=23, minute=0),
        'kwargs': {
            'cfg_id__anthropic': 'ANTHROPIC',
            'model': 'claude-haiku-4-5-20251001',
            'window_days': 1,
            'browsers': ('chrome', 'edge'),
            'max_visits': 600,
            'exclude_domains': (),
        },
        'options': {
            'queue': WorkflowQueue.HFL_BROADCAST,
            'expires': 60 * 60 * 12,
        },
        'manifesto': {
            'code_role': 'capture+distill+express',
            'para_bucket': 'area',
            'express_target': 'file:hfl_corpus+es:hfl-entries',
            'review_artifact': 'es_log+file',
            'hfl_signal': True,
        },
    },

    # Daily location timeline — 23:05 local. Pulls the day's GPS track from the
    # local OwnTracks Recorder (apps/own_tracks), clusters fixes into
    # reverse-geocoded stay-points (Nominatim, free), and distils ONE
    # "where I was today" timeline entry (Haiku) — dual-written corpus + ES.
    # HFL queue: the Recorder + device config live on harqis-server, the Beat
    # host; this is centralized, not a per-machine broadcast like browsing.
    # Active, clean no-op until OwnTracks reports: no device configured /
    # Recorder unreachable / no fixes → no LLM, no entry. Days with fixes but
    # no stay-points write a movement-only breadcrumb.
    # Device read from OWN_TRACKS_DEFAULT_USER / OWN_TRACKS_DEFAULT_DEVICE.
    'run-job--ingest_location_activity': {
        'task': 'workflows.hfl.tasks.ingest_location.ingest_location_activity',
        'schedule': crontab(hour=23, minute=5),
        'kwargs': {
            'cfg_id__anthropic': 'ANTHROPIC',
            'model': 'claude-haiku-4-5-20251001',
            'window_days': 1,
            'radius_m': 150,
            'min_dwell_min': 15,
            'max_gap_min': 90,
            'max_points': 5000,
        },
        'options': {
            'queue': WorkflowQueue.HFL,
            'expires': 60 * 60 * 12,
        },
        'manifesto': {
            'code_role': 'capture+distill+express',
            'para_bucket': 'area',
            'express_target': 'file:hfl_corpus+es:hfl-entries',
            'review_artifact': 'es_log+file',
            'hfl_signal': True,
        },
    },

    # Daily Spotify listening — 23:10 local, alongside browsing (23:00) and
    # location (23:05). Pulls the day's plays from the Spotify Web API
    # (apps/spotify), distils them into ONE "soundtrack of the day" entry
    # (Haiku, mood inferred — no audio-features) and dual-writes corpus + ES.
    # Centralized single-account source on the Beat host (HFL queue, NOT a
    # per-machine broadcast like browsing). recently-played caps at 50/day.
    # Clean no-op until credentials are set: no Spotify creds → no entry, no
    # network call; zero plays in the window → no entry, no LLM call.
    #
    # Active — clean no-op until SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET /
    # SPOTIFY_REFRESH_TOKEN are set in .env/apps.env (mint the refresh token
    # once; see apps/spotify/README.md).
    'run-job--ingest_spotify_activity': {
        'task': 'workflows.hfl.tasks.ingest_spotify.ingest_spotify_activity',
        'schedule': crontab(hour=23, minute=10),
        'kwargs': {
            'cfg_id__anthropic': 'ANTHROPIC',
            'model': 'claude-haiku-4-5-20251001',
            'window_days': 1,
            'max_tracks': 50,
            'top_limit': 10,
        },
        'options': {
            'queue': WorkflowQueue.HFL,
            'expires': 60 * 60 * 12,
        },
        'manifesto': {
            'code_role': 'capture+distill+express',
            'para_bucket': 'area',
            'express_target': 'file:hfl_corpus+es:hfl-entries',
            'review_artifact': 'es_log+file',
            'hfl_signal': True,
            'tenant_safe': True,
        },
    },

    # Daily Plaud voice recordings — 23:15 local, after spotify (23:10). Pulls
    # the day's recordings from the Plaud adapter (apps/plaud — cloud API
    # primary, local export-folder fallback), and writes ONE HFL entry PER
    # recording (not a daily digest) — dual-written corpus + ES, source "plaud".
    # Transcript precedence: Plaud's own transcript first; if absent, the audio
    # is transcribed with OpenAI Whisper (bounded by max_transcribe). Raw
    # recordings + a consolidated YYYY-MM-DD-summary.md are archived to
    # harqis-ones-mac-mini over SSH (PLAUD_ARCHIVE_PATH; skipped if unset).
    # Centralized single-account source on the Beat host (HFL queue, NOT a
    # per-machine broadcast). Clean no-op until acquisition is configured: no
    # PLAUD_TOKEN and no PLAUD_EXPORT_DIR → no entry, no network call; zero
    # recordings in the window → no entry, no LLM call.
    #
    # Active — clean no-op until PLAUD_TOKEN (cloud) or PLAUD_EXPORT_DIR
    # (export-folder fallback) is set in .env/apps.env. Whisper fallback needs
    # OPENAI_API_KEY; archive needs PLAUD_ARCHIVE_PATH (+ key-based SSH).
    'run-job--ingest_plaud_activity': {
        'task': 'workflows.hfl.tasks.ingest_plaud.ingest_plaud_activity',
        'schedule': crontab(hour=23, minute=15),
        'kwargs': {
            'cfg_id__anthropic': 'ANTHROPIC',
            'model': 'claude-haiku-4-5-20251001',
            'window_days': 1,
            'max_recordings': 50,
            'max_transcribe': 20,
            'whisper_model': 'whisper-1',
            'allow_whisper': True,
            'archive': True,
        },
        'options': {
            'queue': WorkflowQueue.HFL,
            'expires': 60 * 60 * 12,
        },
        'manifesto': {
            'code_role': 'capture+distill+express',
            'para_bucket': 'area',
            'express_target': 'file:hfl_corpus+es:hfl-entries',
            'review_artifact': 'es_log+file',
            'hfl_signal': True,
            'tenant_safe': True,
        },
    },

    # Android voice memo inbox — adhoc. The beat slot (Sunday 03:34) is
    # effectively disabled; real invocation is via ingest_voice_memos.delay()
    # from an agent or a Celery webhook triggered by the Termux voice_sender
    # helper (workflows/mobile/android/voice_sender.py). Scans the voice inbox
    # (VOICE_INBOX_PATH or logs/voice_inbox/) for JSON transcript payloads and
    # distils each into one corpus entry (Haiku, raw fallback). No inbox /
    # empty inbox -> clean no-op. Processed files are archived to
    # inbox/processed/. Raw transcript is never written to corpus or ES.
    # Active — clean no-op until a JSON transcript file appears in the inbox.
    'run-job--ingest_voice_memos': {
        'task': 'workflows.hfl.tasks.ingest_voice.ingest_voice_memos',
        'schedule': crontab(day_of_week='sun', hour=3, minute=34),
        'kwargs': {
            'cfg_id__anthropic': 'ANTHROPIC',
            'model': 'claude-haiku-4-5-20251001',
            'max_memos': 20,
        },
        'options': {
            'queue': WorkflowQueue.HFL,
            'expires': 60 * 60,
        },
        'manifesto': {
            'code_role': 'capture+distill+express',
            'para_bucket': 'area',
            'express_target': 'file:hfl_corpus+es:hfl-entries',
            'review_artifact': 'es_log+file',
            'hfl_signal': True,
        },
    },


}
