"""
Configures the Celery app for scheduled tasks based on environment-specific settings.

This module initializes the Celery beat schedule using a configuration dictionary that maps task identifiers to their definitions. It dynamically selects the appropriate task mapping based on an environment variable, ensuring that tasks are scheduled according to environment-specific requirements. Additionally, it configures the Celery app to respect the timezone settings specified in the Django project settings, allowing for accurate scheduling of tasks across different timezones.

The configuration relies on external definitions for task mappings and environment variables to provide flexibility and modularity in defining task schedules.

References:
- Celery Periodic Tasks: https://docs.celeryproject.org/en/stable/userguide/periodic-tasks.html

Known Issues:
- Potential issues with Celery and Eventlet: https://github.com/eventlet/eventlet/issues/616
"""
from core.apps.sprout.app.celery import SPROUT
from core.apps.sprout.settings import TIME_ZONE, USE_TZ

from workflows.purchases.tasks_config import WORKFLOW_PURCHASES
from workflows.hud.tasks_config import WORKFLOWS_HUD
from workflows.desktop.tasks_config import WORKFLOWS_DESKTOP

# Set Celery to use the same timezone settings as the Django project.
SPROUT.conf.enable_utc = USE_TZ
SPROUT.conf.timezone = TIME_ZONE
SPROUT.conf.broker_connection_retry_on_startup = True
SPROUT.autodiscover_tasks(['workflows'])

# Configuration dictionary mapping environment variable values to specific task mappings.
# Be careful to use duplicate keys in the dictionary, as it will overwrite the previous key.
CONFIG_DICTIONARY = WORKFLOW_PURCHASES | WORKFLOWS_HUD | WORKFLOWS_DESKTOP

# Configure the Celery beat schedule based on the current environment's task mapping.
SPROUT.conf.beat_schedule = CONFIG_DICTIONARY

SPROUT.conf.task_routes = {
  "workflows.hud.tasks.*": {"queue": "hud"},
}