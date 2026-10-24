from workflows.second_brain.migrate_hud_dumps import legacy_dump


def test_legacy_dump_is_bounded_redacted_and_preserves_timestamp(tmp_path):
    path = tmp_path / 'dump.txt'
    path.write_text('password=private-value\n' + 'row\n' * 40000)
    payload, captured = legacy_dump({'payload': {'notes_path':str(path)}}, tmp_path)
    assert len(payload['text']) <= 12000
    assert 'private-value' not in payload['text']
    assert captured.endswith('Z')
    assert payload['migration'] == 'legacy-dump'


def test_legacy_dump_refuses_paths_outside_configured_root(tmp_path):
    path = tmp_path / 'dump.txt'
    path.write_text('private')
    assert legacy_dump({'payload': {'notes_path':str(path)}}, tmp_path / 'skins') is None


def test_legacy_dump_never_replaces_captured_text(tmp_path):
    assert legacy_dump({'payload': {'text':'already captured','notes_path':str(tmp_path/'dump.txt')}}, tmp_path) is None


def test_legacy_dump_skips_empty_and_missing_files(tmp_path):
    path = tmp_path / 'dump.txt'
    assert legacy_dump({'payload':{'notes_path':str(path)}}, tmp_path) is None
    path.write_text('')
    assert legacy_dump({'payload':{'notes_path':str(path)}}, tmp_path) is None
