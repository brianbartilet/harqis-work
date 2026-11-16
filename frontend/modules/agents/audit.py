"""Deduplicated fleet receipts delivered through the existing HFL outbox."""
import json
import os
from datetime import datetime
from modules.agents.service import store


def terminal_event(session, kind, payload=None, key=''):
    agent = session['settings'].get('fleet_agent')
    if not agent:
        return
    store().event('terminal:' + session['id'] + ':' + (key or kind), agent['id'],
                  {'kind': kind, 'session_id': session['id'], 'action_id': session['source_id'],
                   'agent_name': agent['name'], 'version': agent['version'], 'configuration_hash': agent['hash'],
                   **(payload or {})})


def deliver_pending(event_ids=None):
    from workflows.hfl.dto import HflEntry
    from workflows.hfl.persistence import submit_hfl_entry
    db = store()
    delivered = 0
    def pending():
        if event_ids is None:
            return db.events(pending=True)
        if not event_ids:
            return []
        with db.connect() as connection:
            rows = connection.execute('SELECT * FROM fleet_events WHERE delivered=0 AND id IN (' + ','.join('?' for _ in event_ids) + ')', tuple(event_ids))
            return [{**dict(row), 'payload': json.loads(row['payload'])} for row in rows]
    for event in pending():
        if os.getenv('HFL_TIMELINE_LOCAL_PREVIEW') == '1':
            break
        payload = event['payload']
        if payload.get('mock'):
            continue
        try:
            execution = payload.get('kind') in {'n8n-execution', 'nod-turn'}
            stamp = (payload.get('stopped_at') or payload.get('started_at')) if execution else event['created']
            entry = HflEntry(when=datetime.fromisoformat(stamp or event['created']),
                             moment=(('Nod activity · ' + payload['status']) if payload.get('kind') == 'nod-turn' else ('n8n: ' + payload['workflow_name'] + ' · ' + payload['status']) if execution else
                                     'Agent activity: ' + payload.get('agent_name', payload.get('name', event['agent_id']))),
                             what_happened=json.dumps({**payload, 'agent_id': event['agent_id']}, ensure_ascii=False, indent=2),
                             why_it_stayed='Links fleet configuration, execution and artifacts to their source.',
                             tags=('agents-activity', 'agent-execution'), source='agents-activity',
                             references=(payload['url'],) if execution else ())
            result = submit_hfl_entry(entry, source='agents-activity', dedup_key='fleet:' + event['id'], synthesized=True)
            if result.get('delivery') in {'persisted', 'forwarded', 'outbox'}:
                with db.connect() as connection:
                    connection.execute('UPDATE fleet_events SET delivered=1 WHERE id=?', (event['id'],))
                delivered += 1
        except Exception:
            continue
    return {'delivered': delivered, 'pending': len(pending())}
