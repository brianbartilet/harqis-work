from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from workflows.hfl.knowledge_graph import (
    build_deterministic_graph,
    merge_graphs,
    query_graph,
)
from workflows.hfl.tasks import build_knowledge_graph as task


ENTRY_TEMPLATE = """## {when}
Source:          {source}
Machine:         {machine}
Entry ID:        {entry_id}
Moment:          {moment}
What happened:   {what}
Why it stayed:   {why}
Possible use:    {use}
Tags:            {tags}
References:
                 - {reference}

"""


@pytest.fixture(autouse=True)
def _fake_anthropic_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


def _write_entry(
    corpus: Path,
    *,
    day: str = "2026-07-01",
    when: str = "2026-07-01 09:00",
    source: str = "manual",
    machine: str = "mac-mini",
    entry_id: str = "hfl-test-1",
    moment: str = "Plaud OAuth recovery",
    what: str = "A stale callback configuration broke transcription sync.",
    why: str = "The same recovery pattern appeared on another machine.",
    use: str = "incident retrospective",
    tags: str = "#oauth #plaud",
    reference: str = "https://example.test/incidents/oauth",
) -> Path:
    corpus.mkdir(parents=True, exist_ok=True)
    path = corpus / f"{day}.md"
    path.write_text(
        ENTRY_TEMPLATE.format(
            when=when,
            source=source,
            machine=machine,
            entry_id=entry_id,
            moment=moment,
            what=what,
            why=why,
            use=use,
            tags=tags,
            reference=reference,
        ),
        encoding="utf-8",
    )
    return path


