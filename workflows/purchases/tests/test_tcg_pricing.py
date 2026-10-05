"""Offline pricing regression tests: no credentials or live listing writes."""
import inspect
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from workflows.purchases.helpers import tcg_pricing as pricing


def offer(id=1, price="12.00", **kwargs):
    return {"id": id, "price": price, "quantity": 1, "own_listing": 0,
            "crd_foil": "0", "crd_language": "EN", "crd_condition": "NM", **kwargs}


@pytest.mark.parametrize("change,expected", [(-20, 13.20), (0, 13.20), (5, 13.20),
                                           (8, 13.20), (15, 14.12), (20, 14.78)])
def test_momentum_and_fee_recovery(change, expected):
    result = pricing.calculate_price(10, change, 1.28)
    assert result["final_price_sgd"] == expected
    assert result["selection"] == "movement"


@pytest.mark.parametrize("change", [-20, 0, 8, 15, 100])
def test_competitor_cap_after_fee_and_momentum_without_floor(change):
    result = pricing.calculate_price(10, change, 1.28, sample=[{"price_sgd": "1"}])
    assert result["final_price_sgd"] == 1
    assert result["selection"] == "competitor_cap"


def test_higher_competitor_price_does_not_raise_movement_price():
    assert pricing.calculate_price(10, 15, 1.28, sample=[{"price_sgd": "99"}])["final_price_sgd"] == 14.12


def test_round_only_final_price_half_up():
    assert pricing.calculate_price("1.005", 0, 1, platform_fee_pct=0)["final_price_sgd"] == 1.01


@pytest.mark.parametrize("field,value", [("base_price_usd", None), ("base_price_usd", 0),
    ("base_price_usd", -1), ("base_price_usd", "NaN"), ("usd_to_sgd_rate", "Infinity"),
    ("usd_to_sgd_rate", 0), ("change_7_day", None), ("platform_fee_pct", 100), ("platform_fee_pct", -1)])
def test_invalid_inputs_are_rejected(field, value):
    args = dict(base_price_usd=10, change_7_day=0, usd_to_sgd_rate=1.28, platform_fee_pct=3)
    args[field] = value
    with pytest.raises(ValueError):
        pricing.calculate_price(**args)


def sample(rows, **kwargs):
    return pricing.competitor_sample(rows, product_id=42, foil=0, language="EN", condition="NM", **kwargs)


def test_cheapest_five_distinct_listings_unweighted():
    rows = [offer(i, str(i), quantity=100 if i == 2 else 1) for i in [8, 2, 4, 1, 7, 6, 3]]
    rows.append(offer(1, "1"))
    chosen = sample(rows)
    assert [x["listing_id"] for x in chosen] == ["1", "2", "3", "4", "6"]
    assert pricing.calculate_price(10, 0, 1.28, sample=chosen)["final_price_sgd"] == 3.2


@pytest.mark.parametrize("overrides", [
    {"own_listing": 1}, {"own_listing": None}, {"user_id": 7}, {"product_id": 999},
    {"crd_foil": "1"}, {"crd_foil": None}, {"crd_language": "JP"},
    {"crd_language": None}, {"crd_condition": "LP"}, {"quantity": 0},
    {"quantity": "NaN"}, {"price": None}, {"price": "NaN"}, {"price": 0},
    {"price": -1}, {"suspended": 1}, {"crd_signed": 1}, {"crd_altered": 1},
])
def test_ineligible_competitors_excluded(overrides):
    assert sample([offer(**overrides)], own_user_id=7) == []


def test_fewer_than_five_and_foil_separation():
    rows = [offer(1, "2"), offer(2, "10", crd_foil="1"), offer(3, "4")]
    assert len(sample(rows)) == 2
    foil = pricing.competitor_sample(rows, product_id=42, foil=1, language="EN", condition="NM")
    assert [x["price_sgd"] for x in foil] == ["10"]


@pytest.mark.parametrize("rows,error,reason", [([], None, "no_eligible_competitors"),
    (None, TimeoutError, "competitor_lookup_failed:TimeoutError"),
    ({"error": "invalid"}, None, "competitor_lookup_failed:ValueError")])
def test_competitor_failure_or_empty_falls_back(rows, error, reason):
    service = SimpleNamespace(get_pricing_listings=Mock(return_value=rows, side_effect=error))
    result = pricing.price_variant(base_price_usd=10, change_7_day=15, fx={"rate": 1.28},
        product_service=service, product_id=42, foil=0, language="EN", condition="NM")
    assert result["final_price_sgd"] == 14.12
    assert result["fallback_reason"] == reason


NOW = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)


