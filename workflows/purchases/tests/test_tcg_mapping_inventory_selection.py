"""Mapping selection contracts; all services are mocked, no inventory writes."""
import inspect
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import workflows.purchases.tasks.tcg_mp_selling as selling


@pytest.fixture
def mapping_services(monkeypatch):
    inventory = Mock()
    # Full inventory is deliberately oldest-first, as get_all_collection is.
    cards = [{"inventory_id": str(i), "emid": str(i)} for i in range(1, 135)]
    inventory.get_all_collection.return_value = cards
    inventory.get_collection.side_effect = lambda **kw: sorted(
        cards, key=lambda card: int(card["inventory_id"]),
        reverse=kw["direction"] == "DESC",
    )[kw["start"]:kw["start"] + kw["limit"]]
    monkeypatch.setattr(selling, "CONFIG_MANAGER", Mock())
    monkeypatch.setattr(selling, "ApiServiceEchoMTGInventory", Mock(return_value=inventory))
    for name in ("ApiServiceEchoMTGNotes", "ApiServiceEchoMTGCardItem",
                 "ApiServiceTcgMpProducts", "ApiServiceTcgMpMerchant",
                 "ApiServiceScryfallCards"):
        monkeypatch.setattr(selling, name, Mock())
    selling.ApiServiceScryfallCards.return_value.config.app_data = {
        "path_folder_static_file": "unused",
    }
    monkeypatch.setattr(selling, "_resolve_config_placeholder", Mock(return_value="unused"))
    monkeypatch.setattr(selling, "load_scryfall_bulk_data", Mock(return_value={}))
    # Fail at metadata before any mapping writes; audit captures every selected ID.
    selling.ApiServiceEchoMTGCardItem.return_value.get_card_meta.side_effect = RuntimeError("offline")
    audit = Mock()
    monkeypatch.setattr(selling, "_write_tcg_audit_csv", audit)
    return SimpleNamespace(inventory=inventory, cards=cards, audit=audit)


@pytest.mark.parametrize("limit", [1, 100])
def test_limited_mapping_requests_only_newest_tradable_inventory(mapping_services, limit):
    services = mapping_services
    assert inspect.unwrap(selling.generate_tcg_mappings)(limit=limit) == "SUCCESS"
    services.inventory.get_collection.assert_called_once_with(
        start=0, limit=limit, sort="i.id", direction="DESC", tradable_only=1,
    )
    services.inventory.get_all_collection.assert_not_called()
    rows = services.audit.call_args.args[1]
    assert [row["inventory_id"] for row in rows] == [
        str(i) for i in range(134, 134 - limit, -1)
    ]


@pytest.mark.parametrize("limit", [None, -1])
def test_unbounded_and_legacy_negative_mapping_preserve_full_inventory(mapping_services, limit):
    services = mapping_services
    assert inspect.unwrap(selling.generate_tcg_mappings)(limit=limit) == "SUCCESS"
    services.inventory.get_all_collection.assert_called_once_with(tradable_only=1)
    services.inventory.get_collection.assert_not_called()
    expected = services.cards if limit is None else services.cards[:limit]
    assert [row["inventory_id"] for row in services.audit.call_args.args[1]] == [
        card["inventory_id"] for card in expected
    ]


def test_zero_mapping_limit_does_not_read_inventory(mapping_services):
    services = mapping_services
    assert inspect.unwrap(selling.generate_tcg_mappings)(limit=0) == "SUCCESS"
    services.inventory.get_collection.assert_not_called()
    services.inventory.get_all_collection.assert_not_called()
    assert services.audit.call_args.args[1] == []


def test_limited_mapping_rejects_malformed_inventory_response(mapping_services):
    mapping_services.inventory.get_collection.side_effect = None
    mapping_services.inventory.get_collection.return_value = {"error": "missing items"}
    with pytest.raises(RuntimeError, match="inventory response is missing 'items'"):
        inspect.unwrap(selling.generate_tcg_mappings)(limit=100)
    mapping_services.audit.assert_not_called()
