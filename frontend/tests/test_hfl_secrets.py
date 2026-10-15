from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from modules.hfl_corpus.corpus import CorpusDocument, CorpusEntry
from modules.hfl_corpus.secrets import (
    filter_documents,
    is_secret_entry,
    normalize_secret_tags,
)
from modules.hfl_shares.models import ALL_SOURCES, ShareConfiguration
from modules.hfl_shares.scope import build_snapshot
from modules.hfl_shares.security import make_csrf_token
from modules.hfl_shares.security import hash_pin
from modules.profile.models import OwnerProfile
from modules.profile.store import get_profile_store


def _entry(anchor: str, tag: str, text: str) -> CorpusEntry:
    return CorpusEntry(
        anchor=anchor,
        header="2026-08-13 10:00",
        moment=text,
        what_happened=text,
        tags=(tag,),
        source="manual-entry",
        text=f"2026-08-13 10:00\nMoment: {text}\nTags: #{tag}",
    )


def _document() -> CorpusDocument:
    entries = (
        _entry("public", "notes", "Visible note"),
        _entry("private", "Secrets", "Private detail"),
    )
    return CorpusDocument(
        relative_path="2026-08-13.md",
        path=None,
        name="2026-08-13.md",
        text="\n\n".join(f"## {entry.text}" for entry in entries),
        created_at=datetime(2026, 8, 13),
        updated_at=datetime(2026, 8, 13),
        tags=("notes", "secrets"),
        references=(),
        excerpt="Visible note Private detail",
        tag_counts=(("notes", 1), ("secrets", 1)),
        entry_count=2,
        entries=entries,
    )


def test_secret_tags_are_exact_normalized_and_filter_entry_text():
    tags = normalize_secret_tags(" #NSFW, secrets, #nsfw ")
    document = _document()

    assert tags == ("secrets", "nsfw")
    assert is_secret_entry(document.entries[1], tags)
    assert not is_secret_entry(_entry("near", "secrets-project", "Near"), tags)
    filtered = filter_documents((document,), tags)[0]
    assert [entry.anchor for entry in filtered.entries] == ["public"]
    assert "Private detail" not in filtered.text


def test_profile_pin_unlocks_for_authenticated_browser_session(authenticated_client):
    profile_form = {
        "csrf": make_csrf_token("frontend-test-user"),
        "secret_tags": "#secrets, #nsfw",
        "new_secret_pin": "123456",
        "confirm_secret_pin": "123456",
    }
    saved = authenticated_client.post("/profile", data=profile_form, follow_redirects=False)
    profile = get_profile_store().get()

    assert saved.status_code == 303
    assert profile.secret_pin_hash and "123456" not in profile.secret_pin_hash
    assert profile.secret_tags == "#secrets, #nsfw"
    denied = authenticated_client.post("/hfl-corpus/secrets/unlock", json={"pin": "111111"})
    unlocked = authenticated_client.post("/hfl-corpus/secrets/unlock", json={"pin": "123456"})
    assert denied.status_code == 403
    assert unlocked.status_code == 200
    assert authenticated_client.cookies.get("hfl_secrets_unlocked")


