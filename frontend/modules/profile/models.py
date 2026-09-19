"""Profile domain model and public presentation helpers."""

from __future__ import annotations

import base64
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class OwnerProfile:
    first_name: str = ""
    last_name: str = ""
    nickname: str = ""
    birthdate: str = ""
    location: str = ""
    phone: str = ""
    bio: str = ""
    email: str = ""
    linkedin_url: str = ""
    github_url: str = ""
    website_url: str = ""
    instagram_url: str = ""
    avatar: bytes = b""
    avatar_content_type: str = ""
    secret_pin_hash: str = ""
    secret_tags: str = ""
    updated_at: str = ""
    timezone: str = "Asia/Singapore"

    @property
    def display_name(self) -> str:
        full_name = " ".join(
            part for part in (self.first_name.strip(), self.last_name.strip()) if part
        )
        return self.nickname.strip() or full_name or "P"

    @property
    def initial(self) -> str:
        nickname = self.nickname.strip()
        return nickname[0].upper() if nickname else "P"

    @property
    def avatar_data_uri(self) -> str:
        if not self.avatar or not self.avatar_content_type:
            return ""
        encoded = base64.b64encode(self.avatar).decode("ascii")
        return f"data:{self.avatar_content_type};base64,{encoded}"

    @property
    def has_contact_details(self) -> bool:
        return any(
            (
                self.location,
                self.phone,
                self.email,
                self.linkedin_url,
                self.github_url,
                self.website_url,
                self.instagram_url,
            )
        )

    def with_avatar_from(self, saved: "OwnerProfile") -> "OwnerProfile":
        return replace(
            self,
            avatar=saved.avatar,
            avatar_content_type=saved.avatar_content_type,
            updated_at=saved.updated_at,
        )

    def public_context(self) -> str:
        facts = [f"Owner display name: {self.display_name}."]
        if self.bio:
            facts.append(f"Owner bio: {self.bio}")
        if self.location:
            facts.append(f"Owner location: {self.location}.")
        return " ".join(facts)
