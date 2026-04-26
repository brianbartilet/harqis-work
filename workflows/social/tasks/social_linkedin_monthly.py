"""
workflows/social/tasks/social_linkedin_monthly.py

Generates a monthly LinkedIn update post for the HARQIS-WORK platform.

Pipeline:
  1. Collect git commit log for the target month from the local repo
  2. Optionally load the previous monthly post from logs/linkedin/ for style context
  3. Optionally load the last LinkedIn post via the LinkedIn API for context
  4. Call Claude (Anthropic) to compose a professional, emoji-enriched post
  5. Save the post as a markdown file in logs/linkedin/
  6. Create a LinkedIn draft post via the LinkedIn API
  7. Send a Gmail notification with the draft content and file path

Default schedule: 1st of each month at 08:00 Asia/Singapore.
Target month is configurable via kwargs (defaults to the previous calendar month).
"""

import calendar
import subprocess
from datetime import date
from pathlib import Path
from typing import Optional

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.apps_config import CONFIG_MANAGER
from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
from apps.linkedin.references.web.api.posts import ApiServiceLinkedInPosts
from apps.google_apps.references.web.api.gmail import ApiServiceGoogleGmail

from workflows.social.prompts import load_prompt

_log = create_logger("social.social_linkedin_monthly")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOGS_DIR = _REPO_ROOT / "logs" / "linkedin"
_HARQIS_REPO_URL = "https://github.com/brianbartilet/harqis-work"


# ── Git helpers ───────────────────────────────────────────────────────────────

