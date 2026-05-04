Build and deploy an n8n workflow from a drawio diagram, XML/BPMN file, or text description directly into the local n8n instance running at `localhost:5678`.

## Arguments

`$ARGUMENTS` format:

```
<diagram_path_or_description> [--name <workflow_name>]
```

| Token | Required | Description |
|---|---|---|
| `diagram_path_or_description` | Yes | Path to `.drawio`, `.xml`, `.bpmn` file, or free-text description of the workflow |
| `--name <name>` | No | Override the workflow name (default: inferred from diagram or description) |

---

## Environment — read before doing anything

**n8n instance:** `http://localhost:5678` (Docker container name: `n8n`)

**User ID for import:** `bcb93758-fbfe-44ac-a52d-87e61f86bc47`

**Output directory:** `workflows/n8n/` (relative to repo root)

**Import method:** n8n CLI inside Docker — no API key needed:
```bash
docker cp /path/to/workflow.json n8n:/tmp/workflow.json
docker exec n8n n8n import:workflow --input=/tmp/workflow.json --userId=bcb93758-fbfe-44ac-a52d-87e61f86bc47
```

### Installed credentials (wire these to nodes that need them)

Query the live instance for current credentials before building:
```bash
docker exec n8n sh -c "sqlite3 /home/node/.n8n/database.sqlite 'SELECT id, name, type FROM credentials_entity;'" 2>/dev/null
```

Known credentials at last check (always re-query, these may change):
| Credential ID | Name | Type (credentialType key) |
|---|---|---|
| PqKljtqzkvgM5AnU | ElevenLabs account | elevenLabsApi |
| T3oVqCm47LhGh73b | OpenAi account | openAiApi |
| IgPQ84bG5jBrff2b | Google Calendar account | googleCalendarOAuth2Api |
| 3lJLfj2EEsTuayJ0 | GitHub account | githubApi |
| j6UJKHhM16IunMhz | flower | httpBasicAuth |

### Installed custom nodes
- `@elevenlabs/n8n-nodes-elevenlabs.elevenLabs` — ElevenLabs TTS/voice

---

## Step 1 — Parse the input

### If a file path was given:
Use the **Read** tool to load the file. Then parse its structure:

**Drawio XML (`.drawio` or `.xml` containing `mxGraphModel`):**
- `mxCell` with `vertex="1"` and `id` not in `{0,1}` = workflow **nodes**; use `value` attribute as the label
- `mxCell` with `edge="1"` = **connections**; use `source` and `target` attributes (cell IDs) to map edges
- `mxCell` with `style` containing `rhombus` or `diamond` = decision/branch node
- `mxCell` with `style` containing `ellipse` = start/end node
- Position hint: use `mxGeometry x,y` to preserve approximate layout

**BPMN XML:**
- `<startEvent>` → manual or webhook trigger
- `<task>` / `<serviceTask>` → action node; use `name` attribute
- `<sequenceFlow sourceRef targetRef>` → connections
- `<exclusiveGateway>` / `<inclusiveGateway>` → IF or Switch node

**Other XML / JSON:** Extract node labels and directed edges by whatever structure is present.

### If a text description was given:
Extract:
1. **Trigger**: how does the workflow start? (schedule, webhook, manual, event)
2. **Steps**: sequence of operations in order
3. **Branches**: any conditional logic
4. **Services/apps**: which external services are involved
5. **Output**: what happens at the end (respond, send message, store, log)

Build a mental node-edge list before writing JSON.

---

## Step 2 — Map labels to n8n node types

Use this table. Match the label text (case-insensitive, partial match) to the node type. When multiple entries match, prefer the most specific one.

### Triggers (must be the first node(s) in the flow)

| Label keywords | n8n type | typeVersion | Notes |
|---|---|---|---|
| webhook, http trigger, api trigger, inbound | `n8n-nodes-base.webhook` | 2.1 | Add `webhookId` (generate UUID) |
| schedule, cron, interval, timer, every, daily, hourly | `n8n-nodes-base.scheduleTrigger` | 1.2 | |
| manual, start, begin | `n8n-nodes-base.manualTrigger` | 1.0 | |
| rabbitmq trigger, mq trigger, queue trigger, message queue | `n8n-nodes-base.rabbitmqTrigger` | 1.0 | |
| chat trigger, chat message, chat | `@n8n/n8n-nodes-langchain.chatTrigger` | 1.1 | |
| email trigger, imap, incoming mail | `n8n-nodes-base.emailReadImap` | 2.0 | |

### Logic / Flow control

