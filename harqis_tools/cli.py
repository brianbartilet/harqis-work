"""JSON-first CLI for lazy access to harqis-work app tools."""

from __future__ import annotations

import argparse
import contextlib
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from mcp.server.fastmcp import FastMCP

from agents.projects.permissions.enforcer import PermissionDenied, PermissionEnforcer
from agents.projects.profiles.schema import AgentProfile
from agents.projects.security.audit import AuditLogger
from harqis_tools.catalog import APP_CATALOG, get_app_spec, is_write_tool, register_app_tools


class CliError(RuntimeError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _load_app(app: str) -> tuple[Any, dict[str, Any]]:
    # App configs resolve ${VAR} placeholders at import time, so bootstrap the
    # host environment before the selected registrar is imported.
    # Some legacy config modules print status lines while importing. Keep stdout
    # reserved for the CLI's single JSON envelope.
    with contextlib.redirect_stdout(sys.stderr):
        from scripts.deploy import load_env_into_os, load_machine_config, machine_env_vars
        load_env_into_os()
        os.environ.setdefault("APP_CONFIG_FILE", "apps_config.yaml")
        os.environ.setdefault("WORKFLOW_CONFIG", "workflows.config")
        os.environ.update(machine_env_vars(load_machine_config(None)))
        spec = get_app_spec(app)
        mcp = FastMCP(f"harqis-cli-{spec.key}")
        register_app_tools(mcp, spec)
    return spec, mcp._tool_manager._tools


def _load_inputs(raw: str | None) -> dict[str, Any]:
    if raw is None:
        return {}
    if raw == "-":
        raw = sys.stdin.read()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CliError(f"Invalid JSON input: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise CliError("Tool input must be a JSON object")
    return value


def _audit_logger(app: str) -> AuditLogger:
    configured = os.environ.get("HARQIS_CLI_AUDIT_LOG")
    path = Path(configured) if configured else Path("logs/harqis_cli_audit.jsonl")
    return AuditLogger("cli", app, log_path=path)


def _enforce_profile(profile_path: str | None, tool_name: str, app_key: str) -> None:
    if not profile_path:
        return
    profile = AgentProfile.from_yaml(Path(profile_path))
    PermissionEnforcer(profile).check_tool(tool_name, app_key=app_key)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harqis-tools", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("apps", help="List available app keys without importing apps")

    commands = sub.add_parser("commands", help="List one app's operations")
    commands.add_argument("app")

    schema = sub.add_parser("schema", help="Show one operation's input schema")
    schema.add_argument("app")
    schema.add_argument("operation")

    call = sub.add_parser("call", help="Invoke one operation and emit JSON")
    call.add_argument("app")
    call.add_argument("operation")
    call.add_argument("--input", help="JSON object, or '-' to read JSON from stdin")
    call.add_argument("--confirm-write", action="store_true")
    call.add_argument("--profile", help="Optional agent profile YAML for tool authorization")
    return parser


def run(argv: Sequence[str] | None = None) -> Any:
    args = build_parser().parse_args(argv)
    if args.command == "apps":
        return [{"key": spec.key, "label": spec.label} for spec in APP_CATALOG]

    spec, tools = _load_app(args.app)
    if args.command == "commands":
        return [
            {
                "name": tool.name,
                "description": tool.description or "",
                "write": is_write_tool(tool.name),
            }
            for tool in tools.values()
        ]

    tool = tools.get(args.operation)
    if tool is None:
        raise CliError(f"Unknown operation '{args.operation}' for app '{spec.key}'")
    if args.command == "schema":
        return {
            "app": spec.key,
            "name": tool.name,
            "description": tool.description or "",
            "write": is_write_tool(tool.name),
            "input_schema": tool.parameters,
        }

    inputs = _load_inputs(args.input)
    audit = _audit_logger(spec.key)
    audit.tool_call(tool.name, inputs)
    write = is_write_tool(tool.name)
    try:
        if write and not args.confirm_write:
            reason = "write operation requires --confirm-write"
            audit.permission_check("write_confirmation", tool.name, allowed=False, reason=reason)
            raise PermissionDenied(reason)
        _enforce_profile(args.profile, tool.name, spec.key)
        audit.permission_check("tool", tool.name, allowed=True)
        with contextlib.redirect_stdout(sys.stderr):
            result = tool.fn(**inputs)
            if inspect.isawaitable(result):
                import asyncio
                result = asyncio.run(result)
        audit.tool_result(tool.name, success=True)
        return result
    except Exception as exc:
        audit.tool_result(tool.name, success=False, detail=str(exc))
        raise


def main(argv: Sequence[str] | None = None) -> int:
    try:
        print(_json({"ok": True, "result": run(argv)}))
        return 0
    except (CliError, KeyError, PermissionDenied, TypeError) as exc:
        print(_json({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2
    except Exception as exc:
        print(_json({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
