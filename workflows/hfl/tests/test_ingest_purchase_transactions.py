from datetime import date, datetime

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
