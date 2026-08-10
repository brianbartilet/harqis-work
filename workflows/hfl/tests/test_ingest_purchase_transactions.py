from datetime import date, datetime

import pytest
from core.web.services.core.config.webservice import AppConfigWSClient

import workflows.hfl.tasks.ingest_purchase_transactions as module


def _activity():
    signal = {
        "signal_id": "sig-1",
        "task": "workflows.purchases.tasks.tcg_mp_selling.generate_tcg_listings",
        "source": "purchase_transactions",
        "summary": "TCG listings: 2 created, 0 errors.",
        "status": "success",
        "when": "2026-08-08T01:00:00",
        "references": ["api:tcg_mp"],
    }
    return {
        "events": [{
            "event_id": "sig-1", "when": signal["when"],
            "kind": "generate_tcg_listings", "status": "success",
            "summary": signal["summary"], "references": signal["references"],
            "origin": "hfl-signal",
        }],
        "event_count": 1,
        "signals": [signal],
        "references": ["api:tcg_mp"],
    }


def test_collect_live_signals_is_bounded_and_structured(monkeypatch):
    monkeypatch.setattr(module, "query_hfl_signals", lambda **kwargs: _activity()["signals"])

    result = module.collect_purchase_transactions_activity(
        since=date(2026, 8, 8), until=date(2026, 8, 8), max_events=10,
    )

    assert result["event_count"] == 1
    assert result["events"][0]["kind"] == "generate_tcg_listings"
    assert result["references"] == ["api:tcg_mp"]


def test_distill_without_synthesis_is_factual_fallback():
    result = module.distill_purchase_transactions_activity(
        _activity(), synthesize=False,
    )

    assert result["synthesized"] is False
    assert "2 created" in result["what_happened"]
    assert "purchase-transactions" in result["tags"]


def test_empty_task_path_makes_no_write_or_llm_call(monkeypatch):
    monkeypatch.setattr(
        module, "collect_purchase_transactions_activity",
        lambda **kwargs: {"events": [], "event_count": 0, "signals": [], "references": []},
    )
    monkeypatch.setattr(
        module, "distill_purchase_transactions_activity",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM called")),
    )
    monkeypatch.setattr(
        module, "_persist_activity",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("write called")),
    )

    result = module.ingest_purchase_transactions_activity.run()

    assert result["entries_written"] == 0
    assert result["skipped"] == "no meaningful purchase events"


def test_task_dual_write_boundary_and_acknowledgement(monkeypatch):
    activity = _activity()
    captured = {}
    monkeypatch.setattr(module, "collect_purchase_transactions_activity", lambda **kwargs: activity)
    monkeypatch.setattr(
        module, "distill_purchase_transactions_activity",
        lambda *args, **kwargs: {
            "skip": False, "moment": "Listings changed", "what_happened": "Two created.",
            "why_it_stayed": "Review exposure.", "possible_use": "transaction-review",
            "tags": ["listing-created"], "synthesized": False,
        },
    )
    monkeypatch.setattr(
        module, "_persist_activity",
        lambda *args, **kwargs: captured.setdefault(
            "write", {"doc_id": "purchase-transactions-2026-08-08", "path": "day.md", "entry_id": "entry"}
        ),
    )
    monkeypatch.setattr(
        module, "mark_hfl_signals_rolled_up",
        lambda signals: captured.setdefault("marked", len(signals)),
    )

    result = module.ingest_purchase_transactions_activity.run()

    assert result["entries_written"] == 1
    assert result["indexed"] is True
    assert captured["marked"] == 1


