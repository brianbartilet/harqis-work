# Running Assistant Cockpit — conversation + proactive updates

> A *why* document for turning Hermes/HARQIS from a notification bot into a
> persistent assistant surface: Brian can converse directly by voice/text while
> the system pushes timely, actionable updates through the same experience.

---

## 1. Problem

Telegram already works as a notification avenue, and Hermes can already receive
messages through the gateway. That is useful, but it still feels like a bot that
occasionally sends alerts.

The desired shape is a **running assistant**:

- Brian can talk to it directly, by voice or text.
- Hermes can send proactive updates, status, and recommendations.
- The same surface handles follow-ups, approvals, snoozes, and commands.
- Missed updates are recoverable with questions like "what did I miss?".

The hard part is not speech-to-text alone. It is combining two streams safely:

1. **Live conversation** — user-initiated questions, commands, captures, and
   approvals.
2. **Update stream** — cron jobs, HARQIS radar, watchdogs, agent runs, HFL
   signals, and other proactive events.

If these are not organized behind a durable event model, the assistant becomes a
noisy chat feed instead of a usable second brain.

## 2. Express output

Build a mobile-first assistant interface where Brian can say:

- "what's active?"
- "what did I miss?"
- "diagnose that"
- "snooze this until tonight"
- "capture this as HFL"
- "approve the safe retry"

…and receive concise, actionable updates from Hermes/HARQIS in the same place.

The first production surface should be Telegram because it is already wired and
mobile-native. The durable architecture should not be Telegram-specific: it
should center on an assistant event bus plus a conversation router, with
Telegram, web/PWA, macOS, iPhone Shortcuts, and future hardware as interchangeable
surfaces.

## 3. What already exists and should be reused

The implementation should build on current Hermes/HARQIS primitives instead of
creating a parallel assistant stack.

| Existing piece | Role in this design |
| --- | --- |
| Hermes Gateway | Human-facing messaging adapters: Telegram now, Discord already configured, others later. |
| Hermes STT | Voice messages from messaging platforms can be transcribed. Current local provider is `faster-whisper`. |
| Hermes TTS | Optional spoken replies using configured TTS provider. Current default is Edge TTS. |
| Hermes cron | Durable scheduled updates and no-agent watchdog/report jobs. |
| HARQIS MCP | First-choice inspection surface for HARQIS state, HFL, apps, and workflows. |
| HARQIS scheduled jobs | Existing sources of proactive status/radar/update signals. |
| HFL / second-brain corpus | Destination for memory-worthy voice captures and distilled events. |
| Hermes API Server | Machine-facing OpenAI-compatible surface for future cockpit UI, Shortcuts, n8n, or local apps. |

The system should distinguish:

- **Telegram/Discord/Slack** — human-facing conversation/update channels.
- **API Server/Webhooks** — machine-facing integration surfaces for apps and
  custom UIs.

## 4. Conceptual architecture

```text
           ┌─────────────────────────────┐
           │        Hermes Brain         │
           │ memory / tools / HARQIS MCP │
           └──────────────┬──────────────┘
                          │
        ┌─────────────────┴─────────────────┐
        │                                   │
 Live conversation                    Update stream
 voice / text / approvals             cron / watchdogs / agents
        │                                   │
        └─────────────────┬─────────────────┘
                          │
              Assistant event bus + router
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
   Telegram DM       Web/PWA cockpit   macOS/iPhone shortcut
```

The key design choice: **Telegram is the first body, not the brain.** The durable
core is the event bus and routing policy. User surfaces can change later.

## 5. Assistant event model

Every proactive update should be captured as a structured event before it is
sent anywhere.

Example shape:

```json
{
  "id": "evt_20260713_001",
  "source": "harqis_radar",
  "type": "workflow_warning",
  "priority": "normal",
  "title": "HFL ingest produced zero new entries",
  "summary": "The scheduled run completed but did not write HFL entries.",
  "suggested_action": "Run the HFL ingest diagnostic ladder.",
  "actions": ["diagnose", "retry", "snooze", "ignore"],
  "status": "unread",
  "created_at": "2026-07-13T09:00:00+08:00"
}
```

