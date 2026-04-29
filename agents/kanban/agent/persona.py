"""Persona helpers — render an agent's identity into Kanban comments.

Two modes are supported by the orchestrator:

- **Mode A** (real Trello/Jira account per profile): when the profile's
  `provider_credentials` env vars are set, the orchestrator builds a per-profile
  KanbanProvider authenticated as that agent's own account. Trello attributes
  the comment / move natively to that member — avatar, name, audit log, all real.

- **Mode B** (signed comments under a shared bot account, default): every comment
  is prefixed with a persona signature block so a human reading the board can see
  *who* posted, even though the underlying API account is shared.

This module supplies the Mode B comment formatter. Mode A goes through
`factory.create_provider()` with the per-profile creds — no signature is needed
there because Trello already shows the member.
"""

from __future__ import annotations

from agents.kanban.profiles.schema import AgentProfile, PersonaConfig


def has_persona(profile: AgentProfile) -> bool:
    """True if the profile has any persona fields populated."""
    p = profile.persona
    return any([p.display_name, p.email, p.avatar_url, p.signature, p.role])


def format_signature_block(profile: AgentProfile) -> str:
    """Render a one-line signature block for the top of a Kanban comment.

    Empty string when the profile has no persona configured — callers should
    skip prepending in that case.
    """
    p = profile.persona
    if not has_persona(profile):
        return ""

    name = p.display_name or profile.name or profile.id
    bits: list[str] = [f"**{name}**"]
    if p.role:
        bits.append(f"_{p.role}_")
    if p.email:
        bits.append(f"<{p.email}>")
    line = " · ".join(bits)

    parts: list[str] = []
    if p.avatar_url:
        # Markdown image rendered inline at the front so the avatar is visible.
        parts.append(f"![{name}]({p.avatar_url})")
    parts.append(f"> 👤 {line}")
    if p.signature:
        parts.append(f"> _{p.signature}_")
    return "\n".join(parts)


def sign_comment(profile: AgentProfile, body: str) -> str:
    """Prepend a persona signature block to a comment body.

    No-op when the profile has no persona — body is returned unchanged.
    """
    sig = format_signature_block(profile)
    if not sig:
        return body
    return f"{sig}\n\n{body}"
