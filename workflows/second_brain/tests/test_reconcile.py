from workflows.second_brain.models import FeedItem
from workflows.second_brain.registry import OperationSpec
from workflows.second_brain.store import SecondBrainStore
from workflows.second_brain.tasks import reconcile as module


def test__reconcile_persists_partial_results_without_hermes(tmp_path, monkeypatch):
    store = SecondBrainStore(tmp_path / "brain.sqlite3")
    store.set_override(("default",), duration_minutes=30, correlation_id="corr")
    operation = OperationSpec("test.fake", "tests.fake.collect")
    monkeypatch.setattr(module, "selected_operations", lambda modes, definitions: ((operation, ("default",), 15),))
    monkeypatch.setattr(module, "_current_calendar_signal", lambda: None)
    monkeypatch.setattr(
        module,
        "_load_callable",
        lambda path: lambda **kwargs: [
            FeedItem(
                logical_key="test:one",
                category="work",
                kind="test",
                title="One useful signal",
                summary="Fresh",
            )
        ],
    )
    monkeypatch.setattr(module, "publish_feed_change", lambda payload: "disabled")
    result = module.reconcile(store=store, correlation_id="corr")
    assert result["effective_modes"] == ["default"]
    assert result["agent_state"] == "disabled"
    assert result["changed"] == 1
    assert result["failures"] == []
    assert store.feed_snapshot()["items"][0]["title"] == "One useful signal"


def test__reconcile_isolates_collector_failure(tmp_path, monkeypatch):
    store = SecondBrainStore(tmp_path / "brain.sqlite3")
    operation = OperationSpec("test.fake", "tests.fake.collect")
    monkeypatch.setattr(module, "selected_operations", lambda modes, definitions: ((operation, ("default",), 15),))
    monkeypatch.setattr(module, "_current_calendar_signal", lambda: None)

    def fail(_path):
        def collector(**_kwargs):
            raise ConnectionError("source unavailable")
        return collector

    monkeypatch.setattr(module, "_load_callable", fail)
    result = module.reconcile(store=store, correlation_id="corr")
    assert result["changed"] == 1
    assert result["failures"] == [{"operation_id": "test.fake", "error_type": "ConnectionError"}]
    assert store.feed_snapshot()["items"][0]["status"] == "degraded"


def test__reconcile_retires_items_after_an_operation_is_detached(tmp_path, monkeypatch):
    from workflows.second_brain.models import ModeDefinition

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
    store.save_mode(ModeDefinition(mode_id="default", name="Default", operation_ids=()))
    published = []
    monkeypatch.setattr(module, "_current_calendar_signal", lambda: None)
    monkeypatch.setattr(module, "publish_feed_change", published.append)

    result = module.reconcile(store=store, correlation_id="corr")

    assert result["retired"] == 1
    assert result["changed"] == 1
    assert store.feed_snapshot()["items"] == []
    assert published[0]["status"] == "retired"
