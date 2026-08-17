"""Manual Facebook Meta-export thread-week ingestion into durable HFL."""

from typing import Any

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from workflows.hfl.tasks.ingest_meta_archive import ingest_meta_work_item


@SPROUT.task()
@log_result()
def ingest_facebook_activity(*, work_item_path: str, **kwargs: Any) -> dict:
    return ingest_meta_work_item(work_item_path=work_item_path, platform="facebook", **kwargs)
