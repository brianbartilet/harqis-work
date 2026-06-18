"""Unit tests for the manual dump backfill / full sweep (workflows/dumps/tasks/pull).

No SSH, no filesystem transfer: the remote list + tar primitives are
monkeypatched so we can assert WHICH windows are requested and WHERE files land.
"""
from datetime import datetime

import pytest
from hamcrest import assert_that, contains_string, equal_to, has_length, none

from workflows.dumps import transport as tx
from workflows.dumps.config import DumpsTarget, PullTarget
from workflows.dumps.tasks import pull as pullmod

# Fixed clock so windows are deterministic: Wed 2026-06-10 14:30 local.
NOW = datetime(2026, 6, 10, 14, 30)


# ── window resolution ─────────────────────────────────────────────────────────

@pytest.mark.smoke
def test__resolve_window_default_is_yesterday():
    start, end = pullmod.resolve_manual_window(now=NOW)
    assert_that(start, equal_to(datetime(2026, 6, 9)))
    assert_that(end, equal_to(datetime(2026, 6, 10)))   # end exclusive → yesterday only


@pytest.mark.smoke
def test__resolve_window_days_includes_today():
    start, end = pullmod.resolve_manual_window(days=3, now=NOW)
    assert_that(start, equal_to(datetime(2026, 6, 8)))  # today - 2
    assert_that(end, equal_to(datetime(2026, 6, 11)))   # today + 1 (incl. today)


@pytest.mark.smoke
def test__resolve_window_since_until_is_inclusive():
    start, end = pullmod.resolve_manual_window(since="2026-05-01", until="2026-05-03", now=NOW)
    assert_that(start, equal_to(datetime(2026, 5, 1)))
    assert_that(end, equal_to(datetime(2026, 5, 4)))    # until + 1 day


# ── pull_dumps_manual (transport mocked) ──────────────────────────────────────

@pytest.fixture()
def wired(monkeypatch, tmp_path):
    """Stub the SSH list/pull + config so pull_dumps_manual runs offline."""
    calls = {"list": [], "pull": []}

    def fake_list(ssh_target, paths, start_iso, end_iso, *, ssh_port=22):
        calls["list"].append({"start": start_iso, "end": end_iso})
        return {paths[0]: ["/sdcard/a.jpg", "/sdcard/b.jpg"]}

    def fake_pull(ssh_target, source_root, files, local_inbox, machine_name_dir, *, ssh_port=22):
        calls["pull"].append({"dir": machine_name_dir, "n": len(files)})
        return len(files)

    monkeypatch.setattr(pullmod, "list_remote_recent_files", fake_list)
    monkeypatch.setattr(pullmod, "pull_via_ssh_tar", fake_pull)
    monkeypatch.setattr(pullmod, "get_dumps_target",
                        lambda: DumpsTarget(ssh="srv@host", inbox=str(tmp_path)))
    monkeypatch.setattr(pullmod, "get_pull_targets",
                        lambda: [PullTarget(name="pixel-7", ssh="u@p",
                                            paths=["/sdcard/DCIM"], port=8022)])
    return calls


@pytest.mark.smoke
def test__full_sweep_drops_time_bounds_into_one_folder(wired):
    result = pullmod.pull_dumps_manual(full=True, now=NOW)
    assert_that(result["mode"], equal_to("full"))
    # Full sweep → no -newermt window at all.
    assert_that(wired["list"][0]["start"], none())
    assert_that(wired["list"][0]["end"], none())
    assert_that(wired["pull"][0]["dir"], equal_to("pixel-7-full-dumps-2026-06-10"))
    assert_that(result["files_count"], equal_to(2))


@pytest.mark.smoke
def test__range_per_day_runs_one_cycle_per_day(wired):
    result = pullmod.pull_dumps_manual(days=3, now=NOW)
    # 3 calendar days → 3 list + 3 pull cycles, daily-dumps layout per day.
    assert_that(wired["list"], has_length(3))
    assert_that(wired["pull"][0]["dir"], equal_to("pixel-7-daily-dumps-2026-06-08"))
    assert_that(wired["pull"][2]["dir"], equal_to("pixel-7-daily-dumps-2026-06-10"))
    assert_that(result["files_count"], equal_to(6))          # 2 files × 3 days
    assert_that(result["mode"], equal_to("range-per-day"))
    assert_that(result["days"], has_length(3))


@pytest.mark.smoke
def test__dry_run_lists_but_transfers_nothing(wired):
    result = pullmod.pull_dumps_manual(days=2, dry_run=True, now=NOW)
    assert_that(wired["pull"], has_length(0))               # nothing transferred
    assert_that(result["files_count"], equal_to(4))         # counted from the listing
    assert_that(result["dry_run"], equal_to(True))


