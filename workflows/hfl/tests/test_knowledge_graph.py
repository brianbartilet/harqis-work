from __future__ import annotations

import inspect
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from workflows.hfl.knowledge_graph import (
    build_deterministic_graph,
    latest_graph,
    load_graph,
    merge_graphs,
    query_graph,
    write_verified_graph,
)
from workflows.hfl.tasks import build_knowledge_graph as task


GENERATION = "20260721T120000000000Z-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
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


def _valid_graph(*, nodes: list[dict] | None = None, links: list[dict] | None = None) -> dict:
    return {
        "directed": True,
        "multigraph": False,
        "graph": {"kind": "test", "schema_version": 1},
        "nodes": nodes or [],
        "links": links or [],
    }


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


def test_duplicate_legacy_moments_get_distinct_stable_entry_ids(tmp_path: Path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    blocks = []
    for what in ("First event.", "Second event."):
        blocks.append(
            ENTRY_TEMPLATE.format(
                when="2026-07-01 09:00",
                source="manual",
                machine="mac-mini",
                entry_id="",
                moment="Repeated headline",
                what=what,
                why="Different memory.",
                use="timeline",
                tags="#duplicate",
                reference=f"https://example.test/{len(blocks) + 1}",
            )
        )
    (corpus / "2026-07-01.md").write_text("".join(blocks), encoding="utf-8")

    first = build_deterministic_graph(corpus)
    second = build_deterministic_graph(corpus)
    entries = [node for node in first["nodes"] if node["type"] == "hfl_entry"]

    assert len(entries) == 2
    assert len({node["id"] for node in entries}) == 2
    assert first == second


def test_duplicate_explicit_entry_ids_are_rejected(tmp_path: Path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    blocks = []
    for what in ("First event.", "Second event."):
        blocks.append(
            ENTRY_TEMPLATE.format(
                when="2026-07-01 09:00",
                source="manual",
                machine="mac-mini",
                entry_id="duplicate-id",
                moment="Repeated headline",
                what=what,
                why="Different memory.",
                use="timeline",
                tags="#duplicate",
                reference=f"https://example.test/{len(blocks) + 1}",
            )
        )
    (corpus / "2026-07-01.md").write_text("".join(blocks), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate Entry ID"):
        build_deterministic_graph(corpus)


def test_merge_preserves_deterministic_node_on_semantic_id_collision(tmp_path: Path):
    corpus = tmp_path / "corpus"
    _write_entry(corpus)
    deterministic = build_deterministic_graph(corpus)
    semantic = {
        "nodes": [{"id": "entry:hfl-test-1", "label": "Model overwrite"}],
        "links": [],
    }

    merged = merge_graphs(deterministic, semantic)
    entry = next(node for node in merged["nodes"] if node["id"] == "entry:hfl-test-1")

    assert entry["label"] == "Plaud OAuth recovery"
    assert entry["layer"] == "deterministic"


def test_merge_bridges_semantic_nodes_to_source_date_not_every_entry(tmp_path: Path):
    corpus = tmp_path / "corpus"
    path = _write_entry(corpus)
    path.write_text(
        path.read_text(encoding="utf-8")
        + ENTRY_TEMPLATE.format(
            when="2026-07-01 14:00",
            source="manual",
            machine="mac-mini",
            entry_id="hfl-test-2",
            moment="Unrelated lunch note",
            what="Lunch happened.",
            why="A separate memory.",
            use="personal timeline",
            tags="#lunch",
            reference="https://example.test/lunch",
        ),
        encoding="utf-8",
    )
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
    bridges = [edge for edge in merged["links"] if edge["relation"] == "extracted_from_date"]

    assert bridges == [
        {
            "source": "concept:callback-recovery",
            "target": "date:2026-07-01",
            "relation": "extracted_from_date",
            "layer": "bridge",
        }
    ]
    assert not any(
        edge["source"].startswith("entry:") and edge["target"] == "concept:callback-recovery"
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


def test_query_graph_honours_low_limit_and_is_deterministic(tmp_path: Path):
    corpus = tmp_path / "corpus"
    _write_entry(corpus)
    graph = build_deterministic_graph(corpus)

    first = query_graph(graph, "oauth", depth=3, limit=1)
    second = query_graph(graph, "oauth", depth=3, limit=1)

    assert first == second
    assert len(first["nodes"]) <= 1
    assert len(first["links"]) <= 1


def test_malformed_graph_is_rejected_before_publication(tmp_path: Path):
    with pytest.raises(ValueError, match="label"):
        write_verified_graph(
            tmp_path / "2026-W27" / GENERATION,
            _valid_graph(nodes=[{"id": "bad", "label": 42}]),
        )


def test_write_verified_graph_rejects_symlinked_generation(tmp_path: Path):
    target = tmp_path / "target"
    target.mkdir()
    generation = tmp_path / "2026-W27" / GENERATION
    generation.parent.mkdir()
    generation.symlink_to(target, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        write_verified_graph(generation, _valid_graph())

    assert not (target / "graph.json").exists()
    assert not (target / "SUCCESS.json").exists()


def test_write_verified_graph_rejects_symlinked_parent(tmp_path: Path):
    target = tmp_path / "target"
    target.mkdir()
    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(target, target_is_directory=True)

    with pytest.raises((OSError, ValueError)):
        write_verified_graph(linked_root / "2026-W27" / GENERATION, _valid_graph())

    assert not any(target.rglob("graph.json"))
    assert not any(target.rglob("SUCCESS.json"))


def test_latest_graph_rejects_invalid_week_and_schema(tmp_path: Path):
    invalid_week = tmp_path / "2026-W99" / GENERATION
    write_verified_graph(invalid_week, _valid_graph())
    invalid_schema = _valid_graph()
    invalid_schema["graph"]["schema_version"] = 999

    assert latest_graph(tmp_path) is None
    with pytest.raises(ValueError, match="schema_version"):
        write_verified_graph(tmp_path / "2026-W27" / GENERATION, invalid_schema)


def test_latest_graph_requires_success_manifest_and_valid_checksum(tmp_path: Path):
    unverified = tmp_path / "2026-W99" / "manual"
    unverified.mkdir(parents=True)
    (unverified / "graph.json").write_text('{"nodes": [], "links": []}', encoding="utf-8")
    arbitrary = tmp_path / "2026-W27" / "manual-published"
    write_verified_graph(arbitrary, _valid_graph())
    assert latest_graph(tmp_path) is None

    verified = tmp_path / "2026-W27" / GENERATION
    write_verified_graph(verified, _valid_graph())

    assert latest_graph(tmp_path) == verified / "graph.json"
    (verified / "graph.json").write_text('{"nodes": [}', encoding="utf-8")
    assert latest_graph(tmp_path) is None


def test_load_graph_rejects_malformed_model_values(tmp_path: Path):
    path = tmp_path / "graph.json"
    path.write_text(
        json.dumps(_valid_graph(nodes=[{"id": "bad", "label": 42}])),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="label"):
        load_graph(path)


def test_public_celery_task_accepts_no_path_or_model_overrides():
    assert list(inspect.signature(getattr(task.build_hfl_knowledge_graph, "run")).parameters) == []


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


def test_snapshot_keeps_open_corpus_when_path_is_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _write_entry(corpus, what="Safe source.")
    external = tmp_path / "external"
    external.mkdir()
    _write_entry(external, what="Unintended source.")
    staging = tmp_path / "staging"
    staging.mkdir()
    real_listdir = task.os.listdir

    def replace_after_list(descriptor):
        names = real_listdir(descriptor)
        corpus.rename(tmp_path / "original-corpus")
        corpus.symlink_to(external, target_is_directory=True)
        return names

    monkeypatch.setattr(task.os, "listdir", replace_after_list)

    copied = task._snapshot_corpus(corpus.resolve(), staging, 1)

    assert copied == ["2026-07-01.md"]
    text = (staging / copied[0]).read_text(encoding="utf-8")
    assert "Safe source." in text
    assert "Unintended source." not in text


def test_build_rejects_symlinked_corpus_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    outside = tmp_path / "private.md"
    outside.write_text("private source", encoding="utf-8")
    (corpus / "2026-07-01.md").symlink_to(outside)
    monkeypatch.setenv("HARQIS_HFL_GRAPH_ENABLE", "1")
    monkeypatch.setattr(task, "_graphify_path", lambda: "/venv/bin/graphify")
    monkeypatch.setattr(task.subprocess, "run", lambda *a, **k: pytest.fail("must not run"))

    result = task.build_hfl_knowledge_graph_impl(corpus_dir_override=str(corpus))

    assert result["reason"] == "unsafe_corpus_file"


def test_build_rejects_symlinked_output_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    corpus = tmp_path / "corpus"
    _write_entry(corpus)
    target = tmp_path / "target"
    target.mkdir()
    output_link = tmp_path / "graphs"
    output_link.symlink_to(target, target_is_directory=True)
    monkeypatch.setenv("HARQIS_HFL_GRAPH_ENABLE", "1")
    monkeypatch.setattr(task, "_graphify_path", lambda: "/venv/bin/graphify")
    monkeypatch.setattr(task.subprocess, "run", lambda *a, **k: pytest.fail("must not run"))

    result = task.build_hfl_knowledge_graph_impl(
        corpus_dir_override=str(corpus), output_root_override=str(output_link)
    )

    assert result["reason"] == "unsafe_output_root"


def test_build_rejects_dangling_output_root_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    corpus = tmp_path / "corpus"
    _write_entry(corpus)
    output_link = tmp_path / "graphs"
    output_link.symlink_to(tmp_path / "missing-target", target_is_directory=True)
    monkeypatch.setenv("HARQIS_HFL_GRAPH_ENABLE", "1")
    monkeypatch.setattr(task, "_graphify_path", lambda: "/venv/bin/graphify")
    monkeypatch.setattr(task.subprocess, "run", lambda *a, **k: pytest.fail("must not run"))

    result = task.build_hfl_knowledge_graph_impl(
        corpus_dir_override=str(corpus), output_root_override=str(output_link)
    )

    assert result["reason"] == "unsafe_output_root"
    assert not (tmp_path / "missing-target").exists()


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
    assert Path(result["deterministic_graph_json"]).is_file()
    assert Path(result["semantic_graph_json"]).is_file()
    assert (Path(result["out_dir"]) / "SUCCESS.json").is_file()
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
    assert "stderr" not in result


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


def test_failed_rebuild_preserves_previous_verified_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    corpus = tmp_path / "corpus"
    output = tmp_path / "out"
    _write_entry(corpus)
    monkeypatch.setenv("HARQIS_HFL_GRAPH_ENABLE", "1")
    monkeypatch.setattr(task, "_graphify_path", lambda: "/venv/bin/graphify")
    monkeypatch.setattr(task, "_index_summary", lambda **kwargs: None)

    def success(argv, **kwargs):
        _artifact_set(Path(argv[argv.index("--out") + 1]))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(task.subprocess, "run", success)
    first = task.build_hfl_knowledge_graph_impl(
        corpus_dir_override=str(corpus), output_root_override=str(output)
    )
    first_graph = Path(first["graph_json"])
    monkeypatch.setattr(
        task.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired(a[0], 2)),
    )

    second = task.build_hfl_knowledge_graph_impl(
        corpus_dir_override=str(corpus), output_root_override=str(output)
    )

    assert second["reason"] == "timeout"
    assert latest_graph(output) == first_graph
    assert first_graph.is_file()


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


def test_graph_query_returns_unavailable_on_filesystem_failure(monkeypatch: pytest.MonkeyPatch):
    from workflows.hfl import mcp as hfl_mcp

    monkeypatch.setattr(hfl_mcp, "latest_graph", lambda root: (_ for _ in ()).throw(OSError("gone")))

    result = hfl_mcp.memory_graph_query_data("oauth")

    assert result["found"] is False
    assert result["error"] == "graph unavailable"


def test_graph_query_returns_unavailable_on_output_root_symlink_loop(
    monkeypatch: pytest.MonkeyPatch,
):
    from workflows.hfl import mcp as hfl_mcp

    monkeypatch.setattr(
        hfl_mcp,
        "_graph_output_root",
        lambda: (_ for _ in ()).throw(RuntimeError("symlink loop")),
    )

    result = hfl_mcp.memory_graph_query_data("oauth")

    assert result["found"] is False
    assert result["error"] == "graph unavailable"


def test_read_only_graph_query_uses_latest_verified_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from workflows.hfl import mcp as hfl_mcp

    graph_dir = tmp_path / "2026-W27" / GENERATION
    graph_path = write_verified_graph(
        graph_dir,
        _valid_graph(
            nodes=[
                {"id": "entry:1", "label": "Plaud OAuth incident"},
                {"id": "lesson:1", "label": "OAuth recovery pattern"},
            ],
            links=[
                {"source": "entry:1", "target": "lesson:1", "relation": "demonstrates"}
            ],
        ),
    )
    monkeypatch.setenv("HFL_GRAPH_OUTPUT_ROOT", str(tmp_path))

    result = hfl_mcp.memory_graph_query_data("Plaud recovery", depth=2, limit=10)

    assert result["found"] is True
    assert result["graph"] == str(graph_path)
    assert any("demonstrates" in line for line in result["explanations"])
