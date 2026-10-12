"""Scrollable card content must not start a Kanban drag."""
import pytest
from playwright.sync_api import expect
from test_action_editing import editor_page
from test_hfl_ideas import ideas
from test_hfl_timeline import payload


@pytest.mark.parametrize('width', [390, 1440])
def test_code_scrolling_does_not_drag_card(editor_page, width, tmp_path):
    page, client = editor_page
    page.set_viewport_size({'width': width, 'height': 1000})
    markdown = '# Description\n\nA compact card.\n\n## Acceptance Criteria\n\n```text\n' + 'long code line ' * 30 + '\n```'
    item = client.post('/hfl-corpus/timeline/items', json=payload(description=markdown)).json()['item']
    page.goto('https://editing.test/hfl-corpus/actions?all=1')
    card = page.locator(f'[data-board-lanes] [data-followup-id="{item["id"]}"]')
    card.get_by_text('Description', exact=True).filter(has_not=page.locator('h1')).first.click()
    code = card.locator('.markdown-body pre').first
    expect(code).to_be_visible()
    assert code.evaluate('(el)=>el.scrollWidth > el.clientWidth')
    code.hover()
    page.mouse.wheel(220, 0)
    page.wait_for_function('(el)=>el.scrollLeft > 0', arg=code.element_handle())
    box = code.bounding_box()
    page.mouse.move(box['x'] + 30, box['y'] + box['height'] - 5)
    page.mouse.down()
    page.mouse.move(box['x'] + 120, box['y'] + box['height'] - 5, steps=8)
    expect(page.locator('.sortable-fallback')).to_have_count(0)
    assert page.locator('#followups-board').get_attribute('data-busy') != 'true'
    page.mouse.up()
    assert card.locator('.markdown-body h1').evaluate('(el)=>parseFloat(getComputedStyle(el).fontSize)') <= 16
    page.screenshot(path=str(tmp_path / f'kanban-markdown-{width}.png'))
