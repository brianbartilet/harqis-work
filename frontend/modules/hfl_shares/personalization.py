"""Owner-only entity lookup and explicit binding of reusable sharing recipes."""
from dataclasses import replace

import httpx

from config import get_settings


def entity_catalog():
    settings = get_settings()
    try:
        if settings.hfl_corpus_api_url:
            response = httpx.get(
                settings.hfl_corpus_api_url.rstrip('/') + '/api/hfl/entities',
                params={'limit': 0},
                headers={'Authorization': 'Bearer ' + settings.hfl_corpus_api_token}, timeout=60)
            response.raise_for_status()
            rows = response.json()['entities']
        else:
            from modules.hfl_corpus.entities import entity_index
            rows = entity_index()
        return [dict(id=row['id'], label=row['label'], kind=row['kind'],
                     count=len(row.get('entries', []))) for row in rows]
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise ValueError('Entity information could not load. Retry before sharing.') from exc


def bind(configuration):
    if not configuration.entity_id:
        if configuration.entity_template:
            raise ValueError('Choose an entity before previewing or generating this template.')
        return configuration
    entity = next((row for row in entity_catalog() if row['id'] == configuration.entity_id), None)
    if entity is None:
        raise ValueError('This entity is unavailable or was merged. Search and select its current identity.')
    return replace(configuration, entity_name=entity['label'], entity_kind=entity['kind'],
                   recipient=entity['label'])


def unbound_template(configuration):
    """Keep recipe rules and exclusions, never the last recipient or live approval set."""
    if not configuration.entity_template:
        return configuration
    activity = dict(configuration.activity)
    activity.pop('approved_ids', None)
    return replace(configuration, entity_id='', entity_name='', entity_kind='', recipient='',
                   activity=activity)
