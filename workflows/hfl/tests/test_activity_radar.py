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
            "status": "open",
            "latest_evidence": ["N1"],
            "resolution_check": "N1 is the newest relevant evidence and records no outcome.",
        }]
    }


def test__validate_findings_requires_evidence_for_high_severity():
    assert module.validate_findings(_finding(evidence=[]), {"N1"}) == []


@pytest.mark.parametrize("status", ["resolved", "uncertain", ""])
def test__validate_findings_suppresses_high_priority_items_not_proven_open(status):
    raw = _finding(severity="critical")
    raw["findings"][0]["status"] = status

    assert module.validate_findings(raw, {"N1"}) == []


def test__validate_findings_requires_latest_recent_evidence_for_high_priority():
    raw = _finding()
    raw["findings"][0]["evidence"] = ["H46"]
    raw["findings"][0]["latest_evidence"] = ["H46"]

    assert module.validate_findings(raw, {"H46"}) == []


def test__validate_findings_rejects_claimed_latest_evidence_when_newer_evidence_exists():
    raw = _finding()
    raw["findings"][0]["evidence"] = ["N1", "N2"]
    raw["findings"][0]["latest_evidence"] = ["N1"]
    lookup = {
        "N1": {"when": "2026-08-14T10:00:00+00:00"},
        "N2": {"when": "2026-08-14T20:00:00+00:00"},
    }

    assert module.validate_findings(raw, set(lookup), lookup=lookup) == []

    raw["findings"][0]["latest_evidence"] = ["N2"]
    assert len(module.validate_findings(raw, set(lookup), lookup=lookup)) == 1


def test__validate_findings_keeps_resolved_item_below_notification_threshold():
    raw = _finding(severity="medium")
    raw["findings"][0]["status"] = "resolved"
    raw["findings"][0]["latest_evidence"] = ["H2"]
    raw["findings"][0]["evidence"] = ["H1", "H2"]
    raw["findings"][0]["resolution_check"] = "H2 records the merged fix and passing tests."

    findings = module.validate_findings(raw, {"H1", "H2"})

    assert len(findings) == 1
    assert findings[0]["severity"] == "medium"
    assert findings[0]["status"] == "resolved"


def test__activity_radar_prompt_requires_latest_status_resolution_check():
    prompt = module.load_prompt("activity_radar")

    assert '"status":"open|resolved|uncertain"' in prompt
    assert '"latest_evidence"' in prompt
    assert '"resolution_check"' in prompt
    assert "Mere recent activity on the same broad topic is insufficient." in prompt


def test__evidence_rows_redacts_source_and_tags_before_downstream_use():
    evidence, lookup = module._evidence_rows(
        [
            {
                "when": "2026-08-20T10:00:00+00:00",
                "source": "notes token=private-value",
                "tags": ["api_key=secret-value", "activity-radar"],
                "moment": "Current status",
            }
        ],
        [],
    )

    assert "private-value" not in str(evidence)
    assert "secret-value" not in str(evidence)
    assert lookup["N1"]["source"] == "notes token=[REDACTED]"
    assert lookup["N1"]["tags"] == ["api_key=[REDACTED]", "activity-radar"]

    markdown = module.render_markdown(
        module.validate_findings(_finding(), {"N1"}), lookup
    )
    assert "private-value" not in markdown
    assert "secret-value" not in markdown


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


def test__select_notifications_surfaces_finding_promoted_to_high_priority():
    finding = module.validate_findings(_finding(severity="high"), {"N1"})[0]
    state = {
        "findings": {
            finding["fingerprint"]: {
                "evidence_signature": finding["evidence_signature"],
                "severity": "medium",
                "status": "open",
            }
        }
    }

    assert module.select_notifications([finding], state) == [finding]


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


def test__run_activity_radar_notification_failure_does_not_advance_marker(tmp_path, monkeypatch):
    now = datetime(2026, 8, 20, 10, tzinfo=timezone.utc)
    row = {"when": (now - timedelta(hours=1)).isoformat(), "entry_id": "x", "source": "notes", "moment": "Release", "tags": []}
    monkeypatch.setenv("HFL_CORPUS_WEB_URL", "https://harqis.example")
    monkeypatch.setattr(module, "retrieve_entries", lambda *a, **k: ([row], []))
    monkeypatch.setattr(
        module,
        "_writeback",
        lambda *a, **k: {
            "delivery": "persisted",
            "path": "/corpus/2026-08-20.md",
            "entry_id": "hfl-radar",
        },
    )
    monkeypatch.setattr(module, "_notify", lambda _text: (_ for _ in ()).throw(RuntimeError("Telegram rejected request")))
    path = tmp_path / "state.json"

    with pytest.raises(RuntimeError, match="Telegram rejected request"):
        module.run_activity_radar(
            scheduled=True, now=now, state_file=path,
            synthesizer=lambda *a, **k: _finding(),
        )

    assert not path.exists()


