"""Recipient binding, additive Space context, and template isolation."""
from dataclasses import replace

import pytest

from modules.hfl_shares import activity, personalization
from modules.hfl_shares.models import ShareConfiguration
from modules.hfl_shares.scope import build_snapshot
from modules.hfl_shares.security import make_csrf_token
from modules.hfl_shares.store import get_share_store
from test_hfl_shares import sharing_corpus, _empty_share_store
from test_workspace_sharing import context
from test_action_editing import editor_page
from test_hfl_ideas import ideas


@pytest.fixture
def entities(monkeypatch, context):
    rows = [dict(id='entity:alex', label='Alex with a name longer than twenty characters', kind='people', count=1),
            dict(id='entity:acme', label='Acme', kind='companies', count=0)]
    monkeypatch.setattr(personalization, 'entity_catalog', lambda: rows)
    monkeypatch.setattr(activity, 'mentions_for_documents', lambda docs: [
        {'id': 'hfl-share-test', 'mentions': [rows[0] | {'label': rows[0]['label']}]}])
    return rows


def recipe(**kwargs):
    values = dict(id='', name='Personal activity', recipient='Untrusted name', sources=('__all__',),
                  entity_id='entity:alex', activity={'version':1, 'sections':['entries','actions','ideas','boards','plans','graph']})
    values.update(kwargs)
    return ShareConfiguration(**values)


def test_binding_filters_entries_and_keeps_related_entities(entities, context, sharing_corpus):
    snapshot = build_snapshot(recipe(), (sharing_corpus,))
    assert snapshot.recipient == entities[0]['label']
    assert len(snapshot.entries) == 1
    assert not snapshot.activity['actions']
    assert not snapshot.activity['ideas']
    assert not snapshot.activity['boards']
    assert build_snapshot(recipe(entity_id='entity:acme'), (sharing_corpus,)).all_entries == ()
    assert not build_snapshot(recipe(tags=('absent',)), (sharing_corpus,)).all_entries


def test_workspace_additions_and_explicit_links(entities, context, sharing_corpus):
    context['links'].append(dict(source='entity:acme', target='action:outside', relation='related-to'))
    cfg = recipe(entity_id='entity:acme', activity={'version':1,'sections':['entries','actions','ideas','graph'], 'workspace_ids':['work']})
    snapshot = build_snapshot(cfg, (sharing_corpus,))
    assert {o['id'] for o in snapshot.activity['actions']} == {'action:a','action:outside'}
    assert {o['id'] for o in snapshot.activity['ideas']} == {'idea:i'}
    assert snapshot.activity['inclusion_reasons']['action:a'] == 'Added workspace content'
    assert snapshot.activity['inclusion_reasons']['action:outside'] == 'Entity-linked activity'
    assert 'Secret-backed' not in str(snapshot.to_record())


def test_workspace_supporting_entries_and_exclusion(entities, context, sharing_corpus):
    context['actions'][0]['source'] = {'path':sharing_corpus.relative_path, 'entry_id':'hfl-share-test'}
    cfg = recipe(entity_id='entity:acme', activity={'version':1, 'sections':['entries','actions'], 'workspace_ids':['work']})
    snapshot = build_snapshot(cfg, (sharing_corpus,))
    assert [e.id for e in snapshot.entries] == ['hfl-share-test']
    assert snapshot.activity['inclusion_reasons']['entry:hfl-share-test'] == 'Supporting entry'
    excluded = replace(cfg, activity={**cfg.activity, 'excluded_ids':['entry:hfl-share-test']})
    assert not build_snapshot(excluded, (sharing_corpus,)).entries


def test_supporting_entries_resolve_legacy_evidence_ids(entities, context, sharing_corpus):
    from modules.hfl_corpus.timeline import entry_evidence_id
    legacy_id = entry_evidence_id(sharing_corpus.entries[0].text)
    context['actions'][0]['source'] = {'path':sharing_corpus.relative_path, 'entry_id':legacy_id}
    cfg = recipe(entity_id='entity:acme', activity={'version':1, 'sections':['entries','actions'], 'workspace_ids':['work']})
    assert [entry.id for entry in build_snapshot(cfg, (sharing_corpus,)).entries] == ['hfl-share-test']


