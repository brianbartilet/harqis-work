#!/usr/bin/env python3
"""Configure a locked-down Hermes profile for Activity Corpus sharing.

Usage:
    python scripts/agents/hfl/setup_hfl_share_hermes.py
    python scripts/agents/hfl/setup_hfl_share_hermes.py --apply
    python scripts/agents/hfl/setup_hfl_share_hermes.py --login
    python scripts/agents/hfl/setup_hfl_share_hermes.py --start
    python scripts/agents/hfl/setup_hfl_share_hermes.py --check
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shlex
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Collection, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]

_ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")
_HERMES_ENV_ALLOWLIST = {
    "HOME",
    "LANG",
    "LC_ALL",
    "LOGNAME",
    "NO_COLOR",
    "PATH",
    "SHELL",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "TERM",
    "TMPDIR",
    "USER",
}
_SENSITIVE_PROFILE_DIRS = {"cron", "hooks", "memories", "plugins", "skills", "workspace"}


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Reject every HTTP redirect before authenticated headers can leave loopback."""

    def redirect_request(
        self,
        req,
        fp,
        code,
        msg,
        headers,
        newurl,
    ):
        return None


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


def _assert_no_symlink_components(path: Path) -> None:
    path = _absolute_path(path)
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError(f"Refusing symlinked path component: {current}")
        if not current.exists():
            break


def _assert_profile_tree_safe(profile_dir: Path) -> None:
    _assert_no_symlink_components(profile_dir)
    if not profile_dir.is_dir():
        raise RuntimeError("Managed Hermes Share profile is not configured.")
    for root, directories, files in os.walk(profile_dir, followlinks=False):
        root_path = Path(root)
        for name in (*directories, *files):
            if (root_path / name).is_symlink():
                raise RuntimeError("Hermes Share profile must not contain symlinks.")
    for name in _SENSITIVE_PROFILE_DIRS:
        directory = profile_dir / name
        if directory.exists() and any(directory.iterdir()):
            raise RuntimeError(f"Hermes Share profile {name}/ must remain empty.")


def _assert_private_permissions(
    path: Path,
    *,
    directory: bool = False,
    required: bool = True,
) -> None:
    if not path.exists():
        if required:
            raise RuntimeError(f"Required private path is missing: {path.name}")
        return
    if path.is_symlink() or (directory and not path.is_dir()) or (
        not directory and not path.is_file()
    ):
        raise RuntimeError(f"Private path has an unsafe type: {path.name}")
    metadata = path.stat()
    # POSIX mode bits are not authoritative on Windows; chmod there does not
    # produce a meaningful 0600/0700 stat result. Type and symlink checks above
    # remain enforced on every platform.
    if os.name != "nt" and metadata.st_mode & 0o077:
        raise RuntimeError(f"{path.name} must have private permissions.")
    if hasattr(os, "getuid") and hasattr(metadata, "st_uid") and metadata.st_uid != os.getuid():
        raise RuntimeError(f"{path.name} must be owned by the current user.")


def _assert_oauth_credentials_private(profile_dir: Path, *, required: bool) -> None:
    auth_path = profile_dir / "auth.json"
    _assert_private_permissions(auth_path, required=required)
    for name in ("auth.lock", ".anthropic_oauth.json"):
        _assert_private_permissions(profile_dir / name, required=False)


def _hermes_environment(hermes_home: Path) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in _HERMES_ENV_ALLOWLIST
    }
    environment["HERMES_HOME"] = str(_absolute_path(hermes_home))
    environment["NO_PROXY"] = "127.0.0.1,::1"
    environment["no_proxy"] = "127.0.0.1,::1"
    return environment


def locked_down_profile_config(model: str) -> dict[str, object]:
    """Return the minimal agent configuration safe for snapshot-only inference."""
    return {
        "model": {
            "default": model,
            "provider": "openai-codex",
            "base_url": "https://chatgpt.com/backend-api/codex",
            "api_mode": "codex_responses",
        },
        "fallback_providers": [],
        "memory": {
            "memory_enabled": False,
            "user_profile_enabled": False,
        },
        "platform_toolsets": {"api_server": []},
        "platforms": {},
        # Temporary Hermes compatibility shim: this app requires its own port,
        # not the host gateway's profile-prefixed shared ingress.
        "gateway": {"standalone": True},
    }