def test__scheduled_radar_with_material_findings_and_notify_disabled_does_not_advance_marker(
    tmp_path, monkeypatch,
):
    now = datetime(2026, 8, 20, 10, tzinfo=timezone.utc)
    row = {
        "when": (now - timedelta(hours=1)).isoformat(),
        "entry_id": "x",
        "source": "notes",
        "moment": "Release",
        "tags": [],
    }
    monkeypatch.setenv("HFL_CORPUS_WEB_URL", "https://harqis.example")
    monkeypatch.setattr(module, "retrieve_entries", lambda *a, **k: ([row], []))
    monkeypatch.setattr(
        module,
        "_writeback",
        lambda *a, **k: {
            "delivery": "persisted",
            "path": "/corpus/2026-08-20.md",
            "entry_id": "hfl-radar",
        },
    )
    path = tmp_path / "state.json"

    result = module.run_activity_radar(
        scheduled=True,
        notify=False,
        now=now,
        state_file=path,
        synthesizer=lambda *a, **k: _finding(),
    )

    assert result["status"] == "findings"
    assert not path.exists()


def test__render_telegram_message_is_compact_and_scannable():
    findings = module.validate_findings(
        {
            "findings": [
                {
                    "category": "critical_risks",
                    "severity": "critical",
                    "confidence": "high",
                    "title": "Production backup is failing",
                    "observation": "The latest backup ended with an error.",
                    "inference": "Recovery coverage may be incomplete.",
                    "recommendation": "Repair the backup and run a restore check.",
                    "evidence": ["N1"],
                    "status": "open",
                    "latest_evidence": ["N1"],
                    "resolution_check": "N1 is the latest backup outcome.",
                },
                {
                    "category": "missed_commitments",
                    "severity": "high",
                    "confidence": "medium",
                    "title": "Release verification remains open",
                    "observation": "Verification was promised but no outcome was recorded.",
                    "inference": "The check may have been missed.",
                    "recommendation": "Verify the release and record the result.",
                    "evidence": ["N2"],
                    "status": "open",
                    "latest_evidence": ["N2"],
                    "resolution_check": "N2 contains no verification outcome.",
                },
            ]
        },
        {"N1", "N2"},
    )

    lookup = {
        "N1": {
            "when": "2026-08-20T09:00:00+00:00",
            "source": "backup",
            "moment": "Nightly backup failed",
        },
        "N2": {
            "when": "2026-08-20T10:00:00+00:00",
            "source": "agent-session",
            "moment": "Release verification promised",
        },
    }
    text = module.render_telegram_message(findings, lookup=lookup)

    assert text.startswith("HFL ACTIVITY RADAR\n2 HIGH-PRIORITY FINDINGS")
    assert "1. 🚨 CRITICAL — Production backup is failing" in text
    assert "2. ⚠️ HIGH — Release verification remains open" in text
    assert "WHAT: The latest backup ended with an error." in text
    assert "WHY: Recovery coverage may be incomplete." in text
    assert "NEXT: Repair the backup and run a restore check." in text
    assert "SOURCE: Aug 20 backup — Nightly backup failed" in text
    assert "SOURCE: N1" not in text
    assert "confidence" not in text
    assert "## Evidence" not in text
    assert "**" not in text
    assert findings[0]["fingerprint"] not in text


def test__render_telegram_message_never_ends_fields_with_opaque_ellipsis():
    raw = _finding()
    raw["findings"][0]["observation"] = (
        "A long but clear sentence describing the current issue in enough detail. "
        + "Additional context " * 30
    )
    finding = module.validate_findings(raw, {"N1"})

    text = module.render_telegram_message(
        finding,
        lookup={
            "N1": {
                "when": "2026-08-20T10:00:00+00:00",
                "source": "notes",
                "moment": "A concrete current record",
            }
        },
    )

    assert "…" not in text
    assert "WHAT: A long but clear sentence describing the current issue in enough detail." in text


