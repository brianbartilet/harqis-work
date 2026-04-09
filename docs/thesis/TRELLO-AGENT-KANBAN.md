# Trello as Agent Kanban

Use Trello as a shared task interface between humans and AI agents. You create cards, agents pick them up, do the work, and post results back — all visible on the same board.

---

## How it works

1. You create a card in **Backlog** with a task title, a label naming the agent type, and a description containing the prompt or context.
2. An agent polls the board, claims cards matching its label, and moves them to **In Progress**.
3. The agent completes the task, posts the result as a **comment**, and moves the card to **Review** (or **Done** if no approval is needed).
4. You review, close, or reassign from there.

---

## Board columns

| Column | Purpose |
|---|---|
| **Backlog** | New tasks waiting to be picked up |
| **In Progress** | Card claimed and actively being worked |
| **Review** | Result posted, awaiting human approval |
| **Done** | Completed and archived |

---

## Card anatomy

Each card is a structured prompt:

| Field | Purpose |
|---|---|
| **Title** | The task instruction |
| **Label** | Routes to the correct agent (e.g. `agent:web`, `agent:write`, `agent:data`) |
| **Description** | Full prompt, context, attachments |
| **Comment** | Agent posts its result here, then moves the card |

---

## Agent types (example labels)

| Label | Responsibility |
|---|---|
| `agent:web` | Browse, scrape, search the web |
| `agent:write` | Draft, edit, summarise text |
| `agent:data` | Run queries, analyse datasets |
| `agent:read` | Parse documents, OCR, extract structured data |

---

## Implementation overview

Each agent is a small worker process that:

1. Calls the **Trello REST API** to find cards in Backlog with its label
2. Moves the card to **In Progress** (claims it)
3. Reads the card description as a prompt
4. Calls the **Claude API** (or other model) with that prompt
5. Posts the response as a **comment** on the card
6. Moves the card to **Review** or **Done**

### Minimal agent loop (pseudocode)

```python
while True:
    cards = trello.get_cards(list="Backlog", label="agent:web")
    for card in cards:
        trello.move_card(card.id, list="In Progress")
        result = claude.complete(prompt=card.description)
        trello.add_comment(card.id, result)
        trello.move_card(card.id, list="Review")
    sleep(30)  # poll interval
```

### Trello API — key endpoints

```
GET  /1/lists/{listId}/cards          # fetch cards in a column
PUT  /1/cards/{cardId}                # move card (idList param)
POST /1/cards/{cardId}/actions/comments  # post result as comment
GET  /1/cards/{cardId}                # read card details
```

### Claude API call (from card description)

```javascript
const response = await fetch("https://api.anthropic.com/v1/messages", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    model: "claude-sonnet-4-20250514",
    max_tokens: 1000,
    messages: [{ role: "user", content: card.description }]
  })
});
const result = response.content[0].text;
```

---

## Trigger strategy

| Approach | When to use |
|---|---|
| **Polling** (cron every N seconds) | Simpler to start, no public endpoint needed |
| **Webhooks** (Trello pushes on card creation) | Faster, event-driven, requires public URL |

For local or internal use, polling is the easiest starting point. For production, set up a Trello webhook pointing to your agent's `/webhook` endpoint.

---

## Tips

- **Use card labels strictly as routing keys** — one label per card, one agent type per label. This prevents two agents from claiming the same card.
- **Add a `claimed-by` comment** immediately when an agent picks up a card, before doing any work, to prevent race conditions if multiple instances are running.
- **Store outputs as attachments** for large results (files, CSVs, images) rather than dumping everything into a comment.
- **Use due dates** on cards to set task deadlines that agents can respect.
- **Human-in-the-loop** is built in — any card sitting in Review waits for you before moving to Done.
