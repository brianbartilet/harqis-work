"""HFL and Telegram delivery for Hermes-owned entity consolidation."""
from datetime import datetime
from zoneinfo import ZoneInfo

from filelock import FileLock
from core.apps.sprout.app.celery import SPROUT
from workflows.hfl.entity_store import get_store
from workflows.hfl.entity_consolidation import load, report, save


def deliver(run_id):
    from workflows.hfl.dto import HflEntry
    from workflows.hfl.persistence import submit_hfl_entry
    from workflows.hfl.tasks.activity_radar import corpus_document_url, _notify
    with FileLock(str(get_store().path) + '.matching.lock', timeout=30):
        run = load(run_id)
        if run['state'] != 'complete':
            raise ValueError('Finish the run before delivering its summary')
        delivery = run['delivery']
        if not delivery.get('hfl'):
            entry = HflEntry(when=datetime.fromisoformat(run['created']),
                moment='Daily entity consolidation', what_happened=report(run),
                why_it_stayed='Automatic identity decisions, evidence and reversal references.',
                possible_use='entity-maintenance', tags=('entity-consolidation',),
                entry_id='hfl-entity-consolidation-' + run_id)
            result = submit_hfl_entry(entry, source='entity-consolidation', dedup_key='entity-consolidation:'+run_id)
            if result.get('delivery') in {'pending', 'outbox', 'forwarded'}:
                raise RuntimeError('Waiting for HFL summary persistence before Telegram delivery')
            delivery['hfl'] = result
            delivery['url'] = corpus_document_url(result, fallback_filename=datetime.fromisoformat(run['created']).astimezone(ZoneInfo('Asia/Singapore')).strftime('%Y-%m-%d.md'))
            save(run)
        if delivery.get('telegram_state') == 'sent':
            return delivery
        if delivery.get('telegram_state') == 'sending':
            raise ValueError('Telegram outcome uncertain; reconcile before retrying to avoid duplicate notification')
        counts = {}
        for pair in run['pairs'].values():
            counts.setdefault(pair['kind'], {'merged': 0, 'deferred': 0})
            counts[pair['kind']]['merged' if pair['state']=='merged' else 'deferred'] += 1
        text = 'Daily entity consolidation — ' + run_id + '\n'
        text += '\n'.join(f"{kind}: {c['merged']} merged groups, {c['deferred']} kept separate/deferred" for kind, c in sorted(counts.items())) or 'No changes.'
        text = text[:3000] + '\nHFL: ' + delivery['url']
        delivery['telegram_state'] = 'sending'
        save(run)
        delivery['telegram_ids'] = _notify(text)
        delivery['telegram_state'] = 'sent'
        delivery.pop('error', None)
        save(run)
        return delivery


@SPROUT.task(bind=True, max_retries=3)
def deliver_entity_consolidation(self, run_id):
    """Callable by Hermes through the API; no independent Beat schedule."""
    try:
        return deliver(run_id)
    except Exception as exc:
        with FileLock(str(get_store().path) + '.matching.lock', timeout=30):
            run = load(run_id)
            run['delivery']['error'] = type(exc).__name__
            save(run)
        if isinstance(exc, ValueError):
            raise
        raise self.retry(exc=exc, countdown=60)
