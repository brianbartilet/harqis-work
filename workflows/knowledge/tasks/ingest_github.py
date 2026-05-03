"""
workflows/knowledge/tasks/ingest_github.py

Index GitHub PRs and issues for one or more repos. Captures the institutional
"why did we do it this way?" memory that lives in PR descriptions and code-
review threads.

For each PR:
  - Title + body
  - First N issue-thread comments (the "discussion" tab)
  - First N PR review comments (line-level review notes)

For each issue (excluding PRs):
  - Title + body
  - First N comments

Source label: 'github'. Chunk ids: f"{owner}/{repo}#PR{n}:{i}" or
f"{owner}/{repo}#I{n}:{i}" so PR and issue numbers don't collide.

Default schedule: nightly 03:00 (staggered after Notion 02:30 and Jira 02:45).
"""

from __future__ import annotations

from typing import Any

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.gemini.references.web.api.embed import ApiServiceGeminiEmbed
from apps.github.config import CONFIG as GITHUB_CONFIG
from apps.github.references.web.api.repos import ApiServiceGitHubRepos
from apps.sqlite_vec import store

from workflows.knowledge.chunking import chunk_text

_log = create_logger("knowledge.ingest_github")

_BATCH_SIZE = 50
_DEFAULT_COMMENTS = 20  # "first 20 review comments" from the thesis


def _embed_batch(embedder: ApiServiceGeminiEmbed, texts: list[str]) -> list[list[float]]:
    resp = embedder.batch_embed_contents(texts=texts, task_type="RETRIEVAL_DOCUMENT")
    data = resp.__dict__ if hasattr(resp, "__dict__") else resp
    embeddings = data.get("embeddings", []) if isinstance(data, dict) else []
    out: list[list[float]] = []
    for e in embeddings:
        values = e.get("values") if isinstance(e, dict) else getattr(e, "values", None)
        if values is None:
            raise RuntimeError(f"Gemini batch returned an item with no values: {e!r}")
        out.append(list(values))
    if len(out) != len(texts):
        raise RuntimeError(f"Gemini batch returned {len(out)} embeddings for {len(texts)} texts")
    return out


def _comments_for_pr(svc: ApiServiceGitHubRepos, owner: str, repo: str,
                     pr_number: int, max_comments: int) -> list[dict[str, Any]]:
    """Fetch issue-thread comments + review comments for a PR via the raw _get."""
    out: list[dict[str, Any]] = []
    try:
        issue_comments = svc._get(
            f"/repos/{owner}/{repo}/issues/{pr_number}/comments",
            params={"per_page": max_comments},
        )
        if isinstance(issue_comments, list):
            out.extend(issue_comments)
    except Exception as exc:
        _log.warning("github comments(issue) %s/%s#%d failed — %s", owner, repo, pr_number, exc)

    try:
        review_comments = svc._get(
            f"/repos/{owner}/{repo}/pulls/{pr_number}/comments",
            params={"per_page": max_comments},
        )
        if isinstance(review_comments, list):
            out.extend(review_comments)
    except Exception as exc:
        _log.warning("github comments(review) %s/%s#%d failed — %s", owner, repo, pr_number, exc)

    return out[:max_comments]


def _comments_for_issue(svc: ApiServiceGitHubRepos, owner: str, repo: str,
                        issue_number: int, max_comments: int) -> list[dict[str, Any]]:
    try:
        data = svc._get(
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            params={"per_page": max_comments},
        )
        return data if isinstance(data, list) else []
    except Exception as exc:
        _log.warning("github comments(issue) %s/%s#%d failed — %s", owner, repo, issue_number, exc)
        return []


