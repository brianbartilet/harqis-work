"""Bounded, entry-level reading feed using the corpus' existing filter rules."""
import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import HTTPException
from itsdangerous import BadSignature, URLSafeTimedSerializer

from config import get_settings
from modules.hfl_corpus.corpus import corpus_index, format_hfl_markdown, _entry_metadata, resolve_corpus_root
from modules.hfl_corpus.secrets import is_secret_entry
from modules.hfl_corpus.view_scope import parse_scope, predicate, resolved
from modules.hfl_corpus.workspace_views import WorkspaceState
from services.markdown import render_markdown
from services.safe_paths import resolve_reference, allowed_reference_roots, load_download_token
from modules.hfl_shares.viewer import classify_preview


def _is_tag_index(entry):
    """Summary tag inventories are document metadata, not reading entries."""
    if entry.header.strip().casefold() != 'tags' or entry.source:
        return False
    body = entry.text.partition('\n')[2].strip()
    return bool(re.fullmatch(r'Tags:\s*(?:#[^\s#]+\s*)+', body, re.IGNORECASE))


def feed_page(params, *, include_secrets=False, secret_tags=()):
    try:
        values = {key: params[key] for key in WorkspaceState.model_fields if key in params}
        for key in ('rolling', 'page_size'):
            if key in values:
                values[key] = int(values[key])
        state = WorkspaceState.model_validate(values)
        scope = parse_scope(params.get('scope', ''))
        if scope.any:
            scope.all = WorkspaceState.model_validate({**scope.all.model_dump(), **values})
        order = params.get('order', 'desc')
        if order not in {'asc', 'desc'}:
            raise ValueError()
        narrowing = predicate(resolved(state))
        scope_narrowing = predicate(resolved(scope.all))
        alternatives = [predicate(resolved(item)) for item in scope.any]
    except ValueError as exc:
        raise HTTPException(422, 'Invalid timeline filters.') from exc
    def meaningful(item):
        if any(str(item.get(key, '')).strip() for key in ('q', 'source', 'date_from', 'date_to')) or item.get('rolling'):
            return True
        if item.get('entry_scope'):
            nested = parse_scope(item['entry_scope'])
            return any(meaningful(value.model_dump()) for value in [*nested.any, nested.all])
        return False
    if not (meaningful(state.model_dump()) or any(meaningful(item.model_dump()) for item in scope.any) or meaningful(scope.all.model_dump())):
        raise HTTPException(422, 'Apply a search, source, or date filter before viewing the timeline.')
    fingerprint = hashlib.sha256(json.dumps([state.model_dump(), scope.model_dump(), order, include_secrets, sorted(secret_tags)], sort_keys=True).encode()).hexdigest()
    signer = URLSafeTimedSerializer(get_settings().secret_key, salt='corpus-curated-feed')
    after = None
    if params.get('cursor'):
        try:
            cursor = signer.loads(params['cursor'], max_age=3600)
            if cursor['scope'] != fingerprint:
                raise ValueError()
            after = tuple(cursor['after'])
        except (BadSignature, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, 'This timeline expired or its filters changed. Reopen it to continue.') from exc
    matches = []
    for document in corpus_index.documents():
        for entry in document.entries:
            if _is_tag_index(entry):
                continue
            if is_secret_entry(entry, secret_tags) and not include_secrets:
                continue
            if not narrowing(document, entry):
                continue
            if not scope_narrowing(document, entry) or (alternatives and not any(check(document, entry) for check in alternatives)):
                continue
            try:
                when = datetime.fromisoformat(entry.header.strip())
                stamp = when.replace(tzinfo=when.tzinfo or timezone.utc).timestamp()
                key = (0, -stamp if order == 'desc' else stamp, document.relative_path, entry.anchor)
            except (ValueError, OverflowError):
                key = (1, 0, document.relative_path, entry.anchor)
            matches.append((key, document, entry))
    matches.sort(key=lambda row: row[0])
    total = len(matches)
    remaining = [row for row in matches if after is None or row[0] > after]
    page = remaining[:50]
    entries = []
    root = resolve_corpus_root()
    roots = allowed_reference_roots(root)
    for key, document, entry in page:
        href = '/hfl-corpus/document/' + quote(document.relative_path, safe='/')
        if include_secrets:
            href += '?show_secrets=true'
        attachments = []
        raw_refs = _entry_metadata(entry.header, entry.text)[1]
        for raw in dict.fromkeys(raw_refs):
            ref = resolve_reference(raw, source_document=document.path or root / document.relative_path,
                                    corpus_root=root, reference_roots=roots)
            if ref.kind not in {'download', 'external'} or not ref.href:
                continue
            item = dict(label=ref.label.replace('\\', '/').rsplit('/', 1)[-1] if ref.kind == 'download' else ref.label, href=ref.href, kind=ref.kind)
            if ref.kind == 'download':
                token = ref.href.split('/')[-2]
                path = load_download_token(token, roots)
                preview = classify_preview(path, include_audio=True) if path else None
                item['token'] = token
                if preview and preview.kind in {'image', 'video', 'audio'}:
                    item['kind'] = preview.kind
                    item['media_url'] = ref.href.removesuffix('/download') + '/media'
            attachments.append(item)
        # Render metadata once, with references in the dedicated attachment area.
        lines = entry.text.splitlines()
        body = []
        in_refs = False
        for line in lines:
            if re.match(r'^\s*References:', line, re.I):
                in_refs = True
                continue
            if in_refs and (not line.strip() or line.strip().startswith('- ')):
                continue
            in_refs = False
            if re.match(r'^\s*(?:(?:Source|Tags|Machine|Entry ID):|#{1,6}\s+)', line, re.I):
                continue
            body.append(line)
        entries.append(dict(id=document.relative_path + '#' + entry.anchor,
            title=entry.moment or entry.header or document.name, date=entry.header,
            source=entry.source, tags=entry.tags, attachments=attachments,
            href=href + '#' + quote(entry.anchor, safe=''),
            html=str(render_markdown(format_hfl_markdown("\n".join(body), ())))))
    next_cursor = signer.dumps({'scope': fingerprint, 'after': page[-1][0]}) if len(remaining) > 50 else None
    return {'entries': entries, 'total': total, 'next_cursor': next_cursor}
