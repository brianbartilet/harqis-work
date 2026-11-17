"""
Beat schedule for the Homework-for-Life workflow.

Tasks:
  - capture_hfl_entry    : adhoc — invoked manually or from an LLM/agent to
                           persist one daily story moment to the corpus.
  - analyze_hfl_media    : daily — vision pass over recent dumps-inbox
                           images/videos; appends one corpus entry per
                            story-worthy item (Haiku).
  - ingest_git_activity  : daily — distils the day's GitHub commits across
                           recently-updated repos into one corpus entry
                           (Haiku, raw fallback).
  - ingest_notes_activity: daily — turns each changed note into a bounded,
                           tagged corpus entry after the host pull.
  - ingest_trello_activity: daily — captures one provenance-linked HFL entry
                            per authored Trello action.
  - ingest_echomtg_inventory_activity: daily — diffs the complete EchoMTG
                            collection against its last successful snapshot.
  - summarize_hfl_week   : weekly rollup of the past 7 days of entries (Haiku).
  - retrieve_hfl_corpus  : on-demand retrieval API; weekly email digest disabled.
                           Pass email_to=None for programmatic recall without mail.
  - ingest_*             : scheduled source-specific capture and distillation.
  - flush_hfl_outbox     : every five minutes on hfl_broadcast; retries durable
                           envelopes from every participating worker.
  - check_activity_corpus_sources: weekly — failure-only source/task/corpus/ES
                           health snapshot; daily adaptive scan is Hermes-owned.

This workflow is active — `WORKFLOW_HFL` is merged into
`workflows/config.py`'s beat schedule.
"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from celery.schedules import crontab

from workflows.queues import WorkflowQueue


def persona_audit_now():
    return datetime.now(ZoneInfo("Asia/Singapore"))


WORKFLOW_HFL = {
    'run-job--reconcile_fleet_observations': {
        'task': 'workflows.hfl.tasks.fleet_observations.reconcile_fleet_observations',
        'schedule': crontab(minute='*/5'), 'kwargs': {},
        'options': {'queue': WorkflowQueue.HOST, 'expires': 300},
        'manifesto': {'code_role': 'capture+organize+express', 'para_bucket': 'area',
                      'express_target': 'hfl:agents-activity', 'review_artifact': 'es_log+fleet_receipts', 'hfl_signal': True},
    },
    # Approved owner workflow: Beat is the sole recurring initiator.
    'run-job--sync_github_pull_requests': {
        'task': 'workflows.hfl.tasks.github_updates.sync_github_pull_requests',
        'schedule': crontab(minute='*/15'),
        'kwargs': {},
        'options': {'queue': WorkflowQueue.HOST, 'expires': 900},
        'manifesto': {
            'code_role': 'capture+organize+express', 'para_bucket': 'area',
            'express_target': 'file:hfl_corpus+es:hfl-entries+api:hfl-actions',
            'review_artifact': 'es_log+github_update_prs+timeline_history',
            'hfl_signal': True,
        },
    },
    'run-job--persona_audit': {
        'task': 'workflows.hfl.tasks.persona_audit.persona_audit',
        'schedule': crontab(day_of_week=os.getenv('HFL_PERSONA_AUDIT_DAY', 'sun'),
                            hour=os.getenv('HFL_PERSONA_AUDIT_HOUR', '9'),
                            minute=os.getenv('HFL_PERSONA_AUDIT_MINUTE', '0'), nowfun=persona_audit_now),
        'kwargs': {},
        'options': {'queue': WorkflowQueue.HOST, 'expires': 86400},
        'manifesto': {'code_role': 'distill+express', 'para_bucket': 'area',
                      'express_target': 'hfl:persona-audit', 'review_artifact': 'es_log+hfl+persona_journal', 'hfl_signal': True},
    },
    # Canonical host only. Previous Singapore day; browsing never invokes this.
    'run-job--generate_timeline_suggestions': {
        'task': 'workflows.hfl.tasks.timeline_suggestions.generate_timeline_suggestions',
        'schedule': crontab(hour=4, minute=15),
        'kwargs': {},
        'options': {'queue': WorkflowQueue.HOST, 'expires': 60 * 60 * 12},
        'manifesto': {
            'code_role': 'distill+express', 'para_bucket': 'area',
            'express_target': 'api:hfl-timeline', 'review_artifact': 'es_log+timeline_cache',
            'hfl_signal': False, 'tenant_safe': True,
        },
    },
    # HFL Activity Radar — Beat scheduling is disabled because the Hermes agent
    # owns the waking-hours schedule. Hermes dispatches this canonical Celery
    # task so marker, suppression, Telegram, and Elasticsearch behavior remain
    # in harqis-work.
    # 'run-job--activity_radar': {
    #     'task': 'workflows.hfl.tasks.activity_radar.activity_radar',
    #     'schedule': crontab(hour='8,10,12,14,16,18,20,22', minute=0),
    #     'kwargs': {
    #         'cfg_id__anthropic': 'ANTHROPIC',
    #         'model': 'claude-haiku-4-5-20251001',
    #         'retrospective_days': 90,
    #     },
    #     'options': {
    #         'queue': WorkflowQueue.HFL,
    #         'expires': 60 * 90,
    #     },
    #     'manifesto': {
    #         'code_role': 'distill+express',
    #         'para_bucket': 'area',
    #         'express_target': 'telegram+es_log',
    #         'review_artifact': 'es_log+telegram',
    #         'hfl_signal': False,
    #         'tenant_safe': True,
    #     },
    # },

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

    # Bounded vision spend, with overlapping recovery for prior capped runs.
    'run-job--analyze_desktop_capture': {
        'task': 'workflows.hfl.tasks.analyze_desktop_capture.analyze_desktop_capture',
        'schedule': crontab(hour=22, minute=0),
        'kwargs': {
            'cfg_id__anthropic': 'ANTHROPIC',
            'model': 'claude-haiku-4-5-20251001',
            'window_days': 7,
            'max_files': 200,
            'frames_per_video': 4,
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

    # Independent of vision success: alert even when the analyzer never ran.
    'run-job--monitor_pending_captures': {
        'task': 'workflows.hfl.tasks.monitor_pending_captures.monitor_pending_captures',
        'schedule': crontab(hour='6', minute='30'),
        'kwargs': {'window_days': 14, 'warning_threshold': 25, 'critical_threshold': 100},
        'options': {'queue': WorkflowQueue.HFL, 'expires': 60 * 60 * 12},
        'manifesto': {
            'code_role': 'capture+express',
            'para_bucket': 'area',
            'express_target': 'telegram+es_log',
            'review_artifact': 'es_log',
            'hfl_signal': False,
        },
    },

    # Daily Android durable-media vision pass. This is distinct from the
    # privacy-reduced android_media attention-log ingest at 23:15.
    'run-job--analyze_android_capture': {
        'task': 'workflows.hfl.tasks.analyze_android_capture.analyze_android_capture',
        'schedule': crontab(hour=22, minute=5),
        'kwargs': {
            'cfg_id__anthropic': 'ANTHROPIC',
            'model': 'claude-haiku-4-5-20251001',
            'window_days': 1,
            'max_files': 10,
            'frames_per_video': 4,
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

    # EchoMTG collection delta — snapshots the complete EchoMTG inventory at
    # 22:55. First activation records a baseline only; subsequent runs compare
    # stable inventory ids and dual-write one added/removed-card daily rollup.
    'run-job--ingest_echomtg_inventory_activity': {
        'task': 'workflows.hfl.tasks.ingest_purchase_transactions.ingest_echomtg_inventory_activity',
        'schedule': crontab(hour=22, minute=55),
        'kwargs': {
            'cfg_id__echo_mtg': 'ECHO_MTG',
            'cfg_id__anthropic': 'ANTHROPIC',
            'model': 'claude-haiku-4-5-20251001',
            'page_size': 1000,
            'max_cards': 20000,
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

    # Purchase transaction review — purchase tasks buffer compact structured
    # outcomes immediately after success. This 23:00 rollup omits no-change
    # runs, distils meaningful mutations/anomalies plus Scryfall provenance,
    # and dual-writes one daily entry. Historical ES/radar-CSV backfill is an
    # explicit ad-hoc task, not part of Beat.
    'run-job--ingest_purchase_transactions_activity': {
        'task': 'workflows.hfl.tasks.ingest_purchase_transactions.ingest_purchase_transactions_activity',
        'schedule': crontab(hour=23, minute=0),
        'kwargs': {
            'cfg_id__anthropic': 'ANTHROPIC',
            'model': 'claude-haiku-4-5-20251001',
            'window_days': 1,
            'max_events': 500,
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

    # Repository notes — 22:50 local, ten minutes after the host's clean,
    # fast-forward-only pull. The first successful run records HEAD as the
    # baseline; later runs create one entry per text note/common image up to
    # the configured repository cap, with one overflow/reference summary.
    'run-job--ingest_notes_activity': {
        'task': 'workflows.hfl.tasks.ingest_notes.ingest_notes_activity',
        'schedule': crontab(hour=22, minute=50),
        'kwargs': {
            'repository_names': ['notes'],
            'cfg_id__anthropic': 'ANTHROPIC',
            'model': 'claude-haiku-4-5-20251001',
            'synthesize': True,
            'pull_max_age_minutes': 90,
        },
        'options': {
            'queue': WorkflowQueue.HFL,
            'expires': 60 * 60,
        },
        'manifesto': {
            'code_role': 'capture+distill+express',
            'para_bucket': 'area',
            'express_target': 'file:hfl_corpus',
            'review_artifact': 'es_log+file',
            'hfl_signal': True,
        },
    },

    # Weekly AI rollup disabled at owner request, alongside the
    # retrieval email digest below. On-demand summarize_hfl_week remains
    # available; no automatic retry or historical backfill is requested.

    # Weekly retrieval email digest disabled at owner request. Keep this
    # schedule as a manual re-enable reference; on-demand retrieval remains
    # available (email_to=None means no mail). Uncomment to restore Sunday
    # 20:00 local delivery to HARQIS_OWNER_EMAIL via GOOGLE_GMAIL_SEND.
    # 'run-job--retrieve_hfl_corpus': {
    #     'task': 'workflows.hfl.tasks.retrieve.retrieve_hfl_corpus',
    #     'schedule': crontab(day_of_week='sun', hour=20, minute=0),
    #     'kwargs': {
    #         'query': '',
    #         'k': 50,
    #         'since': '-7d',
    #         'email_to': os.environ.get('HARQIS_OWNER_EMAIL', 'owner@example.com'),
    #         'cfg_id__gmail': 'GOOGLE_GMAIL_SEND',
    #     },
    #     'options': {
    #         'queue': WorkflowQueue.HFL,
    #         'expires': 60 * 60 * 23,
    #     },
    #     'manifesto': {
    #         'code_role': 'distill+express',
    #         'para_bucket': 'area',
    #         'express_target': 'es_log+email',
    #         'review_artifact': 'es_log',
    #         'hfl_signal': True,
    #     },
    # },

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
    # no stay-points become named route summaries when movement is meaningful;
    # only low-distance/noisy tracks use the movement-only breadcrumb.
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
    # cloud auth and no PLAUD_EXPORT_DIR → no entry, no network call; zero
    # recordings in the window → no entry, no LLM call.
    #
    # Active — cloud auth is PLAUD_EMAIL+PLAUD_PASSWORD (preferred — the
    # adapter mints/refreshes its own ~30-day token) or a manual PLAUD_TOKEN;
    # PLAUD_EXPORT_DIR is the export-folder fallback. All in .env/apps.env.
    # Whisper fallback needs OPENAI_API_KEY; archive needs PLAUD_ARCHIVE_PATH
    # (+ key-based SSH).
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

    # Weekly YouTube upload archive — Mondays at 06:00 local. Scans the previous
    # seven days for own uploads and
    # external-video playlist additions, downloads each video plus a curated
    # Markdown artifact beneath YOUTUBE_ARCHIVE_PATH, then writes one
    # retrospective HFL entry per event. Playlist events use their added-at
    # timestamp as the entry/archive date.
    # Active, but a clean no-op until YOUTUBE_ARCHIVE_PATH and YouTube OAuth are
    # configured. Manual calls may pass days=N or days='all'.
    'run-job--ingest_youtube_activity': {
        'task': 'workflows.hfl.tasks.ingest_youtube.ingest_youtube_activity',
        'schedule': crontab(day_of_week='monday', hour='6', minute='0'),
        'kwargs': {
            'cfg_id__anthropic': 'ANTHROPIC',
            'model': 'claude-haiku-4-5-20251001',
            'days': 7,
            'max_videos': 500,
            'max_playlists': 50,
            'max_playlist_items': 500,
            'synthesize': True,
        },
        # Dashboard-triggered runs use the same rolling weekly window as Beat.
        'manual_kwargs': {
            'days': 7,
        },
        'options': {
            'queue': WorkflowQueue.HFL,
            'expires': 60 * 60 * 24,
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

    # Daily Android screen activity — 23:15 local, one slot after Spotify (23:10).
    # Parses the hourly android_actions-YYYYMMDD_HH.log files written by the
    # Android capture agent (mobile/android/tasks/capture.py), classifies
    # foreground app sessions by category, and distils ONE "attention arc of the
    # day" entry (Haiku) — dual-written corpus + ES. Privacy-safe: OCR text is
    # never passed to the model or written to the corpus; only app categories
    # and session counts are surfaced.
    # Centralized single-device source on the Beat host (HFL queue).
    # Clean no-op until HFL_ANDROID_SCREEN_LOG_DIR is set and points to a dir
    # with log files. No directory → no entry, no I/O, no LLM call.
    'run-job--ingest_android_media_activity': {
        'task': 'workflows.hfl.tasks.ingest_android_media.ingest_android_media_activity',
        'schedule': crontab(hour=23, minute=15),
        'kwargs': {
            'cfg_id__anthropic': 'ANTHROPIC',
            'model': 'claude-haiku-4-5-20251001',
            'window_days': 1,
            'max_log_files': 24,
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

    # Daily DAILY RADAR digest — 23:20 local, after the other ingest sources.
    # Reads the day's DAILY RADAR HUD briefings back out of the shared desktop
    # feed file (<feed_dir>/hud-logs-YYYYMMDD.txt, the @feed() sink the radar
    # writes to) and distils them into ONE "what the day was about" entry
    # (Haiku) — dual-written corpus + ES, source "radar". It does NOT re-run
    # the radar (which pulls ~9 sources + Sonnet every few hours); it ingests
    # the briefings already produced. The feed file is Drive-synced, so the
    # Beat host reads briefings a Windows radar wrote. Centralized single
    # source on the Beat host (HFL queue, NOT a per-machine broadcast).
    # Active — clean no-op until there's signal: no feed dir configured on
    # this host (DESKTOP_PATH_FEED / DESKTOP_PATH_FEED_<OS>) → no entry, no
    # I/O; no radar briefings in the window → no entry, no LLM call.
    'run-job--ingest_radar_activity': {
        'task': 'workflows.hfl.tasks.ingest_radar.ingest_radar_activity',
        'schedule': crontab(hour=23, minute=20),
        'kwargs': {
            'cfg_id__anthropic': 'ANTHROPIC',
            'model': 'claude-haiku-4-5-20251001',
            'window_days': 1,
            'prefix': 'hud-logs',
            'max_briefings': 24,
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

    # Daily Trello activity — 23:25 local, after the 23:20 radar ingest and
    # before the 23:35 retained-session retry. Reads actions authored by the
    # authenticated member during the previous completed calendar day and
    # writes one idempotent HFL entry per meaningful action. Routine actions
    # are rendered deterministically; only long comments/unfamiliar action
    # types call Haiku. HFL_TRELLO_WORKSPACES optionally limits Workspace
    # IDs/slugs; empty means all Workspaces plus personal boards.
    'run-job--ingest_trello_activity': {
        'task': 'workflows.hfl.tasks.ingest_trello.ingest_trello_activity',
        'schedule': crontab(hour=23, minute=25),
        'kwargs': {
            'cfg_id__anthropic': 'ANTHROPIC',
            'model': 'claude-haiku-4-5-20251001',
            'window_days': 1,
            'page_size': 200,
            'max_actions': 10_000,
            'synthesize': True,
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

    # Durable delivery retry for distributed HFL producers. Every worker may
    # hold a local outbox, so this runs through the HFL broadcast exchange.
    # The canonical server persists its own retained entries directly; other
    # workers forward theirs to persist_hfl_entry on the direct hfl queue.
    'run-job--flush_hfl_outbox': {
        'task': 'workflows.hfl.tasks.persist.flush_hfl_outbox',
        'schedule': crontab(minute='*/5'),
        'kwargs': {'limit': 100},
        'options': {
            'queue': WorkflowQueue.HFL_BROADCAST,
            'expires': 60 * 4,
        },
        'manifesto': {
            'code_role': 'express',
            'para_bucket': 'resource',
            'express_target': 'file:hfl_corpus+es:hfl-entries',
            'review_artifact': 'es_log+file',
            'hfl_signal': False,
        },
    },
    # Retry retained prompt/outcome audit events on the canonical HFL worker.
    # Immediate hook delivery remains primary.
    'run-job--ingest_agent_session_events': {
        'task': 'workflows.hfl.tasks.ingest_agent_sessions.ingest_agent_session_events',
        'schedule': crontab(minute='*/10'),
        'kwargs': {
            'cfg_id__anthropic': 'ANTHROPIC',
            'model': 'claude-haiku-4-5-20251001',
            'window_days': 2,
            'max_events': 500,
        },
        'options': {
            'queue': WorkflowQueue.HFL,
            'expires': 60 * 9,
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

    # Daily cross-surface prompt audit rollup after the last ingest slot.
    'run-job--rollup_agent_sessions': {
        'task': 'workflows.hfl.tasks.ingest_agent_sessions.rollup_agent_sessions',
        'schedule': crontab(hour=23, minute=40),
        'kwargs': {
            'cfg_id__anthropic': 'ANTHROPIC',
            'model': 'claude-haiku-4-5-20251001',
            'max_events': 500,
        },
        'options': {
            'queue': WorkflowQueue.HFL,
            'expires': 60 * 60 * 12,
        },
        'manifesto': {
            'code_role': 'distill+express',
            'para_bucket': 'area',
            'express_target': 'file:hfl_corpus+es:hfl-entries',
            'review_artifact': 'es_log+file',
            'hfl_signal': True,
            'tenant_safe': True,
        },
    },

    # Weekly deterministic activity-corpus source audit. This is a separate
    # automation from the Hermes-owned daily adaptive skill invocation: Beat
    # owns this Monday snapshot, while the skill owns daily diagnosis/repair.
    'run-job--check_activity_corpus_sources': {
        'task': 'workflows.hfl.tasks.check_activity_corpus_sources.check_activity_corpus_sources',
        'schedule': crontab(day_of_week='monday', hour=7, minute=30),
        'kwargs': {
            'mode': 'weekly',
            'write_report': True,
            'save_to_hfl': True,
            'notify': True,
        },
        'options': {
            'queue': WorkflowQueue.HFL,
            'expires': 60 * 60 * 6,
        },
        'manifesto': {
            'code_role': 'distill+express',
            'para_bucket': 'area',
            'express_target': 'file:hfl_source_health+hfl_audit+telegram+es_log',
            'review_artifact': 'es_log+file+hfl+telegram',
            'hfl_signal': False,
            'tenant_safe': True,
        },
    },

    # Meta archive import is deliberately manual-only. First run
    # prepare_meta_archive_import on harqis-server, require a complete schema-v2
    # plan with zero parser failures and review all pins, then dispatch controlled
    # batches and call report/recover_meta_archive_import. Do not schedule them.
    #
    # 'run-job--prepare_meta_archive_import': {
    #     'task': 'workflows.hfl.tasks.ingest_meta_archive.prepare_meta_archive_import',
    #     'schedule': crontab(day_of_week='sun', hour=3, minute=47),
    #     'kwargs': {
    #         'platform': 'facebook',
    #         'archive_roots': [],
    #         'work_dir': '${HFL_META_WORK_DIR}',
    #         'max_events': 500000,
    #         'future_tolerance_hours': 24,
    #     },
    #     'options': {'queue': WorkflowQueue.HFL, 'expires': 60 * 60 * 12},
    #     'manifesto': {
    #         'code_role': 'capture+distill+express',
    #         'para_bucket': 'area',
    #         'express_target': 'file:activity-corpus+es:hfl-entries',
    #         'review_artifact': 'es_log+file',
    #         'hfl_signal': True,
    #     },
    # },

}
