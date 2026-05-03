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
"""

from celery.schedules import crontab
from workflows.queues import WorkflowQueue


WORKFLOW_KNOWLEDGE = {

    'run-job--ingest_notion_pages': {
        'task': 'workflows.knowledge.tasks.ingest_notion.ingest_notion_pages',
        'schedule': crontab(hour=2, minute=30),  # nightly 02:30 local
        'kwargs': {
            'cfg_id__notion': 'NOTION',
            'max_pages': 200,
            'rebuild': False,
        },
        'options': {
            'queue': WorkflowQueue.DEFAULT,
            'expires': 60 * 60 * 6,  # 6h — skip if a previous run is still pending
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
            'queue': WorkflowQueue.DEFAULT,
            'expires': 60 * 60 * 6,
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
            'queue': WorkflowQueue.DEFAULT,
            'expires': 60 * 60 * 6,
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
            'queue': WorkflowQueue.DEFAULT,
            'expires': 60 * 60 * 6,
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
    },

}
