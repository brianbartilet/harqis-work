---
name: max-plan
description: >
  # Max Plan — Deep Reasoning Planning for HARQIS-work
user-invocable: true
allowed-tools: Bash Read Glob Grep Edit Write
---

# Max Plan — Deep Reasoning Planning for HARQIS-work

You are the **Max Plan** skill. Your job: delegate a complex planning task to the configured agent CLI running in "plan" permission mode with maximum effort, capturing the result in a markdown plan file.

## When to use this

Use `/max-plan` when you need **deep reasoning on approach** before implementation:

- **Architecture redesign**: "I want to split the worker queue into N sub-queues based on task priority. Plan this."
- **Complex refactor**: "Refactor the HFL ingest pipeline to support streaming. Plan it."
- **Integration uncertainty**: "I want to connect the Elasticsearch cluster to a Redis cache layer for live queries. What's the plan?"
- **Risk mitigation**: "We're changing the deploy hostname matching. Scope the changes and risk areas."
- **Multi-phase work**: "Plan a migration from SQLAlchemy 1.x to 2.x across all apps."

Do NOT use this for:
- Simple clarification (use `/clarify-feature`)
- Immediate code scaffolding (use `/create-new-*`)
- One-line fixes or small patches

---

## Step 0 — Parse the user's intent

The user invokes via:
```
/max-plan <description of the task to plan>
```

Example:
```
/max-plan Refactor the MCP server registration to cache tool schemas on first init instead of on every reload
```

If no description follows, ask: "What task should I plan? (e.g., refactor X, implement Y, integrate Z)"

---

## Step 1 - Invoke the agent CLI in plan mode

Run the configured agent CLI with these flags:

```bash
claude -p "$TASK_DESCRIPTION" \
  --effort max \
  --permission-mode plan \
  --output-format json \
  --max-turns 15 \
  --workdir /Users/harqis-one/repos/harqis-work
```

Where `$TASK_DESCRIPTION` is the user's planning request.

Key flags:
- **`--effort max`** — deepest reasoning; suitable for complex planning
- **`--permission-mode plan`** — The agent can only _propose_ changes, not execute them (auto-prevents accidental writes)
- **`--output-format json`** — structured result with session_id, num_turns, cost tracking
- **`--max-turns 15`** — allow enough turns for iterative planning without runaway
- **`--workdir`** — keep context to HARQIS-work

---

## Step 2 — Capture the plan

After the agent finishes:

1. **Extract the plan text** from the JSON result (field: `result` or `structured_output`)
2. **Write it to .hermes/plans/** with a timestamped filename:
   ```
   .hermes/plans/YYYY-MM-DD_HHMMSS-<slug>.md
   ```
   Where `<slug>` is a short lowercase hyphenated name derived from the task (e.g., `max-plan-mcp-cache-refactor`)

3. **Prepend metadata** to the plan:
   ```markdown
   # Plan: [Task Title]
   
   **Created:** YYYY-MM-DD HH:MM:SS
   **Effort Level:** max
   **Duration:** X turns
   **Cost:** $Y.YY
   
   ---
   
   [Rest of the agent plan output]
   ```

---

## Step 3 — Report back

After saving, reply to the user with:

```
✅ Plan saved: `.hermes/plans/YYYY-MM-DD_HHMMSS-<slug>.md`

**Summary:** [1-2 sentence summary of the plan]

**Key decisions:** [Bullet list of 3-5 core recommendations from the plan]

**Next steps:** Review the plan file. When approved, implementation can proceed with `/commit`, `/create-new-*`, or direct edits guided by the plan.
```

Include the file path so the user can find it easily.

---

## Example Flow

**User says:**
```
/max-plan Rearchitect the TCG-MP auction endpoint to support real-time bid notifications without polling
```

**You run:**
```bash
claude -p "Rearchitect the TCG-MP auction endpoint to support real-time bid notifications without polling. Assume WebSocket or Server-Sent Events (SSE). Map out the changes needed to auth, the database schema, the API, and the frontend. Consider failure modes and backwards compatibility." \
  --effort max \
  --permission-mode plan \
  --output-format json \
  --max-turns 15 \
  --workdir /Users/harqis-one/repos/harqis-work
```

**Agent output:**
A detailed plan covering:
- Architecture (WebSocket vs SSE trade-off, chosen SSE)
- Files affected (apps/tcg_mp/endpoints.py, workflows/auctions/, frontend/panels/)
- Database changes (add notification_queue table, indexes)
- Risk areas (connection drops, message ordering, scaling)
- Rollback strategy

**You save it to:**
```
.hermes/plans/2026-05-21_153022-tcg-mp-live-bidding.md
```

**You reply:**
```
✅ Plan saved: `.hermes/plans/2026-05-21_153022-tcg-mp-live-bidding.md`

**Summary:** Migrate TCG-MP auctions from polling to Server-Sent Events (SSE) for real-time bid updates. Chose SSE over WebSocket for simpler auth and deployment.

**Key decisions:**
- Use SSE instead of WebSocket (simpler, reuses HTTP/auth)
- Add a new `AuctionNotification` Celery task for broadcasting
- Queue notifications in Redis to handle spikes
- Implement graceful degradation (fall back to polling if SSE fails)

**Next steps:** Review the plan and confirm approach. Once approved, start with app changes in `apps/tcg_mp/endpoints.py`.
```

---

## Pitfalls

1. **Forgetting to set `--workdir`** → The agent loses repo context. Always include it.
2. **Not saving the result** → Plan gets lost. Always write to `.hermes/plans/`.
3. **Using `--permission-mode` without `--effort max`** → Wastes the benefit of deep reasoning. Always pair with `--effort max`.
4. **Max-turns too low** → Complex plans get cut short. Use 10-15 for good coverage.
5. **Not summarizing for the user** → They don't know what the plan says. Always provide a brief summary and key decisions.

---

## Success Criteria

- ✅ Plan is saved to `.hermes/plans/` with a clear filename
- ✅ Metadata (date, effort, cost, turns) is included
- ✅ Plan covers architecture, files affected, risks, and next steps
- ✅ User can read it and understand the proposed approach
- ✅ Implementation can proceed directly from the plan, or user can request refinements
