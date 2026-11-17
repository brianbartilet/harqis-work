# Agency specialist profiles in Agent Fleet

Fleet → Add agent → choose a classification → choose an Agency Agents profile.
Preview its description, full instructions, expected output and example task, then
select **Use this profile**. An empty description is filled automatically; replacing
an existing description requires checking the explicit replacement option.
Additional instructions, persona, tools and skills remain under your control.

The initial curated profiles are Code Reviewer, Backend Architect and Technical
Writer. Search covers all three profiles and shows visible result cards;
classification ranks matching profiles first without hiding others. Changing it does not remove a saved
specialist. Custom mode hides catalog browsing without clearing a saved selection;
use **Remove profile** to detach it. Suggested skills are optional, explicit choices.
The use cases, output helpers, examples and skill mappings in `manifest.json` are
HARQIS-authored. Source descriptions and Markdown come from Agency Agents.

## Example

1. Create **Ada · Code reviewer**, service **Hermes**, classification **Coding agent**.
2. Choose **Code Reviewer**, inspect the documentation and use the profile.
3. Add “Focus on retries and idempotency” to Base/Gateway instructions.
4. Optionally select the suggested repository skills.
5. Preview effective instructions, then save. Start a new session to use them.

Saving does not execute a task, install plugins, grant tools or create schedules.
For external services Fleet stores the specialist as metadata and displays
**Provider setup required**. Configure instructions in that provider separately.
For Hermes, action execution snapshots, primary assistant conversations and Fleet
gateway conversations compose the saved specialist with local instructions.
Gateway chat/tool restrictions remain in force. Existing sessions keep their
original instructions; changes affect new sessions only.

## Provenance and updates

`manifest.json` pins an upstream commit and SHA-256 of each exact source file in
`upstream/`. See `LICENSE` for the upstream MIT notice. No runtime GitHub requests
are made. Bodies are loaded on demand and checked against the manifest; the UI
renders them using the existing sanitized Markdown renderer.

To update, fetch the selected source files from one explicit upstream commit,
review their diffs and the license, update the revision and byte hashes in the
manifest, review helper mappings, and run `frontend/tests/test_fleet_specialists.py`.
Do not normalize the source file bytes without updating their hashes. The adjacent
`.gitattributes` preserves those bytes across platforms.

Agent records retain an immutable snapshot (source, ID, revision, hash and body).
New selections are resolved server-side; client-supplied bodies are rejected.
Existing saved snapshots survive catalog removal or updates. To adopt a new
version, preview it in Add/Edit Agent and explicitly use it, then save. Custom
guidance remains separate. Removing the profile leaves custom fields unchanged.
No automatic upstream updates or delegation are introduced.

## Validation and limits

The backend validates profile IDs/revisions/hashes and limits composed Hermes
instructions to 23,000 characters, leaving room for persona and gateway rules.
One specialist is supported per agent. The effective preview shows the same
specialist/local composition used at execution; the runtime adds its own operating
rules and configured skill/tool context.

Catalog endpoints are owner-authenticated under `/agents/api/specialists` and
`/agents/api/specialists/{identity}`. `/agents/api/specialist-preview` validates a
draft without saving or starting a session. Execution snapshots include the
specialist provenance in their existing audit hash.
