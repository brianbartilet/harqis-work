"""Scheduler migration changes execution mode without changing existing cadence."""
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import ModuleType
from zoneinfo import ZoneInfo


def test_reconcile_preserves_existing_schedule_and_disables_agent(monkeypatch, capsys, tmp_path):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / 'scripts/agents/hfl'))
    spec = importlib.util.spec_from_file_location('setup_consolidation', root / 'scripts/agents/hfl/setup_entity_consolidation.py')
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    jobs = ModuleType('cron.jobs')
    captured = []
    jobs.list_jobs = lambda **kw: [dict(id='existing', name='hfl-entity-consolidation-daily', schedule={'expr': '0 12 * * *'})]
    jobs.update_job = lambda identity, fields: captured.append((identity, fields)) or {'id': identity}
    jobs.create_job = lambda **kw: (_ for _ in ()).throw(AssertionError('must not create a second schedule'))
    clock = ModuleType('hermes_time')
    clock.get_timezone = lambda: ZoneInfo('Asia/Singapore')
    constants = ModuleType('hermes_constants')
    constants.get_hermes_home = lambda: tmp_path
    monkeypatch.setitem(sys.modules, 'cron', ModuleType('cron'))
    monkeypatch.setitem(sys.modules, 'cron.jobs', jobs)
    monkeypatch.setitem(sys.modules, 'hermes_time', clock)
    monkeypatch.setitem(sys.modules, 'hermes_constants', constants)
    config = json.loads((root / 'scripts/agents/hfl/entity_consolidation_schedule.json').read_text())
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(dict(spec=config, repo=str(root), apply=True, interpreter='python'))))
    exec(setup.PROGRAM, {})
    identity, fields = captured[0]
    assert identity == 'existing'
    assert fields['schedule'] == '0 12 * * *'
    assert fields['no_agent'] is True
    assert fields['script'] == 'harqis_entity_consolidation.py'
    launcher = (tmp_path / 'scripts' / fields['script']).read_text()
    assert 'run_entity_consolidation.py' in launcher
    compile(launcher, '<launcher>', 'exec')
    assert 'entire backlog' not in fields['prompt']
    assert json.loads(capsys.readouterr().out)['installed']
