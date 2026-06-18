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
from workflows.dumps.tasks.analyze import (
    _filter_machines,
    _render_gaps,
    _render_multi,
    _resolve_target_dates,
    _scan_day,
    analyze_daily_dumps,
)
from workflows.dumps.tasks.collect import broadcast_collect_daily_dumps
from workflows.dumps.tasks.pull import (
    _redact_ssh_user,
    _send_pull_failure_notification,
    pull_daily_dumps_from_remotes,
)
from workflows.dumps.transport import _archive_name, copy_locally
from workflows.dumps.files import CollectedFile, format_dump_dir_name, parse_dump_dir_name
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


# ── Retro analyze: folder-name parsing + date resolution + scan/render ─────────

def test__parse_dump_dir_name_roundtrips_format():
    """parse_ is the inverse of format_, even when the machine name has hyphens."""
    name = format_dump_dir_name("windows-work-all", datetime(2026, 5, 9))
    assert name == "windows-work-all-daily-dumps-2026-05-09"
    assert parse_dump_dir_name(name) == ("windows-work-all", "2026-05-09")


def test__parse_dump_dir_name_rejects_non_dump_dirs():
    assert parse_dump_dir_name("feed-locks") is None
    assert parse_dump_dir_name("machine-daily-dumps-2026-5-9") is None   # not zero-padded


def test__resolve_target_dates_defaults_to_yesterday():
    now = datetime(2026, 6, 18, 9, 0, 0)
    assert _resolve_target_dates(now=now) == ["2026-06-17"]


def test__resolve_target_dates_days_window_ends_yesterday():
    now = datetime(2026, 6, 18, 1, 0, 0)
    assert _resolve_target_dates(days=3, now=now) == ["2026-06-15", "2026-06-16", "2026-06-17"]


def test__resolve_target_dates_explicit_date_is_verbatim():
    now = datetime(2026, 6, 18)
    # Explicit single day is NOT capped at yesterday.
    assert _resolve_target_dates(date="2026-06-18", now=now) == ["2026-06-18"]


def test__resolve_target_dates_month_is_capped_at_yesterday():
    now = datetime(2026, 6, 18)
    dates = _resolve_target_dates(month="2026-06", now=now)
    assert dates[0] == "2026-06-01"
    assert dates[-1] == "2026-06-17"          # capped — today (18th) excluded
    assert len(dates) == 17


def test__resolve_target_dates_full_past_month():
    now = datetime(2026, 6, 18)
    dates = _resolve_target_dates(month="2026-05", now=now)
    assert dates[0] == "2026-05-01" and dates[-1] == "2026-05-31" and len(dates) == 31


def test__scan_day_buckets_machines_for_one_date(tmp_path: Path):
    inbox = tmp_path / "inbox"
    # Two machines on the target day, one on a different day (must be ignored).
    for name, rel in [
        ("alpha-daily-dumps-2026-05-09", "a.txt"),
        ("beta-daily-dumps-2026-05-09", "b.txt"),
        ("alpha-daily-dumps-2026-05-08", "old.txt"),
    ]:
        d = inbox / name
        d.mkdir(parents=True)
        (d / rel).write_text("x")

    machines = _scan_day(inbox, "2026-05-09")
    assert sorted(m["machine"] for m in machines) == ["alpha", "beta"]
    assert all(m["files_count"] == 1 for m in machines)


def test__filter_machines_limits_to_exact_machine_name():
    machines = [
        {"machine": "alpha", "files_count": 1, "bytes_total": 1},
        {"machine": "nothing-phone", "files_count": 2, "bytes_total": 2},
    ]
    assert _filter_machines(machines, "nothing-phone") == [machines[1]]
    assert _filter_machines(machines) == machines


def test__render_multi_marks_missed_days_and_totals():
    per_day = {
        "2026-05-01": [{"machine": "alpha", "files_count": 2, "bytes_total": 2048}],
        "2026-05-02": [],   # missed day
    }
    text = _render_multi(["2026-05-01", "2026-05-02"], per_day, "/inbox")
    assert "Daily dumps retro - 2026-05-01..2026-05-02 - 2 day(s)" in text
    assert "2026-05-02: 0 machines (no dumps)" in text
    assert "1/2 day(s) with dumps" in text


def test__render_gaps_lists_only_missing_days():
    dates = ["2026-05-01", "2026-05-02", "2026-05-03"]
    text = _render_gaps(dates, ["2026-05-02"])
    assert "1 of 3 day(s) missing" in text
    assert "2026-05-02: no dumps" in text
    assert "2026-05-01: no dumps" not in text   # present days are not listed as gaps
    assert "2026-05-03: no dumps" not in text
    assert "2/3 day(s) had dumps" in text


def test__render_gaps_when_none_missing():
    dates = ["2026-05-01", "2026-05-02"]
    text = _render_gaps(dates, [])
    assert "none; all 2 day(s) have dumps" in text


# ── Manual pull: per-file-day bucketing (organize-on-server) ───────────────────

def test__extract_members_by_file_day_buckets_by_mtime(tmp_path: Path):
    """Files in one tar fan out into <device>-daily-dumps-<own-mtime-date>/... ."""
    import io
    import tarfile
    from workflows.dumps.transport import _extract_members_by_file_day

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for relname, day in [("2024/a.txt", "2024-06-01"),
                             ("2024/b.txt", "2024-06-01"),
                             ("2024/c.txt", "2024-06-02")]:
            data = b"x"
            info = tarfile.TarInfo(name=relname)
            info.size = len(data)
            # midnight local → timestamp → fromtimestamp round-trips to same date
            info.mtime = int(datetime.strptime(day, "%Y-%m-%d").timestamp())
            tar.addfile(info, io.BytesIO(data))
    buf.seek(0)

    with tarfile.open(fileobj=buf, mode="r") as tar:
        per_day = _extract_members_by_file_day(
            tar, tmp_path, "nothing-phone", "Camera", dir_prefix="daily")

    assert per_day == {"2024-06-01": 2, "2024-06-02": 1}
    assert (tmp_path / "nothing-phone-daily-dumps-2024-06-01" / "Camera" / "2024" / "a.txt").exists()
    assert (tmp_path / "nothing-phone-daily-dumps-2024-06-02" / "Camera" / "2024" / "c.txt").exists()
    # No execution-dated catch-all folder is created.
    assert not list(tmp_path.glob("*-full-dumps-*"))
