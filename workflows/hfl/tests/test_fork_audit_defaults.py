"""Instance-safe defaults used by the fork Activity Corpus scaffold."""

from scripts.agents.hfl import capture_session_event
from workflows.hfl import persistence
from workflows.hfl.distill import parse_model_json
from workflows.hfl.tasks import capture


def test_activity_paths_follow_instance_data_root(monkeypatch, tmp_path):
    from apps.apps_config import CONFIG_MANAGER

    monkeypatch.setattr(CONFIG_MANAGER, "get", lambda *_args, **_kwargs: None)
    monkeypatch.delenv("HFL_CORPUS_PATH", raising=False)
    monkeypatch.delenv("HFL_OUTBOX_PATH", raising=False)
    monkeypatch.delenv("HFL_SESSION_AUDIT_PATH", raising=False)
    monkeypatch.setenv("HARQIS_DATA_ROOT", str(tmp_path))

    assert capture.resolve_corpus_dir() == (tmp_path / "activity-corpus").resolve()
    assert persistence.outbox_dir() == (tmp_path / "runtime" / "hfl-outbox").resolve()
    assert capture_session_event.audit_root() == (
        tmp_path / "runtime" / "hfl-session-audit"
    ).resolve()


def test_canonical_hfl_machine_is_configurable(monkeypatch):
    monkeypatch.setenv("HFL_CANONICAL_MACHINE", "alam-host")
    assert persistence.is_canonical_machine("alam-host")
    assert not persistence.is_canonical_machine("harqis-server")


def test_distill_json_parser_has_no_source_specific_dependency():
    assert parse_model_json('```json\n{"moment": "Shipped"}\n```') == {
        "moment": "Shipped"
    }
    assert parse_model_json("not-json") == {}
