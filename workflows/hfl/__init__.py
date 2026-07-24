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
import workflows.hfl.tasks.analyze_media  # noqa: F401
import workflows.hfl.tasks.ingest_git     # noqa: F401
import workflows.hfl.tasks.ingest_ai      # noqa: F401
import workflows.hfl.tasks.ingest_chatgpt  # noqa: F401
import workflows.hfl.tasks.ingest_browsing  # noqa: F401
import workflows.hfl.tasks.ingest_location  # noqa: F401
import workflows.hfl.tasks.ingest_spotify   # noqa: F401
import workflows.hfl.tasks.ingest_plaud     # noqa: F401
import workflows.hfl.tasks.ingest_youtube   # noqa: F401
import workflows.hfl.tasks.ingest_radar     # noqa: F401
import workflows.hfl.tasks.time_capsule    # noqa: F401
import workflows.hfl.tasks.ingest_android_media  # noqa: F401
import workflows.hfl.tasks.ingest_notes    # noqa: F401
import workflows.hfl.tasks.ingest_agent_sessions  # noqa: F401
import workflows.hfl.tasks.ingest_trello   # noqa: F401
import workflows.hfl.tasks.persist        # noqa: F401
