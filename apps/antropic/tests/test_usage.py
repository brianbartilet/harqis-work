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
