"""Celery boundary for canonical HFL persistence and outbox replay."""

from __future__ import annotations

from celery.exceptions import MaxRetriesExceededError

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from workflows.hfl.persistence import (
    EntryEnvelope,
    flush_outbox,
    is_canonical_machine,
    persist_envelope,
    save_to_outbox,
)


_log = create_logger("hfl.persist")


@SPROUT.task(bind=True, max_retries=5)
@log_result()
def persist_hfl_entry(self, *, payload: dict) -> dict:
    """Persist one validated envelope on the canonical HFL server.

    A server-side outbox copy is written before retrying so broker redelivery
    exhaustion cannot lose an entry that already reached the canonical host.
    """
    envelope = EntryEnvelope.from_payload(payload)
    if not is_canonical_machine():
        raise RuntimeError("persist_hfl_entry may only run on harqis-server")
    try:
        return persist_envelope(envelope)
    except Exception as exc:
        outbox_path = save_to_outbox(envelope)
        retries = int(getattr(self.request, "retries", 0))
        countdown = min(300, 10 * (2 ** retries))
        _log.warning(
            "Canonical HFL persistence failed; retained %s and retrying in %ss (%s)",
            outbox_path.name,
            countdown,
            type(exc).__name__,
        )
        try:
            raise self.retry(exc=exc, countdown=countdown)
        except MaxRetriesExceededError:
            _log.error(
                "Canonical HFL retries exhausted; entry remains in %s",
                outbox_path,
            )
            raise


@SPROUT.task()
@log_result()
def flush_hfl_outbox(*, limit: int = 100) -> dict[str, int]:
    """Replay durable local outbox entries without creating a second corpus."""
    return flush_outbox(limit=limit)
