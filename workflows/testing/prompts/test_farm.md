/generate-gherkin-scenarios

You are running UNATTENDED inside a scheduled "BDD test case farm" job. The full
ticket specification is provided below — apply the generate-gherkin-scenarios
skill to it directly. Critical overrides for headless operation:

- Do NOT ask any clarifying questions — AskUserQuestion is unavailable here.
  Where the skill would normally ask, choose the most reasonable interpretation
  and list any residual ambiguity under a final "## Open questions" heading.
- Do NOT use any tools and do NOT fetch anything. Everything you need is inline
  below — do not read or write files, do not call Jira.
- Generate scenarios for ALL acceptance criteria you can identify (no subset).
  Skip struck-through / deprecated ACs and note the skip in the header comment.
- think hard about edge cases, negative paths, permissions and integration
  touchpoints before writing.

Output, in this exact order and NOTHING else (no preamble, no closing chatter):
1. A single fenced gherkin code block containing the .feature file.
2. The "AC <-> scenario" coverage mapping table.
3. The type-coverage tally line (N x @functional, M x @integration, ...).
4. An optional "## Open questions" section only if ambiguity remains.

------------------------------------------------------------------------------
Ticket: {key} — {summary}
Issue type: {issuetype}    Priority: {priority}    Status: {status}
Fix version(s): {fix_versions}

Description / Acceptance Criteria:
{description}
------------------------------------------------------------------------------
