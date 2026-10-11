"""Supervisor tests use synthetic children only; never publish a dump summary."""
import ast
import json
import os
from pathlib import Path
import signal
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Supervisor targets the POSIX dumps hub")

WRAPPER = Path(__file__).parents[1] / "harqis_dumps_summary_android_7d.py"


def load_wrapper():
    # Safely load the old unguarded wrapper as well, proving the regression.
    tree = ast.parse(WRAPPER.read_text())
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.If):
            break
        nodes.append(node)
    namespace = {"__name__": "android_wrapper", "__file__": str(WRAPPER)}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(WRAPPER), "exec"), namespace)
    return namespace


def run_child(tmp_path, code, timeout=2):
    wrapper = load_wrapper()
    assert "run_bounded" in wrapper, "wrapper needs bounded subprocess supervision"
    return wrapper["run_bounded"]([sys.executable, "-u", "-c", code],
        cwd=tmp_path, diagnostics_dir=tmp_path / "diagnostics",
        timeout=timeout, heartbeat=0.04, grace=0.1)


def diagnostics(tmp_path):
    files = list((tmp_path / "diagnostics").glob("*.jsonl"))
    assert len(files) == 1
    assert files[0].stat().st_mode & 0o777 == 0o600
    return [json.loads(line) for line in files[0].read_text().splitlines()]


def test_success_preserves_safe_summary_and_discards_private_output(tmp_path):
    code, text = run_child(tmp_path,
        "import time; print('PRIVATE RAW DATA'); print('TOTAL: 3 files, 3 B across 1/7 day(s) with dumps'); print('Wrote 2 summary files'); time.sleep(.12)")
    assert code == 0
    assert "3 files, 3 B" in text and "md: 2 files" in text
    rows = diagnostics(tmp_path)
    assert rows[-1]["event"] == "finished"
    assert any(row["event"] == "running" for row in rows)
    assert "PRIVATE" not in text + json.dumps(rows)


def test_nonzero_is_meaningful_and_redacted(tmp_path):
    code, text = run_child(tmp_path, "import sys; print('secret Exception: private', file=sys.stderr); sys.exit(9)")
    assert code == 9
    assert "exit 9" in text
    assert "private" not in text.lower()
    assert diagnostics(tmp_path)[-1]["returncode"] == 9


def test_timeout_kills_term_ignoring_descendant(tmp_path):
    pidfile = tmp_path / "child.pid"
    child = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
    code = (f"import subprocess,sys,time,pathlib; p=subprocess.Popen([sys.executable,'-c',{child!r}]); "
            f"pathlib.Path({str(pidfile)!r}).write_text(str(p.pid)); time.sleep(60)")
    start = time.monotonic()
    status, text = run_child(tmp_path, code, timeout=0.4)
    assert status == 124 and "timed out" in text
    assert time.monotonic() - start < 3
    pid = int(pidfile.read_text())
    # A killed orphan can briefly be a zombie pending OS reaping.
    import subprocess
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    assert not state or state.startswith("Z")
    assert diagnostics(tmp_path)[-1]["event"] == "timeout"


def test_large_unterminated_output_does_not_hide_deadline(tmp_path):
    status, text = run_child(tmp_path, "import os;\nwhile True: os.write(1, b'x' * 65536)", timeout=.2)
    assert status == 124
    assert len(text) < 400
    assert sum(p.stat().st_size for p in (tmp_path / "diagnostics").iterdir()) < 10000


def test_launch_failure_is_nonzero_without_private_exception(tmp_path):
    wrapper = load_wrapper()
    assert "run_bounded" in wrapper
    code, text = wrapper["run_bounded"](["/nonexistent/private-name"], cwd=tmp_path,
        diagnostics_dir=tmp_path / "diagnostics", timeout=1, heartbeat=.1, grace=.1)
    assert code == 1
    assert "private-name" not in text
    assert diagnostics(tmp_path)[-1]["event"] == "launch_failed"


def test_terminated_supervisor_cleans_child(tmp_path):
    assert "run_bounded" in load_wrapper()
    import subprocess
    pidfile = tmp_path / "child.pid"
    child = f"import os,pathlib,time; pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid())); time.sleep(60)"
    runner = (f"import runpy; m=runpy.run_path({str(WRAPPER)!r}); "
              f"code,text=m['run_bounded']([{sys.executable!r},'-u','-c',{child!r}], "
              f"cwd={str(tmp_path)!r}, diagnostics_dir=m['Path']({str(tmp_path / 'diagnostics')!r}), "
              "timeout=30, heartbeat=.05, grace=.1); raise SystemExit(code)")
    proc = subprocess.Popen([sys.executable, "-c", runner], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        until = time.monotonic() + 3
        while not pidfile.exists() and time.monotonic() < until and proc.poll() is None:
            time.sleep(.02)
        assert pidfile.exists()
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=3) == 143
        with pytest.raises(ProcessLookupError):
            os.kill(int(pidfile.read_text()), 0)
        assert diagnostics(tmp_path)[-1]["event"] == "interrupted"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_diagnostics_io_failure_fails_closed_without_raw_exception(tmp_path, monkeypatch):
    wrapper = load_wrapper()
    def denied(fd):
        raise OSError("private storage detail")
    monkeypatch.setattr(wrapper["os"], "fsync", denied)
    code, text = wrapper["run_bounded"]([sys.executable, "-c", "raise SystemExit(0)"],
        cwd=tmp_path, diagnostics_dir=tmp_path / "diagnostics", timeout=1, grace=.1)
    assert code == 1
    assert "private storage" not in text


def test_cleanup_error_fails_without_raw_exception(tmp_path):
    wrapper = load_wrapper()
    original = wrapper["_stop_group"]
    def cleanup(proc, grace):
        original(proc, grace)
        raise PermissionError("private process detail")
    wrapper["_stop_group"] = cleanup
    code, text = wrapper["run_bounded"]([sys.executable, "-c", "pass"],
        cwd=tmp_path, diagnostics_dir=tmp_path / "diagnostics", timeout=1, grace=.1)
    assert code == 1
    assert "private process" not in text
    assert diagnostics(tmp_path)[-1]["event"] == "cleanup_failed"
