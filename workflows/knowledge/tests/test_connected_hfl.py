import pytest
from workflows.hfl.obsidian import export_vault

def entry(identity='one', text='An ordinary moment'):
    return dict(id=identity, title='A moment', text=text, date='2026-09-01',
                source='notes', tags=['work'], entities={'topics': ['work']})

def test__export_updates_conflicts_and_withdrawals(tmp_path):
    vault = tmp_path / 'vault'
    assert export_vault([entry()], vault)['written'] == 3
    assert export_vault([entry()], vault)['unchanged'] == 3
    personal = vault / 'Personal.md'
    personal.write_text('Keep my notes', encoding='utf-8')
    generated = next((vault / 'Entries').glob('*.md'))
    generated.write_text('My edited copy', encoding='utf-8')
    result = export_vault([entry(text='Updated source')], vault)
    assert len(result['conflicts']) == 1
    result = export_vault([], vault)
    assert result['conflicts'][0]['reason'] == 'withdrawal'
    assert generated.read_text('utf-8') == 'My edited copy'
    assert personal.read_text('utf-8') == 'Keep my notes'
    assert result['withdrawn'] == 2

def test__malicious_manifest_cannot_escape_vault(tmp_path):
    vault = tmp_path / 'vault'
    vault.mkdir()
    (vault / '.harqis-export.json').write_text('{"../outside.md":"x"}', encoding='utf-8')
    with pytest.raises(ValueError):
        export_vault([], vault)
