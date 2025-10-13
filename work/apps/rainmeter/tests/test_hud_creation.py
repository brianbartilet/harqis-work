import pytest

from work.apps.rainmeter.references.helpers.config_builder import init_config, ConfigHelperRainmeter
from work.apps.rainmeter.config import CONFIG


@pytest.mark.skip
@init_config(
    CONFIG,
    hud_item_name="TEST HUD",
    new_sections_dict={
        "meterLink_google": {
            "Preset": "InjectedByTest",
            "W": "181"  # values must be strings
        }
    },
)
def test_update_quick_links(ini=ConfigHelperRainmeter()):

    dump = ''
    url = 'https://www.google.com/'
    ini['meterLink']['tooltiptext'] = url
    ini['meterLink']['Meter'] = 'String'
    ini['meterLink']['MeterStyle'] = 'sItemLink'
    ini['meterLink']['Text'] = 'HELLO WORLD'

    #  region Link: meterLink_google
    url = 'https://www.google.com/'
    ini['meterLink_google']['tooltiptext'] = url
    ini['meterLink_google']['Meter'] = 'String'
    ini['meterLink_google']['MeterStyle'] = 'sItemLink'
    ini['meterLink_google']['X'] = '(9*#Scale#)'
    ini['meterLink_google']['Y'] = '(50*#Scale#)'
    ini['meterLink_google']['W'] = '181'
    ini['meterLink_google']['H'] = '14'
    ini['meterLink_google']['StringStyle'] = 'Italic'
    ini['meterLink_google']['Text'] = 'HELLO GOOGLE'
    ini['meterLink_google']['LeftMouseUpAction'] = '!Execute["{0}" 3]'.format(url)
    #  endregion

    return dump

