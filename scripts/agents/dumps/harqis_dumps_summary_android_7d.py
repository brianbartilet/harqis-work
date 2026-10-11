#!/usr/bin/env python3
"""Bounded Hermes Android summary wrapper; canonical copy for ~/.hermes/scripts.

Only aggregate summary lines are retained in memory. Persistent JSONL diagnostics
contain lifecycle/timing/byte counters, never child output or dump contents.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import time
import uuid

REPO = Path("/Users/harqis-one/GIT/harqis-work")
PY = REPO / ".venv" / "bin" / "python"
SCRIPT = REPO / "scripts" / "agents" / "dumps" / "run_dumps_summary_retro.py"
DEVICE = "nothing-phone"
TIMEOUT_SECONDS = 3000  # Leave cleanup/reporting headroom before the 3600s cron limit.
DIAGNOSTICS_DIR = Path.home() / ".hermes" / "logs" / "android-dumps-summary"
_TOTAL = re.compile(r"TOTAL: (\d+ files, [\d.]+ [KMGTPE]?B across \d+/\d+ day\(s\) with dumps)")
_MD = re.compile(r"Wrote (\d+) summary files?\.?")


def _stop_group(proc, grace):
    """TERM then KILL the session, including children outliving the leader."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        proc.poll()  # Reap the leader without waiting for inherited pipe EOF.
        try:
            os.killpg(proc.pid, 0)
        except ProcessLookupError:
            break
        time.sleep(min(.05, max(0, deadline - time.monotonic())))
    kill_denied = False
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        # macOS can return EPERM while a signalled process is exiting. Reap
        # below, but do not claim cleanup if the group still exists afterward.
        kill_denied = True
    try:
        proc.wait(timeout=max(grace, 1))
        try:
            os.killpg(proc.pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return not kill_denied
        # Descendant zombies can persist briefly; SIGKILL was delivered above.
        return not kill_denied
    except subprocess.TimeoutExpired:
        return False  # Uninterruptible kernel I/O: never hang the supervisor too.


def run_bounded(cmd, *, cwd, diagnostics_dir=DIAGNOSTICS_DIR,
                timeout=TIMEOUT_SECONDS, heartbeat=30, grace=5):
    """Return (exit status, concise report); POSIX process-group supervision.

    Deadline applies even with no output, unlimited output, or inherited pipes.
    Failure output is deliberately redacted; diagnostics are not raw logs.
    """
    title = "📱 Android dumps 7d"
    started = time.monotonic()
    counts = {"stdout_bytes": 0, "stderr_bytes": 0}
    proc = None
    previous = {}
    interrupted = []
    total, md = "complete", None
    pending = b""
    dropping = False
    event, code = "supervisor_failed", 1
    try:
        diagnostics_dir = Path(diagnostics_dir)
        diagnostics_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = diagnostics_dir / (time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex + ".jsonl")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError:
        return 1, title + "\n❌ failed: diagnostics unavailable; child not started"

    def note(kind, **fields):
        row = dict(event=kind, timestamp=time.time(), elapsed_seconds=round(time.monotonic() - started, 3),
                   **counts, **fields)
        log.write(json.dumps(row) + "\n")
        log.flush()
        os.fsync(log.fileno())

    def on_signal(signum, frame):
        interrupted.append(signum)

    def consume(chunk):
        nonlocal pending, dropping, total, md
        for part in chunk.splitlines(keepends=True):
            ended = part.endswith(b"\n")
            if not dropping:
                pending += part
                if len(pending) > 4096:
                    pending, dropping = b"", True
            if ended:
                if not dropping:
                    line = pending.decode("utf-8", errors="replace").strip()
                    match = _TOTAL.fullmatch(line)
                    if match:
                        total = match.group(1)
                    match = _MD.fullmatch(line)
                    if match:
                        md = match.group(1)
                pending, dropping = b"", False

    with os.fdopen(fd, "w", encoding="utf-8") as log, selectors.DefaultSelector() as selector:
        try:
            for sig in (signal.SIGTERM, signal.SIGINT):
                previous[sig] = signal.signal(sig, on_signal)
            note("starting", timeout_seconds=timeout)
            try:
                proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        start_new_session=True)
            except OSError as exc:
                event = "launch_failed"
                note(event, error_type=type(exc).__name__, returncode=1)
                return 1, title + "\n❌ failed: unable to launch summary process"
            note("started", pid=proc.pid)
            for pipe, name in ((proc.stdout, "stdout_bytes"), (proc.stderr, "stderr_bytes")):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, name)
            deadline, next_heartbeat = started + timeout, started + heartbeat
            while True:
                now = time.monotonic()
                if interrupted:
                    code, event = 128 + interrupted[0], "interrupted"
                    break
                if now >= deadline:
                    code, event = 124, "timeout"
                    break
                if now >= next_heartbeat:
                    note("running", pid=proc.pid)
                    next_heartbeat = now + heartbeat
                for key, _ in selector.select(max(0, min(.1, deadline - now, next_heartbeat - now))):
                    try:
                        chunk = os.read(key.fileobj.fileno(), 65536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        counts[key.data] += len(chunk)
                        if key.data == "stdout_bytes":
                            consume(chunk)
                if proc.poll() is not None and not selector.get_map():
                    consume(b"\n")  # Accept a final aggregate line without newline.
                    code = proc.returncode if proc.returncode >= 0 else 128 - proc.returncode
                    event = "finished" if code == 0 else "failed"
                    break
        except Exception as exc:
            event, code = "supervisor_failed", 1
            # Exception messages may contain paths/content; persist only the type.
            try:
                note(event, error_type=type(exc).__name__)
            except OSError:
                pass  # The diagnostics sink itself may have failed.
        finally:
            if proc is not None:
                try:
                    cleaned = _stop_group(proc, grace)
                except OSError:
                    cleaned = False
                if not cleaned:
                    event, code = "cleanup_failed", 1
                for pipe in (proc.stdout, proc.stderr):
                    if pipe:
                        pipe.close()
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        try:
            note(event, returncode=code)
        except OSError:
            return 1, title + "\n❌ failed: diagnostics write failed"
    if code:
        reason = {"timeout": f"timed out after {timeout:g}s", "interrupted": "interrupted",
                  "cleanup_failed": "process-group cleanup incomplete",
                  "supervisor_failed": "supervisor error"}.get(event, f"summary process exit {code}")
        return code, title + f"\n❌ failed: {reason}; redacted diagnostics: {path}"
    lines = [title, f"✅ {total}"]
    if md:
        lines.append(f"📝 md: {md} files")
    return 0, "\n".join(lines)


def main():
    # Same runtime, flags and publishing semantics as the previous local wrapper.
    code, report = run_bounded([str(PY), "-u", str(SCRIPT), "--days", "7", "--device", DEVICE], cwd=REPO)
    print(report, flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
