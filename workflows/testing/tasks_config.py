"""
workflows/testing/tasks_config.py

Celery beat schedule entries for the ``testing`` workflow category.

``run_test_farm`` is ACTIVE: it runs once a week, Mondays at 10:00. ``board_id``
reuses the same rapidView id as ``run-job--show_jira_board`` in
``workflows/hud/tasks_config.py``. Generation bills the Anthropic API
(``ANTHROPIC_API_KEY``) — the task is unattended, so it must not use the
interactive-only Claude Max subscription. Pinned to the ``peon`` queue + windows
(``windows-work-all``) to keep delivery on a single host alongside the report.

``send_test_farm_report`` is the delivery half: it runs Mondays at 10:30
(after the 10:00 generation), renders the just-refreshed
``logs/BDD-TEST-FARM.md`` and emails it (``GOOGLE_GMAIL_SEND``) + posts a
Telegram notice. It runs ``--skip-generate`` so it never re-generates — same
``peon`` / windows host so it reads the markdown that host just produced and
shares the Gmail/Telegram configs.
"""
from celery.schedules import crontab

from workflows.queues import WorkflowQueue

WORKFLOW_TESTING = {

    # ── run_test_farm ─────────────────────────────────────────────────────────
    # BDD "test case farm": Mondays at 10:00, pull active-sprint Bug/Story
    # tickets from the Jira board (the same board hud_jira reads) and generate
    # Gherkin scenarios via the Anthropic API (Sonnet, ANTHROPIC_API_KEY) for any
    # new/changed ticket — one ticket at a time with a rate-limit pause — then
    # rewrite logs/BDD-TEST-FARM.md.
    #
    # `expires`: 8 hours — a missed 10:00 run can still fire later the same day;
    # after that the next Monday tick refreshes anyway.
    'run-job--run_test_farm': {
        'task': 'workflows.testing.tasks.test_farm.run_test_farm',
        'schedule': crontab(hour=10, minute=0, day_of_week='mon'),
        'kwargs': {
            'cfg_id__jira': 'JIRA',
            'board_id': 1790,             # reuse the hud_jira rapidView id
            'model': 'claude-sonnet-4-6', # cost/quality sweet spot for a batch
            'max_tokens': 4000,           # output cap per ticket (bounds API spend)
            'inter_ticket_delay': 5,      # seconds between consecutive generations
            # 'force': False,                 # set True to ignore the change cache
        },
        'options': {
            'queue': WorkflowQueue.PEON,
            'os': ['windows'],
            'expires': 60 * 60 * 8,       # 8 hours
        },
        'manifesto': {
            'code_role': 'capture+distill',
            'para_bucket': 'area',
            'express_target': 'file:logs/BDD-TEST-FARM.md',
            'review_artifact': 'es_log+markdown',
            'hfl_signal': False,
        },
    },

    # ── send_test_farm_report ─────────────────────────────────────────────────
    # Delivery half of the farm: Mondays at 10:30 (30 min after run_test_farm),
    # render the just-refreshed logs/BDD-TEST-FARM.md to HTML, email it via
    # GOOGLE_GMAIL_SEND and post a Telegram completion notice. Shells out to
    # scripts/agents/testing/daily_test_farm_email.py with --skip-generate, so it reuses
    # the 10:00 markdown and never triggers a second generation pass.
    #
    # Same peon/windows pin as run_test_farm so it reads the markdown that host
    # produced and shares the Gmail/Telegram configs.
    #
    # `expires`: 8 hours — a missed 10:30 run can still deliver later in the day.
    'run-job--send_test_farm_report': {
        'task': 'workflows.testing.tasks.test_farm_email.send_test_farm_report',
        'schedule': crontab(hour=10, minute=30, day_of_week='mon'),
        'kwargs': {
            'skip_generate': True,        # reuse the 09:00 markdown — no re-generation
        },
        'options': {
            'queue': WorkflowQueue.PEON,
            'os': ['windows'],
            'expires': 60 * 60 * 8,       # 8 hours
        },
        'manifesto': {
            'code_role': 'express',
            'para_bucket': 'area',
            'express_target': 'email:GOOGLE_GMAIL_SEND+telegram:TELEGRAM',
            'review_artifact': 'es_log+email_html',
            'hfl_signal': False,
        },
    },

}
