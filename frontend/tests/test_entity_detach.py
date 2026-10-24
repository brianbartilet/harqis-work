"""Member splits preserve the retained identity and do not erase shared evidence."""
import json
from uuid import uuid4

from test_entity_merges import merge_data, submit_merge
from modules.hfl_corpus import entities
from workflows.hfl import entity_matching, entity_merges
from workflows.hfl.entity_store import get_store


def detach(client, identity, member):
    base = '/api/hfl/entities/merges/' + identity
    preview = client.post(base + '/detach-preview', json={'member_id': member})
    assert preview.status_code == 200, preview.text
    body = dict(member_id=member, preview_token=preview.json()['preview_token'], request_id=str(uuid4()))
    response = client.post(base + '/detach', json=body)
    assert response.status_code == 200, response.text
    return body, response.json()


def test_detach_shared_activity_profile_audit_and_retry(merge_data, authenticated_client):
    rows, ids, submitted = merge_data
    merged, _, _ = submit_merge(authenticated_client, ids)
    identity = merged['entity_id']
    members = authenticated_client.get(f'/api/hfl/entities/merges/{identity}/members').json()['members']
    assert {m['id'] for m in members} == set(ids)
    assert len(next(m for m in members if m['id'] == ids[0])['entries']) == 2
    body, result = detach(authenticated_client, identity, ids[1])
    directory = {e['id']: e for e in entities.entity_index()}
    assert set(directory) == {identity, ids[1]}
    assert {e['id'] for e in directory[identity]['entries']} == {r['id'] for r in rows}
    assert directory[ids[1]]['entries'][0]['id'] == rows[0]['id']
    profile = get_store().profiles()[identity]
    assert 'Alpha' not in profile['aliases']
    assert 'same@example.test' in profile['emails'] and '1@example.test' not in profile['emails']
    assert 'Note 1' not in profile['notes']
    with get_store().connection() as db:
        assert entity_matching.blocked(db, [identity, ids[1]])
        assert not entity_matching.blocked(db, [ids[0], ids[2]])
    assert authenticated_client.post(f'/api/hfl/entities/merges/{identity}/detach', json=body).json() == result
    assert len(submitted) == 2
    assert entity_merges.history(ids[1])[0]['action'] == 'member-detached'
    assert len(get_store().records()) == 2


def test_detach_preserves_incoming_queue_without_reopening_history(merge_data, authenticated_client, monkeypatch):
    monkeypatch.delenv('HARQIS_ENTITY_REASSESS_HISTORY', raising=False)
    rows, ids, _ = merge_data
    merged, _, _ = submit_merge(authenticated_client, ids)
    store = get_store()
    store.save('unrelated-history', 'v1', [])
    with store.connection() as db:
        db.execute('DELETE FROM entity_resolution_jobs')
        db.execute('INSERT INTO entity_resolution_jobs(entry_id,revision) VALUES (?,?)', ('incoming', 'v1'))
        db.execute('INSERT INTO entity_resolutions VALUES (?,?,?,?)',
                   (rows[0]['id'], ids[0], merged['entity_id'], json.dumps({'active': True})))
    body, result = detach(authenticated_client, merged['entity_id'], ids[1])
    assert authenticated_client.post(f"/api/hfl/entities/merges/{merged['entity_id']}/detach", json=body).json() == result
    with store.connection() as db:
        assert [tuple(r) for r in db.execute('SELECT entry_id,revision FROM entity_resolution_jobs')] == [('incoming', 'v1')]
        assert not json.loads(db.execute('SELECT data FROM entity_resolutions').fetchone()[0])['active']


