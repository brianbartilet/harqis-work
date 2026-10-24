"""Prevent scheduled/manual routes drifting across the Windows/server boundary."""
from core.apps.sprout.app.celery import SPROUT
import workflows.config  # noqa: F401
from workflows.hud.tasks_config import WORKFLOWS_HUD
from workflows.queues import WorkflowQueue


PORTABLE = {'hud_calendar', 'hud_finance', 'hud_forex', 'hud_jira',
            'hud_api_costs', 'hud_logs', 'hud_radar', 'hermes_radar_export'}


def test_portable_schedules_and_manual_calls_use_host():
    for entry in WORKFLOWS_HUD.values():
        task = entry['task']
        if task.split('.')[-2] in PORTABLE:
            assert entry['options']['queue'] == WorkflowQueue.HOST
            assert SPROUT.amqp.router.route({}, task)['queue'].name == WorkflowQueue.HOST
            assert entry['options'].get('os', ['any']) == ['any']


def test_desktop_and_fulfillment_affinity_and_single_radar_schedule():
    for entry in WORKFLOWS_HUD.values():
        if entry['task'].split('.')[-2] in {'hud_gpt', 'hud_utils', 'hud_tcg'}:
            assert entry['options']['queue'] in {WorkflowQueue.HUD, WorkflowQueue.PEON}
            assert entry['options']['os'] == ['windows']
    assert not any('hud_data_only' in entry['task'] for entry in WORKFLOWS_HUD.values())
    assert sum(entry['task'].endswith('.show_daily_radar') for entry in WORKFLOWS_HUD.values()) == 1


def test_schedule_export_handles_directory_mount(tmp_path, monkeypatch):
    from workflows.hud.tasks.hud_logs import _write_schedule_mapping
    monkeypatch.chdir(tmp_path)
    mount = tmp_path / 'workflows.mapping'
    mount.mkdir()
    target = _write_schedule_mapping('schedule data')
    assert target == mount / 'workflows.mapping'
    assert target.read_text() == 'schedule data'
    assert mount.is_dir()


def test_schedule_export_preserves_legacy_file(tmp_path, monkeypatch):
    from workflows.hud.tasks.hud_logs import _write_schedule_mapping
    monkeypatch.chdir(tmp_path)
    target = _write_schedule_mapping('schedule data')
    assert target == tmp_path / 'workflows.mapping'
    assert target.read_text() == 'schedule data'
