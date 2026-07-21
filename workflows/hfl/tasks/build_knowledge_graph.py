"""Opt-in HFL graph build with deterministic and optional semantic layers."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from core.apps.es_logging.app.elasticsearch import log_result
from core.apps.sprout.app.celery import SPROUT
from core.utilities.logging.custom_logger import create_logger

from apps.antropic.config import get_config as get_anthropic_config
from workflows.hfl.knowledge_graph import (
    build_deterministic_graph,
    load_graph,
    merge_graphs,
    write_graph,
    write_verified_graph,
)
from workflows.hfl.tasks.capture import resolve_corpus_dir

_log = create_logger("hfl.build_knowledge_graph")

_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"
_DEFAULT_INDEX = "harqis-hfl-graph"
_DEFAULT_MAX_FILES = 500
_DEFAULT_TIMEOUT_SEC = 60 * 30
_REQUIRED_ARTIFACTS = ("graph.json", "GRAPH_REPORT.md", "graph.html")
_SAFE_ENV_KEYS = (
    "PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
)


def _enabled() -> bool:
    return os.environ.get("HARQIS_HFL_GRAPH_ENABLE", "").strip().casefold() in {
        "1", "true", "yes", "on",
    }


def _graphify_path() -> Optional[str]:
    return shutil.which("graphify")


def _iso_week(when: Optional[datetime] = None) -> str:
    iso = (when or datetime.now()).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _default_output_root() -> Path:
    configured = os.environ.get("HFL_GRAPH_OUTPUT_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser()
    data_root = os.environ.get("HARQIS_DATA_ROOT", "").strip()
    if data_root:
        return Path(data_root).expanduser() / "hfl-graphs"
    return Path(__file__).resolve().parents[3] / ".harqis-data" / "hfl-graphs"


def _outdir(output_root: Path, when: Optional[datetime] = None) -> Path:
    """Compatibility helper: return the weekly generation parent."""
    return output_root / _iso_week(when)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _has_symlink_component(path: Path) -> bool:
    absolute = path.expanduser().absolute()
    return any(candidate.is_symlink() for candidate in (absolute, *absolute.parents))


def _build_env(*, cfg_id__anthropic: str, model: str) -> dict[str, str]:
    """Return a minimal Graphify environment with no competing provider keys."""
    env = {key: os.environ[key] for key in _SAFE_ENV_KEYS if os.environ.get(key)}
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        try:
            cfg = get_anthropic_config(cfg_id__anthropic)
            api_key = str(cfg.app_data.get("api_key") or "").strip()
        except Exception as exc:  # noqa: BLE001
            _log.warning("hfl graph: Anthropic config %s unavailable (%s)", cfg_id__anthropic, exc)
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key
    env["ANTHROPIC_MODEL"] = model
    return env


def _open_directory_no_follow(path: Path) -> int:
    absolute = path.expanduser().absolute()
    descriptor = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in absolute.parts[1:]:
            next_descriptor = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _snapshot_corpus(corpus_dir: Path, staging: Path, max_files: int) -> list[str]:
    """Discover and copy corpus files relative to one stable directory descriptor."""
    corpus_fd = _open_directory_no_follow(corpus_dir)
    copied: list[str] = []
    try:
        candidates: list[str] = []
        for name in os.listdir(corpus_fd):
            path = Path(name)
            if path.suffix != ".md":
                continue
            try:
                datetime.strptime(path.stem, "%Y-%m-%d")
            except ValueError:
                continue
            candidates.append(name)
        for name in sorted(candidates, reverse=True)[: max(1, int(max_files))]:
            descriptor = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=corpus_fd,
            )
            try:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise ValueError("corpus source is not a regular file")
                with os.fdopen(descriptor, "rb", closefd=False) as source:
                    with (staging / name).open("xb") as destination:
                        shutil.copyfileobj(source, destination)
            finally:
                os.close(descriptor)
            copied.append(name)
    finally:
        os.close(corpus_fd)
    return copied


def _parse_stats(report_md: Path) -> dict[str, int]:
    if not report_md.is_file() or report_md.is_symlink():
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


def _index_summary(*, iso_week: str, out_dir: Path, stats: dict[str, Any], elapsed_sec: float) -> bool:
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
                "built_at": datetime.now(timezone.utc).isoformat(),
            },
            index,
            location_key=f"hfl-graph-{iso_week}",
            use_interval_map=False,
        )
        return True
    except Exception as exc:  # noqa: BLE001
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
    """Build one immutable generation; failed builds are never query-visible."""
    if not _enabled():
        return {"ok": False, "skipped": "disabled"}
    if model != _DEFAULT_HAIKU:
        return {"ok": False, "reason": "unsupported_model"}
    cli = _graphify_path()
    if not cli:
        return {"ok": False, "skipped": "cli_missing"}

    corpus_dir = Path(corpus_dir_override).expanduser() if corpus_dir_override else resolve_corpus_dir()
    if corpus_dir.is_symlink() or not corpus_dir.is_dir():
        return {"ok": False, "reason": "unsafe_corpus_dir"}
    corpus_dir = corpus_dir.resolve(strict=True)

    output_root = (
        Path(output_root_override).expanduser() if output_root_override else _default_output_root()
    ).absolute()
    if _has_symlink_component(output_root):
        return {"ok": False, "reason": "unsafe_output_root"}
    if _is_within(output_root.resolve(strict=False), corpus_dir):
        return {"ok": False, "reason": "output_inside_corpus"}

    iso_week = _iso_week()
    generation = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid4().hex}"
    out_dir = output_root / iso_week / generation
    env = _build_env(cfg_id__anthropic=cfg_id__anthropic, model=model)
    if not env.get("ANTHROPIC_API_KEY"):
        return {"ok": False, "reason": "anthropic_key_missing", "out_dir": str(out_dir)}

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="harqis-hfl-graph-") as workspace_raw:
        workspace = Path(workspace_raw)
        staging = workspace / "corpus"
        staging.mkdir(mode=0o700)
        deterministic_path = workspace / "deterministic.json"
        semantic_out = workspace / "semantic"
        artifact_dir = semantic_out / "graphify-out"
        try:
            corpus_files = _snapshot_corpus(corpus_dir, staging, max_files)
        except (OSError, ValueError):
            return {"ok": False, "reason": "unsafe_corpus_file", "out_dir": str(out_dir)}
        if not corpus_files:
            return {"ok": False, "skipped": "empty_corpus", "corpus_dir": str(corpus_dir)}
        try:
            deterministic = build_deterministic_graph(staging)
        except ValueError as exc:
            return {
                "ok": False,
                "reason": "invalid_corpus",
                "error": type(exc).__name__,
                "out_dir": str(out_dir),
            }
        write_graph(deterministic_path, deterministic)
        argv = [
            cli, "extract", str(staging), "--out", str(semantic_out),
            "--backend", "claude", "--model", model, "--force",
            "--max-concurrency", "1",
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
            return {"ok": False, "reason": "timeout", "timeout_sec": timeout_sec, "out_dir": str(out_dir)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reason": f"subprocess_error:{type(exc).__name__}", "out_dir": str(out_dir)}

        elapsed = time.monotonic() - started
        if proc.returncode != 0:
            return {"ok": False, "reason": "non_zero_exit", "returncode": proc.returncode, "out_dir": str(out_dir)}

        missing = [
            name for name in _REQUIRED_ARTIFACTS
            if not (artifact_dir / name).is_file() or (artifact_dir / name).is_symlink()
        ]
        if missing:
            return {"ok": False, "reason": "missing_artifacts", "missing": missing, "out_dir": str(out_dir)}

        try:
            semantic = load_graph(artifact_dir / "graph.json", require_envelope=False)
            merged = merge_graphs(deterministic, semantic)
            graph_path = write_verified_graph(
                out_dir,
                merged,
                artifacts={
                    "deterministic.json": deterministic_path,
                    "semantic/graphify-out/graph.json": artifact_dir / "graph.json",
                    "semantic/graphify-out/graph.html": artifact_dir / "graph.html",
                    "semantic/graphify-out/GRAPH_REPORT.md": artifact_dir / "GRAPH_REPORT.md",
                },
            )
        except (OSError, ValueError, TypeError) as exc:
            return {
                "ok": False,
                "reason": "invalid_graph_artifact",
                "error": type(exc).__name__,
                "out_dir": str(out_dir),
            }
        stats: dict[str, Any] = _parse_stats(artifact_dir / "GRAPH_REPORT.md")

    stats.update(
        deterministic_nodes=len(deterministic["nodes"]),
        deterministic_edges=len(deterministic["links"]),
        merged_nodes=len(merged["nodes"]),
        merged_edges=len(merged["links"]),
        input_files=len(corpus_files),
    )
    try:
        es_indexed = bool(_index_summary(iso_week=iso_week, out_dir=out_dir, stats=stats, elapsed_sec=elapsed))
    except Exception as exc:  # adapter safety
        _log.warning("hfl graph: ES summary adapter failed (%s)", exc)
        es_indexed = False

    final_artifacts = out_dir / "semantic" / "graphify-out"
    return {
        "ok": True,
        "iso_week": iso_week,
        "out_dir": str(out_dir),
        "graph_json": str(graph_path),
        "deterministic_graph_json": str(out_dir / "deterministic.json"),
        "semantic_graph_json": str(final_artifacts / "graph.json"),
        "graph_html": str(final_artifacts / "graph.html"),
        "report_md": str(final_artifacts / "GRAPH_REPORT.md"),
        "stats": stats,
        "elapsed_sec": round(elapsed, 2),
        "es_indexed": es_indexed,
    }


@SPROUT.task()
@log_result()
def build_hfl_knowledge_graph() -> dict[str, Any]:
    """Celery entry point; fixed configuration and absent from Beat until promoted."""
    return build_hfl_knowledge_graph_impl()
