"""
workflows/hfl/tasks/ingest_git.py

Daily git-activity → HFL corpus. Gathers the operator's own GitHub commits
across recently-updated repos, distils them into ONE Homework-for-Life
entry, and appends it to the corpus so the work flows into
summarize_hfl_week and the memory_recall MCP automatically.

GitHub-remote only (per the approved spec). The existing
apps.github.ApiServiceGitHubRepos has no since/until/author params, so
windowing + identity filtering happen client-side, bounded by:
  - max_repos        : how many recently-updated repos to walk
  - commits_per_repo : page size per repo (default branch only)
  - max_commits      : hard cap on commits fed to the model

The collectors (collect_github_activity / distill_git_activity) are plain
functions so the MCP tool (workflows/hfl/mcp.py :: git_activity) can reuse
them for a live, no-write view.

Cost: Haiku only — never raise the Anthropic DEFAULT_MODEL. Skipped
entirely (no LLM, no entry) when there are no commits in the window.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Any, Optional

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
from apps.github.config import CONFIG as GITHUB_CONFIG
from apps.github.references.web.api.repos import ApiServiceGitHubRepos

from workflows.hfl.prompts import load_prompt
from workflows.hfl.tasks.capture import (
    _build_entry,
    append_entry,
    resolve_corpus_dir,
)

_log = create_logger("hfl.ingest_git")

_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"


def _iso_to_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, AttributeError):
        return None


def _identity_set(me: dict, extra: Optional[list[str]]) -> set[str]:
    vals = [me.get("login"), me.get("name"), me.get("email"), *(extra or [])]
    return {str(v).strip().lower() for v in vals if v and str(v).strip()}


def _repo_short(full_name: str) -> str:
    name = full_name.split("/")[-1] if "/" in full_name else full_name
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _parse_model_json(text: str) -> Optional[dict]:
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.strip("`")
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
    s = s.strip().strip("`").strip()
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except (ValueError, TypeError):
        return None


def collect_github_activity(
    *,
    since: date,
    until: date,
    max_repos: int = 30,
    commits_per_repo: int = 50,
    max_commits: int = 200,
    author_match: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Walk recently-updated repos, return the user's commits in [since, until].

    Returns:
        {"identity": [...], "repos": [{"full_name", "commits":
         [{"sha","subject","date"}]}], "commit_count", "repo_count"}
    """
    svc = ApiServiceGitHubRepos(GITHUB_CONFIG)
    try:
        me = svc.get_authenticated_user() or {}
    except Exception as exc:  # noqa: BLE001 - identity is best-effort
        _log.warning("ingest_git: get_authenticated_user failed (%s)", exc)
        me = {}
    identity = _identity_set(me, author_match)

    repos = svc.list_repos(visibility="all", per_page=max_repos)
    groups: list[dict] = []
    total = 0
    for r in repos:
        if total >= max_commits:
            break
        ru = _iso_to_dt(getattr(r, "updated_at", None))
        if ru and ru.date() < since:
            break  # list is updated-desc — nothing older can qualify
        full = getattr(r, "full_name", None) or ""
        if "/" not in full:
            continue
        owner, name = full.split("/", 1)
        try:
            commits = svc.list_commits(
                owner, name,
                branch=getattr(r, "default_branch", None),
                per_page=commits_per_repo,
            )
        except Exception as exc:  # noqa: BLE001 - skip a bad repo, keep going
            _log.info("ingest_git: list_commits failed for %s (%s)", full, exc)
            continue
        keep: list[dict] = []
        for c in commits:
            cd = _iso_to_dt(getattr(c, "date", None))
            if not cd or not (since <= cd.date() <= until):
                continue
            who = (getattr(c, "author_email", "") or "").lower()
            nm = (getattr(c, "author_name", "") or "").lower()
            if identity and who not in identity and nm not in identity:
                continue
            subject = ((getattr(c, "message", "") or "").splitlines() or [""])[0].strip()
            keep.append({
                "sha": (getattr(c, "sha", "") or "")[:10],
                "subject": subject[:140],
                "date": cd.strftime("%Y-%m-%d %H:%M"),
            })
            total += 1
            if total >= max_commits:
                break
        if keep:
            groups.append({"full_name": full, "commits": keep})

    return {
        "identity": sorted(identity),
        "repos": groups,
        "commit_count": total,
        "repo_count": len(groups),
    }


def _activity_body(activity: dict) -> str:
    lines: list[str] = []
    for g in activity["repos"]:
        lines.append(f"### {g['full_name']} ({len(g['commits'])} commits)")
        for c in g["commits"]:
            lines.append(f"- {c['date']}  {c['sha']}  {c['subject']}")
    return "\n".join(lines)


