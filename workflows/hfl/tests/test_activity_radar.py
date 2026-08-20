from datetime import datetime, timedelta, timezone

import pytest

from workflows.hfl.tasks import activity_radar as module


# Workflow integration: deliberately skipped because it reads private HFL data,
# calls Anthropic, and may notify Telegram when invoked as the scheduled task.
@pytest.mark.skip(reason="Manual only — reads live HFL and sends a Telegram notification for findings")
def test__activity_radar():
    module.activity_radar(cfg_id__anthropic="ANTHROPIC")


def _finding(severity="high", evidence=None):
    return {
        "findings": [{
            "category": "missed_commitments", "severity": severity, "confidence": "high",
            "title": "Verify release", "observation": "Verification was promised.",
            "inference": "It may still be open.", "recommendation": "Verify it.",
            "evidence": ["N1"] if evidence is None else evidence,
        }]
    }


def test__validate_findings_requires_evidence_for_high_severity():
    assert module.validate_findings(_finding(evidence=[]), {"N1"}) == []


def test__select_notifications_repeats_critical_but_suppresses_unchanged_lower():
    high = module.validate_findings(_finding(), {"N1"})[0]
    state = {"findings": {high["fingerprint"]: {"evidence_signature": high["evidence_signature"], "status": "open"}}}
    assert module.select_notifications([high], state) == []
    critical = {**high, "severity": "critical"}
    assert module.select_notifications([critical], state) == [critical]


def test__select_notifications_resurfaces_resolved_finding_on_new_evidence():
    finding = module.validate_findings(_finding(), {"N1"})[0]
    state = {"findings": {finding["fingerprint"]: {"evidence_signature": "old", "status": "resolved"}}}
    assert module.select_notifications([finding], state) == [finding]


def test__select_notifications_repeats_dismissed_critical_until_resolved():
    finding = module.validate_findings(_finding(severity="critical"), {"N1"})[0]
    state = {"findings": {finding["fingerprint"]: {"evidence_signature": finding["evidence_signature"], "status": "dismissed"}}}
    assert module.select_notifications([finding], state) == [finding]
    state["findings"][finding["fingerprint"]]["status"] = "resolved"
    assert module.select_notifications([finding], state) == []


def test__run_activity_radar_dry_run_does_not_advance_marker(tmp_path, monkeypatch):
    now = datetime(2026, 8, 20, 10, tzinfo=timezone.utc)
    row = {"when": (now - timedelta(hours=1)).isoformat(), "entry_id": "x", "source": "notes", "moment": "Release", "tags": []}
    monkeypatch.setattr(module, "retrieve_entries", lambda *a, **k: ([row], []))
    result = module.run_activity_radar(
        scheduled=True, dry_run=True, now=now, state_file=tmp_path / "state.json",
        synthesizer=lambda *a, **k: _finding(),
    )
    assert result["status"] == "findings"
    assert not (tmp_path / "state.json").exists()


def test__run_activity_radar_advances_marker_after_silent_success(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "retrieve_entries", lambda *a, **k: ([], []))
    path = tmp_path / "state.json"
    result = module.run_activity_radar(scheduled=True, now=datetime.now(timezone.utc), state_file=path)
    assert result["status"] == "no-findings"
    assert module.load_state(path)["last_success_at"]


def test__run_activity_radar_partial_fallback_does_not_advance_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "retrieve_entries", lambda *a, **k: ([], ["Elasticsearch unavailable"]))
    path = tmp_path / "state.json"
    result = module.run_activity_radar(scheduled=True, now=datetime.now(timezone.utc), state_file=path)
    assert result["status"] == "partial"
    assert module.load_state(path)["last_success_at"] is None


def test__bind_evidence_signatures_detects_changed_content():
    finding = module.validate_findings(_finding(), {"N1"})[0]
    module.bind_evidence_signatures([finding], {"N1": {"moment": "old"}})
    old_signature = finding["evidence_signature"]
    module.bind_evidence_signatures([finding], {"N1": {"moment": "changed"}})
    assert finding["evidence_signature"] != old_signature


def test__redact_secrets_preserves_context():
    text = module.redact_secrets("deploy token=abc123 and password: hunter2")
    assert "deploy" in text
    assert "abc123" not in text
    assert "hunter2" not in text


def test__record_activity_radar_feedback(tmp_path):
    path = tmp_path / "state.json"
    module.save_state({"version": 1, "findings": {"abc": {"status": "open"}}}, path)
    result = module.record_activity_radar_feedback("abc", "resolved", path=path)
    assert result["status"] == "resolved"
    assert module.load_state(path)["findings"]["abc"]["status"] == "resolved"
