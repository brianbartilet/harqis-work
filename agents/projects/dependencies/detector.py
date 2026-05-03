"""
DependencyDetector — analyzes a KanbanCard to identify blocking and soft dependencies.

Blocking dependencies are hard stops that prevent the agent from starting:
  - Missing required environment variables / API keys declared in the card's
    'required_secrets' custom field
  - Service references in the card text whose keys are not present in env

Soft dependencies are things the agent can resolve autonomously:
  - New Celery workflow to scaffold (agent copies from workflows/.template/)
  - New MCP app integration to build (agent copies from apps/.template/)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum

from agents.projects.trello.models import KanbanCard


class DependencyType(str, Enum):
    SECRET = "secret"
    CONFIG = "config"
    NEW_WORKFLOW = "workflow"
    NEW_APP = "app"


@dataclass
class Dependency:
    type: DependencyType
    name: str
    blocking: bool
    description: str
    hint: str = ""


@dataclass
class DetectionResult:
    blocking: list[Dependency] = field(default_factory=list)
    soft: list[Dependency] = field(default_factory=list)

    @property
    def has_blocking(self) -> bool:
        return bool(self.blocking)

    def blocker_summary(self) -> str:
        if not self.blocking:
            return ""
        lines = ["## Blocking Dependencies\n"]
        for dep in self.blocking:
            lines.append(f"- **{dep.type.value}** `{dep.name}`: {dep.description}")
            if dep.hint:
                lines.append(f"  - Hint: {dep.hint}")
        return "\n".join(lines)


class DependencyDetector:
    """
    Heuristic dependency detector for Kanban cards.

    Detection priority:
    1. Explicit `required_secrets` custom field on the card (blocking).
    2. Known service name patterns in card text → check corresponding env var (blocking).
    3. Soft dependency patterns: 'new workflow', 'new app', etc. (non-blocking).
    """

    # (regex pattern, env var name) — checked against card title + description.
    # Env var names MUST match keys in .env/apps.env exactly, otherwise the dependency
    # detector will flag missing secrets that are actually configured (just under a
    # different name).
    # KEEP IN SYNC WITH /new-service-app: every new app integration that has an env var
    # in apps_config.yaml must be represented here so the kanban orchestrator can detect
    # missing creds before starting an agent. Naming MUST match keys in .env/apps.env exactly.
    _SERVICE_SECRETS: list[tuple[str, str]] = [
        # Finance
        (r"\bALPHA\s*VANTAGE\b|\bALPHAVANTAGE\b",  "ALPHA_VANTAGE_API_KEY"),
        (r"\bOANDA\b",                            "OANDA_BEARER_TOKEN"),
        (r"\bYNAB\b",                             "YNAB_ACCESS_TOKEN"),
        # Productivity / project management
        (r"\bJIRA\b",                             "JIRA_API_TOKEN"),
        (r"\bTRELLO\b",                           "TRELLO_API_TOKEN"),
        (r"\bAIRTABLE\b",                         "AIRTABLE_API_TOKEN"),
        (r"\bNOTION\b",                           "NOTION_API_TOKEN"),
        # Communication
        (r"\bDISCORD\b",                          "DISCORD_BOT_TOKEN"),
        (r"\bTELEGRAM\b",                         "TELEGRAM_BOT_TOKEN"),
        (r"\bREDDIT\b",                           "REDDIT_CLIENT_SECRET"),
        (r"\bLINKEDIN\b",                         "LINKEDIN_ACCESS_TOKEN"),
        # Google / Gmail / Calendar use file-based OAuth (credentials.json + storage-*.json);
        # GOOGLE_APPS_API_KEY is the shared API key, used as a coarse readiness signal.
        (r"\bGMAIL\b|\bGOOGLE\s*CALENDAR\b|\bGOOGLE\s*DRIVE\b",
                                                  "GOOGLE_APPS_API_KEY"),
        # GitHub / source control
        (r"\bGITHUB\b|gh\s+pr\b|gh\s+repo\b",     "GITHUB_API_TOKEN"),
        # AI / LLM
        (r"\bANTHROPIC\b|\bCLAUDE\b",             "ANTHROPIC_API_KEY"),
        (r"\bOPENAI\b|\bGPT-?\d*\b",              "OPENAI_API_KEY"),
        (r"\bGROK\b|\bxAI\b",                     "GROK_API_KEY"),
        (r"\bPERPLEXITY\b|\bSONAR\b",             "PERPLEXITY_API_KEY"),
        (r"\bELEVEN\s*LABS\b|\bELEVENLABS\b",     "ELEVEN_LABS_API_KEY"),
        # Magic: The Gathering / TCG
        (r"\bECHO\s*MTG\b|\bECHOMTG\b",           "ECHO_MTG_BEARER_TOKEN"),
        (r"\bTCG\s*MP\b|\bTCGPLAYER\b",           "TCG_MP_PASSWORD"),
        # Cloud / infrastructure
        (r"\bORGO\b",                             "ORGO_API_KEY"),
        (r"\bOWN\s*TRACKS\b|\bOWNTRACKS\b",       "OWN_TRACKS_PASSWORD"),
        (r"\bN8N\b",                              "N8N_API_KEY"),
        # Web scraping / market research
        (r"\bAPIFY\b",                            "APIFY_API_KEY"),
        # Trading / brokerage
        (r"\bMOO\b|\bFUTU\b",                     "MOO_PWD_MD5"),
    ]

    _WORKFLOW_PATTERNS = [
        r"new\s+workflow",
        r"scaffold.*workflow",
        r"create.*workflow",
        r"add.*workflow",
        r"new\s+celery",
    ]

    _APP_PATTERNS = [
        r"new\s+app",
        r"new\s+integration",
        r"new\s+service",
        r"scaffold.*app",
        r"create.*app",
        r"add.*mcp",
        r"new\s+mcp",
    ]

    def detect(self, card: KanbanCard) -> DetectionResult:
        result = DetectionResult()
        text = f"{card.title} {card.description}"

        result.blocking.extend(self._check_explicit_secrets(card))
        result.blocking.extend(self._scan_service_references(text))
        result.soft.extend(self._scan_workflow_patterns(text))
        result.soft.extend(self._scan_app_patterns(text))

        result.blocking = _dedupe(result.blocking)
        result.soft = _dedupe(result.soft)
        return result

    def _check_explicit_secrets(self, card: KanbanCard) -> list[Dependency]:
        deps: list[Dependency] = []
        required = card.custom_fields.get("required_secrets", "")
        if not required:
            return deps
        for var_name in required.split(","):
            var_name = var_name.strip()
            if not var_name:
                continue
            if not os.environ.get(var_name):
                deps.append(Dependency(
                    type=DependencyType.SECRET,
                    name=var_name,
                    blocking=True,
                    description=f"Required environment variable '{var_name}' is not set",
                    hint=f"Add {var_name} to .env/agents.env and restart the orchestrator",
                ))
        return deps

    def _scan_service_references(self, text: str) -> list[Dependency]:
        deps: list[Dependency] = []
        for pattern, env_var in self._SERVICE_SECRETS:
            if re.search(pattern, text, re.IGNORECASE) and not os.environ.get(env_var):
                deps.append(Dependency(
                    type=DependencyType.SECRET,
                    name=env_var,
                    blocking=True,
                    description=f"Card references a service that needs '{env_var}'",
                    hint=f"Add {env_var} to .env/agents.env",
                ))
        return deps

    def _scan_workflow_patterns(self, text: str) -> list[Dependency]:
        for pat in self._WORKFLOW_PATTERNS:
            if re.search(pat, text, re.IGNORECASE):
                return [Dependency(
                    type=DependencyType.NEW_WORKFLOW,
                    name="new_workflow",
                    blocking=False,
                    description="Task requires scaffolding a new Celery workflow",
                    hint="Copy from workflows/.template/ and fill in the implementation",
                )]
        return []

    def _scan_app_patterns(self, text: str) -> list[Dependency]:
        for pat in self._APP_PATTERNS:
            if re.search(pat, text, re.IGNORECASE):
                return [Dependency(
                    type=DependencyType.NEW_APP,
                    name="new_app",
                    blocking=False,
                    description="Task requires scaffolding a new MCP app integration",
                    hint="Copy from apps/.template/ and implement config.py + mcp.py",
                )]
        return []


def _dedupe(deps: list[Dependency]) -> list[Dependency]:
    seen: set[str] = set()
    result = []
    for d in deps:
        if d.name not in seen:
            seen.add(d.name)
            result.append(d)
    return result
