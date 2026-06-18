# MANIFESTO-MODEL-GUIDE.md — Dynamic Model Selection for Manifesto-Aligned Work

> How to select the right LLM model for different tasks in HARQIS-work.
> This guide operationalizes manifesto principles by matching task complexity to model capability.
> Updated: 2026-05-22

---

## Why Dynamic Model Selection Matters

The MANIFESTO.md defines **what** gets built (CODE+PARA, PAER, 7 Habits, Habit 5, Habit 2).
This guide defines **which model** can execute those principles effectively.

Different tasks have different cognitive demands:
- **Quick clarification** (read one file, answer one question) = low context, low reasoning → use the fastest, cheapest model.
- **Multi-file refactor** (Habit 5: read existing code, Habit 2: define Express output, plan architecture) = high context, multi-hop reasoning → use a larger, more capable model.
- **Strategic architecture review** (holding 5+ competing hypotheses, tracing implications across subsystems, settling conflicts between principles) = very high context + sustained reasoning → use the most capable model available.

**Principle:** Always use the smallest model that can do the job well. Start small, escalate only when you hit token walls or reasoning ceiling.

---

## Model Tiers & Capabilities

### Tier 1: Fast, Lightweight (Haiku, Mini, etc.)
**Models:** Claude Haiku 4.5, GPT 4o Mini, Llama 3.1 8B  
**Context window:** 100–128K tokens  
**Reasoning depth:** Single-hop, shallow multi-hop  
**Cost:** ~$0.80–2/M input, ~$4–10/M output  
**Latency:** <1 second per turn

**Strengths:**
- Fast for interactive work, tight feedback loops.
- Great at simple CODE+PARA framing ("Is this Capture or Express?").
- Good at Habit 2 enforcement ("Can you name the output?").
- Cost-efficient for high-volume, low-stakes decisions.

**Weaknesses:**
- Hits context wall on large codebases (>50 files with full content).
- Weak at pattern detection across files (misses ~30–40% of duplicates).
- PAER Analyze phase is shallow; jumps to Execute.
- Poor synthesis of multi-source signals (HFL + repo + agent prompts together).
- Can't hold multiple competing hypotheses in Analyze phase.

**Good for:**
- Quick feedback, interactive clarification, simple troubleshooting.
- Single-file edits, small scripts, reflex corrections.
- Answering "What's in this file?" or "How does X work?"
- Checking syntax, formatting, or basic logic.

**Not good for:**
- Habit 5 on large repos (reading existing code first).
- Full PAER cycles on complex changes.
- Proactive scanning and pattern synthesis.
- Multi-file refactors or architectural decisions.

---

### Tier 2: Balanced (Sonnet 4/4.5, GPT 4o, Claude 3.5 Sonnet)
**Models:** Claude Sonnet 4, GPT 4o (latest), Llama 3.1 70B  
**Context window:** 200K tokens  
**Reasoning depth:** Multi-hop, multi-hypothesis, synthesis  
**Cost:** $3–10/M input, $15–50/M output  
**Latency:** 2–4 seconds per turn

**Strengths:**
- Holds entire large codebases in context (HARQIS-work fits entirely).
- Multi-hop reasoning: can explore Analyze phase properly (3+ hypotheses, trade-offs, risks).
- Pattern detection: catches cross-file duplicates, workflow gaps, underused integrations.
- Synthesis quality: combines HFL entries + repo state + agent prompts into coherent recommendations.
- Habit 5 execution: reads deeply, catches subtle dependencies.
- Proper PAER: doesn't skip Analyze phase; externalizes artifacts.