def test_template_cannot_generate_unbound_and_does_not_keep_last_person(entities, context, sharing_corpus):
    cfg = recipe(entity_template=True)
    template = personalization.unbound_template(cfg)
    assert not template.entity_id and not template.recipient
    with pytest.raises(ValueError, match='Choose an entity'):
        build_snapshot(template, (sharing_corpus,))
    with pytest.raises(ValueError, match='unavailable or was merged'):
        build_snapshot(recipe(entity_id='missing'), (sharing_corpus,))
    assert build_snapshot(cfg, (sharing_corpus,)).recipient == entities[0]['label']
    assert not template.entity_id


def test_template_keeps_exclusions_and_reference_policy():
    cfg = recipe(entity_template=True, references_enabled=False, disabled_reference_ids=('reference:private',),
                 activity={'version':1, 'sections':['entries'], 'excluded_ids':['entry:private']})
    template = personalization.unbound_template(cfg)
    assert template.activity['excluded_ids'] == ['entry:private']
    assert template.disabled_reference_ids == ('reference:private',)
    assert not template.references_enabled


def test_personalized_instant_respects_references_and_saved_template(authenticated_client, entities, context, sharing_corpus):
    template = get_share_store().save_configuration(personalization.unbound_template(recipe(entity_template=True)))
    response = authenticated_client.post('/sharing/instant', data={
        'csrf':make_csrf_token('frontend-test-user'), 'configuration_id':template.id, 'name':'For Alex',
        'entity_id':'entity:alex', 'entity_template':'on', 'sources':'__all__', 'auth_mode':'qr',
        'no_expiry':'on', 'activity_version':'1', 'activity_sections':['entries','graph']})
    assert response.status_code == 200, response.text
    assert response.json()['references_enabled'] is False
    assert not get_share_store().get_configuration(template.id).entity_id


def test_picker_is_owner_only_and_does_not_return_profiles(authenticated_client, entities):
    result = authenticated_client.get('/sharing/personalization-options?q=Alex&kind=people')
    assert result.status_code == 200
    assert len(result.json()['entities']) == 1
    assert 'profile' not in result.json()['entities'][0]
    authenticated_client.cookies.clear()
    assert authenticated_client.get('/sharing/personalization-options').status_code == 401


@pytest.mark.parametrize('width', [1440, 390])
def test_share_with_browser(editor_page, entities, sharing_corpus, width, tmp_path, monkeypatch):
    from playwright.sync_api import expect
    from modules.hfl_corpus import workspace_views
    monkeypatch.setattr(workspace_views, 'listing', lambda: {'views':[{'id':'work','name':'Default'}]})
    page, client = editor_page
    page.set_viewport_size({'width':width, 'height':1000})
    page.goto('https://editing.test/sharing')
    page.locator('#recipient').fill('Existing draft')
    page.locator('[data-personalization] > summary').click()
    panel = page.locator('[data-share-with-form]')
    expect(panel.locator('[name="entity_template"]')).not_to_be_checked()
    expect(panel.locator('[name="all_sources"]')).to_be_checked()
    expect(panel.locator('#entity-type')).to_have_value('people')
    expect(panel.locator('[name="share_with_workspaces"]')).to_be_checked()
    panel.locator('#entity-search').fill('Alex')
    panel.locator('[data-entity-results] button').filter(has_text='Alex').click()
    expect(page.locator('#recipient')).to_have_value('Existing draft')
    panel.locator('[data-personal-review]').click()
    expect(page.locator('#recipient')).to_have_value(entities[0]['label'])
    expect(page.locator('#recipient')).to_be_editable()
    expect(page.locator('[data-preview-ready]')).to_be_visible(timeout=15000)
    expect(page.locator('[data-preview-ready]')).to_contain_text('Planned the Japan trip')
    expect(page.locator('[name="graph_view"]')).to_have_value('{"preset":"people"}')
    expect(page.locator('[data-social-form] [name="configuration_id"]')).to_have_value('')
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.screenshot(path=str(tmp_path / f'personalized-{width}.png'))
    panel.locator('[data-personal-instant]').click()
    expect(page.locator('[data-instant-dialog]')).to_be_visible()
    expect(page.locator('[data-instant-references]')).to_have_text('Disabled')
    expect(page.locator('[data-instant-session]')).to_have_text('24 hours from first redemption')
    page.locator('[data-instant-close]').click()
    expect(page.locator('#recipient')).to_have_value(entities[0]['label'])


