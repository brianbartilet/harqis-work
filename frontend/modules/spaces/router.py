"""Owner-only management of existing saved Spaces."""
import asyncio
from fastapi import APIRouter, Request
from web import require_user, page_context, templates
from modules.hfl_shares.security import make_csrf_token
from modules.hfl_corpus.workspace_views import listing
from modules.hfl_corpus.router import _uses_remote_corpus
from modules.hfl_corpus.remote import RemoteCorpusClient, RemoteCorpusError
from modules.hfl_corpus.corpus import corpus_index
from modules.hfl_corpus.view import corpus_view_cache
from modules.hfl_corpus.secrets import normalize_secret_tags
from modules.profile.store import get_profile_store

router = APIRouter(prefix='/spaces')

@router.get('')
async def page(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    data = await asyncio.to_thread(listing)
    warning = ''
    tags = normalize_secret_tags(get_profile_store().get().secret_tags)
    try:
        if _uses_remote_corpus():
            result = await asyncio.to_thread(RemoteCorpusClient.from_settings().index, params={'page_size': '20', 'include_secrets': 'false', 'secret_tags': ','.join(tags)})
            sources = result.get('sources', [])
        else:
            view = await asyncio.to_thread(corpus_view_cache.get, corpus_index.documents(), include_secrets=False, secret_tags=tags)
            sources = view.sources
    except RemoteCorpusError:
        sources = []
        warning = 'Activity sources are temporarily unavailable. Saved Space sources remain editable.'
    return templates.TemplateResponse(request, 'modules/spaces/index.html', page_context(request, user, 'spaces', csrf=make_csrf_token(user), space_data=data, source_options=sources, source_warning=warning))