def test_nested_member_detaches_without_dissolving_groups(merge_data, authenticated_client):
    _, ids, _ = merge_data
    child, _, _ = submit_merge(authenticated_client, ids[:2], 'Inner')
    root, _, _ = submit_merge(authenticated_client, [child['entity_id'], ids[2]], 'Outer')
    detach(authenticated_client, root['entity_id'], ids[0])
    assert get_store().resolve(ids[1]) == root['entity_id']
    assert get_store().resolve(ids[0]) == ids[0]
    assert 'Alex' not in get_store().profiles()[root['entity_id']]['aliases']
    # Removing the last nested member retires that empty branch, not the root.
    detach(authenticated_client, root['entity_id'], ids[1])
    assert get_store().resolve(ids[2]) == root['entity_id']
    assert {e['id'] for e in entities.entity_index()} == {root['entity_id'], ids[0], ids[1]}
    assert authenticated_client.post(f"/api/hfl/entities/merges/{root['entity_id']}/detach-preview",
                                     json={'member_id': ids[2]}).status_code == 409


def test_detach_subgroup_and_unmerge_remaining(merge_data, authenticated_client):
    _, ids, _ = merge_data
    child, _, _ = submit_merge(authenticated_client, ids[:2], 'Inner')
    root, _, _ = submit_merge(authenticated_client, [child['entity_id'], ids[2]], 'Outer')
    detach(authenticated_client, root['entity_id'], child['entity_id'])
    assert get_store().resolve(ids[0]) == child['entity_id']
    assert authenticated_client.post(f"/api/hfl/entities/merges/{root['entity_id']}/unmerge",
                                     json={'request_id': str(uuid4())}).status_code == 200
    assert {e['id'] for e in entities.entity_index()} == {child['entity_id'], ids[2]}


def test_stale_preview_and_token_scope(merge_data, authenticated_client):
    _, ids, _ = merge_data
    result, _, _ = submit_merge(authenticated_client, ids)
    identity = result['entity_id']; base = f'/api/hfl/entities/merges/{identity}'
    preview = authenticated_client.post(base + '/detach-preview', json={'member_id': ids[0]}).json()
    body = dict(member_id=ids[1], preview_token=preview['preview_token'], request_id=str(uuid4()))
    assert authenticated_client.post(base + '/detach', json=body).status_code == 409
    body['member_id'] = ids[0]
    profile = get_store().profiles()[identity]
    get_store().save_profile(identity, 'people', {**profile, 'notes': 'Edited in another tab'})
    assert authenticated_client.post(base + '/detach', json=body).status_code == 409
    assert get_store().resolve(ids[0]) == identity
    detach(authenticated_client, identity, ids[0])
    assert get_store().profiles()[identity]['notes'] == 'Edited in another tab'


def test_inherited_soul_rules_and_integrity_survive_split(merge_data, authenticated_client):
    from workflows.hfl.entity_soul import empty
    _, ids, _ = merge_data
    with get_store().connection() as db:
        soul = empty(); soul.pop('version'); soul['identity_rules'] = [{'id': 'rule', 'enabled': True}]
        db.execute('INSERT INTO entity_souls VALUES (?,1,?)', (ids[0], json.dumps(soul)))
    child, _, _ = submit_merge(authenticated_client, ids[:2], 'Inner')
    root, _, _ = submit_merge(authenticated_client, [child['entity_id'], ids[2]], 'Outer')
    with get_store().connection() as db:
        db.execute('INSERT INTO entity_integrity VALUES (?,?)', (root['entity_id'], json.dumps({'required': True})))
    detach(authenticated_client, root['entity_id'], ids[0])
    with get_store().connection() as db:
        assert json.loads(db.execute('SELECT data FROM entity_souls WHERE id=?', (root['entity_id'],)).fetchone()[0])['identity_rules'] == []
        assert json.loads(db.execute('SELECT data FROM entity_integrity WHERE id=?', (root['entity_id'],)).fetchone()[0])['required']
        assert json.loads(db.execute('SELECT data FROM entity_souls WHERE id=?', (ids[0],)).fetchone()[0])['identity_rules']


