"""
workflows/mobile/emulator/tasks/manage.py

Celery tasks for starting and managing local Android emulators. Thin wrappers
over apps.android_emulator.client so the same logic backs the MCP tools, the
CLI (scripts/agents/emulator/run_emulator.py), and these queue-routed tasks.

Primary jobs:
  - start_emulator   : boot an AVD from a named profile (+overrides).
  - ensure_emulator  : idempotent "make sure this profile is running" (start
                       only if not already up) — safe to schedule if desired.
  - stop_emulator / list_emulators / create_avd : lifecycle + AVD management.

Host model: "any host with the SDK". Each task self-guards via
`config.sdk_available()` and returns {"skipped": True, ...} on a worker without
the SDK, so a competing-consumers pickup on a non-SDK box no-ops instead of
crashing (mirrors the dumps analyze host-guard pattern). Tasks are unscheduled
by default (see tasks_config.py) — they're on-demand.
"""
from __future__ import annotations

import socket
from typing import Optional

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.android_emulator import client, config

_log = create_logger("mobile.emulator")


def _skip_if_no_sdk() -> Optional[dict]:
    """Return a skip payload when the SDK isn't resolvable on this host."""
    if config.sdk_available():
        return None
    machine = socket.gethostname()
    _log.info("emulator: skipped on %s — Android SDK not available", machine)
    return {"skipped": True, "machine": machine,
            "reason": "Android SDK not available on this host"}


@SPROUT.task(name="workflows.mobile.emulator.tasks.start_emulator")
@log_result()
def start_emulator(profile: Optional[str] = None, avd_name: Optional[str] = None,
                   wait_for_boot: bool = True, boot_timeout: int = 300,
                   **overrides) -> dict:
    """Start an AVD from a profile (+per-call overrides) and optionally wait.

    overrides: any of port/headless/no_snapshot/wipe_data/gpu/memory_mb/cores/
    partition_mb. Returns the launch dict, with a nested "boot" status when
    wait_for_boot is True.
    """
    skip = _skip_if_no_sdk()
    if skip:
        return skip
    try:
        result = client.launch(profile=profile, avd_name=avd_name,
                               overrides=overrides)
    except KeyError as exc:
        return {"success": False, "error": str(exc)}
    if result.get("success") and wait_for_boot:
        boot = client.wait_for_boot(result["serial"], timeout=boot_timeout)
        result["boot"] = boot
        if boot.get("success"):
            # Apply profile-driven guest settings (e.g. nav_mode) post-boot.
            result["configured"] = client.apply_post_boot_settings(
                result["serial"], profile=profile, overrides=overrides)
    _log.info("emulator: start profile=%s -> %s", profile,
              result.get("serial") or result.get("error"))
    return result


@SPROUT.task(name="workflows.mobile.emulator.tasks.ensure_emulator")
@log_result()
def ensure_emulator(profile: Optional[str] = None, avd_name: Optional[str] = None,
                    wait_for_boot: bool = True, boot_timeout: int = 300,
                    **overrides) -> dict:
    """Idempotent: start the profile's AVD only if it isn't already running.

    Resolves the target serial from the profile/override port (default 5554);
    if that serial is already in `adb devices`, returns it untouched. Otherwise
    starts it (waiting for boot unless wait_for_boot is False — deploy uses
    fire-and-forget so it doesn't block on a 1-2 min boot). Safe to run
    repeatedly / on a schedule.
    """
    skip = _skip_if_no_sdk()
    if skip:
        return skip
    try:
        cfg = config.merge_profile(profile, overrides)
    except KeyError as exc:
        return {"success": False, "error": str(exc)}
    port = cfg.get("port", 5554)
    serial = f"emulator-{port}"
    running = {d["serial"] for d in client.list_running()}
    if serial in running:
        _log.info("emulator: ensure — %s already running", serial)
        return {"success": True, "already_running": True, "serial": serial,
                "status": client.status(serial)}
    return start_emulator(profile=profile, avd_name=avd_name,
                          wait_for_boot=wait_for_boot, boot_timeout=boot_timeout,
                          **overrides)


