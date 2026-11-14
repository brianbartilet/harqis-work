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


def deliver_pending():
    from workflows.hfl.dto import HflEntry
    from workflows.hfl.persistence import submit_hfl_entry
    db = store()
    delivered = 0
    for event in db.events(pending=True):
        if os.getenv('HFL_TIMELINE_LOCAL_PREVIEW') == '1':
            break
        payload = event['payload']
        try:
            entry = HflEntry(when=datetime.fromisoformat(event['created']),
                             moment='Agent activity: ' + payload.get('agent_name', payload.get('name', event['agent_id'])),
                             what_happened=json.dumps({**payload, 'agent_id': event['agent_id']}, ensure_ascii=False, indent=2),
                             why_it_stayed='Links fleet configuration, execution and artifacts to their source.',
                             tags=('agents-activity', 'agent-execution'), source='agents-activity')
            result = submit_hfl_entry(entry, source='agents-activity', dedup_key='fleet:' + event['id'], synthesized=True)
            if result.get('delivery') in {'persisted', 'forwarded', 'outbox'}:
                with db.connect() as connection:
                    connection.execute('UPDATE fleet_events SET delivered=1 WHERE id=?', (event['id'],))
                delivered += 1
        except Exception:
            continue
    return {'delivered': delivered, 'pending': len(db.events(pending=True))}
