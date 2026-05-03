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
