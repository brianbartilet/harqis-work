"""Opt-in briefings use the existing Hermes sweep as their sole schedule owner."""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from modules.agents import service
from workflows.hfl.agent_fleet_store import FleetConflict

LEGACY_PROMPT = 'Scheduled read-only briefing: summarize recent activity, open commitments, upcoming work and agent failures. Cite the evidence and its freshness. Do not perform writes, development, scheduling, or external communications.'
PROMPT = LEGACY_PROMPT + ' Always write the briefing in Markdown with headings, lists, and evidence links. Do not wrap the whole answer in a code fence.'

DEFAULT = {'cadence':'off', 'hour':9, 'weekday':0, 'timezone':'Asia/Singapore', 'version':0}


def profile_timezone():
    from modules.profile.store import get_profile_store
    return get_profile_store().get().timezone


def read(user):
    with service.store().connect() as db:
        row = db.execute('SELECT * FROM fleet_briefings WHERE user=?', (user,)).fetchone()
    config = {**json.loads(row['payload']), 'version':row['version']} if row else dict(DEFAULT)
    return {**config, 'timezone': profile_timezone()}


def save(user, raw):
    if set(raw) != set(DEFAULT) or raw['cadence'] not in {'off','daily','weekly'}:
        raise ValueError('Choose off, daily or weekly briefings.')
    for key, maximum in [('hour',23),('weekday',6)]:
        if type(raw[key]) is not int or not 0 <= raw[key] <= maximum:
            raise ValueError('Invalid briefing ' + key + '.')
    raw = {**raw, 'timezone': profile_timezone()}
    with service.store().connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT version FROM fleet_briefings WHERE user=?', (user,)).fetchone()
        version = row[0] if row else 0
        if type(raw['version']) is not int or raw['version'] != version:
            raise FleetConflict('Briefing schedule changed. Reload before saving.')
        db.execute('INSERT INTO fleet_briefings VALUES (?,?,?) ON CONFLICT(user) DO UPDATE SET version=excluded.version,payload=excluded.payload',
                   (user,version+1,json.dumps(raw)))
    return read(user)


def sweep(instant=None):
    from modules.agents.butler import send
    from fastapi import HTTPException
    with service.store().connect() as db:
        schedules = [(r['user'],json.loads(r['payload'])) for r in db.execute('SELECT * FROM fleet_briefings')]
    for user, config in schedules:
        config['timezone'] = profile_timezone()
        local = (instant or datetime.now(ZoneInfo('UTC'))).astimezone(ZoneInfo(config['timezone']))
        if config['cadence']=='off' or local.hour < config['hour'] or (config['cadence']=='weekly' and local.weekday()!=config['weekday']):
            continue
        day = local.date().isoformat()
        key = occurrence_key(user, day)
        with service.store().connect() as db:
            db.execute('INSERT OR IGNORE INTO fleet_briefing_deliveries VALUES (?,?,?,?)',
                       (user, key, day, json.dumps({'cadence': config['cadence'], 'timezone': config['timezone']})))
        try:
            send(user, {'request_id':key, 'message':PROMPT,
                        'context':{'path':'/agents','space':''}})
        except (HTTPException, ValueError, KeyError):
            continue  # Next sweep retries the same occurrence, never duplicates it.


def occurrence_key(user, day):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'fleet-briefing:' + user + ':' + day))


def demo_available():
    return os.getenv('HFL_TIMELINE_LOCAL_PREVIEW') == '1'


def _recover_legacy(db, user):
    # Require both the exact scheduler prompt and its deterministic occurrence ID.
    # The UTC creation date can differ from the original local schedule by one day.
    rows = db.execute('SELECT request_id,created FROM fleet_chat WHERE user=? AND message IN (?,?)', (user, PROMPT, LEGACY_PROMPT))
    for row in rows:
        try:
            created = datetime.fromisoformat(row['created']).date()
        except (ValueError, TypeError):
            continue
        for offset in (-1, 0, 1):
            day = (created + timedelta(days=offset)).isoformat()
            if occurrence_key(user, day) == row['request_id']:
                db.execute('INSERT OR IGNORE INTO fleet_briefing_deliveries VALUES (?,?,?,?)',
                           (user, row['request_id'], day, json.dumps({'cadence': 'scheduled', 'legacy': True})))
                break


def agent_updates(user):
    """Bounded recorded updates, never agent dispatch or a second schedule.

    Scheduled Butler answers already have delivery cards. Exclude those runs,
    retain only the newest attempt per source, and keep stable run identities.
    """
    from modules.agents import projection
    from modules.hfl_corpus.action_agents import store as terminals
    from urllib.parse import quote
    agents = {a['id']: a for a in service.initialize().list()
              if not a.get('mock') and projection.visible(a, user)}
    with service.store().connect() as db:
        existing = {r[0] for r in db.execute('SELECT run_id FROM fleet_chat WHERE run_id IS NOT NULL')}
        observed = [json.loads(r[0]) for r in db.execute(
            'SELECT payload FROM fleet_objects WHERE user=? ORDER BY rowid DESC LIMIT 100', (user,))]
    seen, updates = set(), []
    for run in terminals().list(limit=200):
        source = run['source_key']
        if source in seen:
            continue
        seen.add(source)
        agent = agents.get(run['snapshot'].get('execution_settings', {}).get('fleet_agent', {}).get('id'))
        if not agent or run['id'] in existing or run['state'] not in {'review', 'succeeded', 'failed', 'awaiting_input', 'interrupted'}:
            continue
        record = run['snapshot'].get('source', {})
        updates.append({'id': 'agent-update:' + run['id'], 'date': run['updated_at'],
                        'title': record.get('title', 'Agent result'), 'agent_name': agent['name'],
                        'state': run['state'], 'answer': str((run.get('result') or {}).get('summary') or '')[:5000],
                        'detail': 'Recorded execution update; action completion is reviewed separately.',
                        'workspace_ids': record.get('workspace_ids', []),
                        'url': '/hfl-corpus/actions?integration_agent=' + quote(source.partition(':')[2])})
    for record in observed:
        agent = agents.get(record.get('agent_id'))
        if not agent or record.get('mock') or record.get('kind') not in {'task', 'action', 'feed'} or record.get('state') not in {'completed', 'failed', 'review', 'awaiting_input'}:
            continue
        from modules.agents.ecosystem import safe_url
        updates.append({'id': 'agent-update:' + record['id'], 'date': record.get('created', ''),
                        'title': record['label'], 'agent_name': agent['name'], 'state': record['state'],
                        'answer': record.get('summary', '')[:5000], 'detail': 'Reported by ' + record.get('source', 'agent'),
                        'workspace_ids': record.get('workspace_ids', []), 'url': safe_url(record.get('url', ''))})
    return sorted(updates, key=lambda item: item['date'], reverse=True)[:30]


