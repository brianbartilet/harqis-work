"""Representative activity-graph animation workload (no live corpus reads)."""
from pathlib import Path
import pytest


@pytest.mark.parametrize('width', [1440, 390])
def test_drift_frame_work(authenticated_client, monkeypatch, tmp_path, width):
    playwright = pytest.importorskip('playwright.sync_api')
    from modules.hfl_corpus import entities
    nodes = [dict(id=f'people:{i}', kind='people', label=f'Person {i}') for i in range(700)]
    nodes += [dict(id=f'entry:{i}', kind='entries', label=f'Activity {i}', date='2026-11-21', source='notes') for i in range(1014)]
    edges = [dict(source=f'entry:{i % 1014}', target=f'people:{(i // 1014 + i) % 700}') for i in range(4694)]
    monkeypatch.setattr(entities, 'graph', lambda *args: dict(nodes=nodes, edges=edges, total_nodes=len(nodes), sources=['notes']))
    with playwright.sync_playwright() as engine:
        options = {'headless': True}
        if not Path(engine.chromium.executable_path).exists():
            options['channel'] = 'msedge'
        browser = engine.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000})
            def route_request(route):
                r = route.request
                response = authenticated_client.request(r.method, r.url.replace('http://graph.test', ''), content=r.post_data)
                route.fulfill(status=response.status_code, body=response.content,
                              headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-encoding','content-length'}})
            page.route('http://graph.test/**', route_request)
            page.goto('http://graph.test/hfl-corpus/graph?embed=1')
            page.wait_for_selector('#kg-workspace:not([inert])')
            page.click('#kg-open-animation')
            page.click('[data-animation="drift"]')
            page.mouse.move(0, 0)
            page.wait_for_timeout(1200)
            result = page.evaluate('''() => new Promise(resolve => {
                const ctx=document.querySelector('#kg-canvas canvas').getContext('2d');
                const prototype=CanvasRenderingContext2D.prototype;
                const clear=ctx.clearRect, gradient=prototype.createRadialGradient;
                const times=[];let gradients=0;
                ctx.clearRect=function(...args){times.push(performance.now());return clear.apply(this,args);};
                prototype.createRadialGradient=function(...args){gradients++;return gradient.apply(this,args);};
                setTimeout(()=>{
                    ctx.clearRect=clear;prototype.createRadialGradient=gradient;
                    const gaps=times.slice(1).map((time,i)=>time-times[i]).sort((a,b)=>a-b);
                    resolve({frames:times.length,gradients,p95:gaps[Math.floor(gaps.length*.95)],max:gaps.at(-1),paused:document.querySelector('#kg-canvas').dataset.motion==='paused'});
                },9000);
            })''')
            print(f'Drift workload ({width=}):', result, flush=True)
            assert result['frames'] > 0 and not result['paused'], result
            assert result['gradients'] == 0, result
            page.screenshot(path=str(tmp_path / f'graph-animation-{width}.png'))
        finally:
            browser.close()