def upsert_env_file(
    path: Path,
    values: Mapping[str, str],
    *,
    remove_keys: Collection[str] = (),
) -> None:
    """Atomically update selected dotenv keys while preserving unrelated lines."""
    path = _absolute_path(Path(path))
    _assert_no_symlink_components(path)
    if path.is_symlink():
        raise ValueError(f"Refusing to replace symlinked env file: {path}")
    for key, value in values.items():
        if not _ENV_KEY.fullmatch(key) or "\n" in value or "\r" in value:
            raise ValueError("Invalid environment key or value.")
    if not all(_ENV_KEY.fullmatch(key) for key in remove_keys):
        raise ValueError("Invalid environment key.")

    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    managed = set(values) | set(remove_keys)
    retained = [
        line
        for line in existing
        if not any(line.startswith(f"{key}=") for key in managed)
    ]
    if retained and retained[-1] != "":
        retained.append("")
    retained.extend(f"{key}={value}" for key, value in values.items())
    content = "\n".join(retained).rstrip("\n") + "\n"

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _env_value(path: Path, key: str) -> str:
    if not path.exists() or path.is_symlink():
        return ""
    prefix = f"{key}="
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def _write_private_text(path: Path, content: str) -> None:
    path = _absolute_path(Path(path))
    _assert_no_symlink_components(path)
    if path.is_symlink():
        raise ValueError(f"Refusing to replace symlinked file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _run(command: list[str], *, env: Mapping[str, str], check: bool = False):
    return subprocess.run(
        command,
        env=dict(env),
        check=check,
        capture_output=True,
        text=True,
    )


def _run_interactive(command: list[str], *, env: Mapping[str, str]):
    return subprocess.run(command, env=dict(env), check=False)


def _oauth_ready(profile: str, environment: Mapping[str, str]) -> bool:
    result = _run(
        ["hermes", "-p", profile, "auth", "status", "openai-codex"],
        env=environment,
    )
    output = f"{result.stdout}\n{result.stderr}".lower()
    logged_in = (
        result.returncode == 0
        and "openai-codex: logged in" in output
        and "logged out" not in output
    )
    if not logged_in:
        return False
    profile_dir = (
        Path(environment["HERMES_HOME"]) / "profiles" / profile
    )
    try:
        _assert_oauth_credentials_private(profile_dir, required=True)
    except RuntimeError:
        return False
    return True


def _dotenv_text(values: Mapping[str, str]) -> str:
    for key, value in values.items():
        if not _ENV_KEY.fullmatch(key) or "\n" in value or "\r" in value:
            raise ValueError("Invalid environment key or value.")
    return "".join(f"{key}={value}\n" for key, value in values.items())


def _env_mapping(path: Path) -> dict[str, str]:
    if not path.is_file() or path.is_symlink():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key] = value
    return result


def _profile_env_values(port: int, key: str) -> dict[str, str]:
    return {
        "API_SERVER_ENABLED": "true",
        "API_SERVER_HOST": "127.0.0.1",
        "API_SERVER_PORT": str(port),
        "API_SERVER_KEY": key,
        "API_SERVER_MODEL_NAME": "share-corpus",
    }


def _harqis_env_values(port: int, key: str, context_chars: int) -> dict[str, str]:
    return {
        "HFL_SHARE_PROVIDER": "hermes",
        "HFL_SHARE_HERMES_BASE_URL": f"http://127.0.0.1:{port}/v1",
        "HFL_SHARE_HERMES_API_KEY": key,
        "HFL_SHARE_HERMES_MODEL": "share-corpus",
        "HFL_SHARE_AGENT_TIMEOUT_SECONDS": "90",
        "HFL_SHARE_MAX_OUTPUT_TOKENS": "1200",
        "HFL_SHARE_MAX_CONTEXT_CHARS": str(context_chars),
    }


