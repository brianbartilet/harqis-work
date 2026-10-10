"""Structured machine environment must survive the launcher boundary."""
import json
from scripts import deploy


def test_machine_roots_are_json_not_python_repr(tmp_path, monkeypatch):
    from apps.file_index.local import configured_sources
    from apps.file_index.store import Store
    roots = [str(tmp_path / "Documents with spaces"), str(tmp_path / "O'Brien")]
    env = deploy.machine_env_vars({'env_vars': {'FILES_ALLOWED_ROOTS': roots}})
    monkeypatch.setenv('FILES_ALLOWED_ROOTS', env['FILES_ALLOWED_ROOTS'])
    assert json.loads(env['FILES_ALLOWED_ROOTS']) == roots
    assert {s['root'] for s in configured_sources(Store(tmp_path / 'files.db'))} == set(roots)


def test_machine_env_preserves_strings_scalars_and_precedence():
    values = deploy.machine_env_vars({'_shared': {'env_vars': {'PORT': 1, 'PATHS': ['old']}},
                                     'env_vars': {'PATHS': '["already-json"]', 'PORT': 2, 'FLAG': True}})
    assert values == {'PORT': '2', 'PATHS': '["already-json"]', 'FLAG': 'True'}
