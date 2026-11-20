# Claude connector and Fleet availability

## Approved behavior

Claude Code is a host connector alongside Codex. Butler monitors the connector;
profiles connect through it, and discovered skills belong to the installation.
Unavailable connectors, agents and their dependent entities stay inspectable and
appear grey. Work assignment and execution are disabled in the UI and rejected
by the server. Recovery restores availability without changing saved activation.
Shared entities remain available when another healthy relationship supports them.
This policy applies to every agent type, including provider-backed and host agents.

## Implementation

- Reuses Integrations cards, the existing Fleet connection dialog, SVG icon
  assets, entity normalization and CLI session transport.
- Claude authentication uses `claude auth status` on the HARQIS host; credentials
  and private account fields are not imported. Native sessions require both the
  saved connector and a fresh authenticated runtime advertisement for that host.
- User and project `.claude/skills/*/SKILL.md` frontmatter supplies bounded skill
  names/descriptions. Skill bodies are not imported. Incomplete reads retain the
  last observation. Multiple profiles share installation entities.
- Availability is projected separately from stored activation and work status.
  Inspection, history and configuration remain accessible while work selection,
  session starts, assignment, delegation and sends enforce availability.
- Native host selection must match the connected installation. Replaced accounts
  and installations leave old entities visible but unavailable.
- Codex installation history retains one reporting profile across multiple
  linked profiles, avoiding reattribution on subsequent refreshes.

## Evidence and limits

Read-only checks on `harqis-mac-mini` found Claude at
`/Users/harqis-one/.local/bin/claude`, authenticated with `claude.ai`.
There were 30 project skills, no user skills and no user agent definitions.
No remote files or configuration were changed by these checks.

The [Claude CLI reference](https://code.claude.com/docs/en/cli-reference) documents
authentication status; the [skills reference](https://code.claude.com/docs/en/skills)
documents the skill locations and metadata. Claude history from outside Fleet
is not imported: attribution was not verified. Existing Fleet CLI sessions remain
the source of recorded execution outputs. Existing reconciliation is reused;
this adds no briefing or notification schedule.

Provider availability uses saved connection state and the existing refresh
mechanisms; host availability additionally uses worker advertisements. This is
not continuous network probing of every external provider.

## Validation

Focused tests cover connection setup, shared profiles/skills, owner isolation,
disconnect, worker loss/recovery, disabled agents, shared child availability,
malformed discovery, host affinity, and replaced installations. Browser checks
exercise connection and unavailable inspection at 390px and 1440px. Related
Codex, Grok, entity and graph regressions were also exercised:

- Initial combined Python/browser run: 53 passed, with two old expectations
  failing (hidden native connectors and custom color without a healthy host).
  Both expectations were updated to match the approved policy.
- Follow-up run: 17 passed, including both corrected tests, eight Claude cases
  and seven Fleet session lifecycle/browser cases.
- 26 JavaScript graph/filter/grouping tests passed. The Fleet bundle was rebuilt;
  Python/JavaScript syntax checks and `git diff --check` passed.
- Final settled-graph browser pass: two passed at 390px and 1440px; screenshots
  reviewed for the Claude icon, grey unavailable relationships and inspector.

Local implementation only; not committed or deployed.
