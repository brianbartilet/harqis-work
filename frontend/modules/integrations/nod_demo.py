"""Local Nod protocol double. No model, browser or remote task is invoked."""
import json
import json as jsonlib
import os
import uuid
from fastapi import HTTPException
from modules.agents.service import store
from workflows.hfl.agent_fleet_store import now


def enabled():
    return os.getenv('HARQIS_NOD_MOCK') == '1' and os.getenv('HFL_TIMELINE_LOCAL_PREVIEW') == '1'


class MockNod:
    def __init__(self, user):
        self.user = user

    def test(self):
        self.request('GET', '/api/state')
        return {'account': 'Mock Nod', 'account_id': 'demo'}

    def request(self, method, path, *, json=None):
        if not enabled():
            raise HTTPException(404, 'Nod preview unavailable.')
        with store().connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS nod_demo (owner TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT payload FROM nod_demo WHERE owner=?', (self.user,)).fetchone()
            data = jsonlib.loads(row['payload']) if row else {
                'threadId': str(uuid.uuid4()), 'configuration': {'llmReady': True}, 'turns': [], 'tasks': [],
                'messages': [{'id': str(uuid.uuid4()), 'role': 'assistant', 'text': 'I’m your mock Nod assistant. Send a message to try a reply, or include “approval” to preview an approval request.', 'createdAt': now()}]}
            if method == 'POST' and path == '/api/messages':
                if json['threadId'] != data['threadId']:
                    raise HTTPException(409, 'Conversation changed.')
                previous = next((m for m in data['messages'] if m['id'] == json['clientMessageId']), None)
                if previous:
                    return {'threadId': data['threadId'], 'messageId': previous['id'], 'turnId': previous['turnId']}
                tid = str(uuid.uuid4())
                answer = json.get('approvalAnswer')
                pending = 'approval' in json['text'].lower() and not answer
                if answer:
                    for m in data['messages']:
                        if (m.get('approval') or {}).get('id') == answer['approvalId']:
                            m['approval']['state'] = 'done' if answer['approved'] else 'declined'
                            for t in data['turns']:
                                if t['id'] == m['turnId']:
                                    t.update(status='succeeded' if answer['approved'] else 'cancelled', finishedAt=now())
                    reply = 'Approval recorded in this preview. No external action was performed.'
                else:
                    reply = 'May I send the demo briefing to the demo team? This is a simulated approval.' if pending else 'Mock reply: I received your message. In a connected instance, this is where Nod’s response and work updates appear.'
                data['messages'].extend([
                    {'id': json['clientMessageId'], 'role': 'user', 'text': json['text'], 'turnId': tid, 'createdAt': now()},
                    {'id': str(uuid.uuid4()), 'role': 'assistant', 'text': reply, 'turnId': tid, 'createdAt': now(),
                     **({'approval': {'id': str(uuid.uuid4()), 'state': 'pending', 'title': 'Send demo briefing', 'description': 'Demo team only. No real message will be sent.'}} if pending else {})}])
                data['turns'].insert(0, {'id': tid, 'status': 'waiting' if pending else 'succeeded', 'source': 'user', 'createdAt': now(), 'finishedAt': None if pending else now()})
                result = {'threadId': data['threadId'], 'turnId': tid, 'messageId': json['clientMessageId']}
            elif method == 'POST' and path == '/api/thread/stop':
                for t in data['turns']:
                    if t['status'] in {'queued', 'running', 'waiting'}:
                        t.update(status='cancelled', finishedAt=now())
                for m in data['messages']:
                    if (m.get('approval') or {}).get('state') == 'pending':
                        m['approval']['state'] = 'expired'
                result = {'ok': True}
            elif method == 'GET' and path == '/api/state':
                result = data
            else:
                raise HTTPException(404, 'Unsupported mock operation.')
            db.execute('INSERT INTO nod_demo VALUES (?,?) ON CONFLICT(owner) DO UPDATE SET payload=excluded.payload', (self.user, jsonlib.dumps(data)))
            return result


def connection(user):
    if not enabled():
        raise HTTPException(404, 'Nod preview unavailable.')
    return {'site': 'https://nod.example.test', 'mock': True}, MockNod(user)
