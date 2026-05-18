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
  - retrieve_hfl_corpus  : retrieval API — wired here as an ADHOC slot so it
                           can be invoked via .delay() / MCP; the schedule is
                           Sunday once-a-week (effectively disabled).

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

    # Retrieval — ADHOC. Schedule disabled (Sunday 03:34); real callers invoke
    # via .delay() or MCP tool.
    'run-job--retrieve_hfl_corpus': {
        'task': 'workflows.hfl.tasks.retrieve.retrieve_hfl_corpus',
        'schedule': crontab(day_of_week='sun', hour=3, minute=34),
        'kwargs': {
            'query': '',
            'k': 8,
            'since': None,
        },
        'options': {
            'queue': WorkflowQueue.HFL,
            'expires': 60 * 60,
        },
        'manifesto': {
            'code_role': 'distill+express',
            'para_bucket': 'area',
            'express_target': 'es_log',
            'review_artifact': 'es_log',
            'hfl_signal': True,
        },
    },

    # Daily browsing digest — 23:00 local, same slot as the other ingest
    # sources. Reads the Chrome + Edge `History` SQLite DBs on the Windows
    # worker (no credential — local file access), distils the day's browsing
    # into ONE entry (Haiku) and dual-writes corpus + ES. No history DB / no
    # visits → clean no-op (no LLM). Ships ACTIVE: nothing to configure, the
    # source is always present on the operator's machine. `os: windows`
    # because the History DBs live there. No domain filtering by default —
    # pass `exclude_domains` to redact specific hosts.
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
            'queue': WorkflowQueue.HFL,
            'os': ['windows'],
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


}
