"""Manual brainstorming uses the existing leased agent bridge and owner review."""
from pathlib import Path

from workflows.hfl.agent_bridge_store import digest


def snapshot(identity):
    from modules.hfl_corpus.ideas_api import canonical_snapshot
    from modules.hfl_corpus.entities import graph
    from modules.app_settings.store import read_settings
    data = canonical_snapshot()
    mindmap = next((m for m in data['maps'] if m['id'] == identity), None)
    if not mindmap:
        raise KeyError(identity)
    if not mindmap.get('prompt', '').strip():
        raise ValueError('Save brainstorming instructions before requesting suggestions.')
    available = {n['id']: n for n in graph(limit=0)['nodes']}
    members = [{k: available[i].get(k) for k in ('id', 'label', 'kind', 'description', 'body', 'status')}
               for i in mindmap['members'] if i in available][:100]
    source = {'id': identity, 'title': mindmap['name'], 'version': mindmap['version'], 'prompt': mindmap['prompt'], 'members': members, 'attachments': []}
    path = Path(__file__).resolve().parents[3] / 'workflows/hfl/prompts/ideas_brainstorm.md'
    runtime = path.read_text(encoding='utf-8')
    return {'source_key': 'mindmap:' + identity, 'kind': 'mindmap', 'source_id': identity, 'source': source,
            'category_guidance': '', 'policy': 'ideas-brainstorm-v1', 'execution_settings': {**read_settings(), 'agent_mode': 'restricted'},
            'runtime_prompt': runtime, 'prompt_path': 'workflows/hfl/prompts/ideas_brainstorm.md',
            'prompt_hash': digest(runtime), 'instruction_hash': digest({'source': {k: v for k, v in source.items() if k != 'version'}, 'runtime': runtime})}