def test_persist_uses_stable_daily_dual_write_identity(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        module, "submit_hfl_entry",
        lambda entry, **kwargs: captured.update(entry=entry, **kwargs) or {
            "doc_id": kwargs["es_doc_id"], "path": "day.md"
        },
    )
    distilled = {
        "moment": "Listings changed", "what_happened": "Two created.",
        "why_it_stayed": "Review exposure.", "possible_use": "transaction-review",
        "tags": ["listing-created"], "synthesized": False,
    }

    result = module._persist_activity(
        _activity(), when=datetime(2026, 8, 8, 23, 0), distilled=distilled,
    )

    assert result["doc_id"] == "purchase-transactions-2026-08-08"
    assert captured["dedup_key"] == "purchase-transactions-2026-08-08"
    assert captured["es_doc_id"] == "purchase-transactions-2026-08-08"
    assert captured["entry"].references == ("api:tcg_mp",)


def test_radar_csv_backfill_is_idempotently_identified(tmp_path, monkeypatch):
    path = tmp_path / "sold_inventory_radar-20260808T020304123456.csv"
    path.write_text(
        "applied,action_results,card_name\ntrue,mark_sold:ok,Sol Ring\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "query_hfl_signals", lambda **kwargs: [])
    monkeypatch.setattr(module, "_radar_es_events", lambda **kwargs: [])
    monkeypatch.setattr(module, "_function_log_events", lambda **kwargs: [])

    result = module.collect_purchase_transactions_activity(
        since=date(2026, 8, 8), until=date(2026, 8, 8),
        include_backfill=True, results_dir=tmp_path,
    )

    assert result["event_count"] == 1
    assert result["events"][0]["event_id"] == "radar-csv:20260808020304"
    assert result["events"][0]["references"] == [str(path)]


class _EchoInventoryPages:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def get_collection(self, **kwargs):
        self.calls.append(kwargs)
        return self.pages.pop(0) if self.pages else []


class _EchoInventoryPartitions:
    def __init__(self, partitions, expected_count=None):
        self.partitions = {
            key: list(pages) for key, pages in partitions.items()
        }
        self.expected_count = expected_count
        self.calls = []

    def get_quick_stats(self):
        count = (
            self.expected_count
            if self.expected_count is not None
            else sum(
                len(page)
                for pages in self.partitions.values()
                for page in pages
            )
        )
        return type("Stats", (), {"total_cards": count})()

    def get_collection(self, **kwargs):
        self.calls.append(kwargs)
        pages = self.partitions[kwargs["tradable_only"]]
        return pages.pop(0) if pages else []


def _echo_item(inventory_id, name="Sol Ring", set_name="CMM", foil=0, condition="NM"):
    return {
        "inventory_id": inventory_id, "emid": "100", "name": name,
        "set": set_name, "foil": foil, "condition": condition,
    }


def test_echomtg_collector_first_run_is_baseline_only(tmp_path):
    service = _EchoInventoryPages([[_echo_item("one")]])

    result = module.collect_echomtg_inventory_activity(
        service=service, snapshot_path=tmp_path / "snapshot.json",
    )

    assert result["baseline"] is True
    assert result["current_count"] == 1
    assert result["change_count"] == 0


def test_echo_credentials_support_live_config_shape_and_token():
    config = AppConfigWSClient(app_data={
        "username": "configured", "password": "configured",
    })

    assert module._echo_credentials_present(config) is True
    assert module._echo_credentials_present({
        "app_data": {"token": "configured"},
    }) is True
    assert module._echo_credentials_present(AppConfigWSClient(app_data={
        "username": "${ECHO_MTG_USER}", "password": "configured",
    })) is False


def test_echomtg_collection_fetches_both_tradable_partitions(tmp_path):
    service = _EchoInventoryPartitions({
        0: [[_echo_item("collection-copy")]],
        1: [[_echo_item("tradable-copy")]],
    })

    result = module.collect_echomtg_inventory_activity(
        service=service, snapshot_path=tmp_path / "snapshot.json",
    )

    assert result["current_count"] == 2
    assert set(result["current"]) == {"collection-copy", "tradable-copy"}
    assert [call["tradable_only"] for call in service.calls] == [0, 1]
    assert [call["start"] for call in service.calls] == [0, 0]


def test_echomtg_quick_stats_is_a_lower_bound_not_an_exact_total():
    service = _EchoInventoryPartitions({
        0: [[_echo_item("collection-copy")]],
        1: [[_echo_item("tradable-copy")]],
    }, expected_count=1)

    items = module._fetch_complete_echomtg_collection(service)

    assert set(items) == {"collection-copy", "tradable-copy"}


def test_echomtg_collection_rejects_fewer_items_than_quick_stats():
    service = _EchoInventoryPartitions({
        0: [[_echo_item("collection-copy")]],
        1: [[]],
    }, expected_count=2)

    with pytest.raises(ValueError, match="expected at least 2, received 1"):
        module._fetch_complete_echomtg_collection(service)


def test_echomtg_collector_rolls_up_additions_removals_and_duplicates(tmp_path):
    snapshot = tmp_path / "snapshot.json"
    module._store_echomtg_snapshot(snapshot, {
        "removed": module._normalize_echomtg_item(
            _echo_item("removed", "Counterspell", "DMR", 1, "LP")
        )[1],
        "kept": module._normalize_echomtg_item(_echo_item("kept"))[1],
    })
    service = _EchoInventoryPages([[
        _echo_item("kept"), _echo_item("added-1"), _echo_item("added-2"),
    ]])

    result = module.collect_echomtg_inventory_activity(
        service=service, snapshot_path=snapshot,
    )

    assert result["baseline"] is False
    assert result["added_count"] == 2
    assert result["removed_count"] == 1
    assert result["added"] == [{
        "name": "Sol Ring", "set": "CMM", "foil": False,
        "condition": "NM", "quantity": 2,
    }]
    assert "Removed 1x Counterspell — DMR, foil, LP" in module._echomtg_delta_body(result)


def test_echomtg_collection_paginates_and_rejects_duplicate_ids():
    service = _EchoInventoryPages([
        [_echo_item("one")],
        [_echo_item("one")],
    ])

    with pytest.raises(ValueError, match="repeated inventory_id"):
        module._fetch_complete_echomtg_collection(service, page_size=1, max_cards=10)

    assert [call["start"] for call in service.calls] == [0, 1]


def test_echomtg_distill_without_synthesis_keeps_exact_variant_details():
    activity = {
        "added_count": 2, "removed_count": 1,
        "added": [{"name": "Sol Ring", "set": "CMM", "foil": False,
                   "condition": "NM", "quantity": 2}],
        "removed": [{"name": "Counterspell", "set": "DMR", "foil": True,
                     "condition": "LP", "quantity": 1}],
    }

    result = module.distill_echomtg_inventory_activity(activity, synthesize=False)

    assert result["synthesized"] is False
    assert result["tags"] == ["echomtg", "inventory"]
    assert "Added 2x Sol Ring — CMM, non-foil, NM" in result["what_happened"]


def test_echomtg_task_baseline_writes_snapshot_without_entry_or_llm(monkeypatch, tmp_path):
    snapshot = tmp_path / "snapshot.json"
    current = {"one": module._normalize_echomtg_item(_echo_item("one"))[1]}
    monkeypatch.setattr(module.CONFIG_MANAGER, "get", lambda key: {
        "app_data": {"email": "configured", "password": "configured"}
    })
    monkeypatch.setattr(module, "ApiServiceEchoMTGInventory", lambda cfg: object())
    monkeypatch.setattr(module, "_echomtg_snapshot_path", lambda: snapshot)
    monkeypatch.setattr(module, "collect_echomtg_inventory_activity", lambda **kwargs: {
        "baseline": True, "current": current, "current_count": 1,
        "change_count": 0,
    })
    monkeypatch.setattr(
        module, "distill_echomtg_inventory_activity",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM called")),
    )
    monkeypatch.setattr(
        module, "_persist_echomtg_inventory_activity",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("entry written")),
    )

    result = module.ingest_echomtg_inventory_activity.run()

    assert result["skipped"] == "baseline created"
    assert result["entries_written"] == 0
    assert module._load_echomtg_snapshot(snapshot)["items"] == current


