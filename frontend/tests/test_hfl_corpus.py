from datetime import datetime

import httpx

from modules.hfl_corpus import corpus as corpus_module
from modules.hfl_corpus.corpus import (
    CorpusDocument,
    CorpusIndex,
    build_tree,
    common_tags,
    format_hfl_markdown,
    search_documents,
)
from services.markdown import render_markdown
from services.safe_paths import (
    allowed_reference_roots,
    load_download_token,
    resolve_reference,
)


def _document(
    path,
    *,
    tags=("debugging",),
    tag_counts=None,
    entry_count=1,
    references=(),
    text="root cause story",
):
    return CorpusDocument(
        relative_path=path,
        path=None,
        name=path.rsplit("/", 1)[-1],
        text=text,
        created_at=datetime(2026, 7, 10),
        updated_at=datetime(2026, 7, 12),
        tags=tags,
        references=references,
        excerpt=text,
        tag_counts=tag_counts or tuple((tag, 1) for tag in tags),
        entry_count=entry_count,
    )


def test_recursive_index_extracts_dates_tags_and_references(tmp_path, monkeypatch):
    nested = tmp_path / "time-capsules"
    nested.mkdir()
    source = nested / "2026-07-10.md"
    source.write_text(
        "## 2026-07-10 09:30\n"
        "Moment:          Fixed a hard bug\n"
        "What happened:   Found the root cause\n"
        "Why it stayed:   Useful lesson\n"
        "Possible use:    Retrospective\n"
        "Tags:            #debugging #root-cause\n"
        "References:\n                 - https://example.com/source\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(corpus_module, "resolve_corpus_root", lambda: tmp_path)

    documents = CorpusIndex(ttl_seconds=0).documents(force=True)

    assert len(documents) == 1
    assert documents[0].relative_path == "time-capsules/2026-07-10.md"
    assert documents[0].created_at == datetime(2026, 7, 10, 9, 30)
    assert "debugging" in documents[0].tags
    assert documents[0].tag_counts == (("debugging", 1), ("root-cause", 1))
    assert documents[0].entry_count == 1
    assert documents[0].references == ("https://example.com/source",)


def test_recursive_index_ranks_top_10_tags_by_entry_count(tmp_path, monkeypatch):
    source = tmp_path / "2026-07-10.md"
    entries = []
    for index in range(12):
        repeated = " #frequent" if index < 5 else ""
        entries.append(
            f"## 2026-07-10 {index:02d}:00\n"
            f"Moment: Entry {index}\n"
            f"Tags: #tag-{index:02d}{repeated}\n"
        )
    source.write_text("\n".join(entries), encoding="utf-8")
    monkeypatch.setattr(corpus_module, "resolve_corpus_root", lambda: tmp_path)

    document = CorpusIndex(ttl_seconds=0).documents(force=True)[0]

    assert document.entry_count == 12
    assert len(document.tag_counts) == 10
    assert document.tag_counts[0] == ("frequent", 5)
    assert document.tag_counts[-1] == ("tag-08", 1)


def test_recursive_index_counts_every_level_two_markdown_header(
    tmp_path, monkeypatch
):
    source = tmp_path / "2026-07-10.md"
    source.write_text(
        "# Daily log\n"
        "## First entry\nMoment: One\n"
        "### Entry detail\n"
        "## Second entry\nMoment: Two\n"
        "## Third entry\nMoment: Three\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(corpus_module, "resolve_corpus_root", lambda: tmp_path)

    document = CorpusIndex(ttl_seconds=0).documents(force=True)[0]

    assert document.entry_count == 3


def test_search_combines_text_partial_tags_and_dates():
    matching = _document("2026-07-10.md")
    other = _document(
        "2026-06-01.md",
        tags=("career",),
        text="a different moment",
    )

    results = search_documents(
        (matching, other),
        query="root #debug",
        created_from="2026-07-01",
        updated_to="2026-07-20",
    )

    assert results == [matching]


def test_tree_keeps_nested_directories():
    tree = build_tree((_document("capsules/2026/week.md"),))

    assert tree["directories"][0]["name"] == "capsules"
    assert tree["directories"][0]["directories"][0]["name"] == "2026"


def test_common_tags_are_ranked_by_document_count():
    documents = (
        _document("one.md", tags=("career", "debugging")),
        _document("two.md", tags=("debugging", "root-cause")),
    )

    assert common_tags(documents) == [
        ("debugging", 2),
        ("career", 1),
        ("root-cause", 1),
    ]


def test_hfl_markdown_formatting_bolds_fields_and_normalizes_references():
    source = (
        "## 2026-07-10 09:30\n"
        "Moment:          Fixed a difficult issue\n"
        "What happened:   Found the root cause\n"
        "Why it stayed:   Reusable lesson\n"
        "Possible use:    Retrospective\n"
        "Tags:            #debugging\n"
        "References:\n"
        "                 - https://example.com/source\n"
    )

    formatted = format_hfl_markdown(source)
    rendered = str(render_markdown(formatted))

    assert "**Moment:** Fixed a difficult issue\n\n" in formatted
    assert "**Tags:** #debugging\n\n" in formatted
    assert "**References:**\n\n- https://example.com/source" in formatted
    assert "<strong>Moment:</strong> Fixed a difficult issue" in rendered
    assert "<strong>References:</strong>" in rendered
    assert "<li><a href=" in rendered


def test_reference_downloads_are_signed_and_root_limited(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    document = corpus / "entry.md"
    document.write_text("entry", encoding="utf-8")
    artifact = corpus / "artifact.txt"
    artifact.write_text("artifact", encoding="utf-8")

    reference = resolve_reference(
        "artifact.txt", source_document=document, corpus_root=corpus
    )
    file_uri_reference = resolve_reference(
        artifact.as_uri(), source_document=document, corpus_root=corpus
    )

    assert reference.kind == "download"
    assert file_uri_reference.kind == "download"
    token = reference.href.split("/")[-2]
    assert load_download_token(token, allowed_reference_roots(corpus)) == artifact.resolve()


def test_external_and_outside_references_are_classified(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    document = corpus / "entry.md"
    document.write_text("entry", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")

    external = resolve_reference(
        "https://example.com", source_document=document, corpus_root=corpus
    )
    blocked = resolve_reference(
        str(outside), source_document=document, corpus_root=corpus
    )

    assert external.kind == "external"
    assert blocked.kind == "blocked"
    assert blocked.reason == "outside allowed roots"


def test_tag_cloud_links_to_partial_search_without_result_card_tags(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    document = _document("2026-07-10.md", tags=("debugging", "root-cause"))
    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: (document,))
    monkeypatch.setattr(hfl_routes.corpus_index, "get", lambda path: document)

    index_response = authenticated_client.get("/hfl-corpus")
    document_response = authenticated_client.get(
        "/hfl-corpus/document/2026-07-10.md"
    )

    expected = 'href="/hfl-corpus?q=%23debugging"'
    assert expected in index_response.text
    assert expected in document_response.text
    assert "Find corpus entries with matching tags" not in index_response.text
    assert "max-h-24" in index_response.text
    assert "overflow-y-auto" in index_response.text
    assert 'gap-2 overflow-y-auto p-1' in index_response.text
    assert "1 entries" in index_response.text
    assert "root cause story" not in index_response.text
    assert 'title="1 entries in this document"' in index_response.text
    assert index_response.text.index("1 entries</p>") < index_response.text.index(
        'class="mt-2 flex flex-wrap items-center gap-1.5"'
    )


def test_document_orders_entries_before_tags_and_references(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    document = _document(
        "2026-07-10.md",
        tags=("debugging",),
        references=("https://example.com/source",),
    )
    monkeypatch.setattr(hfl_routes.corpus_index, "get", lambda path: document)

    response = authenticated_client.get("/hfl-corpus/document/2026-07-10.md")

    assert response.status_code == 200
    entry_position = response.text.index('class="markdown-body')
    tags_position = response.text.index(">Tags</h2>")
    references_position = response.text.index(">References</h2>")
    assert entry_position < tags_position < references_position
    assert "overflow-wrap: anywhere" in response.text
    assert "word-break: break-word" in response.text


def test_common_tags_defaults_to_top_100():
    documents = tuple(
        _document(f"{index}.md", tags=(f"tag-{index:03d}",))
        for index in range(101)
    )

    tags = common_tags(documents)

    assert len(tags) == 100
    assert tags[0] == ("tag-000", 1)
    assert tags[-1] == ("tag-099", 1)


def test_corpus_search_uses_compact_date_controls(authenticated_client, monkeypatch):
    import modules.hfl_corpus.router as hfl_routes

    document = _document("2026-07-10.md", tags=("debugging",))
    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: (document,))

    response = authenticated_client.get(
        "/hfl-corpus?date_field=updated&date_from=2026-07-13&date_to=2026-07-20"
    )

    assert response.status_code == 200
    assert 'name="date_field"' in response.text
    assert 'name="date_from"' in response.text
    assert 'name="date_to"' in response.text
    assert 'name="created_from"' not in response.text
    assert "if (this.showPicker) this.showPicker()" in response.text
    tags_heading = '<p class="mb-2 text-xs font-medium text-slate-500">Tags</p>'
    assert response.text.index('name="date_field"') < response.text.index(tags_heading)
    assert response.text.index("Search corpus") < response.text.index(tags_heading)
    assert response.text.index(">Reset</a>") < response.text.index(tags_heading)
    assert "#debugging" in response.text
    assert "bg-blue-950/50" in response.text
    assert ">1</span>" in response.text
    assert "0 matches" in response.text


def test_corpus_api_requires_bearer_token(authenticated_client):
    response = authenticated_client.get("/api/hfl/documents")

    assert response.status_code == 401


def test_corpus_api_returns_canonical_documents(authenticated_client, monkeypatch):
    import modules.hfl_corpus.api as hfl_api

    document = _document("2026-07-10.md", tags=("debugging",))
    monkeypatch.setattr(hfl_api.corpus_index, "documents", lambda: (document,))

    response = authenticated_client.get(
        "/api/hfl/documents?q=%23debug",
        headers={"Authorization": "Bearer frontend-test-hfl-api-token"},
    )

    assert response.status_code == 200
    assert response.json()["document_count"] == 1
    assert response.json()["results"][0]["relative_path"] == "2026-07-10.md"
    assert response.json()["results"][0]["entry_count"] == 1
    assert response.json()["results"][0]["tag_counts"] == [["debugging", 1]]


def test_hfl_markdown_formats_canonical_provenance_fields():
    formatted = format_hfl_markdown(
        "## 2026-07-19 09:30\n"
        "Source:          browsing\n"
        "Machine:         windows-work-all\n"
        "Entry ID:        hfl-abc123\n"
        "Moment:          A useful page\n"
    )

    assert "**Source:** browsing" in formatted
    assert "**Machine:** windows-work-all" in formatted
    assert "**Entry ID:** hfl-abc123" in formatted


def test_remote_client_reads_index_without_local_paths(monkeypatch):
    from modules.hfl_corpus.remote import RemoteCorpusClient

    payload = {
        "documents": [{
            "relative_path": "2026-07-19.md",
            "name": "2026-07-19.md",
            "created_at": "2026-07-19T09:30:00",
            "updated_at": "2026-07-19T10:00:00",
            "tags": ["hfl"],
            "excerpt": "A canonical entry",
        }],
        "results": [],
        "total_results": 0,
        "document_count": 1,
        "tag_cloud": [["hfl", 1]],
    }
    monkeypatch.setattr(
        httpx,
        "get",
        lambda url, **kwargs: httpx.Response(
            200,
            json=payload,
            request=httpx.Request("GET", url),
        ),
    )

    result = RemoteCorpusClient("http://canonical:8081", "secret").index(params={})

    assert result["document_count"] == 1
    assert result["documents"][0].path is None
    assert result["documents"][0].relative_path == "2026-07-19.md"


def test_remote_mode_surfaces_failure_without_local_fallback(authenticated_client, monkeypatch):
    import modules.hfl_corpus.router as hfl_routes

    monkeypatch.setattr(hfl_routes, "_uses_remote_corpus", lambda: True)
    monkeypatch.setattr(
        hfl_routes.RemoteCorpusClient,
        "from_settings",
        classmethod(lambda cls: (_ for _ in ()).throw(
            hfl_routes.RemoteCorpusError("canonical host is offline")
        )),
    )
    monkeypatch.setattr(
        hfl_routes.corpus_index,
        "documents",
        lambda: (_ for _ in ()).throw(AssertionError("local fallback used")),
    )

    response = authenticated_client.get("/hfl-corpus")

    assert response.status_code == 200
    assert "Canonical corpus unavailable" in response.text
    assert "canonical host is offline" in response.text
