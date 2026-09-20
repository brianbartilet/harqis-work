"""Preset transitions and motion against isolated graph data, desktop and mobile."""
from pathlib import Path
import time
import pytest

@pytest.mark.parametrize('mobile', [False, True])
def test_presets_motion_and_large_graph(authenticated_client, monkeypatch, tmp_path, mobile):
    playwright = pytest.importorskip('playwright.sync_api')
    from modules.hfl_corpus import entities
    anchors = [dict(id=f'{kind}:{i}',kind=kind,label=f'{kind} {i}')
               for kind in ['sources','people','tools','companies'] for i in range(2)]
    anchors += [dict(id='daily:2026-09-'+d,kind='daily',label='2026-09-'+d) for d in ['01','20']]
    rows = [dict(id='entry:'+str(i),kind='entries',label='Activity '+str(i),source='notes',date='2026-09-20') for i in range(5990)]
    def graph(*args):
        count=args[3] or 6000
        nodes=(anchors+rows)[:count]
        edges=[dict(source=n['id'],target=anchors[i%len(anchors)]['id']) for i,n in enumerate(nodes[10:])]
        return dict(nodes=nodes,edges=edges,total_nodes=6000,sources=['notes'])
    monkeypatch.setattr(entities,'graph',graph)
    with playwright.sync_playwright() as engine:
        options={'headless':True}
        if not Path(engine.chromium.executable_path).exists(): options['channel']='msedge'
        browser=engine.chromium.launch(**options)
        try:
            page=browser.new_page(viewport={'width':390 if mobile else 1440,'height':844 if mobile else 1000},has_touch=mobile,is_mobile=mobile)
            errors,requests=[],[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            def route_request(route):
                r=route.request;requests.append(r.url)
                response=authenticated_client.request(r.method,r.url.replace('http://graph.test',''),content=r.post_data,
                    headers={'content-type':r.headers.get('content-type','application/json')})
                route.fulfill(status=response.status_code,body=response.content,
                    headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-encoding','content-length'}})
            page.route('http://graph.test/**',route_request)
            started=time.monotonic();page.goto('http://graph.test/hfl-corpus/graph')
            page.wait_for_selector('#kg-workspace:not([inert])')
            print(f'Overview usable ({mobile=}): {time.monotonic()-started:.2f}s')
            assert page.locator('#kg-canvas').get_attribute('data-preset')=='timeline'
            assert not page.locator('#kg-shared').is_checked()
            assert page.locator('#kg-save').count()==0 and page.locator('#kg-group').count()==0
            for preset in ['timeline','people','tools','companies','sources']:
                page.click('#kg-open-views')
                panel=page.locator('#kg-views-panel').bounding_box()
                assert panel['x']>=0 and panel['x']+panel['width']<=page.viewport_size['width']+1
                before=len([r for r in requests if '/entities/graph?' in r])
                page.click('[data-preset="'+preset+'"]')
                assert page.locator('#kg-loading').is_hidden()
                assert page.locator('#kg-canvas').get_attribute('data-preset')==preset
                assert len([r for r in requests if '/entities/graph?' in r])==before
                page.wait_for_timeout(1100)
            canvas=page.locator('#kg-canvas canvas').first
            for mode in ['breathing','ripple','drift']:
                page.click('#kg-open-animation');page.click('[data-animation="'+mode+'"]')
                page.wait_for_timeout(300)
                image=canvas.evaluate('(el)=>el.toDataURL()')
                page.wait_for_timeout(300)
                assert canvas.evaluate('(el)=>el.toDataURL()')!=image
            page.reload();page.wait_for_selector('#kg-workspace:not([inert])')
            assert page.locator('#kg-canvas').get_attribute('data-animation')=='drift'
            assert page.locator('#kg-animation-pill').text_content()=='Drift'
            pill=page.locator('#kg-animation-pill').bounding_box()
            assert pill['x']>=0 and pill['x']+pill['width']<=page.viewport_size['width']
            page.locator('#kg-list button').first.click()
            page.wait_for_function("document.querySelector('#kg-canvas').dataset.motion==='paused'")
            page.wait_for_timeout(100)
            image=canvas.evaluate('(el)=>el.toDataURL()')
            page.wait_for_timeout(300)
            assert canvas.evaluate('(el)=>el.toDataURL()')==image
            page.get_by_role('button',name='Clear selection',exact=True).click()
            page.wait_for_function("document.querySelector('#kg-canvas').dataset.motion==='drift'")
            page.click('#kg-open-filters')
            page.wait_for_function("document.querySelector('#kg-canvas').dataset.motion==='paused'")
            page.click('#kg-close-filters')
            page.click('#kg-open-animation');page.click('[data-animation="off"]')
            page.wait_for_timeout(900)
            image=canvas.evaluate('(el)=>el.toDataURL()');page.wait_for_timeout(300)
            assert canvas.evaluate('(el)=>el.toDataURL()')==image
            page.screenshot(path=str(tmp_path/('presets-mobile.png' if mobile else 'presets-desktop.png')))
            for detail in ['1000','0']:
                start=time.monotonic();page.select_option('#kg-density',detail)
                page.wait_for_selector('#kg-workspace:not([inert])')
                print(f'Detail {detail} ({mobile=}): {time.monotonic()-start:.2f}s')
                assert ('6000 / 6000' if detail=='0' else '1000 / 6000') in page.locator('#kg-status').text_content()
            page.click('#kg-open-animation');page.click('[data-animation="breathing"]')
            gaps=page.evaluate("""() => new Promise(resolve => {
              const gaps=[]; let last=performance.now(),start=last;
              function frame(now){gaps.push(now-last);last=now;if(now-start>=1200)resolve(gaps);else requestAnimationFrame(frame);}
              requestAnimationFrame(frame);
            })""")
            print(f'6000-node animation ({mobile=}): {len(gaps)} browser frames / 1.2s; longest gap {max(gaps):.0f}ms')
            assert max(gaps)<1000
            page.click('#kg-open-animation');page.click('[data-animation="off"]')
            page.emulate_media(reduced_motion='reduce')
            page.reload();page.wait_for_selector('#kg-workspace:not([inert])')
            assert page.locator('#kg-canvas').get_attribute('data-animation')=='off'
            assert page.locator('#kg-canvas').get_attribute('data-preset')=='sources'
            assert page.locator('#kg-density').input_value()=='0'
            assert '6000 / 6000' in page.locator('#kg-status').text_content()
            page.click('#kg-reset');page.wait_for_selector('#kg-workspace:not([inert])')
            page.reload();page.wait_for_selector('#kg-workspace:not([inert])')
            assert page.locator('#kg-density').input_value()=='100'
            page.click('#kg-open-views');page.click('[data-preset="people"]')
            page.wait_for_timeout(1100)
            page.click('#kg-open-filters')
            page.select_option('#kg-rolling','30')
            page.check('#kg-shared')
            page.click('#kg-source-menu summary')
            page.get_by_label('notes',exact=True).check()
            page.click('#kg-filter')
            page.wait_for_selector('#kg-workspace:not([inert])')
            page.click('[data-activity-all]')
            page.wait_for_selector('#kg-workspace:not([inert])')
            page.click('#kg-in');page.wait_for_timeout(1100)
            state_script="JSON.parse(localStorage.getItem(Object.keys(localStorage).find(k=>k.startsWith('hfl:graph:state:v1:'))))"
            before=page.evaluate(state_script)
            assert before['preset']=='people' and before['all']
            page.reload();page.wait_for_selector('#kg-workspace:not([inert])')
            page.wait_for_timeout(800)
            after=page.evaluate(state_script)
            assert page.locator('#kg-canvas').get_attribute('data-preset')=='people'
            assert page.locator('#kg-rolling').input_value()=='30'
            assert page.locator('#kg-shared').is_checked()
            assert page.locator('[data-activity-all]').get_attribute('aria-checked')=='true'
            assert after['sources']==['notes']
            assert after['positions']==before['positions']
            assert after['viewport']['zoom']==pytest.approx(before['viewport']['zoom'])
            assert after['viewport']['x']==pytest.approx(before['viewport']['x'],abs=.01)
            assert after['viewport']['y']==pytest.approx(before['viewport']['y'],abs=.01)
            assert not any('/graph-views' in r for r in requests)
            assert not errors,errors
        finally: browser.close()


@pytest.mark.parametrize('mobile', [False, True])
def test_graph_action_editor_styles(authenticated_client, monkeypatch, mobile):
    playwright = pytest.importorskip('playwright.sync_api')
    from modules.hfl_corpus import entities
    monkeypatch.setattr(entities, 'graph', lambda *args: dict(nodes=[], edges=[], total_nodes=0, sources=[]))
    with playwright.sync_playwright() as engine:
        options = {'headless': True}
        if not Path(engine.chromium.executable_path).exists(): options['channel'] = 'msedge'
        browser = engine.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={'width':390 if mobile else 1440,'height':844})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            def route_request(route):
                r = route.request
                if '/timeline/source?' in r.url:
                    route.fulfill(json={'path':'day.md','entry_id':'hfl-test','title':'Follow up','date':'2026-09-20'})
                    return
                response = authenticated_client.request(r.method, r.url.replace('https://graph.test',''))
                route.fulfill(status=response.status_code, body=response.content,
                    headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-encoding','content-length'}})
            page.route('https://graph.test/**', route_request)
            page.goto('https://graph.test/hfl-corpus/graph?embed=1')
            page.evaluate("""() => {
                document.querySelector('#kg-entry-body').innerHTML = '<div class="corpus-entry-header"><h2>Entry</h2><a class="corpus-followup-action" href="/hfl-corpus?source_path=day.md&source_entry=hfl-test">Make actionable</a></div>';
                document.querySelector('#kg-entry-dialog').showModal();
            }""")
            page.get_by_text('Make actionable', exact=True).click()
            playwright.expect(page.locator('#followup-form input[name=title]')).to_have_value('Follow up')
            style = page.locator('#followup-editor').evaluate('(el)=>({background:getComputedStyle(el).backgroundColor,color:getComputedStyle(el).color})')
            assert style == {'background':'rgb(11, 18, 33)','color':'rgb(226, 232, 240)'}
            box = page.locator('#followup-editor').bounding_box()
            assert box['x'] >= 0 and box['x']+box['width'] <= page.viewport_size['width']
            assert box['y'] >= 0 and box['y']+box['height'] <= 844
            assert page.locator('#followup-form textarea[name=expected_outcome]').evaluate('(el)=>getComputedStyle(el).display') == 'block'
            page.get_by_role('button',name='Close follow-up editor').click()
            assert page.locator('#kg-entry-dialog').is_visible()
            assert not errors, errors
        finally:
            browser.close()

def test_drag_keeps_neighbors_moving_after_pointer_stops(authenticated_client, monkeypatch):
    playwright = pytest.importorskip('playwright.sync_api')
    from modules.hfl_corpus import entities
    monkeypatch.setattr(entities, 'graph', lambda *args: dict(
        nodes=[dict(id='source',kind='sources',label='Source'),dict(id='a',kind='entries',label='Note A'),dict(id='b',kind='entries',label='Note B'),dict(id='person',kind='people',label='Person'),dict(id='c',kind='entries',label='Note C')],
        edges=[dict(source='source',target='a'),dict(source='source',target='b'),dict(source='a',target='person'),dict(source='person',target='c')],total_nodes=5,sources=[]))
    with playwright.sync_playwright() as engine:
        options={'headless':True}
        if not Path(engine.chromium.executable_path).exists(): options['channel']='msedge'
        browser=engine.chromium.launch(**options)
        try:
            page=browser.new_page(viewport={'width':1440,'height':1000})
            def route_request(route):
                response=authenticated_client.get(route.request.url.replace('http://graph.test',''))
                route.fulfill(status=response.status_code,body=response.content,
                    headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-encoding','content-length'}})
            page.route('http://graph.test/**',route_request)
            page.add_init_script('''(() => {
                const fillText=CanvasRenderingContext2D.prototype.fillText;
                CanvasRenderingContext2D.prototype.fillText=function(text,x,y,...args){
                    if((text==='◇'||text==='P') && this.canvas===document.querySelector('#kg-canvas canvas')){
                        const p=new DOMPoint(x,y).matrixTransform(this.getTransform());
                        window[text==='P'?'sharedCenter':'sourceCenter']={x:p.x/devicePixelRatio,y:p.y/devicePixelRatio};
                    }
                    return fillText.call(this,text,x,y,...args);
                };
            })();''')
            page.goto('http://graph.test/hfl-corpus/graph')
            page.wait_for_selector('#kg-workspace:not([inert])')
            page.wait_for_function('!!window.sourceCenter && !!window.sharedCenter')
            page.wait_for_timeout(500)
            center=page.evaluate('window.sourceCenter')
            shared_before=page.evaluate('window.sharedCenter')
            canvas=page.locator('#kg-canvas canvas').first
            box=canvas.bounding_box()
            x,y=box['x']+center['x'],box['y']+center['y']
            page.mouse.move(x,y);page.wait_for_timeout(100)
            page.wait_for_function("document.querySelector('#kg-canvas').style.cursor==='pointer'",timeout=3000)
            page.mouse.down()
            dx=120 if center['x']<box['width']/2 else -120
            dy=100 if center['y']<box['height']/2 else -100
            page.mouse.move(x+dx,y+dy,steps=8)
            first=canvas.evaluate('(el)=>el.toDataURL()')
            page.wait_for_timeout(150)
            assert canvas.evaluate('(el)=>el.toDataURL()')!=first
            shared_after=page.evaluate('window.sharedCenter')
            assert abs(shared_after['x']-shared_before['x'])+abs(shared_after['y']-shared_before['y'])>2
            page.mouse.up();page.mouse.move(box['x']+10,box['y']+10)
            page.wait_for_timeout(6500)
            final=canvas.evaluate('(el)=>el.toDataURL()')
            page.wait_for_timeout(300)
            assert canvas.evaluate('(el)=>el.toDataURL()')==final
        finally:
            browser.close()


@pytest.mark.parametrize('mobile', [False, True])
def test_filter_drawer_persists_all_controls(authenticated_client, monkeypatch, mobile):
    playwright = pytest.importorskip('playwright.sync_api')
    from modules.hfl_corpus import entities
    sample=[dict(id=kind,kind=kind,label=kind) for kind in ['sources','entries','people','tools','companies','daily','objects','topics']]
    monkeypatch.setattr(entities,'graph',lambda *args:dict(nodes=sample,edges=[],total_nodes=len(sample),sources=['notes','desktop']))
    with playwright.sync_playwright() as engine:
        options={'headless':True}
        if not Path(engine.chromium.executable_path).exists(): options['channel']='msedge'
        browser=engine.chromium.launch(**options)
        try:
            page=browser.new_page(viewport={'width':390 if mobile else 1440,'height':1000},has_touch=mobile,is_mobile=mobile)
            requests=[];errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            def route_request(route):
                r=route.request
                if '/entities/graph?' in r.url:requests.append(r.url)
                response=authenticated_client.get(r.url.replace('http://graph.test',''))
                route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-encoding','content-length'}})
            page.route('http://graph.test/**',route_request)
            page.goto('http://graph.test/hfl-corpus/graph')
            page.wait_for_selector('#kg-workspace:not([inert])')
            page.click('#kg-open-filters')
            page.select_option('#kg-rolling','90')
            page.check('#kg-shared')
            page.wait_for_selector('#kg-workspace:not([inert])')
            page.click('#kg-source-menu summary')
            page.get_by_label('notes',exact=True).check()
            page.locator('#kg-types label').filter(has=page.locator('input[data-kind="tools"]')).click()
            page.click('#kg-filter')
            page.wait_for_selector('#kg-workspace:not([inert])')
            page.reload();page.wait_for_selector('#kg-workspace:not([inert])')
            page.click('#kg-open-filters')
            assert page.locator('#kg-rolling').input_value()=='90'
            assert page.locator('#kg-since').is_disabled() and page.locator('#kg-until').is_disabled()
            assert page.locator('#kg-shared').is_checked()
            assert not page.locator('#kg-types input[data-kind="tools"]').is_checked()
            assert page.locator('#kg-types input[data-kind="people"]').is_checked()
            assert 'rolling=90' in requests[-1] and 'sources=notes' in requests[-1] and 'shared=true' in requests[-1]
            page.click('#kg-source-menu summary')
            assert page.get_by_label('notes',exact=True).is_checked()
            assert not page.get_by_label('desktop',exact=True).is_checked()
            page.select_option('#kg-rolling','0')
            page.fill('#kg-since','2026-09-01');page.fill('#kg-until','2026-09-15')
            page.click('#kg-filter');page.wait_for_selector('#kg-workspace:not([inert])')
            page.reload();page.wait_for_selector('#kg-workspace:not([inert])')
            page.click('#kg-open-filters')
            assert page.locator('#kg-rolling').input_value()=='0'
            assert page.locator('#kg-since').input_value()=='2026-09-01'
            assert page.locator('#kg-until').input_value()=='2026-09-15'
            assert page.locator('#kg-since').is_enabled()
            assert 'since=2026-09-01' in requests[-1] and 'until=2026-09-15' in requests[-1]
            assert not page.locator('#kg-types input[data-kind="tools"]').is_checked()
            assert not errors,errors
        finally:browser.close()
