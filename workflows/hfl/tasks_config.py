"""
Beat schedule for the Homework-for-Life workflow.

Four tasks:
  - capture_hfl_entry    : adhoc — invoked manually or from an LLM/agent to
                           persist one daily story moment to the corpus.
  - analyze_hfl_media    : daily — vision pass over recent dumps-inbox
                           images/videos; appends one corpus entry per
                           story-worthy item (Haiku).
  - summarize_hfl_week   : weekly rollup of the past 7 days of entries (Haiku).
  - retrieve_hfl_corpus  : retrieval API — wired here as an ADHOC slot so it
                           can be invoked via .delay() / MCP; the schedule is
                           Sunday once-a-week (effectively disabled).

This workflow is scaffolded but NOT imported in `workflows/config.py`.
Activation is a deliberate flip — see workflows/hfl/README.md §Activation.
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
            'queue': WorkflowQueue.ADHOC,
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
            'queue': WorkflowQueue.AGENT,
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
            'queue': WorkflowQueue.AGENT,
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
            'queue': WorkflowQueue.ADHOC,
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

}
