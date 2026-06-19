"""apps/android_emulator/devices.py

Device-agnostic management on top of adb. The emulator-specific lifecycle
(AVD start/stop, snapshots, create) lives in client.py; this module treats
*any* attached Android target uniformly — emulator, USB handset, or wireless —
so the shared adb operations (install / screenshot / shell / mirror) work on a
real phone exactly as they do on an AVD.

It adds the pieces a physical device needs that an emulator doesn't:
  - list_devices()  : every attached device, tagged emulator/physical/wireless
  - device_info()   : model / brand / android / resolution
  - wireless adb    : pair_wireless / connect_wireless / enable_tcpip / disconnect

Everything returns plain data or a client.CmdResult — never raises for an
operational failure (a missing adb comes back as a structured error).
"""
from __future__ import annotations

import logging
import re
import time

from apps.android_emulator import client

logger = logging.getLogger("harqis-app.android_emulator")


def _adb(args: list[str], *, timeout: int = 60, input_text: str | None = None):
    """Run an adb command via the shared client runner (CmdResult)."""
    return client._run("adb", args, timeout=timeout, input_text=input_text)


def _classify(serial: str) -> str:
    """Tag a serial: 'emulator' (emulator-5554), 'wireless' (ip:port), else
    'physical' (a USB handset's hardware serial)."""
    if serial.startswith("emulator-"):
        return "emulator"
    if ":" in serial:  # adb wireless targets are host:port
        return "wireless"
    return "physical"


def list_devices() -> list[dict]:
    """Every attached device → [{serial, state, kind, model?, port?, ...}].

    Parses `adb devices -l`. `kind` is emulator/physical/wireless; the `-l`
    key:value tokens (model, device, transport_id) are folded in, and an
    emulator's console `port` is derived from its serial.
    """
    res = _adb(["devices", "-l"])
    out: list[dict] = []
    if not res.ok:
        return out
    for ln in res.stdout.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("List of devices"):
            continue
        parts = ln.split()
        serial = parts[0]
        entry: dict = {
            "serial": serial,
            "state": parts[1] if len(parts) > 1 else "unknown",
            "kind": _classify(serial),
        }
        for tok in parts[2:]:
            if ":" in tok:
                k, v = tok.split(":", 1)
                entry[k] = v
        if entry["kind"] == "emulator":
            try:
                entry["port"] = int(serial.split("-", 1)[1])
            except ValueError:
                pass
        out.append(entry)
    return out


def device_info(serial: str) -> dict:
    """Best-effort hardware/OS summary for one device."""
    def prop(name: str) -> str:
        r = _adb(["-s", serial, "shell", "getprop", name], timeout=15)
        return r.stdout.strip() if r.ok else ""

    size = _adb(["-s", serial, "shell", "wm", "size"], timeout=15)
    resolution = ""
    if size.ok:
        m = re.search(r"(\d+x\d+)", size.stdout)
        resolution = m.group(1) if m else size.stdout.strip()
    return {
        "serial": serial,
        "kind": _classify(serial),
        "model": prop("ro.product.model"),
        "brand": prop("ro.product.brand"),
        "android": prop("ro.build.version.release"),
        "sdk": prop("ro.build.version.sdk"),
        "resolution": resolution,
    }


def device_ip(serial: str) -> str | None:
    """Best-effort Wi-Fi (wlan0) IPv4 of a device — for the tcpip→connect flow."""
    r = _adb(["-s", serial, "shell", "ip", "-f", "inet", "addr", "show", "wlan0"],
             timeout=15)
    if r.ok:
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", r.stdout)
        if m:
            return m.group(1)
    return None


# ── Wireless adb (Android 11+ wireless debugging) ───────────────────────────

def pair_wireless(target: str, code: str):
    """Pair with a device's wireless-debugging endpoint (one-time).

    `target` is the host:port shown under Developer options → Wireless
    debugging → "Pair device with pairing code" (a DIFFERENT port from the
    connect port). `code` is the 6-digit pairing code.
    """
    return _adb(["pair", target, code], timeout=30)


def connect_wireless(target: str):
    """`adb connect host:port` to a paired/tcpip device (the connect port)."""
    return _adb(["connect", target], timeout=30)


def enable_tcpip(serial: str, port: int = 5555):
    """Put a USB-attached device into TCP/IP mode so it accepts wireless adb.

    After this, find the device's Wi-Fi IP (device_ip) and connect_wireless
    to `<ip>:<port>` — then the cable can be unplugged.
    """
    return _adb(["-s", serial, "tcpip", str(port)], timeout=30)


def disconnect(target: str | None = None):
    """Disconnect one wireless target, or all if `target` is None."""
    return _adb(["disconnect", target] if target else ["disconnect"], timeout=15)


# ── Auto-connect (USB → wireless → none) ────────────────────────────────────

def connect_auto(serial: str | None = None, wireless: str | None = None,
                 connect_timeout: int = 12) -> dict:
    """Best-effort connect: prefer a USB handset, fall back to a wireless target.

    Order:
      1. A USB-attached physical device in 'device' state — the configured
         `serial` if given, else the first one found.
      2. The configured `wireless` host:port — reuse it if already connected,
         otherwise `adb connect` and wait up to `connect_timeout` for it.
      3. Any already-connected wireless device.
      4. Nothing → success=False with a human `message` (caller exits gracefully).

    Returns {success, serial?, via: 'usb'|'wireless'|None, message?}.
    """
    devs = list_devices()
    usb = [d for d in devs if d["kind"] == "physical" and d["state"] == "device"]
    pick = (next((d for d in usb if d["serial"] == serial), None) if serial
            else (usb[0] if usb else None))
    if pick:
        return {"success": True, "serial": pick["serial"], "via": "usb"}

    if wireless:
        cur = next((d for d in devs
                    if d["serial"] == wireless and d["state"] == "device"), None)
        if cur:
            return {"success": True, "serial": wireless, "via": "wireless"}
        connect_wireless(wireless)
        waited = 0
        while waited < connect_timeout:
            time.sleep(2)
            waited += 2
            d = next((x for x in list_devices() if x["serial"] == wireless), None)
            if d and d["state"] == "device":
                return {"success": True, "serial": wireless, "via": "wireless"}
        return {"success": False, "via": None,
                "message": f"USB unavailable and wireless {wireless} did not connect "
                           f"within {connect_timeout}s (same Wi-Fi? device awake?)"}

    wl = [d for d in devs if d["kind"] == "wireless" and d["state"] == "device"]
    if wl:
        return {"success": True, "serial": wl[0]["serial"], "via": "wireless"}

    return {"success": False, "via": None,
            "message": "no device available — no USB handset attached and no "
                       "wireless target configured/reachable"}
