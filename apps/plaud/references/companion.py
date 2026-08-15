"""ADB control client for the HARQIS PLAUD Android companion app.

The PLAUD Embedded SDK can only control a recorder from a BLE-capable mobile
device.  This module is the server-side half of that bridge: it sends explicit
Android broadcasts to the companion app and parses the ordered-broadcast result
returned by ``adb shell am broadcast``.

Commands fail closed.  The companion requires a shared control token, reports
its actual BLE/recording state as JSON, and never treats a successful ADB
process as proof that the recorder changed state.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

from apps.android_emulator import devices

_COMPONENT = (
    "com.harqis.plaudcompanion/"
    "com.harqis.plaudcompanion.control.RecordCommandReceiver"
)
_ACTION = "com.harqis.plaudcompanion.RECORD_COMMAND"
_VALID_COMMANDS = {"start", "stop", "pause", "resume", "status", "connect"}
_RESULT_RE = re.compile(r'data="((?:\\.|[^"])*)"')


@dataclass(frozen=True)
class CompanionConfig:
    serial: str
    token: str

    @classmethod
    def from_env(cls) -> "CompanionConfig":
        return cls(
            serial=os.environ.get("PLAUD_COMPANION_ADB_SERIAL", "").strip(),
            token=os.environ.get("PLAUD_COMPANION_TOKEN", "").strip(),
        )

    @property
    def ready(self) -> bool:
        return bool(self.serial and self.token)


class PlaudCompanionController:
    """Control and observe one companion phone through ADB."""

    def __init__(
        self,
        config: CompanionConfig | None = None,
        *,
        adb_runner=devices._adb,
    ) -> None:
        self.config = config or CompanionConfig.from_env()
        self._adb = adb_runner

    @property
    def ready(self) -> bool:
        return self.config.ready

    def status(self) -> dict[str, Any]:
        return self.command("status", verify=False)

    def command(
        self,
        action: str,
        *,
        verify: bool = True,
        timeout_seconds: float = 12.0,
        poll_interval: float = 1.0,
    ) -> dict[str, Any]:
        action = action.strip().lower()
        if action not in _VALID_COMMANDS:
            return {
                "success": False,
                "error": f"unsupported action: {action}",
                "allowed": sorted(_VALID_COMMANDS),
            }
        if not self.ready:
            return {
                "success": False,
                "error": (
                    "PLAUD companion not configured; set "
                    "PLAUD_COMPANION_ADB_SERIAL and PLAUD_COMPANION_TOKEN"
                ),
            }

        sent = self._send(action)
        if not sent.get("success") or not verify or action in {"status", "connect"}:
            return sent

        desired = {
            "start": "recording with calendar trigger active",
            "stop": "calendar trigger inactive",
            "pause": "paused",
            "resume": "recording",
        }[action]
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        last = sent
        while time.monotonic() <= deadline:
            last = self._send("status")
            triggers = set(last.get("active_triggers") or [])
            reached = {
                "start": last.get("state") == "recording" and "calendar" in triggers,
                "stop": "calendar" not in triggers,
                "pause": last.get("state") == "paused",
                "resume": last.get("state") == "recording",
            }[action]
            if last.get("success") and reached:
                return {**last, "action": action, "verified": True}
            if poll_interval > 0:
                time.sleep(poll_interval)
        return {
            **last,
            "success": False,
            "action": action,
            "verified": False,
            "error": f"companion did not reach {desired} before timeout",
        }

    def _send(self, action: str) -> dict[str, Any]:
        result = self._adb(
            [
                "-s",
                self.config.serial,
                "shell",
                "am",
                "broadcast",
                "-n",
                _COMPONENT,
                "-a",
                _ACTION,
                "--es",
                "action",
                action,
                "--es",
                "token",
                self.config.token,
            ],
            timeout=30,
        )
        if not result.ok:
            return {
                "success": False,
                "action": action,
                "error": result.stderr.strip() or result.stdout.strip(),
                "returncode": result.returncode,
            }
        payload = _parse_broadcast_payload(result.stdout)
        payload.setdefault("success", False)
        payload.setdefault("action", action)
        payload["adb_serial"] = self.config.serial
        return payload


def _parse_broadcast_payload(output: str) -> dict[str, Any]:
    """Extract the JSON result data emitted by an ordered broadcast."""
    match = _RESULT_RE.search(output or "")
    if not match:
        return {
            "success": False,
            "error": "companion returned no JSON result data",
            "raw": (output or "").strip()[-500:],
        }
    escaped = match.group(1)
    try:
        decoded = json.loads(f'"{escaped}"')
        payload = json.loads(decoded)
    except (json.JSONDecodeError, TypeError) as exc:
        return {
            "success": False,
            "error": f"invalid companion response: {exc}",
            "raw": escaped[-500:],
        }
    return payload if isinstance(payload, dict) else {
        "success": False,
        "error": "companion response was not an object",
    }
