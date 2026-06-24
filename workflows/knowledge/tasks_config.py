"""
Beat schedule for the knowledge / RAG workflow.

Cost guard: source ingestors can fan out across SaaS systems and embedding
credits. The exported `WORKFLOW_KNOWLEDGE` therefore includes only bounded
scheduled work by default, with live behavior controlled by env vars:

  - knowledge_cross_link_report: weekday morning synthesis over existing data
    unless HARQIS_KNOWLEDGE_ENABLE_REPORT=0
  - ingest_confluence_pages: enabled only when
    HARQIS_KNOWLEDGE_CONFLUENCE_SPACES is set and
    HARQIS_KNOWLEDGE_ENABLE_CONFLUENCE is not false
  - ingest_jira_issues: enabled only when
    HARQIS_KNOWLEDGE_JIRA_PROJECTS is set and
    HARQIS_KNOWLEDGE_ENABLE_JIRA is not false
  - knowledge_answer_morning_brief: enabled only when
    HARQIS_KNOWLEDGE_ENABLE_MORNING_BRIEF is true

The parked `_DISABLED__WORKFLOW_KNOWLEDGE` entries are valid task definitions,
but they are intentionally not exported until each source has an explicit scope
and cost guard. In particular, Confluence with empty `space_keys`, Jira with
empty `project_keys`, and Drive with `folder_id=None` can scan every visible item
for that integration.

Historical blocker: the old Gemini embedding model was retired, and this file
was disabled after repeated ingest failures. The model has since moved to the
shared env-driven embedder; embeddings still need funded/provider-backed runtime
configuration on hosts that execute ingest tasks.
"""

import os

from celery.schedules import crontab
from workflows.queues import WorkflowQueue


