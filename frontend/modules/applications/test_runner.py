"""Bounded asynchronous pytest execution using the frontend host environment."""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import subprocess
import sys
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from web import REPO_ROOT


RUN_ROOT = REPO_ROOT / "logs" / "frontend" / "test-runs"
MAX_OUTPUT_CHARS = 500_000
TIMEOUT_SECONDS = 600
_TERMINAL = {"passed", "failed", "timed_out", "cancelled", "error"}
_RUN_ID = re.compile(r"^[0-9a-f]{32}$")


@dataclass
class TestRun:
    # This domain model is not a pytest test container.
    __test__ = False

    id: str
    app: str
    mode: Literal["safe", "full", "file"]
    targets: list[str]
    state: str = "queued"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: str | None = None
    finished_at: str | None = None
    returncode: int | None = None
    output: str = ""
    summary: dict[str, int] = field(default_factory=dict)
    cancel_requested: bool = False
    process: asyncio.subprocess.Process | None = field(default=None, repr=False)

    def public_dict(self) -> dict:
        return {
            item.name: getattr(self, item.name)
            for item in fields(self)
            if item.name != "process"
        }


def _secret_values() -> tuple[str, ...]:
    markers = ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "PRIVATE_KEY")
    return tuple(
        value for key, value in os.environ.items()
        if value and len(value) >= 6 and any(marker in key.upper() for marker in markers)
    )


def redact_output(value: str) -> str:
    cleaned = value or ""
    for secret in sorted(_secret_values(), key=len, reverse=True):
        cleaned = cleaned.replace(secret, "[REDACTED]")
    cleaned = re.sub(
        r"(?i)(authorization|api[-_ ]?key|token|password|secret)(\s*[:=]\s*)([^\s,;]+)",
        r"\1\2[REDACTED]",
        cleaned,
    )
    if len(cleaned) > MAX_OUTPUT_CHARS:
        cleaned = cleaned[:MAX_OUTPUT_CHARS] + "\n[output truncated]"
    return cleaned


def parse_summary(output: str) -> dict[str, int]:
    summary: dict[str, int] = {}
    for key in ("passed", "failed", "skipped", "error", "xfailed", "xpassed"):
        matches = re.findall(rf"(\d+)\s+{key}", output, flags=re.IGNORECASE)
        if matches:
            summary[key] = int(matches[-1])
    return summary


class TestRunManager:
    def __init__(self) -> None:
        self.runs: dict[str, TestRun] = {}
        self._global_limit = asyncio.Semaphore(2)
        self._app_locks: dict[str, asyncio.Lock] = {}
        self._tasks: set[asyncio.Task] = set()

    def start(self, app: str, mode: str, targets: list[str]) -> TestRun:
        run = TestRun(id=uuid4().hex, app=app, mode=mode, targets=targets)
        self.runs[run.id] = run
        task = asyncio.create_task(self._execute(run))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return run

    def get(self, run_id: str) -> TestRun | None:
        return self.runs.get(run_id) or self._load(run_id)

    def latest_for_app(self, app: str, limit: int = 10) -> list[TestRun]:
        live = [run for run in self.runs.values() if run.app == app]
        persisted: list[TestRun] = []
        app_dir = RUN_ROOT / app
        if app_dir.exists():
            for path in sorted(app_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                loaded = self._load(path.stem)
                if loaded and all(item.id != loaded.id for item in live):
                    persisted.append(loaded)
                if len(live) + len(persisted) >= limit:
                    break
        return sorted(live + persisted, key=lambda run: run.created_at, reverse=True)[:limit]

    async def cancel(self, run_id: str) -> bool:
        run = self.runs.get(run_id)
        if not run or run.state in _TERMINAL:
            return False
        run.cancel_requested = True
        if run.process:
            await self._terminate(run.process)
        return True

    async def _execute(self, run: TestRun) -> None:
        lock = self._app_locks.setdefault(run.app, asyncio.Lock())
        async with self._global_limit, lock:
            if run.cancel_requested:
                run.state = "cancelled"
                run.finished_at = datetime.now(timezone.utc).isoformat()
                self._persist(run)
                return
            run.state = "running"
            run.started_at = datetime.now(timezone.utc).isoformat()
            command = [
                sys.executable,
                "-m",
                "pytest",
                *run.targets,
                "-q",
                "--disable-warnings",
                "--maxfail=20",
            ]
            kwargs = {
                "cwd": str(REPO_ROOT),
                "stdout": asyncio.subprocess.PIPE,
                "stderr": asyncio.subprocess.STDOUT,
                "env": {**os.environ, "PYTHONUNBUFFERED": "1"},
            }
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                kwargs["start_new_session"] = True
            try:
                run.process = await asyncio.create_subprocess_exec(*command, **kwargs)
                stdout, _ = await asyncio.wait_for(
                    run.process.communicate(), timeout=TIMEOUT_SECONDS
                )
                run.returncode = run.process.returncode
                run.output = redact_output(stdout.decode("utf-8", errors="replace"))
                if run.cancel_requested:
                    run.state = "cancelled"
                else:
                    run.state = "passed" if run.returncode == 0 else "failed"
            except asyncio.TimeoutError:
                if run.process:
                    await self._terminate(run.process)
                run.state = "timed_out"
                run.output = f"Test run exceeded {TIMEOUT_SECONDS} seconds."
            except Exception as exc:
                run.state = "error"
                run.output = redact_output(f"{type(exc).__name__}: {exc}")
            finally:
                run.process = None
                run.summary = parse_summary(run.output)
                run.finished_at = datetime.now(timezone.utc).isoformat()
                self._persist(run)

    async def _terminate(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        if os.name == "nt":
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(process.pid), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

    def _persist(self, run: TestRun) -> None:
        target = RUN_ROOT / run.app / f"{run.id}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(run.public_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _load(self, run_id: str) -> TestRun | None:
        if not _RUN_ID.fullmatch(run_id or ""):
            return None
        for path in RUN_ROOT.glob(f"*/{run_id}.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return TestRun(**data)
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                return None
        return None


test_runs = TestRunManager()
