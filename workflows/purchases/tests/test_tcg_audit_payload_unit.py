"""No-network audit storage and legacy-reader regressions."""
import copy
import inspect
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import workflows.purchases.tasks.tcg_mp_selling as selling
import workflows.purchases.tasks.sold_inventory_radar as radar


@pytest.mark.parametrize("merchant_id", [123, "USR-SG-005596", None])
@pytest.mark.parametrize("old_status", [None, "previous-status", "Dropped Off"])
def test_audit_preserves_payload_without_dynamic_object_mapping(monkeypatch, merchant_id, old_status):
    detail = {"id": 42, "order_id": "00042", "status": 6,
              "merchant_id": merchant_id, "items": [{"id": "abc", "metadata": {"new": [1, "two"]}}]}
    original = copy.deepcopy(detail)
    service = Mock()
    service.get_orders.side_effect = [[SimpleNamespace(data=[{"id": 42, "order_id": "00042"}])]] + [[]] * 8
    service.get_order_detail.return_value = detail
    monkeypatch.setattr(selling, "CONFIG_MANAGER", Mock())
    monkeypatch.setattr(selling, "ApiServiceTcgMpOrder", Mock(return_value=service))
    monkeypatch.setattr(selling, "get_index_data", Mock(return_value=[] if old_status is None else [{"current_status": old_status}]))
    writes = []

    def post(**kwargs):
        doc = kwargs["json_dump"]
        # Existing indices dynamically mapped merchant_id as long. Do not put
        # evolving provider objects back through that mapping, even for ints.
        assert "last_raw_payload" not in doc
        assert "raw_payload" not in doc
        field = "last_raw_payload_json" if kwargs["index_name"] == "tcg-mp-audit-current" else "raw_payload_json"
        assert json.loads(doc[field]) == original
        writes.append(kwargs)

    monkeypatch.setattr(selling, "post", post)
    inspect.unwrap(selling.generate_audit_for_tcg_orders)()
    if old_status == "Dropped Off":
        assert writes == []  # Unchanged orders retain legacy documents without new events.
    else:
        assert {w["index_name"] for w in writes} == {"tcg-mp-audit-current", "tcg-mp-status-audit"}
        assert len(writes) == 2
    assert detail == original


@pytest.mark.parametrize("encoding", ["legacy", "json"])
def test_radar_reads_both_audit_payload_formats(monkeypatch, encoding):
    payload = {"order_id": "00042", "status": 6, "merchant_id": "USR-SG-005596", "items": []}
    field, value = ("last_raw_payload", payload) if encoding == "legacy" else ("last_raw_payload_json", json.dumps(payload))
    monkeypatch.setattr(radar, "get_index_data", Mock(return_value=[{field: value, "current_status": "Dropped Off"}]))
    assert radar._gather_es_order_details({"Dropped Off"}) == {"00042": payload}


def test_radar_skips_corrupt_json_without_losing_other_orders(monkeypatch):
    payload = {"order_id": "00042", "status": 6, "items": []}
    docs = [{"last_raw_payload_json": value, "current_status": "Dropped Off"} for value in ("{broken", "[]", "null", json.dumps(payload))]
    monkeypatch.setattr(radar, "get_index_data", Mock(return_value=docs))
    assert radar._gather_es_order_details({"Dropped Off"}) == {"00042": payload}
