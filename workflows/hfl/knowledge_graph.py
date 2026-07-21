"""Deterministic HFL graph projection and read-only local traversal.

The Markdown corpus remains the source of truth. This module projects fields
already present in :class:`HflEntry` without an LLM, then optionally merges a
Graphify semantic graph. The merged file uses NetworkX node-link JSON shape so
Graphify's own query/path/explain commands can consume it too.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from workflows.hfl.dto import HflEntry
from workflows.hfl.tasks.retrieve import _entries_for_file

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.:/-]*", re.IGNORECASE)


def _slug(value: str) -> str:
    return re.sub(r"\s+", "-", value.strip().casefold())


def _node(node_id: str, label: str, node_type: str, **attrs: Any) -> dict[str, Any]:
    return {
        "id": node_id,
        "label": label,
        "file_type": node_type,
        "norm_label": label.casefold(),
        **{key: value for key, value in attrs.items() if value not in (None, "", [], ())},
    }


def _link(source: str, target: str, relation: str) -> dict[str, Any]:
    return {
        "source": source,
        "target": target,
        "relation": relation,
        "confidence": "EXTRACTED",
        "confidence_score": 1.0,
        "layer": "deterministic",
    }


def _entry_id(entry: HflEntry, source_path: Path, ordinal: int) -> str:
    if entry.entry_id:
        return f"entry:{entry.entry_id}"
    stable = "\n".join(
        [str(source_path), str(ordinal), entry.moment, entry.when.isoformat() if entry.when else ""]
    )
    return "entry:" + hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]


def _daily_files(corpus_dir: Path) -> Iterable[Path]:
    for path in sorted(corpus_dir.glob("*.md")):
        try:
            date.fromisoformat(path.stem)
        except ValueError:
            continue
        yield path


def build_deterministic_graph(corpus_dir: Path) -> dict[str, Any]:
    """Project explicit entry/date/week/tag/source/machine/artifact relationships."""
    corpus_dir = Path(corpus_dir)
    nodes: dict[str, dict[str, Any]] = {}
    links: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add_node(item: dict[str, Any]) -> None:
        nodes.setdefault(str(item["id"]), item)

    def add_link(source: str, target: str, relation: str) -> None:
        links.setdefault((source, relation, target), _link(source, target, relation))

    for path in _daily_files(corpus_dir):
        for ordinal, raw in enumerate(_entries_for_file(path)):
            entry = HflEntry.from_markdown(raw["header"], raw["body"])
            if not entry.moment:
                continue
            eid = _entry_id(entry, path, ordinal)
            add_node(
                _node(
                    eid,
                    entry.moment,
                    "hfl_entry",
                    when=entry.when.isoformat() if entry.when else None,
                    source_file=str(path),
                    what_happened=entry.what_happened,
                    why_it_stayed=entry.why_it_stayed,
                    possible_use=entry.possible_use,
                    layer="deterministic",
                )
            )

            if entry.when:
                day = entry.when.date().isoformat()
                iso = entry.when.isocalendar()
                week = f"{iso.year}-W{iso.week:02d}"
                day_id, week_id = f"date:{day}", f"week:{week}"
                add_node(_node(day_id, day, "date", layer="deterministic"))
                add_node(_node(week_id, week, "week", layer="deterministic"))
                add_link(eid, day_id, "occurred_on")
                add_link(eid, week_id, "part_of")

            for tag in entry.tags:
                tag_id = f"tag:{_slug(tag)}"
                add_node(_node(tag_id, f"#{tag}", "tag", layer="deterministic"))
                add_link(eid, tag_id, "tagged")

            if entry.source:
                source_id = f"source:{_slug(entry.source)}"
                add_node(_node(source_id, entry.source, "source", layer="deterministic"))
                add_link(eid, source_id, "sourced_from")

            if entry.machine:
                machine_id = f"machine:{_slug(entry.machine)}"
                add_node(_node(machine_id, entry.machine, "machine", layer="deterministic"))
                add_link(eid, machine_id, "captured_on")

            for reference in entry.references:
                artifact_id = f"artifact:{reference}"
                add_node(
                    _node(
                        artifact_id,
                        reference,
                        "artifact",
                        reference=reference,
                        layer="deterministic",
                    )
                )
                add_link(eid, artifact_id, "references")

    return {
        "directed": True,
        "multigraph": False,
        "graph": {"projection": "hfl-deterministic-v1"},
        "nodes": list(nodes.values()),
        "links": list(links.values()),
        "hyperedges": [],
    }


def merge_graphs(*graphs: dict[str, Any]) -> dict[str, Any]:
    """Merge node-link graphs without allowing semantic data to erase DTO facts."""
    nodes: dict[str, dict[str, Any]] = {}
    links: dict[tuple[str, str, str], dict[str, Any]] = {}
    for graph in graphs:
        for raw in graph.get("nodes", []):
            if not isinstance(raw, dict) or "id" not in raw:
                continue
            item = dict(raw)
            item.setdefault("label", str(item["id"]))
            item.setdefault("norm_label", str(item["label"]).casefold())
            item.setdefault("layer", "semantic")
            existing = nodes.get(str(item["id"]))
            if existing:
                nodes[str(item["id"])] = {**item, **existing}
            else:
                nodes[str(item["id"])] = item
        edge_rows = graph.get("links", graph.get("edges", []))
        for raw in edge_rows:
            if not isinstance(raw, dict):
                continue
            source, target = str(raw.get("source", "")), str(raw.get("target", ""))
            if not source or not target:
                continue
            relation = str(raw.get("relation") or "related_to")
            item = dict(raw, source=source, target=target, relation=relation)
            item.setdefault("layer", "semantic")
            links.setdefault((source, relation, target), item)

    entries_by_file: dict[str, list[str]] = {}
    semantic_by_file: dict[str, list[str]] = {}
    for node_id, item in nodes.items():
        source_file = str(item.get("source_file") or "").strip()
        if not source_file:
            continue
        filename = Path(source_file).name.casefold()
        if item.get("file_type") == "hfl_entry":
            entries_by_file.setdefault(filename, []).append(node_id)
        elif item.get("layer") != "deterministic":
            semantic_by_file.setdefault(filename, []).append(node_id)
    for filename in entries_by_file.keys() & semantic_by_file.keys():
        for entry_id in entries_by_file[filename]:
            for semantic_id in semantic_by_file[filename]:
                bridge = {
                    "source": entry_id,
                    "target": semantic_id,
                    "relation": "semantically_enriched_by",
                    "confidence": "EXTRACTED",
                    "confidence_score": 1.0,
                    "layer": "provenance_bridge",
                }
                links.setdefault((entry_id, "semantically_enriched_by", semantic_id), bridge)

    valid = set(nodes)
    clean_links = [
        item
        for item in links.values()
        if item["source"] in valid and item["target"] in valid
    ]
    return {
        "directed": True,
        "multigraph": False,
        "graph": {"projection": "hfl-deterministic+semantic-v1"},
        "nodes": list(nodes.values()),
        "links": clean_links,
        "hyperedges": [],
    }


def _tokens(value: str) -> set[str]:
    return {token.casefold() for token in _TOKEN_RE.findall(value or "") if len(token) > 1}


def query_graph(
    graph: dict[str, Any], question: str, *, depth: int = 2, limit: int = 30
) -> dict[str, Any]:
    """Seed by lexical relevance, then traverse relationships in both directions."""
    depth = max(0, min(int(depth), 5))
    limit = max(1, min(int(limit), 100))
    query_tokens = _tokens(question)
    node_map = {str(n["id"]): n for n in graph.get("nodes", []) if isinstance(n, dict) and "id" in n}
    scored: list[tuple[int, str]] = []
    for node_id, node in node_map.items():
        searchable = " ".join(
            str(node.get(key, ""))
            for key in ("id", "label", "what_happened", "why_it_stayed", "possible_use")
        )
        score = len(query_tokens & _tokens(searchable))
        if score:
            scored.append((score, node_id))
    scored.sort(key=lambda row: (-row[0], node_map[row[1]].get("label", row[1]).casefold()))
    seeds = [node_id for _, node_id in scored[:5]]
    if not seeds:
        return {"found": False, "question": question, "nodes": [], "links": [], "explanations": []}

    adjacency: dict[str, list[dict[str, Any]]] = {node_id: [] for node_id in node_map}
    for edge in graph.get("links", graph.get("edges", [])):
        if not isinstance(edge, dict):
            continue
        source, target = str(edge.get("source", "")), str(edge.get("target", ""))
        if source in adjacency and target in adjacency:
            adjacency[source].append(edge)
            adjacency[target].append(edge)

    selected: set[str] = set(seeds)
    queue = deque((seed, 0) for seed in seeds)
    while queue and len(selected) < limit:
        current, distance = queue.popleft()
        if distance >= depth:
            continue
        for edge in adjacency.get(current, []):
            neighbor = str(edge["target"] if edge["source"] == current else edge["source"])
            if neighbor not in selected:
                selected.add(neighbor)
                queue.append((neighbor, distance + 1))
                if len(selected) >= limit:
                    break

    chosen_links = [
        edge
        for edge in graph.get("links", graph.get("edges", []))
        if isinstance(edge, dict)
        and str(edge.get("source")) in selected
        and str(edge.get("target")) in selected
    ]
    explanations = [
        f"{node_map[str(edge['source'])].get('label', edge['source'])} "
        f"--{edge.get('relation', 'related_to')}--> "
        f"{node_map[str(edge['target'])].get('label', edge['target'])}"
        for edge in chosen_links[:limit]
    ]
    return {
        "found": True,
        "question": question,
        "seed_ids": seeds,
        "nodes": [node_map[node_id] for node_id in selected],
        "links": chosen_links,
        "explanations": explanations,
    }


def write_graph(path: Path, graph: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(graph, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def load_graph(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
        raise ValueError(f"invalid graph JSON: {path}")
    return data


def latest_graph(output_root: Path) -> Path | None:
    candidates = sorted(Path(output_root).glob("*/graph.json"), reverse=True)
    return candidates[0] if candidates else None
