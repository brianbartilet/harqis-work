from datetime import datetime

from modules.hfl_corpus import corpus as corpus_module
from modules.hfl_corpus.corpus import CorpusDocument, CorpusIndex, build_tree, search_documents
from services.safe_paths import (
    allowed_reference_roots,
    load_download_token,
    resolve_reference,
)


def _document(path, *, tags=("debugging",), text="root cause story"):
    return CorpusDocument(
        relative_path=path,
        path=None,
        name=path.rsplit("/", 1)[-1],
        text=text,
        created_at=datetime(2026, 7, 10),
        updated_at=datetime(2026, 7, 12),
        tags=tags,
        references=(),
        excerpt=text,
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
    assert documents[0].references == ("https://example.com/source",)


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
