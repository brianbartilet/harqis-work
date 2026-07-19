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
        description="The operating principles behind HARQIS Work.",
        detail="The manifesto and a map of the platform's automation, integration, and knowledge modules.",
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
        label="Applications",
        route="/applications",
        description="App integrations connected to HARQIS Work.",
        detail="Browse integration documentation and run controlled pytest checks using this host's active configuration.",
    ),
    ModuleDefinition(
        key="hfl_corpus",
        label="HFL Corpus",
        route="/hfl-corpus",
        description="The searchable Homework-for-Life knowledge corpus.",
        detail="Browse captured moments, time capsules, logs, tags, and the source artifacts referenced by each entry.",
    ),
)


def module_by_key(key: str) -> ModuleDefinition | None:
    return next((module for module in MODULES if module.key == key), None)
