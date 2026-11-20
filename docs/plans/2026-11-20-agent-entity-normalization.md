# Agent-type entity normalization

Approved scope: an owner-scoped Fleet entity catalog, explicit equivalents per
agent type, skill entities, conservative empty-record cleanup, and read-only
Grok outputs as evidence for existing Butler briefings.

## Catalog and identity

Use **Manage** beside **Entity orbs**. Each type has a stable key, editable name,
description, color, keywords, visibility, and agent-type equivalents. Keywords
assist discovery; only explicit source-object mappings normalize the graph.
One provider/source-object pair maps to one type. Built-ins can be edited or
hidden; custom types can be removed or reassigned with their references.

Definitions and overrides belong to the signed-in owner. Normalization applies
to all agents of a provider; it never merges their source identities, accounts,
or permissions. Entity IDs, provenance, relationship edges and merge histories
remain independent of display names. Configured/uploaded skills now render as
`skill` using their existing graph IDs.

Removal and cleanup retain original payloads in
`fleet_entity_catalog_audit`. Empty cleanup only removes genuinely blank,
unreferenced placeholders. Zero visible objects, blank descriptions, stale
discovery, and historical objects do not qualify for deletion. On 2026-11-20,
the Mac mini audit checked 59 entity/output records and found no qualifying
empty placeholders; no records were deleted.

## Initial mappings

| Agent type | Source object | Fleet type | Scope / evidence |
| --- | --- | --- | --- |
| Grok | Connection | connector | Account; verified |
| Grok | Published conversation replies | entry | Agent; verified read contract |
| Grok | Skills | skill | Shared account/Cloud Box; documented |
| Grok | Library saved files | file | Account; documented |
| Grok | Library pages | entry | Account; proposed content mapping |
| Grok | Routines | workflow | Agent; documented |
| Grok | Routine schedules | schedule | Agent; documented |
| Grok | Routine events | trigger | Agent; documented |
| Grok | Connected services / accounts | application / account | Account; documented |
| Grok | Media | file | Agent; documented |
| Grok | Settings | configuration | Agent; documented |
| Nod | Schedules | schedule | Installation; verified |
| Nod | Applications / connections | application / account | Installation; verified |
| Hermes | Configured skills / workflows / triggers | skill / workflow / trigger | Existing Fleet configuration |

Schedules mean **when**; triggers mean **which event**. A routine may link to
both. A Library container is not itself a file. Vault credentials are excluded.
The supplied Grok guide describes shared Library and skills, and per-agent
chat, memory, routines and media; these semantics do not prove API coverage.

## Grok output retrieval

**Refresh Grok outputs** in the selected connected Bot's Outputs tab reads at
most 50 transcript entries through `ListGrokBotTranscriptEntries`, reusing the
encrypted account connection. It records completed `send-message` text and
attachment references, deduplicated by account/Bot/entry ID. Internal assistant
messages, streaming rows, credential/approval cards, blobs, unknown types and
undated rows are skipped. Counts and the history limit are reported to the user.
Text is bounded to 5,000 characters. Attachments link to the Bot conversation;
signed download URLs and files are not copied. This is recent-output retrieval,
not a full transcript archive or a task-completion detector.

Recorded replies contribute to Fleet agent updates and existing Butler briefing
evidence. The existing Hermes sweep remains the sole briefing scheduler. No
proactive notification delivery or new polling schedule is installed.

Protocol references inspected:

- [Transcript parser](https://github.com/Nuncio-hq/grokbot-cli/blob/main/packages/grokbot-core/src/transcript.ts)
- [Skill library contract](https://github.com/Nuncio-hq/grokbot-cli/blob/main/packages/grokbot-core/src/workforce-skills.ts)
- [Skill gateway handler](https://github.com/Nuncio-hq/grokbot-cli/blob/main/packages/grokbot-core/src/workforce-skill-handlers.ts)

Grok's skill library uses the separate Cloud Box gateway `getAgentWorkflows`.
Live discovery of that library, Library pages/files, routines and settings is
not implemented by this change. Catalog cards distinguish documented mappings
from verified discovery. Existing configured/uploaded or already detected
skills are supported without asserting those remote capabilities.

## Validation

- 51 focused tests passed across `test_entity_catalog.py`,
  `test_fleet_entities.py`, `test_grokbot_connector.py`, and `test_n8n_fleet.py`.
- 26 JavaScript graph/filter/grouping tests passed, including skill visibility
  under date filtering and catalog-controlled status colors.
- Full-page browser checks at 390px and 1440px covered catalog editing, stable
  keys, create/search/remove, cleanup feedback, overflow, Escape and focus return.
  Screenshots were visually reviewed. The mobile test closes the existing work
  drawer before using the inspector.
- A broader `test_agent_fleet.py` run stopped after 34 passing tests at
  `test_n8n_sync_preserves_local_metadata_and_disable_hides`: its mock covers
  `N8n.agents`, but current sync also performs unmocked workflow-library discovery
  against `n8n.example.test`, returning 502. That integration path is unchanged;
  the dedicated n8n inventory tests passed in the focused suite.
- The frontend bundle was rebuilt. This change has not been committed or deployed.
