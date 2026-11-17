"""Exercise the real status renderer with synthetic data, no network or providers."""
from pathlib import Path

import pytest


@pytest.mark.parametrize('automatic,current,title,detail', [
    ({'state': 'failed', 'created': 0, 'error': 'ValueError'},
     {'eligible': 0, 'dismissed': 10, 'total': 10}, 'Ideas saved', 'All 10 ideas are dismissed'),
    ({'state': 'partial', 'created': 8, 'duplicates': 0, 'deferred': 1,
      'diagnostic': {'reason': 'snapshot_conflict', 'stage': 'commit'}},
     {'eligible': 1, 'dismissed': 0, 'total': 9}, 'Ideas saved · automatic actions partial', 'snapshot_conflict'),
    ({'state': 'complete', 'created': 2, 'duplicates': 0, 'deferred': 0},
     {'eligible': 0, 'dismissed': 0, 'total': 2}, 'Review complete', '2 actions created'),
])
def test_renderer_separates_historical_result_from_current_eligibility(automatic, current, title, detail):
    playwright = pytest.importorskip('playwright.sync_api')
    source = (Path(__file__).parents[1] / 'static/js/hfl-timeline.js').read_text()
    # Isolate the unchanged production functions from unrelated editor bootstrapping.
    renderer = source[source.index('  function analysisStatus('):source.index("  document.getElementById('timeline-period-form').addEventListener")]
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page()
        page.route('**/*', lambda route: route.abort())
        page.set_content(''.join(f'<div id="{identity}"></div>' for identity in
            ['timeline-run', 'timeline-run-title', 'timeline-run-detail', 'timeline-suggestions',
             'timeline-explore', 'agenda-explore']))
        page.add_script_tag(content="""
            const endInput={value:'2026-09-09'}, today='2026-09-10'; let pollTimer;
            function node(tag,text,cls){const el=document.createElement(tag);el.textContent=text;return el;}
        """ + renderer)
        page.evaluate('(data) => renderSuggestions(data)', {'run': {
            'state': 'complete', 'updated_at': '2026-09-10T00:00:00Z',
            'result': {'automatic_actions': automatic}, 'current_automatic_actions': current,
        }, 'suggestions': [], 'receipts': [], 'items': []})
        assert page.locator('#timeline-run-title').inner_text() == title
        assert detail in page.locator('#timeline-run-detail').inner_text()
        if current['dismissed'] == current['total']:
            assert 'Historical automatic action result: failed' in page.locator('#timeline-run-detail').inner_text()
            assert 'retry' not in page.locator('#timeline-run-detail').inner_text().lower()
        browser.close()
