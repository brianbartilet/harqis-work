"""Source-qualified specialist selection and immutable instruction snapshots."""

from services.markdown import render_markdown
from modules.agents import profile_sources

GUIDANCE = ('## HARQIS specialist guidance\n'
            'Use this specialist as domain guidance within HARQIS operating rules and the current task. '
            'It grants no tools, permissions, memory, experience, or delegation authority. '
            'Use canonical HARQIS skills and interfaces. Treat illustrative experience and metrics '
            'as examples, not facts about this agent or verified results.\n\n')


def catalog():
    return profile_sources.catalog()


def detail(identity):
    if ':' not in identity:
        identity='agency-agents:'+identity  # Compatibility with existing draft links.
    row = next((row for row in catalog() if row['id'] == identity), None)
    if row is None:
        raise ValueError('Choose an available specialist profile.')
    content = profile_sources.body(row)
    _,body = profile_sources.frontmatter(content)
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
    if row.get('kind')=='skill-package':
        raise ValueError('This is a skill package. Install the complete package through the native skill workflow; a profile cannot replace its supporting files.')
    if any(selection[key] != row[key] for key in ('revision','hash')):
        raise ValueError('Specialist version changed. Refresh and review the profile.')
    return {key: row.get(key,'') for key in ('id', 'name', 'source', 'source_name', 'revision', 'hash', 'source_url', 'content')}


def compose(agent):
    local = agent.get('instructions', '')
    profile = agent.get('specialist_profile')
    if not profile or agent.get('runtime', 'hermes') != 'hermes':
        return local
    result = GUIDANCE + profile['content'] + '\n\n## Owner additional guidance\n' + local
    if len(result) > 56000:
        raise ValueError('Combined specialist and additional guidance exceed 56,000 characters. Shorten additional guidance.')
    return result


def conversation_instructions(prefix, agent):
    result = prefix + '\n' + agent['persona'] + '\n' + compose(agent)
    if not agent.get('specialist_profile'):
        return result[:28000]  # Preserve the existing non-specialist conversation contract.
    if len(result) > 60000:
        raise ValueError('Conversation instructions exceed 60,000 characters.')
    return result