| Label keywords | n8n type | typeVersion |
|---|---|---|
| if, condition, check, branch, decision, yes/no | `n8n-nodes-base.if` | 2.2 |
| switch, route, multi-branch, classify text | `n8n-nodes-base.switch` | 3.2 |
| merge, combine, join, aggregate results | `n8n-nodes-base.merge` | 3.0 |
| set, assign, map data, transform, format | `n8n-nodes-base.set` | 3.4 |
| code, script, function, execute code, python, javascript | `n8n-nodes-base.code` | 2 |
| wait, delay, pause, sleep | `n8n-nodes-base.wait` | 1.1 |
| respond, response, reply to webhook, send response | `n8n-nodes-base.respondToWebhook` | 1.2 |
| no-op, pass-through, noop, end | `n8n-nodes-base.noOp` | 1.0 |

### HTTP / API

| Label keywords | n8n type | typeVersion | Credential |
|---|---|---|---|
| http request, api call, rest, fetch url, request | `n8n-nodes-base.httpRequest` | 4.2 | None (or httpBasicAuth for Flower) |
| flower, celery task, trigger task | `n8n-nodes-base.httpRequest` | 4.2 | httpBasicAuth ("flower") |

### Google

| Label keywords | n8n type | typeVersion | Credential |
|---|---|---|---|
| google calendar, calendar event, schedule event | `n8n-nodes-base.googleCalendar` | 1.3 | googleCalendarOAuth2Api |
| gmail, google mail, send gmail | `n8n-nodes-base.gmail` | 2.1 | googleOAuth2Api |
| google sheets, spreadsheet, sheets | `n8n-nodes-base.googleSheets` | 4.5 | googleSheetsOAuth2Api |
| google drive, gdrive | `n8n-nodes-base.googleDrive` | 3.0 | googleDriveOAuth2Api |

### Communication

| Label keywords | n8n type | typeVersion | Credential |
|---|---|---|---|
| telegram, telegram message | `n8n-nodes-base.telegram` | 1.2 | telegramApi |
| slack, slack message | `n8n-nodes-base.slack` | 2.3 | slackOAuth2Api |
| email, smtp, send email, mail | `n8n-nodes-base.emailSend` | 2.1 | smtp |
| discord | `n8n-nodes-base.discord` | 2.0 | discordWebhookApi |

### VCS / Dev

| Label keywords | n8n type | typeVersion | Credential |
|---|---|---|---|
| github, git commit, pull request | `n8n-nodes-base.github` | 1.1 | githubApi |

### Queue / Cache / DB

| Label keywords | n8n type | typeVersion |
|---|---|---|
| rabbitmq publish, publish to queue, mq | `n8n-nodes-base.rabbitmq` | 1.0 |
| redis, cache | `n8n-nodes-base.redis` | 1.1 |
| postgres, postgresql, database, sql | `n8n-nodes-base.postgres` | 2.5 |

### AI / LangChain

| Label keywords | n8n type | typeVersion | Credential | Connection type |
|---|---|---|---|---|
| ai agent, llm agent, agent | `@n8n/n8n-nodes-langchain.agent` | 2.2 | — | Receives `ai_languageModel`, `ai_tool` sub-connections |
| openai, gpt, chatgpt, language model, llm | `@n8n/n8n-nodes-langchain.lmChatOpenAi` | 2.0 | openAiApi | Connected via `ai_languageModel` |
| text classifier, intent, classify | `@n8n/n8n-nodes-langchain.textClassifier` | 1.1 | — | Receives `ai_languageModel` |
| output parser, structured output, json output | `@n8n/n8n-nodes-langchain.outputParserStructured` | 1.2 | — | Connected via `ai_outputParser` |
| http tool, tool, api tool | `@n8n/n8n-nodes-langchain.toolHttpRequest` | 1.1 | — | Connected via `ai_tool` to agent |
| memory, window memory, buffer memory | `@n8n/n8n-nodes-langchain.memoryBufferWindow` | 1.3 | — | Connected via `ai_memory` |

### ElevenLabs (custom node)

| Label keywords | n8n type | typeVersion | Credential |
|---|---|---|---|
| elevenlabs, text to speech, tts, voice synthesis, speech | `@elevenlabs/n8n-nodes-elevenlabs.elevenLabs` | 1 | elevenLabsApi |

### Fallback
If no keyword matches, use `n8n-nodes-base.code` with a TODO comment explaining what needs implementation.

---

## Step 3 — Build the workflow JSON

Generate IDs using UUID v4 format (random hex: `xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx`).

**Position layout rules:**
- Linear flow: x = 160 × step_index, y = 0 (or use y from diagram geometry if available)
- Sub-nodes (AI models, tools wired to an agent): place directly below the parent node (same x, y + 200)
- Branching: place branch nodes at y = ±200 from the branch point
- Scale up if nodes overlap (multiply all x/y by 1.5)

**Credential wiring:**
Wire credentials only when the credential type exists in the instance. Use the `credentials` field:
```json
"credentials": {
  "<credentialType>": {
    "id": "<credential_id>",
    "name": "<credential_name>"
  }
}
```

