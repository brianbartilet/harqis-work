---
name: jev-action-triage
description: Evaluate action routing and urgency with Jev.
---

# Jev action triage

Use the TypeSafe decision tool to recommend an agent for supplied work. This
skill produces recommendations; it does not assign work or start other agents.

1. Obtain the action title and description and the relevant candidate agents.
   Use verified fleet IDs and capabilities when available. If only user-supplied
   candidates are available, label them as supplied, not discovered. Ask for
   missing context rather than inventing candidates or fetching unrelated data.
2. Call `analyze_typesafe_decision` (Hermes may prefix the tool with its MCP server
   name) with `template: action_triage_v1` and this state structure:

   ```json
   {
     "action": {"title": "Fix failing tests", "description": "Investigate the supplied Python failure."},
     "candidate_agents": [
       {"id": "actual-fleet-id", "name": "Coding agent", "capabilities": ["Debug Python tests"]}
     ]
   }
   ```

   Supply 1–20 candidates. Keep context focused; the call sends this state to
   TypeSafe and may incur inference charges. Do not include credentials.
3. For `recommendation`, report the suggested ID, urgency score and distribution,
   model, template, and receipt ID. Explain the relevant source facts separately
   from Jev's probabilities. The provisional thresholds have not been calibrated.
4. For `needs_review`, report the reason codes and missing information. For
   `error`, report the failure; never substitute a default assignment. A timeout
   may already have incurred a charge, so do not blindly repeat it.
5. Leave assignments unchanged. A recommendation and `execution_authorized: false`
   are not execution receipts. Any later assignment requires the normal authorized
   workflow and a fresh check of the candidate's availability and capabilities.

Skills installed on the HARQIS frontend are not automatically available on a
remote Hermes gateway. Install this skill on the actual execution profile.
