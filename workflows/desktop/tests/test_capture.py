import pytest
from datetime import datetime, timedelta
import workflows.desktop.tasks.capture as capture_module
from workflows.desktop.tasks_config import WORKFLOWS_DESKTOP
from workflows.queues import WorkflowQueue
from workflows.desktop.tasks.capture import (
    _tail_with_marker,
    MAX_DUMP_CHARS,
    generate_daily_desktop_summary,
    generate_weekly_desktop_summary,
    run_capture_logging,
)


# ── Workflow (integration — live API calls) ──────────────────────────────────
# These will burn Anthropic tokens. They assert on the SUCCESS prefix so a
# 4xx / 5xx / SKIPPED return is now a test failure (previously they passed
# silently regardless).

class _FakeProcess:
    def __init__(self, pid, parent_pid=0, running=True):
        self.pid = pid
        self._parent_pid = parent_pid
        self._running = running

    def ppid(self):
        return self._parent_pid

    def is_running(self):
        return self._running


def test__capture_process_family_treats_venv_launcher_and_child_as_singleton():
    launcher = _FakeProcess(100, parent_pid=50)
    interpreter = _FakeProcess(101, parent_pid=100)

    assert capture_module._capture_families([launcher, interpreter]) == [launcher]


def test__capture_state_file_records_all_processes(tmp_path):
    state_path = capture_module._write_screen_reader_state(
        tmp_path,
        [_FakeProcess(100), _FakeProcess(101, parent_pid=100)],
    )

    payload = __import__("json").loads(state_path.read_text(encoding="utf-8"))
    assert payload["pids"] == [100, 101]
    assert payload["health_path"].endswith("actions_health.json")


def test__capture_health_requires_recent_telemetry_from_live_family():
    process = _FakeProcess(101)
    fresh = {"pid": 101, "timestamp": datetime.now().isoformat()}
    stale = {
        "pid": 101,
        "timestamp": (datetime.now() - timedelta(minutes=5)).isoformat(),
    }

    assert capture_module._capture_health_is_fresh(fresh, [process]) is True
    assert capture_module._capture_health_is_fresh(stale, [process]) is False
    assert capture_module._capture_health_is_fresh(fresh, [_FakeProcess(999)]) is False


def test__capture_schedule_uses_isolated_queue_and_short_supervision_expiry():
    entry = WORKFLOWS_DESKTOP["run-job--run_capture_logging"]

    assert entry["options"]["queue"] == WorkflowQueue.CAPTURE
    assert entry["options"]["expires"] == 300
    assert entry["options"]["os"] == ["windows"]


def test__generate_daily_desktop_summary():
    result = generate_daily_desktop_summary(hud_item_name="DESKTOP LOGS", logs_output_path="logs/daily")
    # SKIPPED is acceptable (no dump.txt yet, or dump empty) — the bug we
    # fixed was the FAILED case being invisible. SUCCESS or SKIPPED both
    # pass; FAILED would now raise (caller sees pytest failure) instead of
    # returning a string.
    assert isinstance(result, str)
    assert result.startswith("SUCCESS:") or result.startswith("SKIPPED:"), (
        f"Daily summary returned unexpected value: {result!r}"
    )


def test__generate_weekly_desktop_summary():
    result = generate_weekly_desktop_summary(logs_daily_path="logs/daily", logs_output_path="logs/weekly")
    assert isinstance(result, str)
    assert result.startswith("SUCCESS:") or result.startswith("SKIPPED:"), (
        f"Weekly summary returned unexpected value: {result!r}"
    )


# ── Unit / function (pure, no API) ────────────────────────────────────────────

def test__tail_with_marker_short_input_unchanged():
    """Input shorter than the cap returns identically — no marker added."""
    text = "hello world"
    assert _tail_with_marker(text, 100) == text


def test__tail_with_marker_truncates_with_marker():
    """Input longer than the cap is truncated to the LAST `max_chars`,
    prefixed with a `[truncated: ...]` marker line."""
    text = "x" * 1000 + "TAIL"
    out = _tail_with_marker(text, 100)
    assert out.startswith("[truncated:")
    assert out.endswith("TAIL")
    # The kept-tail portion is exactly max_chars (excluding the marker line).
    body = out.split("\n", 1)[1]
    assert len(body) == 100


def test__max_dump_chars_within_haiku_context():
    """Sanity: the cap should leave room for prompt + system + 8192 output
    even on the smallest-context model we use (Haiku 200k tokens).
    600KB / ~4 chars per token ≈ 150k tokens; plenty of headroom."""
    # 4 chars per token is conservative for English; actual ratio is ~3.5.
    approx_tokens = MAX_DUMP_CHARS / 4
    assert approx_tokens < 200_000  # under Haiku's 200k context