def history(user):
    from modules.hfl_corpus.agent_bridge import bridge_store
    with service.store().connect() as db:
        _recover_legacy(db, user)
        rows = list(db.execute('''
            SELECT d.request_id,d.scheduled_date,d.payload,c.run_id,c.action_id
            FROM fleet_briefing_deliveries d LEFT JOIN fleet_chat c
            ON c.user=d.user AND c.request_id=d.request_id
            WHERE d.user=? ORDER BY d.scheduled_date DESC,d.request_id DESC LIMIT 100
        ''', (user,)))
    items = []
    for row in rows:
        meta = json.loads(row['payload'])
        if meta.get('mock') and not demo_available():
            continue
        item = {'id': row['request_id'], 'date': row['scheduled_date'],
                'title': 'Weekly briefing' if meta.get('cadence') == 'weekly' else 'Daily briefing' if meta.get('cadence') == 'daily' else 'Scheduled briefing',
                'timezone': meta.get('timezone', ''), 'mock': bool(meta.get('mock')),
                'state': 'pending', 'answer': '', 'detail': 'Waiting for the scheduled worker.',
                'run_id': row['run_id'] or ''}
        if item['mock']:
            item.update(state=meta['state'], answer=meta.get('answer', ''), detail=meta.get('detail', ''))
        elif row['run_id']:
            try:
                run = bridge_store().get(row['run_id'])
                state = run['state']
                item['state'] = {'queued': 'pending', 'succeeded': 'completed', 'completed': 'completed',
                                 'running': 'running', 'review': 'completed', 'accepting': 'completed'}.get(state, 'failed')
                item['answer'] = str((run.get('result') or {}).get('summary') or '')[:50000]
                item['detail'] = {'pending': 'Queued for the scheduled worker.', 'running': 'Preparing your briefing.',
                                  'completed': '', 'failed': 'The worker could not complete this briefing.'}[item['state']]
            except KeyError:
                item.update(state='failed', detail='The worker result is no longer available.')
        from services.markdown import render_markdown
        item['answer_html'] = str(render_markdown(item['answer']))
        items.append(item)
    try:
        updates = agent_updates(user)
    except Exception:
        updates = []
        # Keep scheduled deliveries usable if a separate execution source fails.
        return {'items': items, 'demo_available': demo_available(), 'updates_error': 'Agent updates could not refresh.'}
    from services.markdown import render_markdown
    for item in updates:
        item['answer_html'] = str(render_markdown(item['answer']))
    return {'items': sorted(items + updates, key=lambda item: item['date'], reverse=True), 'demo_available': demo_available()}


def seed_demo(user):
    from fastapi import HTTPException
    if not demo_available():
        raise HTTPException(404, 'Sample briefings are available only in local preview.')
    samples = [
        ('completed', 'Your morning overview\n\nFocus today\nReview the agent workspace release checklist and confirm the production gateway connection.\n\nOpen commitments\nTwo follow-ups are awaiting review. Check their owners and due dates before planning new work.\n\nUpcoming\nA project review is scheduled this afternoon. Prepare the latest notes and outstanding questions.\n\nEvidence: simulated activity, tasks and calendar entries. No live sources were consulted.', ''),
        ('running', '', 'Preparing a sample briefing. This mock stays running for layout review.'),
        ('pending', '', 'Sample briefing waiting for a worker. No job has been queued.'),
        ('failed', '', 'Sample gateway timeout. This is simulated; no live request failed.'),
        ('completed', 'Weekly review\n\nCompleted\nAligned the fleet graph, updated the inspector and verified desktop/mobile flows.\n\nNext week\nValidate briefing delivery, review pending work and confirm deployment readiness.\n\nEvidence: simulated release notes. This is not a live activity report.', ''),
    ]
    with service.store().connect() as db:
        for index, (state, answer, detail) in enumerate(samples):
            day = (datetime.now(timezone.utc).date() - timedelta(days=index)).isoformat()
            meta = {'mock': True, 'cadence': 'weekly' if index == 4 else 'daily', 'state': state,
                    'answer': answer, 'detail': detail, 'timezone': 'UTC'}
            db.execute('INSERT INTO fleet_briefing_deliveries VALUES (?,?,?,?) ON CONFLICT(user,request_id) DO UPDATE SET scheduled_date=excluded.scheduled_date,payload=excluded.payload',
                       (user, 'mock-briefing-' + str(index), day, json.dumps(meta)))
    return history(user)
