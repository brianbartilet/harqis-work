#!/usr/bin/env python3
"""
Daily Test Farm email sequence.

Usage:
  python scripts/agents/testing/daily_test_farm_email.py
  python scripts/agents/testing/daily_test_farm_email.py --dry-run --skip-generate

Runs the existing BDD test farm workflow, renders logs/BDD-TEST-FARM.md to HTML,
and sends it via the HARQIS GOOGLE_GMAIL_SEND configuration.
"""
from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[3]
LOGS_DIR = REPO_ROOT / "logs"
FARM_MD = LOGS_DIR / "BDD-TEST-FARM.md"
EMAIL_LOG_DIR = LOGS_DIR / "test_farm_email"
# Generic placeholders only — the real recipients/sender are resolved in main()
# AFTER _bootstrap_env() loads .env/apps.env, from TEST_FARM_EMAIL_TO /
# TEST_FARM_EMAIL_FROM. Nothing identifying ships in the public source tree.
DEFAULT_TO = "owner@example.com"
DEFAULT_FROM = "owner@example.com"
DEFAULT_BOARD_ID = 1790
DEFAULT_GMAIL_CONFIG = "GOOGLE_GMAIL_SEND"
DEFAULT_TELEGRAM_CONFIG = "TELEGRAM"


def _bootstrap_env() -> None:
    """Load the same HARQIS env/config defaults as runtime services."""
    scripts_dir = REPO_ROOT / "scripts"
    for p in (REPO_ROOT, scripts_dir):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))

    # Reuse the runtime launcher setup so .env/apps.env, machine overrides,
    # PYTHONPATH, PATH_APP_CONFIG, and APP_CONFIG_FILE match HARQIS services.
    from launch import setup_env  # type: ignore

    setup_env()
    os.environ.setdefault("PATH_APP_CONFIG", str(REPO_ROOT))
    os.environ.setdefault("PATH_APP_CONFIG_SECRETS", str(REPO_ROOT / ".env"))
    os.environ.setdefault("APP_CONFIG_FILE", "apps_config.yaml")


def _call_task(task_obj, *args, **kwargs):
    """Call a Celery task object directly without queueing it."""
    if hasattr(task_obj, "run"):
        return task_obj.run(*args, **kwargs)
    return task_obj(*args, **kwargs)


def _claude_oauth_env() -> dict[str, str]:
    """Environment for Claude Code Max/OAuth runs, not API-key billing."""
    env = dict(os.environ)
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        env.pop(key, None)
    return env