_DISABLED__WORKFLOW_KNOWLEDGE = {

    'run-job--ingest_notion_pages': {
        'task': 'workflows.knowledge.tasks.ingest_notion.ingest_notion_pages',
        'schedule': crontab(hour=2, minute=30),  # nightly 02:30 local
        'kwargs': {
            'cfg_id__notion': 'NOTION',
            'max_pages': 200,
            'rebuild': False,
        },
        'options': {
            'queue': WorkflowQueue.HOST,
            'expires': 60 * 60 * 6,  # 6h — skip if a previous run is still pending
        },
        'manifesto': {
            'code_role': 'capture',
            'para_bucket': 'area',
            'express_target': 'vectorstore:knowledge',
            'review_artifact': 'es_log',
            'hfl_signal': True,
        },
    },

    # Staggered nightly so the three ingestors don't fight for the Gemini
    # embed quota. Order: Notion 02:30 → Jira 02:45 → GitHub 03:00 → Drive 03:15.
    'run-job--ingest_jira_issues': {
        'task': 'workflows.knowledge.tasks.ingest_jira.ingest_jira_issues',
        'schedule': crontab(hour=2, minute=45),
        'kwargs': {
            'cfg_id__jira': 'JIRA',
            'project_keys': [],          # set explicitly when first running
            'max_issues': 500,
            'max_comments': 30,
            'jql_extra': '',             # e.g. 'updated >= -30d' for incremental
            'rebuild': False,
        },
        'options': {
            'queue': WorkflowQueue.HOST,
            'expires': 60 * 60 * 6,
        },
        'manifesto': {
            'code_role': 'capture',
            'para_bucket': 'area',
            'express_target': 'vectorstore:knowledge',
            'review_artifact': 'es_log',
            'hfl_signal': False,
        },
    },

    'run-job--ingest_github_repos': {
        'task': 'workflows.knowledge.tasks.ingest_github.ingest_github_repos',
        'schedule': crontab(hour=3, minute=0),
        'kwargs': {
            'repos': [],                 # set explicitly when first running, e.g. ['acme/web']
            'states': 'all',
            'per_repo_limit': 100,
            'max_comments': 20,
            'include_issues': True,
            'include_prs': True,
            'rebuild': False,
        },
        'options': {
            'queue': WorkflowQueue.HOST,
            'expires': 60 * 60 * 6,
        },
        'manifesto': {
            'code_role': 'capture',
            'para_bucket': 'area',
            'express_target': 'vectorstore:knowledge',
            'review_artifact': 'es_log',
            'hfl_signal': False,
        },
    },

    'run-job--ingest_gdrive_docs': {
        'task': 'workflows.knowledge.tasks.ingest_gdrive.ingest_gdrive_docs',
        'schedule': crontab(hour=3, minute=15),
        'kwargs': {
            'folder_id': None,           # None = whole Drive; set to a folder id to scope
            'max_files': 200,
            'modified_after': None,      # e.g. '2026-04-01T00:00:00Z' for incremental
            'rebuild': False,
        },
        'options': {
            'queue': WorkflowQueue.HOST,
            'expires': 60 * 60 * 6,
        },
        'manifesto': {
            'code_role': 'capture',
            'para_bucket': 'area',
            'express_target': 'vectorstore:knowledge',
            'review_artifact': 'es_log',
            'hfl_signal': True,
        },
    },

    # Confluence ingest (Phase 1). Staggered after Drive (03:15). Incremental
    # by page version — only changed/new pages are re-embedded. Set space_keys
    # and fill CONFLUENCE_* in .env/apps.env before enabling.
    'run-job--ingest_confluence_pages': {
        'task': 'workflows.knowledge.tasks.ingest_confluence.ingest_confluence_pages',
        'schedule': crontab(hour=3, minute=30),
        'kwargs': {
            'cfg_id__confluence': 'CONFLUENCE',
            'space_keys': [],          # set explicitly, e.g. ['ENG', 'OPS']
            'cql_extra': '',           # e.g. "lastmodified >= '2026-06-01'"
            'max_pages': 500,
            'rebuild': False,
        },
        'options': {
            'queue': WorkflowQueue.HOST,
            'expires': 60 * 60 * 6,
        },
        'manifesto': {
            'code_role': 'capture',
            'para_bucket': 'area',
            'express_target': 'vectorstore:knowledge',
            'review_artifact': 'es_log',
            'hfl_signal': False,
        },
    },

    # Cross-source radar (Phase 3): working-context + orphan tickets + stale
    # docs, rolled into one ES-logged report. Weekday mornings.
    'run-job--knowledge_cross_link_report': {
        'task': 'workflows.knowledge.tasks.cross_link.cross_link_report',
        'schedule': crontab(hour=7, minute=45, day_of_week='1-5'),
        'kwargs': {
            'since': '-7d',
            'k': 8,
            'min_doc_similarity': 0.55,
            'min_code_similarity': 0.6,
            'limit': 50,
            'summarize': True,
            'model': 'claude-haiku-4-5-20251001',
        },
        'options': {
            'queue': WorkflowQueue.HOST,
            'expires': 60 * 60,
        },
        'manifesto': {
            'code_role': 'distill+express',
            'para_bucket': 'area',
            'express_target': 'es_log',
            'review_artifact': 'es_log',
            'hfl_signal': True,
        },
    },

    # Adhoc/manual answer slot — useful when you want a daily "morning brief"
    # of a fixed question. Defaults to disabled (very-rare crontab).
    'run-job--knowledge_answer_morning_brief': {
        'task': 'workflows.knowledge.tasks.answer.answer',
        'schedule': crontab(hour=8, minute=0, day_of_week='mon'),
        'kwargs': {
            'question': 'What did I write down last week that I haven\'t actioned yet?',
            'k': 8,
            'source': 'notion',
            'cfg_id__anthropic': 'ANTHROPIC',
            'model': 'claude-haiku-4-5-20251001',
            'max_tokens': 1024,
        },
        'options': {
            'queue': WorkflowQueue.HOST,
            'expires': 60 * 60,
        },
        'manifesto': {
            'code_role': 'distill+express',
            'para_bucket': 'area',
            'express_target': 'es_log',
            'review_artifact': 'es_log',
            'hfl_signal': True,
        },
    },

}

def _csv_env(name: str) -> list[str]:
    raw = os.environ.get(name, "").strip()
    return [part.strip() for part in raw.split(",") if part.strip()]


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off"}


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _entry_with_kwargs(name: str, **overrides) -> dict:
    base = _DISABLED__WORKFLOW_KNOWLEDGE[name]
    return {**base, 'kwargs': {**base['kwargs'], **overrides}}


