import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

from workflows.second_brain import hud_projection
from workflows.second_brain.registry import OPERATIONS, operation_catalog


def test__hud_projection_redacts_secrets_and_bounds_payload():
    payload = hud_projection._bounded_payload(
        {
            "text": "useful output token=plain-secret account 123456789012",
            "api_key": "do-not-store",
            "account_id": 123456789012,
            "nested": {"access-token": "also-secret"},
        }
    )

    assert payload["text"] == "useful output token=[redacted] account ••••9012"
    assert payload["api_key"] == "[redacted]"
    assert payload["account_id"] == "••••9012"
    assert payload["nested"]["access-token"] == "[redacted]"


def test__hud_projection_redacts_secrets_from_text_and_mapping_keys():
    payload = hud_projection._bounded_payload(
        {
            "text": "access_token=plain-secret cookie=session-secret",
            "authorization=Bearer hidden": "also-secret",
        }
    )

    encoded = str(payload)
    assert "plain-secret" not in encoded
    assert "session-secret" not in encoded
    assert "Bearer hidden" not in encoded


def test__capture_hud_projection_never_changes_the_task_result(monkeypatch):
    captured = []
    monkeypatch.setattr(
        hud_projection,
        "_publish_projection",
        lambda source_task, result: captured.append((source_task, result)),
    )
    monkeypatch.setattr(hud_projection, "_should_capture_projection", lambda: True)

    @hud_projection.capture_hud_projection()
    def sample_task():
        return {"text": "captured"}

    assert sample_task() == {"text": "captured"}
    assert captured[0][0].endswith(".sample_task")
    assert captured[0][1] == {"text": "captured"}


def test__capture_hud_projection_skips_direct_calls(monkeypatch):
    monkeypatch.setattr(hud_projection, "_should_capture_projection", lambda: False)
    monkeypatch.setattr(
        hud_projection,
        "_publish_projection",
        lambda source_task, result: (_ for _ in ()).throw(AssertionError("unexpected publish")),
    )

    @hud_projection.capture_hud_projection()
    def sample_task():
        return {"text": "direct"}

    assert sample_task() == {"text": "direct"}


def test__fallback_uses_original_source_and_skips_gate_results(monkeypatch):
    captured = []
    monkeypatch.setattr(hud_projection, '_should_capture_projection', lambda: True)
    monkeypatch.setattr(hud_projection, '_publish_projection', lambda source, result: captured.append(source))
    @hud_projection.capture_hud_projection(source_task='workflows.hud.tasks.hud_radar.show_daily_radar')
    def fallback(skipped=False):
        return {'text': 'radar', 'skipped': skipped}
    fallback(skipped=True)
    assert not captured
    fallback()
    assert captured == ['workflows.hud.tasks.hud_radar.show_daily_radar']


def test__capture_hud_projection_does_not_log_projection_error_details(monkeypatch):
    warnings = []
    monkeypatch.setattr(hud_projection, "_should_capture_projection", lambda: True)
    monkeypatch.setattr(
        hud_projection,
        "_publish_projection",
        lambda source_task, result: (_ for _ in ()).throw(RuntimeError("token=plain-secret")),
    )
    monkeypatch.setattr(hud_projection.log, "warning", lambda *args: warnings.append(args))

    @hud_projection.capture_hud_projection()
    def sample_task():
        return {"text": "safe"}

    assert sample_task() == {"text": "safe"}
    assert warnings == [
        (
            "Second Brain HUD projection skipped for %s (%s)",
            f"{sample_task.__module__}.{sample_task.__qualname__}",
            "RuntimeError",
        )
    ]


def test__collect_hud_projection_normalizes_a_fresh_result(monkeypatch):
    captured_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    monkeypatch.setattr(
        hud_projection,
        "_load_projection",
        lambda source_task: {
            "source_task": source_task,
            "captured_at": captured_at.isoformat(),
            "payload": {
                "text": "NAV 100.00\nEUR_USD +2.00",
                "summary": "NAV $100.00 · 1 open trade",
                "metrics": {"nav": 100.0},
                "links": {
                    "broker": "https://example.test/account",
                    "dump": "C:\\private\\dump.txt",
                },
            },
        },
    )

    item = hud_projection.collect_hud_projection(
        source_task="workflows.hud.tasks.hud_forex.show_forex_account",
        operation_id="hud.hud_forex.show_forex_account",
        label="Forex account",
        correlation_id="corr",
        stale_after_minutes=60,
        priority=72,
        sensitivity="restricted",
    )[0]

    assert item.title == "Forex account"
    assert item.summary == "NAV $100.00 · 1 open trade"
    assert item.status == "fresh"
    assert item.sensitivity == "restricted"
    assert item.links == {"broker": "https://example.test/account"}
    assert item.details == "NAV 100.00\nEUR_USD +2.00"
    assert hud_projection._load_projection(item.source_refs[0])["payload"]["metrics"] == {"nav": 100.0}


def test__collect_hud_projection_returns_guidance_before_first_capture(monkeypatch):
    monkeypatch.setattr(hud_projection, "_load_projection", lambda source_task: None)

    item = hud_projection.collect_hud_projection(
        source_task="workflows.hud.tasks.hud_utils.show_mouse_bindings",
        operation_id="hud.hud_utils.show_mouse_bindings",
        label="Mouse bindings",
        correlation_id="corr",
    )[0]

    assert item.status == "awaiting_source"
    assert item.reason_codes == ("hud-projection-missing",)
    assert "Run the source HUD task once" in item.summary


def test__all_current_hud_panels_have_explicit_read_only_adapters():
    hud_operations = {
        operation_id: spec
        for operation_id, spec in OPERATIONS.items()
        if operation_id.startswith("hud.")
    }
    catalog = operation_catalog()

    assert len(hud_operations) == 18
    assert len({spec.source_task for spec in hud_operations.values()}) == 18
    assert all(spec.advisory_only and spec.eligible for spec in hud_operations.values())
    assert all(spec.collector.endswith("collect_hud_projection") for spec in hud_operations.values())
    assert not [entry for entry in catalog if not entry["eligible"]]

    repository = Path(__file__).resolve().parents[3]
    missing_publishers = []
    for spec in hud_operations.values():
        module_name, _, function_name = spec.source_task.rpartition(".")
        source = repository / Path(*module_name.split(".")).with_suffix(".py")
        tree = ast.parse(source.read_text(encoding="utf-8"))
        function = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
        )
        decorators = {
            decorator.func.id
            for decorator in function.decorator_list
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name)
        }
        if "capture_hud_projection" not in decorators:
            missing_publishers.append(spec.source_task)

    assert missing_publishers == []
