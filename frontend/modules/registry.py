"""Declarative navigation registry for frontend modules."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModuleDefinition:
    key: str
    label: str
    route: str
    description: str
    detail: str


MODULES: tuple[ModuleDefinition, ...] = (
    ModuleDefinition(key="agents", label="Second Brain", route="/agents",
                     description="Agent fleet, capabilities and sessions.",
                     detail="Configure Space-aware agents, trace their work and open the HARQIS butler."),
    ModuleDefinition(
        key="home",
        label="Home",
        route="/home",
        description="A map of the HARQIS Work platform.",
        detail="Browse the platform's automation, integration, knowledge, and operating-principle modules.",
    ),
    ModuleDefinition(
        key="hfl_corpus",
        label="Capture",
        route="/hfl-corpus",
        description="Preserve moments and source evidence.",
        detail="Review and capture activity from all your sources in the Activity Corpus.",
    ),
    ModuleDefinition(
        key="sharing",
        label="Share Activity",
        route="/sharing",
        description="Share selected activity as frozen snapshots or configurable live views.",
        detail="Review entries, actions, ideas, boards, goals, and graphs with read-only guest access.",
    ),
    ModuleDefinition(
        key="manifesto",
        label="Manifesto",
        route="/manifesto",
        description="The operating principles behind HARQIS Work.",
        detail="CODE, PARA, the 7 Habits, and the principles that guide how HARQIS captures, distills, and expresses work.",
    ),
    ModuleDefinition(
        key="second_brain",
        label="Second Brain Dashboard",
        route="/second-brain",
        description="A Space-aware HUD of what matters now.",
        detail="Arrange live source widgets, follow shared Spaces, and trace the advisory context feed to its source and freshness.",
    ),
    ModuleDefinition(
        key="files", label="Organize", route="/files",
        description="Find files across storage locations and share versioned packages.",
        detail="Catalog documents and media, connect categories and entities, and publish expiring file packages.",
    ),
    ModuleDefinition(
        key="workflows",
        label="Workflows",
        route="/workflows",
        description="Celery tasks, schedules, queues, and execution history.",
        detail="The orchestration layer that turns application integrations into repeatable scheduled and on-demand work.",
    ),
    ModuleDefinition(
        key="applications",
        label="Integrations",
        route="/applications",
        description="App integrations connected to HARQIS Work.",
        detail="Browse integration documentation and run controlled pytest checks using this host's active configuration.",
    ),
    ModuleDefinition(
        key="git_forks",
        label="Git Forks",
        route="/git-forks",
        description="Trace drift across every managed harqis-work fork.",
        detail="Compare commits and capabilities, inspect branches and PRs, then run guarded synchronization, regression, and deployment operations.",
    ),
)

PRIMARY_MODULES: tuple[ModuleDefinition, ...] = tuple(
    module for module in MODULES if module.key not in {"home", "manifesto"}
)


def module_by_key(key: str) -> ModuleDefinition | None:
    return next((module for module in MODULES if module.key == key), None)