Minimum fields:

| Field | Purpose |
| --- | --- |
| `id` | Stable handle for follow-up commands like "snooze this". |
| `source` | Producer: cron job, agent run, HARQIS radar, HFL ingest, watchdog, etc. |
| `type` | Semantic category for grouping and routing. |
| `priority` | Routing policy: digest-only, immediate, urgent, approval-required. |
| `title` | Compact mobile heading. |
| `summary` | One-screen explanation. |
| `suggested_action` | The smallest next move. |
| `actions` | Allowed follow-ups. |
| `status` | unread, read, snoozed, done, ignored, approval_pending. |
| `created_at` | Timeline and digest ordering. |

A small SQLite store is enough for the first version:

```text
~/.hermes/assistant_events.db
```

This store enables:

- "what did I miss?"
- "show pending approvals"
- "summarize today"
- deduplication of repeated alerts
- snoozing and read/done state
- later web/PWA rendering

## 6. Conversation model

Every inbound interaction should normalize into a command envelope before it is
passed to Hermes.

Example shape:

```json
{
  "source": "telegram",
  "mode": "voice",
  "intent": "command",
  "text": "diagnose that HFL warning",
  "session_key": "brian-running-assistant",
  "reply_to_event_id": "evt_20260713_001"
}
```

Common intents:

| Intent | Meaning |
| --- | --- |
| `ask` | Answer a question. |
| `command` | Do work or inspect state. |
| `capture` | Preserve a thought, note, transcript, or HFL signal. |
| `approve` | Approve a pending action. |
| `snooze` | Delay an event. |
| `ignore` | Mark as intentionally ignored. |
| `status` | Summarize current active state. |

The assistant should support natural language, but the router should still keep a
small explicit action vocabulary so updates are actionable and safe.

## 7. Priority and interruption policy

The running assistant should be useful without becoming noisy.

| Priority | Delivery behavior |
| --- | --- |
| `FYI` | Store for digest; do not interrupt. |
| `normal` | Send compact Telegram/cockpit update. |
| `important` | Send immediately, text only by default. |
| `urgent` | Send immediately; optionally speak if voice alerts are enabled. |
| `approval_required` | Send immediately and hold action until explicit approval. |

Rules:

- Most updates should be readable text, not spoken alerts.
- Spoken alerts should be reserved for urgent or approval-required events.
- Repeated failures should deduplicate or collapse into one evolving event.
- Every proactive update should include a suggested first move.
- Long logs, raw private dumps, credentials, and raw transcripts should never be
  pushed directly; summarize safely and cite sanitized handles.

## 8. Action and approval protocol

A proactive update should invite bounded follow-up actions.

Example mobile message:

```text
HARQIS ingest warning

The Plaud/HFL ingest ran but produced zero new HFL entries.
Likely issue: transcript fallback failed.

Suggested first move:
Run ingest diagnostic ladder.

Actions:
1. diagnose
2. retry
3. snooze 4h
4. ignore
```

Brian can reply by voice or text:

```text
diagnose it
```

Hermes can inspect safely. If the next step mutates state, restarts services,
deletes files, sends external messages, or performs other risky side effects, the
assistant must ask for explicit approval:

```text
This will restart the HARQIS gateway. Approve?
```

Approval rules:

- Voice can request anything; risky actions still need explicit approval.
- "Approve" must resolve to a specific pending action, not a generic capability.
- Group chats should not get unrestricted tool execution by default.
- Approval prompts should name the action, scope, target, and likely effect.

## 9. Voice layer

There are three useful levels.

### Level 1 — Telegram voice MVP

```text
Telegram voice note → Hermes STT → command text → Hermes → Telegram reply
```

This already fits the current stack and should be the first validation target.

### Level 2 — Voice-to-voice on demand

```text
Telegram voice note → Hermes STT → Hermes → text reply + optional TTS audio
```

Use TTS selectively:

