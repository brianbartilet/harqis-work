from __future__ import annotations

from datetime import datetime, timezone

import pytest

from workflows.second_brain.models import ContextEvent, FeedItem, ModeDefinition
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
    store.save_mode(ModeDefinition(mode_id="deep-work", name="Deep Work", keywords=("coding",)))
    override = store.set_override(("deep-work",), duration_minutes=30, correlation_id="corr")
    decision = resolve_modes(
        [{"event_type": "jira", "payload": {"text": "coding"}}],
        mode_definitions=store.list_modes(),
        manual_override=store.active_override(),
        now=datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc),
        correlation_id="corr",
    )
    assert set(decision.detected_modes) == {"default", "deep-work"}
    assert decision.effective_modes == ("deep-work",)
    assert decision.confidence == 1.0
    assert override["expires_at"]
    store.clear_override()
    assert store.active_override() is None


def test__active_override_is_revoked_when_its_category_becomes_disabled(tmp_path):
    store = SecondBrainStore(tmp_path / "brain.sqlite3")
    store.save_mode(ModeDefinition(mode_id="notes", name="Notes"))
    store.set_override(("notes",), duration_minutes=30, correlation_id="corr")

    store.save_mode(ModeDefinition(mode_id="notes", name="Notes", enabled=False))

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


def test__categories_are_configurable_and_default_cannot_be_archived(tmp_path):
    store = SecondBrainStore(tmp_path / "brain.sqlite3")
    saved = store.save_mode(
        ModeDefinition(
            mode_id="tabletop",
            name="Tabletop Lab",
            color="#a78bfa",
            keywords=("mtg", "deck"),
            calendar_categories=("Mischief | Misdirection | Play",),
        )
    )
    assert {mode["mode_id"] for mode in saved["modes"]} == {"default", "tabletop"}
    with pytest.raises(ValueError, match="default"):
        store.archive_mode("default")


def test__overnight_fallback_window_resolves_category():
    local_tz = datetime.now().astimezone().tzinfo
    decision = resolve_modes(
        [],
        mode_definitions=[
            ModeDefinition(mode_id="default", name="Default").to_payload(),
            ModeDefinition(
                mode_id="night-owl",
                name="Night Owl",
                fallback_windows=({"start": "22:00", "end": "03:00", "days": [0]},),
            ).to_payload(),
        ],
        now=datetime(2026, 8, 24, 23, 0, tzinfo=local_tz),
        correlation_id="overnight",
    )
    assert decision.effective_modes == ("night-owl",)


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


def test__feed_store_retires_detached_operation_items_and_preserves_attached_items(tmp_path):
    store = SecondBrainStore(tmp_path / "brain.sqlite3")
    store.upsert_feed_item(
        FeedItem(
            logical_key="default:jira.changed:jira:ABC-1",
            category="default",
            kind="jira_changed",
            title="ABC-1 changed",
            summary="In progress",
            operation_id="jira.changed",
        )
    )
    store.upsert_feed_item(
        FeedItem(
            logical_key="default:hud.daily_radar:hud-projection:hud.daily_radar",
            category="default",
            kind="hud_projection",
            title="Daily radar",
            summary="Ready",
            operation_id="hud.daily_radar",
        )
    )

    retired = store.retire_feed_items({("default", "hud.daily_radar")})

    assert [item["logical_key"] for item in retired] == ["default:jira.changed:jira:ABC-1"]
    assert retired[0]["status"] == "retired"
    assert retired[0]["retirement_reason"] == "configuration_changed"
    assert [item["title"] for item in store.feed_snapshot()["items"]] == ["Daily radar"]


def test__feed_store_retires_legacy_items_by_category_prefixed_logical_key(tmp_path):
    store = SecondBrainStore(tmp_path / "brain.sqlite3")
    store.upsert_feed_item(
        FeedItem(
            logical_key="default:jira.changed:jira:ABC-1",
            category="default",
            kind="jira_changed",
            title="ABC-1 changed",
            summary="In progress",
        )
    )

    retired = store.retire_feed_items(set())

    assert retired[0]["operation_id"] == "jira.changed"
    assert store.feed_snapshot()["items"] == []


def test__successful_operation_is_not_due_until_refresh_interval(tmp_path):
    store = SecondBrainStore(tmp_path / "brain.sqlite3")
    assert store.operation_due("jira.changed", 30) is True
    store.start_run(run_id="run-1", operation_id="jira.changed", correlation_id="corr")
    store.finish_run(run_id="run-1", state="success", result={"items": 0})
    assert store.operation_due("jira.changed", 30) is False


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