def preflight_claude(claude_bin: str | None, model: str) -> str:
    """Verify local Claude Code is installed and authenticated before emailing."""
    bin_path = claude_bin or shutil.which("claude")
    if not bin_path:
        raise RuntimeError("claude CLI not found on PATH; cannot refresh the test farm via local Max subscription")

    proc = subprocess.run(
        [bin_path, "-p", "Reply exactly: OK", "--model", model, "--max-turns", "1"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60, env=_claude_oauth_env(),
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        msg = detail[0] if detail else f"exit {proc.returncode}"
        raise RuntimeError(f"claude CLI Max/OAuth preflight failed: {msg}")
    return bin_path


def refresh_test_farm(args: argparse.Namespace) -> str:
    from workflows.testing.tasks.test_farm import run_test_farm

    old_api_key = os.environ.pop("ANTHROPIC_API_KEY", None)
    old_auth_token = os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
    try:
        return str(_call_task(
            run_test_farm,
            board_id=args.board_id,
            cfg_id__jira=args.jira_config,
            claude_model=args.claude_model,
            claude_bin=args.claude_bin,
            max_thinking_tokens=args.max_thinking_tokens,
            per_ticket_timeout=args.per_ticket_timeout,
            inter_ticket_delay=args.inter_ticket_delay,
            max_results=args.max_results,
            limit=args.limit,
            force=args.force,
        ))
    finally:
        if old_api_key is not None:
            os.environ["ANTHROPIC_API_KEY"] = old_api_key
        if old_auth_token is not None:
            os.environ["ANTHROPIC_AUTH_TOKEN"] = old_auth_token


def _render_inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def _table_to_html(lines: list[str]) -> str:
    rows: list[list[str]] = []
    for line in lines:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and all(re.fullmatch(r":?-{3,}:?", c or "") for c in cells):
            continue
        rows.append(cells)
    if not rows:
        return ""
    out = ["<table>"]
    for i, row in enumerate(rows):
        tag = "th" if i == 0 else "td"
        out.append("<tr>" + "".join(f"<{tag}>{_render_inline(c)}</{tag}>" for c in row) + "</tr>")
    out.append("</table>")
    return "\n".join(out)


def _fallback_markdown_to_html(markdown_text: str) -> str:
    """Small renderer for email-safe HTML when python-markdown is unavailable."""
    out: list[str] = []
    paragraph: list[str] = []
    table: list[str] = []
    code: list[str] = []
    in_code = False

    def flush_paragraph() -> None:
        if paragraph:
            out.append(f"<p>{_render_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    def flush_table() -> None:
        if table:
            out.append(_table_to_html(table))
            table.clear()

    for raw in markdown_text.splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            flush_paragraph(); flush_table()
            if in_code:
                out.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
                code.clear()
            in_code = not in_code
            continue
        if in_code:
            code.append(line)
            continue
        if not line.strip():
            flush_paragraph(); flush_table()
            continue
        if line.startswith("<a "):
            flush_paragraph(); flush_table()
            out.append(line)
            continue
        if line.startswith("|") and line.endswith("|"):
            flush_paragraph()
            table.append(line)
            continue
        flush_table()
        if line.startswith("#"):
            flush_paragraph()
            level = min(len(line) - len(line.lstrip("#")), 3)
            text = line[level:].strip()
            out.append(f"<h{level}>{_render_inline(text)}</h{level}>")
        elif line.startswith("---"):
            flush_paragraph()
            out.append("<hr>")
        elif line.startswith(">"):
            flush_paragraph()
            out.append(f"<blockquote>{_render_inline(line.lstrip('> ').strip())}</blockquote>")
        else:
            paragraph.append(line.strip())
    flush_paragraph(); flush_table()
    if code:
        out.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
    return "\n".join(out)


def markdown_to_html(markdown_text: str, title: str) -> str:
    try:
        import markdown  # type: ignore
        body = markdown.markdown(markdown_text, extensions=["extra", "tables", "fenced_code"])
    except Exception:
        body = _fallback_markdown_to_html(markdown_text)

    css = """
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; line-height: 1.45; color: #17202a; }
    .wrap { max-width: 1100px; margin: 0 auto; }
    h1, h2, h3 { color: #0b3d91; }
    table { border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 14px; }
    th, td { border: 1px solid #d8dee4; padding: 8px 10px; vertical-align: top; }
    th { background: #f3f6fa; text-align: left; }
    code, pre { background: #f6f8fa; border-radius: 4px; }
    code { padding: 1px 4px; }
    pre { padding: 12px; overflow-x: auto; }
    blockquote { border-left: 4px solid #d8dee4; color: #57606a; margin-left: 0; padding-left: 12px; }
    a { color: #0969da; }
    """
    return f"""<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\">
  <title>{html.escape(title)}</title>
  <style>{css}</style>
</head>
<body>
  <div class=\"wrap\">
    <h1>{html.escape(title)}</h1>
    {body}
  </div>
</body>
</html>
"""


def preflight_gmail(cfg_id: str) -> None:
    """Fail fast if the HARQIS Gmail send OAuth token cannot refresh."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google.auth.exceptions import RefreshError
    from apps.apps_config import CONFIG_MANAGER

    cfg = CONFIG_MANAGER.get(cfg_id)
    storage = Path(os.environ["PATH_APP_CONFIG_SECRETS"]) / cfg.app_data.get("storage")
    scopes = cfg.app_data.get("scopes") or []
    if not storage.exists():
        raise RuntimeError(f"Gmail token storage is missing for {cfg_id}: {storage}")

    creds = Credentials.from_authorized_user_file(storage, scopes)
    if creds.valid:
        return
    if not (creds.expired and creds.refresh_token):
        raise RuntimeError(f"Gmail token for {cfg_id} is not refreshable; re-authorize {storage.name}")
    try:
        creds.refresh(Request())
    except RefreshError as e:
        raise RuntimeError(
            f"Gmail token refresh failed for {cfg_id}; re-authorize {storage.name}: {e}"
        ) from e
    storage.write_text(creds.to_json(), encoding="utf-8")


def send_email(to_addr: str, subject: str, plain_text: str, html_text: str, cfg_id: str) -> dict:
    from apps.apps_config import CONFIG_MANAGER
    from apps.google_apps.references.web.api.gmail import ApiServiceGoogleGmail

    cfg = CONFIG_MANAGER.get(cfg_id)
    svc = ApiServiceGoogleGmail(cfg)
    return svc.send_email(to=to_addr, subject=subject, body=plain_text, body_html=html_text)


def send_telegram_notification(
    subject: str,
    to_addr: str,
    generation_summary: str,
    html_path: Path,
    cfg_id: str,
    chat_id: str | None = None,
) -> Any:
    from apps.apps_config import CONFIG_MANAGER
    from apps.telegram.references.web.api.messages import ApiServiceTelegramMessages

    cfg = CONFIG_MANAGER.get(cfg_id)
    target_chat = chat_id or cfg.app_data.get("default_chat_id")
    if not target_chat:
        raise RuntimeError(f"Telegram default_chat_id is missing for {cfg_id}")
    text = (
        f"✅ {subject}\n"
        f"Sent to: {to_addr}\n"
        f"Artifact: {html_path}\n"
        f"{generation_summary}"
    )
    svc = ApiServiceTelegramMessages(cfg)
    return svc.send_message(chat_id=target_chat, text=text)


def write_artifacts(subject: str, markdown_text: str, html_text: str) -> tuple[Path, Path]:
    EMAIL_LOG_DIR.mkdir(parents=True, exist_ok=True)
    stem = datetime.now().strftime("%Y-%m-%d") + "-test-farm"
    html_path = EMAIL_LOG_DIR / f"{stem}.html"
    txt_path = EMAIL_LOG_DIR / f"{stem}.txt"
    html_path.write_text(html_text, encoding="utf-8")
    txt_path.write_text(f"{subject}\n\n{markdown_text}", encoding="utf-8")
    return html_path, txt_path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run BDD test farm and email rendered scenarios.")
    p.add_argument("--dry-run", action="store_true", help="render artifacts but do not send email")
    p.add_argument("--skip-generate", action="store_true", help="use existing logs/BDD-TEST-FARM.md")
    p.add_argument("--to", default=None, help=f"recipients (default: $TEST_FARM_EMAIL_TO, else {DEFAULT_TO})")
    p.add_argument("--from-account", default=None, help="documented sender account; Gmail token controls actual sender")
    p.add_argument("--gmail-config", default=DEFAULT_GMAIL_CONFIG)
    p.add_argument("--telegram-config", default=DEFAULT_TELEGRAM_CONFIG)
    p.add_argument("--telegram-chat-id", default=None, help="override TELEGRAM default_chat_id")
    p.add_argument("--no-telegram", action="store_true", help="skip Telegram completion notification")
    p.add_argument("--board-id", type=int, default=DEFAULT_BOARD_ID)
    p.add_argument("--jira-config", default="JIRA")
    p.add_argument("--claude-model", default="sonnet")
    p.add_argument("--claude-bin", default=None)
    p.add_argument("--max-thinking-tokens", type=int, default=None)
    p.add_argument("--per-ticket-timeout", type=int, default=420)
    p.add_argument("--inter-ticket-delay", type=int, default=5)
    p.add_argument("--max-results", type=int, default=200)
    p.add_argument("--limit", type=int, default=None, help="max new ticket generations this run")
    p.add_argument("--force", action="store_true", help="force regeneration of all tickets")
    p.add_argument("--no-claude-preflight", action="store_true", help="skip local Claude auth probe before generation")
    return p.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    _bootstrap_env()

    # Resolve recipients/sender now that apps.env is loaded (CLI > env > placeholder).
    args.to = args.to or os.environ.get("TEST_FARM_EMAIL_TO", DEFAULT_TO)
    args.from_account = args.from_account or os.environ.get("TEST_FARM_EMAIL_FROM", DEFAULT_FROM)

    date_label = datetime.now().strftime("%d-%m-%Y")
    subject = f"TEST FARM {date_label}"

    if args.skip_generate:
        generation_summary = "Skipped test farm generation; using existing markdown."
    else:
        if not args.no_claude_preflight:
            args.claude_bin = preflight_claude(args.claude_bin, args.claude_model)
        generation_summary = refresh_test_farm(args)

    if not FARM_MD.exists():
        raise FileNotFoundError(f"Missing test farm markdown: {FARM_MD}")

    markdown_text = FARM_MD.read_text(encoding="utf-8")
    plain_text = f"{generation_summary}\n\nRendered source: {FARM_MD}\n\n{markdown_text}"
    html_text = markdown_to_html(markdown_text, subject)
    html_path, txt_path = write_artifacts(subject, markdown_text, html_text)

    if args.dry_run:
        print(f"DRY RUN: rendered {subject} for {args.to}; not sent.")
        print(f"HTML: {html_path}")
        print(f"TEXT: {txt_path}")
        print(generation_summary)
        return 0

    preflight_gmail(args.gmail_config)
    result = send_email(args.to, subject, plain_text, html_text, args.gmail_config)
    msg_id = result.get("id", "unknown") if isinstance(result, dict) else "unknown"
    print(f"Sent {subject} from {args.from_account} to {args.to}; gmail_message_id={msg_id}")
    if not args.no_telegram:
        tg_result = send_telegram_notification(
            subject,
            args.to,
            generation_summary,
            html_path,
            args.telegram_config,
            args.telegram_chat_id,
        )
        tg_msg_id = tg_result.get("message_id", "unknown") if isinstance(tg_result, dict) else "unknown"
        print(f"Telegram notification sent; message_id={tg_msg_id}")
    print(f"HTML: {html_path}")
    print(f"TEXT: {txt_path}")
    print(generation_summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
