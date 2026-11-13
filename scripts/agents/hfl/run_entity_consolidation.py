"""Run one bounded consolidation through the authenticated API, without an agent loop.

Usage: .venv/bin/python scripts/agents/hfl/run_entity_consolidation.py [--execution-id ID]
The default recovery ID permits one execution per Singapore date. No store writes.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


class API:
    def __init__(self, client, base, journal):
        self.client, self.base, self.journal = client, base, journal

    def call(self, path, body=None):
        import httpx
        # Retain the exact last request for recovery without storing credentials.
        self.journal.write_text(json.dumps(dict(path=path, body=body)), encoding='utf-8')
        for attempt in range(3):
            try:
                response = (self.client.get(self.base + path) if body is None
                            else self.client.post(self.base + path, json=body))
                if response.is_error:
                    raise RuntimeError('Entity API rejected request: HTTP ' + str(response.status_code))
                result = response.json()
                if body is not None:
                    import hashlib
                    identity = hashlib.sha256(json.dumps([path, body], sort_keys=True).encode()).hexdigest()
                    archive = self.journal.parent / (self.journal.stem + '-' + identity + '.json')
                    archive.write_text(json.dumps(dict(path=path, body=body, result=result)), encoding='utf-8')
                self.journal.write_text(json.dumps({'body': None, 'last_completed': path}), encoding='utf-8')
                return result
            except httpx.TransportError:
                if attempt == 2:
                    raise RuntimeError('Transport outcome uncertain; retain the recovery journal') from None


def run(api, execution_id, sleep=time.sleep):
    state = api.call('/consolidation/begin?compact=true', {})
    if 'bounded-assessment-v1' not in state.get('capabilities', []):
        raise RuntimeError('Deploy bounded-assessment-v1 before enabling this runner')
    path = '/consolidation/' + state['id']
    api.call(path + '/checkpoint', {})
    execution = api.call(path + '/executions', dict(execution_id=execution_id, max_pairs=40, seconds=900))
    if execution['state'] == 'running':
        reason, errors = 'budget', []
        try:
            # Claims and the server-side model budget bound every iteration.
            for _ in range(40):
                if time.time() >= execution['deadline'] - 30:
                    break
                packet = api.call(path + '/claims', dict(worker_id=execution_id, max_pairs=8,
                    max_bytes=100000, lease_seconds=900))
                claim = packet.get('claim')
                if not claim:
                    if packet.get('required_bytes') or packet.get('waiting'):
                        break
                    reason = 'exhausted'
                    break
                token = claim['token']
                assessment = api.call(path + '/claims/' + token + '/assess', {})
                if assessment['state'] == 'budget':
                    api.call(path + '/claims/' + token, {'action': 'release'})
                    break
                decisions = assessment['decisions']
                rejected = {i: d for i, d in decisions.items() if d['decision'] != 'merge'}
                approved = {i: d for i, d in decisions.items() if d['decision'] == 'merge'}
                if rejected:
                    receipt = api.call(path + '/decisions', dict(decisions=rejected, claim_token=token))
                    if any('error' in r for r in receipt['results']):
                        raise RuntimeError('A decision failed; inspect retained receipts')
                if len(approved) > 1:
                    api.call(path + '/groups', dict(anchor_id=assessment['anchor_id'], decisions=approved,
                        contradictions=assessment['contradictions'], claim_token=token))
                elif approved:
                    receipt = api.call(path + '/decisions', dict(decisions=approved, claim_token=token))
                    if any('error' in r for r in receipt['results']):
                        raise RuntimeError('A merge failed; inspect retained receipts')
                api.call(path + '/claims/' + token, {'action': 'release'})
        except Exception as exc:
            # Do not close over an uncertain write: the journal and active execution
            # stay available for explicit recovery. Never replay a new identity.
            raise RuntimeError('Execution incomplete; recover using the saved request and execution ID') from exc
        execution = api.call(path + '/executions/' + execution_id + '/close', dict(reason=reason, errors=errors))
    report_path = '/consolidation/' + execution['report_id'] + '?compact=true&limit=1'
    for _ in range(12):
        report = api.call(report_path)
        delivery = report.get('delivery', {})
        if delivery.get('hfl') and delivery.get('telegram_state') in {'sent', 'suppressed'} and delivery.get('url'):
            usage = execution.get('assessment_usage', {})
            operations = len(execution.get('operation_ids', []))
            return dict(execution_id=execution_id, merges=operations, counts=report['counts'],
                remaining=execution['remaining_eligible'], usage=usage,
                tokens_per_merge=((usage.get('input_tokens', 0) + usage.get('output_tokens', 0)) / operations
                                  if operations else None), delivery=delivery['telegram_state'])
        sleep(5)
    raise RuntimeError('Execution closed; report delivery not yet verified. Rerun the same execution ID.')


def main():
    from scripts.deploy import load_env_into_os, load_machine_config, machine_env_vars
    load_env_into_os()
    os.environ.setdefault('APP_CONFIG_FILE', str(ROOT / 'apps_config.yaml'))
    os.environ.setdefault('WORKFLOW_CONFIG', 'workflows.config')
    os.environ.update(machine_env_vars(load_machine_config(None)))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execution-id', default='batch-' + datetime.now(ZoneInfo('Asia/Singapore')).date().isoformat())
    args = parser.parse_args()
    import re
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', args.execution_id):
        parser.error('Invalid execution ID')
    base = (os.environ.get('HFL_CORPUS_API_URL') or os.environ.get('HFL_AGENT_BRIDGE_URL') or '').rstrip('/')
    token = os.environ.get('HFL_CORPUS_API_TOKEN', '')
    if not base or not token or '${' in base or '${' in token:
        parser.error('Configure the owning HFL API URL and token')
    journal_dir = ROOT / 'results/entity-consolidation-recovery'
    journal_dir.mkdir(parents=True, exist_ok=True)
    from filelock import FileLock
    import httpx
    try:
        with FileLock(str(journal_dir / 'runner.lock'), timeout=0):
            journal = journal_dir / (args.execution_id + '.json')
            # A prior uncertain request requires explicit recovery, not a blind new claim.
            if journal.exists():
                previous = json.loads(journal.read_text(encoding='utf-8'))
                if previous.get('body') is not None:
                    raise RuntimeError('An unfinished request is retained; inspect and replay it before resuming')
            with httpx.Client(timeout=180, headers={'Authorization': 'Bearer ' + token}) as client:
                result = run(API(client, base + '/api/hfl/entities', journal), args.execution_id)
            journal.write_text(json.dumps({'body': None, 'result': result}), encoding='utf-8')
            print(json.dumps(result))
        return 0
    except Exception as exc:
        print(json.dumps({'state': 'incomplete', 'execution_id': args.execution_id,
                          'error': str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