If a needed credential does NOT exist in the instance, leave `credentials` omitted and add it to the **manual actions** summary.

**LangChain sub-connections:**
AI model and tool nodes connect to their parent agent via special connection types:
```json
"connections": {
  "OpenAI Model": {
    "ai_languageModel": [[{"node": "AI Agent", "type": "ai_languageModel", "index": 0}]]
  },
  "HTTP Tool": {
    "ai_tool": [[{"node": "AI Agent", "type": "ai_tool", "index": 0}]]
  }
}
```

**Webhook node:** always generate a `webhookId` UUID and set `parameters.path` to the same UUID.

**ScheduleTrigger:** set a reasonable default (e.g. `{"rule": {"interval": [{"field": "hours", "hoursInterval": 1}]}}`) and note it in the manual actions summary.

**Workflow JSON template:**

The import format is a **JSON array** containing one workflow object. n8n uses short 16-char alphanumeric IDs (not UUIDs) for the workflow `id` field. Generate one with:
```bash
python3 -c "import random, string; print(''.join(random.choices(string.ascii_letters + string.digits, k=16)))"
```

```json
[{
  "id": "<16-char-alphanumeric-id>",
  "name": "<workflow_name>",
  "nodes": [ ... ],
  "connections": { ... },
  "settings": {
    "executionOrder": "v1"
  },
  "pinData": {},
  "active": false
}]
```

Node `id` fields remain UUID v4 format (`xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx`).

Set `active: false` — the user will activate it after testing.

---

## Step 4 — Write and deploy

### 4a. Save the JSON file
Write the complete workflow JSON to:
```
workflows/n8n/<snake_case_workflow_name>.json
```

### 4b. Verify n8n is running
```bash
curl -s http://localhost:5678/healthz
```
If it returns `{"status":"ok"}`, proceed. If not, stop and tell the user n8n is down.

### 4c. Import via Docker CLI
```bash
# Copy JSON into the container
docker cp workflows/n8n/<filename>.json n8n:/tmp/<filename>.json

# Import (do NOT pass --userId — it causes a credential ownership bug in this n8n version)
docker exec n8n n8n import:workflow --input=/tmp/<filename>.json
```

Capture and show the output. A successful import prints: `Successfully imported 1 workflow.`

If the import fails with a schema error, check that the JSON is valid and the node types are spelled correctly (use `docker exec n8n n8n list:workflow` to confirm the instance accepted it).

### 4d. Confirm it appears in n8n
```bash
docker exec n8n n8n list:workflow 2>/dev/null | grep -i "<workflow_name>"
```

---

## Step 5 — Print the summary

At the end, always print this formatted summary (fill in the actual values):

```
── n8n Workflow Built ──────────────────────────────────────────────
Workflow:   <name>
File:       workflows/n8n/<filename>.json
Status:     Imported as draft (inactive) ✓
n8n URL:    http://localhost:5678  →  open Workflows to find it

── Nodes ───────────────────────────────────────────────────────────
  <node_name>  (<n8n_type>)
  ...

── Credentials wired ───────────────────────────────────────────────
  ✓ <credential_name>  →  <node_name>
  ...

── Manual actions required ─────────────────────────────────────────
  [ ] <action> — e.g. "Add Telegram credential: Settings > Credentials > New > Telegram"
  [ ] <action> — e.g. "Set schedule interval on 'Schedule Trigger' node (currently: every 1h)"
  [ ] <action> — e.g. "Set RabbitMQ queue name in 'Publish to Queue' node"
  [ ] Activate the workflow when ready: toggle the Active switch in n8n UI
  ...

── Dependencies ────────────────────────────────────────────────────
  <any external service, credential, or config needed before activation>
─────────────────────────────────────────────────────────────────────
```

---

## Notes

- **API key is expired** — always use the Docker CLI import method above, not the REST API.
- **Never activate** the workflow programmatically — leave it inactive for the user to test.
- **Credentials not in the instance**: note them in the summary under Manual actions; do not attempt to create credentials via the API.
- **Unknown node labels**: default to `n8n-nodes-base.code` (Code node) with a comment; list them in the summary as TODOs.
- **RabbitMQ nodes**: the harqis-work stack has RabbitMQ on the Docker network at `rabbitmq:5672`. Inside n8n, use `host.docker.internal` or `rabbitmq` as the host depending on network setup.
- **Flower / Celery tasks**: the Flower HTTP API is at `http://host.docker.internal:5555`. Use `n8n-nodes-base.httpRequest` with the `flower` credential (httpBasicAuth) to trigger Celery tasks.
- **HARQIS workflows.mapping**: mounted in n8n at `/data/workflows.mapping`; this file maps task names to webhook-callable endpoints. Reference it in Code nodes if the workflow needs to trigger Celery tasks dynamically.
