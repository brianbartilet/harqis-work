"""Preview/reconcile the repository-owned Hermes minute bridge schedule.

Usage: python scripts/agents/hfl/setup_agent_bridge.py [--apply]
The preview is read-only. --apply installs the wrapper and creates/updates only
the named bridge cron job. Hermes gateway must already run the scheduler.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from agent_bridge_runner import hermes_command


REPO_ROOT = Path(__file__).resolve().parents[3]
PROGRAM = """
import json, sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from cron.jobs import create_job, list_jobs, update_job
from hermes_constants import get_hermes_home
from hermes_time import get_timezone

data = json.load(sys.stdin)
spec = data['spec']
tz = get_timezone()
expected = ZoneInfo(spec['timezone'])
local_matches = tz is None and all(datetime(datetime.now().year, month, 1).astimezone().utcoffset() == datetime(datetime.now().year, month, 1, tzinfo=expected).utcoffset() for month in (1, 7))
if str(tz) != spec['timezone'] and not local_matches:
    raise SystemExit('Set the Hermes timezone to ' + spec['timezone'] + ' before installing this schedule.')
jobs = [job for job in list_jobs(include_disabled=True) if job.get('name') in {spec['name'], 'hfl-agent-bridge-daily'}]
if len(jobs) > 1:
    raise SystemExit('Multiple bridge schedules exist; reconcile them before installing.')
script = get_hermes_home() / 'scripts' / 'hfl_agent_bridge_dispatch.py'
if data['apply']:
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(data['wrapper'], encoding='utf-8')
    if jobs:
        job = update_job(jobs[0]['id'], {'name': spec['name'], 'schedule': spec['schedule'], 'script': str(script), 'no_agent': True, 'deliver': 'local', 'workdir': data['repo']})
    else:
        job = create_job(prompt='', schedule=spec['schedule'], name=spec['name'], script=str(script), no_agent=True, deliver='local', workdir=data['repo'])
    print(json.dumps({'job_id': job['id'], 'installed': True, 'script': str(script)}))
else:
    print(json.dumps({'existing_jobs': len(jobs), 'script': str(script), 'schedule': spec['schedule'], 'timezone': spec['timezone'], 'installed': False}))
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    spec = json.loads(Path(__file__).with_name('agent_bridge_schedule.json').read_text(encoding='utf-8'))
    command, hermes_root = hermes_command()
    runner = REPO_ROOT / spec['runner']
    command_line = [sys.executable, str(runner), *spec['arguments']]
    wrapper = 'import subprocess\nraise SystemExit(subprocess.call(' + repr(command_line) + ', cwd=' + repr(str(REPO_ROOT)) + '))\n'
    result = subprocess.run([command[0], '-c', PROGRAM], cwd=hermes_root, input=json.dumps({'spec': spec, 'repo': str(REPO_ROOT), 'wrapper': wrapper, 'apply': args.apply}),
                            text=True, encoding='utf-8', capture_output=True, timeout=30)
    if result.returncode:
        print(result.stderr.strip(), file=sys.stderr)
        raise SystemExit(result.returncode)
    print(result.stdout.strip())


if __name__ == '__main__':
    main()
