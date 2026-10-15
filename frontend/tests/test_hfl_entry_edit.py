import asyncio
import io
from dataclasses import replace
from pathlib import Path

import pytest
from starlette.datastructures import UploadFile

from modules.hfl_corpus import corpus, entry_edit
from modules.hfl_corpus.document_edit import DocumentConflictError
from modules.hfl_corpus.entry_edit import EntryUpdate, apply_update, entry_details, save_entry


TEXT = '''# Daily notes

## 2026-10-13 17:54
Source: notes
Machine: harqis-server
Entry ID: hfl-existing
Synthesized: false
Moment: Original
What happened: First line
  second line

Custom metadata: keep this exactly
Why it stayed: A reason
Possible use: Review
Tags: #notes
References:
- https://example.test/ticket
- /inbox/shared.pdf

## 2026-10-13 18:00
Source: imported
Entry ID: hfl-neighbor
Moment: Neighbor
What happened: Must remain unchanged
Tags: #private
'''


@pytest.fixture
def doc(tmp_path, monkeypatch):
    path = tmp_path / '2026-10-13.md'
    path.write_text(TEXT, encoding='utf-8')
    monkeypatch.setattr(corpus, 'resolve_corpus_root', lambda: tmp_path)
    index = corpus.CorpusIndex(ttl_seconds=0)
    document = index.documents(force=True)[0]
    monkeypatch.setattr(entry_edit.corpus_index, 'documents', lambda **kwargs: ())
    monkeypatch.setattr(entry_edit, 'sync_entry', lambda *args: True)
    return document


def payload(doc, **changes):
    data = entry_details(doc, doc.entries[0].anchor)
    data.pop('source'); data.pop('machine')
    return EntryUpdate(**(data | changes))


def test_patch_preserves_identity_unknown_metadata_and_neighbors(doc):
    updated, identity = apply_update(doc, payload(doc, moment='Updated', date='2026-10-12'))
    assert identity == 'hfl-existing'
    assert 'Custom metadata: keep this exactly\n' in updated
    assert 'Source: notes\nMachine: harqis-server\nEntry ID: hfl-existing\nSynthesized: false\n' in updated
    assert updated.split('## 2026-10-13 18:00')[1] == TEXT.split('## 2026-10-13 18:00')[1]
    assert '## 2026-10-12 17:54:00' in updated
    assert 'Moment: Updated' in updated


def test_noop_preserves_exact_document(doc):
    assert apply_update(doc, payload(doc))[0] == TEXT


def test_stale_or_mismatched_identity_rejected(doc):
    with pytest.raises(DocumentConflictError):
        apply_update(doc, payload(doc, expected_updated_at='old'))
    with pytest.raises(DocumentConflictError):
        apply_update(doc, payload(doc, entry_id='other'))


@pytest.mark.parametrize('changes', [
    {'what_happened': 'Bad\n## 2026-01-01'},
    {'moment': 'Bad\nEntry ID: forged'},
    {'references': ['file\n## new']},
    {'date': 'bad'},
])
def test_invalid_edits_rejected(doc, changes):
    with pytest.raises(ValueError):
        apply_update(doc, payload(doc, **changes))


def test_add_detach_and_search_warning(doc, tmp_path, monkeypatch):
    from workflows.hfl import entity_events
    monkeypatch.setattr(entity_events, 'notify_change', lambda *args: None)
    shared = tmp_path / 'shared.pdf'; shared.write_bytes(b'shared')
    monkeypatch.setattr(entry_edit, 'sync_entry', lambda *args: False)
    upload = UploadFile(filename='../../extra.txt', file=io.BytesIO(b'extra'))
    result = asyncio.run(save_entry(doc, payload(doc, references=['https://example.test/ticket']),
                                   [upload], corpus_dir=tmp_path, inbox_dir=tmp_path / 'inbox'))
    assert result['updated'] and result['warning']
    written = doc.path.read_text(encoding='utf-8')
    assert '/inbox/shared.pdf' not in written
    assert shared.read_bytes() == b'shared'
    assert len(list((tmp_path / 'inbox').rglob('extra.txt'))) == 1
    assert 'extra.txt' in written


def test_upload_removed_on_concurrent_write(doc, tmp_path, monkeypatch):
    def conflict(*args, **kwargs):
        raise DocumentConflictError('changed')
    monkeypatch.setattr(entry_edit, 'update_document_text', conflict)
    with pytest.raises(DocumentConflictError):
        asyncio.run(save_entry(doc, payload(doc), [UploadFile(filename='file.txt', file=io.BytesIO(b'data'))],
                               corpus_dir=tmp_path, inbox_dir=tmp_path / 'inbox'))
    assert not list((tmp_path / 'inbox').rglob('file.txt'))
    assert doc.path.read_text(encoding='utf-8') == TEXT


def test_size_limit_does_not_change_entry(doc, tmp_path, monkeypatch):
    monkeypatch.setattr(entry_edit, 'MAX_UPLOAD_FILE_BYTES', 2)
    with pytest.raises(ValueError, match='size limit'):
        asyncio.run(save_entry(doc, payload(doc), [UploadFile(filename='large', file=io.BytesIO(b'123'))],
                               corpus_dir=tmp_path, inbox_dir=tmp_path / 'inbox'))
    assert doc.path.read_text(encoding='utf-8') == TEXT


def test_entry_routes_require_csrf_and_protect_secrets(doc, authenticated_client, monkeypatch):
    import json
    from modules.hfl_corpus import router
    from modules.hfl_shares.security import make_csrf_token
    monkeypatch.setattr(router, '_uses_remote_corpus', lambda: False)
    monkeypatch.setattr(router.corpus_index, 'get', lambda path: doc)
    monkeypatch.setattr(router, 'normalize_secret_tags', lambda value: ('private',))
    monkeypatch.setattr(router, 'secrets_unlocked', lambda *args: False)
    url = '/hfl-corpus/entry-edit/' + doc.relative_path
    read = authenticated_client.get(url, params={'anchor': doc.entries[0].anchor})
    assert read.status_code == 200
    assert read.json()['entry_id'] == 'hfl-existing'
    assert authenticated_client.get(url, params={'anchor': doc.entries[1].anchor}).status_code == 403
    assert authenticated_client.post(url, data={'payload': json.dumps(payload(doc).model_dump())}).status_code == 403
    result = authenticated_client.post(url, headers={'X-CSRF-Token': make_csrf_token('frontend-test-user')},
                                       data={'payload': json.dumps(payload(doc, expected_updated_at='old').model_dump())})
    assert result.status_code == 409


def test_legacy_entry_gets_stable_id_without_source_rewrite(doc):
    legacy = replace(doc, text=doc.text.replace('Entry ID: hfl-existing\n', ''))
    text, identity = apply_update(legacy, payload(legacy, moment='Legacy edit'))
    assert identity.startswith('hfl-')
    assert 'Entry ID: ' + identity in text
    assert 'Source: notes' in text
