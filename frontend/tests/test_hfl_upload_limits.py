"""Boundary coverage for manual, task, client and browser upload policies."""
import asyncio
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.datastructures import UploadFile


def payload(names):
    from modules.hfl_corpus.entry_create import CreateEntryRequest
    return CreateEntryRequest(date='2026-07-19', time='12:00', moment='Uploads',
                              what_happened='Boundary test', attachment_names=names)


def test_manual_preview_attachment_count():
    assert len(payload([f'{i}.txt' for i in range(50)]).attachment_names) == 50
    with pytest.raises(ValidationError):
        payload([f'{i}.txt' for i in range(51)])


@pytest.mark.parametrize('manual', [False, True])
@pytest.mark.parametrize('size', [5, 6])
def test_streamed_size_boundary_and_cleanup(tmp_path, monkeypatch, manual, size):
    from modules.hfl_corpus import attachments, entry_create
    uploads = [UploadFile(BytesIO(b'x' * size), filename='file.bin')]
    if manual:
        monkeypatch.setattr(entry_create, 'MAX_UPLOAD_FILE_BYTES', 5)
        monkeypatch.setattr('workflows.hfl.persistence.persist_envelope', lambda *a, **kw: {})
        run = entry_create.persist_manual_entry_with_uploads(
            payload(['file.bin']), uploads, corpus_dir=tmp_path / 'corpus', inbox_dir=tmp_path / 'inbox')
        error = ValueError
    else:
        monkeypatch.setattr(attachments, 'MAX_FILE_BYTES', 5)
        store = attachments.AttachmentStore(tmp_path / 'attachments.sqlite3')
        run = store.upload('actionable:test', uploads)
        error = HTTPException
    if size == 6:
        with pytest.raises(error, match='500 MB'):
            asyncio.run(run)
        assert not list(tmp_path.rglob('file.bin'))
        if not manual:
            assert store.list('actionable:test') == []
    else:
        result = asyncio.run(run)
        path = Path(result['uploads'][0]) if manual else store.path(result[0])
        assert path.read_bytes() == b'x' * size
    assert not list(tmp_path.rglob('.upload-*'))
    assert not list(tmp_path.rglob('.staging'))


def test_client_accepts_fifty_max_size_files_and_rejects_overflow(tmp_path, monkeypatch):
    from apps.hfl_corpus.references.web.api.management import ApiServiceHflCorpusManagement
    service = object.__new__(ApiServiceHflCorpusManagement)
    request = Mock(return_value=Mock(json=lambda: {'attachments': []}))
    monkeypatch.setattr(service, '_raw_request', request)
    source = tmp_path / 'large.bin'
    # Sparse file exercises real stat/open validation without allocating 25 GB.
    with source.open('wb') as stream:
        stream.truncate(500 * 1024 * 1024)
    paths = [str(source)] * 50
    assert service.upload_attachments('actions', 'test', paths) == {'attachments': []}
    assert len(request.call_args.kwargs['files']) == 50
    with pytest.raises(ValueError, match='1–50'):
        service.upload_attachments('actions', 'test', paths + [str(source)])
    with source.open('ab') as stream:
        stream.write(b'x')
    with pytest.raises(ValueError, match='500 MB'):
        service.upload_attachments('actions', 'test', [str(source)])
    assert request.call_count == 1


@pytest.mark.parametrize('with_payload', [False, True])
def test_requests_transport_streams_multipart_in_bounded_reads(tmp_path, monkeypatch, with_payload):
    from types import SimpleNamespace
    from email.parser import BytesParser
    from email.policy import default
    import requests
    from apps.hfl_corpus.references.web.base_api_service import BaseApiServiceHflCorpus

    reads = []
    class GuardedFile:
        def __init__(self, stream):
            self.stream = stream
        def __getattr__(self, name):
            return getattr(self.stream, name)
        def read(self, size=-1):
            assert 0 <= size <= 65536, 'multipart transport attempted an unbounded read'
            reads.append(size)
            return self.stream.read(size)

    source = tmp_path / 'stream.bin'
    source.write_bytes(b'x' * 150000)
    def send(session, prepared, **kwargs):
        assert not isinstance(prepared.body, (bytes, str))
        assert not reads  # Preparing the request must not eagerly read files.
        assert prepared.headers['Authorization'] == 'Bearer test-token'
        chunks = []
        while chunk := prepared.body.read(65536):
            chunks.append(chunk)
        body = b''.join(chunks)
        assert int(prepared.headers['Content-Length']) == len(body)
        message = BytesParser(policy=default).parsebytes(
            ('Content-Type: ' + prepared.headers['Content-Type'] + '\r\n\r\n').encode() + body)
        parts = list(message.iter_parts())
        file_parts = [part for part in parts if part.get_filename()]
        assert [part.get_filename() for part in file_parts] == ['one.bin', 'two.bin']
        assert all(part.get_payload(decode=True) == source.read_bytes() for part in file_parts)
        if with_payload:
            assert parts[0].get_payload(decode=True) == b'{"moment":"stream"}'
        response = requests.Response()
        response.status_code = 200
        response._content = b'{}'
        return response

    monkeypatch.setattr(requests.Session, 'send', send)
    service = SimpleNamespace(api_token='test-token', client=SimpleNamespace(
        timeout=30, verify=True, base_url='http://upload.test/api/hfl'))
    with source.open('rb') as one, source.open('rb') as two:
        response = BaseApiServiceHflCorpus._raw_request(service, 'POST', 'entries/upload',
            data={'payload': '{"moment":"stream"}'} if with_payload else None,
            files=[('files', ('one.bin', GuardedFile(one), 'application/octet-stream')),
                   ('files', ('two.bin', GuardedFile(two), 'application/octet-stream'))])
    assert response.status_code == 200
    assert reads


@pytest.mark.parametrize('width', [390, 1100])
def test_browser_limit_boundaries(width):
    from web import templates
    playwright = pytest.importorskip('playwright.sync_api')
    markup = templates.env.get_template('modules/hfl_corpus/partials/input_attachments.html').render(memory_csrf='test')
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': width, 'height': 900})
        page.set_content(markup)
        page.add_script_tag(path=str(Path(__file__).resolve().parents[1] / 'static/js/hfl-input-attachments.js'))
        page.evaluate("window.editor = new HflInputAttachments(document.querySelector('[data-input-editor]'), 'pin')")
        assert '50 files, 500 MB each' in page.inner_text('body')
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        result = page.evaluate('''() => {
            const check = (count, size) => {
                editor.pending = Array.from({length: count}, (_, i) => ({name: `${i}.bin`, size}));
                try { editor.validate(); return 'ok'; } catch (error) { return error.message; }
            };
            return [check(50, 500 * 1024 * 1024), check(51, 1), check(1, 500 * 1024 * 1024 + 1)];
        }''')
        assert result[0] == 'ok'
        assert all('500 MB' in value for value in result[1:])
        browser.close()
