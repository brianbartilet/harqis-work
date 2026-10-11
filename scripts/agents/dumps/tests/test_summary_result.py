"""Exercise CLI output with an in-memory task; never import real publishers."""
import argparse
import ast
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


def load_cli():
    path = Path(__file__).parents[1] / 'run_dumps_summary_retro.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    ns = dict(argparse=argparse, json=json, sys=sys)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), ns)
    return ns


@pytest.mark.parametrize('result,status,exit_code', [
    ({'files_total': 3, 'bytes_total': 400, 'days': 7, 'days_with_dumps': 2}, 'success', 0),
    ({'files_total': 0, 'days': 7, 'days_with_dumps': 0}, 'no_data', 0),
    ({'files_total': 1, 'date': '2026-10-10', 'machines': 1}, 'success', 0),
    ({'error': 'PRIVATE'}, 'error', 1),
    ({'skipped': True, 'machine': 'PRIVATE'}, 'skipped', 2),
])
def test_cli_structured_result_and_exit_status(monkeypatch, capsys, result, status, exit_code):
    cli = load_cli()
    calls = []
    result.update(markdown='PRIVATE', text='PRIVATE', summary_files=['/private/log'])
    def task(**kwargs):
        calls.append(kwargs)
        return result
    monkeypatch.setitem(sys.modules, 'workflows.dumps.tasks.analyze', SimpleNamespace(analyze_daily_dumps=task))
    monkeypatch.setattr(sys, 'argv', ['summary', '--days', '7', '--device', 'nothing-phone', '--result-json'])
    assert cli['main']() == exit_code
    output = capsys.readouterr().out
    assert output.startswith('DUMPS_RESULT ')
    record = json.loads(output.removeprefix('DUMPS_RESULT '))
    assert record['status'] == status
    assert record['summary_files_count'] == 1
    assert 'private' not in output.lower()
    assert calls == [{'days': 7, 'machine': 'nothing-phone'}]


def test_default_cli_output_is_unchanged(monkeypatch, capsys):
    cli = load_cli()
    monkeypatch.setitem(sys.modules, 'workflows.dumps.tasks.analyze', SimpleNamespace(
        analyze_daily_dumps=lambda **kw: {'markdown': '# Summary', 'summary_files': ['/test/log']}))
    monkeypatch.setattr(sys, 'argv', ['summary'])
    assert cli['main']() == 0
    assert capsys.readouterr().out == '# Summary\n\nAppended to 1 log file(s):\n  /test/log\n'
