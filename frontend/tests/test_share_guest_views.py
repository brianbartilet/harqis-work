"""Recipient navigation, publication compatibility, and approved evidence."""
from dataclasses import replace
from uuid import uuid4

import pytest
from starlette.datastructures import FormData

from modules.hfl_shares.activity_models import from_form, live_configuration
from modules.hfl_shares.agent import _context
from modules.hfl_shares.guest_views import guest_views
from modules.hfl_shares.scope import build_snapshot
from modules.hfl_shares.store import get_share_store
from test_hfl_shares import sharing_corpus
from test_workspace_sharing import context, recipe
from test_action_editing import editor_page
from test_hfl_ideas import ideas


def make_share(snapshot, cfg=None):
    store = get_share_store()
    return store.create_share(configuration_id=cfg.id if cfg else '', name='Portfolio',
        token_hash=uuid4().hex, encrypted_link='encrypted-original-link', pin_hash='pin',
        auth_mode='qr', allowed_email='', snapshot=snapshot, ttl_seconds=3600,
        no_expiry=True, single_use=False, device_limit=4,
        live_configuration=live_configuration(cfg, snapshot) if cfg else None)


def test_required_entries_on_save_preserves_legacy_refresh(context, sharing_corpus):
    assert from_form(FormData([('activity_version', '1'), ('activity_sections', 'ideas')]))['sections'] == ['entries', 'ideas']
    cfg = recipe(activity={'sections': ['ideas']})
    saved = get_share_store().save_configuration(cfg)
    assert saved.activity['sections'] == ['entries', 'ideas']
    # Reading an old publication must not silently expand its scope.
    assert not build_snapshot(cfg, (sharing_corpus,)).entries


def test_menu_scope_and_board_member_citations(context, sharing_corpus):
    snapshot = build_snapshot(recipe(activity={'sections':['entries', 'boards']}), (sharing_corpus,))
    view = guest_views(make_share(snapshot))
    assert view['share_menu'] == [('entries', 'Activity entries'), ('boards', 'Idea boards')]
    member = next(e for e in snapshot.activity_entries if e.id == 'action:a')
    assert view['evidence_destinations'][member.citation[1:]] == 'boards'
    assert member in view['board_evidence']
    empty = replace(snapshot, activity={}, activity_entries=())
    assert guest_views(make_share(empty))['share_menu'] == [('entries', 'Activity entries')]


@pytest.mark.parametrize('live', [False, True])
def test_update_share_in_place_keeps_identity_and_rejects_stale_update(context, sharing_corpus, live):
    cfg = get_share_store().save_configuration(recipe(live_updates=live))
    original = build_snapshot(cfg, (sharing_corpus,))
    grant = make_share(original, cfg)
    store = get_share_store()
    with store._connect() as db:
        before = dict(db.execute('SELECT * FROM shares WHERE id=?', (grant.id,)).fetchone())
    context['actions'][0]['body'] = 'Updated publication'
    snapshot = build_snapshot(cfg, (sharing_corpus,))
    assert store.replace_share_content(grant, snapshot, cfg)
    updated = store.get_share(grant.id)
    assert updated.snapshot == snapshot
    assert updated.live_updates == live
    assert updated.no_expiry
    assert store.get_share_link(grant.id) == 'encrypted-original-link'
    with store._connect() as db:
        after = dict(db.execute('SELECT * FROM shares WHERE id=?', (grant.id,)).fetchone())
    for key in set(before) - {'snapshot', 'snapshot_entry_count', 'live_configuration'}:
        assert before[key] == after[key], key
    if live:
        assert updated.live_configuration.activity['approved_ids']['actions'] == ['action:a']
    assert not store.replace_share_content(grant, original, cfg)


def test_agent_context_includes_only_approved_relationships(context, sharing_corpus):
    snapshot = build_snapshot(recipe(), (sharing_corpus,))
    evidence = next(e for e in snapshot.activity_entries if e.id == 'action:a')
    text = _context(snapshot, entries=(evidence,))
    assert 'Approved action — related-to — Current idea' in text
    assert 'Secret-backed action' not in text