def fx_response(**kwargs):
    return {"rate": 1.28, "last_refreshed": NOW.replace(tzinfo=None).isoformat(), "time_zone": "UTC", **kwargs}


def cache_quote(path, age, quote_age=None):
    path.write_text(json.dumps({"pair": "USD/SGD", "rate": "1.27",
        "fetched_at": (NOW - age).isoformat(),
        "quoted_at": (NOW - (quote_age if quote_age is not None else age)).isoformat()}))


def test_fx_fetch_and_fresh_cache(tmp_path):
    path = tmp_path / "fx.json"
    fetch = Mock(return_value=fx_response())
    fresh = pricing.resolve_fx(cache_path=path, now=NOW, fetch=fetch)
    cached = pricing.resolve_fx(cache_path=path, now=NOW + timedelta(hours=23), fetch=fetch)
    assert fresh["source"] == "alpha_vantage"
    assert cached["source"] == "cache"
    assert fresh["rate"] == cached["rate"] == "1.28"
    fetch.assert_called_once()


def test_fx_refresh_at_24_hours(tmp_path):
    path = tmp_path / "fx.json"
    cache_quote(path, timedelta(hours=24))
    fetch = Mock(return_value=fx_response())
    assert pricing.resolve_fx(cache_path=path, now=NOW, fetch=fetch)["rate"] == "1.28"
    fetch.assert_called_once()


@pytest.mark.parametrize("age", [timedelta(days=1), timedelta(days=7)])
def test_fx_provider_failure_uses_bounded_stale_cache(tmp_path, age):
    path = tmp_path / "fx.json"
    cache_quote(path, age)
    result = pricing.resolve_fx(cache_path=path, now=NOW, fetch=Mock(side_effect=TimeoutError("secret")))
    assert result["source"] == "stale_cache"
    assert result["rate"] == "1.27"
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize("age,quote_age", [(timedelta(days=8), None),
    (timedelta(hours=1), timedelta(days=8)), (timedelta(hours=-1), None)])
def test_expired_or_future_cache_cannot_enable_writes(tmp_path, age, quote_age):
    path = tmp_path / "fx.json"
    cache_quote(path, age, quote_age)
    with pytest.raises(ValueError, match="price writes skipped"):
        pricing.resolve_fx(cache_path=path, now=NOW, fetch=Mock(side_effect=TimeoutError))


@pytest.mark.parametrize("response", [{}, fx_response(rate=0), fx_response(rate="NaN"),
    fx_response(time_zone="unexpected"), fx_response(last_refreshed="bad"),
    fx_response(last_refreshed="2026-09-01 00:00:00")])
def test_bad_fx_response_without_cache_skips(tmp_path, response):
    with pytest.raises(ValueError, match="price writes skipped"):
        pricing.resolve_fx(cache_path=tmp_path / "missing.json", now=NOW, fetch=lambda: response)


def test_corrupt_cache_recovers(tmp_path):
    path = tmp_path / "fx.json"
    path.write_text("not json")
    assert pricing.resolve_fx(cache_path=path, now=NOW, fetch=fx_response)["source"] == "alpha_vantage"


def test_unwritable_cache_still_uses_fresh_quote(tmp_path, monkeypatch):
    monkeypatch.setattr(pricing.os, "replace", Mock(side_effect=PermissionError))
    result = pricing.resolve_fx(cache_path=tmp_path / "fx.json", now=NOW, fetch=fx_response)
    assert result["rate"] == "1.28"
    assert result["fallback_reason"] == "cache_write_failed"


@pytest.mark.parametrize("total,status,rows,valid", [(1, 200, [offer()], True),
    (0, 200, [], True), (2, 200, [offer()], False), (None, 200, [], False),
    (0, 500, [], False), (0, 200, {}, False)])
def test_marketplace_envelope_completeness(total, status, rows, valid):
    from apps.tcg_mp.references.web.api.product import ApiServiceTcgMpProducts
    service = SimpleNamespace(request=Mock(), client=Mock())
    service.request.post.return_value = service.request
    service.request.add_uri_parameter.return_value = service.request
    service.client.execute_request.return_value = SimpleNamespace(data={
        "status": status, "data": {"data": rows}, "meta": {"total": total}})
    if valid:
        assert ApiServiceTcgMpProducts.get_pricing_listings(service, 42) == rows
    else:
        with pytest.raises(ValueError):
            ApiServiceTcgMpProducts.get_pricing_listings(service, 42)


