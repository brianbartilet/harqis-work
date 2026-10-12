"""Owner-only entity lookup and explicit binding of reusable sharing recipes."""
from dataclasses import replace

import httpx

from config import get_settings


class UnavailableEntityError(ValueError):
    """A saved entity selection no longer exists in the current catalog."""


def entity_catalog():
    settings = get_settings()
    try:
        if settings.hfl_corpus_api_url:
            response = httpx.get(
                settings.hfl_corpus_api_url.rstrip('/') + '/api/hfl/entities',
                params={'limit': 0},
                headers={'Authorization': 'Bearer ' + settings.hfl_corpus_api_token}, timeout=60)
            response.raise_for_status()
            payload = response.json()
            rows = payload['entities']
            types = payload.get('types', [])
        else:
            from modules.hfl_corpus.entities import entity_index
            rows = entity_index()
            from workflows.hfl.entity_types import listing
            types = listing()
        colors = {item['id']: item['color'] for item in types}
        return [dict(id=row['id'], label=row['label'], kind=row['kind'],
                     color=colors.get(row['kind'], '#95a7c3'),
                     count=len(row.get('entries', []))) for row in rows]
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise ValueError('Entity information could not load. Retry before sharing.') from exc


def selected_ids(configuration):
    return tuple(configuration.entity_ids) or ((configuration.entity_id,) if configuration.entity_id else ())


def bind(configuration):
    identities = selected_ids(configuration)
    if not identities:
        if configuration.entity_template:
            raise ValueError('Choose an entity before previewing or generating this template.')
        return configuration
    catalog = {row['id']:row for row in entity_catalog()}
    if any(identity not in catalog for identity in identities):
        raise UnavailableEntityError('An entity is unavailable or was merged. Search and select its current identity.')
    entities = tuple({key:catalog[identity][key] for key in ('id','label','kind')} for identity in identities)
    first = entities[0]
    # Old single-entity records retain canonical recipient binding until edited.
    recipient = configuration.recipient if configuration.entity_ids else ''
    return replace(configuration, entity_id=first['id'], entity_name=first['label'], entity_kind=first['kind'],
                   entity_ids=identities, entities=entities, recipient=recipient or first['label'])


def unbound_template(configuration):
    """Keep recipe rules and exclusions, never the last recipient or live approval set."""
    if not configuration.entity_template:
        return configuration
    activity = dict(configuration.activity)
    activity.pop('approved_ids', None)
    return replace(configuration, entity_id='', entity_name='', entity_kind='', entity_ids=(), entities=(), recipient='',
                   activity=activity)
