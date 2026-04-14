# [Workflow Name]

## Description

- Brief description of what this workflow does and what it automates.
- List the apps/services it depends on.

## Directory Structure

```
workflows/<workflow_name>/
├── tasks_config.py             # Celery Beat schedule dict (WORKFLOW_<NAME>)
├── tasks/
│   ├── __init__.py
│   └── <task_module>.py        # @SPROUT.task decorated functions
├── dto/
│   └── __init__.py             # Task parameter DTOs
└── tests/
    └── test_<feature>.py
```

## Tasks

| Task Function | Schedule | Queue | Description |
|---------------|----------|-------|-------------|
| `example_task` | every 10s | default | Does something useful |

## Registering in `workflows/config.py`

To activate this workflow's tasks in the Celery Beat schedule, import and merge in `workflows/config.py`:

```python
from workflows.<workflow_name>.tasks_config import WORKFLOW_<NAME>

CONFIG_DICTIONARY = ... | WORKFLOW_<NAME>
```

## Task Pattern

```python
from core.apps.sprout.app.celery import SPROUT


def example_task(**kwargs):
    """Short description of what this task does."""
    # implementation
    return result
```

With decorators for logging and HUD display:

```python
from core.apps.sprout.decorators import log_result, feed, init_meter


@log_result()
@init_meter(meter_name='WIDGET_NAME', skin='HARQIS_DESKTOP')
@feed()
def example_task(**kwargs):
    ...
```

## `tasks_config.py` Pattern

```python
from celery.schedules import crontab
from datetime import timedelta

WORKFLOW_<NAME> = {
    'run-job--example_task': {
        'task': 'workflows.<workflow_name>.tasks.<module>.example_task',
        'schedule': timedelta(seconds=10),
        'args': [],
        'kwargs': {}
    },
}
```

## Tests

```sh
pytest workflows/<workflow_name>/tests/
```

> Workflow tests are excluded from the default `pytest` run — must be run explicitly.

## Notes

- Tasks are registered in `workflows/config.py` to be picked up by Celery Beat.
- Queue routing is defined in `SPROUT.conf.task_routes` in `workflows/config.py`.
- Copy this template to start a new workflow: `cp -r workflows/.template workflows/<new_name>`
