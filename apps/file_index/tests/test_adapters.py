import io
import json
import socket
import stat
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest

from apps.file_index import adapters, service
from apps.file_index.store import Store


def public_dns(host, port, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port))]


def test_http_scan_retrieval_pins_address_and_streams(tmp_path, monkeypatch):
    client_type = httpx.Client
    calls = []
    def transport(request):
        calls.append(request)
        assert request.url.host == '93.184.216.34'
        assert request.headers['host'] == 'example.com'
        assert request.extensions['sni_hostname'] == 'example.com'
        return httpx.Response(200, headers={'content-length': '5', 'content-type': 'text/plain'},
                              content=b'hello' if request.method == 'GET' else b'')
    monkeypatch.setattr(socket, 'getaddrinfo', public_dns)
    monkeypatch.setattr(httpx, 'Client', lambda **kw: client_type(transport=httpx.MockTransport(transport), **kw))
    store = Store(tmp_path / 'catalog.db')
    source = store.add('sources', {'kind': 'http', 'root': 'https://example.com/file.txt', 'enabled': True})
    service.scan(source['id'], store)
    file = store.catalog()['items'][0]
    assert file['size'] == 5
    output = tmp_path / 'file'
    service.retrieve_file(file['id'], output, store)
    assert output.read_bytes() == b'hello'
    assert [r.method for r in calls] == ['HEAD', 'GET']


def test_http_rebinding_and_redirects_are_rejected(monkeypatch):
    sequence = iter([public_dns('example.com',443), [(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))]])
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **kw: next(sequence))
    with httpx.Client() as client, pytest.raises(PermissionError):
        with adapters.http_request(client, 'GET', 'https://example.com/file'):
            pass
    monkeypatch.setattr(socket, 'getaddrinfo', public_dns)
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(302, headers={'Location':'http://127.0.0.1/private'}))) as client:
        with adapters.http_request(client, 'GET', 'https://example.com/file') as response:
            with pytest.raises(httpx.HTTPStatusError):
                response.raise_for_status()


def test_sftp_discovery_and_retrieval(tmp_path, monkeypatch):
    class Remote:
        def normalize(self, path):
            return path
        def listdir_iter(self, path, **kw):
            return [SimpleNamespace(filename='brief.txt', st_mode=stat.S_IFREG, st_size=5, st_mtime=123)]
        def stat(self, path):
            return SimpleNamespace(st_size=5, st_mtime=123)
        def open(self, path, mode):
            assert path == '/documents/brief.txt'
            return io.BytesIO(b'hello')
    @contextmanager
    def connection(source):
        yield Remote()
    monkeypatch.setattr(adapters, 'sftp', connection)
    store = Store(tmp_path/'catalog.db')
    source = store.add('sources', {'kind':'sftp','root':'/documents','profile':'server','enabled':True})
    service.scan(source['id'],store)
    file = store.catalog()['items'][0]
    output=tmp_path/'download'
    service.retrieve_file(file['id'],output,store)
    assert output.read_bytes()==b'hello'
    with pytest.raises(PermissionError):
        adapters.remote_path(Remote(), source, '/elsewhere/secret')


def test_sftp_requires_known_hosts_and_scoped_profile(tmp_path, monkeypatch):
    import paramiko
    config=tmp_path/'profiles.json'
    config.write_text(json.dumps({'server':{'hostname':'server.test','username':'reader','root':'/documents'}}))
    monkeypatch.setenv('FILES_SFTP_PROFILES_PATH',str(config))
    called=[]
    class Client:
        def load_system_host_keys(self): called.append('known_hosts')
        def set_missing_host_key_policy(self, policy): assert isinstance(policy,paramiko.RejectPolicy)
        def connect(self,*a,**kw): raise OSError('untrusted host')
        def close(self): called.append('closed')
    monkeypatch.setattr(paramiko,'SSHClient',Client)
    source={'profile':'server','root':'/documents'}
    with pytest.raises(OSError):
        with adapters.sftp(source): pass
    assert called==['known_hosts','closed']
    with pytest.raises(PermissionError): adapters.sftp_profile({**source,'root':'/etc'})


def test_drive_pagination_and_incomplete_search():
    from apps.google_apps.references.web.api.drive import ApiServiceGoogleDrive
    class Files:
        def __init__(self): self.tokens=[];self.incomplete=False
        def list(self,**kw):
            self.tokens.append(kw.get('pageToken'))
            page={'files':[{'id':'second'}]} if kw.get('pageToken') else {'files':[{'id':'first'}],'nextPageToken':'next'}
            if self.incomplete: page['incompleteSearch']=True
            return SimpleNamespace(execute=lambda:page)
    service=ApiServiceGoogleDrive.__new__(ApiServiceGoogleDrive)
    service._files=Files()
    assert [f['id'] for f in service.iter_files('test')]==['first','second']
    assert service._files.tokens==[None,'next']
    service._files.incomplete=True
    with pytest.raises(RuntimeError): list(service.iter_files('test'))


def test_reference_registration_is_unknown_and_preserves_existing_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv('FILES_ALLOWED_ROOTS',json.dumps([str(tmp_path)]))
    monkeypatch.setenv('FILES_HOST_ID','host')
    store=Store(tmp_path/'catalog.db')
    source=store.add('sources',{'kind':'local','root':str(tmp_path),'host':'host'})
    file=service.register_reference(source['id'],str(tmp_path/'new.txt'),'new.txt',store=store)
    assert store.locations(file['id'])[0]['status']=='unknown'
    assert not file.get('last_seen')
    store.patch('files',file['id'],{'size':123,'last_seen':456})
    service.register_reference(source['id'],str(tmp_path/'copy.txt'),'copy.txt',file_id=file['id'],store=store)
    assert store.get('files',file['id'])['size']==123
    assert store.get('files',file['id'])['last_seen']==456