def distill_git_activity(
    activity: dict,
    *,
    synthesize: bool = True,
    model: str = _DEFAULT_HAIKU,
    cfg_id: str = "ANTHROPIC",
    max_tokens: int = 900,
) -> dict[str, Any]:
    """Turn collected activity into HFL entry fields (Haiku, raw fallback)."""
    repo_count = activity["repo_count"]
    commit_count = activity["commit_count"]

    def _fallback() -> dict:
        bullets = []
        for g in activity["repos"]:
            subs = "; ".join(c["subject"] for c in g["commits"][:8])
            bullets.append(f"- {g['full_name']}: {len(g['commits'])} commits — {subs}")
        return {
            "skip": False,
            "moment": f"{commit_count} commits across {repo_count} repo(s)",
            "what_happened": "\n".join(bullets),
            "why_it_stayed": "",
            "possible_use": "standup",
            "tags": [_repo_short(g["full_name"]) for g in activity["repos"]][:6],
            "synthesized": False,
        }

    if not synthesize:
        return _fallback()

    user_msg = (
        f"Commits grouped by repo ({commit_count} total across "
        f"{repo_count} repos):\n\n{_activity_body(activity)}"
    )
    try:
        client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
        if not getattr(client, "base_client", None):
            _log.warning("ingest_git: Anthropic not initialized — raw fallback")
            return _fallback()
        resp = client.send_message(
            prompt=user_msg,
            system=load_prompt("ingest_git").strip(),
            model=model,
            max_tokens=max_tokens,
        )
        text = resp.content[0].text if resp and resp.content else ""
        parsed = _parse_model_json(text)
        if not parsed:
            return _fallback()
        parsed.setdefault("skip", False)
        for key in ("moment", "what_happened", "why_it_stayed", "possible_use"):
            parsed[key] = str(parsed.get(key, "")).strip()
        parsed["tags"] = [str(t).strip().lstrip("#") for t in (parsed.get("tags") or [])]
        parsed["synthesized"] = True
        return parsed
    except Exception as exc:  # noqa: BLE001 - never break the beat on API error
        _log.warning("ingest_git: synthesis failed (%s) — raw fallback", exc)
        return _fallback()


@SPROUT.task()
@log_result()
def ingest_git_activity(
    *,
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = _DEFAULT_HAIKU,
    window_days: int = 1,
    max_repos: int = 30,
    commits_per_repo: int = 50,
    max_commits: int = 200,
    author_match: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Append one HFL corpus entry summarizing the day's GitHub commits.

    No commits in the window → no entry, no LLM call.
    """
    until = datetime.now().date()
    since = until - timedelta(days=window_days)

    try:
        activity = collect_github_activity(
            since=since, until=until, max_repos=max_repos,
            commits_per_repo=commits_per_repo, max_commits=max_commits,
            author_match=author_match,
        )
    except Exception as exc:  # noqa: BLE001 - GitHub down must not break beat
        _log.error("ingest_git: GitHub unavailable (%s)", exc)
        return {"skipped": "github unavailable", "entries_written": 0,
                "error": str(exc)[:200]}

    if activity["commit_count"] == 0:
        _log.info("ingest_git: no commits in last %d day(s)", window_days)
        return {"skipped": "no commits", "entries_written": 0, "repos": 0}

    d = distill_git_activity(
        activity, synthesize=True, model=model,
        cfg_id=cfg_id__anthropic, max_tokens=900,
    )
    if d.get("skip"):
        _log.info("ingest_git: distilled as skip — %d commits not story-worthy",
                  activity["commit_count"])
        return {"skipped": "distilled-skip", "entries_written": 0,
                "commit_count": activity["commit_count"]}

    tags = ["git", "commits"] + [
        _repo_short(g["full_name"]) for g in activity["repos"]
    ][:6]

    when = datetime.now()
    corpus_dir = resolve_corpus_dir()
    corpus_dir.mkdir(parents=True, exist_ok=True)
    day_file = corpus_dir / f"{when.strftime('%Y-%m-%d')}.md"
    entry = _build_entry(
        when=when,
        moment=d["moment"],
        what_happened=d["what_happened"],
        why_it_stayed=d["why_it_stayed"],
        possible_use=d["possible_use"] or "standup",
        tags=tags,
    )
    append_entry(
        day_file, entry,
        source="git", synthesized=d.get("synthesized", False),
    )

    _log.info("ingest_git: entry written (%d commits, %d repos) → %s",
              activity["commit_count"], activity["repo_count"], day_file)
    return {
        "entries_written": 1,
        "repos": activity["repo_count"],
        "commits": activity["commit_count"],
        "synthesized": d.get("synthesized", False),
        "model": model if d.get("synthesized") else None,
        "path": str(day_file),
    }
