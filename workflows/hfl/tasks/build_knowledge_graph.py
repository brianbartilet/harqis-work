"""
workflows/hfl/tasks/build_knowledge_graph.py

Phase 1 of the HFL knowledge-graph rollout (see workflows/hfl/KNOWLEDGE_GRAPH.md).

Builds a queryable knowledge graph over the HFL Markdown corpus using
Graphify (https://graphify.net). The corpus stays the source of truth —
this task produces a parallel structural projection (nodes + edges) that
turns the manifesto's "queryable by prompt" promise into actual graph
traversal instead of substring scanning.

Hard contract — never break the beat:
  - graphify CLI missing → log WARNING and no-op (skipped="cli_missing").
  - empty corpus           → no-op (skipped="empty_corpus").
  - graphify exit non-zero → log WARNING, return {ok: False, reason}.
  - ES projection failure  → swallowed; graph files on disk are the win.

Cost guard (per memory: anthropic_model_override):
  graphify uses its OWN environment for the semantic-extraction LLM.
  We export ANTHROPIC_API_KEY + ANTHROPIC_MODEL=claude-haiku-4-5-20251001
  into the subprocess so graphify pins Haiku just like every other HFL
  task. Never raise BaseApiServiceAnthropic.DEFAULT_MODEL here.

Outputs (under <corpus_dir>/_graph/<YYYY-Www>/):
  - graph.html         (interactive viewer — open in any browser)
  - GRAPH_REPORT.md    (one-page audit: top concepts + connections)
  - graph.json         (full graph; queried by future retrieve_hfl_via_graph)

The ES projection writes one summary doc per build to `harqis-hfl-graph`
(env HFL_GRAPH_ES_INDEX). The doc id is deterministic on (corpus_dir, iso_week)
so re-runs upsert rather than duplicate.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.antropic.config import get_config as get_anthropic_config

from workflows.hfl.tasks.capture import resolve_corpus_dir

_log = create_logger("hfl.build_knowledge_graph")

_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"
_DEFAULT_INDEX = "harqis-hfl-graph"
_CLI_NAME = "graphify"
# Cost guard — bound the LLM hit even when the corpus grows. Graphify accepts
# --max-files; we surface it as a kwarg so the beat schedule can tighten it.
_DEFAULT_MAX_FILES = 500
_DEFAULT_TIMEOUT_SEC = 60 * 30  # 30 min hard cap; daily Beat fires aren't this PR


def _graphify_path() -> Optional[str]:
    """Return the absolute path to the graphify CLI, or None.

    pip install graphifyy (note the double-y) puts the binary on PATH as
    `graphify`. We resolve via shutil.which so the task is venv-safe.
    """
    return shutil.which(_CLI_NAME)


def _iso_week(when: Optional[datetime] = None) -> str:
    when = when or datetime.now()
    iso = when.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _outdir(corpus_dir: Path, when: Optional[datetime] = None) -> Path:
    return corpus_dir / "_graph" / _iso_week(when)


def _doc_id(corpus_dir: Path, iso_week: str) -> str:
    # Stable across runs: corpus path + ISO week. Re-runs upsert.
    import hashlib
    h = hashlib.sha1(str(corpus_dir).encode("utf-8")).hexdigest()[:12]
    return f"hfl-graph-{iso_week}-{h}"


def _build_env(
    *,
    cfg_id__anthropic: str,
    model: str,
) -> dict[str, str]:
    """Pin Haiku for the subprocess — graphify reads its own env."""
    env = os.environ.copy()
    try:
        cfg = get_anthropic_config(cfg_id__anthropic)
        api_key = (cfg.app_data.get("api_key") or "").strip()
        if api_key:
            env["ANTHROPIC_API_KEY"] = api_key
    except Exception as exc:  # noqa: BLE001
        _log.warning("anthropic config %s unreadable (%s) — using process env",
                     cfg_id__anthropic, exc)
    env["ANTHROPIC_MODEL"] = model
    # Graphify documents these flags via the CLI; we mirror them as env so a
    # future graphify release that drops a flag still gets the model pinned.
    env["GRAPHIFY_MODEL"] = model
    return env


def _index_summary(
    *,
    iso_week: str,
    corpus_dir: Path,
    out_dir: Path,
    stats: dict[str, Any],
    elapsed_sec: float,
) -> None:
    """Best-effort ES projection of the build summary. Never raises."""
    index = os.environ.get("HFL_GRAPH_ES_INDEX", "").strip() or _DEFAULT_INDEX
    doc = {
        "iso_week": iso_week,
        "corpus_dir": str(corpus_dir),
        "out_dir": str(out_dir),
        "graph_json": str(out_dir / "graph.json"),
        "graph_html": str(out_dir / "graph.html"),
        "report_md": str(out_dir / "GRAPH_REPORT.md"),
        "elapsed_sec": round(elapsed_sec, 2),
        "stats": stats,
        "built_at": datetime.now().isoformat(),
    }
    try:
        from core.apps.es_logging.app.elasticsearch import post
        post(doc, index, location_key=_doc_id(corpus_dir, iso_week),
             use_interval_map=False)
        _log.info("hfl.build_knowledge_graph: indexed summary %s", index)
    except Exception as exc:  # noqa: BLE001 — ES is bonus
        _log.warning("hfl.build_knowledge_graph: ES projection skipped (%s)",
                     exc)


def _parse_stats(report_md: Path) -> dict[str, Any]:
    """Best-effort parse of GRAPH_REPORT.md for HUD-displayable counts.

    Graphify's report format evolves; we only pull lines that look like
    `Nodes: 123` / `Edges: 456` / `Clusters: 7` and ignore the rest.
    Empty dict on any failure — never raises.
    """
    if not report_md.exists():
        return {}
    out: dict[str, int] = {}
    try:
        for line in report_md.read_text(encoding="utf-8").splitlines():
            stripped = line.strip().lstrip("-* ").strip()
            for key in ("Nodes", "Edges", "Clusters", "Files"):
                prefix = f"{key}:"
                if stripped.startswith(prefix):
                    val = stripped[len(prefix):].strip().split()[0].replace(",", "")
                    try:
                        out[key.lower()] = int(val)
                    except ValueError:
                        pass
    except Exception:  # noqa: BLE001
        return out
    return out


@SPROUT.task()
@log_result()
def build_hfl_knowledge_graph(
    *,
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = _DEFAULT_HAIKU,
    max_files: int = _DEFAULT_MAX_FILES,
    timeout_sec: int = _DEFAULT_TIMEOUT_SEC,
    corpus_dir_override: Optional[str] = None,
) -> dict[str, Any]:
    """Run graphify over the HFL corpus and surface the result.

    Adhoc by default (no scheduled beat in Phase 1 — see KNOWLEDGE_GRAPH.md).
    Returns a dict consumed by @log_result for the ES task ledger.
    """
    cli = _graphify_path()
    if not cli:
        _log.warning(
            "hfl.build_knowledge_graph: graphify CLI not on PATH — install with "
            "`pip install graphifyy` (note the double y); skipping."
        )
        return {"ok": False, "skipped": "cli_missing"}

    corpus_dir = (
        Path(corpus_dir_override).expanduser().resolve()
        if corpus_dir_override else resolve_corpus_dir()
    )
    if not corpus_dir.exists() or not any(corpus_dir.glob("*.md")):
        _log.info("hfl.build_knowledge_graph: empty corpus at %s — skipping",
                  corpus_dir)
        return {"ok": False, "skipped": "empty_corpus",
                "corpus_dir": str(corpus_dir)}

    iso_week = _iso_week()
    out_dir = _outdir(corpus_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    env = _build_env(cfg_id__anthropic=cfg_id__anthropic, model=model)

    # graphify CLI: --input <dir> --output <dir> --max-files <n>
    # Pinned model goes through ANTHROPIC_MODEL / GRAPHIFY_MODEL env above.
    argv = [
        cli,
        "--input", str(corpus_dir),
        "--output", str(out_dir),
        "--max-files", str(max_files),
    ]

    started = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            env=env,
            timeout=timeout_sec,
            capture_output=True,
            text=True,
            check=False,
        )
    except subprocess.TimeoutExpired:
        _log.warning("hfl.build_knowledge_graph: timed out after %ds", timeout_sec)
        return {"ok": False, "reason": "timeout",
                "timeout_sec": timeout_sec, "out_dir": str(out_dir)}
    except Exception as exc:  # noqa: BLE001
        _log.warning("hfl.build_knowledge_graph: subprocess error (%s)", exc)
        return {"ok": False, "reason": f"subprocess_error:{type(exc).__name__}"}

    elapsed = time.monotonic() - started

    if proc.returncode != 0:
        _log.warning(
            "hfl.build_knowledge_graph: graphify exit=%d stderr=%s",
            proc.returncode,
            (proc.stderr or "").strip()[:500],
        )
        return {"ok": False, "reason": "non_zero_exit",
                "returncode": proc.returncode,
                "stderr_tail": (proc.stderr or "").strip()[-500:]}

    stats = _parse_stats(out_dir / "GRAPH_REPORT.md")
    _index_summary(
        iso_week=iso_week, corpus_dir=corpus_dir, out_dir=out_dir,
        stats=stats, elapsed_sec=elapsed,
    )

    _log.info(
        "hfl.build_knowledge_graph: ok iso_week=%s out=%s stats=%s",
        iso_week, out_dir, stats,
    )
    return {
        "ok": True,
        "iso_week": iso_week,
        "corpus_dir": str(corpus_dir),
        "out_dir": str(out_dir),
        "graph_html": str(out_dir / "graph.html"),
        "report_md": str(out_dir / "GRAPH_REPORT.md"),
        "graph_json": str(out_dir / "graph.json"),
        "stats": stats,
        "elapsed_sec": round(elapsed, 2),
    }