def _validate_args(args) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9]*", args.profile):
        raise ValueError("Profile must be lowercase alphanumeric.")
    if not 1024 <= args.port <= 65535:
        raise ValueError("Port must be between 1024 and 65535.")
    if not 5_000 <= args.context_chars <= 1_000_000:
        raise ValueError("Context characters must be between 5000 and 1000000.")


def _apply(args) -> tuple[Path, str, bool]:
    _validate_args(args)
    hermes_home = _absolute_path(args.hermes_home)
    profile_dir = hermes_home / "profiles" / args.profile
    marker = profile_dir / ".harqis-share-profile"
    environment = _hermes_environment(hermes_home)
    _assert_no_symlink_components(profile_dir)
    _assert_no_symlink_components(args.harqis_env)

    if profile_dir.exists():
        raise RuntimeError(
            "Refusing --apply over an existing profile. Use --check/--start, "
            "or remove the dedicated profile before recreating it."
        )
    result = _run(
        [
            "hermes",
            "profile",
            "create",
            args.profile,
            "--no-skills",
            "--description",
            "Snapshot-only HARQIS Share Corpus inference",
        ],
        env=environment,
    )
    if result.returncode != 0:
        raise RuntimeError("Hermes profile creation failed.")
    if not profile_dir.exists():
        raise RuntimeError("Hermes did not create the expected profile directory.")

    _assert_profile_tree_safe(profile_dir)
    profile_dir.chmod(0o700)
    _write_private_text(marker, "managed by harqis-work share setup\n")
    _write_private_text(
        profile_dir / "config.yaml",
        json.dumps(locked_down_profile_config(args.model), indent=2) + "\n",
    )
    _write_private_text(
        profile_dir / "SOUL.md",
        "# HARQIS Share Corpus Inference\n\n"
        "You are a snapshot-only, read-only inference process. Follow the "
        "request's corpus boundary, never use tools or memory, and never claim "
        "access beyond supplied text.\n",
    )
    _write_private_text(
        profile_dir / "USER.md",
        "# User\n\nNo owner profile or private user context is available.\n",
    )

    api_key = secrets.token_urlsafe(48)
    _write_private_text(
        profile_dir / ".env",
        _dotenv_text(_profile_env_values(args.port, api_key)),
    )
    upsert_env_file(
        args.harqis_env,
        _harqis_env_values(args.port, api_key, args.context_chars),
    )
    return profile_dir, api_key, _oauth_ready(args.profile, environment)


def _check_api(*, base_url: str, api_key: str, expected_model: str) -> None:
    health_url = base_url.rstrip("/") + "/health"
    models_url = base_url.rstrip("/") + "/models"
    capabilities_url = base_url.rstrip("/") + "/capabilities"
    toolsets_url = base_url.rstrip("/") + "/toolsets"
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _RejectRedirects(),
    )
    last_error: Exception | None = None
    for attempt in range(10):
        try:
            with opener.open(health_url, timeout=3) as response:
                health = json.loads(response.read().decode("utf-8"))
            auth_headers = {"Authorization": f"Bearer {api_key}"}
            request = urllib.request.Request(models_url, headers=auth_headers)
            with opener.open(request, timeout=5) as response:
                models = json.loads(response.read().decode("utf-8"))
            capabilities_request = urllib.request.Request(
                capabilities_url,
                headers=auth_headers,
            )
            with opener.open(capabilities_request, timeout=5) as response:
                capabilities = json.loads(response.read().decode("utf-8"))
            toolsets_request = urllib.request.Request(
                toolsets_url,
                headers=auth_headers,
            )
            with opener.open(toolsets_request, timeout=5) as response:
                toolsets = json.loads(response.read().decode("utf-8"))
            model_data = models.get("data") if isinstance(models, dict) else None
            model_rows = model_data if isinstance(model_data, list) else []
            models_valid = bool(model_rows) and all(
                isinstance(item, dict)
                and isinstance(item.get("id"), str)
                and bool(item["id"])
                for item in model_rows
            )
            model_ids = [item["id"] for item in model_rows] if models_valid else []
            toolset_data = (
                toolsets.get("data") if isinstance(toolsets, dict) else None
            )
            toolset_rows = toolset_data if isinstance(toolset_data, list) else []
            toolsets_valid = isinstance(toolset_data, list) and all(
                isinstance(item, dict)
                and isinstance(item.get("name"), str)
                and bool(item["name"])
                and isinstance(item.get("enabled"), bool)
                for item in toolset_rows
            )
            enabled_toolsets = (
                [item.get("name") for item in toolset_rows if item["enabled"]]
                if toolsets_valid
                else None
            )
            capabilities_valid = (
                isinstance(capabilities, dict)
                and isinstance(capabilities.get("features"), dict)
            )
            if (
                not isinstance(health, dict)
                or health.get("status") != "ok"
                or not models_valid
                or model_ids != [expected_model]
                or not capabilities_valid
                or capabilities.get("model") != expected_model
                or capabilities["features"].get("cors") is not False
                or enabled_toolsets is None
                or enabled_toolsets
            ):
                raise RuntimeError("Hermes API returned an unhealthy response.")
            return
        except (
            OSError,
            RuntimeError,
            ValueError,
            KeyError,
            urllib.error.URLError,
        ) as exc:
            last_error = exc
            if attempt < 9:
                time.sleep(1)
    raise RuntimeError("Hermes Share API health check failed.") from last_error


