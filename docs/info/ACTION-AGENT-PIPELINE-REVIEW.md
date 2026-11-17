# Action, Fleet and results pipeline review

Reviewed against repository code on 2026-11-17. This is a code review, not a verification of deployed workers or live provider connections.

## Findings

| Question | Current behavior and evidence |
| --- | --- |
| Does opening an Action session launch a generic worker? | Only an unassigned legacy Action uses shared defaults. `frontend/modules/hfl_corpus/action_agents.py:effective` resolves the assignment; `start_session` includes Action and board context. `action_assignment.py:resolve` applies the assigned Hermes agent. The screenshot explicitly shows `legacy` / Shared defaults. Opening a terminal does not execute the initial prompt again. |
| Do CLI sessions need assignments? | Yes. Assignment identifies the responsible agent and supplies instructions, skill contents, model, tools, host and repository configuration. CLI is a transport, not an execution identity. The terminal currently supports Hermes only. A Codex/Nod/other provider assignment cannot silently fall back to Hermes. |
| Does assignment select a status workflow? | No. `agent_bridge.py:apply_action`, `report` and `accept` control structured Action run transitions, independent of the Fleet agent's persona. Butler mode adds coordination instructions. An interactive terminal has separate session states; opening or closing it is not proof that the Action started or finished. |
| How do boards fit? | An Action has one canonical status and may appear on multiple boards. Boards provide organization and context (`intent_board_context.py`); changing assignment should not create another Action or another status owner. The separate Trello Kanban orchestrator under `agents/projects` is another execution surface, not an automatic consequence of a Fleet assignment. |
| Are results reported to HFL? | Structured run delivery uses `agent_bridge.py:deliver_pending`, a durable delivery state and the deduplication key `agent-run:<run_id>`. Fleet receipts use `agents/audit.py` and `fleet:<event_id>`. Both call the existing HFL persistence pipeline. A terminal receipt or transcript is evidence of activity, not a structured completion result. |
| What happens when agents change? | `agents/service.py:execution` snapshots the agent ID, version, configuration hash, specialist and selected skill contents for execution. Existing sessions retain their saved settings; future runs resolve current configuration. Native restore currently retains only the original host/profile while other settings come from the current Action assignment (`workflows/hfl/action_agent_store.py:start_session`). This can mix an old conversation with new instructions. |

## Changes in this revision

- Inactive agents are excluded from selectable options. A previously assigned inactive agent remains identifiable; the API rejects a new assignment to an inactive agent.
- Agent default settings opens `/agents`, matching the session workspace.
- Action Connections includes a current `assigned-to` agent relationship, using the existing owner-filtered assignment lookup. This is derived from assignment, not stored as a second editable board edge. Changes to assignments refresh the preview.
- Fleet's Add action opens the shared Create Action form with the selected agent and its Spaces prefilled. Saving uses the existing assignment persistence path; external providers remain assignment-only. No action is created merely by opening the form.
- Fleet session preparation explicitly records `agent` or `butler` mode instead of leaving an assigned session card labelled `legacy`.

UI reuse: `hfl-ideas.js:openEditor` supplies the shared editor, `hfl-action-agent-settings.js` supplies assignment controls and save ordering, `agent-fleet.jsx` supplies existing inspector button styling, and `action-connections.jsx` supplies the graph and relationship inspector. Existing templates use versioned `static_asset` references; the changed React bundles are rebuilt.

## Recommended consolidation

Keep three responsibilities explicit: **Action = intent and outcome; Fleet agent = execution identity and capabilities; board = organization and readiness**. Butler may coordinate, but status and reporting guarantees must live in the shared run service.

