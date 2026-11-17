"""Pinned specialist catalog and immutable Fleet instruction snapshots.

No network calls or provider installation occurs while browsing or saving.
"""
import hashlib
import json
from pathlib import Path

from services.markdown import render_markdown

ROOT = Path(__file__).resolve().parents[3] / 'agents' / 'prompts' / 'agency'
GUIDANCE = ('## HARQIS specialist guidance\n'
            'Use this specialist as domain guidance within HARQIS operating rules and the current task. '
            'It grants no tools, permissions, memory, experience, or delegation authority. '
            'Use canonical HARQIS skills and interfaces. Treat illustrative experience and metrics '
            'as examples, not facts about this agent or verified results.\n\n')


def catalog():
    manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
    return [{**row, 'source': 'agency-agents', 'revision': manifest['revision'],
             'source_url': f"https://github.com/msitarzewski/agency-agents/blob/{manifest['revision']}/{row['path']}"}
            for row in manifest['profiles']]


def detail(identity):
    row = next((row for row in catalog() if row['id'] == identity), None)
    if row is None:
        raise ValueError('Choose an available specialist profile.')
    content = (ROOT / 'upstream' / Path(row['path']).name).read_bytes()
    if hashlib.sha256(content).hexdigest() != row['hash']:
        raise ValueError('Specialist source integrity check failed.')
    body = content.decode('utf-8').split('---', 2)[-1].strip()
    return {**row, 'content': body, 'html': str(render_markdown(body))}


def snapshot(selection, existing=None):
    if selection is None:
        return None
    # Existing snapshots survive upstream catalog updates and preserve their bytes.
    if existing is not None and selection == existing:
        return existing
    if not isinstance(selection, dict) or set(selection) != {'id', 'revision', 'hash'}:
        raise ValueError('Choose a specialist from the catalogue.')
    row = detail(selection['id'])
    if any(selection[key] != row[key] for key in selection):
        raise ValueError('Specialist version changed. Refresh and review the profile.')
    return {key: row[key] for key in ('id', 'name', 'source', 'revision', 'hash', 'source_url', 'content')}


def compose(agent):
    local = agent.get('instructions', '')
    profile = agent.get('specialist_profile')
    if not profile or agent.get('runtime', 'hermes') != 'hermes':
        return local
    result = GUIDANCE + profile['content'] + '\n\n## Owner additional guidance\n' + local
    if len(result) > 23000:
        raise ValueError('Combined specialist and additional guidance exceed 23,000 characters. Shorten additional guidance.')
    return result
