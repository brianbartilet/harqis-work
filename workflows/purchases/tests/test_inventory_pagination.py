"""Exercise the real radar inventory-read path without network or writes."""
import inspect
from unittest.mock import Mock

import pytest

from apps.echo_mtg.references.web.api.inventory import ApiServiceEchoMTGInventory
import workflows.purchases.tasks.sold_inventory_radar as radar


def test_radar_counts_copies_from_every_inventory_page(monkeypatch):
    cards = [{"inventory_id": str(i), "emid": "same-card", "foil": 0, "note_id": "note-1"} for i in range(1414)]
    inventory = object.__new__(ApiServiceEchoMTGInventory)
    inventory.get_collection = Mock(side_effect=lambda **kw: cards[kw.get("start", 0):kw.get("start", 0) + 1000])
    monkeypatch.setattr(radar, "CONFIG_MANAGER", Mock())
    for name in ["ApiServiceTcgMpOrder", "ApiServiceTcgMpUserView", "ApiServiceTcgMpPublish",
                 "ApiServiceEchoMTGNotes", "ApiServiceEchoMTGEarnings"]:
        service = Mock()
        service.get_listings.return_value = []
        monkeypatch.setattr(radar, name, Mock(return_value=service))
    monkeypatch.setattr(radar, "ApiServiceEchoMTGInventory", Mock(return_value=inventory))
    monkeypatch.setattr(radar, "_gather_live_order_details", Mock(return_value={}))

    class ReadVerified(Exception):
        pass

    original_counts = radar._owned_counts

    def check_counts(items):
        assert original_counts(items) == {("same-card", 0): 1414}
        raise ReadVerified  # Stop before notes, review-file writes, or actions.

    monkeypatch.setattr(radar, "_owned_counts", check_counts)
    with pytest.raises(ReadVerified):
        inspect.unwrap(radar.radar_sold_inventory)(dry_run=True, source="live", limit=1)
