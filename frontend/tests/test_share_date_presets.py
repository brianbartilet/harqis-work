"""Recent-day filters stay editable, persist, and roll live shares forward."""
from dataclasses import replace
from datetime import date

import pytest
from starlette.datastructures import FormData

from modules.hfl_shares.date_filters import date_presets, resolve_date_preset
from modules.hfl_shares.models import ShareConfiguration
from modules.hfl_shares.scope import build_snapshot
from test_action_editing import editor_page
from test_hfl_ideas import ideas
from test_hfl_shares import sharing_corpus, _form
from test_workspace_sharing import context


@pytest.fixture
def fixed_today(monkeypatch):
    from modules.hfl_shares import date_filters
    original = date_filters.date_presets
    monkeypatch.setattr(date_filters, 'date_presets', lambda today=None: original(today or date(2026, 7, 10)))


def test_date_presets_inclusive_and_calendar_boundaries():
    assert date_presets(date(2026, 1, 5))['15'] == {'date_from': '2025-12-22', 'date_to': '2026-01-05'}
    assert date_presets(date(2024, 3, 1))['30']['date_from'] == '2024-02-01'
    for days in (15, 30, 90):
        values = date_presets(date(2026, 7, 10))[str(days)]
        assert (date.fromisoformat(values['date_to']) - date.fromisoformat(values['date_from'])).days == days - 1


def test_preset_persists_and_live_window_rolls(sharing_corpus, fixed_today, monkeypatch):
    from modules.hfl_shares.router import _configuration_from_form
    from modules.hfl_shares.store import get_share_store
    cfg = _configuration_from_form(FormData(_form(from_days='15', date_field='updated')))
    saved = get_share_store().save_configuration(cfg)
    assert get_share_store().get_configuration(saved.id).from_days == 15
    snapshot = build_snapshot(saved, (sharing_corpus,))
    assert len(snapshot.entries) == 1
    assert snapshot.filters['date_field'] == 'entry'
    assert snapshot.filters['date_from'] == '2026-06-26'
    later = resolve_date_preset(saved, date(2026, 8, 10))
    assert later.date_from == '2026-07-27'
    from modules.hfl_shares import date_filters
    monkeypatch.setattr(date_filters, 'date_presets', lambda today=None: date_presets(date(2026, 8, 10)))
    assert not build_snapshot(saved, (sharing_corpus,)).entries
    # A fixed snapshot retains its original resolved range.
    assert snapshot.filters['date_to'] == '2026-07-10'
    manual = replace(saved, from_days=0, date_from='2026-01-01', date_to='2026-01-02')
    assert resolve_date_preset(manual) == manual
    with pytest.raises(ValueError, match='From days'):
        replace(saved, from_days=14)


def test_preset_bounds_exclude_old_and_future_entries(sharing_corpus, fixed_today):
    old = replace(sharing_corpus.entries[0], header='2026-06-25 09:30', anchor='old', text='Old')
    first = replace(old, header='2026-06-26 09:30', anchor='first', text='First day')
    future = replace(old, header='2026-07-11 09:30', anchor='future', text='Future')
    doc = replace(sharing_corpus, entries=(old, first, sharing_corpus.entries[0], future))
    cfg = ShareConfiguration(id='', name='Range', recipient='Test', sources=('__all__',), from_days=15)
    result = build_snapshot(cfg, (doc,))
    assert len(result.entries) == 2
    assert result.earliest == '2026-06-26' and result.latest == '2026-07-10'


@pytest.mark.parametrize('width', [1440, 390])
def test_preset_controls_and_error_recovery(editor_page, context, sharing_corpus, fixed_today, monkeypatch, width):
    from playwright.sync_api import expect
    from modules.hfl_shares import router
    page, _ = editor_page
    page.set_viewport_size({'width': width, 'height': 1000})
    page.goto('https://editing.test/sharing')
    page.locator('summary').filter(has_text='Tags, dates, and topic').click()
    preset = page.locator('#share-from-days')
    expect(preset).to_have_value('0')
    expect(page.locator('#date-from')).to_have_value('')
    page.locator('[data-specific-source]').evaluate_all("els => els.forEach(el => {el.checked = true; el.dispatchEvent(new Event('change', {bubbles:true}));})")
    for days in (15, 90, 30):
        preset.select_option(str(days))
        expect(page.locator('#date-from')).to_have_value(date_presets(date(2026, 7, 10))[str(days)]['date_from'])
        expect(page.locator('#date-to')).to_have_value('2026-07-10')
        expect(page.locator('#share-date-field')).to_have_value('entry')
    page.locator('#date-from').fill('2026-07-01')
    expect(preset).to_have_value('0')
    expect(page.locator('#date-from')).to_have_value('2026-07-01')
    preset.select_option('15')
    preset.select_option('0')
    expect(page.locator('#date-from')).to_have_value('')
    expect(page.locator('#date-to')).to_have_value('')
    original = router._build_preview_snapshot
    def bounded(request, configuration, disabled_reference_ids, **kwargs):
        if configuration.from_days != 15:
            raise ValueError('Selected activity exceeds the snapshot size limit. Narrow filters or deselect objects.')
        return original(request, configuration, disabled_reference_ids, **kwargs)
    monkeypatch.setattr(router, '_build_preview_snapshot', bounded)
    preset.select_option('30')
    page.get_by_role('tab', name='Entries', exact=True).click()
    page.locator('[data-share-date-recovery="15"]').click()
    expect(page.locator('[data-preview-ready]')).to_be_visible()
    expect(page.locator('[data-preview-error]')).to_have_count(0)
    expect(preset).to_have_value('15')