def _compose_text(title: str, body: str | None, author: str | None,
                  comments: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    head = title or ""
    if author:
        head += f"  (by {author})"
    parts.append(head)
    if body:
        parts.append(body)
    for c in comments:
        cb = c.get("body") or ""
        if not cb:
            continue
        ca = (c.get("user") or {}).get("login") or "anon"
        parts.append(f"Comment by {ca}:\n{cb}")
    return "\n\n".join(p for p in parts if p)


def _ingest_doc(
    *,
    chunk_id_prefix: str,
    text: str,
    url: str,
    meta_base: dict[str, Any],
    embedder: ApiServiceGeminiEmbed,
) -> int:
    chunks = chunk_text(text)
    if not chunks:
        return 0
    written = 0
    for batch_start in range(0, len(chunks), _BATCH_SIZE):
        slice_ = chunks[batch_start : batch_start + _BATCH_SIZE]
        vectors = _embed_batch(embedder, slice_)
        for offset, (chunk, vec) in enumerate(zip(slice_, vectors)):
            idx = batch_start + offset
            store.upsert(
                chunk_id=f"{chunk_id_prefix}:{idx}",
                text=chunk,
                embedding=vec,
                source="github",
                ref=url,
                meta={**meta_base, "chunk_idx": idx},
            )
            written += 1
    return written


@SPROUT.task()
@log_result()
def ingest_github_repos(**kwargs):
    """Sync PRs and issues from one or more repos into the local vector store.

    Args:
        repos:           List of "owner/repo" strings, e.g. ['acme/web', 'acme/api'].
        states:          Issue/PR states to fetch — 'open', 'closed', or 'all' (default).
        per_repo_limit:  Cap PRs+issues per repo per run (default 100).
        max_comments:    First N comments per item (default 20 — matches thesis).
        include_issues:  Index plain issues (default True).
        include_prs:     Index pull requests (default True).
        rebuild:         If True, drop the 'github' source first (default False).

    Returns:
        Summary dict — repos, prs_seen, issues_seen, chunks_written.
    """
    repos: list[str] = list(kwargs.get("repos", []) or [])
    states: str = kwargs.get("states", "all")
    per_repo_limit: int = int(kwargs.get("per_repo_limit", 100))
    max_comments: int = int(kwargs.get("max_comments", _DEFAULT_COMMENTS))
    include_issues: bool = bool(kwargs.get("include_issues", True))
    include_prs: bool = bool(kwargs.get("include_prs", True))
    rebuild: bool = bool(kwargs.get("rebuild", False))

    if not repos:
        return {"error": "no repos given", "repos": [], "prs_seen": 0, "issues_seen": 0, "chunks_written": 0}

    if rebuild:
        deleted = store.delete_by_source("github")
        _log.info("ingest_github_repos: rebuild=True dropped %d existing chunks", deleted)

    svc = ApiServiceGitHubRepos(GITHUB_CONFIG)

    from apps.gemini.config import CONFIG as GEMINI_CONFIG
    embedder = ApiServiceGeminiEmbed(GEMINI_CONFIG)

    prs_seen = 0
    issues_seen = 0
    chunks_written = 0

    for spec in repos:
        if "/" not in spec:
            _log.warning("ingest_github_repos: skipping malformed repo spec %r", spec)
            continue
        owner, repo = spec.split("/", 1)

        if include_prs:
            try:
                prs = svc.list_pull_requests(owner=owner, repo=repo, state=states, per_page=min(100, per_repo_limit))
            except Exception as exc:
                _log.warning("ingest_github_repos: PRs %s failed — %s", spec, exc)
                prs = []
            for pr in prs[:per_repo_limit]:
                comments = _comments_for_pr(svc, owner, repo, pr.number, max_comments)
                text = _compose_text(pr.title, pr.body, pr.user_login, comments)
                meta = {
                    "owner": owner, "repo": repo, "kind": "pr",
                    "number": pr.number, "state": pr.state,
                    "title": pr.title, "merged": pr.merged,
                }
                chunks_written += _ingest_doc(
                    chunk_id_prefix=f"{owner}/{repo}#PR{pr.number}",
                    text=text, url=pr.html_url, meta_base=meta, embedder=embedder,
                )
                prs_seen += 1
                _log.info("ingest_github_repos: %s#PR%d — %d comments", spec, pr.number, len(comments))

        if include_issues:
            try:
                issues = svc.list_issues(owner=owner, repo=repo, state=states, per_page=min(100, per_repo_limit))
            except Exception as exc:
                _log.warning("ingest_github_repos: issues %s failed — %s", spec, exc)
                issues = []
            for issue in issues[:per_repo_limit]:
                comments = _comments_for_issue(svc, owner, repo, issue.number, max_comments)
                text = _compose_text(issue.title, issue.body, issue.user_login, comments)
                meta = {
                    "owner": owner, "repo": repo, "kind": "issue",
                    "number": issue.number, "state": issue.state,
                    "title": issue.title, "labels": issue.labels,
                }
                chunks_written += _ingest_doc(
                    chunk_id_prefix=f"{owner}/{repo}#I{issue.number}",
                    text=text, url=issue.html_url, meta_base=meta, embedder=embedder,
                )
                issues_seen += 1
                _log.info("ingest_github_repos: %s#I%d — %d comments", spec, issue.number, len(comments))

    summary = {
        "repos": repos,
        "prs_seen": prs_seen,
        "issues_seen": issues_seen,
        "chunks_written": chunks_written,
        "source": "github",
        "rebuild": rebuild,
    }
    _log.info("ingest_github_repos: done — %s", summary)
    return summary
