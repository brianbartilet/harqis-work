"""
Beat schedule for the agents/projects integrations.

Currently one task: `gtasks_kanban_sync` — runs every 2 minutes, drains the
configured 'Agents Tasks' Google Tasks list into the kanban board and reflects
status back. See `workflows/projects/tasks/gtasks_sync.py` for behaviour.

Cost guard: pin Haiku 4.5 via `kwargs.model`. Per the project convention,
do not raise the Anthropic SDK default — pass the model from here.
"""

from celery.schedules import timedelta

from workflows.queues import WorkflowQueue


WORKFLOW_PROJECTS = {

    'run-job--gtasks_kanban_sync': {
        'task': 'workflows.projects.tasks.gtasks_sync.gtasks_kanban_sync',
        # Every 2 minutes — matches the kanban orchestrator's poll cadence so
        # status sync feels prompt without burning Anthropic / Google quota.
        'schedule': timedelta(minutes=2),
        'kwargs': {
            'accounts_env': 'GTASKS_AGENTS_ACCOUNTS',
            'list_name_env': 'GTASKS_AGENTS_LIST',
            'board_id_env': 'KANBAN_BOARD_ID',
            'cfg_id__anthropic': 'ANTHROPIC',
            'model': 'claude-haiku-4-5-20251001',
            'enrich': True,
            'state_path': '.run/gtasks_bindings.json',
        },
        'options': {
            'queue': WorkflowQueue.AGENT,
            # Skip if a previous run is still pending — avoids piling up
            # redundant cycles when one cycle takes longer than 2 min.
            'expires': 60 * 2,
        },
    },

}