def test_detach_dialog_search_activity_and_owner_layout(merge_data, authenticated_client, monkeypatch, tmp_path):
    import pytest
    from pathlib import Path
    pw = pytest.importorskip('playwright.sync_api')
    rows, ids, _ = merge_data
    # The text search must match activity content that is absent from the title.
    rows[1]['text'] += ' unique dental evidence'
    cached = get_store().records()[rows[1]['id']]
    get_store().save(rows[1]['id'], entities.entry_hash(rows[1]), cached['mentions'])
    root, _, _ = submit_merge(authenticated_client, ids)
    original = entities.entity_index
    def directory(*args, **kwargs):
        result = original(*args, **kwargs)
        for entity in result:
            if entity['id'] == root['entity_id']: entity['is_owner'] = True
        return result
    monkeypatch.setattr(entities, 'entity_index', directory)
    with pw.sync_playwright() as engine:
        options = {'headless': True}
        if not Path(engine.chromium.executable_path).exists(): options['channel'] = 'msedge'
        browser = engine.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={'width': 1900, 'height': 1000})
            def route_request(route):
                request = route.request
                response = authenticated_client.request(request.method, request.url.replace('https://entities.test', ''),
                    content=request.post_data_buffer, headers={'content-type':request.headers.get('content-type','application/json')})
                route.fulfill(status=response.status_code, body=response.content,
                              headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-encoding','content-length'}})
            page.route('https://entities.test/**', route_request)
            page.goto('https://entities.test/hfl-corpus/entities')
            card = page.locator('[data-entity-id="' + root['entity_id'] + '"]')
            card.locator(':scope > summary').click()
            pw.expect(card.get_by_role('link', name='Corpus owner', exact=True)).to_be_visible()
            boxes = [card.get_by_role('button', name=name, exact=True).bounding_box() for name in ['Change type','Update soul','Detach','Unmerge']]
            assert max(b['y'] for b in boxes) - min(b['y'] for b in boxes) < 32, boxes
            assert card.evaluate('(d) => d.scrollWidth <= d.clientWidth + 1')
            card.locator('.entity-management-row').scroll_into_view_if_needed()
            page.screenshot(path=str(tmp_path / 'owner-controls.png'))
            for width in (1900, 390):
                page.set_viewport_size({'width': width, 'height': 1000})
                owner = card.get_by_role('link', name='Corpus owner', exact=True).bounding_box()
                controls = card.locator('.entity-management-row').bounding_box()
                assert owner['y'] + owner['height'] <= controls['y']
                assert card.evaluate('(d) => d.scrollWidth <= d.clientWidth + 1')
                card.screenshot(path=str(tmp_path / f'owner-row-{width}.png'))
            page.set_viewport_size({'width':1100,'height':900})
            assert card.evaluate('(d) => d.scrollWidth <= d.clientWidth + 1')
            card.get_by_role('button', name='Detach', exact=True).click()
            dialog = page.get_by_role('dialog', name='Detach members')
            pw.expect(dialog.locator('.detach-member')).to_have_count(3)
            dialog.get_by_role('searchbox').fill('unique dental evidence')
            pw.expect(dialog.locator('.detach-member')).to_have_count(2)
            beta = dialog.locator('.detach-member').filter(has=page.get_by_text('Beta', exact=True))
            beta.locator('summary').click()
            pw.expect(beta.get_by_text('Alex Alpha Beta 1 unique dental evidence', exact=True)).to_be_visible()
            page.screenshot(path=str(tmp_path / 'detach-desktop.png'))
            page.set_viewport_size({'width':390, 'height':844})
            assert dialog.evaluate('(d) => d.scrollWidth <= d.clientWidth + 1')
            page.screenshot(path=str(tmp_path / 'detach-mobile.png'))
            beta.get_by_role('button', name='Detach', exact=True).click()
            dialog.get_by_role('button', name='Confirm detach', exact=True).click()
            pw.expect(dialog.get_by_role('status')).to_contain_text('Detached “Beta”')
            assert get_store().resolve(ids[2]) == ids[2]
            print('UI screenshots:', tmp_path)
        finally:
            browser.close()