def _check_setup(
    args,
    *,
    check_api: bool = True,
    require_oauth: bool = True,
) -> tuple[Path, str, str]:
    _validate_args(args)
    hermes_home = _absolute_path(args.hermes_home)
    profile_dir = hermes_home / "profiles" / args.profile
    marker = profile_dir / ".harqis-share-profile"
    config_path = profile_dir / "config.yaml"
    profile_env = profile_dir / ".env"
    harqis_env = _absolute_path(args.harqis_env)
    _assert_profile_tree_safe(profile_dir)
    _assert_no_symlink_components(harqis_env)
    if not marker.is_file() or marker.is_symlink() or not config_path.is_file():
        raise RuntimeError("Managed Hermes Share profile is not configured.")
    _assert_private_permissions(profile_dir, directory=True)
    _assert_private_permissions(profile_env)
    _assert_private_permissions(harqis_env)
    _assert_oauth_credentials_private(profile_dir, required=require_oauth)
    # Hermes rewrites JSON-compatible YAML as ordinary YAML during migrations.
    # Only its schema-version metadata is exempt from the strict safety contract.
    import yaml

    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError("Expected a configuration mapping")
        version = config.pop("_config_version", 0)
        if type(version) is not int or version < 0:
            raise ValueError("Invalid schema version")
        # JSON comparison also distinguishes booleans from integers (True == 1
        # in ordinary Python dict equality), keeping the boundary fail-closed.
        valid = json.dumps(config, sort_keys=True) == json.dumps(
            locked_down_profile_config(args.model), sort_keys=True
        )
    except (yaml.YAMLError, TypeError, ValueError):
        raise RuntimeError("Hermes Share profile config is not locked down.") from None
    if not valid:
        raise RuntimeError(
            "Hermes Share profile config is not locked down. The dedicated API "
            "requires gateway.standalone: true; shared-gateway status is not readiness."
        )

    api_key = _env_value(profile_env, "API_SERVER_KEY")
    expected_profile_env = _profile_env_values(args.port, api_key)
    if not api_key or _env_mapping(profile_env) != expected_profile_env:
        raise RuntimeError("Hermes Share API environment is not locked down.")

    base_url = f"http://127.0.0.1:{args.port}/v1"
    expected_harqis = _harqis_env_values(
        args.port,
        api_key,
        args.context_chars,
    )
    actual_harqis = _env_mapping(harqis_env)
    if any(actual_harqis.get(key) != value for key, value in expected_harqis.items()):
        raise RuntimeError("HARQIS and Hermes Share environment settings disagree.")

    environment = _hermes_environment(hermes_home)
    if require_oauth and not _oauth_ready(args.profile, environment):
        raise RuntimeError("OpenAI Codex OAuth is not ready for the Share profile.")
    if check_api:
        _check_api(
            base_url=base_url,
            api_key=api_key,
            expected_model="share-corpus",
        )
    return profile_dir, api_key, base_url


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Configure a locked-down Hermes profile for HFL sharing."
    )
    parser.add_argument("--apply", action="store_true", help="Create and configure a new dedicated profile.")
    parser.add_argument("--login", action="store_true", help="Run profile-scoped OpenAI Codex OAuth login.")
    parser.add_argument("--start", action="store_true", help="Install/start the configured profile gateway.")
    parser.add_argument("--check", action="store_true", help="Verify configuration, OAuth, and API health.")
    parser.add_argument("--profile", default="sharecorpus")
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--port", type=int, default=8643)
    parser.add_argument("--context-chars", type=int, default=120_000)
    parser.add_argument(
        "--hermes-home",
        type=Path,
        default=Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")),
    )
    parser.add_argument(
        "--harqis-env",
        type=Path,
        default=REPO_ROOT / ".env" / "apps.env",
    )
    return parser