@pytest.fixture
def worker_environment(monkeypatch):
    import apps.apps_config as config
    import apps.echo_mtg.references.web.api.notes as notes_api
    import apps.echo_mtg.references.web.api.item as item_api
    import apps.echo_mtg.references.web.api.inventory as inventory_api
    import apps.tcg_mp.references.web.api.publish as publish_api
    import apps.tcg_mp.references.web.api.view as view_api
    import workflows.purchases.tasks.tcg_mp_selling as selling

    card = {"emid": 1, "inventory_id": 1, "note_id": 1, "foil": 0,
            "language": "EN", "condition": "NM", "price_change": 15}
    note = {"tcg_mp_card_id": 42, "tcg_mp_listing_id": 100, "tcg_mp_selling_price": 99}
    notes = SimpleNamespace(get_note=lambda _: {"note": {"note": json.dumps(note)}}, update_note=Mock())
    inventory = SimpleNamespace(search_card=lambda *a, **kw: [card], get_all_collection=lambda **kw: [card])
    publish = SimpleNamespace(remove_listings=Mock())
    products = SimpleNamespace(user_id=7, get_pricing_listings=Mock(return_value=[offer(price="13.50")]))
    meta = {"name_clean": "Test", "tcg_mid": 10, "foil_price": 20}
    monkeypatch.setattr(config, "CONFIG_MANAGER", SimpleNamespace(get=lambda _: None))
    monkeypatch.setattr(selling, "CONFIG_MANAGER", config.CONFIG_MANAGER)
    monkeypatch.setattr(notes_api, "ApiServiceEchoMTGNotes", lambda _: notes)
    monkeypatch.setattr(item_api, "ApiServiceEchoMTGCardItem", lambda _: SimpleNamespace(get_card_meta=lambda _: meta))
    monkeypatch.setattr(inventory_api, "ApiServiceEchoMTGInventory", lambda _: inventory)
    monkeypatch.setattr(selling, "ApiServiceEchoMTGInventory", lambda _: inventory)
    monkeypatch.setattr(publish_api, "ApiServiceTcgMpPublish", lambda _: publish)
    monkeypatch.setattr(view_api, "ApiServiceTcgMpUserView", lambda _: object())
    monkeypatch.setattr(selling, "ApiServiceTcgMpProducts", lambda _: products)
    monkeypatch.setattr(selling.time, "sleep", lambda _: None)
    monkeypatch.setattr(selling, "_listable_variant_copies", lambda *a: ([card], {}))
    monkeypatch.setattr(selling, "_find_live_variant_listings", lambda *a, **kw: [])
    edit = Mock(return_value={"success": True})
    add = Mock(return_value=({"insertId": 100}, False))
    monkeypatch.setattr(selling, "_retry_edit_listing", edit)
    monkeypatch.setattr(selling, "_retry_add_listing", add)
    task = {"cards": [card], "card_echo": card, "cfg_id__tcg_mp": "TCG_MP",
            "cfg_id__echo_mtg": "ECHO_MTG", "cfg_id__echo_mtg_fe": "ECHO_MTG_FE",
            "fx": {"rate": "1.28", "source": "test"}, "platform_fee_pct": 3}
    return SimpleNamespace(selling=selling, task=task, card=card, note=note,
                           notes=notes, edit=edit, add=add, products=products)


@pytest.mark.parametrize("foil,expected", [(0, 13.50), (1, 28.24)])
def test_create_and_update_publish_and_save_identical_prices(worker_environment, foil, expected):
    env = worker_environment
    env.card["foil"] = foil
    env.note["tcg_mp_listing_id"] = 0
    generated = env.selling._worker_generate_tcg_listings(env.task)
    env.note["tcg_mp_listing_id"] = 100
    updated = env.selling._worker_update_tcg_listings_prices(env.task)
    assert generated["created"] and updated["updated"]
    assert env.add.call_args.kwargs["price"] == env.edit.call_args.kwargs["price"] == expected
    for call in env.notes.update_note.call_args_list:
        saved = json.loads(call.args[1])
        assert saved["tcg_mp_selling_price"] == expected
        assert saved["tcg_mp_pricing"]["final_price_sgd"] == expected


def test_worker_competitor_failure_still_publishes_movement_price(worker_environment):
    env = worker_environment
    env.products.get_pricing_listings.side_effect = TimeoutError
    result = env.selling._worker_update_tcg_listings_prices(env.task)
    assert result["updated"]
    assert env.edit.call_args.kwargs["price"] == 14.12
    assert "competitor_lookup_failed" in result["pricing"]["fallback_reason"]


@pytest.mark.parametrize("worker_name", ["_worker_generate_tcg_listings", "_worker_update_tcg_listings_prices"])
def test_workers_without_fx_never_write(worker_environment, worker_name):
    env = worker_environment
    env.task.pop("fx")
    result = getattr(env.selling, worker_name)(env.task)
    assert result["status"] == "error"
    env.edit.assert_not_called()
    env.add.assert_not_called()
    env.notes.update_note.assert_not_called()


