# Mandatory explicit imports — SPROUT.autodiscover_tasks(['workflows']) only
# scans for top-level `tasks.py` per package; the `tasks/` subpackage isn't
# walked. Without these, the worker crashes at dispatch time with
# `Received unregistered task of type 'workflows.dumps.tasks.…'`.
import workflows.dumps.tasks.collect    # noqa: F401
import workflows.dumps.tasks.pull       # noqa: F401
import workflows.dumps.tasks.analyze    # noqa: F401
