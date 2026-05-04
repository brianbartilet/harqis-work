Scaffold a new agent profile under `agents/projects/profiles/examples/` — generates the YAML with a persona block, registers placeholder Mode A env vars in `.env/apps.env`, and prints the manual Trello-account setup checklist for the user to follow afterwards.

## Arguments

`$ARGUMENTS` format:

```
<profile_name> [--display-name "..."] [--email "..."] [--role "..."] [--no-mode-a]
```

| Token | Required | Description |
|---|---|---|
| `profile_name` | Yes | snake_case base name. Either bare (`finance` → profile id `agent:finance`, file `agent_finance.yaml`) or already-prefixed (`agent_finance` → same result). |
| `--display-name "..."` | No | Human-readable name shown in signed comments and on the bot's eventual Trello profile. Default: `"Claude · <Name>"`. |
| `--email "..."` | No | Email address the persona uses (and the email you'd register the bot Trello account with). Default: `"claude-<name>@harqis.local"`. |
| `--role "..."` | No | One-line role description shown in the signature. Default: `"<Name> agent"`. |
| `--no-mode-a` | No | Skip the Mode A scaffolding — don't add `provider_credentials` placeholders or `.env` entries. Use this for ephemeral / pure-test profiles. |

If `profile_name` is missing, ask for it. If only `profile_name` is given, fill the other fields with defaults derived from it.

---

## Step 1 — Normalise names

Derive every form once at the top, reuse everywhere:

```
input:        "finance"  or  "agent_finance"
profile_id:   "agent:finance"           # used inside the YAML and for label matching
file_basename:"agent_finance"           # used for the YAML filename
display_default: "Claude · Finance"     # the visible persona name
email_default:   "claude-finance@harqis.local"
role_default:    "Finance agent"
suffix_upper:    "FINANCE"              # used for the env var suffix
```

Rules:
- `profile_id` is always `agent:<bare>` regardless of how the user typed it.
- `file_basename` is always `agent_<bare>` (underscore, lowercase).
- `suffix_upper` is `<bare>` uppercased — used for env var keys
  (`TRELLO_AGENT_API_KEY__<SUFFIX>` and `TRELLO_AGENT_API_TOKEN__<SUFFIX>`).

If the file `agents/projects/profiles/examples/<file_basename>.yaml` already exists, stop and tell the user — don't overwrite.

---

## Step 2 — Generate the profile YAML

Write `agents/projects/profiles/examples/<file_basename>.yaml` using this template. Replace every `${...}` token with the values from Step 1.

```yaml
id: ${profile_id}
name: "${display_default}"
description: "Auto-generated agent profile. Edit me before going to production."
extends: agent:base

model:
  provider: anthropic
  model_id: claude-sonnet-4-6
  max_tokens: 4096

context:
  working_directory: ""

tools:
  allowed:
    - read_file
    - glob
    - grep
    - post_comment
    - move_card
    - check_item
  mcp_apps: []

permissions:
  filesystem:
    allow:
      - "${REPO_ROOT}/**"
    deny:
      - "${REPO_ROOT}/.env/**"
  network:
    allow: []
  git:
    can_push: false
    require_pr: true

hardware:
  node_affinity: any
  queue: default

lifecycle:
  timeout_minutes: 20
  auto_approve: false
  on_success: move_to_review
  detect_dependencies: true
  block_on_missing_secrets: true

secrets:
  required:
    - ANTHROPIC_API_KEY
    # Add any app-specific env var names this agent needs (must match keys in .env/apps.env).

# Persona — used to sign comments under the shared bot account (Mode B), and
# to label this agent in audit logs. When you upgrade to Mode A (real Trello
# account per agent), the persona still drives audit log labels.
persona:
  display_name: "${display_default}"
  email:        "${email_default}"
  role:         "${role_default}"
  signature:    "Posted by ${display_default}. Reply on the card to redirect."
  # avatar_url: ""    # set after you upload an avatar to the bot's Trello profile
  # member_id:  ""    # 24-char Trello member ID once the bot is on the board
```

If `--no-mode-a` was **not** passed, append the Mode A scaffolding (commented — only activates when the env vars below are populated):

```yaml

# Mode A — per-agent Trello account.
# Leave commented until the manual setup (see below) is complete. While commented,
# the orchestrator falls back to Mode B (signed comments under the shared
# TRELLO_API_KEY / TRELLO_API_TOKEN), which works immediately.
# provider_credentials:
#   trello_api_key_env:   TRELLO_AGENT_API_KEY__${suffix_upper}
#   trello_api_token_env: TRELLO_AGENT_API_TOKEN__${suffix_upper}
```

---

## Step 3 — Register Mode A env var placeholders in `.env/apps.env`

Skip this step entirely if `--no-mode-a` was passed.

Read `.env/apps.env`. Look for an existing `# KANBAN AGENT PERSONAS` section (the heading line). Behaviour:

- If the section **does not** exist: append a fresh section at the end of the file with these two lines first.
- If the section **exists**: append the new pair under it without disturbing other agents' lines.

Each new agent gets exactly two empty lines:

```env
# KANBAN AGENT PERSONAS
# Mode A — per-agent Trello accounts (one bot account per profile, real avatar
# + email shown in Trello). Leave blank to keep that agent on Mode B (signed
# comments under TRELLO_API_KEY / TRELLO_API_TOKEN above). See the persona setup
# checklist printed by `/create-new-kanban-profile` for how to populate.
TRELLO_AGENT_API_KEY__${suffix_upper}=
TRELLO_AGENT_API_TOKEN__${suffix_upper}=
```

Do not add real values. Never overwrite a populated line.

---

## Step 4 — Notify the user (manual procedure)

Print this checklist verbatim, with `<NAME>`, `<EMAIL>`, `<SUFFIX>`, `<DISPLAY>` substituted from Step 1:

```
✅ Profile scaffolded: agents/projects/profiles/examples/<file_basename>.yaml
✅ Mode A env vars added to .env/apps.env (blank — fill in to activate)

The agent is RUNNING NOW under Mode B (signed comments under the shared
TRELLO_API_KEY / TRELLO_API_TOKEN). It will appear on the board with a 👤
signature block prefixed to every comment.

To upgrade to Mode A (real Trello account, real avatar, real attribution):

  Manual setup — ~5 minutes per agent
  ────────────────────────────────────
  1. Sign up a new Trello account at https://trello.com/signup
       Email:   <EMAIL>           ← from the persona block
       Name:    <DISPLAY>
       Password: (use your password manager)
       Verify the email when Trello sends the confirmation link.

  2. Upload an avatar at https://trello.com/<NAME>/account
       (or whatever username Trello assigned). Edit the profile YAML's
       `avatar_url` field once you have a stable image URL.

  3. Invite the bot to the Kanban board:
       - Open your KANBAN_BOARD_ID board in Trello (your main account)
       - Share → Invite by email → paste <EMAIL>
       - Set role to "Member" (not "Observer" — bots need to comment + move)
       - The bot accepts the invite from its own email inbox.

  4. Generate the bot's API key + token:
       - While logged in as the bot account, visit https://trello.com/app-key
       - Copy the API Key
       - Click "Token" → authorise → copy the token
       - Paste both into .env/apps.env:
           TRELLO_AGENT_API_KEY__<SUFFIX>=<paste>
           TRELLO_AGENT_API_TOKEN__<SUFFIX>=<paste>

  5. Activate Mode A in the profile YAML:
       - Open agents/projects/profiles/examples/<file_basename>.yaml
       - Uncomment the `provider_credentials:` block
       - Commit the change

  6. Restart the kanban orchestrator:
       /deploy-harqis host           # picks up the new credentials

The orchestrator logs `Mode A active for profile agent:<NAME>` on the first
card it processes for this agent — that's your confirmation.

If you'd rather stay on Mode B forever, you can stop here. Mode B works
indefinitely; the only difference is that all comments come from the shared
Trello account (with the persona signature making it visually clear who
acted).
```

---

## Step 5 — Update the kanban dependency detector if appropriate

If the new profile mentions any service in its description that's not already covered, follow the rules from `/create-new-service-app` Step 9b — but in 99% of cases this skill creates a profile that just *uses* existing apps, so no detector change is needed. Skip unless the user explicitly asks.

---

## Step 6 — Tell the user about test coverage

The new profile is automatically loaded by `ProfileRegistry` and gets exercised by the existing `test_profile_loading.py` collection-style tests. No new test file is required. If the user wants a dedicated behaviour test for this agent, they should ask explicitly — don't auto-generate one.

---

## Quality checklist (verify before finishing)

- [ ] `profile_id` follows the `agent:<bare>` convention
- [ ] File written at `agents/projects/profiles/examples/<file_basename>.yaml`
- [ ] File doesn't already exist (no overwrite)
- [ ] Persona block includes `display_name`, `email`, `role`, `signature`
- [ ] Mode A `provider_credentials` block is **commented** (not active) — Mode B is the default-on
- [ ] `.env/apps.env` updated with `TRELLO_AGENT_API_KEY__<SUFFIX>=` and `TRELLO_AGENT_API_TOKEN__<SUFFIX>=` (blank values)
- [ ] Existing entries in `.env/apps.env` were not modified
- [ ] Manual setup checklist printed verbatim with the right substitutions
- [ ] User reminded that the agent is **already running** under Mode B
- [ ] `--no-mode-a` skips the env-var registration and the manual checklist for it
