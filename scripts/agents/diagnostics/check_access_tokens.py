#!/usr/bin/env python3
"""Silent token-expiry watchdog for HARQIS app credentials.

Checks app credentials that have an observable expiry/refresh signal and prints a
Telegram-ready alert only when a token is expired, revoked, near expiry, or
unusable. Quiet success is intentional: Hermes no-agent cron treats empty stdout
as "send nothing".

Usage:
  python scripts/agents/diagnostics/check_access_tokens.py
  python scripts/agents/diagnostics/check_access_tokens.py --json
  python scripts/agents/diagnostics/check_access_tokens.py --list-applicable
  python scripts/agents/diagnostics/check_access_tokens.py --dry-run

Config:
  machines.toml / machines.local.toml may define either a shared table:

    [token_expiry_watchdog]
    warn_within_days = 2
    include_checks = ["google_oauth", "spotify_refresh", "plaud_jwt", "jwt_env"]
    google_configs = ["GOOGLE_APPS", "GOOGLE_GMAIL", "GOOGLE_GMAIL_SEND", "GOOGLE_KEEP"]

  ...or a per-machine override:

    [<machine>.token_expiry_watchdog]
    enabled = true
    exclude_checks = ["jwt_env"]

Exit codes:
  0  checks completed; stdout is non-empty only when there is an alert
  2  configuration/runtime error in this watchdog itself
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import sys
import time
import tomllib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# scripts/agents/diagnostics/check_access_tokens.py → repo root is parents[3].
REPO_ROOT = Path(__file__).resolve().parents[3]
MACHINES_TOML = REPO_ROOT / "machines.toml"
DEFAULT_CHECKS = ["google_oauth", "spotify_refresh", "plaud_jwt", "jwt_env"]
DEFAULT_GOOGLE_CONFIGS = ["GOOGLE_APPS", "GOOGLE_GMAIL", "GOOGLE_GMAIL_SEND", "GOOGLE_KEEP", "GOOGLE_TASKS", "GOOGLE_DRIVE"]


@dataclass
class Finding:
    check: str
    app: str
    status: str
    detail: str
    expires_at: str | None = None
    remediation: str | None = None


@dataclass
class CheckResult:
    check: str
    app: str
    status: str
    detail: str
    expires_at: str | None = None


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--machine", help="Machine config name; defaults to hostname mapping.")
    p.add_argument("--json", action="store_true", help="Print machine-readable results, including OKs.")
    p.add_argument("--dry-run", action="store_true", help="Print a concise OK/applicable summary instead of staying silent.")
    p.add_argument("--list-applicable", action="store_true", help="List discovered token checks and exit.")
    return p.parse_args()


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = {**base}
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _load_machines() -> dict[str, Any]:
    if not MACHINES_TOML.exists():
        return {}
    cfg = tomllib.loads(MACHINES_TOML.read_text(encoding="utf-8"))
    local = MACHINES_TOML.with_suffix(".local.toml")
    if local.exists():
        cfg = _merge(cfg, tomllib.loads(local.read_text(encoding="utf-8")))
    return cfg


def _machine_name(cfg: dict[str, Any], explicit: str | None) -> str:
    if explicit:
        return explicit
    host = socket.gethostname()
    hostnames = cfg.get("hostnames", {}) if isinstance(cfg.get("hostnames"), dict) else {}
    return hostnames.get(host) or hostnames.get(host.lower()) or "default"


def _watchdog_config(machine_name: str) -> dict[str, Any]:
    cfg = _load_machines()
    shared = cfg.get("token_expiry_watchdog", {}) if isinstance(cfg.get("token_expiry_watchdog"), dict) else {}
    machine = cfg.get(machine_name, {}) if isinstance(cfg.get(machine_name), dict) else {}
    local = machine.get("token_expiry_watchdog", {}) if isinstance(machine.get("token_expiry_watchdog"), dict) else {}
    merged = _merge(shared, local)
    if "enabled" not in merged:
        merged["enabled"] = True
    merged.setdefault("warn_within_days", 2)
    merged.setdefault("notify_missing", False)
    merged.setdefault("include_checks", DEFAULT_CHECKS)
    merged.setdefault("google_configs", DEFAULT_GOOGLE_CONFIGS)
    excludes = set(merged.get("exclude_checks") or [])
    merged["include_checks"] = [c for c in (merged.get("include_checks") or DEFAULT_CHECKS) if c not in excludes]
    return merged


def _bootstrap_env() -> None:
    scripts_dir = REPO_ROOT / "scripts"
    for p in (REPO_ROOT, scripts_dir):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    try:
        from launch import setup_env  # type: ignore

        setup_env()
    except Exception:
        try:
            from dotenv import load_dotenv

            load_dotenv(REPO_ROOT / ".env" / "apps.env", override=False)
        except Exception:
            pass
    os.environ.setdefault("PATH_APP_CONFIG", str(REPO_ROOT))
    os.environ.setdefault("PATH_APP_CONFIG_SECRETS", str(REPO_ROOT / ".env"))
    os.environ.setdefault("APP_CONFIG_FILE", "apps_config.yaml")


def _load_apps_config() -> dict[str, Any]:
    import yaml

    path = Path(os.environ.get("PATH_APP_CONFIG", str(REPO_ROOT))) / os.environ.get("APP_CONFIG_FILE", "apps_config.yaml")
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    return data if isinstance(data, dict) else {}


def _resolve_env(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if value.startswith("${") and value.endswith("}"):
        return os.environ.get(value[2:-1], "")
    return value


def _app_data(apps: dict[str, Any], name: str) -> dict[str, Any]:
    block = apps.get(name) or {}
    data = block.get("app_data") or {}
    return {k: _resolve_env(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _utc(ts: float | int | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat(timespec="seconds")


def _seconds_until(expiry_iso_or_ts: str | float | int | None) -> float | None:
    if expiry_iso_or_ts is None:
        return None
    if isinstance(expiry_iso_or_ts, (int, float)):
        return float(expiry_iso_or_ts) - time.time()
    try:
        return datetime.fromisoformat(expiry_iso_or_ts.replace("Z", "+00:00")).timestamp() - time.time()
    except Exception:
        return None


def _decode_jwt_exp(token: str) -> float | None:
    parts = token.split(".")
    if len(parts) < 2:
        return None
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except Exception:
        return None
    exp = claims.get("exp")
    try:
        return float(exp) if exp else None
    except (TypeError, ValueError):
        return None


def _finding_if_expired(check: str, app: str, detail: str, exp_ts: float | None, warn_days: float, remediation: str | None) -> Finding | None:
    if exp_ts is None:
        return None
    remaining = exp_ts - time.time()
    expires_at = _utc(exp_ts)
    if remaining <= 0:
        return Finding(check, app, "expired", detail, expires_at, remediation)
    if remaining <= warn_days * 86400:
        return Finding(check, app, "expires_soon", detail, expires_at, remediation)
    return None


def check_google(apps: dict[str, Any], cfg: dict[str, Any]) -> tuple[list[Finding], list[CheckResult]]:
    findings: list[Finding] = []
    results: list[CheckResult] = []
    warn_days = float(cfg.get("warn_within_days", 2))
    configs = cfg.get("google_configs") or DEFAULT_GOOGLE_CONFIGS
    secrets_dir = Path(os.environ.get("PATH_APP_CONFIG_SECRETS", str(REPO_ROOT / ".env")))

    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    for name in configs:
        data = _app_data(apps, str(name))
        storage = data.get("storage")
        scopes = data.get("scopes") or []
        if not storage:
            continue
        storage_path = secrets_dir / str(storage)
        if not storage_path.exists():
            missing = CheckResult("google_oauth", str(name), "missing", f"OAuth storage file is missing: {storage}")
            if cfg.get("notify_missing"):
                findings.append(Finding(
                    "google_oauth", str(name), "missing", f"OAuth storage file is missing: {storage}", None,
                    f"Run scripts/agents/diagnostics/reauth_gmail_send.py --config {name} or the matching Google reauth flow.",
                ))
            else:
                results.append(missing)
            continue
        try:
            creds = Credentials.from_authorized_user_file(str(storage_path), scopes)
        except Exception as exc:
            findings.append(Finding("google_oauth", str(name), "invalid", f"OAuth storage cannot be parsed ({type(exc).__name__}).", None,
                                    f"Re-authorize {name}; replace {storage} under .env/."))
            continue

        expiry = creds.expiry.replace(tzinfo=timezone.utc).isoformat(timespec="seconds") if creds.expiry else None
        try:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                results.append(CheckResult("google_oauth", str(name), "ok", "expired access token refreshed successfully in memory", expiry))
            elif creds.expired:
                findings.append(Finding("google_oauth", str(name), "expired", "OAuth access token expired and no refresh_token is present.", expiry,
                                        f"Re-authorize {name}; this token cannot refresh itself."))
            else:
                soon = _finding_if_expired("google_oauth", str(name), "OAuth access token is close to expiry.", creds.expiry.timestamp() if creds.expiry else None, warn_days, None)
                if soon and not creds.refresh_token:
                    findings.append(soon)
                else:
                    results.append(CheckResult("google_oauth", str(name), "ok", "OAuth storage is usable", expiry))
        except RefreshError as exc:
            findings.append(Finding("google_oauth", str(name), "revoked_or_expired", f"Refresh failed: {exc}", expiry,
                                    f"Run scripts/agents/diagnostics/reauth_gmail_send.py --config {name}; if it recurs weekly, move the OAuth app to production."))
        except Exception as exc:
            findings.append(Finding("google_oauth", str(name), "check_failed", f"Refresh check failed ({type(exc).__name__}): {exc}", expiry,
                                    f"Inspect {name} Google OAuth storage and network connectivity."))
    return findings, results


def check_spotify(apps: dict[str, Any], cfg: dict[str, Any]) -> tuple[list[Finding], list[CheckResult]]:
    findings: list[Finding] = []
    results: list[CheckResult] = []
    data = _app_data(apps, "SPOTIFY")
    if not all(data.get(k) for k in ("client_id", "client_secret", "refresh_token")):
        return findings, results
    import httpx

    try:
        resp = httpx.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "refresh_token", "refresh_token": data["refresh_token"]},
            auth=(data["client_id"], data["client_secret"]),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30.0,
        )
        if resp.status_code >= 400:
            detail = "Spotify refresh-token exchange failed"
            try:
                body = resp.json() or {}
                if body.get("error"):
                    detail += f": {body.get('error')}"
                if body.get("error_description"):
                    detail += f" — {body.get('error_description')}"
            except Exception:
                detail += f" with HTTP {resp.status_code}"
            findings.append(Finding("spotify_refresh", "SPOTIFY", "revoked_or_expired", detail, None,
                                    "Re-run apps/spotify/mint_token.py and update SPOTIFY_REFRESH_TOKEN."))
            return findings, results
        body = resp.json() or {}
        if not body.get("access_token"):
            findings.append(Finding("spotify_refresh", "SPOTIFY", "invalid", "Token endpoint returned no access_token.", None,
                                    "Re-run apps/spotify/mint_token.py and update SPOTIFY_REFRESH_TOKEN."))
        else:
            expires_at = _utc(time.time() + float(body.get("expires_in") or 3600))
            results.append(CheckResult("spotify_refresh", "SPOTIFY", "ok", "refresh token minted a fresh access token", expires_at))
    except Exception as exc:
        findings.append(Finding("spotify_refresh", "SPOTIFY", "check_failed", f"Refresh-token check failed ({type(exc).__name__}): {exc}", None,
                                "Check network/client credentials; if invalid_grant appears, mint a new Spotify refresh token."))
    return findings, results


def check_plaud(apps: dict[str, Any], cfg: dict[str, Any]) -> tuple[list[Finding], list[CheckResult]]:
    findings: list[Finding] = []
    results: list[CheckResult] = []
    warn_days = float(cfg.get("warn_within_days", 2))
    data = _app_data(apps, "PLAUD")

    # Preferred Plaud auth is email/password auto-minting. If those are present,
    # a stale PLAUD_TOKEN fallback should not page Brian; the adapter mints and
    # caches a fresh token before using the manual token fallback.
    if data.get("email") and data.get("password"):
        cache = REPO_ROOT / "logs" / "plaud_token.json"
        if cache.exists():
            try:
                cached = json.loads(cache.read_text(encoding="utf-8"))
                exp = float(cached.get("expires_at") or 0) or None
                finding = _finding_if_expired("plaud_jwt", "PLAUD", "Cached Plaud access token is expired or near expiry; auto-mint credentials are configured.", exp, warn_days, None)
                if finding and finding.status == "expired":
                    # Expired cache is OK when email/password can mint a replacement.
                    results.append(CheckResult("plaud_jwt", "PLAUD", "ok", "cached token expired but auto-mint credentials are configured", _utc(exp)))
                elif finding:
                    results.append(CheckResult("plaud_jwt", "PLAUD", "ok", "cached token near expiry but auto-mint credentials are configured", _utc(exp)))
                else:
                    results.append(CheckResult("plaud_jwt", "PLAUD", "ok", "cached token usable; auto-mint credentials configured", _utc(exp)))
            except Exception as exc:
                results.append(CheckResult("plaud_jwt", "PLAUD", "unknown", f"could not parse Plaud cache ({type(exc).__name__}); auto-mint credentials configured"))
        else:
            results.append(CheckResult("plaud_jwt", "PLAUD", "ok", "auto-mint credentials configured; no manual token to expire"))
        return findings, results

    token = str(data.get("token") or "")
    if token:
        exp = _decode_jwt_exp(token)
        finding = _finding_if_expired("plaud_jwt", "PLAUD", "Manual PLAUD_TOKEN JWT is expired or near expiry.", exp, warn_days,
                                      "Refresh PLAUD_TOKEN from web.plaud.ai or switch to PLAUD_EMAIL+PLAUD_PASSWORD auto-minting.")
        if finding:
            findings.append(finding)
        elif exp:
            results.append(CheckResult("plaud_jwt", "PLAUD", "ok", "manual PLAUD_TOKEN JWT has a future exp", _utc(exp)))
        else:
            results.append(CheckResult("plaud_jwt", "PLAUD", "unknown", "manual PLAUD_TOKEN is not a JWT with exp; expiry cannot be predicted"))
    return findings, results


def check_jwt_env(apps: dict[str, Any], cfg: dict[str, Any]) -> tuple[list[Finding], list[CheckResult]]:
    findings: list[Finding] = []
    results: list[CheckResult] = []
    warn_days = float(cfg.get("warn_within_days", 2))
    for app_name, block in apps.items():
        if not isinstance(block, dict):
            continue
        data = block.get("app_data") or {}
        if not isinstance(data, dict):
            continue
        for key, raw in data.items():
            if str(app_name) == "PLAUD" and str(key) == "token":
                # Covered by plaud_jwt with Plaud-specific remediation; avoid duplicate alerts.
                continue
            value = _resolve_env(raw)
            if not isinstance(value, str) or value.count(".") < 2 or len(value) < 40:
                continue
            exp = _decode_jwt_exp(value)
            if exp is None:
                continue
            app = f"{app_name}.{key}"
            finding = _finding_if_expired("jwt_env", app, "JWT-style configured token is expired or near expiry.", exp, warn_days,
                                          f"Refresh the {key} value for {app_name} in the host secret store.")
            if finding:
                findings.append(finding)
            else:
                results.append(CheckResult("jwt_env", app, "ok", "JWT exp is still in the future", _utc(exp)))
    return findings, results


def _render_alert(machine: str, findings: list[Finding]) -> str:
    if not findings:
        return ""
    lines = [
        "HARQIS token expiry watchdog",
        f"Host: {machine}",
        f"Findings: {len(findings)} token issue(s)",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    for item in findings:
        lines.append(f"• {item.app} [{item.status}]")
        lines.append(f"  Check: {item.check}")
        if item.expires_at:
            lines.append(f"  Expires: {item.expires_at}")
        lines.append(f"  Detail: {item.detail}")
        if item.remediation:
            lines.append(f"  Fix: {item.remediation}")
    return "\n".join(lines)


def main() -> int:
    args = _parse_args()
    _bootstrap_env()
    machines = _load_machines()
    machine = _machine_name(machines, args.machine)
    cfg = _watchdog_config(machine)
    if not cfg.get("enabled", True):
        return 0

    try:
        apps = _load_apps_config()
    except Exception as exc:
        print(f"HARQIS token expiry watchdog failed to load apps_config.yaml ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 2

    checks = cfg.get("include_checks") or DEFAULT_CHECKS
    findings: list[Finding] = []
    results: list[CheckResult] = []

    runners = {
        "google_oauth": check_google,
        "spotify_refresh": check_spotify,
        "plaud_jwt": check_plaud,
        "jwt_env": check_jwt_env,
    }
    for check in checks:
        runner = runners.get(str(check))
        if not runner:
            continue
        try:
            f, r = runner(apps, cfg)
            findings.extend(f)
            results.extend(r)
        except Exception as exc:
            findings.append(Finding(str(check), "watchdog", "check_failed", f"{check} crashed ({type(exc).__name__}): {exc}", None,
                                    "Fix the watchdog or disable this check in machines.local.toml."))

    if args.list_applicable:
        for result in results:
            print(f"{result.check}: {result.app} — {result.status} ({result.detail})")
        for finding in findings:
            print(f"{finding.check}: {finding.app} — {finding.status} ({finding.detail})")
        return 0

    if args.json:
        print(json.dumps({
            "machine": machine,
            "findings": [asdict(f) for f in findings],
            "results": [asdict(r) for r in results],
        }, indent=2, sort_keys=True))
        return 0

    if args.dry_run:
        print(f"HARQIS token expiry watchdog dry run: {len(findings)} finding(s), {len(results)} ok/applicable check(s) on {machine}.")
        if findings:
            print(_render_alert(machine, findings))
        return 0

    alert = _render_alert(machine, findings)
    if alert:
        print(alert)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
