"""Deterministic HFL graph projection and bounded read-only traversal.

HFL Markdown remains canonical. Graph artifacts are derived, local, validated,
and replaceable. Semantic enrichment may add edges, but never mutates entries.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import stat
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from workflows.hfl.dto.entry import HflEntry

_WEEK_RE = re.compile(r"^\d{4}-W\d{2}$")
_GENERATION_RE = re.compile(r"^\d{8}T\d{12}Z-[0-9a-f]{32}$")
_DATE_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")
_SCHEMA_VERSION = 1


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", value.casefold()).strip("-") or "unknown"


def _node(node_id: str, label: str, node_type: str, **attrs: Any) -> dict[str, Any]:
    return {
        "id": node_id,
        "label": label,
        "norm_label": label.casefold(),
        "type": node_type,
        "layer": "deterministic",
        **attrs,
    }


def _link(source: str, relation: str, target: str, **attrs: Any) -> dict[str, Any]:
    return {
        "source": source,
        "target": target,
        "relation": relation,
        "layer": "deterministic",
        **attrs,
    }


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
        return True
    except (FileNotFoundError, OSError, ValueError):
        return False


def _valid_week_name(value: str) -> bool:
    if not _WEEK_RE.match(value):
        return False
    year, week = value.split("-W", 1)
    try:
        datetime.fromisocalendar(int(year), int(week), 1)
        return True
    except ValueError:
        return False


def _daily_files(corpus_dir: Path) -> list[Path]:
    if not corpus_dir.is_dir() or corpus_dir.is_symlink():
        return []
    root = corpus_dir.resolve(strict=True)
    return [
        path
        for path in sorted(corpus_dir.glob("????-??-??.md"))
        if path.is_file() and not path.is_symlink() and _inside(path, root)
    ]


def _entry_nodes(
    entry: HflEntry,
    source_file: Path,
    ordinal: int,
) -> tuple[list[dict], list[dict]]:
    when = entry.when or datetime.fromisoformat(source_file.stem)
    date_value = when.date().isoformat()
    iso = when.isocalendar()
    week_value = f"{iso.year}-W{iso.week:02d}"
    fallback_hash = hashlib.sha256(entry.to_markdown().encode("utf-8")).hexdigest()[:10]
    entry_key = entry.entry_id or (
        f"{date_value}-{_slug(entry.moment)}-{ordinal:03d}-{fallback_hash}"
    )
    entry_id = f"entry:{entry_key}"
    nodes = [
        _node(
            entry_id,
            entry.moment or entry_key,
            "hfl_entry",
            occurred_at=when.isoformat(),
            source_file=source_file.name,
            what_happened=entry.what_happened,
            why_it_stayed=entry.why_it_stayed,
            possible_use=entry.possible_use,
        ),
        _node(f"date:{date_value}", date_value, "date"),
        _node(f"week:{week_value}", week_value, "week"),
    ]
    links = [
        _link(entry_id, "occurred_on", f"date:{date_value}"),
        _link(entry_id, "part_of", f"week:{week_value}"),
    ]
    if entry.source:
        node_id = f"source:{_slug(entry.source)}"
        nodes.append(_node(node_id, entry.source, "source"))
        links.append(_link(entry_id, "sourced_from", node_id))
    if entry.machine:
        node_id = f"machine:{_slug(entry.machine)}"
        nodes.append(_node(node_id, entry.machine, "machine"))
        links.append(_link(entry_id, "captured_on", node_id))
    for tag in entry.tags:
        clean = tag.removeprefix("#").strip()
        if clean:
            node_id = f"tag:{_slug(clean)}"
            nodes.append(_node(node_id, clean, "tag"))
            links.append(_link(entry_id, "tagged", node_id))
    for reference in entry.references:
        value = reference.strip()
        if value:
            node_id = f"artifact:{value}"
            nodes.append(_node(node_id, value, "artifact"))
            links.append(_link(entry_id, "references", node_id))
    return nodes, links


def build_deterministic_graph(corpus_dir: Path) -> dict[str, Any]:
    """Project explicit HFL DTO fields into a stable local graph."""
    nodes: dict[str, dict] = {}
    links: dict[tuple[str, str, str], dict] = {}
    files = _daily_files(corpus_dir)
    entry_count = 0
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for ordinal, chunk in enumerate(re.split(r"(?m)^## ", text)[1:], start=1):
            header, _, body = chunk.partition("\n")
            entry = HflEntry.from_markdown(header, body)
            entry_count += 1
            if entry.entry_id and f"entry:{entry.entry_id}" in nodes:
                raise ValueError(f"duplicate Entry ID: {entry.entry_id}")
            new_nodes, new_links = _entry_nodes(entry, path, ordinal)
            for item in new_nodes:
                nodes.setdefault(item["id"], item)
            for item in new_links:
                key = (item["source"], item["relation"], item["target"])
                links.setdefault(key, item)
    graph = {
        "directed": True,
        "multigraph": False,
        "graph": {
            "kind": "hfl-deterministic",
            "schema_version": _SCHEMA_VERSION,
            "source_files": len(files),
            "entries": entry_count,
        },
        "nodes": sorted(nodes.values(), key=lambda item: item["id"]),
        "links": sorted(
            links.values(),
            key=lambda item: (item["source"], item["relation"], item["target"]),
        ),
    }
    validate_graph(graph)
    return graph


def validate_graph(
    graph: Any,
    *,
    require_envelope: bool = True,
) -> dict[str, Any]:
    """Validate the bounded schema accepted by publication and MCP querying."""
    if not isinstance(graph, dict):
        raise ValueError("graph must be an object")
    if require_envelope:
        metadata = graph.get("graph")
        if (
            graph.get("directed") is not True
            or graph.get("multigraph") is not False
            or not isinstance(metadata, dict)
            or metadata.get("schema_version") != _SCHEMA_VERSION
        ):
            raise ValueError(f"graph envelope must use schema_version {_SCHEMA_VERSION}")
    nodes = graph.get("nodes")
    links = graph.get("links")
    if not isinstance(nodes, list) or not isinstance(links, list):
        raise ValueError("graph nodes and links must be lists")
    ids: set[str] = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise ValueError(f"node {index} must be an object")
        node_id = node.get("id")
        label = node.get("label")
        if not isinstance(node_id, str) or not node_id:
            raise ValueError(f"node {index} id must be a non-empty string")
        if not isinstance(label, str):
            raise ValueError(f"node {node_id} label must be a string")
        if node_id in ids:
            raise ValueError(f"duplicate node id: {node_id}")
        if "source_file" in node and not isinstance(node["source_file"], str):
            raise ValueError(f"node {node_id} source_file must be a string")
        ids.add(node_id)
    for index, link in enumerate(links):
        if not isinstance(link, dict):
            raise ValueError(f"link {index} must be an object")
        values = [link.get(key) for key in ("source", "relation", "target")]
        if not all(isinstance(value, str) and value for value in values):
            raise ValueError(f"link {index} fields must be non-empty strings")
        if values[0] not in ids or values[2] not in ids:
            raise ValueError(f"link {index} references an unknown node")
    return graph


def merge_graphs(*graphs: dict[str, Any]) -> dict[str, Any]:
    """Union validated graph layers and add date-level provenance bridges."""
    nodes: dict[str, dict] = {}
    links: dict[tuple[str, str, str], dict] = {}
    for layer_index, graph in enumerate(graphs):
        if not isinstance(graph, dict):
            raise ValueError("graph must be an object")
        for raw in graph.get("nodes", []):
            if not isinstance(raw, dict):
                raise ValueError("node must be an object")
            item = dict(raw)
            node_id = item.get("id")
            label = item.get("label", node_id)
            if not isinstance(node_id, str) or not node_id:
                raise ValueError("node id must be a non-empty string")
            if not isinstance(label, str):
                raise ValueError(f"node {node_id} label must be a string")
            item["label"] = label
            item.setdefault("norm_label", label.casefold())
            item.setdefault("layer", "deterministic" if layer_index == 0 else "semantic")
            existing = nodes.get(node_id)
            if existing and existing.get("layer") == "deterministic" and layer_index > 0:
                continue
            nodes[node_id] = {**existing, **item} if existing else item
        for raw in graph.get("links", []):
            if not isinstance(raw, dict):
                raise ValueError("link must be an object")
            item = dict(raw)
            source, relation, target = (
                item.get("source"),
                item.get("relation") or item.get("label") or "related_to",
                item.get("target"),
            )
            if not all(isinstance(value, str) and value for value in (source, relation, target)):
                raise ValueError("link fields must be non-empty strings")
            item.update(source=source, relation=relation, target=target)
            item.setdefault("layer", "deterministic" if layer_index == 0 else "semantic")
            links.setdefault((source, relation, target), item)

    for node_id, item in sorted(nodes.items()):
        if item.get("layer") != "semantic":
            continue
        match = _DATE_FILE_RE.match(Path(item.get("source_file", "")).name)
        if not match:
            continue
        date_id = f"date:{match.group(1)}"
        if date_id in nodes:
            bridge = {
                "source": node_id,
                "target": date_id,
                "relation": "extracted_from_date",
                "layer": "bridge",
            }
            links.setdefault((node_id, "extracted_from_date", date_id), bridge)

    merged = {
        "directed": True,
        "multigraph": False,
        "graph": {"kind": "hfl-merged", "schema_version": _SCHEMA_VERSION},
        "nodes": sorted(nodes.values(), key=lambda item: item["id"]),
        "links": sorted(
            links.values(),
            key=lambda item: (item["source"], item["relation"], item["target"]),
        ),
    }
    validate_graph(merged)
    return merged


def write_graph(path: Path, graph: dict[str, Any]) -> Path:
    validate_graph(graph)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(graph, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _open_directory_chain(path: Path, *, create: bool) -> int:
    absolute = path.expanduser().absolute()
    if ".." in absolute.parts:
        raise ValueError("unsafe directory path")
    descriptor = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in absolute.parts[1:]:
            if create:
                try:
                    os.mkdir(component, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
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


def _write_bytes_at(directory_fd: int, name: str, content: bytes) -> None:
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
        dir_fd=directory_fd,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(content)
    finally:
        os.close(descriptor)


def _read_regular_bytes(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("artifact source must be a regular file")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _artifact_directory(root_fd: int, parts: tuple[str, ...]) -> int:
    descriptor = os.dup(root_fd)
    try:
        for component in parts:
            if component in {"", ".", ".."}:
                raise ValueError("unsafe artifact path")
            try:
                os.mkdir(component, mode=0o700, dir_fd=descriptor)
            except FileExistsError:
                pass
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


def write_verified_graph(
    generation_dir: Path,
    graph: dict[str, Any],
    *,
    built_at: datetime | None = None,
    artifacts: dict[str, Path] | None = None,
) -> Path:
    """Create one generation through no-follow directory descriptors."""
    validate_graph(graph)
    parent_fd = _open_directory_chain(generation_dir.parent, create=True)
    generation_fd: int | None = None
    try:
        try:
            os.mkdir(generation_dir.name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError as exc:
            if generation_dir.is_symlink():
                raise ValueError("generation directory is a symlink") from exc
            raise ValueError("generation already exists") from exc
        generation_fd = os.open(
            generation_dir.name,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        for relative, source in sorted((artifacts or {}).items()):
            relative_path = Path(relative)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise ValueError("unsafe artifact path")
            target_fd = _artifact_directory(generation_fd, relative_path.parts[:-1])
            try:
                _write_bytes_at(target_fd, relative_path.name, _read_regular_bytes(source))
            finally:
                os.close(target_fd)

        graph_bytes = json.dumps(graph, indent=2, sort_keys=True).encode("utf-8")
        _write_bytes_at(generation_fd, "graph.json", graph_bytes)
        manifest = {
            "status": "success",
            "schema_version": _SCHEMA_VERSION,
            "built_at": (built_at or datetime.now(timezone.utc)).isoformat(),
            "graph_file": "graph.json",
            "sha256": hashlib.sha256(graph_bytes).hexdigest(),
        }
        _write_bytes_at(
            generation_fd,
            "SUCCESS.json",
            json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"),
        )
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ValueError("generation directory is a symlink") from exc
        raise
    finally:
        if generation_fd is not None:
            os.close(generation_fd)
        os.close(parent_fd)
    return generation_dir / "graph.json"


def load_graph(path: Path, *, require_envelope: bool = True) -> dict[str, Any]:
    return validate_graph(
        json.loads(path.read_text(encoding="utf-8")),
        require_envelope=require_envelope,
    )


def latest_graph(root: Path) -> Path | None:
    """Return the newest complete, checksummed, schema-valid generation."""
    if not root.is_dir() or root.is_symlink():
        return None
    candidates: list[tuple[datetime, str, Path]] = []
    try:
        week_dirs = list(root.iterdir())
    except OSError:
        return None
    for week_dir in week_dirs:
        try:
            if not week_dir.is_dir() or week_dir.is_symlink() or not _valid_week_name(week_dir.name):
                continue
            generations = list(week_dir.iterdir())
        except OSError:
            continue
        for generation in generations:
            if (
                not generation.is_dir()
                or generation.is_symlink()
                or not _GENERATION_RE.match(generation.name)
            ):
                continue
            manifest_path = generation / "SUCCESS.json"
            graph_path = generation / "graph.json"
            if (
                not manifest_path.is_file()
                or manifest_path.is_symlink()
                or not graph_path.is_file()
                or graph_path.is_symlink()
            ):
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if (
                    manifest.get("status") != "success"
                    or manifest.get("schema_version") != _SCHEMA_VERSION
                    or manifest.get("graph_file") != "graph.json"
                    or manifest.get("sha256") != _sha256(graph_path)
                    or not isinstance(manifest.get("built_at"), str)
                ):
                    continue
                built_at = datetime.fromisoformat(manifest["built_at"])
                if built_at.tzinfo is None:
                    raise ValueError("manifest built_at must include a timezone")
                load_graph(graph_path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            candidates.append((built_at, str(graph_path), graph_path))
    return max(candidates)[2] if candidates else None


def _tokens(question: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9][a-z0-9._-]+", question.casefold()) if len(token) > 2}


def _search_text(node: dict[str, Any]) -> str:
    fields: Iterable[str] = (
        "label",
        "type",
        "what_happened",
        "why_it_stayed",
        "possible_use",
        "source_file",
    )
    return " ".join(str(node.get(field, "")) for field in fields).casefold()


def query_graph(graph: dict[str, Any], question: str, *, depth: int = 2, limit: int = 30) -> dict[str, Any]:
    """Bounded keyword-seeded traversal; no mutation or query language."""
    validate_graph(graph)
    depth = max(0, min(int(depth), 3))
    limit = max(1, min(int(limit), 100))
    tokens = _tokens(question)
    nodes = {item["id"]: item for item in graph["nodes"]}
    scored = []
    for node_id, item in nodes.items():
        text = _search_text(item)
        score = sum(1 for token in tokens if token in text)
        if score:
            scored.append((-score, node_id))
    scored.sort()
    seed_ids = [node_id for _, node_id in scored[: min(5, limit)]]
    if not seed_ids:
        return {"question": question, "nodes": [], "links": [], "explanations": []}

    adjacency: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for edge in graph["links"]:
        adjacency[edge["source"]].append((edge["target"], edge))
        adjacency[edge["target"]].append((edge["source"], edge))
    for values in adjacency.values():
        values.sort(key=lambda pair: (pair[0], pair[1]["relation"]))

    selected_order = list(seed_ids)
    selected = set(seed_ids)
    queue = deque((node_id, 0) for node_id in seed_ids)
    while queue and len(selected_order) < limit:
        node_id, level = queue.popleft()
        if level >= depth:
            continue
        for neighbor, _ in adjacency.get(node_id, []):
            if neighbor in selected:
                continue
            selected.add(neighbor)
            selected_order.append(neighbor)
            queue.append((neighbor, level + 1))
            if len(selected_order) >= limit:
                break

    chosen_links = sorted(
        (
            edge
            for edge in graph["links"]
            if edge["source"] in selected and edge["target"] in selected
        ),
        key=lambda edge: (edge["source"], edge["relation"], edge["target"]),
    )[:limit]
    chosen_nodes = [nodes[node_id] for node_id in sorted(selected)]
    explanations = [
        f"{nodes[edge['source']]['label']} --{edge['relation']}--> {nodes[edge['target']]['label']}"
        for edge in chosen_links
    ]
    return {
        "question": question,
        "nodes": chosen_nodes,
        "links": chosen_links,
        "explanations": explanations,
    }