def _artifact_set(out_arg: Path) -> Path:
    artifact_dir = out_arg / "graphify-out"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "graph.json").write_text(
        json.dumps(
            {
                "directed": True,
                "multigraph": False,
                "graph": {},
                "nodes": [
                    {"id": "semantic:oauth-recovery", "label": "OAuth recovery pattern"}
                ],
                "links": [],
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "GRAPH_REPORT.md").write_text(
        "Nodes: 1\nEdges: 0\nClusters: 1\n", encoding="utf-8"
    )
    (artifact_dir / "graph.html").write_text("<html></html>", encoding="utf-8")
    return artifact_dir


def test_deterministic_graph_projects_explicit_hfl_fields(tmp_path: Path):
    corpus = tmp_path / "corpus"
    _write_entry(corpus)

    graph = build_deterministic_graph(corpus)
    nodes = {node["id"]: node for node in graph["nodes"]}
    links = {(link["source"], link["relation"], link["target"]) for link in graph["links"]}

    entry_id = "entry:hfl-test-1"
    assert nodes[entry_id]["label"] == "Plaud OAuth recovery"
    assert (entry_id, "occurred_on", "date:2026-07-01") in links
    assert (entry_id, "part_of", "week:2026-W27") in links
    assert (entry_id, "tagged", "tag:oauth") in links
    assert (entry_id, "sourced_from", "source:manual") in links
    assert (entry_id, "captured_on", "machine:mac-mini") in links
    assert (
        entry_id,
        "references",
        "artifact:https://example.test/incidents/oauth",
    ) in links


def test_merge_bridges_semantic_nodes_to_entries_by_source_file(tmp_path: Path):
    corpus = tmp_path / "corpus"
    _write_entry(corpus)
    deterministic = build_deterministic_graph(corpus)
    semantic = {
        "nodes": [
            {
                "id": "concept:callback-recovery",
                "label": "Callback recovery",
                "source_file": "2026-07-01.md",
            }
        ],
        "links": [],
    }

    merged = merge_graphs(deterministic, semantic)

    assert any(
        edge["source"] == "entry:hfl-test-1"
        and edge["target"] == "concept:callback-recovery"
        and edge["relation"] == "semantically_enriched_by"
        for edge in merged["links"]
    )


def test_merged_graph_exposes_non_obvious_relationship_paths(tmp_path: Path):
    corpus = tmp_path / "corpus"
    _write_entry(corpus, entry_id="hfl-plaud", moment="Plaud transcription incident")
    _write_entry(
        corpus,
        day="2026-07-02",
        when="2026-07-02 10:00",
        entry_id="hfl-drive",
        moment="Drive OAuth callback failure",
        source="browsing",
        tags="#oauth #drive",
        reference="https://example.test/incidents/drive",
    )
    _write_entry(
        corpus,
        day="2026-07-03",
        when="2026-07-03 11:00",
        entry_id="hfl-recovery",
        moment="Reusable OAuth recovery checklist",
        source="git",
        tags="#oauth #automation",
        reference="https://example.test/playbooks/oauth",
    )
    deterministic = build_deterministic_graph(corpus)
    semantic = {
        "directed": True,
        "multigraph": False,
        "graph": {},
        "nodes": [
            {"id": "lesson:oauth-recovery", "label": "OAuth recovery pattern"},
        ],
        "links": [
            {"source": "entry:hfl-plaud", "target": "lesson:oauth-recovery", "relation": "demonstrates"},
            {"source": "entry:hfl-drive", "target": "lesson:oauth-recovery", "relation": "demonstrates"},
            {"source": "entry:hfl-recovery", "target": "lesson:oauth-recovery", "relation": "automates"},
        ],
    }

    merged = merge_graphs(deterministic, semantic)
    result = query_graph(merged, "Plaud OAuth recovery", depth=2, limit=20)

    labels = {node["label"] for node in result["nodes"]}
    relations = {edge["relation"] for edge in result["links"]}
    assert "Plaud transcription incident" in labels
    assert "OAuth recovery pattern" in labels
    assert "Drive OAuth callback failure" in labels
    assert {"demonstrates", "tagged"} & relations
    assert result["explanations"]


def test_build_is_disabled_without_explicit_enable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("HARQIS_HFL_GRAPH_ENABLE", raising=False)
    monkeypatch.setattr(task, "_graphify_path", lambda: pytest.fail("CLI lookup must not run"))

    assert task.build_hfl_knowledge_graph_impl() == {
        "ok": False,
        "skipped": "disabled",
    }


def test_build_rejects_unreviewed_model_before_cli_lookup(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HARQIS_HFL_GRAPH_ENABLE", "1")
    monkeypatch.setattr(task, "_graphify_path", lambda: pytest.fail("CLI lookup must not run"))

    result = task.build_hfl_knowledge_graph_impl(model="claude-opus-unreviewed")

    assert result == {"ok": False, "reason": "unsupported_model"}


def test_build_skips_when_cli_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HARQIS_HFL_GRAPH_ENABLE", "1")
    monkeypatch.setattr(task, "_graphify_path", lambda: None)

    assert task.build_hfl_knowledge_graph_impl()["skipped"] == "cli_missing"


def test_build_skips_empty_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HARQIS_HFL_GRAPH_ENABLE", "1")
    monkeypatch.setattr(task, "_graphify_path", lambda: "/venv/bin/graphify")

    result = task.build_hfl_knowledge_graph_impl(corpus_dir_override=str(tmp_path))

    assert result["skipped"] == "empty_corpus"


def test_build_uses_current_cli_pinned_backend_and_verified_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    corpus = tmp_path / "corpus"
    output = tmp_path / "graphs"
    _write_entry(corpus)
    seen: dict = {}

    monkeypatch.setenv("HARQIS_HFL_GRAPH_ENABLE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "must-not-leak")
    monkeypatch.setattr(task, "_graphify_path", lambda: "/venv/bin/graphify")
    monkeypatch.setattr(task, "_index_summary", lambda **kwargs: None)

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["env"] = kwargs["env"]
        out_arg = Path(argv[argv.index("--out") + 1])
        _artifact_set(out_arg)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(task.subprocess, "run", fake_run)

    result = task.build_hfl_knowledge_graph_impl(
        corpus_dir_override=str(corpus),
        output_root_override=str(output),
        max_files=1,
    )

    assert result["ok"] is True
    assert seen["argv"][:3] == ["/venv/bin/graphify", "extract", seen["argv"][2]]
    assert "--backend" in seen["argv"] and seen["argv"][seen["argv"].index("--backend") + 1] == "claude"
    assert "--model" in seen["argv"]
    assert "--max-files" not in seen["argv"]
    assert "--force" in seen["argv"]
    assert seen["env"]["ANTHROPIC_API_KEY"] == "test-key"
    assert "GEMINI_API_KEY" not in seen["env"]
    assert Path(result["graph_json"]).is_file()
    assert Path(result["semantic_graph_json"]).parent.name == "graphify-out"
    assert not str(Path(result["out_dir"])).startswith(str(corpus))


def test_build_reports_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    corpus = tmp_path / "corpus"
    _write_entry(corpus)
    monkeypatch.setenv("HARQIS_HFL_GRAPH_ENABLE", "1")
    monkeypatch.setattr(task, "_graphify_path", lambda: "/venv/bin/graphify")
    monkeypatch.setattr(
        task.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired(a[0], 2)),
    )

    result = task.build_hfl_knowledge_graph_impl(
        corpus_dir_override=str(corpus), output_root_override=str(tmp_path / "out")
    )

    assert result["reason"] == "timeout"


def test_build_reports_nonzero_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    corpus = tmp_path / "corpus"
    _write_entry(corpus)
    monkeypatch.setenv("HARQIS_HFL_GRAPH_ENABLE", "1")
    monkeypatch.setattr(task, "_graphify_path", lambda: "/venv/bin/graphify")
    monkeypatch.setattr(
        task.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=2, stdout="", stderr="bad invocation"),
    )

    result = task.build_hfl_knowledge_graph_impl(
        corpus_dir_override=str(corpus), output_root_override=str(tmp_path / "out")
    )

    assert result["reason"] == "non_zero_exit"
    assert result["returncode"] == 2


def test_exit_zero_without_artifacts_is_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    corpus = tmp_path / "corpus"
    output = tmp_path / "out"
    _write_entry(corpus)
    stale = task._outdir(output) / "semantic"
    _artifact_set(stale)
    monkeypatch.setenv("HARQIS_HFL_GRAPH_ENABLE", "1")
    monkeypatch.setattr(task, "_graphify_path", lambda: "/venv/bin/graphify")
    monkeypatch.setattr(
        task.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    result = task.build_hfl_knowledge_graph_impl(
        corpus_dir_override=str(corpus), output_root_override=str(output)
    )

    assert result["reason"] == "missing_artifacts"
    assert "graph.json" in result["missing"]


def test_es_failure_does_not_erase_verified_graph(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    corpus = tmp_path / "corpus"
    _write_entry(corpus)
    monkeypatch.setenv("HARQIS_HFL_GRAPH_ENABLE", "1")
    monkeypatch.setattr(task, "_graphify_path", lambda: "/venv/bin/graphify")

    def fake_run(argv, **kwargs):
        _artifact_set(Path(argv[argv.index("--out") + 1]))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(task.subprocess, "run", fake_run)
    monkeypatch.setattr(task, "_index_summary", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("ES down")))

    result = task.build_hfl_knowledge_graph_impl(
        corpus_dir_override=str(corpus), output_root_override=str(tmp_path / "out")
    )

    assert result["ok"] is True
    assert result["es_indexed"] is False
    assert Path(result["graph_json"]).is_file()


def test_graphify_dependency_is_exactly_pinned():
    requirement = Path("requirements-graphify.txt").read_text(encoding="utf-8")
    assert "graphifyy[anthropic]==0.9.22" in requirement


def test_read_only_graph_query_uses_latest_verified_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from workflows.hfl import mcp as hfl_mcp

    graph_dir = tmp_path / "2026-W27"
    graph_dir.mkdir(parents=True)
    (graph_dir / "graph.json").write_text(
        json.dumps(
            {
                "nodes": [
                    {"id": "entry:1", "label": "Plaud OAuth incident"},
                    {"id": "lesson:1", "label": "OAuth recovery pattern"},
                ],
                "links": [
                    {"source": "entry:1", "target": "lesson:1", "relation": "demonstrates"}
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HFL_GRAPH_OUTPUT_ROOT", str(tmp_path))

    result = hfl_mcp.memory_graph_query_data("Plaud recovery", depth=2, limit=10)

    assert result["found"] is True
    assert result["graph"] == str(graph_dir / "graph.json")
    assert any("demonstrates" in line for line in result["explanations"])
