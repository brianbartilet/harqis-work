"""Offline coverage of product listings; no credentials or marketplace writes.

Envelope/row shapes were observed on listed_item_filter (2026-10-14).
Fixture values are synthetic; merchant/account details are not recorded.
"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.tcg_mp.references.web.api.product import ApiServiceTcgMpProducts


@pytest.fixture
def service():
    config = SimpleNamespace(
        client="rest", parameters={"base_url": "https://marketplace.invalid/"},
        app_data={"category_id": 3, "token": "offline-token"},
        return_data_only=True,
    )
    return ApiServiceTcgMpProducts(config, client=Mock())


def envelope(rows, *, status=200, total=None):
    return {"status": status, "data": {"data": rows, "message": "fixture"},
            "meta": {"total": len(rows) if total is None else total}}


def test_listed_smoke_accepts_successful_empty_variant(service):
    # Reproduce a catalog hit whose particular nonfoil printing has no offers.
    from apps.tcg_mp.tests.test_product import test_product_listed as listed_smoke

    service.client.execute_request.side_effect = [
        SimpleNamespace(data={"data": [{"id": "348314", "name": "Underground River"}]}),
        SimpleNamespace(data=envelope([])),
    ]
    listed_smoke(service)
    assert service.client.execute_request.call_count == 2


# Field names and types match the observed populated response; values are fake.
OFFER = {
    "id": 101, "new_cpp_id": "433280", "source_region": "fixture",
    "user_id": 202, "merchant_new_user_id": "303", "details": None,
    "own_listing": 0, "merchant_id": 404, "merchant_name": "Fixture seller",
    "merchant_type": "fixture", "quantity": 2, "price": "1.25",
    "crd_condition": "NM", "crd_foil": "0", "crd_language": "English",
    "crd_signed": 0, "crd_altered": 0, "country_code": "SG",
    "avg_rating": 0, "listed": 1, "sales": 0, "front_img": None,
    "back_img": None, "crd_setcode": "FIX", "suspended": 0,
    "dropoff_available": 0,
}


@pytest.mark.parametrize("method", ["search_single_card_listings", "get_pricing_listings"])
@pytest.mark.parametrize("rows", [[], [OFFER]])
def test_listing_readers_preserve_rows_and_finish_scope(service, method, rows):
    from core.web.services.core.constants.http_methods import HttpMethod

    service.client.execute_request.return_value = SimpleNamespace(data=envelope(rows))
    read = getattr(service, method)
    # Reuse the real builder: paths/payloads must not accumulate between calls.
    assert read("433280") == rows
    assert read("433280", foil=1) == rows
    for call, finish in zip(service.client.execute_request.call_args_list, ["0", "1"]):
        request = call.args[0]
        assert request.get_request_method() == HttpMethod.POST
        assert request.get_full_url().strip("/") == "product/listed_item_filter"
        assert request.get_body() == {"json": {"foil": finish, "product_id": "433280"}}


@pytest.mark.parametrize("payload", [
    envelope([], status=500),
    envelope([OFFER], status=500),
    {"status": 200, "data": {"message": "fixture"}, "meta": {"total": 0}},
    envelope({}),
    envelope([OFFER], total=2),
    {"status": 200, "data": {"data": []}, "meta": {}},
    [],
], ids=["api-error-empty", "api-error-populated", "missing-rows", "object-not-rows",
        "partial-page", "missing-total", "non-object-envelope"])
def test_listed_smoke_rejects_api_errors_and_invalid_envelopes(service, payload):
    from apps.tcg_mp.tests.test_product import test_product_listed as listed_smoke

    service.client.execute_request.side_effect = [
        SimpleNamespace(data={"data": [{"id": "348314", "name": "Underground River"}]}),
        SimpleNamespace(data=payload),
    ]
    with pytest.raises(ValueError, match="Marketplace listing"):
        listed_smoke(service)


def test_listed_smoke_rejects_non_object_offer(service):
    from apps.tcg_mp.tests.test_product import test_product_listed as listed_smoke

    service.client.execute_request.side_effect = [
        SimpleNamespace(data={"data": [{"id": "348314", "name": "Underground River"}]}),
        SimpleNamespace(data=envelope(["not an offer"])),
    ]
    with pytest.raises(AssertionError):
        listed_smoke(service)


@pytest.mark.parametrize("method", ["search_single_card_listings", "get_pricing_listings"])
def test_listing_transport_failure_is_not_an_empty_result(service, method):
    service.client.execute_request.side_effect = TimeoutError("fixture timeout")
    with pytest.raises(TimeoutError, match="fixture timeout"):
        getattr(service, method)("348314")


def test_legacy_reader_preserves_explicit_raw_response_mode(service):
    service.config.return_data_only = False
    raw = SimpleNamespace(data=envelope([]))
    service.client.execute_request.return_value = raw
    assert service.search_single_card_listings("348314") is raw