@pytest.mark.parametrize('width', [1440, 390])
def test_recipient_views_mobile_and_desktop(editor_page, context, sharing_corpus, width, tmp_path):
    from playwright.sync_api import expect
    context['plans'] = [
        dict(id='early', title='Earlier plan', category='Alpha', start_date='2026-10-01', end_date='2026-10-02', workspace_ids=['work']),
        dict(id='later', title='Later plan', category='Zulu', start_date='2026-09-01', end_date='2027-02-01', workspace_ids=['work']),
    ]
    cfg = recipe(activity={'sections':['entries','actions','ideas','boards','plans','graph'],
                           'graph_view':{'preset':'people','animation':'off'}})
    snapshot = build_snapshot(cfg, (sharing_corpus,))
    grant = make_share(snapshot)
    page, client = editor_page
    page.set_viewport_size({'width':width, 'height':844})
    page.goto('https://editing.test/sharing/shares/' + grant.id + '/preview')
    page.locator('[data-preview-toast-close]').click()
    expect(page.locator('[data-chat-form]')).to_be_visible()
    expect(page.locator('[data-share-sidebar=entries]')).not_to_have_attribute('hidden', '')
    page.locator('#question').fill('Keep this draft')

    def choose(key):
        page.get_by_role('button', name='Choose shared view').click()
        page.locator('[data-share-view=' + key + ']').click()

    choose('actions')
    panel = page.locator('[data-share-sidebar=actions]')
    expect(panel).to_be_visible()
    expect(panel).to_contain_text('Approved action')
    expect(panel).to_contain_text('Current idea')
    assert panel.locator('.share-guest-group').first.get_attribute('data-kind') == 'actions'
    assert panel.bounding_box()['width'] <= width
    if width <= 900:
        expect(page.locator('[data-entry-drawer]')).to_have_css('transform', 'matrix(1, 0, 0, 1, 0, 0)')
        assert page.locator('[data-entry-drawer]').bounding_box()['x'] >= 0
        assert page.locator('.chat-workspace').evaluate('(el)=>el.inert')
    page.screenshot(path=str(tmp_path / f'shared-actions-{width}.png'))
    page.locator('[data-drawer-close]').click()
    choose('plans')
    expect(page.locator('[data-share-sidebar=plans] h3').first).to_have_text('Zulu')
    page.locator('[data-drawer-close]').click()
    choose('graph')
    graph = page.locator('[data-share-main=graph]')
    expect(graph.locator('canvas').first).to_be_visible()
    expect(page.locator('[data-chat-form]')).not_to_be_visible()
    expect(graph.get_by_label('Graph preset', exact=True)).to_have_value('people')
    graph.get_by_label('Graph preset', exact=True).select_option('sources')
    page.screenshot(path=str(tmp_path / f'shared-graph-{width}.png'))
    graph.get_by_role('button', name='Back to chat').click()
    expect(page.locator('#question')).to_have_value('Keep this draft')
    if width > 900:
        page.locator('[data-drawer-close]').click()
    choose('graph')
    expect(graph.get_by_label('Graph preset', exact=True)).to_have_value('people')
    choose('boards')
    expect(page.locator('[data-share-main=boards] canvas').first).to_be_visible()
    expect(page.locator('[data-share-main=graph] canvas')).to_have_count(0)
    page.locator('[data-share-main=boards] [data-return-chat]').click()
    # An actual chat citation opens the appropriate source panel.
    citation = next(e.citation[1:] for e in snapshot.activity_entries if e.id == 'action:a')
    page.locator('[data-chat-thread]').evaluate('(el, id) => { const a=document.createElement("a"); a.href="/share/session?page=1#evidence-"+id; a.textContent="Cited action"; el.append(a); }', citation)
    page.get_by_role('link', name='Cited action').click()
    expect(page.locator('#evidence-' + citation)).to_be_visible()
    expect(page.locator('[data-share-sidebar=actions]')).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.locator('[data-drawer-close]').click()
    expect(page.get_by_role('link', name='End', exact=True)).to_be_visible()
