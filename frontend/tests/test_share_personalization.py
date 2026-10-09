"""Recipient binding, additive workspace context, and template isolation."""
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
def test_personalized_template_browser(editor_page, entities, sharing_corpus, width, tmp_path):
    from playwright.sync_api import expect
    page, client = editor_page
    page.set_viewport_size({'width':width, 'height':1000})
    page.goto('https://editing.test/sharing')
    page.locator('[data-personalization] > summary').click()
    page.locator('#quick-template').select_option('entity')
    page.locator('#entity-search').fill('Alex')
    page.locator('[data-entity-results] button').filter(has_text='Alex').click()
    expect(page.locator('#recipient')).to_have_value(entities[0]['label'])
    expect(page.locator('#recipient')).to_have_attribute('readonly', '')
    page.get_by_role('tab', name='Entries', exact=True).click()
    expect(page.locator('[data-preview-ready]')).to_be_visible(timeout=15000)
    expect(page.locator('[data-preview-ready]')).to_contain_text('Planned the Japan trip')
    page.screenshot(path=str(tmp_path / f'personalized-{width}.png'))
    page.locator('[data-personal-instant]').click()
    page.locator('[data-personal-instant]').click()
    expect(page.locator('[data-instant-dialog]')).to_be_visible()
    expect(page.locator('[data-instant-references]')).to_have_text('Disabled')
    page.locator('[data-instant-close]').click()
    page.get_by_role('tab', name='Details and Filtering', exact=True).click()
    page.get_by_role('button', name='Save recipe', exact=True).click()
    expect(page.locator('[name="configuration_id"]')).not_to_have_value('')
    expect(page.locator('[name="entity_id"]')).to_have_value('')
    expect(page.locator('#recipient')).to_have_value('')
    page.locator('#entity-search').fill('Acme')
    page.locator('[data-entity-results] button').filter(has_text='Acme').click()
    page.get_by_role('tab', name='Entries', exact=True).click()
    expect(page.locator('[data-preview-ready]')).not_to_contain_text('Planned the Japan trip', timeout=15000)


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