1. Use one assignment record for the editor, Fleet, connections, queued runs and sessions. Retain legacy behavior for existing actions; migrate only after selecting a specific agent. New actions should default to manual unless created for an agent. Consolidate per-card execution overrides into Fleet over time; retain Action-specific guidance and outcome criteria.
2. Add an explicit capability contract per provider: assign, converse, execute Action, resume, cancel, report result, upload artifact. Derive available controls from verified capabilities rather than `runtime === 'hermes'`. Gateway chat availability and provider observation are not proof of Action execution support.
3. Give every execution a stable run ID, Action ID, agent ID, configuration version/hash, provider execution ID, parent run ID where delegated, and one execution owner. Map native provider events into shared queued/running/awaiting-input/review/failed/completed states. Keep session connectivity separate from these states.
4. Make readiness and dispatch explicit. Current labels are In Review (`open`), Ready (`active`), In Progress, Incomplete, Done and Dismissed. The scheduler selects eligible enabled Ready Actions with prompts. Preserve that gate when adding provider dispatch. Assignment alone must not dispatch. Use idempotent dispatch and optimistic Action versions so two surfaces cannot launch or complete the same attempt independently.
5. Require a structured final result containing summary, completion assessment, evidence and artifact references. Apply completion through existing acceptance/auto-completion policy. Provider adapters should use this contract rather than interpreting a disconnected terminal or completed chat turn as Action completion.
6. Preserve existing HFL delivery and Fleet receipts. Correlate both with Action/run/provider IDs; show delivery pending/failed separately from execution success. A retry of corpus delivery must not re-run the task. Keep produced artifacts and the saved execution snapshot attached to the original attempt.

## Agent mutation and Add agent flow

Use a stable, owner-scoped provider identity; never join agents or results by display name. Provider refresh should preserve local customizations and independent relationships. Deactivation blocks new assignments/runs while retaining historical provenance.

The Add agent flow should capture provider/account, verified capabilities, purpose/specialist, skills, tools, worker or remote endpoint, Spaces and scheduling owner. Its final screen can offer Add action using the shared editor introduced here. Selecting a skill is instruction configuration, not a grant of tools or credentials; validate required tools and worker availability before dispatch.

Before restoring a native session, compare the original assignment/configuration with the current one. Prefer restoring the complete saved execution snapshot; offer a fresh session for current settings. Keep deactivation and access checks in force. Also make clear when an existing live session is being attached, since the store returns a live session instead of creating a second one for the same Action.

Related repository skills:

- `design-agent-connector`: provider discovery, stable identities, capability verification, customization preservation and one schedule owner.
- `create-action`: canonical Action creation and attachments; currently records intent with execution disabled. It does not yet provide the Fleet assignment operation, so do not imply that naming an agent in a prompt assigns it.
- `choose-automation-runtime`: use before introducing schedules. The proposed pipeline is hybrid: agents decide and perform adaptive work; durable services own dispatch, leases, retries and reporting. Choose exactly one schedule owner for each automation.
- `create-new-kanban-profile` / `create-new-kanban-board`: apply to the separate Trello orchestration setup. Integrate through a run adapter and explicit Action/card correlation, not a second uncoordinated status loop.
- `capture-hfl-session`: a fallback audit capture when lifecycle capture is unavailable. It should not duplicate the structured result delivery or declare an Action complete.

## Follow-up priorities

1. Resolve native restore configuration consistency; add tests for reassignment, agent edits, deactivation and restoration.
2. Introduce shared provider capability and run/result contracts, then enable one additional provider end to end with dispatch deduplication and result correlation tests.
3. Extend canonical Action tools/skills to assign an agent and read its effective capability state; avoid requiring browser-only configuration.
4. Add a compact Action run timeline showing assigned agent, actual run snapshot, status transitions, artifacts and corpus delivery state. Validate concurrent edits, retries, provider failures and multiple-board membership.
5. Resolve draft execution summaries from the proposed assignment. The editor currently displays the last loaded effective settings until save; a new agent selection can temporarily show shared or previous runtime defaults. Extend the read-only preview contract to return effective execution settings as well as composed instructions.

These architectural steps are recommendations, not implemented provider integrations or changes to live scheduling in this revision.

## Validation

- Frontend bundles rebuilt successfully; `git diff --check` passed.
- Twelve focused tests passed across assignment persistence, inactive-option filtering, settings navigation, current assignment connections, Fleet session preparation, frozen sessions and the Fleet Add action shortcut.
- New Action form screenshots inspected at 1440px and 390px; no horizontal overflow. Keyboard dismissal and save behavior exercised.
- A broader existing `test_fleet_browser` run failed waiting for `.fleet-work-panel header p` after agent selection, before reaching the new shortcut. The isolated shortcut test passed. The broader failure remains unresolved.
- No deployment, live worker execution, external-provider dispatch or live corpus delivery was performed.