def _get_git_commits(year: int, month: int) -> list[dict]:
    """Return all git commits for the given month from the harqis-work repo."""
    last_day = calendar.monthrange(year, month)[1]
    since = f"{year}-{month:02d}-01"
    until = f"{year}-{month:02d}-{last_day}"

    result = subprocess.run(
        [
            "git", "log",
            f"--since={since}",
            f"--until={until} 23:59:59",
            "--format=%H|%ad|%s",
            "--date=short",
            "--no-merges",
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )

    commits = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split("|", 2)
        if len(parts) == 3:
            commits.append({
                "hash": parts[0][:8],
                "date": parts[1],
                "subject": parts[2],
            })

    _log.info("_get_git_commits: found %d commits for %d-%02d", len(commits), year, month)
    return commits


def _format_commits_for_prompt(commits: list[dict]) -> str:
    if not commits:
        return "(no commits found for this month)"
    lines = [f"  [{c['date']}] {c['subject']}" for c in commits]
    return "\n".join(lines)


# ── Previous post helpers ─────────────────────────────────────────────────────

def _load_previous_post_from_logs(year: int, month: int) -> Optional[str]:
    """
    Load the most recent previous monthly post from logs/linkedin/.
    Checks the file for (month-1) first, then walks backwards up to 6 months.
    """
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    for delta in range(1, 7):
        prev_month = month - delta
        prev_year = year
        while prev_month < 1:
            prev_month += 12
            prev_year -= 1
        path = _LOGS_DIR / f"MONTHLY-WORK-UPDATE-{prev_month:02d}-{prev_year}.md"
        if path.exists():
            _log.info("_load_previous_post_from_logs: found %s", path.name)
            return path.read_text(encoding="utf-8")
    return None


def _get_linkedin_last_post(cfg_id__linkedin: str) -> Optional[str]:
    """Try to fetch the last LinkedIn post for style context. Silently skips on error."""
    try:
        cfg = CONFIG_MANAGER.get(cfg_id__linkedin)
        default_urn = cfg.app_data.get("default_post_urn", "")
        if not default_urn:
            return None
        service = ApiServiceLinkedInPosts(cfg)
        post = service.get_post(default_urn)
        text = (
            post.get("specificContent", {})
            .get("com.linkedin.ugc.ShareContent", {})
            .get("shareCommentary", {})
            .get("text", "")
        )
        if text:
            _log.info("_get_linkedin_last_post: loaded last post (%d chars)", len(text))
        return text or None
    except Exception as exc:
        _log.warning("_get_linkedin_last_post: could not fetch last post — %s", exc)
        return None


# ── Claude generation ─────────────────────────────────────────────────────────

def _generate_post_with_claude(
    year: int,
    month: int,
    commits: list[dict],
    previous_post: Optional[str],
    cfg_id__anthropic: str,
) -> str:
    """Call Claude to compose the LinkedIn post."""
    month_name = date(year, month, 1).strftime("%B")
    commit_text = _format_commits_for_prompt(commits)

    system_prompt = load_prompt("monthly_linkedin_post")

    user_message = (
        f"Target month: {month_name} {year}\n\n"
        f"Git commit log for {month_name} {year}:\n{commit_text}\n"
    )
    if previous_post:
        user_message += f"\nPrevious monthly post (for style reference):\n\n{previous_post}\n"

    client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id__anthropic))
    if not client.base_client:
        raise RuntimeError("Anthropic client failed to initialize")

    response = client._with_backoff(
        client.base_client.messages.create,
        model=client.model,
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    return response.content[0].text.strip()


# ── Save to file ──────────────────────────────────────────────────────────────

def _save_post_to_file(year: int, month: int, post_text: str) -> Path:
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"MONTHLY-WORK-UPDATE-{month:02d}-{year}.md"
    path = _LOGS_DIR / filename
    path.write_text(post_text, encoding="utf-8")
    _log.info("_save_post_to_file: saved to %s", path)
    return path


# ── Gmail notification ────────────────────────────────────────────────────────

def _send_gmail_notification(
    cfg_id__gmail: str,
    year: int,
    month: int,
    post_text: str,
    output_path: Path,
    draft_result: dict,
    recipient_email: str,
) -> None:
    """Send a Gmail notification that the draft is ready."""
    month_name = date(year, month, 1).strftime("%B")
    subject = f"✅ HARQIS-WORK {month_name} {year} LinkedIn Draft Ready"

    preview = post_text[:500] + ("..." if len(post_text) > 500 else "")

    body = (
        f"Your monthly LinkedIn draft for {month_name} {year} is ready.\n\n"
        f"📄 Saved to: {output_path}\n\n"
        f"--- Draft preview ---\n{preview}\n\n"
        f"--- LinkedIn API response ---\n{draft_result}\n\n"
        f"Next steps:\n"
        f"  1. Open LinkedIn and find the draft in your posts.\n"
        f"  2. Review and adjust if needed.\n"
        f"  3. Publish when ready.\n"
    )

    try:
        cfg = CONFIG_MANAGER.get(cfg_id__gmail)
        gmail = ApiServiceGoogleGmail(cfg)
        gmail.send_email(to=recipient_email, subject=subject, body=body)
        _log.info("_send_gmail_notification: email sent to %s", recipient_email)
    except Exception as exc:
        _log.warning("_send_gmail_notification: failed — %s", exc)


# ── Main task ─────────────────────────────────────────────────────────────────

@SPROUT.task()
@log_result()
def generate_monthly_linkedin_post(**kwargs):
    """Generate, save, and draft the HARQIS-WORK monthly LinkedIn update post.

    Args:
        month:              Target month number (1–12). Defaults to previous month.
        year:               Target year. Defaults to the year of the previous month.
        cfg_id__linkedin:   Config key for LinkedIn (default 'LINKEDIN').
        cfg_id__gmail:      Config key for Gmail send (default 'GOOGLE_GMAIL_SEND').
        cfg_id__anthropic:  Config key for Anthropic (default 'ANTHROPIC').
        recipient_email:    Email address for the notification (default: LinkedIn account email).
        skip_draft:         If True, skips posting the LinkedIn draft (default False).
        skip_email:         If True, skips the Gmail notification (default False).

    Returns:
        Summary string describing what was done.
    """
    # ── Resolve target month ─────────────────────────────────────────────────
    today = date.today()
    default_month = today.month - 1 if today.month > 1 else 12
    default_year = today.year if today.month > 1 else today.year - 1

    month: int = int(kwargs.get("month", default_month))
    year: int = int(kwargs.get("year", default_year))
    cfg_id__linkedin: str = kwargs.get("cfg_id__linkedin", "LINKEDIN")
    cfg_id__gmail: str = kwargs.get("cfg_id__gmail", "GOOGLE_GMAIL_SEND")
    cfg_id__anthropic: str = kwargs.get("cfg_id__anthropic", "ANTHROPIC")
    recipient_email: str = kwargs.get("recipient_email", "brian.bartilet@gmail.com")
    skip_draft: bool = bool(kwargs.get("skip_draft", False))
    skip_email: bool = bool(kwargs.get("skip_email", False))

    month_name = date(year, month, 1).strftime("%B")
    _log.info("generate_monthly_linkedin_post: target %s %d", month_name, year)

    # ── Step 1: Collect git history ──────────────────────────────────────────
    commits = _get_git_commits(year, month)
    _log.info("generate_monthly_linkedin_post: %d commits collected", len(commits))

    # ── Step 2: Load previous post for style context ─────────────────────────
    previous_post = _load_previous_post_from_logs(year, month)
    if not previous_post:
        previous_post = _get_linkedin_last_post(cfg_id__linkedin)

    # ── Step 3: Generate post with Claude ────────────────────────────────────
    post_text = _generate_post_with_claude(
        year=year,
        month=month,
        commits=commits,
        previous_post=previous_post,
        cfg_id__anthropic=cfg_id__anthropic,
    )
    _log.info("generate_monthly_linkedin_post: post generated (%d chars)", len(post_text))

    # ── Step 4: Save to logs/linkedin/ ───────────────────────────────────────
    output_path = _save_post_to_file(year, month, post_text)

    # ── Step 5: Create LinkedIn draft ────────────────────────────────────────
    draft_result = {}
    if not skip_draft:
        try:
            cfg_li = CONFIG_MANAGER.get(cfg_id__linkedin)
            posts_service = ApiServiceLinkedInPosts(cfg_li)
            draft_result = posts_service.create_draft(text=post_text)
            _log.info("generate_monthly_linkedin_post: LinkedIn draft created — %s", draft_result)
        except Exception as exc:
            _log.warning("generate_monthly_linkedin_post: LinkedIn draft failed — %s", exc)
            draft_result = {"error": str(exc)}

    # ── Step 6: Gmail notification ────────────────────────────────────────────
    if not skip_email:
        _send_gmail_notification(
            cfg_id__gmail=cfg_id__gmail,
            year=year,
            month=month,
            post_text=post_text,
            output_path=output_path,
            draft_result=draft_result,
            recipient_email=recipient_email,
        )

    summary = (
        f"Monthly LinkedIn post for {month_name} {year} — "
        f"{len(commits)} commits analysed, "
        f"saved to {output_path.name}, "
        f"draft={'created' if not skip_draft and 'error' not in draft_result else 'skipped/failed'}, "
        f"email={'sent' if not skip_email else 'skipped'}"
    )
    _log.info(summary)
    return summary
