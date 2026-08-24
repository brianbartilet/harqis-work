"""Optional, configuration-gated delivery adapters for Second Brain."""

from __future__ import annotations

from core.apps.es_logging.app.elasticsearch import log_result
from core.apps.sprout.app.celery import SPROUT

from workflows.second_brain.adapters import client_items, render_text
from workflows.second_brain.store import get_store


@SPROUT.task()
@log_result()
def deliver_second_brain_telegram(**_kwargs):
    """Send one redacted advisory digest when Telegram delivery is enabled."""
    store = get_store()
    config = store.get_config()
    if not (config.get("clients") or {}).get("telegram", False):
        return {"text": "Second Brain Telegram delivery disabled", "delivered": False}
    decision = store.latest_decision() or {}
    items = client_items(
        store.feed_snapshot(
            client="telegram",
            limit=10,
            modes=decision.get("effective_modes") or (),
        ),
        client="telegram",
    )
    if not items:
        return {"text": "Second Brain Telegram delivery had no fresh items", "delivered": False}
    from apps.telegram.config import CONFIG as telegram_config
    from apps.telegram.references.web.api.messages import ApiServiceTelegramMessages

    chat_id = telegram_config.app_data.get("default_chat_id")
    if not chat_id:
        raise RuntimeError("Telegram default_chat_id is missing")
    text = render_text(items, title="HARQIS SECOND BRAIN", limit=8)
    result = ApiServiceTelegramMessages(telegram_config).send_message(
        chat_id=chat_id,
        text=text[:3900],
        disable_notification=True,
    )
    message_id = result.get("message_id") if isinstance(result, dict) else None
    if isinstance(message_id, bool) or not isinstance(message_id, int) or message_id <= 0:
        raise RuntimeError("Telegram sendMessage did not return a valid message_id")
    return {"text": "Second Brain Telegram digest delivered", "delivered": True, "message_id": message_id}
