"""Reconcile the daily Hermes job.

Usage: python scripts/agents/hfl/setup_entity_consolidation.py [--apply]
"""
import argparse
import json
import os
import subprocess
from pathlib import Path

from agent_bridge_runner import bootstrap, hermes_command

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = '''
import json, sys
from pathlib import Path
from datetime import datetime
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
    raise SystemExit('Hermes timezone must be ' + spec['timezone'])
jobs = [j for j in list_jobs(include_disabled=True) if j.get('name') == spec['name']]
if len(jobs) > 1:
    raise SystemExit('Duplicate consolidation schedules need reconciliation')
schedule = jobs[0]['schedule']['expr'] if jobs else spec['schedule']
result = {'installed': False, 'existing_jobs': len(jobs), 'schedule': schedule, 'no_agent': True}
if data['apply']:
    root = Path(data['repo'])
    scripts = (get_hermes_home() / 'scripts').resolve()
    scripts.mkdir(parents=True, exist_ok=True)
    launcher = scripts / 'harqis_entity_consolidation.py'
    if launcher.is_symlink():
        raise SystemExit('Refusing to overwrite a symlinked consolidation launcher')
    marker = '# Managed by HARQIS entity consolidation setup.'
    if launcher.exists() and not launcher.read_text(encoding='utf-8').startswith(marker):
        raise SystemExit('Existing launcher is not managed by this installer')
    launcher.write_text(marker + '\\nimport runpy\\nrunpy.run_path(' + repr(str(root / spec['script']))
                        + ', run_name="__main__")\\n', encoding='utf-8')
    fields = dict(prompt=spec['prompt'], schedule=schedule, name=spec['name'],
                  script=launcher.name, interpreter=data['interpreter'],
                  no_agent=True, deliver='local', workdir=data['repo'])
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
        input=json.dumps({'spec': spec, 'repo': str(ROOT), 'apply': args.apply,
            'interpreter': str(ROOT / ('.venv/Scripts/python.exe' if os.name == 'nt' else '.venv/bin/python'))}),
        capture_output=True, text=True, encoding='utf-8', timeout=30)
    print(result.stdout.strip())
    if result.returncode:
        raise SystemExit(result.stderr.strip())


if __name__ == '__main__':
    main()
