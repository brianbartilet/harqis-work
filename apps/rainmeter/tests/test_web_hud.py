from apps.rainmeter.references.helpers import config_builder as builder
import pytest


def test_portable_collector_needs_no_desktop_configuration(monkeypatch):
    monkeypatch.delenv('HARQIS_LEGACY_RAINMETER', raising=False)
    @builder.init_meter({}, hud_item_name='SERVER')
    def collect(ini, **kwargs):
        return {'text': 'Server output'}
    assert collect()['renderer'] == 'web'
    with pytest.raises(ValueError, match='Missing required config'):
        collect(render_legacy_hud=True)


def test_web_renderer_preserves_output_without_skin_io(monkeypatch, tmp_path):
    monkeypatch.delenv('HARQIS_LEGACY_RAINMETER', raising=False)
    def forbidden(**kwargs):
        raise AssertionError('Web collection must not write Rainmeter resources')
    monkeypatch.setattr(builder, '_ensure_dirs_and_resources', forbidden)
    config = {'skin_name':'TEST', 'static_path':str(tmp_path), 'write_skin_to_path':str(tmp_path/'skins'), 'bin_path':'missing.exe'}
    @builder.init_meter(config, hud_item_name='WEB TEST')
    def collect(ini, **kwargs):
        assert ini.has_section('MeterDisplay')
        ini['meterLink']['Text'] = 'BOARD'
        ini['meterLink']['LeftMouseUpAction'] = '!Execute ["https://example.test/board" 3]'
        return {'text':'Captured rows', 'summary':'One item', 'metrics':{'count':1}}
    result = collect()
    assert result['text'] == 'Captured rows'
    assert result['metrics']['count'] == 1
    assert result['links'] == {'BOARD':'https://example.test/board'}
    assert result['renderer'] == 'web'
    assert not (tmp_path/'skins').exists()
