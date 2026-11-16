"""Nod inventory adapter: GET /api/apps and /api/schedules (2026-11-16).

Contract: n8n-io/nod src/server/integrations.ts and schedules.ts.
Only bounded display metadata is retained; never prompts, tokens or tool data.
"""
from fastapi import HTTPException
from modules.agents import entities
from modules.integrations.nod import context


def required(row, field):
    value = row.get(field)
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError('Unsupported Nod inventory identity.')
    return value


def refresh(user, agent_id):
    try:
        data, client, _ = context(user, agent_id)
    except HTTPException:
        from modules.agents import service
        try:
            agent = service.store().get(agent_id)
        except KeyError:
            raise HTTPException(404, 'Nod agent unavailable.') from None
        if agent.get('connector_user') != user or agent.get('connector_provider') != 'nod':
            raise HTTPException(404, 'Nod agent unavailable.') from None
        scope = 'nod:' + agent['connector_site'].rstrip('/')
        for category in ('applications', 'schedules', ''):
            entities.stale(user, scope, category, 'stale')
        return {'counts': {}, 'warnings': ['Nod is unavailable; last-known entities were retained.']}
    scope = 'nod:' + data['site'].rstrip('/')
    common = dict(source='nod', scope=scope, mock=data.get('mock', False))
    connector = entities.entity('connector', scope, 'installation', 'Nod', url=data['site'], state='connected', **common)
    entities.observe(user, [connector], [('agent:'+agent_id, connector['id'], 'connected through')])
    warnings, counts = [], {}
    for category, path in [('applications', '/api/apps'), ('schedules', '/api/schedules')]:
        try:
            raw = client.request('GET', path)
            if not isinstance(raw, list) or len(raw) > 1000 or any(not isinstance(r, dict) for r in raw):
                raise ValueError('Unsupported or oversized Nod inventory response.')
            rows, edges = [], []
            for item in raw:
                if category == 'applications':
                    # The API also lists available-but-never-connected services.
                    if not item.get('connectionId'):
                        if item.get('status') == 'connected':
                            raise ValueError('Connected application has no stable identity.')
                        continue
                    slug, cid = required(item, 'slug'), required(item, 'connectionId')
                    app = entities.entity('application', 'nod:apps', slug, required(item, 'name'),
                                          summary='Application shared across connected accounts.', source='nod',
                                          mock=data.get('mock', False))
                    account = entities.entity('account', scope+':'+slug, cid,
                        str(item.get('accountName') or item.get('accountEmail') or item['name'])[:300],
                        url=data['site']+'/apps', state=item.get('status', 'unknown'),
                        summary='Account connection for '+item['name'], category=category, **common)
                    rows.extend([app, account])
                    edges.extend([(connector['id'], account['id'], 'provides'),
                                  (account['id'], app['id'], 'account for')])
                else:
                    sid = required(item, 'id')
                    summary = ' · '.join(str(item.get(k) or '') for k in ('kind', 'cron', 'timeZone', 'nextRun')).strip(' ·')
                    schedule = entities.entity('schedule', scope, sid, required(item, 'title'),
                        url=data['site']+'/schedule', state='enabled' if item.get('enabled') is True else 'paused',
                        summary=summary, category=category, **common)
                    rows.append(schedule)
                    edges.append((connector['id'], schedule['id'], 'owns schedule'))
                    # Watch IDs are connection IDs, not names or permission grants.
                    watch = item.get('watch') or []
                    if not isinstance(watch, list) or any(not isinstance(v, str) for v in watch):
                        raise ValueError('Unsupported Nod watch identities.')
                    for account in entities.snapshot(user)['items']:
                        if account['kind'] == 'account' and account['scope'] == scope and any(p['remote_id'] in watch for p in account['provenance']):
                            edges.append((schedule['id'], account['id'], 'watches'))
            # Successful absence means no longer observed, never deletion. Restore
            # present observations in the same transaction as their relationships.
            entities.reconcile(user, scope, category, rows, edges)
            counts[category] = len({r['id'] for r in rows if r['kind'] != 'application'})
        except (HTTPException, ValueError) as exc:
            status = 'unsupported' if isinstance(exc, HTTPException) and exc.status_code == 404 else 'stale'
            entities.stale(user, scope, category, status)
            warnings.append('Nod '+category+' '+('are unsupported by this server.' if status == 'unsupported' else 'could not refresh; last-known entities were retained.'))
    return {'counts': counts, 'warnings': warnings}
