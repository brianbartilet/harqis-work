"""Celery tasks for the agents/projects kanban orchestrator.

Currently exposes the gtasks ↔ kanban bridge sync task. See
`workflows/projects/tasks/gtasks_sync.py` and `tasks_config.py`.
"""

import workflows.projects.tasks.gtasks_sync  # noqa: F401  — registers @SPROUT.task
