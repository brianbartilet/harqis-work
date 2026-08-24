from __future__ import annotations

from datetime import datetime, timezone

import pytest

from workflows.second_brain.models import ContextEvent, FeedItem
from workflows.second_brain.resolver import resolve_modes
from workflows.second_brain.store import SecondBrainStore


def test__reconcile_second_brain_live_jira():
    pytest.skip("Manual only — reads live Jira and writes canonical Second Brain state")


def test__context_event_is_deterministic_for_dedup_key():
    first = ContextEvent(source="desktop", event_type="activity", payload={"app": "Code"}, dedup_key="one")
    second = ContextEvent(source="desktop", event_type="activity", payload={"app": "Code"}, dedup_key="one")
    assert first.event_id == second.event_id


def test__store_deduplicates_context_and_versions_material_feed_changes(tmp_path):
    store = SecondBrainStore(tmp_path / "brain.sqlite3")
    event = ContextEvent(source="frontend", event_type="text_command", payload={"text": "jira"}, dedup_key="same")
    assert store.append_context(event) is True
    assert store.append_context(event) is False

    item = FeedItem(
        logical_key="jira:ABC-1",
        category="work",
        kind="jira_changed",
        title="ABC-1 · Review work",
        summary="In progress",
        allowed_clients=("web", "cli"),
    )
    persisted, changed = store.upsert_feed_item(item)
    assert changed is True
    assert persisted["revision"] == 1
    unchanged, changed = store.upsert_feed_item(item)
    assert changed is False
    assert unchanged["revision"] == 1

    updated = FeedItem(**{**item.__dict__, "summary": "Done"})
    persisted, changed = store.upsert_feed_item(updated)
    assert changed is True
    assert persisted["revision"] == 2
    assert store.feed_snapshot(client="web")["cursor"] == 2
    assert store.feed_snapshot(client="cli")["items"][0]["summary"] == "Done"


def test__manual_override_wins_and_expires_deterministically(tmp_path):
    store = SecondBrainStore(tmp_path / "brain.sqlite3")
    override = store.set_override(("play", "finance"), duration_minutes=30, correlation_id="corr")
    decision = resolve_modes(
        [{"event_type": "jira", "payload": {"text": "coding"}}],
        manual_override=store.active_override(),
        now=datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc),
        correlation_id="corr",
    )
    assert decision.detected_modes == ("work",)
    assert decision.effective_modes == ("play", "finance")
    assert decision.confidence == 1.0
    assert override["expires_at"]
    store.clear_override()
    assert store.active_override() is None


def test__client_configuration_keeps_web_enabled(tmp_path):
    store = SecondBrainStore(tmp_path / "brain.sqlite3")
    config = store.update_config(
        clients={"web": False, "telegram": True, "rainmeter": False, "cli": True},
        hermes_enabled=True,
    )
    assert config["clients"] == {
        "web": True,
        "telegram": True,
        "rainmeter": False,
        "cli": True,
    }
    assert config["hermes_enabled"] is True


def test__feed_store_refreshes_expiry_without_creating_revision(tmp_path):
    store = SecondBrainStore(tmp_path / "brain.sqlite3")
    first, first_changed = store.upsert_feed_item(
        FeedItem(
            logical_key="jira:ABC-1",
            category="work",
            kind="jira_changed",
            title="ABC-1 changed",
            summary="In progress",
            fresh_until="2026-08-24T10:00:00Z",
            expires_at="2026-08-25T10:00:00Z",
        )
    )
    refreshed, refreshed_changed = store.upsert_feed_item(
        FeedItem(
            logical_key="jira:ABC-1",
            category="work",
            kind="jira_changed",
            title="ABC-1 changed",
            summary="In progress",
            fresh_until="2026-08-24T10:15:00Z",
            expires_at="2026-08-25T10:15:00Z",
        )
    )

    assert first_changed is True
    assert refreshed_changed is False
    assert refreshed["revision"] == first["revision"]
    assert refreshed["fresh_until"] == "2026-08-24T10:15:00Z"


def test__feed_store_applies_limit_after_mode_filtering(tmp_path):
    store = SecondBrainStore(tmp_path / "brain.sqlite3")
    for index in range(3):
        store.upsert_feed_item(
            FeedItem(
                logical_key=f"finance:{index}",
                category="finance",
                kind="price",
                title=f"Finance {index}",
                summary="Changed",
                priority=100 - index,
            )
        )
    store.upsert_feed_item(
        FeedItem(
            logical_key="work:one",
            category="work",
            kind="jira_changed",
            title="Work item",
            summary="Changed",
            priority=10,
        )
    )

    snapshot = store.feed_snapshot(modes=("work",), limit=1)

    assert [item["logical_key"] for item in snapshot["items"]] == ["work:one"]