def _followup_command(args, action: str) -> str:
    return shlex.join(
        [
            "python",
            "scripts/agents/hfl/setup_hfl_share_hermes.py",
            action,
            "--profile",
            args.profile,
            "--model",
            args.model,
            "--port",
            str(args.port),
            "--context-chars",
            str(args.context_chars),
            "--hermes-home",
            str(args.hermes_home),
            "--harqis-env",
            str(args.harqis_env),
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _validate_args(args)
    if args.check and (args.apply or args.login or args.start):
        raise ValueError("--check cannot be combined with write/start actions.")
    if args.login and (args.apply or args.start):
        raise ValueError("--login must be run as a separate interactive step.")
    if not any((args.apply, args.login, args.start, args.check)):
        print("DRY RUN — no files or services changed")
        print(f"Hermes profile: {args.profile}")
        print(f"Model: openai-codex/{args.model}")
        print(f"API: http://127.0.0.1:{args.port}/v1")
        print(f"HARQIS env: {args.harqis_env}")
        print(f"Context budget: {args.context_chars} characters")
        print("Run again with --apply after reviewing this plan.")
        return 0
    if args.check:
        _check_setup(args)
        print("Configuration and API checks passed.")
        return 0
    if args.login:
        _check_setup(args, check_api=False, require_oauth=False)
        environment = _hermes_environment(args.hermes_home)
        result = _run_interactive(
            [
                "hermes",
                "-p",
                args.profile,
                "auth",
                "add",
                "openai-codex",
                "--type",
                "oauth",
            ],
            env=environment,
        )
        if result.returncode != 0 or not _oauth_ready(args.profile, environment):
            raise RuntimeError("OpenAI Codex OAuth did not complete for the Share profile.")
        print("OpenAI Codex OAuth is ready for the isolated Share profile.")
        return 0

    profile_dir: Path
    api_key: str
    base_url: str
    auth_ready: bool
    if args.apply:
        profile_dir, api_key, auth_ready = _apply(args)
        base_url = f"http://127.0.0.1:{args.port}/v1"
        print(f"Configured isolated Hermes profile: {profile_dir}")
        print(f"Configured HARQIS environment: {args.harqis_env}")
        print("API bearer key generated/synchronized without displaying it.")
    else:
        profile_dir, api_key, base_url = _check_setup(
            args,
            check_api=False,
            require_oauth=True,
        )
        auth_ready = True

    if not auth_ready:
        print("Codex OAuth is not ready for this isolated profile.")
        print(f"Run: {_followup_command(args, '--login')}")
        if args.start:
            print("Gateway was not started because profile OAuth is not ready.")
            return 2
        return 0

    if args.start:
        environment = _hermes_environment(args.hermes_home)
        for command in (
            ["hermes", "-p", args.profile, "gateway", "install"],
            ["hermes", "-p", args.profile, "gateway", "restart"],
        ):
            result = _run(command, env=environment)
            if result.returncode != 0:
                raise RuntimeError("Hermes gateway installation/start failed.")
        _check_api(
            base_url=base_url,
            api_key=api_key,
            expected_model="share-corpus",
        )
        print(f"Hermes Share API is ready at {base_url}")
        print("Restart the HARQIS frontend to load the updated environment.")
        return 0
    print(f"Next: {_followup_command(args, '--login')}")
    print(f"Then: {_followup_command(args, '--start')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
