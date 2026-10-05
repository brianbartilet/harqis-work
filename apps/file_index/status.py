"""Read-only catalog coverage and estimated scan timing (no filesystem walk)."""
import os
import json
import time


def indexing_status(store, sources):
    automatic = os.environ.get('FILES_ENABLED', '').lower() in {'1', 'true', 'yes'}
    now = time.time()
    with store.connect() as db:
        counts = db.execute("""SELECT count(*) AS total,
            coalesce(sum(json_extract(data,'$.last_seen') IS NOT NULL),0) AS indexed,
            coalesce(sum(json_array_length(data,'$.categories') > 0),0) AS categorized
            FROM files""").fetchone()
        active = {r['key']: r['until'] for r in db.execute(
            "SELECT key,until FROM leases WHERE until>?", (now,))}
    coverage = dict(counts)
    for key in ('indexed', 'categorized'):
        coverage[key + '_percent'] = round(100 * coverage[key] / coverage['total'], 1) if coverage['total'] else None
    locations = []
    for source in sources:
        processed = source.get('processed')
        if processed is None:
            # Legacy failed scans recorded their partial count only in the audit log.
            with store.connect() as db:
                event = db.execute("SELECT at,data FROM events WHERE subject=? AND kind IN ('scan_failed','scan_completed','scan_partial') ORDER BY id DESC LIMIT 1", (source['id'],)).fetchone()
            processed = json.loads(event['data']).get('count', 0) if event and event['at'] >= (source.get('started_at') or 0) else source.get('count') or 0
        state = source.get('state', 'new')
        if state == 'scanning' and 'source:' + source['id'] not in active:
            state = 'interrupted'
        eligible = automatic and source.get('enabled', True) and source['kind'] != 'ftp' and source.get('configured_available') is not False
        due = max(source.get('last_scan') or 0, source.get('last_queued') or 0) + source.get('interval_hours', 24) * 3600
        locations.append({
            'id': source['id'], 'name': source['name'], 'state': state,
            'root': source.get('root', ''), 'kind': source['kind'], 'host': source.get('host'),
            'can_scan': source.get('enabled', True) and source['kind'] != 'ftp' and source.get('configured_available') is not False,
            'error_detail': source.get('error_detail'),
            'last_started': source.get('started_at'),
            'last_finished': source.get('finished_at', source.get('last_attempt') or source.get('last_scan')),
            'last_success': source.get('last_scan'), 'processed': processed,
            'warnings': source.get('warnings', []), 'warning_count': source.get('warning_count', 0),
            'progress_at': source.get('progress_at'), 'error': source.get('error'),
            'next_due': due if eligible and state != 'scanning' else None,
            'schedule': 'scanning' if state == 'scanning' else 'scheduled' if eligible else 'unavailable' if source.get('configured_available') is False else 'paused' if not source.get('enabled', True) else 'reference only' if source['kind'] == 'ftp' else 'disabled',
        })
    return {'automatic_scans': automatic, 'coverage': coverage, 'locations': locations, 'as_of': now}