def test__render_telegram_message_redacts_sensitive_source_metadata():
    finding = module.validate_findings(_finding(), {"N1"})

    text = module.render_telegram_message(
        finding,
        lookup={
            "N1": {
                "when": "2026-08-20T10:00:00+00:00",
                "source": "notes token=private-value",
                "moment": "Current status",
            }
        },
    )

    assert "private-value" not in text
    assert "[REDACTED]" in text


def test__compact_plain_text_never_exceeds_requested_limit():
    assert len(module._compact_plain_text("x" * 100, limit=20)) <= 20


def test__render_telegram_message_caps_and_normalizes_mobile_output():
    findings = module.validate_findings(
        {
            "findings": [
                {
                    **_finding(severity="high")["findings"][0],
                    "title": f"Finding {index} " + ("T" * 180),
                    "observation": "first line\nsecond line " + ("O" * 300),
                    "inference": "",
                    "recommendation": "",
                }
                for index in range(6)
            ]
        },
        {"N1"},
    )

    text = module.render_telegram_message(findings, max_findings=4)
    archive_text = module.render_telegram_message(findings)

    assert "6 HIGH-PRIORITY FINDINGS (SHOWING 4)" in text
    assert "MORE: 2 additional findings are in the linked HFL entry." in text
    assert text.count("WHAT:") == 4
    assert text.count("WHY: Not provided.") == 4
    assert text.count("NEXT: Not provided.") == 4
    assert "first line second line" in text
    assert "Finding 4" not in text
    assert "Finding 4" in archive_text
    assert "Finding 5" in archive_text
    assert len(text) < 3900
    assert len(text) + len("\n\nCORPUS: ") + 320 + len(
        "/hfl-corpus/document/2026-08-20.md"
    ) < 3900


def test__render_telegram_message_stays_single_chunk_at_worst_case_size():
    raw = {
        "findings": [
            {
                **_finding()["findings"][0],
                "title": f"Finding {index} " + "T" * 200,
                "observation": "O" * 400,
                "inference": "I" * 400,
                "recommendation": "R" * 400,
                "evidence": [f"N{index}"],
                "latest_evidence": [f"N{index}"],
            }
            for index in range(1, 5)
        ]
    }
    valid_ids = {f"N{index}" for index in range(1, 5)}
    findings = module.validate_findings(raw, valid_ids)
    lookup = {
        eid: {
            "when": "2026-08-20T10:00:00+00:00",
            "source": "source-" + "S" * 80,
            "moment": "M" * 300,
        }
        for eid in valid_ids
    }

    text = module.render_telegram_message(
        findings,
        degraded=["D" * 300, "E" * 300, "F" * 300],
        max_findings=4,
        lookup=lookup,
    )
    delivered = text + "\n\nCORPUS: " + "https://" + "x" * 312

    assert len(delivered) < 3900


def test__scheduled_dedup_key_changes_after_marker_or_day_advance():
    now = datetime(2026, 8, 20, 10, tzinfo=timezone.utc)
    first = module.scheduled_dedup_key({"last_success_at": None}, now)
    retry = module.scheduled_dedup_key({"last_success_at": None}, now)
    next_run = module.scheduled_dedup_key(
        {"last_success_at": "2026-08-20T10:00:00+00:00"}, now
    )
    next_day = module.scheduled_dedup_key(
        {"last_success_at": None}, now + timedelta(days=1)
    )

    assert first == retry
    assert next_run != first
    assert next_day != first


@pytest.mark.parametrize(
    "origin",
    [
        "https://:secret@example.com",
        "https://@example.com",
        "https://example.com/private",
        "https://example.com?token=secret",
        "https://exa mple.com",
        "https://example..com",
        "https://example.com////",
        "https://%65xample.com",
        "https://-bad.example",
        "https://bad-.example",
        "https://exam\u00adple.com",
        "https://exam\u200bple.com",
        "https://example.com:",
        "https://example.com:/",
        "https://example.com:-1",
        "https://example.com:0",
        "https://example.com:65536",
        "https://example.com:999999999999999999999999",
        "https://127.1",
        "https://0177.0.0.1",
        "https://2130706433",
        "https://0x7f000001",
        "https://0x7f.0x0.0x0.0x1",
        "https://127.0.0.0x1",
        "https://127.0.0x0.1",
        "https://127.0x0.0.1",
        "file://example.com",
    ],
)
def test__corpus_origin_rejects_unsafe_values(monkeypatch, origin):
    monkeypatch.setenv("HFL_CORPUS_WEB_URL", origin)

    with pytest.raises(RuntimeError, match="HFL_CORPUS_WEB_URL"):
        module.corpus_document_url({"path": "/corpus/2026-08-20.md"})


