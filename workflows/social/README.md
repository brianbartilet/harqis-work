# Social Workflows

Automated social media reporting and content generation.

---

### `generate_monthly_linkedin_post`

**Goal:** Generate a professional, emoji-enriched LinkedIn monthly update post summarising the previous month's git commits for the HARQIS-WORK platform, save it as markdown, create a LinkedIn draft, and send a Gmail notification.

**Apps chained:**
1. `git log` (subprocess) → collect commits for the target month
2. `logs/linkedin/` (filesystem) → load previous monthly post for style context
3. `apps/linkedin` → optionally load last posted URN for additional context
4. `apps/antropic` → Claude generates the post content
5. `logs/linkedin/` (filesystem) → save `MONTHLY-WORK-UPDATE-MM-YYYY.md`
6. `apps/linkedin` → create LinkedIn draft via `ApiServiceLinkedInPosts.create_draft()`
7. `apps/google_apps` → send Gmail notification via `ApiServiceGoogleGmail.send_email()`

**Schedule:** `crontab(day_of_month=1, hour=8, minute=0)` — 1st of each month, 08:00 Asia/Singapore

**Queue:** `WorkflowQueue.DEFAULT`

**Required config keys:** `LINKEDIN`, `GOOGLE_GMAIL_SEND`, `ANTHROPIC`

**Required env vars:** `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`, `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_PERSON_ID`, `LINKEDIN_DEFAULT_POST_URN`, `ANTHROPIC_API_KEY`

**Configurable kwargs:**

| kwarg | Default | Description |
|---|---|---|
| `month` | previous month | Target month number (1–12) |
| `year` | year of previous month | Target year |
| `cfg_id__linkedin` | `LINKEDIN` | Config key for LinkedIn |
| `cfg_id__gmail` | `GOOGLE_GMAIL_SEND` | Config key for Gmail send |
| `cfg_id__anthropic` | `ANTHROPIC` | Config key for Anthropic |
| `recipient_email` | `brian.bartilet@gmail.com` | Notification recipient |
| `skip_draft` | `False` | Skip creating the LinkedIn draft |
| `skip_email` | `False` | Skip the Gmail notification |

**Data flow:**
```
git log (month) → [Claude post generation] → logs/linkedin/MONTHLY-WORK-UPDATE-MM-YYYY.md
                                           → LinkedIn draft (lifecycleState: DRAFT)
                                           → Gmail notification
```

**AI prompt:** `workflows/social/prompts/monthly_linkedin_post.md`

**Output file naming:** `logs/linkedin/MONTHLY-WORK-UPDATE-{MM}-{YYYY}.md`

**Post title format:** `HARQIS-WORK: {MONTH_NAME} {YYYY} Update`

---

## Setup

### 1. `GOOGLE_GMAIL_SEND` OAuth credential

Add the following section to `apps_config.yaml` (requires a separate OAuth token with `gmail.send` scope):

```yaml
GOOGLE_GMAIL_SEND:
  app_id: 'gmail'
  client: 'rest'
  parameters:
    base_url: 'https://gmail.googleapis.com/'
    response_encoding: 'utf-8'
    verify: True
    timeout: 60
    stream: True
  app_data:
    scopes:
      - "https://www.googleapis.com/auth/gmail.send"
    credentials: "credentials.json"
    storage: "storage-gmail-send.json"
  return_data_only: True
```

Then authorize the new OAuth token:

```bash
python3 -c "
from apps.google_apps.references.web.client import GoogleApiClient
from core.config.loader import ConfigLoaderService
import os
cfg = ConfigLoaderService(file_name=os.environ['ENV_APP_CONFIG_FILE']).config['GOOGLE_GMAIL_SEND']
client = GoogleApiClient(
    scopes_list=cfg['app_data']['scopes'],
    credentials=cfg['app_data']['credentials'],
    storage=cfg['app_data']['storage'],
)
client.authorize()
print('Authorization complete — storage-gmail-send.json written.')
"
```

### 2. Activate the schedule

Uncomment in `workflows/config.py`:
```python
from workflows.social.tasks_config import WORKFLOW_SOCIAL
CONFIG_DICTIONARY = CONFIG_DICTIONARY | WORKFLOW_SOCIAL
```

Uncomment the task entry in `workflows/social/tasks_config.py`.

Then restart Celery Beat.

---

## Running manually

```bash
# Previous month (default)
python3 -c "
from workflows.social.tasks.social_linkedin_monthly import generate_monthly_linkedin_post
result = generate_monthly_linkedin_post(skip_draft=True, skip_email=True)
print(result)
"

# Specific month (e.g. March 2026), full pipeline
python3 -c "
from workflows.social.tasks.social_linkedin_monthly import generate_monthly_linkedin_post
result = generate_monthly_linkedin_post(month=3, year=2026)
print(result)
"
```

---

## Tests

```bash
# Unit tests (mocked — no credentials needed)
pytest workflows/social/tests/test_social_linkedin_monthly.py -v -m smoke

# Live integration tests (requires full credentials)
pytest workflows/social/tests/test_social_linkedin_monthly.py -v -m integration
```
