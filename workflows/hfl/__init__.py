# HFL (Homework for Life) — manifesto-first-class data source.
# See workflows/hfl/README.md and docs/MANIFESTO.md §Homework for Life.
#
# Tasks are imported so Celery autodiscovery picks them up when (and only when)
# this workflow is registered in workflows/config.py. The scaffold ships
# inactive on purpose — activation is a deliberate flip once the corpus path
# and prompts are tuned.
import workflows.hfl.tasks.capture        # noqa: F401
import workflows.hfl.tasks.retrieve       # noqa: F401
import workflows.hfl.tasks.summarize      # noqa: F401