def test_secret_pages_render_custom_pin_dialog_without_native_prompt(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as corpus_router

    get_profile_store().save(
        OwnerProfile(secret_pin_hash=hash_pin("002795"), secret_tags="#secrets")
    )
    document = _document()
    monkeypatch.setattr(corpus_router.corpus_index, "documents", lambda: (document,))
    monkeypatch.setattr(corpus_router.corpus_index, "get", lambda path: document)

    corpus_page = authenticated_client.get("/hfl-corpus")
    document_page = authenticated_client.get("/hfl-corpus/document/2026-08-13.md")
    sharing_page = authenticated_client.get("/sharing")

    for page in (corpus_page, document_page, sharing_page):
        assert page.status_code == 200
        assert "data-secrets-pin-dialog" in page.text
        assert 'inputmode="numeric"' in page.text
        assert 'pattern="[0-9]{6}"' in page.text
        assert "window.prompt" not in page.text
    assert "requestHflSecretsUnlock" in corpus_page.text
    assert "requestHflSecretsUnlock" in document_page.text
    assert "requestHflSecretsUnlock" in sharing_page.text
    assert 'data-secrets-toggle' in corpus_page.text
    assert 'role="switch"' in corpus_page.text
    assert 'aria-checked="false"' in corpus_page.text
    assert ">Secrets<" in corpus_page.text
    assert 'class="secrets-toggle-track"' in corpus_page.text
    assert 'class="secrets-toggle-thumb"' in corpus_page.text
    assert '[data-secrets-toggle][aria-checked="true"]' in corpus_page.text
    assert '<button type="button" data-secrets-toggle' not in document_page.text
    for page in (corpus_page, document_page):
        assert "Show secrets" not in page.text
        assert "Hide secrets" not in page.text
    corpus_toggle = corpus_page.text.split(
        '<button type="button" data-secrets-toggle', 1
    )[1].split(">", 1)[0]
    assert 'data-corpus-header-actions class="corpus-header-actions"' in corpus_page.text
    assert "corpus-secrets-control" in corpus_toggle
    assert "bg-slate-900" not in corpus_toggle
    assert "bg-violet-900" not in corpus_toggle


def test_secrets_without_pin_offers_setup_without_direct_navigation(authenticated_client):
    page = authenticated_client.get('/hfl-corpus')
    assert page.status_code == 200
    assert '<button type="button" data-secrets-setup aria-haspopup="dialog"' in page.text
    assert 'data-secrets-setup-dialog' in page.text
    assert 'Set up your secrets PIN' in page.text
    assert 'href="/settings#corpus-secrets-title">Set up PIN in App Settings</a>' in page.text
    assert '<button type="button" data-secrets-toggle' not in page.text


def test_mixed_document_blurs_secret_entry_and_protects_editor(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as corpus_router

    get_profile_store().save(
        OwnerProfile(secret_pin_hash=hash_pin("123456"), secret_tags="#secrets")
    )
    document = _document()
    monkeypatch.setattr(corpus_router.corpus_index, "get", lambda path: document)

    page = authenticated_client.get("/hfl-corpus/document/2026-08-13.md")
    edit = authenticated_client.post(
        "/hfl-corpus/document/2026-08-13.md", json={"text": document.text}
    )

    assert page.status_code == 200
    assert "Visible note" in page.text
    assert "Private detail" not in page.text
    assert '<h2 id="private" class="scroll-mt-40">2026-08-13 10:00</h2>' in page.text
    assert "Hidden entry" in page.text
    assert "PIN protected" in page.text
    assert "Protected content is hidden." not in page.text
    assert "Secret entry" not in page.text
    assert 'data-secret-reveal="private"' in page.text
    assert edit.status_code == 403


def test_revealing_one_secret_entry_reveals_all_secrets_in_document(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as corpus_router

    get_profile_store().save(
        OwnerProfile(secret_pin_hash=hash_pin("123456"), secret_tags="#secrets")
    )
    original = _document()
    second_secret = _entry("private-two", "Secrets", "Another private detail")
    entries = (*original.entries, second_secret)
    document = replace(
        original,
        text="\n\n".join(f"## {entry.text}" for entry in entries),
        excerpt="Visible note Private detail Another private detail",
        tag_counts=(("notes", 1), ("secrets", 2)),
        entry_count=3,
        entries=entries,
    )
    monkeypatch.setattr(corpus_router.corpus_index, "get", lambda path: document)

    unlocked = authenticated_client.post(
        "/hfl-corpus/secrets/unlock", json={"pin": "123456"}
    )
    revealed = authenticated_client.get(
        "/hfl-corpus/document/2026-08-13.md?reveal=private"
    )

    assert unlocked.status_code == 200
    assert revealed.status_code == 200
    assert "Private detail" in revealed.text
    assert "Another private detail" in revealed.text
    assert "Hidden entry" not in revealed.text
    assert "data-secret-entry=" not in revealed.text


def test_share_snapshot_requires_explicit_secret_authorization():
    configuration = ShareConfiguration(
        id="", name="Secrets", recipient="Sam", sources=(ALL_SOURCES,),
        include_secrets=True,
    )
    document = _document()

    locked = build_snapshot(configuration, (document,), secret_tags=("secrets",))
    unlocked = build_snapshot(
        configuration, (document,), allow_secrets=True, secret_tags=("secrets",)
    )

    assert [entry.anchor for entry in locked.entries] == ["public"]
    assert {entry.anchor for entry in unlocked.entries} == {"public", "private"}
