"""Android emulator MCP tools — control local AVDs via the SDK CLIs.

Local-CLI app (no REST): every tool shells out through apps.android_emulator.client
and returns a JSON-friendly dict. Nothing raises — a missing SDK or a failed
command comes back as {"success": False, "error": ...}.

Tool groups: SDK info · emulator lifecycle · AVD management · device ops ·
snapshots. `emulator_adb_shell` is restricted to a read-mostly command whitelist
for safety; use the Celery task path if you need unrestricted adb.
"""
from __future__ import annotations

import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP

from apps.android_emulator import client, config

logger = logging.getLogger("harqis-mcp.android_emulator")

# adb shell sub-commands allowed via the MCP tool (first token of the command).
# Mutating/dangerous verbs (rm, reboot, svc, setprop, ...) are intentionally out.
_ADB_SHELL_WHITELIST = {
    "getprop", "dumpsys", "pm", "am", "input", "wm", "settings", "ls", "cat",
    "df", "ps", "top", "screencap", "monkey", "logcat", "service",
}


def register_android_emulator_tools(mcp: FastMCP):

    # ── SDK info ──────────────────────────────────────────────────────────
    @mcp.tool()
    def emulator_sdk_info() -> dict:
        """Report the resolved Android SDK location, tool paths, and profiles.

        Use this first to confirm the SDK is installed/visible on the host
        running the MCP server.
        """
        logger.info("Tool called: emulator_sdk_info")
        sdk = config.resolve_sdk_root()
        return {
            "success": config.sdk_available(),
            "sdk_root": str(sdk) if sdk else None,
            "tools": {t: (str(config.tool_path(t)) if config.tool_path(t) else None)
                      for t in ("emulator", "adb", "avdmanager", "sdkmanager")},
            "profiles": sorted(config.get_profiles()),
            "default_profile": config.default_profile_name(),
        }

    # ── Emulator lifecycle ────────────────────────────────────────────────
    @mcp.tool()
    def emulator_start(profile: Optional[str] = None, avd_name: Optional[str] = None,
                       port: Optional[int] = None, headless: Optional[bool] = None,
                       no_snapshot: Optional[bool] = None,
                       wipe_data: Optional[bool] = None,
                       gpu: Optional[str] = None,
                       wait_for_boot: bool = False,
                       boot_timeout: int = 180) -> dict:
        """Start an AVD with a named profile's config (plus optional overrides).

        Args:
            profile:     Profile name from apps_config ANDROID_EMULATOR.profiles.
                         Falls back to default_profile if omitted.
            avd_name:    AVD to launch. Defaults to the profile name.
            port:        Console port (even, 5554-5682). Default 5554.
            headless:    -no-window (no GUI). Profile value used if omitted.
            no_snapshot: Cold boot, ignore saved snapshot.
            wipe_data:   Factory-reset the AVD on boot.
            gpu:         GPU mode (auto / host / swiftshader_indirect / off).
            wait_for_boot: Block until the device finishes booting.
            boot_timeout:  Seconds to wait when wait_for_boot is True.

        Returns the launch result {pid, port, serial, avd, args} and, when
        wait_for_boot, a nested "boot" status.
        """
        logger.info("Tool called: emulator_start profile=%s avd=%s", profile, avd_name)
        overrides = {"port": port, "headless": headless, "no_snapshot": no_snapshot,
                     "wipe_data": wipe_data, "gpu": gpu}
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
        return result

    @mcp.tool()
    def emulator_spawn(profile: Optional[str] = None, name: Optional[str] = None,
                       port: Optional[int] = None, wait_for_boot: bool = True,
                       boot_timeout: int = 300) -> dict:
        """Create-if-needed and launch a parallel instance from a profile.

        Each `name` is its own AVD with independent, persistent state; a free
        console port is auto-allocated so it runs alongside other instances.
        Profile toggles (hw_keyboard/play_store/nav_mode) apply per instance.

        Args:
            profile:  Profile for device/image/resources/toggles.
            name:     AVD name = this instance's persistent state (default: profile).
            port:     Preferred console port; a free one is picked otherwise.
            wait_for_boot: Block until booted, then apply post-boot settings.
            boot_timeout:  Seconds to wait when wait_for_boot is True.
        """
        logger.info("Tool called: emulator_spawn profile=%s name=%s", profile, name)
        result = client.spawn(profile=profile, name=name, port=port)
        if result.get("success") and wait_for_boot:
            boot = client.wait_for_boot(result["serial"], timeout=boot_timeout)
            result["boot"] = boot
            if boot.get("success"):
                result["configured"] = client.apply_post_boot_settings(
                    result["serial"], profile=profile)
        return result

    @mcp.tool()
    def emulator_clone_avd(src: str, name: str, force: bool = False) -> dict:
        """Duplicate an AVD (with its saved userdata) under a new name.

        The clone boots from a copy of the source's data partition (installed
        apps, files, settings). Stop the source first for a clean copy, then
        launch the clone with emulator_spawn.

        Args:
            src:   Source AVD to copy.
            name:  New AVD name.
            force: Overwrite an existing target AVD.
        """
        logger.info("Tool called: emulator_clone_avd src=%s name=%s", src, name)
        return client.clone_avd(src, name, force=force)

    @mcp.tool()
    def emulator_stop(serial: str) -> dict:
        """Gracefully stop a running emulator (adb -s <serial> emu kill).

        Args:
            serial: Device serial, e.g. "emulator-5554".
        """
        logger.info("Tool called: emulator_stop serial=%s", serial)
        return client.stop_emulator(serial).as_dict()

    @mcp.tool()
    def emulator_list_running() -> dict:
        """List running emulator devices (serial, port, state)."""
        logger.info("Tool called: emulator_list_running")
        return {"success": True, "running": client.list_running()}

    @mcp.tool()
    def emulator_status(serial: str) -> dict:
        """Report whether an emulator serial is running and finished booting.

        Args:
            serial: Device serial, e.g. "emulator-5554".
        """
        logger.info("Tool called: emulator_status serial=%s", serial)
        return client.status(serial)

    # ── AVD management ────────────────────────────────────────────────────
    @mcp.tool()
    def emulator_list_avds() -> dict:
        """List installed AVD names."""
        logger.info("Tool called: emulator_list_avds")
        return {"success": True, "avds": client.list_avds()}

    @mcp.tool()
    def emulator_list_system_images() -> dict:
        """List installed `system-images;...` packages available for AVDs."""
        logger.info("Tool called: emulator_list_system_images")
        return {"success": True, "system_images": client.list_system_images()}

    @mcp.tool()
    def emulator_create_avd(name: Optional[str] = None, profile: Optional[str] = None,
                            image: Optional[str] = None, device: Optional[str] = None,
                            force: bool = False) -> dict:
        """Create an AVD, from a profile and/or explicit image/device.

        Args:
            name:    AVD name. Defaults to the profile name.
            profile: Profile to take device/image defaults from.
            image:   system-images;... package (overrides the profile image).
            device:  avdmanager device id, e.g. "pixel_7" (overrides profile).
            force:   Overwrite an existing AVD of the same name.
        """
        logger.info("Tool called: emulator_create_avd name=%s profile=%s", name, profile)
        try:
            res = client.create_from_profile(
                profile=profile, name=name,
                overrides={"image": image, "device": device}, force=force)
        except KeyError as exc:
            return {"success": False, "error": str(exc)}
        return res.as_dict()

    @mcp.tool()
    def emulator_delete_avd(name: str) -> dict:
        """Delete an AVD by name.

        Args:
            name: AVD name to delete.
        """
        logger.info("Tool called: emulator_delete_avd name=%s", name)
        return client.delete_avd(name).as_dict()

    # ── Device operations ─────────────────────────────────────────────────
    @mcp.tool()
    def emulator_install_apk(serial: str, apk_path: str,
                             reinstall: bool = True) -> dict:
        """Install an APK onto a running emulator.

        Args:
            serial:    Device serial, e.g. "emulator-5554".
            apk_path:  Host path to the .apk file.
            reinstall: Pass -r to keep app data on reinstall (default True).
        """
        logger.info("Tool called: emulator_install_apk serial=%s apk=%s", serial, apk_path)
        return client.install_apk(serial, apk_path, reinstall=reinstall).as_dict()

    @mcp.tool()
    def emulator_adb_shell(serial: str, command: str) -> dict:
        """Run a whitelisted `adb shell` command on a running emulator.

        Args:
            serial:  Device serial, e.g. "emulator-5554".
            command: Shell command. The first token must be one of the allowed
                     verbs (getprop, dumpsys, pm, am, input, wm, settings, ls,
                     cat, df, ps, top, screencap, monkey, logcat, service).

        For unrestricted adb, use the Celery task path instead.
        """
        logger.info("Tool called: emulator_adb_shell serial=%s cmd=%s", serial, command)
        tokens = command.split()
        if not tokens:
            return {"success": False, "error": "empty command"}
        if tokens[0] not in _ADB_SHELL_WHITELIST:
            return {"success": False,
                    "error": f"command {tokens[0]!r} not in whitelist "
                             f"{sorted(_ADB_SHELL_WHITELIST)}"}
        return client.adb_shell(serial, tokens).as_dict()

    @mcp.tool()
    def emulator_screenshot(serial: str, dest_path: str) -> dict:
        """Capture a PNG screenshot from a running emulator to a host path.

        Args:
            serial:    Device serial, e.g. "emulator-5554".
            dest_path: Host file path to write the PNG to.
        """
        logger.info("Tool called: emulator_screenshot serial=%s dest=%s", serial, dest_path)
        return client.screenshot(serial, dest_path)

    # ── Snapshots ─────────────────────────────────────────────────────────
    @mcp.tool()
    def emulator_snapshot_save(serial: str, name: str) -> dict:
        """Save a named snapshot of a running emulator's state.

        Args:
            serial: Device serial, e.g. "emulator-5554".
            name:   Snapshot name.
        """
        logger.info("Tool called: emulator_snapshot_save serial=%s name=%s", serial, name)
        return client.snapshot_save(serial, name).as_dict()

    @mcp.tool()
    def emulator_snapshot_load(serial: str, name: str) -> dict:
        """Restore a running emulator to a previously saved snapshot.

        Args:
            serial: Device serial, e.g. "emulator-5554".
            name:   Snapshot name to load.
        """
        logger.info("Tool called: emulator_snapshot_load serial=%s name=%s", serial, name)
        return client.snapshot_load(serial, name).as_dict()

    @mcp.tool()
    def emulator_snapshot_list(serial: str) -> dict:
        """List snapshots saved for a running emulator.

        Args:
            serial: Device serial, e.g. "emulator-5554".
        """
        logger.info("Tool called: emulator_snapshot_list serial=%s", serial)
        return client.snapshot_list(serial).as_dict()