def test_failed_update_does_not_save_unpublished_price(worker_environment):
    env = worker_environment
    env.edit.side_effect = ValueError("rejected")
    result = env.selling._worker_update_tcg_listings_prices(env.task)
    assert not result["updated"]
    saved = json.loads(env.notes.update_note.call_args.args[1])
    assert saved["tcg_mp_selling_price"] == 99
    assert "tcg_mp_pricing" not in saved


def test_successful_edit_with_cleanup_failure_saves_published_price(worker_environment, monkeypatch):
    env = worker_environment
    monkeypatch.setattr(env.selling, "_find_live_variant_listings",
                        lambda *a, **kw: [{"listing_id": 100, "quantity": 1}])
    monkeypatch.setattr(env.selling, "_remove_duplicate_variant_listings", Mock(side_effect=TimeoutError))
    result = env.selling._worker_update_tcg_listings_prices(env.task)
    assert result["updated"]
    assert result["audit_failures"]
    assert json.loads(env.notes.update_note.call_args.args[1])["tcg_mp_selling_price"] == 13.50


def test_disappeared_adopted_listing_does_not_stamp_price(worker_environment):
    env = worker_environment
    env.edit.return_value = ""
    result = env.selling._worker_generate_tcg_listings(env.task)
    assert result["status"] == "error"
    env.notes.update_note.assert_not_called()


@pytest.mark.parametrize("task_name", ["generate_tcg_listings", "update_tcg_listings_prices"])
def test_parent_resolves_one_fx_snapshot_for_all_workers(worker_environment, monkeypatch, task_name):
    env = worker_environment
    selling = env.selling
    cards = [env.card, {**env.card, "emid": 2, "inventory_id": 2}]
    monkeypatch.setattr(selling, "ApiServiceEchoMTGInventory",
                        lambda _: SimpleNamespace(get_all_collection=lambda **kw: cards))
    monkeypatch.setattr(selling, "ApiServiceTcgMpMerchant", lambda _: SimpleNamespace(set_listing_status=Mock()))
    monkeypatch.setattr(selling, "ApiServiceTcgMpOrder", lambda _: object())
    monkeypatch.setattr(selling, "_reserved_quantities_by_product_foil", lambda *a, **kw: {})
    monkeypatch.setattr(selling, "_filter_cards_needing_listing", lambda *a: cards)
    fx = Mock(return_value={"rate": "1.28", "source": "test"})
    monkeypatch.setattr(selling, "resolve_fx", fx)
    pool = Mock()
    pool.get_tasks_output.return_value = []
    dispatch = Mock(return_value=pool)
    monkeypatch.setattr(selling, "MultiProcessingClient", dispatch)
    inspect.unwrap(getattr(selling, task_name))(output_csv=False, cfg_id__alpha_vantage="FX_CONFIG")
    fx.assert_called_once_with(cfg_id="FX_CONFIG")
    tasks = dispatch.call_args.kwargs["tasks"]
    assert len(tasks) == 2
    assert all(t["fx"] == fx.return_value and t["platform_fee_pct"] == 3 for t in tasks)


@pytest.mark.parametrize("task_name", ["generate_tcg_listings", "update_tcg_listings_prices"])
def test_parent_fx_failure_prevents_dispatch(worker_environment, monkeypatch, tmp_path, task_name):
    env = worker_environment
    selling = env.selling
    monkeypatch.setattr(selling, "ApiServiceTcgMpMerchant", lambda _: SimpleNamespace(set_listing_status=Mock()))
    monkeypatch.setattr(selling, "ApiServiceTcgMpOrder", lambda _: object())
    monkeypatch.setattr(selling, "_reserved_quantities_by_product_foil", lambda *a, **kw: {})
    monkeypatch.setattr(selling, "_filter_cards_needing_listing", lambda *a: [env.card])
    monkeypatch.setattr(selling, "resolve_fx", Mock(side_effect=ValueError("No usable USD/SGD quote")))
    dispatch = Mock(side_effect=AssertionError("Must not dispatch workers"))
    monkeypatch.setattr(selling, "MultiProcessingClient", dispatch)
    result = inspect.unwrap(getattr(selling, task_name))(audit_output_dir=tmp_path)
    assert result["hfl_status"] == "failure"
    dispatch.assert_not_called()
    env.edit.assert_not_called()
    env.add.assert_not_called()
    assert "pricing_fx" in next(tmp_path.glob("*.csv")).read_text(encoding="utf-8-sig")