def test_echomtg_task_missing_credentials_makes_no_network_call(monkeypatch):
    monkeypatch.setattr(module.CONFIG_MANAGER, "get", lambda key: {
        "app_data": {"email": "${ECHO_MTG_USER}", "password": ""}
    })
    monkeypatch.setattr(
        module, "ApiServiceEchoMTGInventory",
        lambda cfg: (_ for _ in ()).throw(AssertionError("network client created")),
    )

    result = module.ingest_echomtg_inventory_activity.run()

    assert result["skipped"] == "no EchoMTG credentials"
    assert result["entries_written"] == 0
    assert result["snapshot_advanced"] is False


def test_echomtg_task_dual_writes_then_advances_snapshot(monkeypatch, tmp_path):
    snapshot = tmp_path / "snapshot.json"
    current = {"new": module._normalize_echomtg_item(_echo_item("new"))[1]}
    activity = {
        "baseline": False, "current": current, "current_count": 1,
        "added": [{"name": "Sol Ring", "set": "CMM", "foil": False,
                   "condition": "NM", "quantity": 1}],
        "removed": [], "added_count": 1, "removed_count": 0,
        "change_count": 1, "references": [module._ECHOMTG_REFERENCE],
    }
    monkeypatch.setattr(module.CONFIG_MANAGER, "get", lambda key: {
        "app_data": {"email": "configured", "password": "configured"}
    })
    monkeypatch.setattr(module, "ApiServiceEchoMTGInventory", lambda cfg: object())
    monkeypatch.setattr(module, "_echomtg_snapshot_path", lambda: snapshot)
    monkeypatch.setattr(module, "collect_echomtg_inventory_activity", lambda **kwargs: activity)
    monkeypatch.setattr(module, "distill_echomtg_inventory_activity", lambda *args, **kwargs: {
        "skip": False, "moment": "One card added", "what_happened": "Added one.",
        "why_it_stayed": "Collection changed.", "possible_use": "inventory-review",
        "tags": ["echomtg", "inventory"], "synthesized": False,
    })
    monkeypatch.setattr(module, "_persist_echomtg_inventory_activity", lambda *args, **kwargs: {
        "doc_id": "echomtg-inventory-2026-08-08", "path": "day.md", "entry_id": "entry",
    })

    result = module.ingest_echomtg_inventory_activity.run()

    assert result["entries_written"] == 1
    assert result["added"] == 1 and result["removed"] == 0
    assert result["snapshot_advanced"] is True
    assert module._load_echomtg_snapshot(snapshot)["items"] == current


