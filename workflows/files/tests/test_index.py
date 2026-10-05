"""Real local task execution plus scheduling and signal contracts."""
import importlib
import json
from types import SimpleNamespace

from apps.file_index.store import Store
from workflows.files.tasks.index import scan_source, maintain_files


def test__scan_source(tmp_path, monkeypatch):
    root = tmp_path / 'documents'
    root.mkdir()
    (root / 'output.txt').write_text('content')
    monkeypatch.setenv('FILES_STORE_PATH', str(tmp_path / 'catalog.db'))
    monkeypatch.setenv('FILES_ALLOWED_ROOTS', json.dumps([str(root)]))
    monkeypatch.setenv('FILES_HOST_ID', 'host')
    source = Store().add('sources', {'name':'Documents','kind':'local','host':'host','root':str(root),'enabled':True,'interval_hours':24})
    result = scan_source(source['id'])
    assert result['count'] == 1
    assert Store().catalog()['total'] == 1


def test__maintain_files_queues_due_sources_once(tmp_path, monkeypatch):
    monkeypatch.setenv('FILES_STORE_PATH', str(tmp_path / 'catalog.db'))
    monkeypatch.setenv('FILES_ALLOWED_ROOTS', '[]')
    Store().add('sources', {'kind':'local','enabled':True,'interval_hours':24})
    calls=[]
    monkeypatch.setattr(scan_source, 'apply_async', lambda **kw: calls.append(kw) or SimpleNamespace(id='task-id'))
    assert maintain_files()['queued'] == ['task-id']
    assert maintain_files()['queued'] == []
    assert len(calls)==1


def test__task_registration_and_opt_in_schedule(monkeypatch):
    from core.apps.sprout.app.celery import SPROUT
    from workflows.files import tasks_config
    for name in ['scan_source','publish_package','maintain_files']:
        assert 'workflows.files.tasks.index.'+name in SPROUT.tasks
    with monkeypatch.context() as context:
        context.setenv('FILES_ENABLED','0')
        assert not importlib.reload(tasks_config).WORKFLOW_FILES
        context.setenv('FILES_ENABLED','1')
        assert len(importlib.reload(tasks_config).WORKFLOW_FILES)==1
    importlib.reload(tasks_config)


def test__output_paths_are_bounded_and_explicit():
    from workflows.files.output_signals import output_paths
    value={'text':'/not/a/declared/path','artifacts':[{'output_path':'/documents/result.pdf'}]}
    assert list(output_paths(value))==['/documents/result.pdf']


def test__maintenance_discovers_configured_roots_without_opening_ui(tmp_path, monkeypatch):
    monkeypatch.setenv('FILES_STORE_PATH', str(tmp_path / 'catalog.db'))
    monkeypatch.setenv('FILES_ALLOWED_ROOTS', json.dumps([str(tmp_path / 'documents')]))
    monkeypatch.setenv('FILES_HOST_ID', 'test-host')
    calls = []
    monkeypatch.setattr(scan_source, 'apply_async', lambda **kw: calls.append(kw) or SimpleNamespace(id='task-id'))
    assert maintain_files()['queued'] == ['task-id']
    assert len(Store().all('sources')) == 1
    assert maintain_files()['queued'] == []
    monkeypatch.setenv('FILES_ALLOWED_ROOTS', '[]')
    source, = Store().all('sources')
    Store().patch('sources', source['id'], {'last_queued': 0})
    assert maintain_files()['queued'] == []
    assert len(calls) == 1
