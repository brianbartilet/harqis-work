import os

from celery.schedules import crontab
from workflows.queues import WorkflowQueue

WORKFLOW_SOCIAL = {

    'run-job--generate_monthly_linkedin_post': {
        'task': 'workflows.social.tasks.social_linkedin_monthly.generate_monthly_linkedin_post',
        'schedule': crontab(day_of_month=1, hour=0, minute=0),
        'kwargs': {
            'cfg_id__linkedin': 'LINKEDIN',
            'cfg_id__gmail': 'GOOGLE_GMAIL_SEND',
            'cfg_id__anthropic': 'ANTHROPIC',
            'recipient_email': os.environ.get('HARQIS_OWNER_EMAIL', 'owner@example.com'),
            'skip_draft': False,
            'skip_email': False,
        },
        'options': {
            'queue': WorkflowQueue.PEON,
            'expires': 60 * 60 * 24 * 7,
        },
        'manifesto': {
            'code_role': 'distill+express',
            'para_bucket': 'area',
            'express_target': 'api:linkedin+message:gmail+file:markdown',
            'review_artifact': 'es_log+file',
            'hfl_signal': True,
        },
    },

}
