"""Opt-in HFL knowledge-graph build with deterministic and semantic layers.

The deterministic projection is derived locally from ``HflEntry`` fields.
Graphify is optional semantic enrichment and receives only a bounded staging
copy when ``HARQIS_HFL_GRAPH_ENABLE=1``. Generated output lives outside the
corpus and is never treated as source input.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.apps.es_logging.app.elasticsearch import log_result
from core.apps.sprout.app.celery import SPROUT
from core.utilities.logging.custom_logger import create_logger

from apps.antropic.config import get_config as get_anthropic_config
from workflows.hfl.knowledge_graph import (
    build_deterministic_graph,
    load_graph,
    merge_graphs,
    write_graph,
)
from workflows.hfl.tasks.capture import resolve_corpus_dir

_log = create_logger("hfl.build_knowledge_graph")

_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"
_DEFAULT_INDEX = "harqis-hfl-graph"
_DEFAULT_MAX_FILES = 500
_DEFAULT_TIMEOUT_SEC = 60 * 30
_REQUIRED_ARTIFACTS = ("graph.json", "GRAPH_REPORT.md", "graph.html")
_SAFE_ENV_KEYS = (
    "PATH",
    "HOME",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
)


def _enabled() -> bool:
    return os.environ.get("HARQIS_HFL_GRAPH_ENABLE", "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _graphify_path() -> Optional[str]:
    return shutil.which("graphify")


def _iso_week(when: Optional[datetime] = None) -> str:
    iso = (when or datetime.now()).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _default_output_root() -> Path:
    configured = os.environ.get("HFL_GRAPH_OUTPUT_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    data_root = os.environ.get("HARQIS_DATA_ROOT", "").strip()
    if data_root:
        return (Path(data_root).expanduser() / "hfl-graphs").resolve()
    return (Path(__file__).resolve().parents[3] / ".harqis-data" / "hfl-graphs").resolve()


def _outdir(output_root: Path, when: Optional[datetime] = None) -> Path:
    return output_root / _iso_week(when)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _build_env(*, cfg_id__anthropic: str, model: str) -> dict[str, str]:
    """Return a minimal Graphify environment with no competing provider keys."""
    env = {key: os.environ[key] for key in _SAFE_ENV_KEYS if os.environ.get(key)}
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        try:
            cfg = get_anthropic_config(cfg_id__anthropic)
            api_key = str(cfg.app_data.get("api_key") or "").strip()
        except Exception as exc:  # noqa: BLE001 - task returns a clean failure later
            _log.warning("hfl graph: Anthropic config %s unavailable (%s)", cfg_id__anthropic, exc)
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key
    env["ANTHROPIC_MODEL"] = model
    return env


def _daily_corpus_files(corpus_dir: Path, max_files: int) -> list[Path]:
    files: list[Path] = []
    for path in sorted(corpus_dir.glob("*.md"), reverse=True):
        try:
            datetime.strptime(path.stem, "%Y-%m-%d")
        except ValueError:
            continue
        files.append(path)
        if len(files) >= max(1, int(max_files)):
            break
    return files


def _parse_stats(report_md: Path) -> dict[str, int]:
    if not report_md.is_file():
        return {}
    stats: dict[str, int] = {}
    try:
        for line in report_md.read_text(encoding="utf-8").splitlines():
            stripped = line.strip().lstrip("-* ").strip()
            for key in ("Nodes", "Edges", "Clusters", "Files"):
                if stripped.startswith(f"{key}:"):
                    raw = stripped.split(":", 1)[1].strip().split()[0].replace(",", "")
                    try:
                        stats[key.casefold()] = int(raw)
                    except ValueError:
                        pass
    except OSError:
        return stats
    return stats


def _index_summary(
    *,
    iso_week: str,
    out_dir: Path,
    stats: dict[str, Any],
    elapsed_sec: float,
) -> bool:
    """Best-effort metadata projection. Corpus paths and source text are omitted."""
    try:
        from core.apps.es_logging.app.elasticsearch import post

        index = os.environ.get("HFL_GRAPH_ES_INDEX", "").strip() or _DEFAULT_INDEX
        post(
            {
                "iso_week": iso_week,
                "out_dir": str(out_dir),
                "graph_json": str(out_dir / "graph.json"),
                "elapsed_sec": round(elapsed_sec, 2),
                "stats": stats,
                "built_at": datetime.now().isoformat(),
            },
            index,
            location_key=f"hfl-graph-{iso_week}",
            use_interval_map=False,
        )
        return True
    except Exception as exc:  # noqa: BLE001 - verified files remain the source
        _log.warning("hfl graph: ES summary skipped (%s)", exc)
        return False


def build_hfl_knowledge_graph_impl(
    *,
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = _DEFAULT_HAIKU,
    max_files: int = _DEFAULT_MAX_FILES,
    timeout_sec: int = _DEFAULT_TIMEOUT_SEC,
    corpus_dir_override: Optional[str] = None,
    output_root_override: Optional[str] = None,
) -> dict[str, Any]:
    """Build a verified merged graph. Never raises for operational failures."""
    if not _enabled():
        return {"ok": False, "skipped": "disabled"}
    if model != _DEFAULT_HAIKU:
        return {"ok": False, "reason": "unsupported_model"}

    cli = _graphify_path()
    if not cli:
        return {"ok": False, "skipped": "cli_missing"}

    corpus_dir = (
        Path(corpus_dir_override).expanduser().resolve()
        if corpus_dir_override
        else resolve_corpus_dir().resolve()
    )
    corpus_files = _daily_corpus_files(corpus_dir, max_files)
    if not corpus_files:
        return {"ok": False, "skipped": "empty_corpus", "corpus_dir": str(corpus_dir)}

    output_root = (
        Path(output_root_override).expanduser().resolve()
        if output_root_override
        else _default_output_root()
    )
    if _is_within(output_root, corpus_dir):
        return {"ok": False, "reason": "output_inside_corpus"}

    iso_week = _iso_week()
    out_dir = _outdir(output_root)
    semantic_out = out_dir / "semantic"
    artifact_dir = semantic_out / "graphify-out"
    out_dir.mkdir(parents=True, exist_ok=True)
    if semantic_out.is_symlink() or semantic_out.is_file():
        semantic_out.unlink()
    elif semantic_out.exists():
        shutil.rmtree(semantic_out)

    deterministic = build_deterministic_graph(corpus_dir)
    write_graph(out_dir / "deterministic.json", deterministic)
    env = _build_env(cfg_id__anthropic=cfg_id__anthropic, model=model)
    if not env.get("ANTHROPIC_API_KEY"):
        return {
            "ok": False,
            "reason": "anthropic_key_missing",
            "out_dir": str(out_dir),
            "deterministic_graph_json": str(out_dir / "deterministic.json"),
        }

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="harqis-hfl-graph-") as staging_raw:
        staging = Path(staging_raw)
        for source in corpus_files:
            shutil.copy2(source, staging / source.name)
        argv = [
            cli,
            "extract",
            str(staging),
            "--out",
            str(semantic_out),
            "--backend",
            "claude",
            "--model",
            model,
            "--force",
            "--max-concurrency",
            "1",
        ]
        try:
            proc = subprocess.run(
                argv,
                env=env,
                timeout=max(1, int(timeout_sec)),
                capture_output=True,
                text=True,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "reason": "timeout",
                "timeout_sec": timeout_sec,
                "out_dir": str(out_dir),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "reason": f"subprocess_error:{type(exc).__name__}",
                "out_dir": str(out_dir),
            }

    elapsed = time.monotonic() - started
    if proc.returncode != 0:
        return {
            "ok": False,
            "reason": "non_zero_exit",
            "returncode": proc.returncode,
            "out_dir": str(out_dir),
        }

    missing = [name for name in _REQUIRED_ARTIFACTS if not (artifact_dir / name).is_file()]
    if missing:
        return {
            "ok": False,
            "reason": "missing_artifacts",
            "missing": missing,
            "out_dir": str(out_dir),
        }

    try:
        semantic = load_graph(artifact_dir / "graph.json")
        merged = merge_graphs(deterministic, semantic)
        write_graph(out_dir / "graph.json", merged)
    except (OSError, ValueError, TypeError) as exc:
        return {
            "ok": False,
            "reason": "invalid_graph_artifact",
            "error": type(exc).__name__,
            "out_dir": str(out_dir),
        }

    stats: dict[str, Any] = _parse_stats(artifact_dir / "GRAPH_REPORT.md")
    stats.update(
        {
            "deterministic_nodes": len(deterministic["nodes"]),
            "deterministic_edges": len(deterministic["links"]),
            "merged_nodes": len(merged["nodes"]),
            "merged_edges": len(merged["links"]),
            "input_files": len(corpus_files),
        }
    )
    try:
        es_indexed = bool(
            _index_summary(
                iso_week=iso_week,
                out_dir=out_dir,
                stats=stats,
                elapsed_sec=elapsed,
            )
        )
    except Exception as exc:  # protects the graph if a test/adapter violates best-effort
        _log.warning("hfl graph: ES summary adapter failed (%s)", exc)
        es_indexed = False

    return {
        "ok": True,
        "iso_week": iso_week,
        "out_dir": str(out_dir),
        "graph_json": str(out_dir / "graph.json"),
        "deterministic_graph_json": str(out_dir / "deterministic.json"),
        "semantic_graph_json": str(artifact_dir / "graph.json"),
        "graph_html": str(artifact_dir / "graph.html"),
        "report_md": str(artifact_dir / "GRAPH_REPORT.md"),
        "stats": stats,
        "elapsed_sec": round(elapsed, 2),
        "es_indexed": es_indexed,
    }


@SPROUT.task()
@log_result()
def build_hfl_knowledge_graph(**kwargs: Any) -> dict[str, Any]:
    """Celery entry point; intentionally absent from Beat until promoted."""
    return build_hfl_knowledge_graph_impl(**kwargs)
