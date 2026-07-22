from dataclasses import replace
from datetime import datetime, timedelta

import httpx

from modules.hfl_corpus import corpus as corpus_module
from modules.hfl_corpus.corpus import (
    CorpusDocument,
    CorpusEntry,
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
    entries=None,
):
    if entries is None and entry_count:
        entries = (
            CorpusEntry(
                anchor="hfl-entry-1-test-entry",
                header="Test entry",
                moment="A useful moment",
                what_happened="Something worth remembering",
                tags=tags,
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
    assert documents[0].entries[0].anchor == "hfl-entry-1-2026-07-10-09-30"
    assert documents[0].matching_text_entries("USEFUL LESSON") == documents[0].entries
    assert documents[0].matching_text_entries("useful retrospective") == ()
    assert documents[0].references == ("https://example.com/source",)


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
    assert "max-h-16" in index_response.text
    assert "overflow-y-auto" in index_response.text
    assert 'flex max-h-16 flex-wrap gap-2 overflow-y-auto p-1' in index_response.text
    assert "1 entries" in index_response.text
    assert "root cause story" not in index_response.text
    assert 'title="1 entries in this document"' in index_response.text
    assert index_response.text.index("1 entries</p>") < index_response.text.index(
        'class="mt-2 flex flex-wrap items-center gap-1.5"'
    )


def test_document_orders_entries_before_references_and_floating_navigator(
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
    references_position = response.text.index(">References</h2>")
    navigator_position = response.text.index('aria-label="Document tag navigator"')
    assert entry_position < references_position < navigator_position
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
    tags_heading = '<p class="mb-1.5 text-xs font-medium text-slate-500">Tags</p>'
    assert response.text.index('name="date_field"') < response.text.index(tags_heading)
    assert response.text.index(">Search</button>") < response.text.index(tags_heading)
    assert response.text.index(">Reset</a>") < response.text.index(tags_heading)
    assert "#debugging" in response.text
    assert "bg-blue-950/50" in response.text
    assert ">1</span>" in response.text
    assert "0 matches" in response.text


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
    assert ">Enter search</label>" in response.text
    assert 'placeholder="Search tags or query string"' in response.text
    assert 'aria-label="How corpus search works"' in response.text
    assert "every space-delimited tag must match" in response.text
    assert response.text.count('aria-pressed="true"') == 2
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
    assert "sticky top-24" in response.text
    assert "md:top-14" in response.text
    assert "fixed inset-x-4 bottom-4" not in response.text
    assert ">Document results</h2>" in response.text
    assert response.text.index(">Directory tree</h2>") < response.text.index(
        ">Document results</h2>"
    )


def test_corpus_mobile_layout_prioritizes_search_results(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    document = _document("2026-07-10.md")
    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: (document,))

    response = authenticated_client.get("/hfl-corpus")

    assert response.status_code == 200
    main = response.text.split('data-corpus-index', 1)[1].split('>', 1)[0]
    assert "overflow-x-hidden" in main
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
    assert "sticky top-24" in response.text
    assert "md:top-14" in response.text


def test_corpus_mobile_date_filters_are_collapsed_but_desktop_fields_remain_visible(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    document = _document("2026-07-10.md")
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
    assert "peer-focus-visible:ring-2" in filters
    assert "peer-focus-visible:ring-blue-500" in filters
    assert 'id="mobile-date-filter-fields"' in filters
    assert ">Date filters<" in filters
    assert "lg:hidden" in filters
    assert "hidden" in fields_opening
    assert "peer-checked:grid" in fields_opening
    assert "lg:contents" in fields_opening
    assert filters.count('class="block') == 3
    assert filters.count("lg:block") == 3
    assert 'name="date_field"' in filters
    assert 'name="date_from"' in filters
    assert 'name="date_to"' in filters


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

    card_marker = '<article class="rounded-xl bg-slate-900'
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

    card_marker = '<article class="rounded-xl bg-slate-900'
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

    document = _document("2026-07-10.md", tags=("debugging",))
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
    assert "sticky top-24" in response.text
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
    assert response.json()["documents"][0]["relative_path"] == "2026-07-10.md"
    assert response.json()["results"][0]["entries"][0]["moment"] == "A useful moment"


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
    assert result["page"] == 1
    assert result["page_size"] == 20
    assert result["total_pages"] == 1
    assert result["has_next"] is False
    assert result["documents"] == ()
    assert result["tree"]["files"][0].path is None
    assert result["tree"]["files"][0].relative_path == "2026-07-19.md"
    assert (
        result["results"][0].first_matching_entry_anchor("hfl")
        == "hfl-entry-1-remote"
    )


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

    monkeypatch.setattr(httpx, "get", legacy_get)

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
