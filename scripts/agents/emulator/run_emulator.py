#!/usr/bin/env python
"""Start and manage Android emulators from the shell.

A thin CLI over workflows.mobile.emulator.tasks.manage (which wraps
apps.android_emulator.client), so the command line, the MCP tools, and the
Celery tasks all share one implementation. Runs synchronously and self-guards:
on a host without the Android SDK it prints a skip notice and exits 2.

Usage:
    # start the default (or named) profile and wait for boot
    python scripts/agents/emulator/run_emulator.py start
    python scripts/agents/emulator/run_emulator.py start --profile pixel7-test
    python scripts/agents/emulator/run_emulator.py start --profile pixel7-test --port 5556 --no-wait
    python scripts/agents/emulator/run_emulator.py start --no-headless          # show the GUI window

    # lifecycle / management
    python scripts/agents/emulator/run_emulator.py list
    python scripts/agents/emulator/run_emulator.py stop emulator-5554
    python scripts/agents/emulator/run_emulator.py create --profile pixel7-test
    python scripts/agents/emulator/run_emulator.py create --name p7 --image "system-images;android-34;google_apis;x86_64" --device pixel_7

Exit codes: 0 ok · 1 error · 2 skipped (no SDK on this host).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

# scripts/agents/emulator/run_emulator.py → repo root is parents[3]. Mirror the
# dumps retro bootstrap so workflows.*/apps.* imports + config resolution work
# whether run via deploy.py or directly from a shell.
REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(REPO_ROOT / ".env" / "apps.env")
import os  # noqa: E402  (after load_dotenv so APP_CONFIG_FILE can be defaulted)

os.environ.setdefault("APP_CONFIG_FILE", "apps_config.yaml")
os.environ.setdefault("WORKFLOW_CONFIG", "workflows.config")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Start/manage Android emulators.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("start", help="Start an AVD from a profile (+overrides).")
    s.add_argument("--profile", help="Profile name (default: ANDROID_EMULATOR.default_profile).")
    s.add_argument("--avd", dest="avd_name", help="AVD name (default: profile name).")
    s.add_argument("--port", type=int, help="Console port (even, 5554-5682).")
    s.add_argument("--headless", action=argparse.BooleanOptionalAction, default=None,
                   help="Run with/without a window (default: profile value).")
    s.add_argument("--no-snapshot", action="store_true", help="Cold boot, ignore snapshot.")
    s.add_argument("--wipe-data", action="store_true", help="Factory-reset on boot.")
    s.add_argument("--gpu", help="GPU mode (auto/host/swiftshader_indirect/off).")
    s.add_argument("--no-wait", action="store_true", help="Don't wait for boot.")
    s.add_argument("--boot-timeout", type=int, default=300, help="Boot wait seconds.")

    sp = sub.add_parser("spawn", help="Create-if-needed + launch a parallel instance on a free port.")
    sp.add_argument("--profile", help="Profile for device/image/resources/toggles.")
    sp.add_argument("--name", help="AVD name = this instance's persistent state (default: profile name).")
    sp.add_argument("--port", type=int, help="Preferred console port (auto-picks a free one otherwise).")
    sp.add_argument("--no-wait", action="store_true", help="Don't wait for boot.")
    sp.add_argument("--boot-timeout", type=int, default=300, help="Boot wait seconds.")

    cl = sub.add_parser("clone", help="Duplicate an AVD (with its saved data) to a new name.")
    cl.add_argument("--src", required=True, help="Source AVD to copy.")
    cl.add_argument("--name", required=True, help="New AVD name.")
    cl.add_argument("--force", action="store_true", help="Overwrite an existing target AVD.")
    cl.add_argument("--start", action="store_true", help="Spawn the clone on a free port after copying.")
    cl.add_argument("--boot-timeout", type=int, default=300, help="Boot wait seconds (with --start).")

    en = sub.add_parser("ensure", help="Idempotently start a profile's AVD (skip if already running).")
    en.add_argument("--profile", help="Profile name (default: ANDROID_EMULATOR.default_profile).")
    en.add_argument("--avd", dest="avd_name", help="AVD name (default: profile name).")
    en.add_argument("--port", type=int, help="Console port (even, 5554-5682).")
    en.add_argument("--no-wait", action="store_true", help="Don't wait for boot (fire-and-forget; used by deploy).")
    en.add_argument("--boot-timeout", type=int, default=300, help="Boot wait seconds.")

    st = sub.add_parser("stop", help="Stop a running emulator by serial or profile.")
    st.add_argument("serial", nargs="?", help="Device serial, e.g. emulator-5554.")
    st.add_argument("--profile", help="Stop the profile's instance (resolves serial from its port).")

    sub.add_parser("list", help="List running emulators + installed AVDs.")

    c = sub.add_parser("create", help="Create an AVD from a profile/image.")
    c.add_argument("--name", help="AVD name (default: profile name).")
    c.add_argument("--profile", help="Profile to take device/image defaults from.")
    c.add_argument("--image", help="system-images;... package.")
    c.add_argument("--device", help="avdmanager device id, e.g. pixel_7.")
    c.add_argument("--force", action="store_true", help="Overwrite existing AVD.")

    return p.parse_args()


def main() -> int:
    args = _parse_args()
    from workflows.mobile.emulator.tasks import manage

    if args.cmd == "start":
        overrides = {"port": args.port, "headless": args.headless, "gpu": args.gpu}
        if args.no_snapshot:
            overrides["no_snapshot"] = True
        if args.wipe_data:
            overrides["wipe_data"] = True
        result = manage.start_emulator(
            profile=args.profile, avd_name=args.avd_name,
            wait_for_boot=not args.no_wait, boot_timeout=args.boot_timeout,
            **overrides)
    elif args.cmd == "spawn":
        result = manage.spawn_instance(
            profile=args.profile, name=args.name, port=args.port,
            wait_for_boot=not args.no_wait, boot_timeout=args.boot_timeout)
    elif args.cmd == "clone":
        result = manage.clone_instance(
            src=args.src, name=args.name, force=args.force,
            start=args.start, boot_timeout=args.boot_timeout)
    elif args.cmd == "ensure":
        result = manage.ensure_emulator(
            profile=args.profile, avd_name=args.avd_name,
            wait_for_boot=not args.no_wait, boot_timeout=args.boot_timeout,
            **({"port": args.port} if args.port else {}))
    elif args.cmd == "stop":
        serial = args.serial
        if not serial and args.profile:
            from apps.android_emulator import config
            cfg = config.merge_profile(args.profile)
            serial = f"emulator-{cfg.get('port', 5554)}"
        if not serial:
            print(json.dumps({"success": False,
                              "error": "stop needs a serial or --profile"}))
            return 1
        result = manage.stop_emulator(serial)
    elif args.cmd == "list":
        result = manage.list_emulators()
    elif args.cmd == "create":
        result = manage.create_avd(name=args.name, profile=args.profile,
                                   image=args.image, device=args.device,
                                   force=args.force)
    else:  # argparse(required=True) prevents this
        return 1

    print(json.dumps(result, indent=2, default=str))
    if result.get("skipped"):
        return 2
    if result.get("success") is False:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
