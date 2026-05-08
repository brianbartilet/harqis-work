"""
Celery task wrapper for `agents/projects/integrations/gtasks_bridge.GTasksBridge`.

Fires on the beat schedule every 2 minutes (see `tasks_config.py`). One run
does both halves of the loop:

    inbound:  any new gtask in the configured 'Agents Tasks' list across
              every configured Google account → Trello card in `Ready`,
              with an LLM-enriched description and a back-reference link
              written into the gtask notes.

    outbound: every recorded binding's Trello card status is reflected
              back into the gtask's title (`|<Status>| ...`). When the
              card lands in `Done`, the gtask is marked completed.

Cost note: pin Anthropic Haiku 4.5 via `kwargs.model` from the schedule —
do not raise the Anthropic SDK default. See memory: anthropic_model_override.
"""

from __future__ import annotations

import os
from pathlib import Path

from core.apps.es_logging.app.elasticsearch import log_result
from core.apps.sprout.app.celery import SPROUT
from core.utilities.logging.custom_logger import create_logger

from agents.projects.integrations.gtasks_bridge import (
    DescriptionEnricher,
    GTasksBridge,
    load_accounts,
)
from agents.projects.orchestrator.lists import INTAKE_LIST
from agents.projects.trello.client import TrelloClient

_log = create_logger("workflows.projects.gtasks_sync")

_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"


@SPROUT.task()
@log_result()
def gtasks_kanban_sync(
    *,
    accounts_env: str = "GTASKS_AGENTS_ACCOUNTS",
    list_name_env: str = "GTASKS_AGENTS_LIST",
    board_id_env: str = "KANBAN_BOARD_ID",
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = _DEFAULT_HAIKU,
    enrich: bool = True,
    state_path: str = ".run/gtasks_bindings.json",
) -> dict:
    """One sync cycle of the gtasks ↔ kanban bridge.

    Args (all optional, env-driven defaults):
        accounts_env:    name of env var holding a comma-separated list of
                         apps_config keys (e.g. 'GOOGLE_TASKS,GOOGLE_TASKS_WORK').
                         Default falls back to a single 'GOOGLE_TASKS' account.
        list_name_env:   name of env var holding the gtask list to watch.
                         Default 'Agents Tasks'.
        board_id_env:    name of env var holding the Trello board id. Reuses
                         `KANBAN_BOARD_ID` so all kanban automation lives on
                         one board.
        cfg_id__anthropic: apps_config key for the Anthropic SDK config.
        model:           Claude model id for enrichment. Defaults to Haiku 4.5.
        enrich:          when False, new cards get a placeholder description
                         instead of an LLM-generated one. Useful for offline
                         hosts or initial debugging.
        state_path:      relative path to the binding state JSON.

    Returns:
        {'inbound_created': N, 'outbound_updated': M, 'active_bindings': K}
        On configuration error, returns {'error': '...'} so the worker can
        log the message without raising and triggering a retry storm.
    """
    accounts_str = os.environ.get(accounts_env, "GOOGLE_TASKS")
    account_keys = [k.strip() for k in accounts_str.split(",") if k.strip()]
    list_name = os.environ.get(list_name_env, "Agents Tasks")
    board_id = os.environ.get(board_id_env)
    if not board_id:
        return {"error": f"{board_id_env} not set"}

    api_key = os.environ.get("TRELLO_API_KEY")
    token = os.environ.get("TRELLO_API_TOKEN")
    if not api_key or not token:
        return {"error": "TRELLO_API_KEY / TRELLO_API_TOKEN not set"}

    accounts = load_accounts(account_keys)
    if not accounts:
        return {
            "error": f"no accounts resolved from {accounts_env}={accounts_str!r}"
        }

    trello = TrelloClient(api_key=api_key, token=token)
    enricher = (
        DescriptionEnricher(anthropic_config_key=cfg_id__anthropic, model=model)
        if enrich
        else None
    )
    bridge = GTasksBridge(
        accounts=accounts,
        list_name=list_name,
        board_id=board_id,
        intake_column=INTAKE_LIST,
        trello=trello,
        state_path=Path(state_path),
        enricher=enricher,
    )
    return bridge.run_once()
