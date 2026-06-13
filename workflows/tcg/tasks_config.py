"""Beat schedule for the TCG workflow category.

Every task here is **manual-trigger only** (run via pytest —
``workflows/tcg/tests/test_pokedex_proxies.py`` — or ad hoc from the
dashboard), so the dictionary ships empty. Importing this module from
``workflows/config.py`` still registers the task modules with Celery
workers (via ``workflows/tcg/__init__.py``), which is what makes ad-hoc
triggering possible without scheduling anything.
"""

WORKFLOW_TCG = {

    # ── run_pokedex_proxy_pipeline ────────────────────────────────────────────
    # Manual only by design: the pipeline scrapes ~1025 dex entries, makes
    # ~1025 Pokemon TCG API calls, renders ~1025 card images, and (when
    # upload=True) drives a headed browser against the user's MPC account.
    # There is nothing to gain from a recurring schedule — printings data
    # changes a few times a year at most. Trigger via pytest or the dashboard.
    # Required kwargs: cfg_id__pokemon_tcg='POKEMON_TCG', cfg_id__mpc='MPC'
    #
    # 'run-job--pokedex-proxy-pipeline': {
    #     'task': 'workflows.tcg.tasks.pokedex_proxies.run_pokedex_proxy_pipeline',
    #     'schedule': crontab(minute=0, hour=4, day_of_month=1),   # if ever scheduled
    #     'kwargs': {
    #         'preview': True,           # safety: preview unless deliberately flipped
    #         'cfg_id__pokemon_tcg': 'POKEMON_TCG',
    #         'cfg_id__mpc': 'MPC',
    #     },
    #     'options': {
    #         'queue': WorkflowQueue.TCG,
    #         'expires': 60 * 60,
    #     },
    #     'manifesto': {
    #         'code_role': 'capture+express',
    #         'para_bucket': 'project',
    #         'express_target': 'file:proxy-card-images+api:makeplayingcards',
    #         'review_artifact': 'es_log+file',
    #         'hfl_signal': False,
    #     },
    # },

}
