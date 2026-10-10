"""Incremental, source-scoped persona observations with durable run receipts."""
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

from filelock import FileLock
from modules.roles import store


def evidence(role):
    from modules.hfl_corpus.workspace_views import listing
    from modules.hfl_shares.router import _sharing_documents
    from modules.hfl_shares.models import ShareConfiguration, ALL_SOURCES
    from modules.hfl_shares.scope import build_snapshot
    from modules.hfl_corpus.secrets import normalize_secret_tags
    from modules.profile.store import get_profile_store
    spaces = {s['id']: s for s in listing()['views']}
    selected = role.get('workspace_ids', [])
    if not selected:
        return []
    if any(identity not in spaces for identity in selected):
        raise ValueError('A linked Space is unavailable.')
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).date().isoformat()
    config = ShareConfiguration(id='persona-audit', name='Persona audit', sources=(ALL_SOURCES,),
        date_from=cutoff, corpus_scope=json.dumps({'any': [spaces[i]['state'] for i in selected]}),
        activity={'sections': ['entries', 'actions', 'ideas'], 'workspace_ids': selected, 'include_completed': True})
    snapshot = build_snapshot(config, _sharing_documents((ALL_SOURCES,)),
                              secret_tags=normalize_secret_tags(get_profile_store().get().secret_tags))
    return [{'id': e.id, 'title': e.moment or e.header, 'text': e.text, 'source': e.source,
             'path': e.relative_path, 'anchor': e.anchor} for e in snapshot.all_entries
            if e.source not in {'persona', 'persona-audit', 'activity-radar', 'hfl-timeline-suggestions', 'hfl-followup-outcome'}]


def analyze(role, rows):
    from workflows.hfl.timeline import model_json
    from workflows.hfl.prompts import load_prompt
    from workflows.hfl.tasks.activity_radar import redact_secrets
    return model_json(redact_secrets(json.dumps({'role': role['name'], 'soul': role['soul'][:15000], 'evidence': rows})),
                      load_prompt('persona_audit'), 'observations')


def report(run):
    from workflows.hfl.dto import HflEntry
    from workflows.hfl.persistence import submit_hfl_entry
    summary = '\n'.join(f"- {r['name']}: {r.get('selected', 0)} new/changed sources; {r.get('observations', 0)} observations; {r.get('status', 'complete')}. Coverage: {r.get('coverage', '')}" for r in run.get('roles', []))
    summary = summary or 'No active roles with linked Spaces; no personal analysis was needed.'
    entry = HflEntry(when=datetime.fromisoformat(run['created_at']), moment='Persona audit · ' + run['status'],
        what_happened=f"Run {run['id']}\n\n{summary}\n\n" + run.get('error', ''),
        why_it_stayed='Private role refinement review; Soul and published shares were not changed.',
        tags=('persona-audit', 'secrets'), source='persona-audit')
    response = submit_hfl_entry(entry, source='persona-audit', dedup_key='persona-audit:' + run['id'], replace_duplicate=True)
    run['report_delivery'] = response.get('delivery', 'persisted')
    if response.get('delivery') == 'outbox':
        raise RuntimeError('The persona receipt is retained in the HFL outbox for retry.')
    return response


def run(identity):
    from modules.profile.store import get_profile_store
    # Serialize audits across HTTP workers and scheduled/manual triggers.
    with FileLock(str(get_profile_store().path) + '.persona-audit.lock', timeout=1):
        with store.connection() as db:
            previous = db.execute('SELECT payload FROM persona_runs WHERE id=?', (identity,)).fetchone()
        previous = json.loads(previous[0]) if previous else {}
        if previous.get('status') == 'complete':
            if previous.get('report_pending'):
                report(previous)
                previous['report_pending'] = False
                store.record_run(previous)
            return previous
        result = {'id': identity, 'created_at': previous.get('created_at') or store.now(), 'status': 'running',
                  'roles': previous.get('roles', []), 'report_pending': True}
        store.record_run(result)
        try:
            for role in store.listing():
                if role.get('archived') or not role.get('workspace_ids'):
                    continue
                rows = evidence(role)
                with store.connection() as db:
                    seen = dict(db.execute('SELECT evidence_id,digest FROM persona_seen WHERE role_id=?', (role['id'],)))
                pending = [(row, hashlib.sha256(row['text'].encode()).hexdigest()) for row in rows]
                pending = [(row, digest) for row, digest in pending if seen.get(row['id']) != digest]
                bounded, used = [], 0
                for row, digest in pending:
                    text = row['text'][:6000]
                    if used + len(text) > 60000 or len(bounded) >= 100:
                        break
                    bounded.append(({**row, 'text': text}, digest)); used += len(text)
                sources = {row['id']: row for row, _ in bounded}
                response = analyze(role, list(sources.values())) if sources else {'observations': []}
                observations = response.get('observations')
                if not isinstance(observations, list) or len(observations) > 12:
                    raise ValueError('Invalid analysis output.')
                additions = []
                for item in observations:
                    if not isinstance(item, dict) or not isinstance(item.get('text'), str) or not 1 <= len(item['text']) <= 3000:
                        raise ValueError('Invalid observation.')
                    ids = item.get('evidence_ids')
                    if not isinstance(ids, list) or not ids or any(not isinstance(i, str) or i not in sources for i in ids):
                        raise ValueError('Observation cited unavailable evidence.')
                    note_id = hashlib.sha256(json.dumps([item['text'], sorted(ids)]).encode()).hexdigest()[:24]
                    additions.append({'id': note_id, 'text': item['text'], 'status': 'pending', 'created_at': store.now(), 'run_id': identity,
                                      'evidence': [{k: sources[i][k] for k in ('id', 'title', 'source', 'path', 'anchor')} for i in ids]})
                known = {n['id'] for n in role['journal']}
                additions = [n for n in additions if n['id'] not in known]
                # A concurrent owner edit aborts this role without advancing evidence checkpoints.
                store.save(role['id'], role['revision'], {'journal': role['journal'] + additions} if additions else {},
                           checkpoints=[(row['id'], digest) for row, digest in bounded])
                result['roles'] = [r for r in result['roles'] if r['id'] != role['id']]
                result['roles'].append({'id': role['id'], 'name': role['name'], 'selected': len(bounded), 'observations': len(additions),
                    'coverage': f"90-day entries plus linked actions/ideas; {len(pending)-len(bounded)} sources deferred; per-source text capped at 6000 characters"})
                store.record_run(result)
            result['status'] = 'complete'
        except Exception as exc:
            logging.getLogger(__name__).warning('Persona audit failed run=%s type=%s', identity, type(exc).__name__)
            result['status'] = 'failed'
            result['error'] = 'Analysis failed or evidence changed. Existing Soul and published shares are preserved; retry is safe.'
        store.record_run(result)
        try:
            report(result)
            result['report_pending'] = False
        except Exception:
            result['report_pending'] = True
        store.record_run(result)
        # Retry receipts from earlier runs without regenerating their observations.
        for old in store.runs():
            if old['id'] != identity and old.get('report_pending') and old.get('status') in {'complete', 'failed'}:
                try:
                    report(old); old['report_pending'] = False; store.record_run(old)
                except Exception:
                    break
        return result