def test_share_with_review_validation(authenticated_client, entities, sharing_corpus):
    csrf = make_csrf_token('frontend-test-user')
    for fields in ({}, {'entity_id':'entity:alex'}, {'entity_id':'missing','workspace_confirmed':'on'},
                   {'entity_id':'entity:alex','workspace_confirmed':'on','share_with_workspaces':'missing'}):
        response = authenticated_client.post('/sharing/share-with/review', data={'csrf':csrf, **fields})
        assert response.status_code == 422
    response = authenticated_client.post('/sharing/share-with/review', data={
        'csrf':csrf, 'entity_id':'entity:alex','workspace_confirmed':'on','all_sources':'on'})
    assert response.status_code == 200, response.text
    cfg = response.json()['configuration']
    assert cfg['recipient'] == entities[0]['label']
    assert cfg['activity']['graph_view']['preset'] == 'people'
    assert not cfg['entity_template'] and not cfg['references_enabled'] and not cfg['live_updates']


def test_redemption_starts_full_day_and_is_atomic(entities, sharing_corpus, monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timedelta, timezone
    from modules.hfl_shares import models, store as stores
    clock = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    monkeypatch.setattr(stores, 'utc_now', lambda:clock[0])
    monkeypatch.setattr(models, 'utc_now', lambda:clock[0])
    store = get_share_store()
    def create(token, special=86400):
        return store.create_share(configuration_id='',name='Test',token_hash=token,pin_hash='',auth_mode='qr',
            allowed_email='',snapshot=build_snapshot(recipe(), (sharing_corpus,)),ttl_seconds=86400,
            single_use=True,device_limit=1,instant=True,redemption_session_seconds=special)
    grant = create('full-day')
    unredeemed = create('unredeemed')
    legacy = create('legacy', 0)
    clock[0] += timedelta(hours=23, minutes=59)
    other_store = stores.ShareStore(store.path)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(store.create_session, grant.id, 'one')
        second = executor.submit(other_store.create_session, grant.id, 'two')
        sessions = [first.result(), second.result()]
    assert sum(result is not None for result in sessions) == 1
    session_id, deadline = next(result for result in sessions if result)
    secret = 'one' if sessions[0] else 'two'
    assert datetime.fromisoformat(deadline) == clock[0] + timedelta(days=1)
    legacy_session = store.create_session(legacy.id, 'legacy-secret')
    assert legacy_session[1] == legacy.expires_at
    assert store.get_share(grant.id).redemption_expires_at == grant.expires_at
    clock[0] += timedelta(hours=7)
    assert store.validate_session(session_id, secret)
    assert not store.create_session(unredeemed.id, 'late')
    assert not store.validate_session(legacy_session[0], 'legacy-secret')
    assert not store.create_session(grant.id, 'second')
    assert store.get_share(grant.id).expires_at == deadline
    clock[0] = datetime.fromisoformat(deadline)
    assert not store.validate_session(session_id, secret)


def test_explicit_entry_links_and_no_recursive_entity_expansion(entities, context, sharing_corpus, monkeypatch):
    monkeypatch.setattr(activity, 'mentions_for_documents', lambda docs: [])
    context['links'].extend([
        dict(source='entity:acme', target='entry:hfl-share-test', relation='context'),
        dict(source='entry:hfl-share-test', target='idea:i', relation='context'),
        dict(source='idea:i', target='action:outside', relation='context')])
    result = build_snapshot(recipe(entity_id='entity:acme'), (sharing_corpus,))
    assert [entry.id for entry in result.entries] == ['hfl-share-test']
    assert [obj['id'] for obj in result.activity['ideas']] == ['idea:i']
    assert not result.activity['actions']
    assert 'entity:acme' in {node['id'] for node in result.activity['graph']['nodes']}


def test_personalized_live_refresh_keeps_binding_and_approval(entities, context, sharing_corpus):
    from modules.hfl_shares.activity_models import live_configuration
    cfg = recipe(live_updates=True, activity={'version':1, 'sections':['entries','ideas'], 'workspace_ids':['work']})
    initial = build_snapshot(cfg, (sharing_corpus,))
    live = live_configuration(cfg, initial)
    context['ideas'].append(dict(id='new',title='New workspace idea', workspace_ids=['work']))
    assert [obj['id'] for obj in build_snapshot(live, (sharing_corpus,)).activity['ideas']] == ['idea:i']
    automatic = replace(live, activity={**live.activity,'automatic':['ideas']})
    assert len(build_snapshot(automatic, (sharing_corpus,)).activity['ideas']) == 2
    assert automatic.entity_id == cfg.entity_id
    assert 'New workspace idea' not in str(initial.to_record())


def test_update_from_template_retains_frozen_share_entity(authenticated_client, entities, context, sharing_corpus):
    from modules.hfl_shares.security import opaque_hash
    store = get_share_store()
    cfg = recipe(entity_template=True)
    template = store.save_configuration(personalization.unbound_template(cfg))
    grant = store.create_share(configuration_id=template.id, name='For Alex', token_hash=opaque_hash('personal-test'),
        pin_hash='', auth_mode='qr', allowed_email='', snapshot=build_snapshot(cfg, (sharing_corpus,)),
        ttl_seconds=3600, single_use=False, device_limit=1)
    response = authenticated_client.post('/sharing/shares/' + grant.id + '/update',
                                        data={'csrf':make_csrf_token('frontend-test-user')})
    assert response.status_code == 200, response.text
    updated = store.get_share(grant.id)
    assert updated.snapshot.filters['entity']['id'] == 'entity:alex'
    assert updated.snapshot.recipient == entities[0]['label']
    assert store.get_share_by_token_hash(opaque_hash('personal-test')).id == grant.id
    assert not store.get_configuration(template.id).entity_id


def test_share_with_instant_flags_and_cookie_survive_seven_hours(authenticated_client, entities, sharing_corpus, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from itsdangerous import TimestampSigner
    from starlette.requests import Request
    from modules.hfl_shares import security, store as stores, models
    clock = [datetime.now(timezone.utc)]
    monkeypatch.setattr(stores, 'utc_now', lambda:clock[0])
    monkeypatch.setattr(models, 'utc_now', lambda:clock[0])
    monkeypatch.setattr(TimestampSigner, 'get_timestamp', lambda self:int(clock[0].timestamp()))
    result = authenticated_client.post('/sharing/share-with/instant', data={
        'csrf':make_csrf_token('frontend-test-user'), 'entity_id':'entity:alex',
        'all_sources':'on', 'workspace_confirmed':'on'})
    assert result.status_code == 200, result.text
    store = get_share_store()
    with store._connect() as conn:
        row = conn.execute('SELECT id FROM shares').fetchone()
    grant = store.get_share(row['id'])
    assert grant.instant and grant.single_use and grant.device_limit == 1
    assert grant.redemption_session_seconds == 86400
    assert not grant.live_configuration and result.json()['references_enabled'] is False
    assert all(not ref.enabled for entry in grant.snapshot.all_entries for ref in entry.references)
    session_id, expiry = store.create_session(grant.id, security.opaque_hash('secret'))
    cookie = security.make_session_cookie(session_id, 'secret')
    request = Request({'type':'http','headers':[(b'cookie',f'{security.GUEST_COOKIE}={cookie}'.encode())]})
    clock[0] += timedelta(hours=7)
    assert security.current_session(request, store)[1] == session_id
    assert store.get_share(grant.id).expires_at == expiry
    store.revoke_share(grant.id)
    assert security.current_session(request, store) is None


def test_share_with_template_keeps_rules(authenticated_client, entities, sharing_corpus):
    cfg = get_share_store().save_configuration(personalization.unbound_template(recipe(
        entity_template=True, tags=('absent',), activity={'version':1,'sections':['entries','graph'],
        'excluded_ids':['entry:private']})))
    result = authenticated_client.post('/sharing/share-with/review', data={
        'csrf':make_csrf_token('frontend-test-user'), 'entity_id':'entity:alex','template_id':cfg.id,
        'all_sources':'on','workspace_confirmed':'on'})
    assert result.status_code == 200, result.text
    result = result.json()['configuration']
    assert result['tags'] == ['absent']
    assert result['activity']['excluded_ids'] == ['entry:private']
    assert not get_share_store().get_configuration(cfg.id).entity_id


@pytest.mark.parametrize('workspaces', [[], [{'id':'a','name':'Default'},{'id':'b','name':'default'}]])
def test_missing_default_requires_choice_and_failure_keeps_draft(editor_page, entities, sharing_corpus, monkeypatch, workspaces):
    from playwright.sync_api import expect
    from modules.hfl_corpus import workspace_views
    monkeypatch.setattr(workspace_views,'listing',lambda:{'views':workspaces})
    page, client = editor_page
    page.goto('https://editing.test/sharing')
    page.locator('#recipient').fill('Keep draft')
    page.locator('[data-personalization] > summary').click()
    page.locator('[data-entity-results] button').filter(has_text='Alex').click()
    page.locator('[data-personal-review]').click()
    expect(page.locator('[data-share-with-error]')).to_contain_text('Choose a Space')
    expect(page.locator('#recipient')).to_have_value('Keep draft')
    page.locator('[data-workspace-selector] > summary').click()
    page.locator('[data-no-workspace]').click()
    # The entity disappearing between selection and review must fail closed.
    monkeypatch.setattr(personalization, 'entity_catalog', lambda:[])
    page.locator('[data-personal-review]').click()
    expect(page.locator('[data-share-with-error]')).to_contain_text('unavailable or was merged')
    expect(page.locator('#recipient')).to_have_value('Keep draft')
    expect(page.locator('[data-share-with-form] [name="entity_id"]')).to_have_value('entity:alex')


def test_saved_template_browser_rebind_and_save(editor_page, entities, sharing_corpus, monkeypatch):
    from playwright.sync_api import expect
    from modules.hfl_corpus import workspace_views
    monkeypatch.setattr(workspace_views,'listing',lambda:{'views':[{'id':'work','name':'Default'}]})
    store=get_share_store()
    cfg=store.save_configuration(personalization.unbound_template(recipe(entity_template=True,
        tags=('absent',), activity={'version':1,'sections':['entries','graph'],
        'workspace_ids':['work'],'excluded_ids':['entry:private']})))
    page, client=editor_page
    page.goto('https://editing.test/sharing?configuration_id='+cfg.id)
    page.locator('[data-personalization] > summary').click()
    page.locator('[data-entity-results] button').filter(has_text='Alex').click()
    page.locator('[data-share-with-form] [name="entity_template"]').check()
    page.locator('[data-personal-review]').click()
    expect(page.locator('#recipient')).to_have_value(entities[0]['label'])
    expect(page.locator('[name="excluded_object_ids"]')).to_have_value('entry:private')
    page.get_by_role('tab',name='Details and Filtering',exact=True).click()
    page.get_by_role('button',name='Save recipe',exact=True).click()
    expect(page.locator('#recipient')).to_have_value('')
    saved_id=page.locator('[data-social-form] [name="configuration_id"]').input_value()
    saved=store.get_configuration(saved_id)
    assert saved.entity_template and not saved.entity_id
    assert saved.tags == ('absent',)
    assert saved.activity['excluded_ids'] == ['entry:private']


def test_multiple_entities_union_deduplicated_filtered_and_excluded(entities, context, sharing_corpus, monkeypatch):
    second=replace(sharing_corpus.entries[0], anchor='second', text=sharing_corpus.entries[0].text.replace('hfl-share-test','second'))
    document=replace(sharing_corpus, entries=(*sharing_corpus.entries,second),entry_count=2)
    monkeypatch.setattr(activity,'mentions_for_documents',lambda docs:[
        {'id':'hfl-share-test','mentions':entities}, {'id':'second','mentions':[entities[1]]}])
    context['links'].extend([{'source':'entity:alex','target':'action:a'},
                             {'source':'entity:acme','target':'action:a'},
                             {'source':'entity:acme','target':'action:outside'}])
    cfg=recipe(entity_ids=('entity:alex','entity:acme','entity:alex'), recipient='My recipient')
    snapshot=build_snapshot(cfg,(document,))
    assert {e.id for e in snapshot.entries} == {'hfl-share-test','second'}
    assert len(snapshot.entries)==2
    assert {a['id'] for a in snapshot.activity['actions']} == {'action:a','action:outside'}
    assert len(snapshot.activity['actions'])==2
    assert snapshot.recipient=='My recipient'
    assert [e['id'] for e in snapshot.filters['entities']]==['entity:alex','entity:acme']
    assert not build_snapshot(replace(cfg,tags=('absent',)),(document,)).entries
    excluded=replace(cfg,activity={**cfg.activity,'excluded_ids':['entry:second','action:a']})
    result=build_snapshot(excluded,(document,))
    assert [e.id for e in result.entries]==['hfl-share-test']
    assert 'action:a' not in {a['id'] for a in result.activity['actions']}
    with pytest.raises(ValueError,match='unavailable or was merged'):
        build_snapshot(replace(cfg,entity_ids=('entity:alex','missing')),(document,))
    template=personalization.unbound_template(replace(cfg,entity_template=True))
    assert not template.entity_ids and not template.entities and not template.entity_id and not template.recipient


@pytest.mark.parametrize('width',[390,1440])
def test_multi_entity_picker_preserves_recipient_and_round_trips(editor_page,entities,sharing_corpus,monkeypatch,width):
    from playwright.sync_api import expect
    from modules.hfl_corpus import workspace_views
    monkeypatch.setattr(workspace_views,'listing',lambda:{'views':[{'id':'work','name':'Default'}]})
    page,client=editor_page
    page.set_viewport_size({'width':width,'height':1000})
    page.goto('https://editing.test/sharing')
    page.locator('[data-personalization] > summary').click()
    page.locator('[data-entity-results] button').filter(has_text='Alex').click()
    expect(page.locator('#share-with-recipient')).to_have_value(entities[0]['label'])
    page.locator('#share-with-recipient').fill('For my friend')
    page.locator('#entity-type').select_option('companies')
    page.locator('[data-entity-results] button').filter(has_text='Acme').click()
    expect(page.locator('[data-selected-entities] .selected-entity-card')).to_have_count(2)
    expect(page.locator('#share-with-recipient')).to_have_value('For my friend')
    page.locator('[data-personal-review]').click()
    expect(page.locator('#recipient')).to_have_value('For my friend')
    expect(page.locator('[data-social-form] [name="entity_ids"]')).to_have_count(2)
    expect(page.locator('[name="graph_view"]')).to_have_value('{"preset":"timeline"}')
    page.get_by_role('tab',name='Details and Filtering',exact=True).click()
    page.locator('#recipient').fill('Edited recipient')
    page.get_by_role('button',name='Save recipe',exact=True).click()
    expect(page.locator('#recipient')).to_have_value('Edited recipient')
    cfg=get_share_store().get_configuration(page.locator('[name="configuration_id"]').input_value())
    assert cfg.entity_ids==('entity:alex','entity:acme')
    assert cfg.recipient=='Edited recipient'
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
    # Start a new selection and exercise removal without resetting recipient.
    page.goto('https://editing.test/sharing')
    page.locator('[data-personalization] > summary').click()
    page.locator('[data-entity-results] button').filter(has_text='Alex').click()
    page.locator('#entity-type').select_option('companies')
    page.locator('[data-entity-results] button').filter(has_text='Acme').click()
    page.get_by_role('button',name='Remove '+entities[0]['label'],exact=True).click()
    expect(page.locator('#share-with-recipient')).to_have_value(entities[0]['label'])
    expect(page.locator('[data-selected-entities] .selected-entity-card')).to_have_count(1)
    page.locator('[data-clear-entity]').click()
    expect(page.locator('#share-with-recipient')).to_have_value('')
    expect(page.locator('[data-selected-entities] .selected-entity-card')).to_have_count(0)


def test_multi_entity_instant_and_template_update_keep_all_bindings(authenticated_client,entities,context,sharing_corpus):
    from modules.hfl_shares.security import opaque_hash
    from modules.hfl_shares.activity_models import live_configuration
    from modules.hfl_shares.store import ShareStore
    cfg=recipe(entity_ids=('entity:alex','entity:acme'),recipient='Recipient',entity_template=True,
               live_updates=True,activity={'version':1,'sections':['entries','actions','graph']})
    initial=build_snapshot(cfg,(sharing_corpus,))
    live=live_configuration(cfg,initial)
    assert build_snapshot(live,(sharing_corpus,)).filters['entities']==initial.filters['entities']
    store=get_share_store()
    template=store.save_configuration(personalization.unbound_template(cfg))
    grant=store.create_share(configuration_id=template.id,name='Combined',token_hash=opaque_hash('multi'),
        pin_hash='',auth_mode='qr',allowed_email='',snapshot=initial,ttl_seconds=3600,single_use=False,device_limit=1,
        live_configuration=live)
    restored=ShareStore(store.path).get_share(grant.id)
    assert tuple(restored.live_configuration.entity_ids)==cfg.entity_ids
    response=authenticated_client.post('/sharing/shares/'+grant.id+'/update',data={'csrf':make_csrf_token('frontend-test-user')})
    assert response.status_code==200,response.text
    updated=store.get_share(grant.id)
    assert updated.snapshot.filters['entities']==initial.filters['entities']
    assert updated.snapshot.recipient=='Recipient'
    assert not store.get_configuration(template.id).entity_ids
    response=authenticated_client.post('/sharing/share-with/instant',data={
        'csrf':make_csrf_token('frontend-test-user'),'entity_ids':['entity:alex','entity:acme'],
        'recipient':'One individual','all_sources':'on','workspace_confirmed':'on'})
    assert response.status_code==200,response.text
    with store._connect() as db:
        row=db.execute('SELECT id FROM shares WHERE instant=1').fetchone()
    instant=store.get_share(row['id'])
    assert len(instant.snapshot.filters['entities'])==2
    assert instant.snapshot.recipient=='One individual'
    assert instant.single_use and instant.redemption_session_seconds==86400
