"""
workflows/knowledge/tasks/ingest_jira.py

Index Jira issues — summary + description + comments — into the local vector
store. The "kanban agent with project memory" capability from the thesis becomes
real once this runs: every closed ticket is now retrievable by semantic
similarity.

Pipeline (per project key):
  1. JQL search: `project = <key> ORDER BY updated DESC`
  2. For each issue: get_issue_comments → flatten ADF descriptions/comments
  3. Compose chunk text: title + description + each comment, separated
  4. Embed in batches with Gemini (RETRIEVAL_DOCUMENT)
  5. Upsert keyed by f"{issue_key}:{chunk_idx}", source='jira'

Idempotent: re-running replaces existing chunks for any seen issue. For a
clean rebuild, pass rebuild=True.

Default schedule: nightly 02:45 (staggered after Notion at 02:30 to avoid
fighting for the Gemini embed quota).
"""

from __future__ import annotations

from typing import Any, Iterable

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.apps_config import CONFIG_MANAGER
from apps.gemini.references.web.api.embed import ApiServiceGeminiEmbed
from apps.jira.references.web.api.issues import ApiServiceJiraIssues
from apps.sqlite_vec import store

from workflows.knowledge.chunking import chunk_text, flatten_adf

_log = create_logger("knowledge.ingest_jira")

_BATCH_SIZE = 50


def _coerce_text(value: Any) -> str:
    """Issue fields may be plain strings (v2 API) or ADF dicts (v3) — handle both."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return flatten_adf(value).strip()


def _issue_url(base_url: str, issue_key: str) -> str:
    """Render a browse URL like https://<domain>.atlassian.net/browse/HARQIS-42."""
    base = base_url.rstrip("/")
    if base.endswith("/rest/api/2") or base.endswith("/rest/api/3"):
        base = base.rsplit("/rest/", 1)[0]
    return f"{base}/browse/{issue_key}"


def _compose_issue_text(issue: dict[str, Any], comments: Iterable[dict[str, Any]]) -> str:
    fields = issue.get("fields", {}) or {}
    summary = fields.get("summary") or ""
    description = _coerce_text(fields.get("description"))
    status = (fields.get("status") or {}).get("name", "")
    issue_type = (fields.get("issuetype") or {}).get("name", "")
    parts: list[str] = [
        f"{issue.get('key', '')}: {summary}",
        f"Type: {issue_type}    Status: {status}",
    ]
    if description:
        parts.append(description)
    for c in comments:
        body = _coerce_text(c.get("body"))
        if not body:
            continue
        author = ((c.get("author") or {}).get("displayName")) or "anon"
        parts.append(f"Comment by {author}:\n{body}")
    return "\n\n".join(p for p in parts if p)


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


@SPROUT.task()
@log_result()
def ingest_jira_issues(**kwargs):
    """Sync one or more Jira projects into the local vector store.

    Args:
        cfg_id__jira:    Config key for Jira (default 'JIRA').
        project_keys:    List of project keys to ingest, e.g. ['HARQIS', 'OPS'].
                         If empty, the JQL falls back to "ORDER BY updated DESC"
                         (returns issues across all visible projects).
        max_issues:      Cap issues per run (default 500).
        max_comments:    Comments fetched per issue (default 30 — first N).
        jql_extra:       Extra JQL appended with AND, e.g. 'updated >= -7d'.
        rebuild:         If True, drop the 'jira' source first (default False).

    Returns:
        Summary dict — issues_seen, chunks_written.
    """
    cfg_id__jira: str = kwargs.get("cfg_id__jira", "JIRA")
    project_keys: list[str] = list(kwargs.get("project_keys", []) or [])
    max_issues: int = int(kwargs.get("max_issues", 500))
    max_comments: int = int(kwargs.get("max_comments", 30))
    jql_extra: str = kwargs.get("jql_extra", "") or ""
    rebuild: bool = bool(kwargs.get("rebuild", False))

    if rebuild:
        deleted = store.delete_by_source("jira")
        _log.info("ingest_jira_issues: rebuild=True dropped %d existing chunks", deleted)

    jira_cfg = CONFIG_MANAGER.get(cfg_id__jira)
    issues_svc = ApiServiceJiraIssues(jira_cfg)

    from apps.gemini.config import CONFIG as GEMINI_CONFIG
    embedder = ApiServiceGeminiEmbed(GEMINI_CONFIG)

    base_url = jira_cfg.parameters.get("base_url", "") if hasattr(jira_cfg, "parameters") else ""

    if project_keys:
        jql = f"project in ({','.join(project_keys)})"
    else:
        jql = ""
    if jql_extra:
        jql = f"{jql} AND {jql_extra}" if jql else jql_extra
    jql = (jql + " ORDER BY updated DESC").strip()

    issues_seen = 0
    chunks_written = 0
    start_at = 0

    while issues_seen < max_issues:
        page_size = min(50, max_issues - issues_seen)
        resp = issues_svc.search_issues(jql=jql, max_results=page_size, start_at=start_at)
        if not isinstance(resp, dict):
            _log.warning("ingest_jira_issues: unexpected search response: %r", resp)
            break
        batch = resp.get("issues", []) or []
        if not batch:
            break

        for issue in batch:
            issue_key = issue.get("key")
            if not issue_key:
                continue
            try:
                comments_resp = issues_svc.get_issue_comments(issue_key, max_results=max_comments)
                comments = (comments_resp.get("comments", []) or []) if isinstance(comments_resp, dict) else []
            except Exception as exc:
                _log.warning("ingest_jira_issues: %s comments fetch failed — %s", issue_key, exc)
                comments = []

            text = _compose_issue_text(issue, comments)
            chunks = chunk_text(text)
            if not chunks:
                issues_seen += 1
                continue

            url = _issue_url(base_url, issue_key)
            fields = issue.get("fields", {}) or {}
            meta_base = {
                "issue_key": issue_key,
                "project": (fields.get("project") or {}).get("key", ""),
                "status": (fields.get("status") or {}).get("name", ""),
                "issue_type": (fields.get("issuetype") or {}).get("name", ""),
                "summary": fields.get("summary", ""),
            }

            for batch_start in range(0, len(chunks), _BATCH_SIZE):
                slice_ = chunks[batch_start : batch_start + _BATCH_SIZE]
                vectors = _embed_batch(embedder, slice_)
                for offset, (chunk, vec) in enumerate(zip(slice_, vectors)):
                    idx = batch_start + offset
                    store.upsert(
                        chunk_id=f"{issue_key}:{idx}",
                        text=chunk,
                        embedding=vec,
                        source="jira",
                        ref=url,
                        meta={**meta_base, "chunk_idx": idx},
                    )
                    chunks_written += 1

            issues_seen += 1
            _log.info(
                "ingest_jira_issues: %s '%s' — %d chunks",
                issue_key, fields.get("summary", "")[:60], len(chunks),
            )

        start_at += page_size
        if start_at >= int(resp.get("total", 0) or 0):
            break

    summary = {
        "issues_seen": issues_seen,
        "chunks_written": chunks_written,
        "source": "jira",
        "rebuild": rebuild,
        "jql": jql,
    }
    _log.info("ingest_jira_issues: done — %s", summary)
    return summary
