import base64
from email import policy
from email.parser import BytesParser
from unittest.mock import MagicMock

import pytest
from apps.google_apps.references.web.api.gmail import ApiServiceGoogleGmail


@pytest.fixture
def gmail(tmp_path, monkeypatch):
    monkeypatch.setenv('HARQIS_DATA_ROOT', str(tmp_path))
    service = object.__new__(ApiServiceGoogleGmail)
    service.user_id = 'me'
    service.service = MagicMock()
    service.service.users().messages().send().execute.return_value = {'id': 'sent-123'}
    service.service.reset_mock()
    return service


def test_attachment_and_duplicate_receipt(gmail, tmp_path):
    path = tmp_path / 'report.md'
    path.write_text('# Report\nVerified output', encoding='utf-8')
    first = gmail.send_email('owner@example.org', 'Report', 'Attached', attachments=[str(path)], operation_key='action:1:email:1')
    second = gmail.send_email('owner@example.org', 'Report', 'Attached', attachments=[str(path)], operation_key='action:1:email:1')
    assert first == second and first['id'] == 'sent-123'
    send = gmail.service.users().messages().send
    assert send.call_count == 1
    message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(send.call_args.kwargs['body']['raw']))
    attachment = list(message.iter_attachments())[0]
    assert attachment.get_filename() == 'report.md'
    assert attachment.get_payload(decode=True) == path.read_bytes()
    assert message['To'] == 'owner@example.org'
    assert first['attachments'][0]['sha256']
    with pytest.raises(ValueError, match='different email'):
        gmail.send_email('other@example.org', 'Report', 'Attached', attachments=[str(path)], operation_key='action:1:email:1')


def test_uncertain_send_is_not_retried(gmail):
    gmail.service.users().messages().send().execute.side_effect = TimeoutError()
    gmail.service.reset_mock()
    with pytest.raises(TimeoutError):
        gmail.send_email('owner@example.org', 'Report', 'Body', operation_key='uncertain')
    with pytest.raises(RuntimeError, match='outcome uncertain'):
        gmail.send_email('owner@example.org', 'Report', 'Body', operation_key='uncertain')
    assert gmail.service.users().messages().send.call_count == 1


def test_invalid_attachment_and_headers_do_not_send(gmail, tmp_path):
    with pytest.raises(ValueError):
        gmail.send_email('owner@example.org', 'Bad\nBcc: other@example.org', 'Body')
    with pytest.raises(ValueError):
        gmail.send_email('owner@example.org', 'Report', 'Body', attachments=[str(tmp_path / 'missing')])
    gmail.service.users().messages().send.assert_not_called()


def test_mcp_exposes_send_with_stable_key(monkeypatch):
    from apps.google_apps import mcp as module
    tools = {}
    class Registry:
        def tool(self):
            def register(function):
                tools[function.__name__] = function
                return function
            return register
    module.register_google_apps_tools(Registry())
    service = MagicMock()
    service.send_email.return_value = {'id': 'receipt'}
    monkeypatch.setattr(module, 'ApiServiceGoogleGmail', lambda config: service)
    assert tools['send_gmail_email']('owner@example.org', 'Report', 'Body', 'operation:email:1')['id'] == 'receipt'
    assert 'search_gmail' in tools
    with pytest.raises(ValueError):
        tools['send_gmail_email']('owner@example.org', 'Report', 'Body', '')
