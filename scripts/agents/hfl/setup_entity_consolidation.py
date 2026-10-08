"""Reconcile the daily Hermes job.

Usage: python scripts/agents/hfl/setup_entity_consolidation.py [--apply]
"""
import argparse
import json
import subprocess
from pathlib import Path

from agent_bridge_runner import bootstrap, hermes_command

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = '''
import json, sys
from datetime import datetime
from zoneinfo import ZoneInfo
from cron.jobs import create_job, list_jobs, update_job
from hermes_time import get_timezone
data = json.load(sys.stdin)
spec = data['spec']
tz = get_timezone()
expected = ZoneInfo(spec['timezone'])
local_matches = tz is None and all(datetime(datetime.now().year, month, 1).astimezone().utcoffset() == datetime(datetime.now().year, month, 1, tzinfo=expected).utcoffset() for month in (1, 7))
if str(tz) != spec['timezone'] and not local_matches:
    raise SystemExit('Hermes timezone must be ' + spec['timezone'])
jobs = [j for j in list_jobs(include_disabled=True) if j.get('name') == spec['name']]
if len(jobs) > 1:
    raise SystemExit('Duplicate consolidation schedules need reconciliation')
result = {'installed': False, 'existing_jobs': len(jobs), 'schedule': spec['schedule']}
if data['apply']:
    fields = dict(prompt=spec['prompt'], schedule=spec['schedule'], name=spec['name'],
                  no_agent=False, deliver='local', workdir=data['repo'])
    job = update_job(jobs[0]['id'], fields) if jobs else create_job(**fields)
    result.update(installed=True, job_id=job['id'])
print(json.dumps(result))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    bootstrap()
    command, root = hermes_command(PROGRAM)
    spec = json.loads(Path(__file__).with_name('entity_consolidation_schedule.json').read_text(encoding='utf-8'))
    result = subprocess.run(command, cwd=root,
        input=json.dumps({'spec': spec, 'repo': str(ROOT), 'apply': args.apply}),
        capture_output=True, text=True, encoding='utf-8', timeout=30)
    print(result.stdout.strip())
    if result.returncode:
        raise SystemExit(result.stderr.strip())


if __name__ == '__main__':
    main()
