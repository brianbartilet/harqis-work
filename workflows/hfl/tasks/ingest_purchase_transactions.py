"""Purchase workflow outcomes -> Homework-for-Life review summaries.

Live purchase capture comes from the generic ``task_success`` hook: purchase tasks return
small structured results and their manifesto opts into the
``purchase_transactions`` signal source. This module drains those signals once
per day, distils only mutations/anomalies/provenance with Claude Haiku, and
dual-writes through the canonical HFL persistence boundary.

A separate EchoMTG-only flow snapshots the complete current collection at
22:55, compares stable inventory ids with the previous successful snapshot,
and records one daily rollup of added and removed card variants. The first run
is baseline-only. Snapshot state advances only after a clean no-change run or a
durably submitted entry, preventing failed/truncated reads from becoming false
mass removals.

Historical backfill is read-only at acquisition time. It reconstructs bounded
daily events from ``tcg-mp-sold-radar`` Elasticsearch documents, radar review
CSVs under ``results/``, and the aggregate ``@log_result`` index. Backfill uses
stable per-day entry ids, so reruns update rather than duplicate entries.

Elasticsearch unavailable / no events -> clean no-op. Anthropic unavailable ->
factual raw fallback. No new credentials are required: existing
ELASTIC_LOGGING and ANTHROPIC configuration is reused.
"""

from __future__ import annotations

import csv
import json
import os
import re
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from core.apps.es_logging.app.elasticsearch import log_result
from core.apps.sprout.app.celery import SPROUT
from core.utilities.logging.custom_logger import create_logger

from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
from apps.apps_config import CONFIG_MANAGER
from apps.echo_mtg.references.web.api.inventory import ApiServiceEchoMTGInventory
from workflows.hfl.dto import HflEntry
from workflows.hfl.persistence import submit_hfl_entry
from workflows.hfl.prompts import load_prompt
from workflows.hfl.signal_store import (
    mark_hfl_signals_rolled_up,
    query_hfl_signals,
)
from workflows.hfl.tasks.ingest_git import _parse_model_json
from workflows.hfl.tasks.capture import resolve_corpus_dir

_log = create_logger("hfl.ingest_purchase_transactions")

_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"
_SOURCE = "purchase_transactions"
_ECHOMTG_SOURCE = "echomtg_inventory"
_ECHOMTG_REFERENCE = "https://www.echomtg.com/inventory/"
_ECHOMTG_SNAPSHOT_VERSION = 1
_REPO_ROOT = Path(__file__).resolve().parents[3]
_RADAR_INDEX = "tcg-mp-sold-radar"
_FUNCTION_LOG_INDEX = "harqis-elastic-logging"
_RUN_ID = re.compile(r"(\d{8})T(\d{6})")
_PURCHASE_TASK_NAMES = {
    "workflows.purchases.tasks.tcg_mp_selling.generate_tcg_listings",
    "workflows.purchases.tasks.tcg_mp_selling.reconcile_then_update_tcg_listings",
    "workflows.purchases.tasks.tcg_mp_selling.download_scryfall_bulk_data",
    "workflows.purchases.tasks.sold_inventory_radar.radar_sold_inventory",
}


def _echomtg_snapshot_path() -> Path:
    return resolve_corpus_dir() / ".ingest-state" / "echomtg-inventory.json"


