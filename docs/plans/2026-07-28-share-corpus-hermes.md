# Share Corpus Hermes Backend Implementation Plan

> **For Hermes:** Implement task-by-task with strict RED-GREEN-REFACTOR and verify every runtime boundary before publishing.

**Goal:** Route Share Corpus Q&A through a dedicated, locked-down Hermes profile using the owner's connected OpenAI Codex model while preserving HARQIS snapshot authorization, citation validation, rate limits, and the Anthropic fallback.

**Architecture:** HARQIS remains the security and retrieval boundary. It selects and sanitizes frozen entries, builds the bounded prompt, calls either Anthropic or a loopback-only Hermes OpenAI-compatible API, and validates citations before rendering. A dry-run-first runtime setup script creates an isolated `sharecorpus` Hermes profile with no skills, memory, user profile, tools, messaging surfaces, or browser CORS; it writes a dedicated API key into gitignored profile/HARQIS environment files and optionally installs and starts the profile gateway after OAuth is configured.

**Tech Stack:** FastAPI frontend, Pydantic settings, `httpx`, Hermes OpenAI-compatible API, Python 3.11 setup automation, pytest.

---

## Express output

A reviewable GitHub pull request where:

- `HFL_SHARE_PROVIDER=hermes` routes Q&A server-side to a loopback Hermes API.
- The browser never sees the Hermes URL or bearer key.
- The default Hermes profile is never used.
- The dedicated profile has an empty API-server toolset and disabled memory/profile injection.
- HARQIS still rejects uncited or out-of-snapshot answers.
- A setup/check script configures both sides without printing or committing secrets.
- The Hermes setup raises the recommended retrieval budget to 120,000 characters while keeping it configurable.

## Task 1: Add provider-routing tests

**Files:**
- Modify: `frontend/tests/test_hfl_shares.py`
- Modify: `frontend/config.py`
- Modify: `frontend/modules/hfl_shares/agent.py`

**Steps:**
1. Write a failing async test that selects `hermes`, stubs `httpx.AsyncClient`, and asserts the request uses loopback `/v1/chat/completions`, bearer authentication, the configured model, system/user messages, no stream, and bounded output tokens.
2. Run the single test and confirm it fails because Hermes routing does not exist.
3. Add the minimum settings and adapter implementation.
4. Run the single test and confirm it passes.
5. Add failing tests for missing key, non-loopback URL, malformed/empty response, and provider failure redaction.
6. Implement only the validation/error handling required by those tests.
7. Run the focused agent tests.

## Task 2: Add secure setup automation

**Files:**
- Create: `scripts/setup_hfl_share_hermes.py`
- Create: `scripts/tests/test_setup_hfl_share_hermes.py`
- Modify: `scripts/README.md`

**Steps:**
1. Write failing tests for dry-run no-write behavior, idempotent env-file updates, locked-down profile configuration, restrictive file permissions, and secret-free output.
2. Run the script tests and confirm missing implementation failures.
3. Implement a Python 3.11 script with `--apply`, `--start`, and `--check` modes.
4. Create a blank `sharecorpus` profile with `--no-skills`; never clone the default profile.
5. Configure `gpt-5.6-sol` through `openai-codex`, disable memory and user profile, set `platform_toolsets.api_server: []`, bind the API to `127.0.0.1`, omit CORS, and generate a dedicated bearer key.
6. Update gitignored HARQIS `.env/apps.env` with provider, endpoint, model alias, key, and `HFL_SHARE_MAX_CONTEXT_CHARS=120000` without printing the key.
7. Require a one-time profile-scoped Codex OAuth login before `--start`; never copy the default profile's credentials or private state.
8. Optionally install/restart the profile gateway and verify `/health` plus authenticated `/v1/models`.
9. Document real invocation paths and recovery/rollback.

## Task 3: Update operator documentation

**Files:**
- Modify: `docs/info/HFL-CORPUS-SHARING.md`
- Modify: `scripts/README.md`

**Steps:**
1. Document Anthropic and Hermes provider settings.
2. Explain that Hermes must use the dedicated profile, localhost transport, empty toolset, disabled memory, and separate OAuth/session state.
3. Explain setup, health check, frontend restart, rollback, model-quota implications, and the 120k context trade-off.
4. Correct stale snapshot-limit examples encountered in the touched documentation.

## Task 4: Verify and publish

**Steps:**
1. Run focused frontend and setup-script tests.
2. Run the complete `frontend/tests/test_hfl_shares.py` suite.
3. Run script dry-run against temporary homes and perform syntax checks.
4. Run a security review for secret leakage, SSRF, tool exposure, memory exposure, and citation bypass.
5. Review the diff against `origin/main`; ensure the dirty primary checkout is untouched.
6. Commit only intentional files, push `feat/share-corpus-hermes`, and create the PR.
7. Inspect GitHub checks and report their actual state.