def _enabled_workflow_knowledge() -> dict:
    """Export the live-safe scheduled knowledge surface.

    Broad source ingestors stay opt-in. Confluence and Jira are exported only
    when the host supplies scoped source filters. The report stays on by
    default, but scheduled LLM work remains env-controlled.
    """
    enabled = {}

    if _bool_env("HARQIS_KNOWLEDGE_ENABLE_REPORT", True):
        enabled['run-job--knowledge_cross_link_report'] = _entry_with_kwargs(
            'run-job--knowledge_cross_link_report',
            since=os.environ.get("HARQIS_KNOWLEDGE_REPORT_SINCE", "-7d").strip() or "-7d",
            k=_int_env("HARQIS_KNOWLEDGE_REPORT_K", 8),
            min_doc_similarity=_float_env("HARQIS_KNOWLEDGE_REPORT_MIN_DOC_SIMILARITY", 0.55),
            min_code_similarity=_float_env("HARQIS_KNOWLEDGE_REPORT_MIN_CODE_SIMILARITY", 0.6),
            limit=_int_env("HARQIS_KNOWLEDGE_REPORT_LIMIT", 50),
            summarize=_bool_env("HARQIS_KNOWLEDGE_REPORT_SUMMARIZE", False),
            model=os.environ.get(
                "HARQIS_KNOWLEDGE_REPORT_MODEL",
                'claude-haiku-4-5-20251001',
            ).strip() or 'claude-haiku-4-5-20251001',
        )

    confluence_spaces = _csv_env("HARQIS_KNOWLEDGE_CONFLUENCE_SPACES")
    if confluence_spaces and _bool_env("HARQIS_KNOWLEDGE_ENABLE_CONFLUENCE", True):
        kwargs = {
            'space_keys': confluence_spaces,
            'max_pages': _int_env("HARQIS_KNOWLEDGE_CONFLUENCE_MAX_PAGES", 200),
        }
        cql_extra = os.environ.get("HARQIS_KNOWLEDGE_CONFLUENCE_CQL_EXTRA", "").strip()
        if cql_extra:
            kwargs['cql_extra'] = cql_extra
        enabled['run-job--ingest_confluence_pages'] = _entry_with_kwargs(
            'run-job--ingest_confluence_pages',
            **kwargs,
        )

    jira_projects = _csv_env("HARQIS_KNOWLEDGE_JIRA_PROJECTS")
    if jira_projects and _bool_env("HARQIS_KNOWLEDGE_ENABLE_JIRA", True):
        enabled['run-job--ingest_jira_issues'] = _entry_with_kwargs(
            'run-job--ingest_jira_issues',
            project_keys=jira_projects,
            max_issues=_int_env("HARQIS_KNOWLEDGE_JIRA_MAX_ISSUES", 100),
            max_comments=_int_env("HARQIS_KNOWLEDGE_JIRA_MAX_COMMENTS", 20),
            jql_extra=os.environ.get("HARQIS_KNOWLEDGE_JIRA_JQL_EXTRA", "").strip(),
        )

    if _bool_env("HARQIS_KNOWLEDGE_ENABLE_MORNING_BRIEF", False):
        enabled['run-job--knowledge_answer_morning_brief'] = _entry_with_kwargs(
            'run-job--knowledge_answer_morning_brief',
            question=os.environ.get(
                "HARQIS_KNOWLEDGE_MORNING_BRIEF_QUESTION",
                "What did I write down last week that I haven't actioned yet?",
            ).strip() or "What did I write down last week that I haven't actioned yet?",
            k=_int_env("HARQIS_KNOWLEDGE_MORNING_BRIEF_K", 8),
            source=os.environ.get("HARQIS_KNOWLEDGE_MORNING_BRIEF_SOURCE", "confluence").strip() or "confluence",
            cfg_id__anthropic=os.environ.get("HARQIS_KNOWLEDGE_MORNING_BRIEF_ANTHROPIC_CFG", "ANTHROPIC").strip() or "ANTHROPIC",
            model=os.environ.get(
                "HARQIS_KNOWLEDGE_MORNING_BRIEF_MODEL",
                'claude-haiku-4-5-20251001',
            ).strip() or 'claude-haiku-4-5-20251001',
            max_tokens=_int_env("HARQIS_KNOWLEDGE_MORNING_BRIEF_MAX_TOKENS", 1024),
        )

    return enabled


WORKFLOW_KNOWLEDGE = _enabled_workflow_knowledge()