@pytest.mark.parametrize("codepoint", [*range(32), 127])
def test__validated_web_origin_rejects_ascii_controls(codepoint):
    with pytest.raises(RuntimeError, match="HFL_CORPUS_WEB_URL"):
        module._validated_web_origin(chr(codepoint) + "https://example.com")


def test__corpus_origin_accepts_localhost_ipv4_and_ipv6(monkeypatch):
    cases = [
        ("http://localhost:8081/", "http://localhost:8081"),
        ("https://127.0.0.1", "https://127.0.0.1"),
        ("https://[::1]:8081", "https://[::1]:8081"),
        ("https://harqis-server", "https://harqis-server"),
        ("https://123.example", "https://123.example"),
    ]

    for origin, expected in cases:
        monkeypatch.setenv("HFL_CORPUS_WEB_URL", origin)
        assert module._corpus_web_origin() == expected


def test__corpus_document_url_rejects_non_daily_document(monkeypatch):
    monkeypatch.setenv("HFL_CORPUS_WEB_URL", "https://harqis.example")

    with pytest.raises(RuntimeError, match="daily Markdown"):
        module.corpus_document_url({"path": "/corpus/private.md"})


def test__corpus_document_url_uses_persisted_document_path(monkeypatch):
    monkeypatch.setenv("HFL_CORPUS_WEB_URL", "https://harqis.example/")

    url = module.corpus_document_url({"path": "/corpus/2026-08-20.md"})

    assert url == "https://harqis.example/hfl-corpus/document/2026-08-20.md"
    assert module.corpus_document_url(
        {"path": ""}, fallback_filename="2026-08-21.md"
    ) == "https://harqis.example/hfl-corpus/document/2026-08-21.md"


def test__scheduled_radar_writes_hfl_before_linked_notification(tmp_path, monkeypatch):
    now = datetime(2026, 8, 20, 10, tzinfo=timezone.utc)
    row = {
        "when": (now - timedelta(hours=1)).isoformat(),
        "entry_id": "x",
        "source": "notes",
        "moment": "Release",
        "tags": [],
    }
    raw = {
        "findings": [
            *_finding(severity="high")["findings"],
            {
                **_finding(severity="medium")["findings"][0],
                "title": "Routine follow-up",
            },
        ]
    }
    events = []
    saved = []
    sent = []
    monkeypatch.setenv("HFL_CORPUS_WEB_URL", "https://harqis.example")
    monkeypatch.setattr(module, "retrieve_entries", lambda *a, **k: ([row], []))

    def writeback(text, _now, **_kwargs):
        events.append("write")
        saved.append(text)
        return {
            "delivery": "forwarded",
            "path": "",
            "entry_id": "hfl-radar",
        }

    def notify(text):
        events.append("notify")
        sent.append(text)
        return [123]

    monkeypatch.setattr(module, "_writeback", writeback)
    monkeypatch.setattr(module, "_notify", notify)

    result = module.run_activity_radar(
        scheduled=True,
        now=now,
        state_file=tmp_path / "state.json",
        synthesizer=lambda *a, **k: raw,
    )

    assert result["finding_count"] == 1
    assert result["text"].startswith("HFL ACTIVITY RADAR\n1 HIGH-PRIORITY FINDING")
    assert "Verify release" in result["text"]
    assert "Routine follow-up" not in result["text"]
    assert saved == [result["text"].split("\n\nCORPUS: ", 1)[0]]
    assert result["text"].endswith(
        "CORPUS: https://harqis.example/hfl-corpus/document/2026-08-20.md"
    )
    assert result["writeback"]["entry_id"] == "hfl-radar"
    assert sent == [result["text"]]
    assert events == ["write", "notify"]


