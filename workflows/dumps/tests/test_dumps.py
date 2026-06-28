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
    ExpectedDumpSource,
    get_dumps_summary_path,
    get_dumps_target,
    get_expected_dump_sources,
    get_local_dumps_config,
    get_pull_targets,
    load_merged_config,
)
from workflows.dumps.tasks.analyze import (
    _filter_machines,
    _find_missing_expected_sources,
    _missing_notification_marker,
    _render_gaps,
    _render_multi,
    _resolve_target_dates,
    _scan_day,
    _send_missing_dumps_notification,
    analyze_daily_dumps,
)
from workflows.dumps.tasks.collect import broadcast_collect_daily_dumps
from workflows.dumps.tasks.pull import (
    _redact_ssh_user,
    _send_pull_failure_notification,
    pull_daily_dumps_from_remotes,
)
from workflows.dumps.summary_store import (
    LOG_FILENAME,
    append_day_summary,
    render_day_markdown,
    resolve_summary_dirs,
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


def test__get_expected_dump_sources_includes_workers_and_pull_targets():
    cfg = {
        "windows-work-all": {
            "daily_dumps": {"paths": ["C:/dump"]},
        },
        "disabled-box": {
            "enabled": False,
            "daily_dumps": {"paths": ["/disabled"]},
        },
        "empty-box": {
            "daily_dumps": {"paths": []},
        },
        "dumps": {
            "pull_targets": {
                "nothing-phone": {
                    "ssh": "u0_a368@phone.tailnet.ts.net",
                    "port": 8022,
                    "paths": ["/storage/emulated/0/DCIM/Camera"],
                },
                "bad-phone": {"ssh": "x@y", "paths": []},
            }
        },
    }

    sources = get_expected_dump_sources(cfg)

    assert [(s.name, s.source_type) for s in sources] == [
        ("nothing-phone", "pull"),
        ("windows-work-all", "worker"),
    ]


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


def test__find_missing_expected_sources_treats_absent_and_empty_as_missing():
    expected = [
        ExpectedDumpSource("windows-work-all", "worker", ["C:/dump"]),
        ExpectedDumpSource("nothing-phone", "pull", ["/storage/emulated/0/DCIM/Camera"]),
        ExpectedDumpSource("empty-folder", "worker", ["/logs"]),
    ]
    machines = [
        {"machine": "windows-work-all", "files_count": 3, "bytes_total": 99},
        {"machine": "empty-folder", "files_count": 0, "bytes_total": 0},
    ]

    missing = _find_missing_expected_sources(expected, machines)

    assert missing == [
        {"name": "nothing-phone", "source_type": "pull", "paths_count": 1},
        {"name": "empty-folder", "source_type": "worker", "paths_count": 1},
    ]


def test__send_missing_dumps_notification_dedupes_existing_marker(tmp_path):
    missing = [{"name": "nothing-phone", "source_type": "pull", "paths_count": 2}]
    marker = _missing_notification_marker(tmp_path, "2026-06-25", missing)
    marker.parent.mkdir(parents=True)
    marker.write_text("sent\n", encoding="utf-8")

    result = _send_missing_dumps_notification(
        date_suffix="2026-06-25",
        missing=missing,
        observed=[],
        inbox=tmp_path,
    )

    assert result == {"sent": False, "skipped": "already notified", "marker": str(marker)}


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


# ── Consolidated Markdown log sink (summary_store) ─────────────────────────────

def test__render_day_markdown_has_header_table_and_total():
    machines = [
        {"machine": "pixel-7", "files_count": 88, "bytes_total": 60 * 1024 * 1024},
        {"machine": "windows-work-all", "files_count": 54, "bytes_total": 5 * 1024 * 1024},
    ]
    md = render_day_markdown("2026-06-18", machines, "/inbox",
                             now=datetime(2026, 6, 19, 1, 0, 0))
    assert md.startswith("# Daily Dumps — 2026-06-18")
    assert "2 machine(s) · 142 files" in md
    assert "| machine | files | bytes |" in md
    # Sorted by bytes desc — pixel-7 (60 MB) before windows-work-all (5 MB).
    assert md.index("pixel-7") < md.index("windows-work-all")
    assert "inbox `/inbox`" in md


def test__render_day_markdown_no_machines_renders_empty_marker():
    md = render_day_markdown("2026-06-18", [], "/inbox")
    assert "# Daily Dumps — 2026-06-18" in md
    assert "_No machine dumps found._" in md


def test__append_day_summary_appends_to_consolidated_log(tmp_path, monkeypatch):
    monkeypatch.setenv("DUMPS_SUMMARY_PATH", str(tmp_path))
    # No feed dir on the test host → resolve_summary_dirs is just the repo sink.
    monkeypatch.delenv("DESKTOP_PATH_FEED", raising=False)
    monkeypatch.delenv("DESKTOP_PATH_FEED_WINDOWS", raising=False)
    monkeypatch.delenv("DESKTOP_PATH_FEED_DARWIN", raising=False)
    monkeypatch.delenv("DESKTOP_PATH_FEED_LINUX", raising=False)

    machines = [{"machine": "alpha", "files_count": 3, "bytes_total": 2048}]
    written = append_day_summary("2026-06-18", machines, "/inbox")

    target = tmp_path / LOG_FILENAME
    assert str(target) in written
    assert target.exists()
    after_one = target.read_text(encoding="utf-8")
    assert after_one.count("# Daily Dumps — 2026-06-18") == 1

    # Plain append — re-running a date stacks another block (allow-dupes).
    append_day_summary("2026-06-18", machines, "/inbox")
    after_two = target.read_text(encoding="utf-8")
    assert after_two.count("# Daily Dumps — 2026-06-18") == 2
    assert after_two.startswith(after_one)

    # A different day appends a further block to the same log.
    append_day_summary("2026-06-19", machines, "/inbox")
    final = target.read_text(encoding="utf-8")
    assert "# Daily Dumps — 2026-06-19" in final


def test__resolve_summary_dirs_includes_env_repo_sink(tmp_path, monkeypatch):
    monkeypatch.setenv("DUMPS_SUMMARY_PATH", str(tmp_path))
    dirs = resolve_summary_dirs()
    assert tmp_path.resolve() in dirs
    # De-duplicated — no path appears twice.
    assert len(dirs) == len({str(d) for d in dirs})


def test__machines_toml_summary_path_wins_over_env(tmp_path, monkeypatch):
    """[dumps] summary_path is the canonical home and beats the env fallback."""
    import workflows.dumps.summary_store as store

    toml_dir = tmp_path / "from-toml"
    monkeypatch.setenv("DUMPS_SUMMARY_PATH", str(tmp_path / "from-env"))
    # _repo_sink imports get_dumps_summary_path lazily from config, so patch the source.
    monkeypatch.setattr("workflows.dumps.config.get_dumps_summary_path",
                        lambda cfg=None: str(toml_dir))

    assert store._repo_sink() == toml_dir.resolve()


def test__get_dumps_summary_path_none_when_unset():
    from workflows.dumps.config import get_dumps_summary_path
    assert get_dumps_summary_path(cfg={}) is None
    assert get_dumps_summary_path(cfg={"dumps": {}}) is None
    assert get_dumps_summary_path(cfg={"dumps": {"summary_path": "/x"}}) == "/x"


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