- `/voice tts` for voice replies when desired.
- urgent or approval-required updates only, if voice alerts are enabled.
- avoid speaking every routine digest.

### Level 3 — Dedicated push-to-talk surface

```text
web/PWA or iPhone Shortcut
→ hold-to-talk / dictate
→ Hermes API Server or webhook
→ assistant event bus / Hermes
→ Telegram/cockpit/TTS response
```

This is the best long-term user experience, but it should come after the event
model works through Telegram.

## 10. Phased implementation plan

### Phase 1 — Telegram Assistant Mode

Goal: prove the two-way running assistant loop without building a custom app.

Deliverables:

- Standard proactive update format.
- Telegram voice commands through existing Hermes Gateway STT.
- Optional TTS replies for direct conversation.
- Short commands:
  - "what's active?"
  - "what did I miss?"
  - "show pending approvals"
  - "snooze this"
  - "mark done"
- Conservative approval behavior for risky tool actions.

### Phase 2 — Assistant Event Store

Goal: make updates durable, queryable, and stateful.

Deliverables:

- SQLite-backed `assistant_events` table.
- Small helper for producers to append events.
- Router that sends events to Telegram based on priority.
- Read/done/snoozed/ignored state.
- Deduplication key for repeated warnings.
- Daily digest command backed by the event store.

### Phase 3 — HARQIS producers

Goal: route existing HARQIS signals into the assistant bus.

Candidate producers:

- HARQIS radar / improvement scout.
- HFL ingest health.
- Plaud/voice recording pipeline health.
- Test farm failures.
- Celery/workflow health warnings.
- Agent run completion or blockage.
- Scheduled digest summaries.

Each producer should emit a compact event with evidence and a suggested first
move, not a raw log dump.

### Phase 4 — Web/PWA Cockpit

Goal: provide a dedicated interface without replacing Telegram.

Suggested sections:

```text
Now
- current focus
- pending approvals
- active jobs
- suggested first move

Inbox
- unread / snoozed / done assistant events

Talk
- push-to-talk
- transcript
- TTS reply toggle

Commands
- quick buttons: status, radar, summarize, capture, approve
```

The web/PWA should call Hermes through the API Server or a narrow webhook layer,
not by shelling out directly.

### Phase 5 — Shortcuts and local voice

Goal: make the assistant feel ambient.

Surfaces:

- iPhone Shortcut: dictate → POST to Hermes → response in Telegram/cockpit.
- macOS push-to-talk: hotkey → record/transcribe → Hermes.
- Optional hardware capture: USB-C mic or recorder for longer voice notes and HFL
  ingestion.

## 11. CODE + PARA framing

| CODE stage | Design responsibility |
| --- | --- |
| Capture | Voice/text inputs, cron outputs, HARQIS job results, agent statuses, watchdog findings. |
| Organize | Normalize into conversation envelopes and assistant events; assign priority/status/source. |
| Distill | Summarize updates into mobile-first messages with suggested first moves. |
| Express | Deliver through Telegram/cockpit/TTS and route approved actions back into Hermes tools. |

PARA bucket: `Resources` while this remains architecture/design reference;
promote specific implementation tasks into `Projects` when Phase 1/2 build work
starts.

## 12. Open questions

- Should Telegram remain the canonical assistant thread, or should a PWA become
  canonical once the event store exists?
- Which updates deserve voice alerts versus text-only delivery?
- Should approvals expire after a timeout?
- Should event state live under `~/.hermes`, HARQIS repo storage, or a HARQIS app
  database?
- Should the assistant event bus become a generic HARQIS workflow, a Hermes
  plugin, or a small bridge script first?
- How much command interpretation should be rule-based before falling back to an
  LLM?

## 13. Recommended first build

Start with **Assistant Event Store + Telegram Assistant Mode**.

This gives Brian:

- direct voice/text conversation
- proactive updates
- missed-update recovery
- action/snooze/done loops
- approval prompts
- no custom app dependency yet

Then, once the interaction model feels right, add the web/PWA cockpit and
Shortcuts integration as additional surfaces.
