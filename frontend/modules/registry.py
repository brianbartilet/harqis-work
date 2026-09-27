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
    ModuleDefinition(
        key="home",
        label="Home",
        route="/home",
        description="A map of the HARQIS Work platform.",
        detail="Browse the platform's automation, integration, knowledge, and operating-principle modules.",
    ),
    ModuleDefinition(
        key="hfl_corpus",
        label="Distill",
        route="/distill",
        description="Turn lived activity into useful knowledge and deliberate action.",
        detail="Review the Activity Corpus, connect ideas in the Graph, and move work forward in Kanban.",
    ),
    ModuleDefinition(
        key="sharing",
        label="Share",
        route="/sharing",
        description="Recipes stay live while every generated snapshot freezes a fresh view.",
        detail="Shape Activity Corpus sources, tags, and filters into temporary portals with expiring guest access.",
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
        label="Second Brain",
        route="/second-brain",
        description="A context-aware feed of what matters now.",
        detail="Blend automatic signals with temporary manual modes, then trace every advisory item to its source and freshness.",
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
        label="Apps",
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
