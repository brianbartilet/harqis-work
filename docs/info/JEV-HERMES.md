# Jev Decision Assistant in the Hermes fleet

This integration adds a versioned decision tool to an existing Hermes runtime.
Hermes retains its reasoning model; Jev evaluates typed questions. Release one
is manual, recommendation-only action triage, with local decision receipts.

## Flow

1. The owner submits action context and candidate capabilities through Fleet's
   **Conversation → Run task** on the connected Hermes agent.
2. HARQIS submits a durable run to that agent's dedicated Hermes gateway.
3. Hermes loads `jev-action-triage` and calls `analyze_typesafe_decision`.
4. The service validates bounded input, builds the versioned questions, calls
   TypeSafe, validates the answers, applies review policy, and saves a receipt.
5. Hermes explains the result, citing receipt ID, model and uncertainty. Fleet
   shows the conversation and run status. Assignments remain unchanged.

The initial MCP surface contains only model discovery and decision analysis.
Supply candidate context in the task; broader corpus retrieval requires separately
configured tools. No scheduler or automatic delegation is installed.

## Prepare the execution host

Deploy this checkout and its normal virtual environment on the machine that will
run Hermes. Configure `TYPESAFE_API_KEY` in that checkout's `.env/apps.env`. The
MCP launcher uses the existing machine environment resolver; do not paste the
key into Fleet instructions or committed YAML. Select a pinned available model
in the app config after using `list_typesafe_models`.

Create a dedicated profile through Hermes's normal profile setup, for example:

```sh
hermes profile create jev-decisions --no-skills
```

Configure its supported reasoning model using Hermes's own setup. Identify the
profile's actual home directory; do not assume Fleet creates or selects it.

Preview and apply the repository setup helper on that host:

```sh
python scripts/setup_jev_hermes.py --profile-home /absolute/path/to/jev-profile
python scripts/setup_jev_hermes.py --profile-home /absolute/path/to/jev-profile --apply
```

Use `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` on macOS/Linux.
The helper requires an existing `config.yaml`, preserves its model and other MCP
servers, backs it up once to `config.yaml.before-jev`, and installs the local skill.
It refuses conflicting entries or modified skills. YAML formatting/comments are
normalized on the first write; the backup preserves the original text.

It adds a `harqis_typesafe` MCP server running the repository's existing launcher,
with `MCP_ENABLED_APPS=typesafe` and an explicit per-profile receipt path. Hermes
tool filtering includes only the two TypeSafe tools. No key is written into that
entry. Existing profile tools are preserved; use a dedicated profile and inspect
its complete tool list before exposing the gateway.

For integration development, optionally install the upstream
[TypeSafe skill](https://docs.typesafe.ai/agent-skill) from a reviewed, pinned
revision of `typesafe-ai/skills`, copying its complete skill directory into the
profile. The operational triage skill is self-contained and does not require it.

Restart/reload the selected profile's MCP connections and verify both tools appear.
Run model discovery first. A successful model list establishes API access, not
decision accuracy. Run one synthetic triage task next; verify its persisted receipt.

## Connect Fleet

Start that profile's dedicated authenticated Runs gateway using the installed
Hermes version's supported setup. Enable the profile's MCP tools for the API
platform. This helper intentionally does not alter gateway ports, credentials,
model authentication, API-platform tool policy, or service lifecycle.

Use **Add agent → Hermes → Connected Hermes gateway → Chat and task execution**.
Enter the gateway origin reachable from the HARQIS frontend, test, then save as
**Jev Decision Assistant**. HTTPS is required except for loopback HTTP. The
TypeSafe API URL is not a Hermes gateway URL.

The gateway must advertise run submission/status and durable idempotent admission
with at least one-hour retention. Stock/version-specific gateways that fail the
capability check are not compatible; resolve that deployment gap before saving.
See [AGENT-GATEWAYS.md](AGENT-GATEWAYS.md) for the exact contract and stop/steer
behavior. Remote skill bodies are not automatically supplied by the fleet editor.

Suggested Fleet instructions:

> Use jev-action-triage to evaluate supplied actions and candidate capabilities.
> Report the actual model, receipt ID, recommendation or review reason, and
> uncertainty. Distinguish Jev probabilities from your explanation. Leave
> assignments unchanged. Never invent candidates, receipt IDs or completed work.

## Verification and evaluation

- Submit a clear match, ambiguous match, missing-context case and unsuitable set.
- Confirm real returned answers and receipt IDs, not just tool discovery.
- Check receipt SQLite storage on the profile host and the Fleet conversation.
- Confirm an API failure is visible as an error, not a recommendation.
- Test gateway request retry using the same run admission key; do not turn an
  ambiguous run into a new submission.
- Compare decisions with a labeled sample before calibrating thresholds. Include
  Hermes reasoning cost as well as Jev tokens and latency. No cost/accuracy claim
  is established by offline tests.

## Boundaries and rollback

Action **Start session** still uses the existing Action bridge; connecting this
gateway does not redirect Actions to it. To use that path, provision the tool and
skill on its worker separately and verify its execution context. This release
does not change Action routing or upload local receipts to HFL.

Each gateway/profile should serve its intended owner. Receipt storage is scoped
by local profile, not a browser-supplied owner field. Protect and back up profile
files using the execution host's access controls; Windows uses filesystem ACLs.

To roll back, disable the Fleet connection for future submissions, reconcile any
active run on its original gateway, remove the `harqis_typesafe` MCP entry and
triage skill, and restart/reload that profile. Restore `config.yaml.before-jev`
only if doing so will not discard later edits. Keep receipt history until normal
retention permits removal. No schedules need to be removed.

Provider references checked 2026-11-18:
[TypeSafe schema](https://api.typesafe.ai/openapi.json),
[Hermes MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp),
[Hermes skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills).
