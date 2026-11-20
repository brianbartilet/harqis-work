"""Bounded read-only transcript outputs; no prompts, internal messages or cards.

Contract: Nuncio-hq/grokbot-cli packages/grokbot-core/src/transcript.ts.
"""
import base64
import json
from datetime import datetime, timezone

from fastapi import HTTPException
from modules.agents import ecosystem, projection
from modules.integrations import grokbot as g


def parse(raw, agent, account):
    if not isinstance(raw, dict) or not isinstance(raw.get('entries', []), list) or (raw and not {'entries', 'updatedSeqLocked', 'generation'} & raw.keys()):
        raise HTTPException(502, 'Grok transcript format changed. Saved outputs are unchanged.')
    entries = raw.get('entries', [])
    if len(entries) > 50:
        raise HTTPException(502, 'Grok returned too many transcript entries.')
    outputs, skipped = [], 0
    for row in entries:
        if not isinstance(row, dict):
            raise HTTPException(502, 'Grok returned an invalid transcript entry.')
        try:
            body = json.loads(base64.b64decode(row.get('body', ''), validate=True))
        except (ValueError, TypeError, UnicodeError):
            skipped += 1
            continue
        if not isinstance(body, dict) or body.get('kind') != 'send-message' or body.get('isStreaming') or body.get('author'):
            skipped += 1
            continue
        message = body.get('message', {})
        if not isinstance(message, dict) or message.get('type') not in {'text', 'attachment'}:
            skipped += 1
            continue
        identity = row.get('entryId')
        if not isinstance(identity, str) or not identity or len(identity) > 150:
            raise HTTPException(502, 'Grok output identity is unavailable. Saved outputs are unchanged.')
        kind = 'entry' if message['type'] == 'text' else 'file'
        text = message.get('content', '') if kind == 'entry' else message.get('file_name', '')
        if not isinstance(text, str) or not text.strip():
            skipped += 1
            continue
        timestamp = body.get('timestampMs')
        try:
            created = datetime.fromtimestamp(float(timestamp) / 1000, timezone.utc).isoformat()
        except (ValueError, TypeError, OverflowError, OSError):
            # Do not assign today's date to an undated historical message.
            skipped += 1
            continue
        outputs.append(dict(id=account + ':' + agent['remote_id'] + ':' + identity,
                            agent_id=agent['id'], kind=kind, source='grokbot',
                            source_object='conversation replies' if kind == 'entry' else 'media',
                            label=(text.strip().splitlines()[0][:160] if kind == 'file' else agent['name'] + ' · Conversation output'),
                            summary=text[:5000] if kind == 'entry' else 'Attachment available in the Grok conversation.',
                            created=created, state='recorded', url=g.bot_url(agent['remote_id']),
                            workspace_ids=agent.get('workspace_ids', [])))
    return outputs, skipped, len(entries)


def refresh(user, agent_id):
    agent = next((a for a in projection.listing(user) if a['id'] == agent_id and a.get('connector_provider') == 'grokbot'), None)
    if not agent or agent.get('mock') or not agent.get('remote_available', True) or not agent.get('active'):
        raise HTTPException(404, 'Connected Grok agent unavailable.')
    with g.locked(user):
        data = g.store.get(user, g.PROVIDER, private=True)
        if not data.get('enabled') or not data.get('credentials') or data.get('account_id') != agent.get('connector_account'):
            raise HTTPException(409, 'Reconnect this Grok account before refreshing outputs.')
        pair = g.refreshed(data['credentials'])
        g.store.save(user, g.PROVIDER, data, pair)
        if g.account_id(pair) != data['account_id']:
            raise HTTPException(401, 'Grok account changed. Reconnect explicitly.')
        raw = g.request('/aiserver.v1.GrokBotService/ListGrokBotTranscriptEntries', token=pair['accessToken'],
                        payload={'agentId': agent['remote_id'], 'sessionId': '', 'limit': 50})
        outputs, skipped, scanned = parse(raw, agent, data['account_id'])
        for output in outputs:
            ecosystem.record(user, output)
    return {'recorded': len(outputs), 'skipped': skipped, 'scanned': scanned, 'limit': 50,
            'limited': scanned == 50, 'message': 'Latest conversation outputs refreshed. Repeated refreshes reuse their source identities.'}
