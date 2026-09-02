import io
import json
import os
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from modules.hfl_corpus import corpus as corpus_module
from modules.hfl_corpus import remote as remote_module
from modules.hfl_corpus.corpus import (
    CorpusDocument,
    CorpusEntry,
    CorpusIndex,
    activity_calendar_years,
    activity_counts,
    activity_day_entries,
    activity_years,
    build_tree,
    common_sources,
    common_tags,
    dated_document_paths,
    format_hfl_markdown,
    search_documents,
)
from services.markdown import render_markdown
from services.safe_paths import (
    ReferenceLink,
    allowed_reference_roots,
    load_download_token,
    make_download_token,
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
    entries=None,
    source="",
):
    if entries is None and entry_count:
        entries = (
            CorpusEntry(
                anchor="hfl-entry-1-test-entry",
                header="Test entry",
                moment="A useful moment",
                what_happened="Something worth remembering",
                tags=tags,
                source=source,
            ),
        )
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
        entries=entries or (),
    )


def test_recursive_index_extracts_dates_tags_and_references(tmp_path, monkeypatch):
    nested = tmp_path / "time-capsules"
    nested.mkdir()
    source = nested / "2026-07-10.md"
    source.write_text(
        "## 2026-07-10 09:30\n"
        "Source:          browsing\n"
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
    assert documents[0].entries[0].moment == "Fixed a hard bug"
    assert documents[0].entries[0].what_happened == "Found the root cause"
    assert documents[0].entries[0].source == "browsing"
    assert documents[0].entries[0].anchor == "hfl-entry-1-2026-07-10-09-30"
    assert documents[0].matching_text_entries("USEFUL LESSON") == documents[0].entries
    assert documents[0].matching_text_entries("useful retrospective") == ()
    assert documents[0].references == ("https://example.com/source",)


def test_entry_previews_skip_markdown_sections_and_never_render_blank():
    entries = corpus_module.parse_entries(
        "## 2026-07-21 20:09\n"
        "Moment:\n"
        "What happened:   ### Request\n"
        "Pull latest and restart the stack\n\n"
        "### Outcome\n"
        "- Pulled the latest changes and restarted successfully.\n"
        "Tags: #hermes\n\n"
        "## 2026-07-21 19:00\n"
        "Tags: #hermes\n"
    )

    assert entries[0].moment == "Pulled the latest changes and restarted successfully."
    assert entries[0].what_happened == "Pulled the latest changes and restarted successfully."
    assert entries[1].moment == "2026-07-21 19:00"
    assert entries[1].what_happened == "2026-07-21 19:00"


def test_entry_previews_read_plain_text_prompt_audit_sections():
    entries = corpus_module.parse_entries(
        "## 2026-07-22 01:10\n"
        "Moment: Git pull latest and restart the stack\n"
        "What happened: Request: Git pull latest and restart the stack\n"
        "Outcome:\n"
        "Pulled and restarted the HARQIS stack.\n"
        "• Branch: main\n"
        "Tags: #prompt-audit\n"
    )

    assert entries[0].what_happened == "Pulled and restarted the HARQIS stack."


def test_recursive_index_ignores_bare_git_hash_references(tmp_path, monkeypatch):
    source = tmp_path / "2026-07-21.md"
    source.write_text(
        "## 2026-07-21 20:09\n"
        "Moment: Restarted frontend\n"
        "References:\n"
        "  - /tmp/audit.json\n"
        "  - b8cf522\n"
        "  - b09033a\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(corpus_module, "resolve_corpus_root", lambda: tmp_path)

    document = CorpusIndex(ttl_seconds=0).documents(force=True)[0]

    assert document.references == ("/tmp/audit.json",)


def test_recursive_index_excludes_hidden_directories(tmp_path, monkeypatch):
    _write_visible = tmp_path / "visible" / "2026-07-10.md"
    _write_visible.parent.mkdir()
    _write_visible.write_text("## 2026-07-10\nMoment: Visible\n", encoding="utf-8")
    hidden = tmp_path / ".migrations" / "2026-06-01.md"
    hidden.parent.mkdir()
    hidden.write_text("## 2026-06-01\nMoment: Hidden\n", encoding="utf-8")
    monkeypatch.setattr(corpus_module, "resolve_corpus_root", lambda: tmp_path)

    documents = CorpusIndex(ttl_seconds=0).documents(force=True)

    assert [document.relative_path for document in documents] == [
        "visible/2026-07-10.md"
    ]


def test_recursive_index_reuses_unchanged_documents_on_refresh(tmp_path, monkeypatch):
    first_path = tmp_path / "a.md"
    second_path = tmp_path / "b.md"
    first_path.write_text("## 2026-07-10\nMoment: A\n", encoding="utf-8")
    second_path.write_text("## 2026-07-11\nMoment: B\n", encoding="utf-8")
    monkeypatch.setattr(corpus_module, "resolve_corpus_root", lambda: tmp_path)
    index = CorpusIndex(ttl_seconds=0)

    initial = index.documents(force=True)
    unchanged = index.documents(force=True)
    first_path.write_text(
        "## 2026-07-10\nMoment: A changed and longer\n", encoding="utf-8"
    )
    refreshed = index.documents(force=True)

    assert unchanged[0] is initial[0]
    assert unchanged[1] is initial[1]
    assert refreshed[0] is not initial[0]
    assert refreshed[1] is initial[1]
    assert "changed and longer" in refreshed[0].text


def _cached_daily_index(tmp_path, monkeypatch):
    source = tmp_path / "2026-08-30.md"
    source.write_text(
        "## 2026-08-30 08:00\nSource: git\nMoment: Existing entry\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(corpus_module, "resolve_corpus_root", lambda: tmp_path)
    index = CorpusIndex(ttl_seconds=3600)
    return source, index, index.documents(force=True)[0]


def _prepend_trello_entry(source, initial):
    source.write_text(
        "## 2026-08-30 15:29\n"
        "Source: trello\n"
        "Moment: Completed checklist item\n\n"
        + initial.text,
        encoding="utf-8",
    )


def _assert_trello_refresh(refreshed, initial):
    assert refreshed is not None
    assert refreshed is not initial
    assert [entry.source for entry in refreshed.entries] == ["trello", "git"]


def test_recursive_index_get_refreshes_external_append_inside_ttl(
    tmp_path, monkeypatch
):
    source, index, initial = _cached_daily_index(tmp_path, monkeypatch)
    _prepend_trello_entry(source, initial)

    _assert_trello_refresh(index.get("2026-08-30.md"), initial)


def test_recursive_index_get_uses_consistent_snapshot_during_refresh(
    tmp_path, monkeypatch
):
    source, index, initial = _cached_daily_index(tmp_path, monkeypatch)
    original_documents = index.documents
    raced = False

    def racing_documents(force=False):
        nonlocal raced
        documents = original_documents(force=force)
        if not force and not raced:
            raced = True
            _prepend_trello_entry(source, initial)
            original_documents(force=True)
        return documents

    monkeypatch.setattr(index, "documents", racing_documents)

    _assert_trello_refresh(index.get("2026-08-30.md"), initial)


def test_recursive_index_get_retries_when_file_changes_after_stat(
    tmp_path, monkeypatch
):
    source, index, initial = _cached_daily_index(tmp_path, monkeypatch)
    original_stat = Path.stat
    raced = False

    def racing_stat(path, *args, **kwargs):
        nonlocal raced
        stat = original_stat(path, *args, **kwargs)
        if path == source and not raced:
            raced = True
            _prepend_trello_entry(source, initial)
        return stat

    monkeypatch.setattr(Path, "stat", racing_stat)

    _assert_trello_refresh(index.get("2026-08-30.md"), initial)


def test_recursive_index_serves_stale_documents_while_refresh_starts(
    tmp_path, monkeypatch
):
    source = tmp_path / "a.md"
    source.write_text(
        "## 2026-07-10\nMoment: Fast cached response\nTags: #performance\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(corpus_module, "resolve_corpus_root", lambda: tmp_path)
    index = CorpusIndex(ttl_seconds=0, stale_while_revalidate=True)
    initial = index.documents(force=True)
    refreshes = []
    monkeypatch.setattr(index, "_refresh_in_background", lambda: refreshes.append(True))

    cached = index.documents()

    assert cached is initial
    assert refreshes == [True]
    assert initial[0].tag_entry_anchors == (("performance", initial[0].entries[0].anchor),)


def test_corpus_view_cache_reuses_query_independent_aggregates(monkeypatch):
    from modules.hfl_corpus import view as view_module

    document = _document("cached.md", tags=("performance",))
    documents = (document,)
    cache = view_module.CorpusViewCache()
    builds = []
    original_build_tree = view_module.build_tree
    monkeypatch.setattr(
        view_module,
        "build_tree",
        lambda items: builds.append(items) or original_build_tree(items),
    )

    first = cache.get(
        documents,
        include_secrets=True,
        secret_tags=("secrets",),
    )
    second = cache.get(
        documents,
        include_secrets=True,
        secret_tags=("secrets",),
    )

    assert second is first
    assert len(builds) == 1

    refreshed = cache.get(
        tuple([document]),
        include_secrets=True,
        secret_tags=("secrets",),
    )
    assert refreshed is not first
    assert len(builds) == 2


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


def test_search_requires_all_partial_tags():
    first = _document("first.md", tags=("jira", "notes"))
    second = _document("second.md", tags=("jira", "testing"))

    results = search_documents((first, second), query="#jir #note")

    assert results == [first]


def test_search_combines_multiple_tags_with_partial_text():
    matching = _document(
        "matching.md",
        tags=("jira", "testing"),
        text="A useful testing topic for the release",
    )
    wrong_text = _document(
        "wrong-text.md",
        tags=("jira", "testing"),
        text="An unrelated release note",
    )
    wrong_tag = _document(
        "wrong-tag.md",
        tags=("jira", "notes"),
        text="A useful testing topic for the release",
    )

    results = search_documents(
        (wrong_text, matching, wrong_tag),
        query="#jira #test testing topic",
    )

    assert results == [matching]


def test_search_can_reverse_created_date_order():
    older = replace(_document("older.md"), created_at=datetime(2026, 7, 1))
    newer = replace(_document("newer.md"), created_at=datetime(2026, 7, 20))

    assert search_documents((older, newer)) == [newer, older]
    assert search_documents((older, newer), sort_order="asc") == [older, newer]


def test_tree_keeps_nested_directories():
    tree = build_tree((_document("capsules/2026/week.md"),))

    assert tree["directories"][0]["name"] == "capsules"
    assert tree["directories"][0]["directories"][0]["name"] == "2026"


def test_corpus_directory_tree_loads_nested_branches_on_demand(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    documents = (
        _document("2026/Jul/one.md"),
        _document("2026/Aug/two.md"),
    )
    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: documents)

    index_response = authenticated_client.get("/hfl-corpus")
    branch_response = authenticated_client.get("/hfl-corpus/tree?path=2026")

    assert index_response.status_code == 200
    assert "hfl-corpus/tree?path=2026" in index_response.text
    assert 'data-tree-file="2026/Jul/one.md"' not in index_response.text
    assert branch_response.status_code == 200
    assert "Jul" in branch_response.text
    assert "Aug" in branch_response.text
    assert "one.md" not in branch_response.text


def test_tree_sorts_named_month_directories_chronologically():
    tree = build_tree(
        (
            _document("2026/Dec/late.md"),
            _document("2026/Apr/spring.md"),
            _document("2026/Jan/early.md"),
            _document("2026/Feb/next.md"),
        )
    )

    months = tree["directories"][0]["directories"]
    assert [month["name"] for month in months] == ["Jan", "Feb", "Apr", "Dec"]


def test_tree_hides_system_directories_even_for_preindexed_documents():
    tree = build_tree(
        (
            _document("visible/entry.md"),
            _document(".migrations/hidden.md"),
            _document("visible/.system/nested-hidden.md"),
        )
    )

    assert [directory["name"] for directory in tree["directories"]] == ["visible"]
    assert tree["directories"][0]["directories"] == []


def test_tree_sorts_named_directories_first_then_numeric_descending():
    same_day = datetime(2026, 7, 10, 9, 0)
    documents = (
        replace(_document("zeta/nested.md"), created_at=datetime(2026, 7, 12)),
        replace(_document("Alpha/nested.md"), created_at=datetime(2026, 7, 1)),
        _document("2024/nested.md"),
        _document("2026/nested.md"),
        _document("2025/nested.md"),
        replace(_document("old.md"), created_at=datetime(2026, 7, 1)),
        replace(_document("new.md"), created_at=datetime(2026, 7, 12)),
        replace(_document("b.md"), created_at=same_day),
        replace(_document("a.md"), created_at=same_day),
    )

    tree = build_tree(documents)

    assert [directory["name"] for directory in tree["directories"]] == [
        "Alpha",
        "zeta",
        "2026",
        "2025",
        "2024",
    ]
    assert [document.name for document in tree["files"]] == [
        "new.md",
        "a.md",
        "b.md",
        "old.md",
    ]


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


def test_hfl_markdown_reference_preview_includes_thumbnail_card_markup():
    source = (
        "## 2026-07-10 09:30\n"
        "References:\n"
        "                 - photo.jpg\n"
    )
    reference = ReferenceLink(
        label="photo.jpg",
        kind="download",
        href="/hfl-corpus/references/token/download",
        source="photo.jpg",
        preview_kind="image",
        preview_url="/hfl-corpus/references/token/preview",
        media_url="/hfl-corpus/references/token/media",
        thumbnail_url="/hfl-corpus/references/token/thumbnail",
    )

    rendered = str(render_markdown(format_hfl_markdown(source, [reference])))

    assert 'class="corpus-reference-preview"' in rendered
    assert 'class="corpus-reference-thumbnail"' in rendered
    assert '<img src="/hfl-corpus/references/token/thumbnail" alt="">' in rendered
    assert '<span class="corpus-reference-action">Open viewer</span>' in rendered


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


def test_reference_rendering_links_safe_files_and_omits_blocked_items(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    document = corpus / "entry.md"
    document.write_text("entry", encoding="utf-8")
    artifact = corpus / "17-03-2026 [LOGS] Daily Scratchboard.md"
    artifact.write_text("notes", encoding="utf-8")
    outside = tmp_path / "private.txt"
    outside.write_text("private", encoding="utf-8")
    source = (
        "## 2026-03-17 09:30\n"
        "Moment:          Linked notes\n"
        "References:\n"
        f"                 - {artifact}\n"
        f"                 - {outside}\n"
        "                 - http://harqis-ones-mac-mini:8081/dashboard\n"
        "                 - https://example.com/source\n"
    )
    links = [
        resolve_reference(
            reference,
            source_document=document,
            corpus_root=corpus,
        )
        for reference in (
            str(artifact),
            str(outside),
            "http://harqis-ones-mac-mini:8081/dashboard",
            "https://example.com/source",
        )
    ]

    rendered = str(render_markdown(format_hfl_markdown(source, links)))

    assert str(artifact) in rendered
    assert links[0].href in rendered
    assert "17-03-2026 [LOGS] Daily Scratchboard.md" in rendered
    assert str(outside) not in rendered
    assert "outside allowed roots" not in rendered
    assert "Unavailable:" not in rendered
    assert "http://harqis-ones-mac-mini:8081/dashboard" not in rendered
    assert 'href="https://example.com/source"' in rendered


def test_insecure_http_and_forged_outside_download_are_blocked(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    document = corpus / "entry.md"
    document.write_text("entry", encoding="utf-8")
    outside = tmp_path / "private.txt"
    outside.write_text("private", encoding="utf-8")

    insecure = resolve_reference(
        "HTTP://internal.example/file",
        source_document=document,
        corpus_root=corpus,
    )
    forged = make_download_token(outside)

    assert insecure.kind == "blocked"
    assert insecure.reason == "insecure http"
    assert load_download_token(forged, allowed_reference_roots(corpus)) is None


def test_symlink_and_relative_traversal_cannot_escape_allowed_root(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    document = corpus / "entry.md"
    document.write_text("entry", encoding="utf-8")
    outside = tmp_path / "private.txt"
    outside.write_text("private", encoding="utf-8")
    linked = corpus / "linked-private.txt"
    try:
        linked.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable on this host")

    symlink_reference = resolve_reference(
        linked.name,
        source_document=document,
        corpus_root=corpus,
    )
    traversal_reference = resolve_reference(
        "../private.txt",
        source_document=document,
        corpus_root=corpus,
    )

    assert symlink_reference.kind == "blocked"
    assert symlink_reference.reason == "outside allowed roots"
    assert traversal_reference.kind == "blocked"
    assert traversal_reference.reason == "outside allowed roots"


def test_malformed_and_credential_bearing_references_fail_closed(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    document = corpus / "entry.md"
    document.write_text("entry", encoding="utf-8")

    malformed = resolve_reference(
        "https://[invalid",
        source_document=document,
        corpus_root=corpus,
    )
    credentialed = resolve_reference(
        "https://user:password@example.com/private",
        source_document=document,
        corpus_root=corpus,
    )

    assert malformed.kind == "blocked"
    assert malformed.reason == "invalid"
    assert credentialed.kind == "blocked"
    assert credentialed.reason == "embedded credentials"


def test_index_tag_cloud_links_to_partial_search_and_document_uses_navigator(
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
    assert expected not in document_response.text
    assert 'data-tag="debugging"' in document_response.text
    assert "Find corpus entries with matching tags" not in index_response.text
    tag_cloud = index_response.text.split("<details data-tag-cloud", 1)[1].split(
        "</details>", 1
    )[0]
    assert " open" not in tag_cloud.split(">", 1)[0]
    assert "max-h-56" in tag_cloud
    assert "overflow-y-auto" in index_response.text
    assert 'flex max-h-56 flex-wrap gap-2 overflow-y-auto p-1' in index_response.text
    assert "1 entries" in index_response.text
    assert "root cause story" not in index_response.text
    assert 'title="1 entries in this document"' in index_response.text
    assert index_response.text.index("1 entries</p>") < index_response.text.index(
        'class="mt-2 flex flex-wrap items-center gap-1.5"'
    )


def test_document_orders_entries_before_floating_navigator_without_reference_summary(
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
    navigator_position = response.text.index('aria-label="Document entry navigator"')
    assert entry_position < navigator_position
    assert ">References</h2>" not in response.text
    assert ".markdown-body p, .markdown-body li" in response.text
    assert "overflow-wrap: anywhere" in response.text
    assert "word-break: break-word" in response.text
    assert 'data-document-header class="corpus-document-header"' in response.text
    assert "position: sticky" in response.text
    assert "top: var(--corpus-document-header-offset)" in response.text
    assert ".corpus-document-header::before" in response.text
    assert "height: var(--corpus-document-header-offset)" in response.text
    assert ".corpus-document-header.is-editing" in response.text
    assert "scroll-margin-top:6rem" in response.text
    assert "textarea.focus({ preventScroll: true })" in response.text
    assert "editor.scrollIntoView({ block: 'start' })" in response.text


def test_document_floating_navigator_can_be_minimized(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    document = _document("2026-07-10.md", tags=("debugging",))
    monkeypatch.setattr(hfl_routes.corpus_index, "get", lambda path: document)

    response = authenticated_client.get("/hfl-corpus/document/2026-07-10.md")

    assert response.status_code == 200
    assert 'data-navigator-toggle aria-expanded="true"' in response.text
    assert 'id="navigator-content" data-navigator-content class="mt-3"' in response.text
    assert "Search &amp; navigate" in response.text
    assert "setNavigatorCollapsed" in response.text
    assert "hfl-corpus-document-navigator-collapsed" in response.text
    assert "navigator-collapsed" in response.text


def test_document_tag_navigator_shows_counts_in_descending_order(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    document = _document(
        "2026-07-10.md",
        tags=("popular", "rare", "steady"),
        tag_counts=(("popular", 4), ("steady", 2), ("rare", 1)),
    )
    monkeypatch.setattr(hfl_routes.corpus_index, "get", lambda path: document)

    response = authenticated_client.get("/hfl-corpus/document/2026-07-10.md")

    assert response.status_code == 200
    popular = response.text.index('data-tag="popular"')
    steady = response.text.index('data-tag="steady"')
    rare = response.text.index('data-tag="rare"')
    assert popular < steady < rare
    assert '#popular <span class="text-blue-500">4</span>' in response.text
    assert '#steady <span class="text-blue-500">2</span>' in response.text
    assert '#rare <span class="text-blue-500">1</span>' in response.text


def test_document_navigator_collapses_sources_before_tags_with_counts(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    entries = (
        CorpusEntry(
            anchor="hfl-entry-1-browser",
            header="Browser one",
            moment="One",
            what_happened="First browsing entry",
            tags=("research",),
            source="browsing",
        ),
        CorpusEntry(
            anchor="hfl-entry-2-browser",
            header="Browser two",
            moment="Two",
            what_happened="Second browsing entry",
            tags=("research",),
            source="Browsing",
        ),
        CorpusEntry(
            anchor="hfl-entry-3-manual",
            header="Manual",
            moment="Three",
            what_happened="Manual entry",
            tags=("notes",),
            source="manual-entry",
        ),
        CorpusEntry(
            anchor="hfl-entry-4-legacy",
            header="Legacy",
            moment="Four",
            what_happened="No source entry",
            tags=("notes",),
            source="",
        ),
    )
    document = _document(
        "2026-07-10.md",
        tags=("research", "notes"),
        entry_count=4,
        entries=entries,
    )
    monkeypatch.setattr(hfl_routes.corpus_index, "get", lambda path: document)

    response = authenticated_client.get("/hfl-corpus/document/2026-07-10.md")

    assert response.status_code == 200
    source_section = response.text.split(
        '<details data-filter-section="source"', 1
    )[1].split("</details>", 1)[0]
    tag_section = response.text.split(
        '<details data-filter-section="tag"', 1
    )[1].split("</details>", 1)[0]
    assert " open" in source_section.split(">", 1)[0]
    assert " open" not in tag_section.split(">", 1)[0]
    assert response.text.index(">Document source</span>") < response.text.index(
        ">Document tags</span>"
    )
    assert 'data-source="browsing"' in source_section
    assert '>browsing <span class="text-blue-500">2</span>' in source_section
    assert '>manual-entry <span class="text-blue-500">1</span>' in source_section
    assert 'data-anchors="hfl-entry-1-browser,hfl-entry-2-browser"' in source_section
    assert "Legacy" not in source_section


def test_document_navigator_uses_one_deselectable_source_or_tag_selection(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    entries = (
        CorpusEntry(
            anchor="hfl-entry-1-browser",
            header="Browser",
            moment="One",
            what_happened="Browser entry",
            tags=("research",),
            source="browsing",
        ),
    )
    document = _document(
        "2026-07-10.md",
        tags=("research",),
        entry_count=1,
        entries=entries,
    )
    monkeypatch.setattr(hfl_routes.corpus_index, "get", lambda path: document)

    response = authenticated_client.get(
        "/hfl-corpus/document/2026-07-10.md?source=BROWSING"
    )

    assert response.status_code == 200
    assert 'data-selected-source="browsing"' in response.text
    assert 'data-selected-tag=""' in response.text
    assert ">Select a source or tag</span>" in response.text
    assert "if (currentButton === button)" in response.text
    assert "clearSelection();" in response.text
    assert "styleButtons(button);" in response.text
    assert "url.searchParams.delete('tag')" in response.text
    assert "url.searchParams.delete('source')" in response.text
    assert "url.searchParams.set(currentKind, currentValue)" in response.text
    assert "initial.closest('details')?.setAttribute('open', '')" in response.text


def test_document_navigator_places_go_to_end_beside_back_to_top(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    document = _document("2026-07-10.md")
    monkeypatch.setattr(hfl_routes.corpus_index, "get", lambda path: document)

    response = authenticated_client.get("/hfl-corpus/document/2026-07-10.md")

    assert response.status_code == 200
    assert 'id="document-end"' in response.text
    assert 'id="navigator-go-to-end"' in response.text
    assert response.text.index('id="navigator-go-to-end"') < response.text.index(
        'id="navigator-back-to-top"'
    )
    assert "document.getElementById('document-end')?.scrollIntoView" in response.text


def test_document_renders_downloads_inline_without_reference_summary(
    authenticated_client, monkeypatch, tmp_path
):
    import modules.hfl_corpus.router as hfl_routes

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    artifact = corpus / "17-03-2026 [LOGS] Daily Scratchboard.md"
    artifact.write_text("notes", encoding="utf-8")
    source_path = corpus / "2026-03-17.md"
    text = (
        "## 2026-03-17 09:30\n"
        "Moment:          Linked notes\n"
        "Tags:            #notes\n"
        "References:\n"
        f"                 - {artifact}\n"
    )
    source_path.write_text(text, encoding="utf-8")
    document = replace(
        _document(
            "2026-03-17.md",
            tags=("notes",),
            references=(str(artifact),),
            text=text,
        ),
        path=source_path,
    )
    monkeypatch.setattr(hfl_routes.corpus_index, "get", lambda path: document)
    monkeypatch.setattr(hfl_routes, "resolve_corpus_root", lambda: corpus)

    response = authenticated_client.get("/hfl-corpus/document/2026-03-17.md")

    assert response.status_code == 200
    assert response.text.count(str(artifact)) == 1
    assert 'data-reference-preview=""' in response.text
    assert 'data-preview-kind="markdown"' in response.text
    assert "/preview" in response.text
    assert "/media" in response.text
    assert ">References</h2>" not in response.text
    assert "Unavailable:" not in response.text


def test_document_page_offers_plaintext_edit_save_and_discard(
    authenticated_client, monkeypatch, tmp_path
):
    import modules.hfl_corpus.router as hfl_routes

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    source = corpus / "2026-07-10.md"
    source.write_text("# Before\n", encoding="utf-8")
    document = replace(
        _document("2026-07-10.md", text="# Before\n"),
        path=source,
    )
    monkeypatch.setattr(hfl_routes.corpus_index, "get", lambda path: document)
    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda force=False: (document,))
    monkeypatch.setattr(hfl_routes, "resolve_corpus_root", lambda: corpus)

    page = authenticated_client.get("/hfl-corpus/document/2026-07-10.md")
    saved = authenticated_client.post(
        "/hfl-corpus/document/2026-07-10.md",
        json={"text": "# After\n\nEdited safely.\n"},
    )

    assert page.status_code == 200
    assert 'data-document-edit-open' in page.text
    assert 'data-document-edit-text' in page.text
    assert '>Save changes</button>' in page.text
    assert '>Discard</button>' in page.text
    assert saved.status_code == 200
    assert saved.json()["updated"] is True
    assert source.read_text(encoding="utf-8") == "# After\n\nEdited safely.\n"


def test_corpus_document_update_rejects_stale_revision(
    authenticated_client, monkeypatch, tmp_path
):
    import modules.hfl_corpus.router as hfl_routes

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    source = corpus / "2026-07-10.md"
    source.write_text("# Before\n", encoding="utf-8")
    expected = datetime.fromtimestamp(source.stat().st_mtime).isoformat()
    document = replace(
        _document("2026-07-10.md", text="# Before\n"),
        path=source,
    )
    source.write_text("# Concurrent edit\n", encoding="utf-8")
    stat = source.stat()
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    monkeypatch.setattr(hfl_routes.corpus_index, "get", lambda path: document)
    monkeypatch.setattr(hfl_routes, "resolve_corpus_root", lambda: corpus)

    response = authenticated_client.post(
        "/hfl-corpus/document/2026-07-10.md",
        json={
            "text": "# Stale replacement\n",
            "expected_updated_at": expected,
        },
    )

    assert response.status_code == 409
    assert "changed after review" in response.json()["detail"]
    assert source.read_text(encoding="utf-8") == "# Concurrent edit\n"


def test_corpus_text_reference_preview_is_authenticated_and_sanitized(
    authenticated_client, monkeypatch, tmp_path
):
    import modules.hfl_corpus.router as hfl_routes

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    artifact = corpus / "notes.md"
    artifact.write_text("# Notes\n<script>alert('no')</script>\nSafe text", encoding="utf-8")
    token = make_download_token(artifact)
    monkeypatch.setattr(hfl_routes, "resolve_corpus_root", lambda: corpus)

    response = authenticated_client.get(
        f"/hfl-corpus/references/{token}/preview"
    )

    assert response.status_code == 200
    assert '<div class="viewer-document markdown-body">' in response.text
    assert "<h1>Notes</h1>" in response.text
    assert "<script>" not in response.text
    assert "Safe text" in response.text


def test_reference_download_route_requires_authenticated_session(tmp_path):
    from fastapi.testclient import TestClient
    from main import app

    artifact = tmp_path / "artifact.txt"
    artifact.write_text("private", encoding="utf-8")
    token = make_download_token(artifact)

    with TestClient(app) as client:
        response = client.get(
            f"/hfl-corpus/references/{token}/download",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_reference_preview_route_requires_authenticated_session(tmp_path):
    from fastapi.testclient import TestClient
    from main import app

    artifact = tmp_path / "artifact.txt"
    artifact.write_text("private", encoding="utf-8")
    token = make_download_token(artifact)

    with TestClient(app) as client:
        response = client.get(
            f"/hfl-corpus/references/{token}/preview",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_common_tags_defaults_to_top_100():
    documents = tuple(
        _document(f"{index}.md", tags=(f"tag-{index:03d}",))
        for index in range(101)
    )

    tags = common_tags(documents)

    assert len(tags) == 100
    assert tags[0] == ("tag-000", 1)
    assert tags[-1] == ("tag-099", 1)


def test_common_sources_are_distinct_trimmed_and_alphabetical():
    documents = (
        _document("manual.md", source="manual-entry"),
        _document("browse.md", source="Browsing"),
        _document("browse-again.md", source="browsing"),
        _document("legacy.md", source=""),
    )

    assert common_sources(documents) == ["Browsing", "manual-entry"]


def test_source_filter_requires_query_and_source_on_the_same_entry():
    browsing = CorpusEntry(
        anchor="browse",
        header="Browse",
        moment="Release research",
        what_happened="Read release notes",
        tags=("research",),
        source="browsing",
        text="Release research",
    )
    manual = CorpusEntry(
        anchor="manual",
        header="Manual",
        moment="Unrelated thought",
        what_happened="Wrote a note",
        tags=("notes",),
        source="manual-entry",
        text="Unrelated thought",
    )
    matching = _document(
        "matching.md",
        tags=("research", "notes"),
        text="Release research and unrelated thought",
        entries=(browsing, manual),
    )

    assert search_documents((matching,), source="browsing") == [matching]
    assert search_documents(
        (matching,),
        source="browsing",
        query="#research release",
    ) == [matching]
    assert search_documents(
        (matching,),
        source="browsing",
        query="#notes unrelated",
    ) == []
    assert matching.matching_entries((), "", "BROWSING") == (browsing,)


def test_activity_counts_and_entry_date_search_use_occurrence_headers():
    first = CorpusEntry(
        anchor="first",
        header="2026-01-05 09:30",
        moment="First memory",
        what_happened="Worked on the corpus",
        tags=("work",),
        source="notes",
        text="First corpus memory",
    )
    second = CorpusEntry(
        anchor="second",
        header="2026-01-05 18:00:00",
        moment="Second memory",
        what_happened="Reviewed the corpus",
        tags=("work",),
        source="git",
        text="Second corpus memory",
    )
    historical = CorpusEntry(
        anchor="historical",
        header="2025-12-31",
        moment="Historical memory",
        what_happened="Closed the year",
        tags=("personal",),
        source="notes",
        text="Historical memory",
    )
    malformed = CorpusEntry(
        anchor="malformed",
        header="Undated entry",
        moment="Undated memory",
        what_happened="Missing a canonical date",
        tags=("work",),
        source="notes",
        text="Undated memory",
    )
    document = _document(
        "mixed.md",
        tags=("work", "personal"),
        entry_count=4,
        entries=(first, second, historical, malformed),
    )

    assert activity_years((document,)) == (2026, 2025)
    assert activity_counts((document,), year=2026) == {"2026-01-05": 2}
    assert activity_counts(
        (document,), year=2026, query="#work", source="notes"
    ) == {"2026-01-05": 1}
    assert search_documents(
        (document,),
        date_field="entry",
        date_from="2026-01-05",
        date_to="2026-01-05",
    ) == [document]
    assert search_documents(
        (document,),
        date_field="entry",
        date_from="2026-01-06",
        date_to="2026-01-06",
    ) == []


def test_activity_counts_all_entries_in_a_canonical_daily_document():
    entries = tuple(
        CorpusEntry(
            anchor=f"entry-{index}",
            header=("2026-08-20 09:00" if index < 3 else f"Imported item {index}"),
            moment=f"Memory {index}",
            what_happened=f"Memory {index}",
            tags=("work",),
            source="notes",
            text=f"Memory {index}",
        )
        for index in range(72)
    )
    document = _document(
        "2026-08-20.md",
        tags=("work",),
        entry_count=72,
        entries=entries,
    )

    assert activity_counts((document,), year=2026) == {"2026-08-20": 72}
    assert activity_counts(
        (document,), year=2026, query="#work", source="notes"
    ) == {"2026-08-20": 72}


def test_activity_day_entries_include_noncanonical_historical_documents():
    historical = CorpusEntry(
        anchor="historical-entry",
        header="2023-01-04 09:30",
        moment="Historical memory",
        what_happened="An older event",
        tags=("history",),
        source="notes",
    )
    other_day = CorpusEntry(
        anchor="other-entry",
        header="2023-01-05 09:30",
        moment="Other memory",
        what_happened="Another event",
        tags=("history",),
        source="notes",
    )
    archive = _document(
        "archive/import.md",
        tags=("history",),
        entry_count=2,
        entries=(historical, other_day),
    )

    assert activity_day_entries(
        (archive,), activity_day=date(2023, 1, 4)
    ) == (("archive/import.md", historical),)
    assert activity_day_entries(
        (archive,),
        activity_day=date(2023, 1, 4),
        query="#missing",
    ) == ()


def test_activity_calendar_includes_twenty_years_and_canonical_date_documents():
    documents = (
        _document("2026-08-24.md"),
        _document("archive/2025-01-02.md"),
        _document("notes.md"),
    )

    years = activity_calendar_years(today=date(2026, 8, 30))

    assert len(years) == 20
    assert years[0] == 2026
    assert years[-1] == 2007
    assert dated_document_paths(documents) == {
        "2026-08-24": "2026-08-24.md",
    }


def test_activity_heatmap_covers_leap_day_and_iso_week_boundaries():
    import modules.hfl_corpus.router as hfl_routes

    heatmap = hfl_routes._activity_heatmap(
        2020,
        {"2020-02-29": 3},
        selected_day=datetime(2020, 2, 29).date(),
    )
    days = [
        day
        for week in heatmap["weeks"]
        for day in week["days"]
        if day["in_year"]
    ]

    assert len(days) == 366
    assert heatmap["weeks"][0]["week"] == 1
    assert heatmap["weeks"][-1]["week"] == 53
    assert [week["month"] for week in heatmap["weeks"] if week["month"]] == [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]
    leap_day = next(day for day in days if day["date"] == "2020-02-29")
    assert leap_day["count"] == 3
    assert leap_day["selected"] is True

    future = hfl_routes._activity_heatmap(date.today().year + 1, {})
    assert all(
        day["is_future"]
        for week in future["weeks"]
        for day in week["days"]
        if day["in_year"]
    )


def test_activity_heatmap_filters_document_cards_and_is_mobile_traversable(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    matching = _document(
        "2026-08-24.md",
        tags=("work",),
        entry_count=2,
        entries=(
            CorpusEntry(
                anchor="morning",
                header="2026-08-24 09:00",
                moment="Morning work",
                what_happened="Started the work",
                tags=("work",),
                source="notes",
                text="Morning work",
            ),
            CorpusEntry(
                anchor="evening",
                header="2026-08-24 18:30",
                moment="Evening work",
                what_happened="Finished the work",
                tags=("work",),
                source="notes",
                text="Evening work",
            ),
        ),
    )
    other = _document(
        "other.md",
        tags=("personal",),
        entries=(
            CorpusEntry(
                anchor="other",
                header="2025-03-02 12:00",
                moment="Other memory",
                what_happened="Did something else",
                tags=("personal",),
                source="notes",
                text="Other memory",
            ),
        ),
    )
    monkeypatch.setattr(
        hfl_routes.corpus_index,
        "documents",
        lambda: (matching, other),
    )

    response = authenticated_client.get(
        "/hfl-corpus?activity_year=2026&q=%23work&date_field=entry&"
        "date_from=2026-08-24&date_to=2026-08-24"
    )

    assert response.status_code == 200
    assert "data-activity-panel" in response.text
    assert 'class="corpus-header-shell mb-4 shrink-0"' in response.text
    assert 'class="corpus-page-header page-header"' in response.text
    assert ".corpus-page-header .page-header-title { margin-top:.5rem; }" in response.text
    assert ".corpus-page-header .page-header-description { margin-top:.375rem; }" in response.text
    corpus_header = response.text.split('class="corpus-header-shell', 1)[1].split(
        "</div>\n  </div>", 1
    )[0]
    assert "corpus-secrets-control" in corpus_header
    assert "corpus-create-entry" in corpus_header
    assert ".corpus-page-header,.corpus-header-actions { display:contents; }" in response.text
    assert 'data-activity-toggle aria-expanded="true"' in response.text
    assert "data-activity-body" in response.text
    assert 'data-activity-year aria-label="Activity year"' in response.text
    activity_header_actions = response.text.split(
        "data-activity-header-actions", 1
    )[1].split("</div>", 1)[0]
    assert 'data-activity-year aria-label="Activity year"' not in activity_header_actions
    assert "data-activity-toggle" in activity_header_actions
    assert 'data-activity-year-list role="listbox"' in response.text
    assert 'data-activity-year-trigger aria-haspopup="listbox" aria-expanded="false"' in response.text
    assert 'data-activity-year-trigger-value>2026</span>' in response.text
    assert 'activity-year-controls[data-year-menu-open="true"] .activity-year-list' in response.text
    assert "setYearMenuOpen" in response.text
    assert 'data-activity-year-option="2026"' in response.text
    activity_body = response.text.split("data-activity-body", 1)[1].split(
        "data-activity-day-menu", 1
    )[0]
    assert "data-activity-year" in activity_body
    assert "data-activity-year-list" in activity_body
    assert 'data-activity-year aria-label="Activity year"' in activity_body
    year_header = activity_body.split('class="activity-year-controls"', 1)[1].split(
        'class="activity-year-select-wrap"', 1
    )[0]
    assert "Year" in year_header
    assert "data-activity-today>Today</button>" in year_header
    assert "corpus-select-shell" not in response.text
    assert "corpus-select-caret" not in response.text
    assert 'class="activity-year-select corpus-select block"' in response.text
    assert response.text.count('class="corpus-select mt-1.5 block w-full') == 2
    assert "background-position:right .85rem center" in response.text
    assert "grid-template-columns:4.75rem minmax(0,1fr) 11rem" in response.text
    assert '<option value="2026" selected>2026</option>' in response.text
    assert '<option value="2025"' in response.text
    assert 200 < response.text.count('data-activity-day="') <= 366
    assert 'data-activity-year-segment="2026"' in response.text
    assert 'style="--activity-weeks:53" data-activity-year-segment="2026"' in response.text
    assert "overflow-clip-margin:6px" in response.text
    assert "calendarWeekCount" in response.text
    assert "Math.floor((last - first) / 604800000) + 1" in response.text
    assert "Math.round((last - first) / 604800000) + 1" not in response.text
    assert "segment.style.setProperty('--activity-weeks', weekIndex)" in response.text
    assert "activity-year-segment::before" not in response.text
    assert "activity-year-marker" not in response.text
    assert "data-activity-previous-year" in response.text
    assert "data-activity-next-year" in response.text
    assert "activity-coachmark-anchor-next" in response.text
    assert "const updateYearCoachmarks = value =>" in response.text
    assert "nextYearCoachmark.textContent = hasNext ? nextValue : ''" in response.text
    assert "nextYearCoachmark.hidden = !hasNext" in response.text
    assert "new IntersectionObserver" in response.text
    assert "hydrateYear(segment)" in response.text
    assert 'data-activity-day="2026-08-24"' in response.text
    future_cell = response.text.split(
        'data-activity-day="2026-12-31"', 1
    )[1].split(">", 1)[0]
    assert "Future date" in future_cell
    assert 'data-future="true"' in future_cell
    assert "disabled" not in future_cell
    assert 'background:rgba(30,41,59,.58); opacity:.52' in response.text
    assert 'border-color:rgba(71,85,105,.82); opacity:.7' in response.text
    assert "Week 35 · 2 entries" in response.text
    selected_cell = response.text.split(
        'data-activity-day="2026-08-24"', 1
    )[1].split(">", 1)[0]
    assert 'aria-pressed="true"' in selected_cell
    assert '<option value="entry" selected>Entry date</option>' in response.text
    result_cards = response.text.split("data-corpus-results-scroll", 1)[1]
    assert "2026-08-24.md" in result_cards
    assert "other.md" not in result_cards
    assert "ArrowDown: 1" in response.text
    assert "ArrowRight: 7" in response.text
    assert "<span>Tue</span>" in response.text
    assert "<span>Sun</span>" in response.text
    assert "scroll-snap-type:x proximity" in response.text
    assert "target.scrollIntoView({" in response.text
    assert "inline:'center'" in response.text
    assert "overflow-anchor:none" in response.text
    assert "const scrollToDate = async (value, {behavior='', focus=true}={})" in response.text
    assert "rootMargin:'0px 100%'" in response.text
    assert 'data-activity-loaded="true"' in response.text
    assert "const yearLoads = new Map()" in response.text
    assert "yearLoads.has(selectedYear)" in response.text
    assert "`/hfl-corpus/activity-year/${selectedYear}`" in response.text
    assert "hydrateYear(segment, {animate:true})" in response.text
    assert "delay:weekIndex * 11" in response.text
    assert "prefers-reduced-motion: reduce" in response.text
    assert "data-activity-day-menu" in response.text
    assert "data-activity-menu-create" in response.text
    assert "data-activity-menu-pin" in response.text
    assert "data-activity-menu-document" in response.text
    assert "data-activity-menu-matches" in response.text
    assert "data-activity-menu-matches-panel" in response.text
    day_menu = response.text.split('data-activity-day-menu', 1)[1].split("</div>\n    </div>", 1)[0]
    assert day_menu.index("Create entry") < day_menu.index("Show document")
    assert day_menu.index("Show document") < day_menu.index("Matching entries")
    assert "const hasDocument = !isFuture && Boolean(documentUrl)" in response.text
    assert "const canShowMatches = !isFuture" in response.text
    assert "showDocument.setAttribute('aria-disabled', String(!hasDocument))" in response.text
    assert "matchingEntries.disabled = !canShowMatches" in response.text
    assert "if (canShowMatches) matchingEntries.click()" in response.text
    assert "resetMatchingEntries()" in response.text
    assert "matchingContent.dataset.loaded === 'true'" in response.text
    assert "window.htmx?.process(matchingContent)" in response.text
    assert "openDayMenu(button)" in response.text
    assert "createEntry.disabled = isFuture" in response.text
    assert "hfl:create-entry-for-date" in response.text
    assert 'data-document-url="http://testserver/hfl-corpus/document/2026-08-24.md"' in response.text
    assert (
        'data-matches-url="http://testserver/hfl-corpus/day-matches/2026-08-24?'
        in selected_cell
    )
    assert "q=%23work" in selected_cell
    assert "form.elements.time.value = selectedDate ? ''" in response.text
    assert "successUrl.searchParams.set('date_from', savedActivityDate)" in response.text
    assert "const centerDateForYear = value =>" in response.text
    assert "if (value === timelineData.end.slice(0, 4)) return timelineData.end" in response.text
    assert "const midpoint = `${value}-07-01`" in response.text
    assert "if (midpoint < timelineData.start) return timelineData.start" in response.text
    assert "if (midpoint > timelineData.calendar_end) return timelineData.calendar_end" in response.text
    assert "await scrollToDate(centerDateForYear(value), {focus:false})" in response.text
    assert "const yearAtViewportCenter = () =>" in response.text
    assert "const distance = center < rect.left ? rect.left - center : center > rect.right ? center - rect.right : 0" in response.text
    assert "const value = yearAtViewportCenter()?.dataset.activityYearSegment" in response.text
    assert "segment.offsetLeft + segment.offsetWidth / 2" not in response.text
    assert "scrollbar-width:none" in response.text
    assert ".activity-grid { display:flex; width:max-content; align-items:stretch; gap:var(--activity-cell); }" in response.text
    assert '<div class="activity-chart-column">' in response.text
    assert '<div class="activity-legend"' in response.text
    assert ".activity-chart-column { order:1; }" in response.text
    assert ".activity-chart-shell { justify-content:flex-start; }" in response.text
    assert "enableDragScroll(scroll, 'x'" in response.text
    assert "enableWheelScroll(scroll)" in response.text
    wheel_handler = response.text.split("const enableWheelScroll =", 1)[1].split(
        "const isoWeek =", 1
    )[0]
    assert "element.addEventListener('wheel'" in wheel_handler
    assert "event.preventDefault()" in wheel_handler
    assert "element.scrollLeft > 0" in wheel_handler
    assert "element.scrollLeft < maxScroll" in wheel_handler
    assert "{passive:false}" in wheel_handler
    assert "enableDragScroll(pinList, 'y')" in response.text
    assert "const formatPinnedEnd = range =>" in response.text
    assert "return `ENDS ${day} ${month} ${value.getFullYear()}`" in response.text
    assert "b.end_date.localeCompare(a.end_date)" in response.text
    assert "b.start_date.localeCompare(a.start_date)" in response.text
    assert "Number(b.id) - Number(a.id)" in response.text
    assert "details.open = true" not in response.text
    pinned_header = response.text.split('class="activity-pin-controls"', 1)[1].split(
        'data-activity-pin-list', 1
    )[0]
    assert "Pinned" in pinned_header
    assert "data-activity-today>Today</button>" in pinned_header
    assert response.text.count("data-activity-today>Today</button>") == 2
    assert "const todayShortcuts = Array.from" in response.text
    assert "void scrollToDate(timelineData.end)" in response.text
    assert "closeDayMenu();" in response.text
    assert "if (focus) target.focus({preventScroll:true})" in response.text
    assert "button.addEventListener('click', () => scrollToDate(midpoint(range)))" in response.text
    assert "editRange.addEventListener('click', () => openMemoryDialog({range}))" in response.text
    assert "[data-memory-range-save] { border:1px solid #fbbf24" in response.text
    assert "memory-dialog-select-caret" in response.text
    assert ".memory-dialog-select { appearance:none; padding-right:2.5rem; }" in response.text
    drag_handler = response.text.split("const enableDragScroll =", 1)[1].split(
        "const isoWeek =", 1
    )[0]
    pointer_down, pointer_move = drag_handler.split(
        "element.addEventListener('pointermove'", 1
    )
    assert "setPointerCapture" not in pointer_down
    assert "setPointerCapture" in pointer_move
    assert "Create a category first" in response.text
    assert "memoryRefs.categorySelect.disabled = !memoryState.categories.length" in response.text
    assert "memoryRefs.start.max = timelineData.calendar_end" in response.text
    assert "memoryRefs.end.max = timelineData.calendar_end" in response.text
    assert ">Edit category</button>" in response.text
    assert "Create or edit a category" not in response.text
    assert "Select a day to recall or create a memory" not in response.text
    assert '.activity-day[data-pinned="true"] { border-color:var(--pin-color); box-shadow:inset 0 0 0 1px var(--pin-color); }' in response.text
    assert '.activity-day[data-pinned="true"]::after' not in response.text
    pinned_style = response.text.split('.activity-day[data-pinned="true"] {', 1)[1].split('}', 1)[0]
    assert "background:" not in pinned_style
    assert "const centerSelectedYear = () =>" in response.text
    assert "yearList.scrollTop + selectedRect.top - listRect.top" in response.text
    assert "await scrollToDate(timelineData.end, {behavior:'auto', focus:false})" in response.text
    assert "window.addEventListener('pageshow', () => {" in response.text
    assert "void centerSelectedDay();" in response.text
    assert "window.requestAnimationFrame(() => {\n        window.requestAnimationFrame" in response.text
    assert "hfl-corpus:activity-expanded" in response.text
    assert "writeActivityState(nextExpanded)" in response.text
    assert "Activity rhythm" not in response.text
    assert "data-result-tags" in response.text


def test_memory_pins_persist_categories_ranges_and_notes(authenticated_client):
    from modules.hfl_shares.security import make_csrf_token

    csrf = make_csrf_token("frontend-test-user")
    category = authenticated_client.post(
        "/hfl-corpus/memory-pins",
        json={
            "csrf": csrf,
            "action": "save_category",
            "name": "Turning points",
            "color": "#f59e0b",
        },
    )
    category_id = category.json()["categories"][0]["id"]
    pinned = authenticated_client.post(
        "/hfl-corpus/memory-pins",
        json={
            "csrf": csrf,
            "action": "save_range",
            "category_id": category_id,
            "start_date": "2018-06-12",
            "end_date": "2018-06-18",
            "note": "Recall the week the direction changed.",
        },
    )

    assert category.status_code == 200
    assert pinned.status_code == 200
    assert pinned.json()["ranges"][0]["start_date"] == "2018-06-12"
    assert pinned.json()["ranges"][0]["end_date"] == "2018-06-18"
    page = authenticated_client.get("/hfl-corpus?activity_year=2018")
    assert "Turning points" in page.text
    assert "Recall the week the direction changed." in page.text
    assert "Nothing here" in page.text  # Client-side empty-state copy remains available.


def test_memory_pin_categories_share_colors_and_exceed_palette_size(tmp_path):
    from modules.hfl_corpus.memory_pins import MemoryPinStore, PIN_COLORS

    store = MemoryPinStore(tmp_path / "memory-pins.db")
    for index in range(13):
        store.save_category(
            category_id=None,
            name=f"Category {index + 1}",
            color=PIN_COLORS[0],
        )

    snapshot = store.snapshot()
    assert len(snapshot["categories"]) == 13
    assert {category["color"] for category in snapshot["categories"]} == {
        PIN_COLORS[0]
    }
    assert len(snapshot["palette"]) == 12
    assert snapshot["palette"][-4:] == ["#e5e7eb", "#9ca3af", "#64748b", "#475569"]


def test_memory_pin_store_migrates_legacy_unique_colors_without_data_loss(tmp_path):
    import sqlite3

    from modules.hfl_corpus.memory_pins import MemoryPinStore

    path = tmp_path / "legacy-memory-pins.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE memory_pin_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                color TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE memory_pin_ranges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER NOT NULL REFERENCES memory_pin_categories(id) ON DELETE CASCADE,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK (start_date <= end_date)
            );
            INSERT INTO memory_pin_categories
                (id, name, color, created_at, updated_at)
            VALUES (1, 'Existing', '#f59e0b', 'before', 'before');
            INSERT INTO memory_pin_ranges
                (category_id, start_date, end_date, note, created_at, updated_at)
            VALUES (1, '2020-06-01', '2020-06-02', 'Keep this', 'before', 'before');
            """
        )

    store = MemoryPinStore(path)
    store.save_category(
        category_id=None,
        name="Same color",
        color="#f59e0b",
    )

    snapshot = store.snapshot()
    assert [category["name"] for category in snapshot["categories"]] == [
        "Existing",
        "Same color",
    ]
    assert snapshot["ranges"][0]["note"] == "Keep this"
    with store._connect() as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_activity_year_endpoint_returns_local_counts(authenticated_client, monkeypatch):
    import modules.hfl_corpus.router as hfl_routes

    document = _document("2023-04-05.md", entry_count=3)
    monkeypatch.setattr(hfl_routes, "_uses_remote_corpus", lambda: False)
    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: (document,))

    response = authenticated_client.get("/hfl-corpus/activity-year/2023")

    assert response.status_code == 200
    assert response.json() == {
        "year": 2023,
        "counts": {"2023-04-05": 3},
        "documents": {"2023-04-05": "2023-04-05.md"},
    }


def test_activity_year_endpoint_uses_legacy_remote_year_counts(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    requested = {}

    class FakeRemote:
        def index(self, *, params):
            requested.update(params)
            return {
                "activity": {
                    "counts": {"2023-04-05": 2, "2024-01-01": 9},
                    "documents": {
                        "2023-04-05": "2023-04-05.md",
                        "2024-01-01": "2024-01-01.md",
                    },
                }
            }

    monkeypatch.setattr(hfl_routes, "_uses_remote_corpus", lambda: True)
    monkeypatch.setattr(
        hfl_routes.RemoteCorpusClient,
        "from_settings",
        classmethod(lambda cls: FakeRemote()),
    )

    response = authenticated_client.get(
        "/hfl-corpus/activity-year/2023?q=%23work&source=notes"
    )

    assert response.status_code == 200
    assert response.json() == {
        "year": 2023,
        "counts": {"2023-04-05": 2},
        "documents": {"2023-04-05": "2023-04-05.md"},
    }
    assert requested["activity_year"] == "2023"
    assert requested["q"] == "#work"
    assert requested["source"] == "notes"
    assert requested["compact"] == "true"


def test_memory_pin_mutations_require_valid_csrf(authenticated_client):
    response = authenticated_client.post(
        "/hfl-corpus/memory-pins",
        json={"csrf": "", "action": "delete_range", "range_id": 1},
    )

    assert response.status_code == 403


def test_memory_pin_range_accepts_future_dates_through_five_year_limit(
    authenticated_client,
):
    from modules.hfl_shares.security import make_csrf_token

    csrf = make_csrf_token("frontend-test-user")
    category = authenticated_client.post(
        "/hfl-corpus/memory-pins",
        json={
            "csrf": csrf,
            "action": "save_category",
            "name": "Future",
            "color": "#3b82f6",
        },
    ).json()["categories"][0]
    allowed = date.today().replace(year=date.today().year + 5)
    response = authenticated_client.post(
        "/hfl-corpus/memory-pins",
        json={
            "csrf": csrf,
            "action": "save_range",
            "category_id": category["id"],
            "start_date": date.today().isoformat(),
            "end_date": allowed.isoformat(),
        },
    )

    assert response.status_code == 200
    assert response.json()["ranges"][0]["end_date"] == allowed.isoformat()

    rejected = authenticated_client.post(
        "/hfl-corpus/memory-pins",
        json={
            "csrf": csrf,
            "action": "save_range",
            "category_id": category["id"],
            "start_date": allowed.isoformat(),
            "end_date": (allowed + timedelta(days=1)).isoformat(),
        },
    )

    assert rejected.status_code == 422
    assert allowed.isoformat() in rejected.json()["detail"]


def test_memory_signal_exposes_exact_five_year_future_boundary(authenticated_client):
    import modules.hfl_corpus.router as hfl_routes

    today = date.today()
    max_pin_date = hfl_routes._add_calendar_years(today, 5)

    page = authenticated_client.get("/hfl-corpus")
    future_year = authenticated_client.get(
        f"/hfl-corpus/activity-year/{max_pin_date.year}"
    )
    beyond_limit = authenticated_client.get(
        f"/hfl-corpus/activity-year/{max_pin_date.year + 1}"
    )

    assert page.status_code == 200
    assert f'<option value="{max_pin_date.year}"' in page.text
    assert f'"calendar_end": "{max_pin_date.isoformat()}"' in page.text
    assert future_year.status_code == 200
    assert future_year.json() == {
        "year": max_pin_date.year,
        "counts": {},
        "documents": {},
    }
    assert beyond_limit.status_code == 404


def test_five_year_boundary_clamps_leap_day():
    import modules.hfl_corpus.router as hfl_routes

    assert hfl_routes._add_calendar_years(date(2024, 2, 29), 5) == date(2029, 2, 28)


def test_historical_counted_day_enables_matching_without_canonical_document(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    historical = CorpusEntry(
        anchor="historical-entry",
        header="2023-01-04 09:30",
        moment="Historical memory",
        what_happened="An older event",
        tags=("history",),
    )
    archive = _document(
        "archive/import.md",
        tags=("history",),
        entries=(historical,),
    )
    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: (archive,))

    response = authenticated_client.get("/hfl-corpus?activity_year=2023")

    assert response.status_code == 200
    historical_cell = response.text.split(
        'data-activity-day="2023-01-04"', 1
    )[1].split(">", 1)[0]
    assert 'data-count="1"' in historical_cell
    assert 'data-document-url=""' in historical_cell
    assert (
        "hfl-corpus/day-matches/2023-01-04"
        in historical_cell
    )
    assert "matchingEntries.disabled = !canShowMatches" in response.text


def test_corpus_search_uses_compact_date_controls(authenticated_client, monkeypatch):
    import modules.hfl_corpus.router as hfl_routes

    document = _document(
        "2026-07-10.md",
        tags=("debugging",),
        source="browsing",
    )
    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: (document,))

    response = authenticated_client.get(
        "/hfl-corpus?date_field=updated&date_from=2026-07-13&date_to=2026-07-20"
    )

    assert response.status_code == 200
    assert 'name="source"' in response.text
    assert '<option value="">All</option>' in response.text
    source_select = response.text.split('name="source"', 1)[1].split(
        "</select>",
        1,
    )[0]
    assert 'value="browsing"' in source_select
    assert ">browsing</option>" in source_select
    assert 'name="date_field"' in response.text
    assert 'name="date_from"' in response.text
    assert 'name="date_to"' in response.text
    assert 'name="created_from"' not in response.text
    assert "if (this.showPicker) this.showPicker()" in response.text
    tags_section = "<details data-tag-cloud"
    assert response.text.index('name="source"') < response.text.index(
        'name="date_field"'
    )
    assert response.text.index('name="date_field"') < response.text.index(tags_section)
    assert response.text.index(">Search</button>") < response.text.index(tags_section)
    assert response.text.index(">Reset</a>") < response.text.index(tags_section)
    assert "#debugging" in response.text
    assert "bg-blue-950/50" in response.text
    assert ">1</span>" in response.text
    assert "0 matches" in response.text


def test_corpus_source_filter_preserves_selection_across_index_controls(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    browsing = _document(
        "browsing.md",
        tags=("web",),
        source="browsing",
    )
    manual = _document(
        "manual.md",
        tags=("notes",),
        source="manual-entry",
    )
    monkeypatch.setattr(
        hfl_routes.corpus_index,
        "documents",
        lambda: (browsing, manual),
    )

    response = authenticated_client.get(
        "/hfl-corpus?source=manual-entry&page_size=50&sort=asc"
    )

    assert response.status_code == 200
    result_cards = response.text.split("data-corpus-results-scroll", 1)[1]
    assert "manual.md" in result_cards
    assert "browsing.md" not in result_cards
    assert (
        '<option value="manual-entry" selected>manual-entry</option>'
        in response.text
    )
    assert "source=manual-entry" in response.text
    assert 'href="/hfl-corpus?source=manual-entry&amp;page_size=50"' in response.text
    assert "?q=&source=manual-entry" in response.text

    all_sources = authenticated_client.get("/hfl-corpus?source=retired-source")
    assert "manual.md" in all_sources.text
    assert "browsing.md" in all_sources.text
    assert '<option value="">All</option>' in all_sources.text


def test_search_and_reset_actions_are_grouped_with_the_text_input(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    monkeypatch.setattr(
        hfl_routes.corpus_index,
        "documents",
        lambda: (_document("2026-07-10.md"),),
    )

    response = authenticated_client.get("/hfl-corpus")

    group = response.text.split("data-search-input-actions", 1)[1].split("</div>", 1)[0]
    assert 'id="q"' in group
    assert ">Search</button>" in group
    assert ">Reset</a>" in group
    assert group.index('id="q"') < group.index(">Search</button>") < group.index(">Reset</a>")


def test_corpus_search_explains_combined_search_and_supports_tag_cloud_toggles(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    document = _document("2026-07-10.md", tags=("jira", "notes", "testing"))
    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: (document,))

    response = authenticated_client.get(
        "/hfl-corpus?q=%23jira+%23notes+testing+topic"
    )

    assert response.status_code == 200
    assert ">Search the corpus</label>" in response.text
    assert 'placeholder="Try a topic, phrase, or #tag"' in response.text
    assert 'aria-label="How corpus search works"' in response.text
    assert "every space-delimited tag must match" in response.text
    tag_cloud = response.text.split("data-tag-cloud", 1)[1].split("</details>", 1)[0]
    assert tag_cloud.count('aria-pressed="true"') == 2
    assert (
        'href="/hfl-corpus?q=%23notes+testing+topic"' in response.text
    )
    assert (
        'href="/hfl-corpus?q=%23jira+%23notes+%23testing+testing+topic"'
        in response.text
    )


def test_corpus_results_sort_control_reverses_created_date_order(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    older = replace(
        _document("older.md"), created_at=datetime(2026, 7, 1)
    )
    newer = replace(
        _document("newer.md"), created_at=datetime(2026, 7, 20)
    )
    monkeypatch.setattr(
        hfl_routes.corpus_index, "documents", lambda: (older, newer)
    )

    newest_first = authenticated_client.get("/hfl-corpus")
    oldest_first = authenticated_client.get("/hfl-corpus?sort=asc")

    newer_card = '<h3 class="truncate text-sm font-semibold text-white">newer.md</h3>'
    older_card = '<h3 class="truncate text-sm font-semibold text-white">older.md</h3>'
    assert newest_first.text.index(newer_card) < newest_first.text.index(older_card)
    assert oldest_first.text.index(older_card) < oldest_first.text.index(newer_card)
    assert 'aria-label="Show oldest results first"' in newest_first.text
    assert 'aria-label="Show newest results first"' in oldest_first.text


def test_corpus_search_is_sticky_above_aligned_directory_and_results(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    document = _document("2026-07-10.md")
    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: (document,))

    response = authenticated_client.get("/hfl-corpus")

    search_position = response.text.index(
        '<form id="corpus-search-form" method="get" action="/hfl-corpus"'
    )
    grid_position = response.text.index(
        'lg:grid-cols-[minmax(14rem,1fr)_minmax(0,3fr)]'
    )
    assert search_position < grid_position
    assert "sticky top-0" in response.text
    assert "fixed inset-x-4 bottom-4" not in response.text
    assert ">Document results</h2>" in response.text
    assert response.text.index(">Directory tree</h2>") < response.text.index(
        ">Document results</h2>"
    )


def test_corpus_search_cards_show_updated_timestamp(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    document = replace(
        _document("2026-07-10.md"),
        updated_at=datetime(2026, 7, 12, 14, 35),
    )
    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: (document,))

    response = authenticated_client.get("/hfl-corpus")

    assert "Updated 2026-07-12 14:35" in response.text


def test_corpus_mobile_results_disclosure_is_open_by_default_and_uses_page_flow(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    document = _document("2026-07-10.md")
    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: (document,))

    response = authenticated_client.get("/hfl-corpus")

    main = response.text.split('data-corpus-index', 1)[1].split(">", 1)[0]
    search = response.text.split('data-index-search-panel', 1)[1].split(">", 1)[0]
    layout = response.text.split('data-corpus-layout', 1)[1].split(">", 1)[0]
    results = response.text.split('data-corpus-results', 1)[1].split(">", 1)[0]
    toggle = response.text.split('data-mobile-results-toggle', 1)[1].split(">", 1)[0]
    body = response.text.split('data-corpus-results-body', 1)[1].split(">", 1)[0]
    toolbar = response.text.split('data-corpus-results-toolbar', 1)[1].split(
        ">", 1
    )[0]
    cards = response.text.split('data-corpus-results-scroll', 1)[1].split(
        ">", 1
    )[0]
    assert "flex" in main
    assert "flex-col" in main
    assert "h-auto" in main
    assert "md:h-[calc(100dvh-3.5rem)]" in main
    assert "lg:overflow-hidden" in main
    assert "max-h" not in search
    assert "block" in layout
    assert "lg:min-h-0" in layout
    assert 'type="checkbox"' in toggle
    assert 'aria-controls="corpus-results-body"' in toggle
    assert " checked" in toggle
    assert 'for="mobile-results-toggle"' in response.text
    assert ">Document results<" in response.text
    results_disclosure = response.text.split('for="mobile-results-toggle"', 1)[1].split(
        "</label>", 1
    )[0]
    assert "corpus-disclosure-caret" in results_disclosure
    assert "data-disclosure-caret" in results_disclosure
    assert "hfl-corpus:results-expanded" in response.text
    assert "restoreDisclosure(resultsToggle, stateKeys.results)" in response.text
    assert "peer-focus-visible:ring-2" in response.text
    assert "overflow-visible" in results
    assert "lg:min-h-0" in results
    assert "hidden" in body
    assert "peer-checked:flex" in body
    assert "lg:flex" in body
    assert "shrink-0" in toolbar
    assert "overflow-visible" in cards
    assert "lg:overflow-y-auto" in cards
    assert response.text.index('data-corpus-results-toolbar') < response.text.index(
        'data-corpus-results-scroll'
    )
    assert "data-results-page-size" in response.text
    assert "event.currentTarget.form?.requestSubmit()" in response.text
    assert 'form="corpus-search-form"' in response.text
    assert response.text.count("data-focus-results") >= 2
    assert "data-corpus-result" in response.text
    assert "firstResult" in response.text
    assert "scrollIntoView" in response.text


def test_corpus_mobile_layout_prioritizes_search_results(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    document = _document("2026-07-10.md")
    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: (document,))

    response = authenticated_client.get("/hfl-corpus")

    assert response.status_code == 200
    main = response.text.split('data-corpus-index', 1)[1].split('>', 1)[0]
    assert "overflow-x-clip" in main
    assert "pr-5" in main
    directory = response.text.split('data-directory-tree', 1)[1].split('>', 1)[0]
    assert "hidden" in directory
    assert "lg:flex" in directory
    assert 'data-corpus-results' in response.text
    toolbar_opening = response.text.split('data-corpus-results-toolbar', 1)[1].split(
        ">", 1
    )[0]
    controls_opening = response.text.split('data-corpus-results-controls', 1)[1].split(
        ">", 1
    )[0]
    count_opening = response.text.split('data-corpus-results-count', 1)[1].split(
        ">", 1
    )[0]
    assert "flex-col" in toolbar_opening
    assert "sm:flex-row" in toolbar_opening
    assert "flex-wrap" in controls_opening
    assert "w-full" in count_opening
    assert "sm:w-auto" in count_opening
    assert "[@media(max-height:600px)]:hidden" in count_opening
    search_opening = response.text.split('data-search-input-actions', 1)[0].rsplit(
        "<div", 1
    )[1]
    search_actions = response.text.split('data-search-input-actions', 1)[1].split(
        "</div>", 1
    )[0]
    assert "grid-cols-2" in search_opening
    assert "sm:flex" in search_opening
    assert "col-span-2" in search_actions
    assert ">Reset</a>" in search_actions
    assert "sticky top-0" in response.text


def test_corpus_mobile_all_filters_include_source_dates_and_tag_cloud(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    document = _document("2026-07-10.md", source="manual-entry")
    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: (document,))

    response = authenticated_client.get("/hfl-corpus")

    filters = response.text.split('data-mobile-date-filters', 1)[1].split(
        "</form>", 1
    )[0]
    wrapper_opening = filters.split(">", 1)[0]
    toggle = filters.split('data-mobile-date-filter-toggle', 1)[1].split(">", 1)[0]
    fields_opening = filters.split('data-date-filter-fields', 1)[1].split(">", 1)[0]
    assert "lg:contents" in wrapper_opening
    assert 'type="checkbox"' in toggle
    assert 'aria-controls="mobile-date-filter-fields"' in toggle
    assert " checked" not in toggle
    assert 'for="mobile-date-filters"' in filters
    filters_disclosure = filters.split('for="mobile-date-filters"', 1)[1].split(
        "</label>", 1
    )[0]
    assert "corpus-disclosure-caret" in filters_disclosure
    assert "data-disclosure-caret" in filters_disclosure
    assert "hfl-corpus:filters-expanded" in response.text
    assert "restoreDisclosure(filtersToggle, stateKeys.filters)" in response.text
    assert "peer-focus-visible:ring-2" in filters
    assert "peer-focus-visible:ring-blue-500" in filters
    assert 'id="mobile-date-filter-fields"' in filters
    assert ">See all filters<" in filters
    assert "lg:hidden" in filters
    assert "hidden" in fields_opening
    assert "peer-checked:grid" in fields_opening
    assert "lg:contents" in fields_opening
    assert filters.count('class="block') == 4
    assert filters.count("lg:block") == 4
    assert 'name="source"' in filters
    assert 'name="date_field"' in filters
    assert 'name="date_from"' in filters
    assert 'name="date_to"' in filters
    assert 'data-tag-cloud' in filters
    assert "hfl-corpus:tags-expanded" in response.text
    assert "restoreDetails(tagCloud, stateKeys.tags)" in response.text
    assert "details.addEventListener('toggle'" in response.text
    assert filters.index('name="source"') < filters.index('name="date_field"')
    assert filters.index('name="date_to"') < filters.index('data-tag-cloud')


def test_corpus_defaults_to_first_20_results_and_paginates_search(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    documents = tuple(
        replace(
            _document(f"{index:02d}.md"),
            created_at=datetime(2026, 7, 1) + timedelta(days=index),
        )
        for index in range(45)
    )
    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: documents)

    default_response = authenticated_client.get("/hfl-corpus")
    second_page = authenticated_client.get(
        "/hfl-corpus?q=root&page=2&page_size=20"
    )

    card_marker = '<article data-corpus-result class="rounded-xl bg-slate-900'
    assert default_response.text.count(card_marker) == 20
    assert "45 matches · showing 1–20" in default_response.text
    assert second_page.text.count(card_marker) == 20
    assert "45 matches · showing 21–40" in second_page.text
    assert "Page 2 of 3" in second_page.text
    assert "q=root&amp;page=3&amp;page_size=20" in second_page.text


def test_corpus_supports_50_and_100_result_page_sizes(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    documents = tuple(
        replace(
            _document(f"{index:03d}.md"),
            created_at=datetime(2026, 1, 1) + timedelta(days=index),
        )
        for index in range(120)
    )
    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: documents)

    page_50 = authenticated_client.get("/hfl-corpus?page=2&page_size=50")
    page_100 = authenticated_client.get("/hfl-corpus?page=2&page_size=100")

    card_marker = '<article data-corpus-result class="rounded-xl bg-slate-900'
    assert page_50.text.count(card_marker) == 50
    assert "120 matches · showing 51–100" in page_50.text
    assert "Page 2 of 3" in page_50.text
    assert page_100.text.count(card_marker) == 20
    assert "120 matches · showing 101–120" in page_100.text
    assert "Page 2 of 2" in page_100.text


def test_selected_tag_result_defers_matching_entry_markup_until_expanded(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    entries = tuple(
        CorpusEntry(
            anchor=f"hfl-entry-{index}",
            header=f"Entry {index}",
            moment=f"Moment {index}",
            what_happened="Something worth remembering",
            tags=("debugging",),
            text="A debugging memory",
        )
        for index in range(25)
    )
    document = _document(
        "2026-07-10.md",
        tags=("debugging",),
        entry_count=25,
        entries=entries,
    )
    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: (document,))

    response = authenticated_client.get("/hfl-corpus?q=%23debug")

    assert response.status_code == 200
    assert "25 matching entries" in response.text
    assert 'data-matching-entry=' not in response.text
    assert "hfl-corpus/matches/2026-07-10.md?q=%23debug" in response.text
    assert 'hx-trigger="click once"' in response.text


def test_matching_entry_endpoint_returns_at_most_20_rows(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    entries = tuple(
        CorpusEntry(
            anchor=f"entry-{index}",
            header=f"Entry {index}",
            moment=f"Moment {index}",
            what_happened="Matched",
            tags=("work",),
            text="A work memory",
        )
        for index in range(25)
    )
    document = _document("many.md", tags=("work",), entry_count=25, entries=entries)
    monkeypatch.setattr(hfl_routes.corpus_index, "get", lambda path: document)

    response = authenticated_client.get("/hfl-corpus/matches/many.md?q=%23work")
    next_response = authenticated_client.get(
        "/hfl-corpus/matches/many.md?q=%23work&offset=20"
    )

    assert response.status_code == 200
    assert response.text.count('data-matching-entry=') == 20
    assert "offset=20" in response.text
    assert "Load next 5" in response.text
    assert next_response.status_code == 200
    assert next_response.text.count('data-matching-entry=') == 5
    assert 'class="h-64' not in next_response.text


def test_matching_entry_endpoint_returns_all_entries_without_filters(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    entries = (
        CorpusEntry(
            anchor="entry-one",
            header="Entry one",
            moment="First memory",
            what_happened="First event",
            tags=("work",),
        ),
        CorpusEntry(
            anchor="entry-two",
            header="Entry two",
            moment="Second memory",
            what_happened="Second event",
            tags=("personal",),
        ),
    )
    document = _document("2026-08-24.md", entry_count=2, entries=entries)
    monkeypatch.setattr(hfl_routes.corpus_index, "get", lambda path: document)

    response = authenticated_client.get(
        "/hfl-corpus/matches/2026-08-24.md"
    )

    assert response.status_code == 200
    assert response.text.count('data-matching-entry=') == 2
    assert "First memory" in response.text
    assert "Second memory" in response.text


def test_matching_entry_endpoint_shows_empty_filtered_state(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    document = _document("2026-08-24.md", tags=("work",))
    monkeypatch.setattr(hfl_routes.corpus_index, "get", lambda path: document)

    response = authenticated_client.get(
        "/hfl-corpus/matches/2026-08-24.md?q=%23personal"
    )

    assert response.status_code == 200
    assert 'data-matching-entry=' not in response.text
    assert "No entries match the current filters." in response.text


def test_day_matching_endpoint_opens_entries_from_historical_documents(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    historical = CorpusEntry(
        anchor="historical-entry",
        header="2023-01-04 09:30",
        moment="Historical memory",
        what_happened="An older event",
        tags=("history",),
        source="notes",
    )
    archive = _document(
        "archive/import.md",
        tags=("history",),
        entries=(historical,),
    )
    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: (archive,))

    response = authenticated_client.get(
        "/hfl-corpus/day-matches/2023-01-04?q=%23history"
    )

    assert response.status_code == 200
    assert 'data-matching-entry="historical-entry"' in response.text
    assert (
        "hfl-corpus/document/archive/import.md?tag=history#historical-entry"
        in response.text
    )


def test_day_matching_endpoint_keeps_twenty_entry_pagination(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    entries = tuple(
        CorpusEntry(
            anchor=f"historical-{index}",
            header="2023-01-04 09:30",
            moment=f"Historical memory {index}",
            what_happened="An older event",
            tags=("history",),
        )
        for index in range(25)
    )
    archive = _document(
        "archive/import.md",
        tags=("history",),
        entry_count=25,
        entries=entries,
    )
    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: (archive,))

    response = authenticated_client.get(
        "/hfl-corpus/day-matches/2023-01-04"
    )

    assert response.status_code == 200
    assert response.text.count('data-matching-entry=') == 20
    assert "day-matches/2023-01-04" in response.text
    assert "offset=20" in response.text
    assert "Load next 5" in response.text


def test_selected_cloud_tag_missing_from_top_counts_is_rendered_first_and_highlighted(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    entries = (
        CorpusEntry(
            anchor="hfl-entry-1-selected",
            header="Selected",
            moment="Selected tag moment",
            what_happened="The selected tag is outside the top ten",
            tags=("selected-tag",),
        ),
    )
    document = _document(
        "2026-07-10.md",
        tags=("selected-tag", "popular"),
        tag_counts=(("popular", 9),),
        entries=entries,
    )
    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: (document,))

    response = authenticated_client.get("/hfl-corpus?q=%23selected-tag")

    assert response.status_code == 200
    selected = response.text.index("#selected-tag")
    popular = response.text.index("#popular")
    assert selected < popular
    assert 'data-result-tag="selected-tag"' in response.text
    selected_tag_markup = response.text.split('data-result-tag="selected-tag"', 1)[1].split("</a>", 1)[0]
    assert "bg-emerald-950/70" in selected_tag_markup


def test_matching_entry_preview_links_to_anchored_document_entry(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    document = _document(
        "2026-07-10.md",
        tags=("debugging",),
        source="browsing",
    )
    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: (document,))

    response = authenticated_client.get("/hfl-corpus?q=%23debugging")
    preview = authenticated_client.get(
        "/hfl-corpus/matches/2026-07-10.md?q=%23debugging"
    )

    assert response.status_code == 200
    assert 'data-matching-entry="hfl-entry-1-test-entry"' not in response.text
    assert preview.status_code == 200
    assert 'data-matching-entry="hfl-entry-1-test-entry"' in preview.text
    assert "?tag=debugging#hfl-entry-1-test-entry" in preview.text


def test_corpus_index_uses_full_width_search_and_left_directory_layout(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    document = _document("2026-07-10.md")
    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: (document,))

    response = authenticated_client.get("/hfl-corpus")

    assert response.status_code == 200
    assert "1 file" in response.text
    assert "Markdown files" not in response.text
    assert response.text.index(">Directory tree</h2>") < response.text.index(">Document results</h2>")
    assert 'data-index-search-panel' in response.text
    assert "sticky top-0" in response.text
    assert "border-blue-800/70" in response.text


def test_plain_text_search_shows_clickable_matching_entry_previews(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    entries = (
        CorpusEntry(
            anchor="hfl-entry-1-first",
            header="First",
            moment="Solved a difficult issue",
            what_happened="The team investigated it",
            tags=("debugging",),
            text="First\nWhy it stayed: A reusable root cause lesson",
        ),
        CorpusEntry(
            anchor="hfl-entry-2-second",
            header="Second",
            moment="A different memory",
            what_happened="Nothing related",
            tags=("career",),
            text="Second\nWhy it stayed: Something else",
        ),
    )
    document = _document(
        "2026-07-10.md",
        tags=("career", "debugging"),
        entry_count=2,
        entries=entries,
        text="Why it stayed: A reusable root cause lesson",
    )
    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: (document,))

    response = authenticated_client.get("/hfl-corpus?q=reusable+root+cause")
    preview = authenticated_client.get(
        "/hfl-corpus/matches/2026-07-10.md?q=reusable+root+cause"
    )

    assert response.status_code == 200
    assert "1 matching entries" in response.text
    assert "Solved a difficult issue" not in response.text
    assert preview.status_code == 200
    assert "Solved a difficult issue" in preview.text
    assert "A different memory" not in preview.text
    assert (
        'href="http://testserver/hfl-corpus/document/2026-07-10.md#hfl-entry-1-first"'
        in preview.text
    )


def test_document_adds_entry_anchors_and_wraparound_tag_navigation(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    entries = (
        CorpusEntry(
            anchor="hfl-entry-1-first",
            header="First",
            moment="One",
            what_happened="First event",
            tags=("debugging",),
        ),
        CorpusEntry(
            anchor="hfl-entry-2-second",
            header="Second",
            moment="Two",
            what_happened="Second event",
            tags=("debugging",),
        ),
    )
    document = _document(
        "2026-07-10.md",
        tags=("debugging",),
        entry_count=2,
        entries=entries,
        text="## First\nMoment: One\nTags: #debugging\n\n## Second\nMoment: Two\nTags: #debugging\n",
    )
    monkeypatch.setattr(hfl_routes.corpus_index, "get", lambda path: document)

    response = authenticated_client.get(
        "/hfl-corpus/document/2026-07-10.md?tag=debug"
    )

    assert response.status_code == 200
    assert 'id="hfl-entry-1-first"' in response.text
    assert 'id="hfl-entry-2-second"' in response.text
    assert 'data-selected-tag="debug"' in response.text
    assert 'data-anchors="hfl-entry-1-first,hfl-entry-2-second"' in response.text
    assert "(currentIndex + 1) % anchors.length" in response.text
    assert "(currentIndex - 1 + anchors.length) % anchors.length" in response.text
    assert 'id="navigator-corpus-index" href="/hfl-corpus"' in response.text
    assert 'id="navigator-back-to-top"' in response.text
    assert "window.scrollTo({ top: 0, behavior: 'smooth' })" in response.text
    assert "max-h-28 overflow-y-auto" in response.text
    assert "max-w-4xl" in response.text
    assert "pb-56" in response.text
    assert "sm:order-2 sm:w-auto" in response.text
    assert "button.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' })" in response.text
    assert "window.location.hash.slice(1)" in response.text
    assert "anchors.indexOf(requestedAnchor)" in response.text


def test_document_without_entries_keeps_content_and_hides_navigator(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    document = _document(
        "notes.md",
        tags=(),
        entry_count=0,
        text="# Supporting notes\nThis content should remain visible.",
    )
    monkeypatch.setattr(hfl_routes.corpus_index, "get", lambda path: document)

    response = authenticated_client.get("/hfl-corpus/document/notes.md")

    assert response.status_code == 200
    assert "No entries found" in response.text
    assert "This content should remain visible." in response.text
    assert 'id="tag-navigator"' not in response.text
    assert 'id="navigator-corpus-index"' not in response.text
    assert 'id="navigator-back-to-top"' not in response.text


def test_corpus_api_requires_bearer_token(authenticated_client):
    response = authenticated_client.get("/api/hfl/documents")

    assert response.status_code == 401


def test_corpus_api_returns_canonical_documents(authenticated_client, monkeypatch):
    import modules.hfl_corpus.api as hfl_api

    document = _document(
        "2026-07-10.md",
        tags=("debugging",),
        source="browsing",
    )
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
    assert response.json()["sources"] == ["browsing"]
    assert response.json()["selected_source"] == ""
    assert response.json()["documents"][0]["relative_path"] == "2026-07-10.md"
    assert response.json()["results"][0]["entries"][0]["moment"] == "A useful moment"


def test_corpus_api_returns_filtered_activity_without_date_range_bias(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.api as hfl_api

    document = _document(
        "2026-02-02.md",
        tags=("work", "personal"),
        entry_count=2,
        entries=(
            CorpusEntry(
                anchor="work",
                header="2026-02-02 08:00",
                moment="Work entry",
                what_happened="Worked",
                tags=("work",),
                source="notes",
                text="Focused work",
            ),
            CorpusEntry(
                anchor="personal",
                header="2025-12-31 20:00",
                moment="Personal entry",
                what_happened="Rested",
                tags=("personal",),
                source="notes",
                text="Personal time",
            ),
        ),
    )
    monkeypatch.setattr(hfl_api.corpus_index, "documents", lambda: (document,))

    response = authenticated_client.get(
        "/api/hfl/documents?activity_year=2026&q=%23work&date_field=entry&"
        "date_from=2026-02-03&date_to=2026-02-03",
        headers={"Authorization": "Bearer frontend-test-hfl-api-token"},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["results"] == []
    assert payload["activity"] == {
        "year": 2026,
        "years": list(activity_calendar_years()),
        "counts": {"2026-02-02": 1},
        "documents": {"2026-02-02": "2026-02-02.md"},
        "timeline_counts": {"2026-02-02": 1},
    }


def test_corpus_api_applies_owner_configured_secret_tags(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.api as hfl_api

    document = _document("private.md", tags=("private",), source="notes")
    profile_store = SimpleNamespace(
        get=lambda: SimpleNamespace(secret_tags="#private")
    )
    monkeypatch.setattr(hfl_api, "get_profile_store", lambda: profile_store)
    monkeypatch.setattr(hfl_api.corpus_index, "documents", lambda: (document,))

    response = authenticated_client.get(
        "/api/hfl/documents?source=notes",
        headers={"Authorization": "Bearer frontend-test-hfl-api-token"},
    )

    assert response.status_code == 200
    assert response.json()["document_count"] == 0
    assert response.json()["results"] == []
    assert response.json()["activity"]["counts"] == {}


def test_corpus_api_paginates_results_and_returns_page_metadata(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.api as hfl_api

    documents = tuple(_document(f"{index:02d}.md") for index in range(25))
    monkeypatch.setattr(hfl_api.corpus_index, "documents", lambda: documents)

    response = authenticated_client.get(
        "/api/hfl/documents?q=%23debugging&page=2&page_size=20&compact=true",
        headers={"Authorization": "Bearer frontend-test-hfl-api-token"},
    )

    payload = response.json()
    assert response.status_code == 200
    assert len(payload["results"]) == 5
    assert "documents" not in payload
    assert "tree" in payload
    assert "entries" not in payload["results"][0]
    assert payload["results"][0]["matching_entry_count"] == 1
    assert payload["results"][0]["tag_entry_anchors"] == [
        ["debugging", "hfl-entry-1-test-entry"]
    ]
    assert payload["page"] == 2
    assert payload["page_size"] == 20
    assert payload["total_results"] == 25
    assert payload["total_pages"] == 2
    assert payload["has_previous"] is True
    assert payload["has_next"] is False


def test_corpus_api_returns_bounded_matching_entries(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.api as hfl_api

    entries = tuple(
        CorpusEntry(
            anchor=f"entry-{index}",
            header=f"Entry {index}",
            moment=f"Moment {index}",
            what_happened="Matched",
            tags=("work",),
            text="A work memory",
        )
        for index in range(25)
    )
    document = _document("many.md", tags=("work",), entry_count=25, entries=entries)
    monkeypatch.setattr(hfl_api.corpus_index, "get", lambda path: document)

    response = authenticated_client.get(
        "/api/hfl/matches/many.md?q=%23work&offset=20&limit=20",
        headers={"Authorization": "Bearer frontend-test-hfl-api-token"},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["total"] == 25
    assert payload["offset"] == 20
    assert len(payload["entries"]) == 5


def test_corpus_api_returns_all_matching_entries_without_filters(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.api as hfl_api

    entries = (
        CorpusEntry(
            anchor="entry-one",
            header="Entry one",
            moment="First memory",
            what_happened="First event",
            tags=("work",),
        ),
        CorpusEntry(
            anchor="entry-two",
            header="Entry two",
            moment="Second memory",
            what_happened="Second event",
            tags=("personal",),
        ),
    )
    document = _document("2026-08-24.md", entry_count=2, entries=entries)
    monkeypatch.setattr(hfl_api.corpus_index, "get", lambda path: document)

    response = authenticated_client.get(
        "/api/hfl/matches/2026-08-24.md",
        headers={"Authorization": "Bearer frontend-test-hfl-api-token"},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["total"] == 2
    assert [entry["anchor"] for entry in payload["entries"]] == [
        "entry-one",
        "entry-two",
    ]


def test_corpus_api_returns_day_matches_from_historical_documents(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.api as hfl_api

    historical = CorpusEntry(
        anchor="historical-entry",
        header="2023-01-04 09:30",
        moment="Historical memory",
        what_happened="An older event",
        tags=("history",),
    )
    archive = _document(
        "archive/import.md",
        tags=("history",),
        entries=(historical,),
    )
    monkeypatch.setattr(hfl_api.corpus_index, "documents", lambda: (archive,))

    response = authenticated_client.get(
        "/api/hfl/day-matches/2023-01-04",
        headers={"Authorization": "Bearer frontend-test-hfl-api-token"},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["total"] == 1
    assert payload["matches"][0]["relative_path"] == "archive/import.md"
    assert payload["matches"][0]["entry"]["anchor"] == "historical-entry"


def test_corpus_api_exposes_only_safe_resolved_references(
    authenticated_client, monkeypatch, tmp_path
):
    import modules.hfl_corpus.api as hfl_api

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    source_path = corpus / "2026-07-26.md"
    source_path.write_text("entry", encoding="utf-8")
    artifact = corpus / "Daily Notes [final].md"
    artifact.write_text("notes", encoding="utf-8")
    outside = tmp_path / "private.txt"
    outside.write_text("private", encoding="utf-8")
    document = replace(
        _document(
            "2026-07-26.md",
            references=(
                str(artifact),
                str(outside),
                "http://internal.example/dashboard",
                "https://example.com/source",
            ),
        ),
        path=source_path,
    )
    monkeypatch.setattr(hfl_api.corpus_index, "get", lambda path: document)
    monkeypatch.setattr(hfl_api, "resolve_corpus_root", lambda: corpus)

    response = authenticated_client.get(
        "/api/hfl/document/2026-07-26.md",
        headers={"Authorization": "Bearer frontend-test-hfl-api-token"},
    )

    references = response.json()["references"]
    assert response.status_code == 200
    assert {reference["kind"] for reference in references} == {
        "download",
        "external",
    }
    assert {reference["source"] for reference in references} == {
        str(artifact),
        "https://example.com/source",
    }
    download = next(item for item in references if item["kind"] == "download")
    assert download["label"] == str(artifact.resolve())
    assert download["href"] is None
    assert download["token"]
    assert download["preview_kind"] == "markdown"
    serialized = json.dumps(response.json())
    assert str(outside) not in serialized
    assert "http://internal.example/dashboard" not in serialized


def test_corpus_api_filters_documents_and_entries_by_source(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.api as hfl_api

    browsing = CorpusEntry(
        anchor="browse",
        header="Browse",
        moment="A page",
        what_happened="Read it",
        tags=("web",),
        source="browsing",
        text="A page",
    )
    manual = CorpusEntry(
        anchor="manual",
        header="Manual",
        moment="A note",
        what_happened="Wrote it",
        tags=("notes",),
        source="manual-entry",
        text="A note",
    )
    document = _document(
        "mixed.md",
        tags=("web", "notes"),
        entry_count=2,
        entries=(browsing, manual),
    )
    monkeypatch.setattr(hfl_api.corpus_index, "documents", lambda: (document,))
    monkeypatch.setattr(hfl_api.corpus_index, "get", lambda path: document)
    headers = {"Authorization": "Bearer frontend-test-hfl-api-token"}

    index = authenticated_client.get(
        "/api/hfl/documents?source=BROWSING&compact=true",
        headers=headers,
    )
    matches = authenticated_client.get(
        "/api/hfl/matches/mixed.md?source=browsing",
        headers=headers,
    )

    assert index.status_code == 200
    assert index.json()["selected_source"] == "browsing"
    assert index.json()["sources"] == ["browsing", "manual-entry"]
    assert index.json()["results"][0]["matching_entry_count"] == 1
    assert matches.status_code == 200
    assert matches.json()["total"] == 1
    assert matches.json()["entries"][0]["source"] == "browsing"


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
        "tree": {
            "name": "Corpus",
            "path": "",
            "directories": [],
            "files": [{
                "relative_path": "2026-07-19.md",
                "name": "2026-07-19.md",
                "created_at": "2026-07-19T09:30:00",
                "updated_at": "2026-07-19T10:00:00",
                "tags": ["hfl"],
                "tag_counts": [["hfl", 1]],
                "entry_count": 1,
                "excerpt": "A canonical entry",
            }],
        },
        "results": [{
            "relative_path": "2026-07-19.md",
            "name": "2026-07-19.md",
            "created_at": "2026-07-19T09:30:00",
            "updated_at": "2026-07-19T10:00:00",
            "tags": ["hfl"],
            "tag_counts": [["hfl", 1]],
            "entry_count": 1,
            "matching_entry_count": 1,
            "tag_entry_anchors": [["hfl", "hfl-entry-1-remote"]],
            "excerpt": "A canonical entry",
        }],
        "total_results": 1,
        "page": 1,
        "page_size": 20,
        "total_pages": 1,
        "has_previous": False,
        "has_next": False,
        "document_count": 1,
        "tag_cloud": [["hfl", 1]],
        "sources": ["browsing", "manual-entry"],
        "selected_source": "browsing",
        "activity": {
            "year": 2026,
            "years": [2026, 2025],
            "counts": {"2026-07-19": 3},
            "documents": {"2026-07-19": "2026-07-19.md"},
        },
    }
    monkeypatch.setattr(
        remote_module,
        "_http_client",
        lambda: SimpleNamespace(
            get=lambda url, **kwargs: httpx.Response(
                200,
                json=payload,
                request=httpx.Request("GET", url),
            )
        ),
    )

    result = RemoteCorpusClient("http://canonical:8081", "secret").index(params={})

    assert result["document_count"] == 1
    assert result["page"] == 1
    assert result["page_size"] == 20
    assert result["total_pages"] == 1
    assert result["has_next"] is False
    assert result["sources"] == ["browsing", "manual-entry"]
    assert result["selected_source"] == "browsing"
    assert result["activity"] == {
        "year": 2026,
        "years": [2026, 2025],
        "counts": {"2026-07-19": 3},
        "documents": {"2026-07-19": "2026-07-19.md"},
    }
    assert result["documents"] == ()
    assert result["tree"]["files"][0].path is None
    assert result["tree"]["files"][0].relative_path == "2026-07-19.md"
    assert (
        result["results"][0].first_matching_entry_anchor("hfl")
        == "hfl-entry-1-remote"
    )


def test_remote_client_reuses_and_closes_process_connection_pool():
    remote_module.close_remote_http_client()

    first = remote_module._http_client()
    second = remote_module._http_client()

    assert second is first

    remote_module.close_remote_http_client()
    replacement = remote_module._http_client()
    try:
        assert replacement is not first
    finally:
        remote_module.close_remote_http_client()


def test_remote_client_loads_historical_day_matches(monkeypatch):
    from modules.hfl_corpus.remote import RemoteCorpusClient

    requests = []
    payload = {
        "matches": [{
            "relative_path": "archive/import.md",
            "entry": {
                "anchor": "historical-entry",
                "header": "2023-01-04 09:30",
                "moment": "Historical memory",
                "what_happened": "An older event",
                "tags": ["history"],
            },
        }],
        "total": 1,
        "offset": 0,
        "limit": 20,
    }

    def remote_get(url, **kwargs):
        requests.append((url, kwargs["params"]))
        return httpx.Response(
            200,
            json=payload,
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(
        remote_module,
        "_http_client",
        lambda: SimpleNamespace(get=remote_get),
    )

    result = RemoteCorpusClient(
        "http://canonical:8081", "secret"
    ).day_matches(date(2023, 1, 4), query="#history")

    assert requests[0][0].endswith("/api/hfl/day-matches/2023-01-04")
    assert requests[0][1]["q"] == "#history"
    assert result["total"] == 1
    assert result["matches"][0][0] == "archive/import.md"
    assert result["matches"][0][1].anchor == "historical-entry"


def test_remote_client_builds_corpus_previewer_urls(monkeypatch):
    from modules.hfl_corpus.remote import RemoteCorpusClient

    payload = {
        "document": {
            "relative_path": "2026-07-19.md",
            "name": "2026-07-19.md",
            "created_at": "2026-07-19T09:30:00",
            "updated_at": "2026-07-19T10:00:00",
            "tags": ["notes"],
            "tag_counts": [["notes", 1]],
            "entry_count": 1,
            "excerpt": "A canonical entry",
            "text": "## Entry",
            "entries": [],
        },
        "references": [{
            "label": "notes.md",
            "kind": "download",
            "href": None,
            "source": "notes.md",
            "token": "signed-token",
            "preview_kind": "markdown",
        }],
    }
    monkeypatch.setattr(
        remote_module,
        "_http_client",
        lambda: SimpleNamespace(
            get=lambda url, **kwargs: httpx.Response(
                200,
                json=payload,
                request=httpx.Request("GET", url),
            )
        ),
    )

    _, references = RemoteCorpusClient(
        "http://canonical:8081",
        "secret",
    ).document("2026-07-19.md")

    reference = references[0]
    assert reference.href == (
        "/hfl-corpus/remote-references/signed-token/download"
    )
    assert reference.preview_kind == "markdown"
    assert reference.preview_url == (
        "/hfl-corpus/remote-references/signed-token/preview"
    )
    assert reference.media_url == (
        "/hfl-corpus/remote-references/signed-token/media"
    )


def test_remote_client_loads_entry_documents_for_selected_share_sources(monkeypatch):
    from modules.hfl_corpus.remote import RemoteCorpusClient

    requests = []

    def remote_get(url, **kwargs):
        requests.append(kwargs["params"])
        source = kwargs["params"]["source"]
        payload = {
            "selected_source": source,
            "results": [{
                "relative_path": f"{source}.md",
                "name": f"{source}.md",
                "created_at": "2026-07-19T09:30:00",
                "updated_at": "2026-07-19T10:00:00",
                "tags": ["hfl"],
                "tag_counts": [["hfl", 1]],
                "entry_count": 1,
                "excerpt": "A canonical entry",
                "entries": [{
                    "anchor": f"hfl-entry-{source}",
                    "header": "2026-07-19 09:30",
                    "moment": "Remote moment",
                    "what_happened": "Remote event",
                    "tags": ["hfl"],
                    "source": source,
                    "text": f"Source: {source}",
                }],
            }],
        }
        return httpx.Response(
            200,
            json=payload,
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(
        remote_module,
        "_http_client",
        lambda: SimpleNamespace(get=remote_get),
    )

    documents = RemoteCorpusClient(
        "http://canonical:8081",
        "secret",
    ).sharing_documents(["notes", "git"])

    assert {document.entries[0].source for document in documents} == {
        "notes",
        "git",
    }
    assert all(request["compact"] == "false" for request in requests)


def test_remote_client_paginates_legacy_index_contract(monkeypatch):
    from modules.hfl_corpus.remote import RemoteCorpusClient

    documents = [
        {
            "relative_path": f"{index:02d}.md",
            "name": f"{index:02d}.md",
            "created_at": "2026-07-19T09:30:00",
            "updated_at": "2026-07-19T10:00:00",
            "tags": ["hfl"],
            "tag_counts": [["hfl", 1]],
            "entry_count": 0,
            "entries": [],
            "excerpt": "A legacy canonical entry",
        }
        for index in range(25)
    ]
    payload = {
        "documents": documents,
        "results": documents,
        "total_results": 25,
        "document_count": 25,
        "tag_cloud": [["hfl", 25]],
    }
    requested = {}

    def legacy_get(url, **kwargs):
        requested.update(kwargs.get("params") or {})
        return httpx.Response(
            200,
            json=payload,
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(
        remote_module,
        "_http_client",
        lambda: SimpleNamespace(get=legacy_get),
    )

    result = RemoteCorpusClient("http://canonical:8081", "secret").index(
        params={"page": "2", "page_size": "20"}
    )

    assert requested["compact"] == "true"
    assert len(result["results"]) == 5
    assert result["page"] == 2
    assert result["page_size"] == 20
    assert result["total_pages"] == 2
    assert result["has_previous"] is True
    assert result["has_next"] is False
    assert len(result["tree"]["files"]) == 25


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


def _create_entry_payload():
    return {
        "date": "2026-07-19",
        "time": "10:45",
        "moment": "Captured a useful thought",
        "what_happened": "Wrote the details down manually.",
        "why_it_stayed": "It may be useful later.",
        "possible_use": "brainstorming",
        "tags": "#notes #manual-entry #thoughts",
        "references": "https://example.com/one\n- C:\\notes\\source.md\n\n",
    }


def test_corpus_index_renders_create_review_and_discard_dialogs(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: ())

    response = authenticated_client.get("/hfl-corpus?created=true")

    assert response.status_code == 200
    assert "Create entry" in response.text
    assert "Catch it before it wanders" in response.text
    assert 'data-create-entry-dialog' in response.text
    assert 'name="date"' in response.text
    assert f'name="date" required max="{date.today().isoformat()}"' in response.text
    assert 'name="time"' in response.text
    assert 'name="moment"' in response.text
    assert 'name="moment" required maxlength="500" placeholder="description"' in response.text
    assert 'name="what_happened" required rows="3" placeholder="enter details"' in response.text
    assert "enter moment details" not in response.text
    assert "just writing down notes or thoughts" in response.text
    assert 'placeholder="brainstorming"' in response.text
    assert "#notes #manual-entry #thoughts" in response.text
    assert 'data-entry-review-dialog' in response.text
    assert 'data-entry-discard-dialog' in response.text
    assert 'type="file" name="attachments" multiple' in response.text
    assert "data-entry-file-list" in response.text
    assert "data-entry-upload-progress" in response.text
    assert "new XMLHttpRequest()" in response.text
    assert "request.upload.addEventListener('progress'" in response.text
    assert ">Review and save</button>" in response.text
    assert "HFL entry created successfully." in response.text


def test_manual_entry_rejects_future_dates():
    from modules.hfl_corpus.entry_create import CreateEntryRequest, _timestamp

    request = _create_entry_payload()
    request["date"] = (date.today() + timedelta(days=1)).isoformat()

    with pytest.raises(ValueError, match="future date"):
        _timestamp(CreateEntryRequest.model_validate(request))


def test_create_entry_dialog_uses_mobile_sheets_and_touch_friendly_controls(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: ())

    response = authenticated_client.get("/hfl-corpus")

    create_dialog = response.text.split(
        "<dialog data-create-entry-dialog", 1
    )[1].split(">", 1)[0]
    create_form = response.text.split(
        "data-create-entry-form", 1
    )[1].split(">", 1)[0]
    create_header = response.text.split(
        "data-entry-dialog-header", 1
    )[1].split(">", 1)[0]
    form_body = response.text.split(
        "data-entry-form-body", 1
    )[1].split(">", 1)[0]
    create_actions = response.text.split(
        "data-entry-dialog-actions", 1
    )[1].split(">", 1)[0]
    review_dialog = response.text.split(
        "data-entry-review-dialog", 1
    )[1].split(">", 1)[0]
    review_actions = response.text.split(
        "data-entry-review-actions", 1
    )[1].split(">", 1)[0]
    more_details = response.text.split(
        "data-entry-more-details", 1
    )[1].split("</details>", 1)[0]
    date_time_fields = response.text.split(
        'name="date"', 1
    )[0].rsplit("<div", 1)[1]

    assert "h-[100dvh]" in create_dialog
    assert "w-screen" in create_dialog
    assert "overflow-hidden" in create_dialog
    assert "rounded-none" in create_dialog
    assert "sm:m-auto" in create_dialog
    assert "sm:h-auto" in create_dialog
    assert "sm:rounded-2xl" in create_dialog
    assert "dialog[data-create-entry-dialog]" in response.text
    assert "dialog[data-create-entry-dialog] > form" in response.text
    assert "height: fit-content !important" in response.text
    assert "@media (min-width: 640px)" in response.text
    assert "flex h-full" in create_form
    assert "overflow-hidden" in create_form
    assert "sm:block" in create_form
    assert "safe-area-inset-top" in create_header
    assert "overflow-y-auto" in form_body
    assert "scroll-padding-bottom:8rem" in form_body
    assert "sticky bottom-0" in create_actions
    assert "flex-col" in create_actions
    assert "safe-area-inset-bottom" in create_actions
    assert "sm:flex-row" in create_actions
    assert "grid-cols-2" in date_time_fields
    assert "min-h-11" in response.text
    assert "text-base" in response.text
    assert "sm:text-sm" in response.text
    assert "h-[100dvh]" in review_dialog
    assert "w-screen" in review_dialog
    assert "overflow-hidden" in review_dialog
    assert "sticky bottom-0" in review_actions
    assert "sm:flex-row" in review_actions
    assert "window.innerWidth >= 640" in response.text
    assert "scrollIntoView({behavior: 'smooth', block: 'center'})" in response.text
    assert "form.checkValidity()" in response.text
    assert " open" not in more_details.split(">", 1)[0]
    assert ">Add more details</span>" in more_details
    assert 'stroke-width="2.5"' in more_details
    assert 'd="m5 7.5 5 5 5-5"' in more_details
    assert 'name="why_it_stayed"' in more_details
    assert 'name="possible_use"' in more_details
    assert 'name="include_location" checked' in more_details
    assert 'name="source"' in more_details
    assert '<option value="manual-entry" selected>manual-entry</option>' in more_details
    assert 'data-entry-location-toggle' in more_details
    assert ">Include location</span>" in more_details
    assert "Use your activity timeline first" in more_details
    assert 'name="tags" value="#notes #manual-entry #thoughts"' in more_details
    assert 'name="references"' in more_details
    assert "moreDetails.open = false" in response.text
    assert "navigator.geolocation.getCurrentPosition" in response.text
    assert "data-entry-enrichment-summary" in response.text
    assert "Adding context…" in response.text


def test_compiled_css_contains_manual_entry_location_toggle_utilities():
    css = (
        Path(__file__).resolve().parents[1] / "static" / "css" / "app.min.css"
    ).read_text(encoding="utf-8")

    assert ".h-6{height:1.5rem}" in css
    assert ".w-11{width:2.75rem}" in css
    assert ".left-1{left:.25rem}" in css
    assert ".bg-white{" in css
    assert "peer-checked\\:bg-blue-600" in css
    assert "peer-checked\\:translate-x-5" in css


def test_create_entry_launcher_and_discard_actions_stack_on_mobile(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: ())

    response = authenticated_client.get("/hfl-corpus")

    launcher = response.text.split(
        "data-create-entry-open", 1
    )[1].split(">", 1)[0]
    discard_dialog = response.text.split(
        "data-entry-discard-dialog", 1
    )[1].split("</dialog>", 1)[0]

    assert "min-h-11" in launcher
    assert "w-full" in launcher
    assert "sm:w-auto" in launcher
    assert "w-[min(28rem,calc(100%-2rem))]" in discard_dialog
    assert "flex flex-col" in discard_dialog
    assert "sm:flex-row" in discard_dialog
    assert "safe-area-inset-bottom" in discard_dialog


def test_manual_entry_preview_uses_canonical_shape_and_reference_list(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    monkeypatch.setattr(
        hfl_routes,
        "enrich_manual_entry",
        lambda payload: (payload, {
            "location_source": "disabled",
            "location_label": "",
            "added_tags": [],
            "notices": [],
        }),
    )
    monkeypatch.setattr(
        "workflows.hfl.persistence.local_machine_name",
        lambda: "harqis-server",
    )

    response = authenticated_client.post(
        "/hfl-corpus/entries/preview",
        json=_create_entry_payload(),
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["filename"] == "2026-07-19.md"
    assert "## 2026-07-19 10:45" in payload["markdown"]
    assert "Source:          manual-entry" in payload["markdown"]
    assert "Machine:         harqis-server" in payload["markdown"]
    assert "Possible use:    brainstorming" in payload["markdown"]
    assert "Tags:            #notes #manual-entry #thoughts" in payload["markdown"]
    assert "                 - https://example.com/one" in payload["markdown"]
    assert "                 - C:\\notes\\source.md" in payload["markdown"]
    assert "<strong>References:</strong>" in payload["html"]
    assert "<li>" in payload["html"]


def test_manual_entry_preview_allows_source_override(authenticated_client, monkeypatch):
    import modules.hfl_corpus.router as hfl_routes

    monkeypatch.setattr(
        hfl_routes,
        "enrich_manual_entry",
        lambda payload: (payload, {
            "location_source": "disabled",
            "location_label": "",
            "added_tags": [],
            "notices": [],
        }),
    )
    request = _create_entry_payload()
    request["source"] = "browsing"

    response = authenticated_client.post("/hfl-corpus/entries/preview", json=request)

    assert response.status_code == 200
    assert "Source:          browsing" in response.json()["markdown"]


def test_manual_entry_preview_rejects_required_blank_fields(authenticated_client):
    request = _create_entry_payload()
    request["moment"] = " "

    response = authenticated_client.post(
        "/hfl-corpus/entries/preview",
        json=request,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Moment is required."


def test_manual_entry_preview_adds_future_attachment_references(
    authenticated_client, monkeypatch, tmp_path
):
    import modules.hfl_corpus.entry_create as entry_create
    import modules.hfl_corpus.router as hfl_routes

    monkeypatch.setattr(entry_create, "resolve_upload_inbox", lambda: tmp_path)
    monkeypatch.setattr(
        hfl_routes,
        "enrich_manual_entry",
        lambda payload: (payload, {
            "location_source": "disabled",
            "location_label": "",
            "added_tags": [],
            "notices": [],
        }),
    )
    monkeypatch.setattr(
        "workflows.hfl.persistence.local_machine_name",
        lambda: "harqis-server",
    )
    request = _create_entry_payload()
    request["attachment_names"] = ["photo.jpg", "../unsafe:name.txt"]

    response = authenticated_client.post(
        "/hfl-corpus/entries/preview",
        json=request,
    )

    assert response.status_code == 200
    markdown = response.json()["markdown"]
    assert str(tmp_path / "uploads" / "2026-07-19") in markdown
    assert "photo.jpg" in markdown
    assert "unsafe_name.txt" in markdown
    assert "../unsafe:name.txt" not in markdown


def test_local_manual_entry_create_persists_and_refreshes_index(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    persisted = []
    refreshed = []
    monkeypatch.setattr(hfl_routes, "_uses_remote_corpus", lambda: False)
    monkeypatch.setattr(hfl_routes, "resolve_corpus_root", lambda: "C:/corpus")
    monkeypatch.setattr(
        hfl_routes,
        "persist_manual_entry",
        lambda payload, *, corpus_dir: persisted.append(
            (payload, corpus_dir)
        ) or {
            "entry_id": "hfl-manual",
            "path": "C:/corpus/2026-07-19.md",
            "duplicate": False,
            "indexed": True,
            "delivery": "persisted",
        },
    )
    monkeypatch.setattr(
        hfl_routes.corpus_index,
        "documents",
        lambda force=False: refreshed.append(force) or (),
    )

    response = authenticated_client.post(
        "/hfl-corpus/entries",
        json=_create_entry_payload(),
    )

    assert response.status_code == 200
    assert response.json()["indexed"] is True
    assert persisted[0][1] == "C:/corpus"
    assert refreshed == [True]


def test_remote_manual_entry_create_uses_canonical_host(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    submitted = []

    class FakeRemote:
        def create_entry(self, payload):
            submitted.append(payload)
            return {
                "entry_id": "hfl-remote",
                "path": "/corpus/2026-07-19.md",
                "duplicate": False,
                "indexed": True,
                "delivery": "persisted",
            }

    monkeypatch.setattr(hfl_routes, "_uses_remote_corpus", lambda: True)
    monkeypatch.setattr(
        hfl_routes.RemoteCorpusClient,
        "from_settings",
        classmethod(lambda cls: FakeRemote()),
    )
    monkeypatch.setattr(
        hfl_routes,
        "persist_manual_entry",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("local writer used")
        ),
    )

    response = authenticated_client.post(
        "/hfl-corpus/entries",
        json=_create_entry_payload(),
    )

    assert response.status_code == 200
    assert response.json()["entry_id"] == "hfl-remote"
    assert submitted[0]["moment"] == "Captured a useful thought"


def test_remote_manual_entry_preview_enriches_on_canonical_host(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    submitted = []

    class FakeRemote:
        def preview_entry(self, payload):
            submitted.append(payload)
            enriched = {**payload, "tags": payload["tags"] + " #contextual"}
            return {
                "filename": "2026-07-19.md",
                "markdown": "preview",
                "html": "<p>preview</p>",
                "payload": enriched,
                "enrichment": {
                    "location_source": "owntracks",
                    "location_label": "Singapore",
                    "added_tags": ["contextual"],
                    "notices": [],
                },
            }

    monkeypatch.setattr(hfl_routes, "_uses_remote_corpus", lambda: True)
    monkeypatch.setattr(
        hfl_routes.RemoteCorpusClient,
        "from_settings",
        classmethod(lambda cls: FakeRemote()),
    )
    monkeypatch.setattr(
        hfl_routes,
        "enrich_manual_entry",
        lambda payload: (_ for _ in ()).throw(
            AssertionError("local enrichment used")
        ),
    )

    response = authenticated_client.post(
        "/hfl-corpus/entries/preview",
        json=_create_entry_payload(),
    )

    assert response.status_code == 200
    assert response.json()["payload"]["tags"].endswith("#contextual")
    assert submitted[0]["moment"] == "Captured a useful thought"


def test_local_manual_entry_upload_persists_files_and_references(
    authenticated_client, monkeypatch, tmp_path
):
    import modules.hfl_corpus.entry_create as entry_create
    import modules.hfl_corpus.router as hfl_routes

    corpus_dir = tmp_path / "corpus"
    inbox_dir = tmp_path / "dumps"
    monkeypatch.setattr(hfl_routes, "_uses_remote_corpus", lambda: False)
    monkeypatch.setattr(hfl_routes, "resolve_corpus_root", lambda: corpus_dir)
    monkeypatch.setattr(entry_create, "resolve_upload_inbox", lambda: inbox_dir)
    monkeypatch.setattr(
        "workflows.hfl.persistence.local_machine_name",
        lambda: "harqis-server",
    )
    monkeypatch.setattr(
        "workflows.hfl.es_store.index_hfl_entry",
        lambda entry, **kwargs: entry.entry_id,
    )
    monkeypatch.setattr(
        entry_create.os,
        "link",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("uploads must not require hard-link support")
        ),
    )
    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda force=False: ())
    request = _create_entry_payload()
    request["attachment_names"] = ["photo.jpg", "notes.txt"]

    response = authenticated_client.post(
        "/hfl-corpus/entries/upload",
        data={"payload": json.dumps(request)},
        files=[
            ("files", ("photo.jpg", b"image-bytes", "image/jpeg")),
            ("files", ("notes.txt", b"notes", "text/plain")),
        ],
    )

    assert response.status_code == 200
    result = response.json()
    assert result["duplicate"] is False
    assert len(result["uploads"]) == 2
    for uploaded in result["uploads"]:
        assert Path(uploaded).is_file()
    markdown = (corpus_dir / "2026-07-19.md").read_text(encoding="utf-8")
    assert result["entry_id"] in markdown
    assert result["uploads"][0] in markdown
    assert result["uploads"][1] in markdown


def test_duplicate_manual_upload_merges_new_references(
    authenticated_client, monkeypatch, tmp_path
):
    import modules.hfl_corpus.entry_create as entry_create
    import modules.hfl_corpus.router as hfl_routes

    corpus_dir = tmp_path / "corpus"
    inbox_dir = tmp_path / "dumps"
    monkeypatch.setattr(hfl_routes, "_uses_remote_corpus", lambda: False)
    monkeypatch.setattr(hfl_routes, "resolve_corpus_root", lambda: corpus_dir)
    monkeypatch.setattr(entry_create, "resolve_upload_inbox", lambda: inbox_dir)
    monkeypatch.setattr(
        "workflows.hfl.persistence.local_machine_name",
        lambda: "harqis-server",
    )
    monkeypatch.setattr(
        "workflows.hfl.es_store.index_hfl_entry",
        lambda entry, **kwargs: entry.entry_id,
    )
    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda force=False: ())

    results = []
    for filename in ("first.txt", "second.txt"):
        request = _create_entry_payload()
        request["attachment_names"] = [filename]
        response = authenticated_client.post(
            "/hfl-corpus/entries/upload",
            data={"payload": json.dumps(request)},
            files=[("files", (filename, filename.encode(), "text/plain"))],
        )
        assert response.status_code == 200
        results.append(response.json())

    assert results[0]["entry_id"] == results[1]["entry_id"]
    assert results[0]["duplicate"] is False
    assert results[1]["duplicate"] is True
    markdown = (corpus_dir / "2026-07-19.md").read_text(encoding="utf-8")
    assert markdown.count(f"Entry ID:        {results[0]['entry_id']}") == 1
    assert results[0]["uploads"][0] in markdown
    assert results[1]["uploads"][0] in markdown


def test_manual_upload_limit_failure_leaves_no_files_or_entry(
    authenticated_client, monkeypatch, tmp_path
):
    import modules.hfl_corpus.entry_create as entry_create
    import modules.hfl_corpus.router as hfl_routes

    corpus_dir = tmp_path / "corpus"
    inbox_dir = tmp_path / "dumps"
    monkeypatch.setattr(hfl_routes, "_uses_remote_corpus", lambda: False)
    monkeypatch.setattr(hfl_routes, "resolve_corpus_root", lambda: corpus_dir)
    monkeypatch.setattr(entry_create, "resolve_upload_inbox", lambda: inbox_dir)
    monkeypatch.setattr(entry_create, "MAX_UPLOAD_FILE_BYTES", 3)
    request = _create_entry_payload()
    request["attachment_names"] = ["large.bin"]

    response = authenticated_client.post(
        "/hfl-corpus/entries/upload",
        data={"payload": json.dumps(request)},
        files=[("files", ("large.bin", b"four", "application/octet-stream"))],
    )

    assert response.status_code == 400
    assert "50 MB per-file upload limit" in response.json()["detail"]
    assert not (corpus_dir / "2026-07-19.md").exists()
    assert not any((inbox_dir / "uploads").rglob("large.bin"))


def test_corpus_write_api_requires_bearer_token(authenticated_client):
    response = authenticated_client.post(
        "/api/hfl/entries",
        json=_create_entry_payload(),
    )

    assert response.status_code == 401


def test_corpus_write_api_persists_on_canonical_host(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.api as hfl_api

    persisted = []
    monkeypatch.setattr(hfl_api, "resolve_corpus_root", lambda: "C:/canonical")
    monkeypatch.setattr(
        hfl_api,
        "persist_manual_entry",
        lambda payload, *, corpus_dir: persisted.append(corpus_dir) or {
            "entry_id": "hfl-api",
            "path": "C:/canonical/2026-07-19.md",
            "duplicate": False,
            "indexed": True,
            "delivery": "persisted",
        },
    )
    monkeypatch.setattr(
        hfl_api.corpus_index,
        "documents",
        lambda force=False: (),
    )

    response = authenticated_client.post(
        "/api/hfl/entries",
        json=_create_entry_payload(),
        headers={"Authorization": "Bearer frontend-test-hfl-api-token"},
    )

    assert response.status_code == 200
    assert response.json()["entry_id"] == "hfl-api"
    assert persisted == ["C:/canonical"]


def test_corpus_upload_api_requires_bearer_token(authenticated_client):
    request = _create_entry_payload()
    request["attachment_names"] = ["notes.txt"]

    response = authenticated_client.post(
        "/api/hfl/entries/upload",
        data={"payload": json.dumps(request)},
        files=[("files", ("notes.txt", b"notes", "text/plain"))],
    )

    assert response.status_code == 401


def test_remote_client_posts_manual_entry_with_bearer_token(monkeypatch):
    from modules.hfl_corpus.remote import RemoteCorpusClient

    captured = {}

    def fake_post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return httpx.Response(
            200,
            json={
                "entry_id": "hfl-remote",
                "path": "/corpus/2026-07-19.md",
                "duplicate": False,
                "indexed": True,
                "delivery": "persisted",
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(
        remote_module,
        "_http_client",
        lambda: SimpleNamespace(post=fake_post),
    )

    result = RemoteCorpusClient(
        "http://canonical:8081", "secret"
    ).create_entry(_create_entry_payload())

    assert result["entry_id"] == "hfl-remote"
    assert captured["url"] == "http://canonical:8081/api/hfl/entries"
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["json"]["moment"] == "Captured a useful thought"


def test_remote_client_returns_enriched_manual_entry_preview(monkeypatch):
    from modules.hfl_corpus.remote import RemoteCorpusClient

    request_payload = _create_entry_payload()

    def fake_post(url, **kwargs):
        enriched = {**request_payload, "tags": request_payload["tags"] + " #contextual"}
        return httpx.Response(
            200,
            json={
                "filename": "2026-07-19.md",
                "markdown": "preview",
                "html": "<p>preview</p>",
                "payload": enriched,
                "enrichment": {
                    "location_source": "browser",
                    "location_label": "Singapore",
                    "added_tags": ["contextual"],
                    "notices": [],
                },
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(
        remote_module,
        "_http_client",
        lambda: SimpleNamespace(post=fake_post),
    )

    result = RemoteCorpusClient(
        "http://canonical:8081", "secret"
    ).preview_entry(request_payload)

    assert result["payload"]["tags"].endswith("#contextual")
    assert result["enrichment"]["location_source"] == "browser"


def test_remote_client_forwards_manual_entry_files_as_multipart(monkeypatch):
    from starlette.datastructures import UploadFile

    from modules.hfl_corpus.remote import RemoteCorpusClient

    captured = {}

    def fake_post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return httpx.Response(
            200,
            json={
                "entry_id": "hfl-remote",
                "path": "/corpus/2026-07-19.md",
                "duplicate": False,
                "indexed": True,
                "delivery": "persisted",
                "uploads": ["/Users/harqis-one/dumps/uploads/notes.txt"],
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(
        remote_module,
        "_http_client",
        lambda: SimpleNamespace(post=fake_post),
    )
    upload = UploadFile(filename="notes.txt", file=io.BytesIO(b"notes"))
    request = _create_entry_payload()
    request["attachment_names"] = ["notes.txt"]

    result = RemoteCorpusClient(
        "http://canonical:8081", "secret"
    ).create_entry_with_uploads(request, [upload])

    assert result["uploads"] == ["/Users/harqis-one/dumps/uploads/notes.txt"]
    assert captured["url"] == "http://canonical:8081/api/hfl/entries/upload"
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert json.loads(captured["data"]["payload"])["moment"] == "Captured a useful thought"
    assert captured["files"][0][1][0] == "notes.txt"
    assert captured["timeout"] == 300.0


def test_manual_entry_enrichment_prefers_owntracks_and_appends_context(monkeypatch):
    from modules.hfl_corpus.entry_create import CreateEntryRequest
    import modules.hfl_corpus.entry_enrichment as enrichment

    request = _create_entry_payload()
    request.update({
        "browser_latitude": 1.20,
        "browser_longitude": 103.70,
        "browser_location_status": "available",
    })
    seen = {}
    monkeypatch.setattr(
        enrichment,
        "_owntracks_fix",
        lambda when: (1.2644, 103.8222),
    )
    monkeypatch.setattr(
        enrichment,
        "_reverse_geocode",
        lambda latitude, longitude: seen.update(
            {"coordinates": (latitude, longitude)}
        ) or "VivoCity, HarbourFront",
    )
    monkeypatch.setattr(
        enrichment,
        "_suggest_tags",
        lambda payload, *, place="": ("thoughts", "shopping", "reflection"),
    )

    enriched, result = enrichment.enrich_manual_entry(
        CreateEntryRequest.model_validate(request)
    )

    assert seen["coordinates"] == (1.2644, 103.8222)
    assert result["location_source"] == "owntracks"
    assert result["location_label"] == "VivoCity, HarbourFront"
    assert result["added_tags"] == ["shopping", "reflection"]
    assert "#notes #manual-entry #thoughts #shopping #reflection" == enriched.tags
    assert "[VivoCity, HarbourFront](https://www.openstreetmap.org/search?" in enriched.references
    assert enriched.browser_latitude is None
    assert enriched.browser_longitude is None


def test_manual_entry_enrichment_falls_back_to_browser_location(monkeypatch):
    from modules.hfl_corpus.entry_create import CreateEntryRequest
    import modules.hfl_corpus.entry_enrichment as enrichment

    request = _create_entry_payload()
    request.update({
        "browser_latitude": 1.3521,
        "browser_longitude": 103.8198,
    })
    monkeypatch.setattr(enrichment, "_owntracks_fix", lambda when: None)
    monkeypatch.setattr(
        enrichment,
        "_reverse_geocode",
        lambda latitude, longitude: "Singapore",
    )
    monkeypatch.setattr(enrichment, "_suggest_tags", lambda payload, *, place="": ())

    enriched, result = enrichment.enrich_manual_entry(
        CreateEntryRequest.model_validate(request)
    )

    assert result["location_source"] == "browser"
    assert result["location_label"] == "Singapore"
    assert "[Singapore](https://www.openstreetmap.org/search?query=Singapore)" in enriched.references


def test_manual_entry_enrichment_failures_keep_manual_content(monkeypatch):
    from modules.hfl_corpus.entry_create import CreateEntryRequest
    import modules.hfl_corpus.entry_enrichment as enrichment

    monkeypatch.setattr(enrichment, "_owntracks_fix", lambda when: None)
    monkeypatch.setattr(
        enrichment,
        "_suggest_tags",
        lambda payload, *, place="": (_ for _ in ()).throw(RuntimeError("offline")),
    )

    enriched, result = enrichment.enrich_manual_entry(
        CreateEntryRequest.model_validate(_create_entry_payload())
    )

    assert enriched.tags == "#notes #manual-entry #thoughts"
    assert enriched.references == _create_entry_payload()["references"]
    assert result["location_source"] == "unavailable"
    assert len(result["notices"]) == 2


def test_manual_entry_preview_returns_the_exact_enriched_save_payload(
    authenticated_client, monkeypatch
):
    from modules.hfl_corpus.entry_create import CreateEntryRequest
    import modules.hfl_corpus.router as hfl_routes

    def fake_enrich(payload: CreateEntryRequest):
        enriched = payload.model_copy(
            update={
                "tags": payload.tags + " #contextual",
                "references": payload.references + "\n[Singapore](https://example.com/map)",
            }
        )
        return enriched, {
            "location_source": "owntracks",
            "location_label": "Singapore",
            "added_tags": ["contextual"],
            "notices": [],
        }

    monkeypatch.setattr(hfl_routes, "enrich_manual_entry", fake_enrich)

    response = authenticated_client.post(
        "/hfl-corpus/entries/preview",
        json=_create_entry_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["payload"]["tags"].endswith("#contextual")
    assert "[Singapore](https://example.com/map)" in body["payload"]["references"]
    assert body["enrichment"]["location_source"] == "owntracks"


def test_markdown_external_reference_uses_short_label(tmp_path):
    from services.safe_paths import resolve_reference

    source = tmp_path / "entry.md"
    source.write_text("entry", encoding="utf-8")

    reference = resolve_reference(
        "[VivoCity](https://www.openstreetmap.org/search?query=VivoCity)",
        source_document=source,
        corpus_root=tmp_path,
    )

    assert reference.kind == "external"
    assert reference.label == "VivoCity"
    assert reference.href == "https://www.openstreetmap.org/search?query=VivoCity"