**Weaknesses:**
- Slower than Tier 1. Interactive work feels sluggish.
- Overkill for simple tasks (you'll notice the latency).
- Still not ideal for very long sustained reasoning chains (>5K token analysis).

**Good for:**
- Full PAER cycles on multi-file work.
- Habit 5 execution: "read all the existing code, then suggest."
- Proactive scanning: weekly improvement PRs, pattern synthesis.
- Feature planning: design before implement.
- Code review synthesis: large diffs with architectural implications.
- Crossing concerns: "How do agents/projects, apps_config, and workflows interact?"

**Not good for:**
- Quick interactive fixes (too slow).
- One-off questions (overkill).
- Situations where you need sub-second latency.

---

### Tier 3: Deep Reasoning (Opus, GPT 5.5 if reasoning, Claude 4 if available)
**Models:** Claude Opus (if available), GPT 5.5 with reasoning, o3-mini, o1 (older reasoning models)  
**Context window:** 200K+ tokens  
**Reasoning depth:** Sustained, multi-level hypothesis exploration, formal reasoning  
**Cost:** $15–50/M input, $60–200+/M output  
**Latency:** 5–30 seconds per turn (or longer for reasoning models)

**Strengths:**
- Sustained reasoning over 10K+ token analysis traces.
- Exceptional Analyze phase: holds 5+ competing hypotheses, explores deeply, articulates confidence.
- Best at catching subtle code smells, architectural debt, manifesto drift.
- Strategic synthesis: when resolving conflicts between principles, this is the model.
- Can reason formally about tradeoffs, risk, and long-term impact.

**Weaknesses:**
- Very high cost. Each run can be $10–30+ depending on reasoning depth.
- Very high latency. 5–30 seconds or more. Kills interactivity.
- Overkill for 95% of routine work.
- Reasoning models may refuse vague requests; need well-formed problems.

**Good for:**
- Quarterly/annual manifesto audits: "Does our codebase still align with our principles?"
- Strategic architecture decisions: "Should we refactor the agents/projects orchestrator?"
- High-stakes trade-offs: "Optimize for speed vs. observability vs. cost — which wins and why?"
- Merging conflicting principles: "Habit 5 says read first, but we're time-constrained. How do we balance?"
- Deep postmortems: "Why did this deployment fail? What architectural assumptions broke?"
- Multi-month roadmap planning: long-term implications across 10+ initiatives.

**Not good for:**
- Routine tasks.
- Interactive debugging.
- Anything where you need quick feedback.

---

## Decision Tree: Which Model to Use

```
START: I've been asked to do work.

1. Is this a QUICK ANSWER? (≤30 seconds to respond, single file, no planning)
   YES → Tier 1 (Haiku). Cost-efficient, fast feedback.
   NO → Go to 2.

2. Is this INTERACTIVE WORK? (tight loop, user waiting for each response)
   YES → Tier 1 (Haiku). Latency matters.
   NO → Go to 3.

3. Does this require reading EXISTING CODE FIRST? (Habit 5)
   YES → Go to 4.
   NO → Go to 5.

4. Is the scope SINGLE FILE or SMALL (≤5 files)?
   YES → Tier 1 (Haiku, maybe Tier 2 if uncertain).
   NO → Does it touch multiple subsystems (apps/, workflows/, agents/)?
        YES → Tier 2 (Sonnet). Need full repo cognition.
        NO → Go to 5.

5. Does this require PAER CYCLE with FULL ANALYZE? (multi-hypothesis, trade-offs)
   YES → Tier 2 (Sonnet) or Tier 3 (Opus) if very high stakes.
   NO → Go to 6.

6. Is this PATTERN SYNTHESIS or PROACTIVE SCANNING?
   (e.g., "find all unused integrations," "suggest improvements," "cross-file dedup")
   YES → Tier 2 (Sonnet). Need broad code cognition + synthesis quality.
   NO → Go to 7.

7. Is this a STRATEGIC DECISION or MANIFESTO AUDIT?
   (e.g., "Should we refactor the core?" "Does this align with principles?" "How do we balance X vs Y?")
   YES → Tier 3 (Opus) if available and high stakes. Otherwise Tier 2.
   NO → Go to 8.

8. If still uncertain, DEFAULT TO:
   - Tier 1 (Haiku) for routine tasks.
   - Tier 2 (Sonnet) for anything complex or multi-step.
   - Ask explicitly: "I'm escalating to Sonnet/Opus because [reason]."
```

---

## Model Profiles by Provider

### Anthropic (Claude family)

| Model | Tier | Context | Latency | Cost | Notes |
|-------|------|---------|---------|------|-------|
| Haiku 4.5 | 1 | 100K | <1s | $0.80/$4 | Current default. Fast, good enough for simple tasks. |
| Sonnet 4.5 | 2 | 200K | 2-3s | $3/$15 | **Recommended for HARQIS-work.** Best balance of context, reasoning, cost. |
| Sonnet 4 | 2 | 200K | 2-3s | $3/$15 | Older Sonnet. Similar to 4.5; slight reasoning gap. Use 4.5 if available. |
| Opus | 3 | 200K | 5-10s | $15/$60 | Best reasoning. Very expensive. Reserve for strategic audits. |

### OpenAI (GPT family)

| Model | Tier | Context | Latency | Cost | Notes |
|-------|------|---------|---------|------|-------|
| GPT 4o Mini | 1 | 128K | <1s | $0.15/$0.60 | **Even cheaper than Haiku.** Trade-off: slightly weaker reasoning. |
| GPT 4o | 2 | 128K | 1-2s | $5/$15 | Similar to Sonnet 4. Slightly better at some reasoning tasks. Try both. |
| GPT 4.5 (if avail) | 2 | 128K | 2s | ~$5/$15 | Expected soon. Monitor for release. |
| GPT 5.5 (TBD) | 2–3 | TBD | TBD | TBD | **When released:** likely Tier 2 or 2.5. Update this guide. |
| o1 / o3-mini | 3 | 128K | 5-30s | $20/$80 | Deep reasoning. Very slow, expensive. Use sparingly for strategic work. |

### Meta / Open Source (Llama, Mistral, etc.)

| Model | Tier | Context | Latency | Cost | Notes |
|-------|------|---------|---------|------|-------|
| Llama 3.1 8B | 1 | 128K | <1s (local) | Free | Good local option if you run inference on hardware. |
| Llama 3.1 70B | 2 | 128K | 1-3s (local) | Free | Solid local Sonnet alternative. Requires beefy hardware. |
| Mistral Large | 2 | 32K | 1-2s | $8/$24 | Lower context but fast. Not ideal for HARQIS-work. |

---

## Implementation: Dynamic Model Selection

### In Claude Code / Interactive Sessions

When I (Claude Code) am asked to do work, I follow this protocol:

1. **Categorize the task** using the decision tree above.
2. **State the model selection** explicitly: "I'm using Sonnet for this because [reason]."
3. **Switch models** (if possible) before proceeding. If model switching isn't available, note the limitation.
4. **If I hit a ceiling** (context wall, reasoning depth), escalate: "I'm out of useful token budget on Haiku. Switching to Sonnet for full analysis."

Example:
```
You: "Refactor the agents/projects orchestrator to separate concerns."

Me: "That's a multi-subsystem change (Habit 5: read existing code first, Habit 2: 
define Express output, PAER Analyze phase). I'm using Sonnet for this because:
- Need to read agents/projects/*.py (~8 files, 1000+ LOC)
- Need to cross-reference apps_config.yaml, workflows/kanban*, agents/prompts/*
- Need PAER Analyze to explore 3+ architectural options before committing to one

[Proceeding with Sonnet...]"
```

### In Automation (weekly_claude_pr.py, cron jobs, etc.)

Each automated context has a **model specification**:

```yaml
# weekly_claude_pr.py: Friday 6 PM orchestration
model: sonnet  # Tier 2 because: proactive scanning, pattern synthesis, PAER Analyze
budget: 2      # Conservative token budget
max_turns: 15  # Allow multi-phase reasoning

# daily_improvement_scout.py: Continuous scanning
model: haiku   # Tier 1 because: quick checks, patterns pre-identified
budget: 1      # Minimal budget
max_turns: 5

# Quarterly manifesto audit (manual, on-demand)
model: opus    # Tier 3 because: strategic, multi-hypothesis, high stakes
budget: unlimited
max_turns: 20  # Allow deep reasoning
```

### Config Location

Update your deployment/cron configs:

```python
# scripts/agents/repo-quality/weekly_claude_pr.py
CLAUDE_MODEL = "sonnet-4.5"  # Explicitly name the version
CLAUDE_BUDGET = 2  # Input + output token budget in 100s
CLAUDE_TEMPERATURE = 0.7  # Exploration for Analyze phase
```

```python
# scripts/agents/repo-quality/daily_improvement_scout.py
CLAUDE_MODEL = "haiku"  # Quick scans
CLAUDE_BUDGET = 1
CLAUDE_TEMPERATURE = 0.5  # Less exploration needed
```

---

## Handling Model Unavailability

If your preferred model isn't available (API outage, subscription lapsed, etc.), fall back in order:

1. **Tier 1 fallback:** Haiku → GPT 4o Mini (if available) → Llama 3.1 8B (local)
2. **Tier 2 fallback:** Sonnet 4.5 → GPT 4o → Sonnet 4 → Llama 3.1 70B
3. **Tier 3 fallback:** Opus → o1 (if available and cost permits) → manual review (preferred over degraded automation)

**Protocol:**
- If the task demands Tier 2+ and only Tier 1 is available, **pause and notify.** Don't degrade automation quality silently.
- For interactive work, downgrade gracefully ("Haiku is available; Sonnet would be better. Proceeding with Haiku, but analysis will be shallower").

---

## Case Studies

### Case 1: "Quick bug fix in one file"
**Task:** User reports a typo in `workflows/hud/README.md`.  
**Decision:** Read file, fix, verify. No Habit 5 (pre-reading), no Analyze phase, no PAER.  
**Model:** Tier 1 (Haiku). 30 seconds, $0.001.

---

### Case 2: "Add a new workflow that integrates two existing apps"
**Task:** User wants to combine Google Calendar + Slack into a "daily standup reminder" workflow.  
**Decision:**
- Habit 5: Read `apps_config.yaml`, existing workflows, agents/projects routing.
- Habit 2: Express output = "Post standup reminder to Slack #engineering at 9 AM SGT every Mon–Fri."
- PAER: Plan (scope), Analyze (choose between 3 routing options), Execute (code), Review (test + memory).
- Subsystem scope: touches apps/, workflows/, agents/projects.
**Model:** Tier 2 (Sonnet). 5–10 minutes, $0.10–0.30.

---

### Case 3: "Refactor the core Kanban agent"
**Task:** Separate concern of card claiming from agent invocation. Understand why it's coupled first.  
**Decision:**
- Habit 5: Read agents/projects/*.py (8 files), agents/prompts/*.md (5 files), workflows/kanban/*.py (4 files). Trace execution flow end-to-end.
- Habit 2: Express output = "Kanban agent can be mocked/tested independently of orchestrator; new ability to dry-run agents locally."
- PAER: Full cycle. Analyze phase explores: (A) Extract to separate module? (B) Extract to separate agent? (C) Dependency injection? Which is most maintainable?
- Cross-subsystems: agents/projects, agents/prompts, workflows/kanban, possibly apps_config.
**Model:** Tier 2 (Sonnet). 15–30 minutes, $0.50–1.50.

---

### Case 4: "Should we refactor the entire agents/projects orchestrator?"
**Task:** Evaluate if the polling model scales. Compare with event-driven. What architectural debt exists?  
**Decision:**
- Habit 5: Read all agents/projects/*.py, trace execution over time, analyze failure modes, review HFL entries from past issues.
- Habit 2: Express output = "Recommendation document with trade-offs (polling vs. event-driven vs. hybrid)."
- PAER Analyze: Hold 3+ hypotheses, trace implications across 5+ dimensions (latency, observability, cost, complexity, resilience, team expertise). Rank by 7 Habits alignment.
- Very high stakes: decision impacts all agent execution for months.
**Model:** Tier 3 (Opus). 1–2 hours, $5–15.
**Alternative:** Tier 2 (Sonnet) if budget is tight; reasoning will be shallower but still valuable.

---

## Monitoring & Iteration

Track model selection decisions in a log to improve future guidance:

```
Date | Task | Model | Duration | Cost | Outcome | Could have used?
2026-05-22 | Bug fix in README | Haiku | 30s | $0.001 | ✓ Perfect | —
2026-05-22 | New workflow | Sonnet | 8m | $0.18 | ✓ Good | Could have used Haiku for first draft
2026-05-23 | Kanban refactor | Haiku | 12m | $0.05 | ✗ Incomplete | Should have used Sonnet (context wall)
```

Over time, you'll see patterns:
- "I always upgrade Haiku to Sonnet for workflow work" → make Sonnet the default for workflows.
- "Tier 3 is overkill for [class of task]" → downgrade.
- "New model X is cheaper than Sonnet with better reasoning" → add to profiles.

---

## Updating This Guide

When new models arrive (GPT 5.5, Sonnet 5, Opus 2, etc.):

1. **Get the specs:** Context window, latency, cost, reasoning capability, release date.
2. **Assign a tier** based on this guide's rubric.
3. **Test against a representative task** (e.g., agents/projects refactor) — does it beat the current tier-holder?
4. **Update the table** in "Model Profiles by Provider."
5. **Update the decision tree** if the new model changes best practices.
6. **Note the change** in this section so Brian can review.

Example format:
```markdown
### [DATE] — GPT 5.5 Released

**Specs:** 256K context, 0.5s latency, $10/M in, $50/M out.
**Tier assignment:** Tier 2.5 (between Sonnet and Opus).
**Test result:** Handles Kanban refactor (Case 3) in 8m vs Sonnet's 15m. Better reasoning. Recommended.
**Updated:** Moved to Tier 2.5 profile. Updated decision tree step 7 to prefer GPT 5.5 for strategic work if cost is not primary constraint.
```

---

## TL;DR

| Task | Model | Why |
|------|-------|-----|
| Quick answers, single file, interactive | Tier 1 (Haiku) | Fast, cheap. |
| Multi-file, Habit 5, PAER, pattern synthesis | Tier 2 (Sonnet) | Big context, good reasoning, cost-effective. |
| Strategic architecture, manifesto audit, high stakes | Tier 3 (Opus) | Deep reasoning, holds complex trade-offs. |

**Default for HARQIS-work:** Tier 2 (Sonnet) for deliberate work, Tier 1 (Haiku) for quick feedback.

**Weekly PR orchestration (weekly_claude_pr.py):** Tier 2 (Sonnet). Cost per run: ~$0.15–0.50. ROI: 30–40% more actionable improvements.
