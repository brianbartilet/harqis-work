# TypeSafe

## Description

TypeSafe's Jev evaluates supplied state using typed questions. This integration
provides recommendation-only action triage for Hermes through the shared CLI/MCP
catalog. Authentication is bearer-token based. Contract reviewed 2026-11-18:
[OpenAPI](https://api.typesafe.ai/openapi.json),
[quick start](https://docs.typesafe.ai/introduction/quickstart).

## Supported Automations

- [x] webservices — model discovery and System One decisions
- [ ] browser
- [ ] desktop
- [ ] mobile
- [ ] internet of things

## Directory Structure

```text
apps/typesafe/
  config.py
  mcp.py
  templates.py                 # Versioned questions and review thresholds
  receipts.py                  # Profile-local SQLite receipts
  references/dto/system_one.py # Typed response validation
  references/web/base_api_service.py
  references/web/api/system_one.py
  tests/test_live.py           # Opt-in live API checks
```

Offline protocol and policy tests live in `tools/tests/test_typesafe.py`.

## Configuration

The tracked `apps_config.yaml` contains:

```yaml
TYPESAFE:
  app_id: 'typesafe'
  client: 'rest'
  parameters:
    base_url: 'https://api.typesafe.ai/'
    response_encoding: 'utf-8'
    verify: True
    timeout: 30
    stream: False
  app_data:
    api_key: ${TYPESAFE_API_KEY}
    model: 'jev-latest'
  return_data_only: True
```

Set `TYPESAFE_API_KEY` in the execution host's gitignored `.env/apps.env`.
The transport deliberately fixes the HTTPS origin, verifies TLS, rejects redirects,
and uses a 30-second operation timeout with a 5-second connect timeout.
Changing generic REST parameters does not change these transport limits.
Use model discovery to select an account-visible pinned model for production;
`jev-latest` is a moving alias. No new SDK dependency is required.

`TYPESAFE_RECEIPTS_DB` optionally selects the local receipt database. Otherwise it
lives under `HERMES_HOME`, or `~/.hermes`, as `typesafe-decisions.sqlite3`. Give each
owner/runtime its own profile and database; this file is not a multi-user web API.
Keep it outside tracked checkout files and include it in host backups.

## Available Services

| Class | Method | Behavior |
|---|---|---|
| `ApiServiceTypeSafeDecisions` | `list_models()` | GET `/v1/models` |
| `ApiServiceTypeSafeDecisions` | `analyze_decision(template, state)` | POST `/v1/systemone`, validate, interpret, persist receipt |

The generic endpoint is deliberately internal. The operational tool uses only
the reviewed `action_triage_v1` template; no arbitrary questions, images, long
context flags, execution or scheduling are exposed.

## MCP Tools

| Tool | Args | Description |
|---|---|---|
| `list_typesafe_models` | none | Discover available models |
| `analyze_typesafe_decision` | `template`, `state` | Billed inference; stores a local receipt; never assigns or executes work |

All surfaces reuse the registration in `tools/catalog.py`. Load the repository's
machine environment before bare CLI/test invocations. The MCP launcher does this
automatically. With that environment loaded:

```sh
python -m tools commands typesafe
python -m tools schema typesafe analyze_typesafe_decision
python -m tools call typesafe list_typesafe_models
python -m tools call typesafe analyze_typesafe_decision --input -
```

Pass this JSON on stdin for the last command:

```json
{
  "template": "action_triage_v1",
  "state": {
    "action": {"title": "Fix failing tests", "description": "Investigate the supplied Python assertion failure."},
    "candidate_agents": [
      {"id": "actual-fleet-id", "name": "Coding agent", "capabilities": ["Debug Python tests"]}
    ]
  }
}
```

Use real, visible fleet IDs when available; the tool validates the supplied set
but does not independently discover fleet membership or permissions. Limits:
1–20 candidates, unique IDs, title 500 characters, description 16000 characters,
1–20 capability strings per candidate (500 characters each), 48 KB state total.
Extra input fields are rejected to prevent accidental context forwarding.

## Tests

Use the repository virtual environment and machine environment bootstrap:

```sh
python -m pytest tools/tests/test_typesafe.py scripts/tests/test_setup_jev_hermes.py -q
python -m pytest apps/typesafe/tests -q
```

Live tests skip unless `TYPESAFE_LIVE_TESTS=1`. They require a real
`TYPESAFE_API_KEY`; the synthetic decision test sends synthetic context and may
incur a charge. Offline tests validate HTTP behavior, response contracts, review
outcomes, receipt privacy/failures, setup idempotence, and CLI/MCP discovery.

## Notes

- `recommendation` means a candidate passes provisional review thresholds;
  `needs_review` means no candidate should be assigned automatically. Both return
  `execution_authorized: false`. Thresholds live in `templates.py`; calibrate on
  labeled examples before changing automation policy. Version changed policies.
- A successful response includes typed answers, actual model, token usage,
  template, policy, latency, and receipt ID. HTTP/transport/schema failures return
  `status: error` with a sanitized message and receipt. Input/configuration errors
  raise before inference. Receipt write failure raises instead of returning a
  usable recommendation. CLI callers must inspect the nested decision status as
  well as the CLI envelope.
- The tool retries 429/502/503/504 at most twice (1 and 2 seconds). Timeouts and
  transport errors are not retried because admission is ambiguous. Provider
  retries may be billed; the API does not supply our Hermes run idempotency.
- Receipts retain candidate IDs, probabilities, model, usage, policy and outcome;
  raw action text and candidate names/capability descriptions are excluded.
  The shared CLI has its own input audit log; private callers should use the
  scoped MCP path and review host logging/retention. Normal agent histories can
  also retain submitted context.
- Receipts are local, not automatically uploaded to HFL or displayed in Fleet.
  Fleet gateway conversations retain the agent's report. Automatic HFL receipt
  ingestion and remote Action-bridge routing are separate follow-up work.
- Jev is not the Hermes reasoning model. See the
  [Hermes deployment guide](../../docs/info/JEV-HERMES.md).