def test__scheduled_radar_archives_all_high_findings_but_sends_four(tmp_path, monkeypatch):
    now = datetime(2026, 8, 20, 10, tzinfo=timezone.utc)
    row = {
        "when": (now - timedelta(hours=1)).isoformat(),
        "entry_id": "x",
        "source": "notes",
        "moment": "Release",
        "tags": [],
    }
    raw = {
        "findings": [
            {
                **_finding(severity="high")["findings"][0],
                "title": f"High finding {index}",
            }
            for index in range(6)
        ]
    }
    saved = []
    sent = []
    monkeypatch.setenv("HFL_CORPUS_WEB_URL", "https://harqis.example")
    monkeypatch.setattr(module, "retrieve_entries", lambda *a, **k: ([row], []))
    monkeypatch.setattr(
        module,
        "_writeback",
        lambda text, *a, **k: saved.append(text) or {
            "delivery": "persisted",
            "path": "/corpus/2026-08-20.md",
            "entry_id": "hfl-radar",
        },
    )
    monkeypatch.setattr(module, "_notify", lambda text: sent.append(text) or [123])

    result = module.run_activity_radar(
        scheduled=True,
        now=now,
        state_file=tmp_path / "state.json",
        synthesizer=lambda *a, **k: raw,
    )

    assert result["finding_count"] == 6
    assert "High finding 5" in saved[0]
    assert "6 HIGH-PRIORITY FINDINGS (SHOWING 4)" in sent[0]
    assert "High finding 3" in sent[0]
    assert "High finding 4" not in sent[0]
    assert "MORE: 2 additional findings are in the linked HFL entry." in sent[0]
    assert len(sent[0]) < 3900


def test__scheduled_radar_does_not_notify_when_hfl_write_is_not_delivered(tmp_path, monkeypatch):
    now = datetime(2026, 8, 20, 10, tzinfo=timezone.utc)
    row = {
        "when": (now - timedelta(hours=1)).isoformat(),
        "entry_id": "x",
        "source": "notes",
        "moment": "Release",
        "tags": [],
    }
    sent = []
    monkeypatch.setenv("HFL_CORPUS_WEB_URL", "https://harqis.example")
    monkeypatch.setattr(module, "retrieve_entries", lambda *a, **k: ([row], []))
    monkeypatch.setattr(
        module,
        "_writeback",
        lambda *a, **k: {"delivery": "outbox", "path": "", "entry_id": "hfl-radar"},
    )
    monkeypatch.setattr(module, "_notify", lambda text: sent.append(text))

    with pytest.raises(RuntimeError, match="HFL writeback was not delivered"):
        module.run_activity_radar(
            scheduled=True,
            now=now,
            state_file=tmp_path / "state.json",
            synthesizer=lambda *a, **k: _finding(severity="high"),
        )

    assert sent == []
    assert not (tmp_path / "state.json").exists()


def test__scheduled_radar_is_silent_when_only_lower_priority_findings_exist(tmp_path, monkeypatch):
    now = datetime(2026, 8, 20, 10, tzinfo=timezone.utc)
    row = {
        "when": (now - timedelta(hours=1)).isoformat(),
        "entry_id": "x",
        "source": "notes",
        "moment": "Release",
        "tags": [],
    }
    sent = []
    monkeypatch.setattr(module, "retrieve_entries", lambda *a, **k: ([row], []))
    monkeypatch.setattr(module, "_notify", lambda text: sent.append(text))

    result = module.run_activity_radar(
        scheduled=True,
        now=now,
        state_file=tmp_path / "state.json",
        synthesizer=lambda *a, **k: _finding(severity="medium"),
    )

    assert result["status"] == "no-findings"
    assert result["finding_count"] == 0
    assert result["text"] == "No high-priority findings."
    assert sent == []


def test__writeback_scopes_replacement_to_scheduled_dedup(monkeypatch):
    captured = []

    def submit(_entry, **kwargs):
        captured.append(kwargs)
        return {"delivery": "persisted", "path": "/corpus/2026-08-20.md"}

    monkeypatch.setattr(module, "submit_hfl_entry", submit)
    now = datetime(2026, 8, 20, 10, tzinfo=timezone.utc)

    module._writeback("Interactive report", now)
    module._writeback(
        "High-priority summary",
        now,
        dedup_key="activity-radar:stable",
    )

    assert captured[0]["dedup_key"] is None
    assert captured[0]["replace_duplicate"] is False
    assert captured[1]["dedup_key"] == "activity-radar:stable"
    assert captured[1]["replace_duplicate"] is True


def test__notify_requires_message_id(monkeypatch):
    from apps.telegram import config as telegram_config
    from apps.telegram.references.web.api import messages

    monkeypatch.setitem(telegram_config.CONFIG.app_data, "default_chat_id", "123")
    monkeypatch.setattr(messages.ApiServiceTelegramMessages, "send_message", lambda *a, **k: {})

    with pytest.raises(RuntimeError, match="valid message_id"):
        module._notify("Finding")


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
