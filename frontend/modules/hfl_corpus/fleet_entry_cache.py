"""Bounded, process-wide corpus reads for Fleet and its canonical snapshot API.

Intent records are never cached here: edits/status/assignment reads stay live.
Concurrent tabs share one corpus scan per 30-second window per server process.
"""
from threading import Lock
from time import monotonic

TTL_SECONDS = 30
_lock = Lock()
_key = None
_entries = None
_expires = 0


def context_key():
    import os
    from config import get_settings
    from modules.hfl_corpus.corpus import resolve_corpus_root
    from modules.hfl_corpus.secrets import normalize_secret_tags
    from modules.profile.store import get_profile_store
    settings = get_settings()
    return (settings.hfl_corpus_api_url, settings.hfl_corpus_api_token,
            str(resolve_corpus_root()), str(settings.profile_store_path),
            os.getenv('HARQIS_ENTITIES_DB'),
            normalize_secret_tags(get_profile_store().get().secret_tags))


def current_entries():
    global _key, _entries, _expires
    from modules.hfl_corpus import entities
    # The lock coalesces simultaneous cold reads, including on the canonical host.
    with _lock:
        key = context_key()
        if key == _key and _entries is not None and monotonic() < _expires:
            return _entries
        # Never serve an expired result when the source fails.
        entries = entities.current_entries()
        _key, _entries, _expires = key, entries, monotonic() + TTL_SECONDS
        return entries
