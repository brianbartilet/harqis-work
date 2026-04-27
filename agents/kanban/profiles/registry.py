"""
Profile registry — loads, resolves, and caches AgentProfile objects.

Resolution order for a card:
  1. Exact match on card assignee name
  2. Exact label match (e.g. "agent:code:harqis")
  3. Prefix label match (e.g. "agent:code" matches "agent:code:harqis")
  4. None — card is skipped by the orchestrator
"""

import logging
from pathlib import Path
from typing import Optional

from agents.kanban.interface import KanbanCard
from agents.kanban.profiles.schema import AgentProfile

logger = logging.getLogger(__name__)


class ProfileRegistry:
    def __init__(self):
        self._profiles: dict[str, AgentProfile] = {}

    # ── Loading ───────────────────────────────────────────────────────────────

    def register(self, profile: AgentProfile) -> None:
        self._profiles[profile.id] = profile
        logger.debug("Registered profile: %s", profile.id)

    def load_file(self, path: Path) -> AgentProfile:
        profile = AgentProfile.from_yaml(path)
        if profile.extends:
            base = self._profiles.get(profile.extends)
            if base:
                profile = profile.merge_base(base)
            else:
                logger.warning(
                    "Profile '%s' extends '%s' which is not loaded yet",
                    profile.id,
                    profile.extends,
                )
        self.register(profile)
        return profile

    def load_dir(self, directory: Path) -> int:
        """Load all .yaml/.yml profile files from a directory. Returns count loaded."""
        if not directory.exists():
            logger.warning("Profiles directory does not exist: %s", directory)
            return 0

        # Two-pass: load base profiles (no 'extends') first
        paths = list(directory.glob("*.yaml")) + list(directory.glob("*.yml"))
        base_first = sorted(paths, key=lambda p: _has_extends(p))

        count = 0
        for path in base_first:
            try:
                self.load_file(path)
                count += 1
            except Exception as e:
                logger.error("Failed to load profile %s: %s", path, e)
        return count

    @classmethod
    def from_dir(cls, directory: Path) -> "ProfileRegistry":
        registry = cls()
        registry.load_dir(directory)
        return registry

    # ── Resolution ────────────────────────────────────────────────────────────

    def resolve(self, profile_id: str) -> Optional[AgentProfile]:
        """Resolve by exact ID."""
        return self._profiles.get(profile_id)

    def resolve_for_card(self, card: KanbanCard) -> Optional[AgentProfile]:
        """Find the best matching profile for a card."""
        # 1. Assignee name exact match
        for member_id in card.assignees:
            if match := self._profiles.get(member_id):
                return match

        # 2. Exact label match
        for label in card.labels:
            if match := self._profiles.get(label):
                return match

        # 3. Prefix label match — find most specific
        best: Optional[AgentProfile] = None
        best_len = 0
        for label in card.labels:
            for pid, profile in self._profiles.items():
                if label.startswith(pid) or pid.startswith(label):
                    if len(pid) > best_len:
                        best = profile
                        best_len = len(pid)
        return best

    # ── Inspection ────────────────────────────────────────────────────────────

    def list(self) -> list[AgentProfile]:
        return list(self._profiles.values())

    def __len__(self) -> int:
        return len(self._profiles)

    def __iter__(self):
        return iter(self._profiles.values())

    def __contains__(self, profile_id: str) -> bool:
        return profile_id in self._profiles


def _has_extends(path: Path) -> int:
    """Return 1 if the YAML file has an 'extends' key, else 0 (base files sort first)."""
    try:
        text = path.read_text(encoding="utf-8")
        return 1 if "extends:" in text else 0
    except OSError:
        return 0
