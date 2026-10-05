"""Offline regression tests: never authenticate or mutate live inventory."""
from unittest.mock import Mock

import pytest

from apps.echo_mtg.references.web.api.inventory import ApiServiceEchoMTGInventory


def test_full_collection_includes_cards_after_server_page_cap():
    service = object.__new__(ApiServiceEchoMTGInventory)
    cards = [{"inventory_id": str(i)} for i in range(1414)]
    service.get_collection = Mock(side_effect=[cards[:1000], cards[1000:], []])

    assert service.get_all_collection(tradable_only=1) == cards
    assert [call.kwargs["start"] for call in service.get_collection.call_args_list] == [0, 1000, 1414]
    assert all(call.kwargs == {
        "start": start, "limit": 1000, "sort": "i.id", "direction": "ASC", "tradable_only": 1,
    } for call, start in zip(service.get_collection.call_args_list, [0, 1000, 1414]))


@pytest.mark.parametrize("bad_page", [None, {}, {"error": "unavailable"}, [None], [{}]])
def test_invalid_later_page_does_not_return_partial_inventory(bad_page):
    service = object.__new__(ApiServiceEchoMTGInventory)
    service.get_collection = Mock(side_effect=[[{"inventory_id": "1"}], bad_page, []])
    with pytest.raises(ValueError, match="EchoMTG"):
        service.get_all_collection()


def test_later_page_exception_propagates():
    service = object.__new__(ApiServiceEchoMTGInventory)
    service.get_collection = Mock(side_effect=[[{"inventory_id": "1"}], RuntimeError("offline")])
    with pytest.raises(RuntimeError, match="offline"):
        service.get_all_collection()


@pytest.mark.parametrize("pages", [
    [[{"inventory_id": "1"}], [{"inventory_id": 1}], []],
    [[{"inventory_id": "1"}, {"inventory_id": "1"}], []],
])
def test_repeated_inventory_ids_abort_instead_of_double_counting(pages):
    service = object.__new__(ApiServiceEchoMTGInventory)
    service.get_collection = Mock(side_effect=pages)
    with pytest.raises(ValueError, match="repeated"):
        service.get_all_collection()


def test_safety_bound_raises_instead_of_silently_truncating():
    service = object.__new__(ApiServiceEchoMTGInventory)
    service.get_collection = Mock(side_effect=[
        [{"inventory_id": "1"}, {"inventory_id": "2"}],
        [{"inventory_id": "3"}], [],
    ])
    with pytest.raises(ValueError, match="max_items"):
        service.get_all_collection(max_items=2)


@pytest.mark.parametrize("count", [0, 1000, 2000, 10001])
def test_empty_exact_multiple_and_large_collections(count):
    service = object.__new__(ApiServiceEchoMTGInventory)
    cards = [{"inventory_id": str(i)} for i in range(count)]
    service.get_collection = Mock(side_effect=lambda **kw: cards[kw["start"]:kw["start"] + kw["limit"]])
    assert service.get_all_collection(tradable_only=0) == cards
    assert all(c.kwargs["tradable_only"] == 0 for c in service.get_collection.call_args_list)