@pytest.mark.smoke
def test__single_folder_range_uses_one_cycle(wired):
    result = pullmod.pull_dumps_manual(
        since="2026-05-01", until="2026-05-03", per_day=False, now=NOW)
    assert_that(wired["list"], has_length(1))
    assert_that(wired["pull"][0]["dir"], equal_to("pixel-7-range-dumps-2026-05-01_2026-05-03"))
    assert_that(result["mode"], equal_to("range-single"))


@pytest.mark.smoke
def test__unknown_device_is_reported(wired):
    result = pullmod.pull_dumps_manual(device="nope", now=NOW)
    assert_that(result.get("error"), contains_string("nope"))


# ── missing-only (catch-up) ───────────────────────────────────────────────────

@pytest.mark.smoke
def test__device_day_has_dumps_detects_empty_vs_filled(tmp_path):
    day = datetime(2026, 6, 9)
    assert pullmod._device_day_has_dumps(tmp_path, "pixel-7", day) is False  # absent
    folder = tmp_path / "pixel-7-daily-dumps-2026-06-09"
    folder.mkdir()
    assert pullmod._device_day_has_dumps(tmp_path, "pixel-7", day) is False  # empty
    (folder / "a.jpg").write_text("x")
    assert pullmod._device_day_has_dumps(tmp_path, "pixel-7", day) is True   # has file


@pytest.mark.smoke
def test__missing_only_skips_present_days(wired, tmp_path):
    # Pre-seed 2026-06-09 so it counts as already present (non-empty).
    seeded = tmp_path / "pixel-7-daily-dumps-2026-06-09" / "old.jpg"
    seeded.parent.mkdir(parents=True)
    seeded.write_text("x")

    result = pullmod.pull_dumps_manual(days=3, missing_only=True, now=NOW)
    # Window = 06-08, 06-09, 06-10. 06-09 present → only 2 pull cycles run.
    assert_that(result["mode"], equal_to("range-per-day-missing"))
    assert_that(wired["pull"], has_length(2))
    pulled = {c["dir"] for c in wired["pull"]}
    assert "pixel-7-daily-dumps-2026-06-09" not in pulled
    assert "pixel-7-daily-dumps-2026-06-08" in pulled
    assert "pixel-7-daily-dumps-2026-06-10" in pulled
    assert_that(result["days_skipped"], equal_to(1))


@pytest.mark.smoke
def test__missing_only_dry_run_reports_gaps(wired, tmp_path):
    seeded = tmp_path / "pixel-7-daily-dumps-2026-06-09" / "old.jpg"
    seeded.parent.mkdir(parents=True)
    seeded.write_text("x")

    result = pullmod.pull_dumps_manual(days=3, missing_only=True, dry_run=True, now=NOW)
    assert_that(wired["pull"], has_length(0))   # dry-run transfers nothing
    by_day = {d["day"]: d for d in result["days"]}
    assert "pixel-7" in by_day["2026-06-09"]["present_devices"]
    assert "pixel-7" in by_day["2026-06-08"]["pulled_devices"]


@pytest.mark.smoke
def test__missing_only_rejects_full_sweep(wired):
    result = pullmod.pull_dumps_manual(full=True, missing_only=True, now=NOW)
    assert_that(result.get("error"), contains_string("missing_only"))
    assert_that(wired["pull"], has_length(0))


# ── transport: full-sweep find command ────────────────────────────────────────

@pytest.mark.smoke
def test__list_all_files_omits_time_predicate(monkeypatch):
    captured = {}

    class _Result:
        returncode = 0
        stdout = b"/sdcard/a.jpg\0/sdcard/b.jpg\0"
        stderr = b""

    def fake_run(cmd, **_kwargs):
        captured["cmd"] = cmd
        return _Result()

    monkeypatch.setattr(tx.subprocess, "run", fake_run)
    out = tx.list_remote_recent_files("u@h", ["/sdcard"], None, None, ssh_port=8022)
    find_cmd = captured["cmd"][-1]
    assert_that("-newermt" in find_cmd, equal_to(False))
    assert_that("-type f" in find_cmd, equal_to(True))
    assert_that(out["/sdcard"], equal_to(["/sdcard/a.jpg", "/sdcard/b.jpg"]))


@pytest.mark.smoke
def test__list_window_keeps_both_time_bounds(monkeypatch):
    captured = {}

    class _Result:
        returncode = 0
        stdout = b""
        stderr = b""

    monkeypatch.setattr(
        tx.subprocess, "run",
        lambda cmd, **_k: (captured.__setitem__("cmd", cmd) or _Result()),
    )
    tx.list_remote_recent_files(
        "u@h", ["/sdcard"], "2026-06-09 00:00:00", "2026-06-10 00:00:00")
    assert_that(captured["cmd"][-1].count("-newermt"), equal_to(2))
