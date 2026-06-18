"""Tests for workflows/dumps/* — both integration and unit.

Per the create-new-workflow skill convention:
  - Workflow tests first (call the actual task function with no mocks)
  - Unit / function tests after (test individual helpers in isolation)

The workflow tests are SKIPPED by default — they require either a configured
[<machine>.daily_dumps] block in machines.toml.local AND a live ssh target,
OR they need to run on harqis-server itself (local copy path).
"""
from pathlib import Path

import pytest

from workflows.dumps.config import (
    HARQIS_SERVER_MACHINE_NAME,
    get_dumps_target,
    get_local_dumps_config,
    get_pull_targets,
    load_merged_config,
)
from workflows.dumps.tasks.analyze import analyze_daily_dumps
from workflows.dumps.tasks.collect import broadcast_collect_daily_dumps
from workflows.dumps.tasks.pull import (
    _redact_ssh_user,
    _send_pull_failure_notification,
    pull_daily_dumps_from_remotes,
)
from workflows.dumps.transport import _archive_name, copy_locally
from workflows.dumps.files import CollectedFile
from datetime import datetime


# ── Workflow (integration) ────────────────────────────────────────────────────

@pytest.mark.skip(reason="Integration — requires live machines.toml.local + ssh target")
def test__broadcast_collect_daily_dumps():
    result = broadcast_collect_daily_dumps()
    assert result["machine"]
    assert "files_count" in result


@pytest.mark.skip(reason="Integration — requires harqis-server + Termux SSHD")
def test__pull_daily_dumps_from_remotes():
    result = pull_daily_dumps_from_remotes()
    assert "pulled_devices" in result


def test__analyze_daily_dumps_runs_without_inbox():
    """Analyze is safe to run anywhere — it self-guards off-hub and just logs.

    Three valid outcomes depending on where the test runs:
      - off harqis-server : host-guard short-circuits -> {"skipped": True}
      - on harqis-server, no inbox yet : {"date": ..., "machines": 0}
      - on harqis-server, inbox present : {"date": ..., "details": [...]}
    """
    result = analyze_daily_dumps()
    assert result.get("skipped") or "date" in result or "error" in result


# ── Unit / function ───────────────────────────────────────────────────────────

def test__load_merged_config_returns_dict():
    cfg = load_merged_config()
    assert isinstance(cfg, dict)


def test__local_dumps_config_resolves_machine_name():
    local = get_local_dumps_config()
    assert local.machine_name           # always non-empty (falls back to hostname)
    assert isinstance(local.paths, list)
    assert isinstance(local.is_harqis_server, bool)


def test__harqis_server_constant_is_canonical():
    """The constant must match how machines.toml names the central hub."""
    assert HARQIS_SERVER_MACHINE_NAME == "harqis-server"


def test__archive_name_uses_posix_separators():
    name = _archive_name(
        machine_name_dir="windows-work-all-daily-dumps-2026-05-09",
        source_basename="Screenshots 1",
        relative=Path("2026") / "05" / "shot.png",
    )
    assert name == "windows-work-all-daily-dumps-2026-05-09/Screenshots 1/2026/05/shot.png"
    assert "\\" not in name


def test__copy_locally_writes_files(tmp_path: Path):
    src = tmp_path / "src"; src.mkdir()
    inbox = tmp_path / "inbox"
    f = src / "file.txt"
    f.write_text("hello")
    cf = CollectedFile(source_root=src, path=f, relative=Path("file.txt"), mtime=datetime.now())

    written = copy_locally([cf], inbox, "test-machine-daily-dumps-2026-05-09")
    assert written == 1
    expected = inbox / "test-machine-daily-dumps-2026-05-09" / "src" / "file.txt"
    assert expected.exists()
    assert expected.read_text() == "hello"


def test__get_pull_targets_returns_list():
    """Should return [] if no [dumps.pull_targets.*] entries; never None."""
    targets = get_pull_targets()
    assert isinstance(targets, list)
    for t in targets:
        assert t.name and t.ssh and t.paths


def test__get_dumps_target_returns_none_when_unconfigured():
    """If [dumps] harqis_server_ssh / inbox aren't set, returns None (not a crash)."""
    # Pass an empty config dict to bypass the live machines.toml lookup.
    target = get_dumps_target(cfg={})
    assert target is None


def test__pull_failure_notification_skips_when_no_failures():
    result = _send_pull_failure_notification([], "2026-06-04 00:00:00", "2026-06-05 00:00:00")
    assert result == {"sent": False, "skipped": "no failures"}


def test__redact_ssh_user_keeps_host_for_operator_hint():
    error = "ssh find failed on u0_a368@nothing-phone.tailnet.ts.net:/storage (exit 255)"
    assert _redact_ssh_user(error) == "ssh find failed on <user>@nothing-phone.tailnet.ts.net:/storage (exit 255)"
