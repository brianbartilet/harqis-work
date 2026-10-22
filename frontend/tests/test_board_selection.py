"""Selecting a board must replace the example/cache with current board content."""
from pathlib import Path
import pytest
from test_hfl_ideas import ideas
from test_hfl_boards import board_payload


def test_board_selection_exits_example_and_loads_graph(ideas, authenticated_client):
    pw = pytest.importorskip('playwright.sync_api')
    topic = ideas.topic('A current board member')['id']
    board = ideas.save_map(board_payload(name='Selected board', members=[topic]))
    other = ideas.save_map(board_payload(name='Second board', drafts=[{'id':'draft:second','title':'Second board thought','body':'Other'}], root='draft:second'))
    with pw.sync_playwright() as engine:
        options = {'headless': True}
        if not Path(engine.chromium.executable_path).exists(): options['channel'] = 'msedge'
        browser = engine.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={'width':1440,'height':1000})
            requests = []
            def route_request(route):
                r = route.request
                requests.append(r.url)
                response = authenticated_client.request(r.method, r.url.replace('http://board.test',''),
                    content=r.post_data_buffer, headers={'content-type':r.headers.get('content-type','application/json')})
                route.fulfill(status=response.status_code, body=response.content,
                              headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-encoding','content-length'}})
            page.route('http://board.test/**', route_request)
            page.goto('http://board.test/hfl-corpus/graph?example=1')
            page.wait_for_function('window.HflIdeas?.maps.loaded.length === 2')
            page.locator('[data-board-id="'+board['id']+'"]').click()
            pw.expect(page.locator('.idea-map-status')).to_contain_text('Board ready')
            assert 'example=1' not in page.url
            assert any('/maps/'+board['id']+'/graph?' in url for url in requests)
            pw.expect(page.locator('#kg-map-title')).to_have_text('Selected board')
            page.locator('[data-board-id="'+other['id']+'"]').click()
            pw.expect(page.locator('.idea-map-status')).to_contain_text('Board ready')
            pw.expect(page.locator('#kg-map-title')).to_have_text('Second board')
            assert any('/maps/'+other['id']+'/graph?' in url for url in requests)
        finally:
            browser.close()