def _load_echomtg_snapshot(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid EchoMTG inventory snapshot: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid EchoMTG inventory snapshot schema")
    items = payload.get("items")
    if payload.get("version") != _ECHOMTG_SNAPSHOT_VERSION or not isinstance(items, dict):
        raise ValueError("invalid EchoMTG inventory snapshot schema")
    return payload


def _store_echomtg_snapshot(path: Path, items: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": _ECHOMTG_SNAPSHOT_VERSION,
        "captured_at": datetime.now().isoformat(),
        "count": len(items),
        "items": items,
    }
    temporary = path.with_name(
        f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    )
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _echo_credentials_present(config: Any) -> bool:
    if not isinstance(config, dict):
        return False
    data = config.get("app_data") or {}
    email = str(data.get("email") or "").strip()
    password = str(data.get("password") or "").strip()
    return bool(email and password and "${" not in email and "${" not in password)


def _normalize_echomtg_item(item: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    inventory_id = str(item.get("inventory_id") or item.get("id") or "").strip()
    if not inventory_id:
        raise ValueError("EchoMTG collection item is missing inventory_id")
    name = str(
        item.get("name") or item.get("card_name") or item.get("product_name")
        or f"EchoMTG card {item.get('emid') or 'unknown'}"
    ).strip()
    set_name = str(
        item.get("set_code") or item.get("set") or item.get("expansion") or "Unknown set"
    ).strip()
    condition = str(item.get("condition") or item.get("card_condition") or "Unknown").strip()
    foil_value = item.get("foil")
    foil = str(foil_value).strip().casefold() in {"1", "true", "yes", "foil"}
    return inventory_id, {
        "inventory_id": inventory_id,
        "emid": str(item.get("emid") or "").strip(),
        "name": name,
        "set": set_name,
        "foil": foil,
        "condition": condition,
    }


def _fetch_complete_echomtg_collection(
    service: ApiServiceEchoMTGInventory,
    *,
    page_size: int = 1000,
    max_cards: int = 20_000,
) -> dict[str, dict[str, Any]]:
    page_size = min(max(1, int(page_size)), 5000)
    max_cards = min(max(page_size, int(max_cards)), 100_000)
    expected_count: Optional[int] = None
    if hasattr(service, "get_quick_stats"):
        stats = service.get_quick_stats()
        raw_expected = getattr(stats, "total_cards", None)
        if raw_expected is not None:
            expected_count = int(raw_expected)
            if expected_count < 0 or expected_count > max_cards:
                raise ValueError(
                    f"EchoMTG quick stats count {expected_count} is outside the safe bound"
                )
    items: dict[str, dict[str, Any]] = {}
    start = 0
    while True:
        page = service.get_collection(
            start=start, limit=page_size, sort="i.id", direction="ASC", tradable_only=0,
        )
        if not isinstance(page, list):
            raise ValueError(f"EchoMTG collection returned {type(page).__name__}, expected list")
        for raw in page:
            if not isinstance(raw, dict):
                raise ValueError("EchoMTG collection contained a non-object item")
            inventory_id, normalized = _normalize_echomtg_item(raw)
            if inventory_id in items:
                raise ValueError(f"EchoMTG collection repeated inventory_id {inventory_id}")
            items[inventory_id] = normalized
            if len(items) > max_cards:
                raise ValueError(f"EchoMTG collection exceeded max_cards={max_cards}")
        if len(page) < page_size:
            break
        start += len(page)
    if expected_count is not None and len(items) != expected_count:
        raise ValueError(
            f"EchoMTG collection incomplete: expected {expected_count}, received {len(items)}"
        )
    return items


def _variant_counts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter = Counter(
        (
            str(item.get("name") or "Unknown card"),
            str(item.get("set") or "Unknown set"),
            bool(item.get("foil")),
            str(item.get("condition") or "Unknown"),
        )
        for item in items
    )
    return [
        {"name": key[0], "set": key[1], "foil": key[2], "condition": key[3], "quantity": count}
        for key, count in sorted(
            counter.items(),
            key=lambda pair: tuple(str(value).casefold() for value in pair[0]),
        )
    ]


def collect_echomtg_inventory_activity(
    *,
    service: ApiServiceEchoMTGInventory,
    snapshot_path: Optional[Path] = None,
    page_size: int = 1000,
    max_cards: int = 20_000,
) -> dict[str, Any]:
    """Compare the complete EchoMTG collection with the last successful snapshot."""
    path = snapshot_path or _echomtg_snapshot_path()
    current = _fetch_complete_echomtg_collection(
        service, page_size=page_size, max_cards=max_cards,
    )
    previous_payload = _load_echomtg_snapshot(path)
    if previous_payload is None:
        return {
            "baseline": True, "current": current, "current_count": len(current),
            "added": [], "removed": [], "added_count": 0, "removed_count": 0,
            "change_count": 0, "snapshot_path": str(path),
            "references": [_ECHOMTG_REFERENCE],
        }
    previous = previous_payload["items"]
    added_items = [current[key] for key in sorted(current.keys() - previous.keys())]
    removed_items = [previous[key] for key in sorted(previous.keys() - current.keys())]
    return {
        "baseline": False, "current": current, "current_count": len(current),
        "previous_count": len(previous),
        "added": _variant_counts(added_items),
        "removed": _variant_counts(removed_items),
        "added_count": len(added_items), "removed_count": len(removed_items),
        "change_count": len(added_items) + len(removed_items),
        "snapshot_path": str(path), "references": [_ECHOMTG_REFERENCE],
    }


def _echomtg_delta_body(activity: dict[str, Any]) -> str:
    lines: list[str] = []
    for label, key in (("Added", "added"), ("Removed", "removed")):
        for item in activity.get(key) or []:
            finish = "foil" if item["foil"] else "non-foil"
            lines.append(
                f"- {label} {item['quantity']}x {item['name']} — "
                f"{item['set']}, {finish}, {item['condition']}"
            )
    return "\n".join(lines)


def distill_echomtg_inventory_activity(
    activity: dict[str, Any],
    *,
    synthesize: bool = True,
    model: str = _DEFAULT_HAIKU,
    cfg_id: str = "ANTHROPIC",
    max_tokens: int = 900,
) -> dict[str, Any]:
    """Distil an EchoMTG delta while preserving the exact variant list."""
    added = int(activity.get("added_count") or 0)
    removed = int(activity.get("removed_count") or 0)
    exact_body = _echomtg_delta_body(activity)

    def _fallback() -> dict[str, Any]:
        return {
            "skip": False,
            "moment": f"EchoMTG inventory: {added} card(s) added, {removed} removed",
            "what_happened": exact_body,
            "why_it_stayed": "Records the daily change in the card collection.",
            "possible_use": "inventory-review",
            "tags": ["echomtg", "inventory"],
            "synthesized": False,
        }

    if not synthesize:
        return _fallback()
    try:
        client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
        if not getattr(client, "base_client", None):
            return _fallback()
        response = client.send_message(
            prompt=exact_body,
            system=load_prompt("ingest_echomtg_inventory").strip(),
            model=model,
            max_tokens=max_tokens,
        )
        text = response.content[0].text if response and response.content else ""
        parsed = _parse_model_json(text)
        if not parsed:
            return _fallback()
        parsed["skip"] = False
        for key in ("moment", "why_it_stayed", "possible_use"):
            parsed[key] = str(parsed.get(key, "")).strip()
        parsed["what_happened"] = exact_body
        parsed["tags"] = ["echomtg", "inventory", *[
            str(tag).strip().lstrip("#") for tag in (parsed.get("tags") or [])
            if str(tag).strip().lstrip("#") not in {"echomtg", "inventory"}
        ]][:6]
        parsed["synthesized"] = True
        return parsed
    except Exception as exc:  # noqa: BLE001 - never break beat
        _log.warning("EchoMTG inventory synthesis failed (%s) — raw fallback", exc)
        return _fallback()


def _event_day(value: Any) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace(" UTC", "+00:00").replace("Z", "+00:00")).date()
    except ValueError:
        match = re.search(r"\d{4}-\d{2}-\d{2}", str(value))
        return date.fromisoformat(match.group(0)) if match else None


def _in_window(value: Any, since: date, until: date) -> bool:
    day = _event_day(value)
    return bool(day and since <= day <= until)


def _signal_events(
    *, since: date, until: date, include_rolled_up: bool, limit: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    signals = query_hfl_signals(
        since=str(since), until=str(until), source=_SOURCE,
        include_rolled_up=include_rolled_up, limit=limit,
    )
    events = [
        {
            "event_id": signal.get("signal_id") or (
                f"signal:{signal.get('task')}:{signal.get('when')}:{signal.get('summary')}"
            ),
            "when": signal.get("when"),
            "kind": str(signal.get("task") or "").rsplit(".", 1)[-1],
            "status": signal.get("status") or "success",
            "summary": str(signal.get("summary") or "").strip(),
            "references": list(signal.get("references") or []),
            "origin": "hfl-signal",
        }
        for signal in signals if str(signal.get("summary") or "").strip()
    ]
    return events, signals


def _radar_es_events(*, since: date, until: date, limit: int) -> list[dict[str, Any]]:
    try:
        from core.apps.es_logging.app.elasticsearch import get_index_data

        rows = get_index_data(_RADAR_INDEX, fetch_docs=limit) or []
    except Exception as exc:  # noqa: BLE001 - backfill source is optional
        _log.info("purchase backfill: radar ES unavailable (%s)", exc)
        return []
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if not isinstance(row, dict) or not _in_window(row.get("generated_at"), since, until):
            continue
        grouped[str(row.get("run_id") or row.get("generated_at"))].append(row)
    events = []
    for run_id, group in grouped.items():
        when = group[0].get("generated_at")
        acted = sum(1 for row in group if str(row.get("applied", "")).lower() == "true")
        errors = sum(1 for row in group if "error:" in str(row.get("action_results", "")).lower())
        events.append({
            "event_id": f"radar-es:{run_id}", "when": when,
            "kind": "sold-reconciled", "status": "anomaly" if errors else "success",
            "summary": (
                f"Sold-inventory radar found {len(group)} candidate(s), "
                f"acted on {acted}, with {errors} action error(s)."
            ),
            "references": [f"es:{_RADAR_INDEX}:{run_id}"], "origin": "radar-es",
        })
    return events


def _radar_csv_events(
    *, since: date, until: date, results_dir: Path, seen_runs: set[str], limit: int
) -> list[dict[str, Any]]:
    events = []
    for path in sorted(results_dir.glob("sold_inventory_radar-*.csv"), reverse=True):
        if "-applied-" in path.name:
            continue
        match = _RUN_ID.search(path.name)
        if not match:
            continue
        run_id = "".join(match.groups())
        if run_id in seen_runs:
            continue
        try:
            when = datetime.strptime(run_id, "%Y%m%d%H%M%S")
        except ValueError:
            continue
        if not (since <= when.date() <= until):
            continue
        try:
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
        except OSError:
            continue
        if not rows:
            continue
        acted = sum(1 for row in rows if str(row.get("applied", "")).lower() in {"1", "true", "yes"})
        errors = sum(1 for row in rows if "error:" in str(row.get("action_results", "")).lower())
        events.append({
            "event_id": f"radar-csv:{run_id}", "when": when.isoformat(),
            "kind": "sold-reconciled", "status": "anomaly" if errors else "success",
            "summary": (
                f"Sold-inventory radar found {len(rows)} candidate(s), "
                f"acted on {acted}, with {errors} action error(s)."
            ),
            "references": [str(path)], "origin": "radar-csv",
        })
        if len(events) >= limit:
            break
    return events


def _function_log_events(*, since: date, until: date) -> list[dict[str, Any]]:
    """Recover only facts the aggregate @log_result documents can prove."""
    try:
        from core.apps.es_logging.app.elasticsearch import get_index_data

        rows = get_index_data(_FUNCTION_LOG_INDEX, fetch_docs=10_000) or []
    except Exception as exc:  # noqa: BLE001 - optional historical source
        _log.info("purchase backfill: function logs unavailable (%s)", exc)
        return []
    events = []
    for row in rows:
        if not isinstance(row, dict) or row.get("name") not in _PURCHASE_TASK_NAMES:
            continue
        name = str(row["name"])
        failed = int(row.get("failed") or 0)
        last_failed = row.get("last_failed")
        if failed and _in_window(last_failed, since, until):
            events.append({
                "event_id": f"function-log-failure:{name}:{last_failed}",
                "when": last_failed, "kind": name.rsplit(".", 1)[-1],
                "status": "failure",
                "summary": (
                    f"{name.rsplit('.', 1)[-1]} recorded a historical failure "
                    f"({row.get('exception_message') or 'unknown exception'})."
                ),
                "references": [f"es:{_FUNCTION_LOG_INDEX}:{name}"],
                "origin": "function-log",
            })
        if name.endswith("download_scryfall_bulk_data") and _in_window(row.get("date"), since, until):
            events.append({
                "event_id": f"function-log-scryfall:{row.get('date')}",
                "when": row.get("date"), "kind": "scryfall-refresh", "status": "success",
                "summary": "Scryfall bulk card data refresh completed.",
                "references": [f"es:{_FUNCTION_LOG_INDEX}:{name}"],
                "origin": "function-log",
            })
    return events


def collect_purchase_transactions_activity(
    *,
    since: date,
    until: date,
    include_rolled_up: bool = False,
    include_backfill: bool = False,
    max_events: int = 500,
    results_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Collect bounded structured summaries for live ingestion or backfill."""
    max_events = max(1, min(int(max_events), 5000))
    events, signals = _signal_events(
        since=since, until=until, include_rolled_up=include_rolled_up,
        limit=max_events,
    )
    if include_backfill:
        es_events = _radar_es_events(since=since, until=until, limit=max_events)
        events.extend(es_events)
        seen_runs = {
            str(event["event_id"]).split(":", 1)[1]
            for event in es_events if str(event.get("event_id", "")).startswith("radar-es:")
        }
        events.extend(_radar_csv_events(
            since=since, until=until,
            results_dir=results_dir or (_REPO_ROOT / "results"),
            seen_runs=seen_runs, limit=max_events,
        ))
        events.extend(_function_log_events(since=since, until=until))

    unique: dict[str, dict] = {}
    for event in events:
        unique[str(event.get("event_id") or event)] = event
    ordered = sorted(unique.values(), key=lambda event: str(event.get("when") or ""))
    ordered = ordered[-max_events:]
    return {
        "events": ordered,
        "event_count": len(ordered),
        "signals": signals,
        "references": sorted({
            str(ref) for event in ordered for ref in (event.get("references") or []) if ref
        }),
    }


def _activity_body(activity: dict) -> str:
    return "\n".join(
        f"- {event.get('when', '')} [{event.get('status', 'success')}] "
        f"{event.get('kind', 'purchase')}: {event.get('summary', '')}"
        for event in activity["events"]
    )


def distill_purchase_transactions_activity(
    activity: dict,
    *,
    synthesize: bool = True,
    model: str = _DEFAULT_HAIKU,
    cfg_id: str = "ANTHROPIC",
    max_tokens: int = 900,
) -> dict[str, Any]:
    """Distil transaction-run summaries with Haiku and a factual fallback."""
    events = activity["events"]

    def _fallback() -> dict:
        kinds = {str(event.get("kind") or "purchase") for event in events}
        return {
            "skip": False,
            "moment": f"Reviewed {len(events)} meaningful purchase workflow event(s)",
            "what_happened": _activity_body(activity),
            "why_it_stayed": "Keeps marketplace mutations and operational anomalies reviewable.",
            "possible_use": "transaction-review",
            "tags": ["purchase-transactions", *sorted(kinds)[:5]],
            "synthesized": False,
        }

    if not synthesize:
        return _fallback()
    try:
        client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
        if not getattr(client, "base_client", None):
            return _fallback()
        response = client.send_message(
            prompt=_activity_body(activity),
            system=load_prompt("ingest_purchase_transactions").strip(),
            model=model,
            max_tokens=max_tokens,
        )
        text = response.content[0].text if response and response.content else ""
        parsed = _parse_model_json(text)
        if not parsed:
            return _fallback()
        parsed.setdefault("skip", False)
        for key in ("moment", "what_happened", "why_it_stayed", "possible_use"):
            parsed[key] = str(parsed.get(key, "")).strip()
        parsed["tags"] = [str(tag).strip().lstrip("#") for tag in (parsed.get("tags") or [])]
        parsed["synthesized"] = True
        return parsed
    except Exception as exc:  # noqa: BLE001 - never break beat
        _log.warning("purchase transaction synthesis failed (%s) — raw fallback", exc)
        return _fallback()


def _persist_activity(activity: dict, *, when: datetime, distilled: dict) -> dict[str, Any]:
    stable_id = f"purchase-transactions-{when.strftime('%Y-%m-%d')}"
    entry = HflEntry(
        when=when,
        moment=distilled["moment"],
        what_happened=distilled["what_happened"],
        why_it_stayed=distilled["why_it_stayed"],
        possible_use=distilled["possible_use"] or "transaction-review",
        tags=tuple(["purchase-transactions", *(distilled.get("tags") or [])][:8]),
        references=tuple(activity.get("references") or []),
        source=_SOURCE,
        entry_id=stable_id,
        synthesized=bool(distilled.get("synthesized")),
    )
    return submit_hfl_entry(
        entry, source=_SOURCE, synthesized=bool(distilled.get("synthesized")),
        dedup_key=stable_id, es_doc_id=stable_id,
    )


@SPROUT.task()
@log_result()
def ingest_purchase_transactions_activity(
    *,
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = _DEFAULT_HAIKU,
    window_days: int = 1,
    max_events: int = 500,
) -> dict[str, Any]:
    """Drain pending purchase signals into one concise daily HFL entry."""
    until = datetime.now().date()
    since = until - timedelta(days=max(0, int(window_days)))
    try:
        activity = collect_purchase_transactions_activity(
            since=since, until=until, max_events=max_events,
        )
    except Exception as exc:  # noqa: BLE001 - never break beat
        return {"skipped": "collection failed", "entries_written": 0, "error": str(exc)[:200]}
    if not activity["event_count"]:
        return {"skipped": "no meaningful purchase events", "entries_written": 0, "events": 0}
    distilled = distill_purchase_transactions_activity(
        activity, model=model, cfg_id=cfg_id__anthropic,
    )
    if distilled.get("skip"):
        return {"skipped": "distilled-skip", "entries_written": 0, "events": activity["event_count"]}
    persistence = _persist_activity(activity, when=datetime.now(), distilled=distilled)
    marked = mark_hfl_signals_rolled_up(activity["signals"])
    return {
        "entries_written": 1, "events": activity["event_count"],
        "signals_marked": marked,
        "indexed": persistence.get("doc_id") is not None,
        "synthesized": bool(distilled.get("synthesized")),
        "model": model if distilled.get("synthesized") else None,
        "path": persistence.get("path", ""),
        "entry_id": persistence.get("entry_id"),
    }


def _persist_echomtg_inventory_activity(
    activity: dict[str, Any], *, when: datetime, distilled: dict[str, Any]
) -> dict[str, Any]:
    stable_id = f"echomtg-inventory-{when.strftime('%Y-%m-%d')}"
    entry = HflEntry(
        when=when,
        moment=distilled["moment"],
        what_happened=distilled["what_happened"],
        why_it_stayed=distilled["why_it_stayed"],
        possible_use=distilled["possible_use"] or "inventory-review",
        tags=tuple(dict.fromkeys(
            ["echomtg", "inventory", *(distilled.get("tags") or [])]
        ))[:8],
        references=tuple(activity.get("references") or []),
        source=_ECHOMTG_SOURCE,
        entry_id=stable_id,
        synthesized=bool(distilled.get("synthesized")),
    )
    return submit_hfl_entry(
        entry,
        source=_ECHOMTG_SOURCE,
        synthesized=bool(distilled.get("synthesized")),
        dedup_key=stable_id,
        es_doc_id=stable_id,
    )


@SPROUT.task()
@log_result()
def ingest_echomtg_inventory_activity(
    *,
    cfg_id__echo_mtg: str = "ECHO_MTG",
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = _DEFAULT_HAIKU,
    page_size: int = 1000,
    max_cards: int = 20_000,
) -> dict[str, Any]:
    """Write one daily EchoMTG-only rollup when inventory ids changed.

    Missing credentials, first-run baseline, and unchanged collections make no
    entry and no model call. Failed or incomplete reads never advance state.
    """
    try:
        config = CONFIG_MANAGER.get(cfg_id__echo_mtg)
    except Exception as exc:  # noqa: BLE001 - config failure must not break beat
        return {
            "skipped": "EchoMTG config unavailable", "entries_written": 0,
            "error": str(exc)[:200], "snapshot_advanced": False,
        }
    if not _echo_credentials_present(config):
        _log.info("EchoMTG inventory ingest: credentials unavailable — no-op")
        return {
            "skipped": "no EchoMTG credentials", "entries_written": 0,
            "snapshot_advanced": False,
        }

    snapshot_path = _echomtg_snapshot_path()
    try:
        activity = collect_echomtg_inventory_activity(
            service=ApiServiceEchoMTGInventory(config),
            snapshot_path=snapshot_path,
            page_size=page_size,
            max_cards=max_cards,
        )
    except Exception as exc:  # noqa: BLE001 - never advance on uncertain input
        _log.error("EchoMTG inventory collection unavailable (%s)", exc)
        return {
            "skipped": "EchoMTG inventory unavailable", "entries_written": 0,
            "error": str(exc)[:200], "snapshot_advanced": False,
        }

    if activity["baseline"]:
        try:
            _store_echomtg_snapshot(snapshot_path, activity["current"])
        except Exception as exc:  # noqa: BLE001 - retry baseline next run
            return {
                "skipped": "baseline write failed", "entries_written": 0,
                "error": str(exc)[:200], "snapshot_advanced": False,
            }
        return {
            "skipped": "baseline created", "entries_written": 0,
            "cards": activity["current_count"], "snapshot_advanced": True,
            "snapshot_path": str(snapshot_path),
        }

    if not activity["change_count"]:
        try:
            _store_echomtg_snapshot(snapshot_path, activity["current"])
        except Exception as exc:  # noqa: BLE001 - harmless retry next run
            return {
                "skipped": "snapshot write failed", "entries_written": 0,
                "error": str(exc)[:200], "snapshot_advanced": False,
            }
        return {
            "skipped": "no EchoMTG inventory changes", "entries_written": 0,
            "cards": activity["current_count"], "snapshot_advanced": True,
        }

    distilled = distill_echomtg_inventory_activity(
        activity, model=model, cfg_id=cfg_id__anthropic,
    )
    if distilled.get("skip"):
        return {
            "skipped": "distilled-skip", "entries_written": 0,
            "changes": activity["change_count"], "snapshot_advanced": False,
        }
    try:
        persistence = _persist_echomtg_inventory_activity(
            activity, when=datetime.now(), distilled=distilled,
        )
        _store_echomtg_snapshot(snapshot_path, activity["current"])
    except Exception as exc:  # noqa: BLE001 - retain old state for retry
        _log.error("EchoMTG inventory persistence failed (%s)", exc)
        return {
            "skipped": "persistence failed", "entries_written": 0,
            "error": str(exc)[:200], "snapshot_advanced": False,
        }
    return {
        "entries_written": 1,
        "added": activity["added_count"],
        "removed": activity["removed_count"],
        "cards": activity["current_count"],
        "indexed": persistence.get("doc_id") is not None,
        "synthesized": bool(distilled.get("synthesized")),
        "model": model if distilled.get("synthesized") else None,
        "path": persistence.get("path", ""),
        "entry_id": persistence.get("entry_id"),
        "snapshot_advanced": True,
    }


@SPROUT.task()
@log_result()
def backfill_purchase_transactions_activity(
    *,
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = _DEFAULT_HAIKU,
    window_days: int = 3650,
    max_events: int = 5000,
) -> dict[str, Any]:
    """Idempotently reconstruct one purchase review entry per historical day."""
    until = datetime.now().date()
    since = until - timedelta(days=max(1, int(window_days)))
    activity = collect_purchase_transactions_activity(
        since=since, until=until, include_rolled_up=True,
        include_backfill=True, max_events=max_events,
    )
    if not activity["event_count"]:
        return {"skipped": "no historical purchase events", "entries_written": 0}
    by_day: dict[date, list[dict]] = defaultdict(list)
    for event in activity["events"]:
        day = _event_day(event.get("when"))
        if day:
            by_day[day].append(event)
    written = 0
    for day, events in sorted(by_day.items()):
        daily = {
            "events": events, "event_count": len(events), "signals": [],
            "references": sorted({
                str(ref) for event in events for ref in (event.get("references") or []) if ref
            }),
        }
        distilled = distill_purchase_transactions_activity(
            daily, model=model, cfg_id=cfg_id__anthropic,
        )
        if distilled.get("skip"):
            continue
        _persist_activity(daily, when=datetime.combine(day, datetime.min.time()), distilled=distilled)
        written += 1
    return {"entries_written": written, "days": len(by_day), "events": activity["event_count"]}
