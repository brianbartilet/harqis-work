"""
Beat schedule for the knowledge / RAG workflow.

Two tasks:
  - ingest_notion_pages: nightly Notion → vector store sync
  - answer:              on-demand RAG answer (kept here so beat-driven
                         scheduled questions remain possible — most callers
                         invoke it directly via .delay() or the MCP tool)

Cost guard: `answer` pins Haiku 4.5 via `kwargs.model`. Per the project
convention (see memory: anthropic_model_override), do not change the
Anthropic default — pass the model from here.

────────────────────────────────────────────────────────────────────────
DISABLED 2026-05-14 — beat schedule is empty (`WORKFLOW_KNOWLEDGE = {}`)
────────────────────────────────────────────────────────────────────────
ES rollups showed ingest_notion_pages / ingest_jira_issues /
ingest_gdrive_docs failing 5 nights in a row with `RuntimeError`.
ingest_github_repos looked "passing" only because tasks_config had
`repos: []` so it short-circuited before touching Gemini.

Two stacked blockers — BOTH must be fixed before re-enabling:

  1. Stale Gemini embedding model. `apps/gemini/references/web/api/embed.py`
     hard-codes `DEFAULT_EMBED_MODEL = 'models/text-embedding-004'`, which
     Google retired. The v1beta endpoint returns 404 NOT_FOUND. The
     `_embed_batch()` helper (copy-pasted across all 4 ingest tasks) then
     sees no `embeddings` key in the response and raises RuntimeError.
     Fix: bump default to `'models/gemini-embedding-001'` (current GA;
     `gemini-embedding-2` is also available).

  2. Gemini project credits depleted. Even with the correct model name,
     a live probe returns 429 RESOURCE_EXHAUSTED ("prepayment credits are
     depleted"). Top up at https://ai.studio/projects, OR switch the
     embedder (sentence-transformers locally, OpenAI, Cohere). Gemini's
     free tier no longer covers embeddings.

To re-enable: rename `_DISABLED__WORKFLOW_KNOWLEDGE` → `WORKFLOW_KNOWLEDGE`
below. Beat picks it up on the next scheduler restart. See
workflows/knowledge/README.md "Status" for the full write-up.

Note: `run-job--knowledge_answer_morning_brief` is included in the
disable because `retriever.embed_query` uses the same Gemini embedder
for question vectors — top up + model bump are required for it too.
"""

from celery.schedules import crontab
from workflows.queues import WorkflowQueue


# Empty exported schedule — see DISABLED header above.
WORKFLOW_KNOWLEDGE: dict = {}


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
            'queue': WorkflowQueue.AGENT,
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
            'queue': WorkflowQueue.AGENT,
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
            'queue': WorkflowQueue.AGENT,
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
            'queue': WorkflowQueue.AGENT,
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
            'queue': WorkflowQueue.AGENT,
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
            'queue': WorkflowQueue.ADHOC,
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
            'queue': WorkflowQueue.ADHOC,
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
