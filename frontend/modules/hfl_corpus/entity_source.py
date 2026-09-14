"""Current corpus access for derived entities; no local corpus copy or capture store."""
from __future__ import annotations
import os
import re
from collections import Counter
from datetime import date
from urllib.parse import quote
from config import get_settings
from modules.hfl_corpus.corpus import corpus_index, entry_occurrence_date
from modules.hfl_corpus.remote import RemoteCorpusClient
from modules.hfl_corpus.secrets import is_secret_entry, normalize_secret_tags
from modules.profile.store import get_profile_store

def collect_entries(store, month: str = 'latest') -> tuple[list[dict], str]:
    """Collect before mutation; source errors propagate without withdrawing existing data."""
    from workflows.knowledge.entities import extract_entities
    settings = get_settings()
    profile = get_profile_store().get()
    protected = normalize_secret_tags(profile.secret_tags)
    source_url = settings.hfl_corpus_api_url
    if source_url:
        client = RemoteCorpusClient(source_url, settings.hfl_corpus_api_token)
        documents, month = client.knowledge_documents(month, secret_tags=protected)
    else:
        from modules.hfl_corpus.corpus import resolve_corpus_root
        if not resolve_corpus_root().is_dir():
            raise ValueError('Local corpus directory is unavailable')
        documents = corpus_index.documents(force=True)
    selected = []
    for document in documents:
        for entry in document.entries:
            if is_secret_entry(entry, protected):
                continue
            occurred = entry_occurrence_date(entry)
            if occurred is None:
                continue
            selected.append((document, entry, occurred))
    if month == 'latest':
        month = max((occurred.isoformat()[:7] for _, _, occurred in selected), default=date.today().isoformat()[:7])
    if month != 'all':
        date.fromisoformat(month + '-01')
    result = []
    legacy_signatures = Counter((entry.header, entry.source) for _, entry, _ in selected)
    seen = {}
    for document, entry, occurred in selected:
        if month != 'all' and occurred.isoformat()[:7] != month:
            continue
        match = re.search(r'^\s*Entry ID:\s*(\S+)', entry.text, re.M | re.I)
        if match:
            identity = match.group(1)
        else:
            signature = entry.header + '\n' + entry.source
            if legacy_signatures[(entry.header, entry.source)] > 1:
                signature += '\n' + entry.moment
            identity = store.legacy_id(signature)
        if identity in seen:
            if seen[identity] != entry.text:
                raise ValueError('Conflicting duplicate identity; review source entries before indexing')
            continue
        seen[identity] = entry.text
        entities = {}
        result.append(dict(id=identity, title=entry.moment, text=entry.text,
                           date=occurred.isoformat(), source=entry.source,
                           tags=list(entry.tags), entities=entities,
                           path=document.relative_path, anchor=entry.anchor,
                           ref=source_url.rstrip('/') + '/hfl-corpus/document/' + quote(document.relative_path, safe='/') + '#' + quote(entry.anchor)))
    return result, month



def entry_locator(item):
    """Signed location hint; entry content and permissions are still read live."""
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(get_settings().secret_key, salt='graph-entry-location').dumps(
        {'id': item['id'], 'path': item['path'], 'anchor': item['anchor']})