def test_echomtg_persist_uses_stable_daily_identity_and_required_tags(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        module, "submit_hfl_entry",
        lambda entry, **kwargs: captured.update(entry=entry, **kwargs) or {
            "doc_id": kwargs["es_doc_id"], "path": "day.md"
        },
    )
    activity = {"references": [module._ECHOMTG_REFERENCE]}
    distilled = {
        "moment": "One card added", "what_happened": "Added one.",
        "why_it_stayed": "Collection changed.", "possible_use": "inventory-review",
        "tags": ["cards-added"], "synthesized": False,
    }

    result = module._persist_echomtg_inventory_activity(
        activity, when=datetime(2026, 8, 8, 22, 55), distilled=distilled,
    )

    assert result["doc_id"] == "echomtg-inventory-2026-08-08"
    assert captured["dedup_key"] == "echomtg-inventory-2026-08-08"
    assert captured["es_doc_id"] == "echomtg-inventory-2026-08-08"
    assert captured["entry"].tags[:2] == ("echomtg", "inventory")
    assert captured["entry"].references == (module._ECHOMTG_REFERENCE,)


@pytest.mark.skip(reason="Manual only — queries the live EchoMTG collection and writes HFL state")
def test_echomtg_full_pipeline_manual():
    module.ingest_echomtg_inventory_activity.run()
