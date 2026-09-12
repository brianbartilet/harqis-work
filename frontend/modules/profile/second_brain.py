"""Canonical timeline settings surfaced from the owner profile."""
import os
import httpx
from config import get_settings
from workflows.hfl.timeline_store import FollowUpStore, store_path


async def timeline_settings(days=None):
    settings=get_settings()
    if settings.hfl_corpus_api_url and os.getenv('HFL_TIMELINE_LOCAL_PREVIEW')!='1':
        async with httpx.AsyncClient(timeout=20) as client:
            response=await client.request('GET' if days is None else 'PATCH',
                settings.hfl_corpus_api_url.rstrip('/')+'/api/hfl/timeline/settings',
                headers={'Authorization':'Bearer '+settings.hfl_corpus_api_token},
                **({} if days is None else {'json':{'complete_after_days':days}}))
            response.raise_for_status()
            return response.json()
    canonical=FollowUpStore(store_path())
    return canonical.settings() if days is None else canonical.save_settings(days)
