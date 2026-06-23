"""
workflows/knowledge/entities.py

Deterministic entity extraction — the cheap, reliable backbone of cross-source
linking. No LLM, no embeddings: just regex + a caller-supplied vocabulary.

The thesis is that in a large org the *explicit* references are the strongest
links and the easiest to get right: a Confluence page that says "see PAY-1421"
is unambiguously about that Jira issue; a PR titled "harden JB-One RASP check"
names a system. Semantic similarity (embeddings) finds the *fuzzy* links; this
module finds the *hard* ones. The cross-linker uses both.

Extracted types:
    jira_keys   PROJECT-123 style issue keys
    pr_refs     owner/repo#123  and bare #123
    urls        http(s) links
    services    matches against a caller vocabulary (service / system names)
    acronyms    2–6 char all-caps tokens (RASP, OAuth-ish, SSO, ...)
"""

from __future__ import annotations

import re
from typing import Iterable

# A Jira key: an uppercase project key (letters/digits, starts with a letter)
# followed by -<number>. Bounded so "UTF-8" / "COVID-19" style noise is rarer.
_JIRA_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d+)\b")
_PR_QUALIFIED_RE = re.compile(r"\b([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#\d+)\b")
_PR_BARE_RE = re.compile(r"(?<![\w/])#(\d{1,7})\b")
_URL_RE = re.compile(r"https?://[^\s<>()\"']+")
_ACRONYM_RE = re.compile(r"\b([A-Z]{2,6})\b")

# Acronym false-friends — common English / formatting tokens that match the
# all-caps shape but carry no entity signal.
_ACRONYM_STOP = {
    "THE", "AND", "FOR", "ALL", "ANY", "NOT", "BUT", "YOU", "ARE", "WAS",
    "API", "URL", "URI",  # too generic to be useful as a *topic* link
    "TODO", "FIXME", "NOTE", "WARN", "INFO", "OK", "ID", "OK",
}


def _services(text: str, vocab: Iterable[str]) -> set[str]:
    """Case-insensitive whole-word match of known service/system names."""
    found: set[str] = set()
    low = text.lower()
    for name in vocab:
        n = (name or "").strip()
        if not n:
            continue
        # word-ish boundary: name surrounded by non-alphanumerics or string ends
        pat = re.compile(r"(?<![a-z0-9])" + re.escape(n.lower()) + r"(?![a-z0-9])")
        if pat.search(low):
            found.add(n)
    return found


def extract_entities(text: str, *, service_vocab: Iterable[str] = ()) -> dict[str, list[str]]:
    """Extract typed entities from a blob of text. Order-stable, de-duplicated.

    `service_vocab` is the list of service/system names worth tracking — pass
    the `services:` list from a watchlist so matching is scoped to what the
    user actually cares about (keeps acronym noise down).
    """
    text = text or ""
    jira = _dedup(_JIRA_RE.findall(text))
    prs = _dedup(_PR_QUALIFIED_RE.findall(text) + _PR_BARE_RE.findall(text))
    urls = _dedup(_URL_RE.findall(text))
    services = sorted(_services(text, service_vocab))
    acronyms = _dedup(a for a in _ACRONYM_RE.findall(text) if a not in _ACRONYM_STOP)
    return {
        "jira_keys": jira,
        "pr_refs": prs,
        "urls": urls,
        "services": services,
        "acronyms": acronyms,
    }


def entity_keys(entities: dict[str, list[str]]) -> set[str]:
    """Flatten an entity dict into a single comparable key set.

    Keys are namespaced (``jira:PAY-1`` vs ``svc:Payments``) so a Jira key and a
    service name never collide. Used to score the overlap between two documents.
    """
    out: set[str] = set()
    prefix = {"jira_keys": "jira", "pr_refs": "pr", "services": "svc", "acronyms": "acr"}
    for kind, items in entities.items():
        p = prefix.get(kind)
        if not p:  # urls are not useful as shared-entity links
            continue
        for it in items:
            out.add(f"{p}:{it}")
    return out


def shared_entities(
    text_a: str, text_b: str, *, service_vocab: Iterable[str] = ()
) -> set[str]:
    """Namespaced entity keys present in BOTH texts — an explicit link signal."""
    a = entity_keys(extract_entities(text_a, service_vocab=service_vocab))
    b = entity_keys(extract_entities(text_b, service_vocab=service_vocab))
    return a & b


def _dedup(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out