@SPROUT.task(name="workflows.mobile.emulator.tasks.spawn_instance")
@log_result()
def spawn_instance(profile: Optional[str] = None, name: Optional[str] = None,
                   port: Optional[int] = None, wait_for_boot: bool = True,
                   boot_timeout: int = 300, **overrides) -> dict:
    """Create-if-needed and launch a *parallel* instance from a profile.

    `name` is the AVD (its own persistent state); a free console port is picked
    automatically so it runs alongside other instances. Profile toggles
    (hw_keyboard/play_store/nav_mode) are applied per instance.
    """
    skip = _skip_if_no_sdk()
    if skip:
        return skip
    result = client.spawn(profile=profile, name=name, port=port,
                          overrides=overrides)
    if result.get("success") and wait_for_boot:
        boot = client.wait_for_boot(result["serial"], timeout=boot_timeout)
        result["boot"] = boot
        if boot.get("success"):
            result["configured"] = client.apply_post_boot_settings(
                result["serial"], profile=profile, overrides=overrides)
    _log.info("emulator: spawn name=%s -> %s", name,
              result.get("serial") or result.get("error"))
    return result


@SPROUT.task(name="workflows.mobile.emulator.tasks.clone_instance")
@log_result()
def clone_instance(src: str, name: str, force: bool = False, start: bool = False,
                   boot_timeout: int = 300, **overrides) -> dict:
    """Duplicate an AVD (with its saved userdata) and optionally spawn it.

    Stops nothing automatically — stop the source first for a clean copy. With
    start=True the clone is launched on a free port (parallel to the source).
    """
    skip = _skip_if_no_sdk()
    if skip:
        return skip
    res = client.clone_avd(src, name, force=force)
    if not res.get("success") or not start:
        return res
    spawn_res = client.spawn(name=name, port=overrides.pop("port", None),
                             overrides=overrides)
    if spawn_res.get("success"):
        boot = client.wait_for_boot(spawn_res["serial"], timeout=boot_timeout)
        spawn_res["boot"] = boot
        if boot.get("success"):
            spawn_res["configured"] = client.apply_post_boot_settings(
                spawn_res["serial"], overrides=overrides)
    res["spawn"] = spawn_res
    _log.info("emulator: clone %s -> %s (start=%s)", src, name, start)
    return res


@SPROUT.task(name="workflows.mobile.emulator.tasks.stop_emulator")
@log_result()
def stop_emulator(serial: str) -> dict:
    """Gracefully stop a running emulator by serial (e.g. emulator-5554)."""
    skip = _skip_if_no_sdk()
    if skip:
        return skip
    res = client.stop_emulator(serial).as_dict()
    _log.info("emulator: stop %s -> success=%s", serial, res.get("success"))
    return res


@SPROUT.task(name="workflows.mobile.emulator.tasks.list_emulators")
@log_result()
def list_emulators() -> dict:
    """List running emulators + installed AVDs on this host."""
    skip = _skip_if_no_sdk()
    if skip:
        return skip
    return {"success": True, "running": client.list_running(),
            "avds": client.list_avds()}


@SPROUT.task(name="workflows.mobile.emulator.tasks.create_avd")
@log_result()
def create_avd(name: Optional[str] = None, profile: Optional[str] = None,
               image: Optional[str] = None, device: Optional[str] = None,
               force: bool = False) -> dict:
    """Create an AVD from a profile and/or explicit image/device."""
    skip = _skip_if_no_sdk()
    if skip:
        return skip
    try:
        res = client.create_from_profile(
            profile=profile, name=name,
            overrides={"image": image, "device": device}, force=force)
    except KeyError as exc:
        return {"success": False, "error": str(exc)}
    _log.info("emulator: create_avd name=%s profile=%s -> success=%s",
              name, profile, res.ok)
    return res.as_dict()
