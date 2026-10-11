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
    tree = ast.parse(WRAPPER.read_text(encoding="utf-8"))
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
    return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]


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
    secret = "child-stderr-secret-8d4f71"
    code, text = run_child(tmp_path, f"import sys; print({secret!r}, file=sys.stderr); sys.exit(9)")
    assert code == 9
    assert "exit 9" in text
    rows = diagnostics(tmp_path)
    assert secret not in text + json.dumps(rows)
    assert rows[-1]["returncode"] == 9


def test_timeout_kills_term_ignoring_descendant(tmp_path):
    pidfile = tmp_path / "child.pid"
    child = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
    code = (f"import subprocess,sys,time,pathlib; p=subprocess.Popen([sys.executable,'-c',{child!r}]); "
            f"pathlib.Path({str(pidfile)!r}).write_text(str(p.pid)); time.sleep(60)")
    start = time.monotonic()
    status, text = run_child(tmp_path, code, timeout=0.4)
    # Some Linux hosts retain orphan zombies. Conservative cleanup verification
    # reports these as incomplete, while preserving the timeout in diagnostics.
    assert status in (124, 1)
    assert "timed out" in text or "cleanup incomplete" in text
    assert time.monotonic() - start < 3
    pid = int(pidfile.read_text(encoding="utf-8"))
    # A killed orphan can briefly be a zombie pending OS reaping.
    import subprocess
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    assert not state or state.startswith("Z")
    rows = diagnostics(tmp_path)
    assert rows[-1]["event"] == "timeout" or any(row.get("outcome") == "timeout" for row in rows)


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
            os.kill(int(pidfile.read_text(encoding="utf-8")), 0)
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


def test_existing_group_is_not_reported_as_cleaned(monkeypatch):
    from types import SimpleNamespace
    wrapper = load_wrapper()
    monkeypatch.setattr(wrapper['os'], 'killpg', lambda *args: None)
    proc = SimpleNamespace(pid=123, poll=lambda: 0, wait=lambda timeout: 0)
    assert wrapper['_stop_group'](proc, 0) is False


def test_cleanup_waits_for_group_disappearance(monkeypatch):
    from types import SimpleNamespace
    wrapper = load_wrapper()
    probes = []
    def killpg(pid, sig):
        if sig == 0:
            probes.append(sig)
            if len(probes) == 2:
                raise ProcessLookupError
    monkeypatch.setattr(wrapper['os'], 'killpg', killpg)
    proc = SimpleNamespace(pid=123, poll=lambda: 0, wait=lambda timeout: 0)
    assert wrapper['_stop_group'](proc, 0) is True
    assert len(probes) == 2


def test_stalled_diagnostics_do_not_block_timeout_or_cleanup(tmp_path, monkeypatch):
    import threading
    wrapper = load_wrapper()
    entered, release = threading.Event(), threading.Event()
    def blocked(fd):
        entered.set()
        release.wait(10)
    monkeypatch.setattr(wrapper['os'], 'fsync', blocked)
    pidfile = tmp_path / 'pid'
    child = f"import os,pathlib,time; pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid())); time.sleep(60)"
    started = time.monotonic()
    try:
        code, text = wrapper['run_bounded']([sys.executable, '-c', child], cwd=tmp_path,
            diagnostics_dir=tmp_path / 'diagnostics', timeout=.4, heartbeat=.05, grace=.1)
        assert entered.is_set()
        assert time.monotonic() - started < 3
        assert code == 1 and 'stalled' in text
        with pytest.raises(ProcessLookupError):
            os.kill(int(pidfile.read_text(encoding="utf-8")), 0)
    finally:
        release.set()


@pytest.mark.parametrize('status,files', [('success', 3), ('no_data', 0)])
def test_structured_summary(tmp_path, status, files):
    payload = dict(version=1, status=status, files_total=files, bytes_total=files * 100,
                   days=7, days_with_dumps=int(bool(files)), summary_files_count=2 if files else 0)
    code, text = run_child(tmp_path, f"print('DUMPS_RESULT ' + {json.dumps(payload)!r})")
    assert code == 0
    assert f'{files} files' in text
    assert ('No dumps available' in text) == (status == 'no_data')
    if files:
        assert 'md: 2 files' in text


@pytest.mark.parametrize('record', ['', 'DUMPS_RESULT {broken', 'DUMPS_RESULT {"version":1,"status":"success"}'])
def test_required_result_cannot_silently_report_complete(tmp_path, record):
    wrapper = load_wrapper()
    code, text = wrapper['run_bounded']([sys.executable, '-c', f'print({record!r})'],
        cwd=tmp_path, diagnostics_dir=tmp_path / 'diagnostics', require_result=True, grace=.1)
    assert code == 1 and 'structured summary' in text
    assert diagnostics(tmp_path)[-1]['event'] == 'invalid_result'


def test_nonzero_exit_overrides_success_record(tmp_path):
    payload = dict(version=1, status='success', files_total=1, bytes_total=10,
                   days=7, days_with_dumps=1, summary_files_count=2)
    code, text = run_child(tmp_path, f"print('DUMPS_RESULT ' + {json.dumps(payload)!r}); raise SystemExit(9)")
    assert code == 9 and 'exit 9' in text
