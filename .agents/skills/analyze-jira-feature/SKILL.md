---
name: analyze-jira-feature
description: >
  Analyze a Jira feature, epic, or objective with its related stories, generate story-level
  Gherkin, and write an end-to-end Markdown overview with dependencies, risks, and gaps.
allowed-tools: Bash Read Glob Grep Edit Write
---

# Analyze Jira Feature

Turn a Jira feature, epic, or objective into a cohesive delivery and test view. Use the
root ticket and its directly related stories to explain the business outcome, process
flow, dependencies, coverage, risks, edge cases, and specification improvements.

Use the `generate-gherkin-scenarios` skill for story-level feature files. Read that skill
before generating and preserve its clarification, quality, tagging, overwrite, and
validation rules.

## Inputs

Accept a Jira URL or key for a Feature, Epic, Objective, or similar grouping ticket.
Optional user choices may change:

- relationship depth: direct children/stories or recursive traversal;
- criteria scope: functional only, technical only, or both;
- Gherkin style and output locations.

Defaults:

- analyze stories directly related to the root ticket;
- reference secondary Features, Tests, bugs, and external dependencies without
  recursively generating Gherkin for them;
- generate functional acceptance criteria when present;
- if a story has no functional acceptance criteria, generate its technical acceptance
  criteria instead;
- write Gherkin to `results/gherkin-generated/<STORY-KEY>.feature`;
- write the overview to `results/feature-analysis/<ROOT-KEY>.md`.

Never overwrite an existing output without explicit confirmation.

## Clarify once

Before writing, fetch enough Jira data to understand the hierarchy and specifications.
If the user has not already decided, ask one compact clarification round with at most
three questions covering:

1. direct versus recursive relationship scope;
2. functional/technical acceptance-criteria scope;
3. Gherkin style and whether unresolved outcomes should become `@pending` scenarios.

Do not ask again for choices already established in the conversation.

## Discover the feature graph

Load `.env/apps.env` and call Jira REST API v2 with Bearer authentication. Fetch only
fields needed for the analysis: key, summary, issue type, status, description, labels,
components, fix versions, issue links, subtasks, and known parent/epic fields.

Relationship field IDs vary by Jira installation. Discover their IDs from Jira field
metadata instead of hardcoding them. Treat link direction and wording carefully:
`objective of`, `belongs to objective`, `Child of`, `depends on`, `dependency for`,
`tested by`, and `relates to` express different relationships.

By default:

- include direct Story children in scenario generation;
- use linked Features/Epics to group the stories and understand parallel workstreams;
- list Tests, Test Executions, bugs, and external dependencies as context;
- do not recursively expand every linked issue, because generic `relates to` links can
  create an unbounded and misleading scope.

If the root description is empty, infer the objective from its summary and child-story
evidence, and clearly label that interpretation as an inference.

## Generate story-level Gherkin

For every in-scope story:

1. identify functional ACs, TACs, deprecated/struck-through criteria, and ambiguities;
2. apply the confirmed criteria policy;
3. generate one complete `.feature` document using `generate-gherkin-scenarios`;
4. use `@pending` only when the user has approved placeholders for unresolved behavior;
5. keep placeholder outcomes explicit, such as `Then TODO: define ...`;
6. validate that the file has one `Feature:`, at least one scenario, and exactly one
   `When` and one `Then` block per scenario;
7. record scenario and type-coverage totals for the overview.

Do not generate scenario files for grouping tickets, Tests, bugs, or dependencies unless
the user explicitly includes them.

## Analyze how the stories come together

Build the process from business outcome to technical delivery. Distinguish Jira facts
from reasonable inference. Identify:

- user and audience journeys;
- content or data lifecycle;
- system handoffs and identifier transformations;
- regional, role, device, channel, and format decisions;
- dependency chains and likely critical paths;
- status and release inconsistencies;
- repeated or conflicting acceptance criteria;
- missing failure behavior and non-functional requirements;
- test assets and traceability gaps.

When multiple journeys share infrastructure, show the shared foundation and each branch
instead of forcing them into one linear flow.

## Write the Markdown overview

Create `results/feature-analysis/<ROOT-KEY>.md` with:

1. root-ticket link and dated scope snapshot;
2. executive overview and overall objective;
3. scope and generation policy;
4. related Feature/Epic grouping;
5. end-to-end process flow, using Mermaid when it materially clarifies dependencies;
6. story details, status, release, generated criteria, and links to each `.feature` file;
7. dependency and readiness view;
8. existing Test, Test Execution, and bug coverage;
9. prioritized risks and edge cases with affected stories and recommended checks;
10. pending scenario decisions;
11. actionable specification, architecture, and test improvements;
12. recommended end-to-end acceptance slices.

From the default report directory, link generated files as:

```markdown
[ICON-1234.feature](../gherkin-generated/ICON-1234.feature)
```

Use absolute Jira HTTPS links for tickets. Do not include credentials, internal API
responses, or raw custom-field dumps.

## Quality checks

Before reporting completion:

- verify every in-scope story has a generated file;
- verify every report link resolves locally;
- verify struck-through criteria were excluded;
- verify functional-only stories contain no TAC-tagged scenarios;
- verify TAC-only fallback is clearly stated in file headers and the overview;
- recount scenario and tag totals from the generated files;
- run whitespace/diff checks;
- validate this skill with the skill-creator validator after editing it.

Report generated paths, total stories/scenarios, pending decisions, and the most material
risks. Note when the `results` directory is ignored by Git so the user understands that
the artifacts remain local.
