import subprocess
import threading
import time

import pytest

from apps.desktop.helpers import feed
from apps.rainmeter.references.helpers import bangs
from apps.rainmeter.references.helpers.config_builder import init_meter


@pytest.fixture(autouse=True)
def windows_subprocess_compat(monkeypatch):
    """Provide the Windows subprocess surface when unit tests run elsewhere."""
    if not hasattr(bangs.subprocess, "STARTUPINFO"):
        class StartupInfo:
            def __init__(self):
                self.dwFlags = 0
                self.wShowWindow = None

        monkeypatch.setattr(
            bangs.subprocess, "STARTUPINFO", StartupInfo, raising=False
        )
    monkeypatch.setattr(
        bangs.subprocess, "STARTF_USESHOWWINDOW", 1, raising=False
    )


def test_atomic_replace_retries_windows_sharing_violation(monkeypatch, tmp_path):
    source = tmp_path / "temporary"
    destination = tmp_path / "skin.ini"
    source.write_text("new", encoding="utf-8")
    destination.write_text("old", encoding="utf-8")
    real_replace = feed.os.replace
    calls = 0

    def flaky_replace(src, dst):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise PermissionError(13, "Access is denied")
        real_replace(src, dst)

    monkeypatch.setattr(feed.os, "replace", flaky_replace)
    monkeypatch.setattr(feed.time, "sleep", lambda _delay: None)

    feed._atomic_replace(source, destination)

    assert calls == 3
    assert destination.read_text(encoding="utf-8") == "new"
    assert not source.exists()


def test_atomic_replace_cleans_temp_file_after_final_failure(monkeypatch, tmp_path):
    source = tmp_path / "temporary"
    destination = tmp_path / "skin.ini"
    source.write_text("new", encoding="utf-8")

    def denied(_src, _dst):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(feed.os, "replace", denied)
    monkeypatch.setattr(feed.time, "sleep", lambda _delay: None)

    with pytest.raises(PermissionError):
        feed._atomic_replace(source, destination, attempts=2)

    assert not source.exists()


def test_rainmeter_command_has_timeout(monkeypatch, tmp_path):
    executable = tmp_path / "Rainmeter.exe"
    executable.touch()
    captured = {}

    def timeout(_command, **kwargs):
        captured.update(kwargs)
        raise subprocess.TimeoutExpired(_command, kwargs["timeout"])

    monkeypatch.setattr(bangs, "RAINMETER_EXE", executable)
    monkeypatch.setattr(bangs.subprocess, "run", timeout)

    with pytest.raises(RuntimeError, match="timed out after 5s"):
        bangs._send_rainmeter_cmd_no_focus("!Refresh", "HARQIS\\HUD")

    assert captured["timeout"] == bangs.RAINMETER_COMMAND_TIMEOUT_SECS


def test_rainmeter_commands_are_serialized(monkeypatch, tmp_path):
    executable = tmp_path / "Rainmeter.exe"
    executable.touch()
    active = 0
    max_active = 0
    guard = threading.Lock()

    def tracked_run(_command, **_kwargs):
        nonlocal active, max_active
        with guard:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.02)
        with guard:
            active -= 1

    monkeypatch.setattr(bangs, "RAINMETER_EXE", executable)
    monkeypatch.setattr(bangs.subprocess, "run", tracked_run)
    threads = [
        threading.Thread(
            target=bangs._send_rainmeter_cmd_no_focus,
            args=("!Refresh", f"HARQIS\\HUD{i}"),
        )
        for i in range(4)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert max_active == 1


def test_overlapping_hud_render_is_skipped(monkeypatch, tmp_path):
    static_path = tmp_path / "static"
    static_path.mkdir()
    (static_path / "base.ini").write_text(
        "[meterTitle]\ntext=HUD\n\n[MeterBackground]\n"
        "shape=Stroke Color [#darkColor]\n",
        encoding="utf-8",
    )
    config = {
        "skin_name": "HARQIS",
        "static_path": str(static_path),
        "write_skin_to_path": str(tmp_path / "skins"),
        "bin_path": str(tmp_path / "Rainmeter.exe"),
    }
    entered = threading.Event()
    release = threading.Event()

    monkeypatch.setattr(
        "apps.rainmeter.references.helpers.config_builder._activate_config",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        "apps.rainmeter.references.helpers.config_builder._refresh_skin",
        lambda *_args: None,
    )

    @init_meter(
        config,
        hud_item_name="SERIAL HUD",
        include_notes_bin=False,
        reset_alerts_secs=0,
        play_sound=False,
    )
    def render(ini, **_kwargs):
        entered.set()
        release.wait(timeout=1)
        return "rendered"

    first_result = {}
    first = threading.Thread(
        target=lambda: first_result.setdefault("value", render())
    )
    first.start()
    assert entered.wait(timeout=1)

    overlapping = render()
    release.set()
    first.join(timeout=2)

    assert overlapping["skipped"] is True
    assert overlapping["summary"] == "Skipped overlapping HUD render"
    assert first_result["value"]["hud"] == "SERIAL HUD"
