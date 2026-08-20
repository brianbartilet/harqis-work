"""
workflows/testing/tasks_config.py

Celery beat schedule entries for the ``testing`` workflow category.

``run_test_farm`` is DISABLED in Celery Beat while schedule ownership moves to
Hermes. The canonical Celery task remains registered for Hermes or manual
dispatch to the ``peon`` queue on Windows. The commented block below preserves
the former Monday 10:00 settings as the migration reference and prevents a
duplicate Beat run.

``send_test_farm_report`` is the independently scheduled delivery half: it
runs Mondays at 10:30, renders the latest ``logs/BDD-TEST-FARM.md``, emails it
(``GOOGLE_GMAIL_SEND``), and posts a Telegram notice. It runs
``--skip-generate`` so it never re-generates. The Hermes generation job should
finish before this task to avoid delivering stale output.
"""
from celery.schedules import crontab

from workflows.queues import WorkflowQueue

WORKFLOW_TESTING = {

    # ── run_test_farm ─────────────────────────────────────────────────────────
    # DISABLED — schedule ownership is moving to Hermes. Keep this block
    # line-commented so Celery Beat cannot duplicate the Hermes-triggered run.
    # The canonical task remains registered and callable on the PEON queue.
    # Former schedule: Mondays at 10:00; pull active-sprint Bug/Story
    # tickets from the Jira board (the same board hud_jira reads) and generate
    # Gherkin scenarios via the Anthropic API (Sonnet, ANTHROPIC_API_KEY) for any
    # new/changed ticket — one ticket at a time with a rate-limit pause — then
    # rewrite logs/BDD-TEST-FARM.md.
    #
    # `expires`: 8 hours — a missed 10:00 run can still fire later the same day;
    # after that the next Monday tick refreshes anyway.
    # 'run-job--run_test_farm': {
    #     'task': 'workflows.testing.tasks.test_farm.run_test_farm',
    #     'schedule': crontab(hour=10, minute=0, day_of_week='mon'),
    #     'kwargs': {
    #         'cfg_id__jira': 'JIRA',
    #         'board_id': 1790,             # reuse the hud_jira rapidView id
    #         'model': 'claude-sonnet-4-6', # cost/quality sweet spot for a batch
    #         'max_tokens': 4000,           # output cap per ticket (bounds API spend)
    #         'inter_ticket_delay': 5,      # seconds between consecutive generations
    #         'force': False,               # set True to ignore the change cache
    #     },
    #     'options': {
    #         'queue': WorkflowQueue.PEON,
    #         'os': ['windows'],
    #         'expires': 60 * 60 * 8,       # 8 hours
    #     },
    #     'manifesto': {
    #         'code_role': 'capture+distill',
    #         'para_bucket': 'area',
    #         'express_target': 'file:logs/BDD-TEST-FARM.md',
    #         'review_artifact': 'es_log+markdown',
    #         'hfl_signal': False,
    #     },
    # },

    # ── send_test_farm_report ─────────────────────────────────────────────────
    # Delivery half of the farm: Mondays at 10:30. While the generation schedule
    # migrates to Hermes, this independently scheduled task delivers the latest
    # available logs/BDD-TEST-FARM.md; Hermes should finish generation first.
    # Render the markdown to HTML, email it via
    # GOOGLE_GMAIL_SEND and post a Telegram completion notice. Shells out to
    # scripts/agents/testing/daily_test_farm_email.py with --skip-generate, so it reuses
    # the latest markdown and never triggers a second generation pass.
    #
    # Same peon/windows pin as run_test_farm so it reads the markdown that host
    # produced and shares the Gmail/Telegram configs.
    #
    # `expires`: 8 hours — a missed 10:30 run can still deliver later in the day.
    'run-job--send_test_farm_report': {
        'task': 'workflows.testing.tasks.test_farm_email.send_test_farm_report',
        'schedule': crontab(hour=10, minute=30, day_of_week='mon'),
        'kwargs': {
            'skip_generate': True,        # reuse existing markdown — no re-generation
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
