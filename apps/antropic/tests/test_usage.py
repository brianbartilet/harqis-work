import os
import pytest
from datetime import datetime, timezone
from hamcrest import assert_that, instance_of, greater_than_or_equal_to, not_none

from apps.antropic.references.web.api.usage import ApiServiceAnthropicUsage, _estimate_cost, _get_pricing
from apps.antropic.references.dto.usage import DtoAnthropicUsageSummary, DtoAnthropicUsageEntry
from apps.antropic.config import CONFIG

_has_admin_key = bool(os.environ.get("ANTHROPIC_ADMIN_KEY"))
_skip_no_admin = pytest.mark.skipif(
    not _has_admin_key,
    reason="ANTHROPIC_ADMIN_KEY not set — skipping live usage API tests. "
           "Get an admin key at https://console.anthropic.com/settings/keys",
)


@pytest.fixture()
def given():
    return ApiServiceAnthropicUsage(CONFIG)


# ── Pricing unit tests (offline) ─────────────────────────────────────────────

def test_pricing_sonnet():
    inp, out, cw, cr = _get_pricing("claude-sonnet-4-6")
    assert inp == 3.00
    assert out == 15.00


def test_pricing_opus():
    inp, out, _, _ = _get_pricing("claude-opus-4")
    assert inp == 15.00


def test_pricing_unknown_falls_back():
    inp, out, _, _ = _get_pricing("unknown-model-xyz")
    assert inp == 3.00  # falls back to Sonnet 4 pricing


def test_cost_estimate_zero_tokens():
    entry = DtoAnthropicUsageEntry(model="claude-sonnet-4-6", input_tokens=0, output_tokens=0)
    assert _estimate_cost(entry) == 0.0


def test_cost_estimate_1m_input():
    entry = DtoAnthropicUsageEntry(model="claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=0)
    assert _estimate_cost(entry) == pytest.approx(3.00, abs=0.001)


def test_cost_estimate_1m_output():
    entry = DtoAnthropicUsageEntry(model="claude-sonnet-4-6", input_tokens=0, output_tokens=1_000_000)
    assert _estimate_cost(entry) == pytest.approx(15.00, abs=0.001)


# ── Live API tests (require ANTHROPIC_ADMIN_KEY) ─────────────────────────────

@_skip_no_admin
@pytest.mark.smoke
def test_get_month_to_date_returns_summary(given):
    when = given.get_month_to_date()
    assert_that(when, instance_of(DtoAnthropicUsageSummary))
    assert_that(when.start_time, not_none())
    assert_that(when.end_time, not_none())
    assert_that(when.total_input_tokens, greater_than_or_equal_to(0))
    assert_that(when.total_output_tokens, greater_than_or_equal_to(0))
    assert_that(when.estimated_total_cost_usd, greater_than_or_equal_to(0.0))


@_skip_no_admin
@pytest.mark.smoke
def test_get_month_to_date_start_is_first_of_month(given):
    when = given.get_month_to_date()
    start = datetime.fromisoformat(when.start_time.replace("Z", "+00:00"))
    assert start.day == 1


@_skip_no_admin
@pytest.mark.sanity
def test_get_usage_explicit_range(given):
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    when = given.get_usage(
        start_time=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        end_time=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    assert_that(when, instance_of(DtoAnthropicUsageSummary))
    assert_that(when.by_model, instance_of(list))


@_skip_no_admin
@pytest.mark.sanity
def test_by_model_entries_have_cost(given):
    when = given.get_month_to_date()
    for entry in when.by_model:
        assert_that(entry.model, not_none())
        assert entry.estimated_cost_usd is not None
        assert entry.estimated_cost_usd >= 0.0


# ── Cost report (actual billed USD) — offline, mocked transport ──────────────

class _FakeResp:
    """Minimal stand-in for an httpx.Response used by ApiServiceAnthropicUsage._get."""
    def __init__(self, payload, ok=True, status=200):
        self._payload = payload
        self.is_success = ok
        self.status_code = status
        self.text = str(payload)

    def json(self):
        return self._payload


def test_get_cost_by_model_parses_cents_and_aggregates(given, monkeypatch):
    """amount is cents (÷100); per-model aggregated across pages; null model → 'other'."""
    page1 = {"data": [{"results": [
        {"amount": "5232.96", "currency": "USD", "model": "claude-sonnet-4-6"},
        {"amount": "100.00",  "currency": "USD", "model": None},
    ]}], "has_more": True, "next_page": "PAGE2"}
    page2 = {"data": [{"results": [
        {"amount": "1786.00", "currency": "USD", "model": "claude-haiku-4-5-20251001"},
        {"amount": "1000.00", "currency": "USD", "model": "claude-sonnet-4-6"},
    ]}], "has_more": False}

    def fake_get(url, headers=None, params=None, timeout=None):
        page = dict(params or []).get("page")
        return _FakeResp(page2 if page == "PAGE2" else page1)

    monkeypatch.setattr("apps.antropic.references.web.api.usage.httpx.get", fake_get)
    out = given.get_cost_by_model("2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z")

    assert out["claude-sonnet-4-6"] == pytest.approx(62.3296)          # (5232.96+1000)/100
    assert out["claude-haiku-4-5-20251001"] == pytest.approx(17.86)
    assert out["other"] == pytest.approx(1.0)                          # null-model bucket


def test_get_cost_by_model_skips_zero(given, monkeypatch):
    payload = {"data": [{"results": [
        {"amount": "0", "currency": "USD", "model": "claude-opus-4-7"},
    ]}], "has_more": False}
    monkeypatch.setattr("apps.antropic.references.web.api.usage.httpx.get",
                        lambda *a, **k: _FakeResp(payload))
    out = given.get_cost_by_model("2026-05-01T00:00:00Z")
    assert "claude-opus-4-7" not in out


def test_parse_summary_reads_nested_cache_creation(given):
    """Live usage report nests cache-creation tokens — must not be dropped to 0."""
    data = {"data": [{"results": [
        {"model": "claude-sonnet-4-6", "uncached_input_tokens": 1000,
         "output_tokens": 50, "cache_read_input_tokens": 200,
         "cache_creation": {"ephemeral_5m_input_tokens": 489496,
                            "ephemeral_1h_input_tokens": 10}},
    ]}]}
    summary = given._parse_summary(data, "s", "e")
    assert summary.total_cache_creation_tokens == 489506


def test_parse_summary_legacy_flat_cache_creation(given):
    """Backward-compat: older flat cache_creation_input_tokens still parsed."""
    data = {"data": [
        {"model": "claude-sonnet-4-6", "input_tokens": 100,
         "cache_creation_input_tokens": 777},
    ]}
    summary = given._parse_summary(data, "s", "e")
    assert summary.total_cache_creation_tokens == 777
