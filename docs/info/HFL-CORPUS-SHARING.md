# Activity Corpus Sharing

Activity Corpus Sharing creates temporary, read-only guest portals without
joining a guest device to the HARQIS VPN or exposing the HARQIS topology. A QR
code is only a convenient encoding of a high-entropy capability link. It does
not install software, enroll a device, or grant network access.

Run Sharing on the canonical Activity Corpus host. A frontend configured as a
remote corpus reader fails closed rather than freezing data from its local
disk.

## Lifecycle

1. The owner creates or loads a reusable recipe.
2. Sources are selected as the primary authorization boundary. Tags, dates,
   topic terms, and explicit entry IDs can narrow it further.
3. Preview recalculates current corpus matches and shows counts, date range,
   source/tag distribution, context size, warnings, entry summaries, and
   eligible references.
4. Owner preview chat uses only that transient preview and does not create a
   guest audit event.
5. Generate forces a fresh corpus read and freezes the matches into an
   immutable SQLite snapshot.
6. The owner receives a QR and pasteable capability link. PIN mode additionally
   displays a random eight-digit PIN once.
7. Successful redemption binds one server session to an HTTP-only signed
   cookie. No browser fingerprint is collected.
8. Expiry or owner revocation makes the grant and every associated session
   invalid immediately.

Editing or deleting a recipe never changes or revokes previously generated
shares. To change an active scope, revoke it and generate a new snapshot.

## Access modes

| Mode | Verification | Notes |
|---|---|---|
| QR + PIN | Capability token plus separately communicated eight-digit PIN | Default. Five failed attempts lock the grant. |
| Email OTP | Cloudflare Access identity header plus exact configured email | Requires the dedicated `/share/email/*` Access policy described below. |
| Manual approval | Capability token plus one owner-approved browser request | Guest waiting cookie is HTTP-only and expires after one hour. |
| QR possession | Capability token only | Suitable only for low-risk context; link possession is authorization. |

The default grant lasts one hour, permits one session, is single-use, disables
references, and terminates active sessions when revoked.

## Required configuration

Configure secrets in gitignored `.env/apps.env` or machine-local environment
settings:

```env
BEHIND_PROXY=true
HFL_SHARE_PUBLIC_URL=https://share.example.com
HFL_SHARE_SECRET_KEY=<independent-random-secret>
HFL_SHARE_STORE_PATH=/Users/harqis-one/.harqis-data/hfl-shares.sqlite3
HFL_SHARE_DEFAULT_TTL_SECONDS=3600
HFL_SHARE_DEFAULT_DEVICE_LIMIT=1
HFL_SHARE_PIN_MAX_ATTEMPTS=5
HFL_SHARE_PROVIDER=anthropic
HFL_SHARE_MODEL=claude-haiku-4-5-20251001
HFL_SHARE_HERMES_BASE_URL=http://127.0.0.1:8643/v1
HFL_SHARE_HERMES_API_KEY=<dedicated-server-side-bearer>
HFL_SHARE_HERMES_MODEL=share-corpus
HFL_SHARE_AGENT_TIMEOUT_SECONDS=90
HFL_SHARE_MAX_OUTPUT_TOKENS=1200
HFL_SHARE_MAX_CONTEXT_CHARS=120000
HFL_SHARE_MAX_SNAPSHOT_CHARS=10000000
HFL_SHARE_CHAT_LIMIT_PER_HOUR=30
HFL_SHARE_TRUST_PROXY_IDENTITY=false
```

`HFL_SHARE_PUBLIC_URL` must be HTTPS when `BEHIND_PROXY=true`. Use a dedicated
share signing key so rotating guest grants does not require rotating the owner
login session key. Back up the SQLite database with the same care as the HFL
corpus: snapshots contain the guest-visible corpus text and enabled reference
targets.

`HFL_SHARE_PROVIDER=anthropic` uses the existing configured Anthropic provider.
`HFL_SHARE_PROVIDER=hermes` uses the dedicated loopback OpenAI-compatible
Hermes endpoint. Provider failure never blocks snapshot browsing; Q&A returns a
generic temporary error without exposing endpoint, credential, or upstream
response details.

`HFL_SHARE_MAX_CONTEXT_CHARS` bounds the ranked entry excerpt sent for each
question, not the frozen snapshot itself. The 120,000-character default is
roughly 30,000 tokens before system instructions and conversation history.
Increasing it raises latency/quota use and can dilute relevance; whole-corpus
questions still need iterative retrieval rather than one unbounded prompt.

## Dedicated Hermes profile

Never point public Share Corpus Q&A at the normal Hermes profile. The standard
Hermes API server layers client instructions over its core agent and can expose
memory, skills, files, and terminal tools. HARQIS calls Hermes server-side over
loopback, but prompt injection still makes profile isolation mandatory.

Preview the setup first:

```bash
python scripts/setup_hfl_share_hermes.py
```

Apply the locked-down profile and HARQIS environment:

```bash
python scripts/setup_hfl_share_hermes.py --apply
python scripts/setup_hfl_share_hermes.py --login  # one-time, if requested
python scripts/setup_hfl_share_hermes.py --start
python scripts/setup_hfl_share_hermes.py --check
```

The script:

- creates a fresh `sharecorpus` profile with `--no-skills`; `--apply` refuses
  every existing profile rather than trusting or reusing unknown state;
- configures OpenAI Codex `gpt-5.6-sol`, with no fallback provider;
- disables long-term memory and user-profile injection;
- sets `platform_toolsets.api_server: []` and no messaging platforms;
- binds the API to literal `127.0.0.1:8643`, disables HTTP proxy inheritance,
  rejects redirects on authenticated checks, and leaves browser CORS unset;
- passes Hermes subprocesses only an allowlisted environment, excluding inherited
  messaging, webhook, proxy, CORS, and platform credentials;
- generates a dedicated API bearer and writes it only to private, gitignored
  Hermes/HARQIS environment files with mode `0600`;
- validates the full managed API environment, sensitive profile directories,
  owner-only credential/profile permissions, OAuth's explicit `logged in`
  status, and the exact `share-corpus` model alias;
- uses a profile-scoped `--login` action that also honors custom `--hermes-home`;
  and
- installs/restarts the isolated profile gateway only after OAuth is ready,
  then verifies `/v1/health`, the exact model alias, disabled live CORS, and an
  empty effective toolset through authenticated API discovery without proxies.

Follow-up commands printed after `--apply` preserve every custom profile, model,
port, context, Hermes-home, and HARQIS-environment argument.

Restart the HARQIS frontend after a successful `--start` so Pydantic reloads
`.env/apps.env`. Guest questions consume the connected Codex account's quota.
The backend assigns every inference a dedicated Hermes session ID and requests
session deletion immediately after the completion so supplied snapshot text is
not retained as normal profile history. Failed/interrupted runs remain isolated
inside this dedicated profile and should be handled as local operational data.
The integration is not an unlimited inference service; keep the durable per-share
rate limit and confirm that delegated guest use complies with the provider's
terms.

Rollback without deleting the isolated profile:

```env
HFL_SHARE_PROVIDER=anthropic
```

Then restart the HARQIS frontend. Stop the isolated gateway with
`hermes -p sharecorpus gateway stop` when it is no longer needed. Do not delete
or copy profile credentials as part of routine rollback.

## Cloudflare tunnel policy

Keep the origin bound to a private interface or firewall it so only the
tunnel can reach it. Do not trust identity headers from a directly reachable
origin.

Recommended path policies, evaluated most-specific first:

1. `/share/email/*`: Cloudflare Access email OTP policy for invited identities.
2. `/share/access/*`: public bypass; the application enforces PIN, manual, or
   capability verification.
3. `/share/session*`: public bypass; the application requires its signed,
   HTTP-only, same-site session cookie.
4. `/share/pending`: public bypass; the application requires its signed
   approval-request cookie.
5. `/*`: owner-only Cloudflare Access policy or deny-by-default policy.

### Cloudflare cache policy

In the zone dashboard, create a Cache Rule that marks only
`/static/*` as eligible for caching. The application emits content-versioned
URLs and `Cache-Control: public, max-age=31536000, immutable` for successful
static responses. Keep a higher-priority bypass rule for `/share/*`, login,
owner module pages, APIs, and all other dynamic paths. Dynamic application
responses emit `Cache-Control: no-store`; never enable Cache Everything for the
hostname.

Verify a static response reports `CF-Cache-Status: HIT` after a warm request,
while `/share/*` and authenticated module pages remain `DYNAMIC` or `BYPASS`.

Enable `HFL_SHARE_TRUST_PROXY_IDENTITY=true` only after the origin is locked
down and the `/share/email/*` policy supplies both
`Cf-Access-Authenticated-User-Email` and `Cf-Access-Jwt-Assertion`. Mixed PIN
and email shares work because email grants use the distinct `/share/email/`
path. The application requires the exact configured email and never accepts a
guest-supplied form value as identity.

Cloudflare being unavailable, the self-hosted server being offline, or the
tunnel stopping makes the share unavailable. No corpus snapshot is replicated
to a cloud service by this feature.

## Snapshot and agent boundary

Snapshot construction:

- requires at least one source;
- uses AND semantics for tags and topic terms;
- optionally limits dates and exact entry IDs;
- removes machine names, canonical entry IDs, reference blocks, and common
  local filesystem paths from guest text;
- drops plain `http://` references;
- resolves files through the same allowlisted-root and symlink containment
  checks as Activity Corpus downloads; and
- includes reference labels only when the owner enables reference sharing and
  checks each file in preview.

The Q&A system prompt treats corpus text as untrusted quoted data, escapes
prompt delimiters, limits context size, refuses unsupported questions, and
requires `[S#]` citations. Suggested prompts fill no authorization role and
cannot expand the snapshot.

## Audit behavior

Share creation, failed redemption, redemption, approval requests, revocation,
reference access, and successful guest Q&A are submitted through canonical HFL
persistence with source `sharing-audit`. Audit content is length-limited and
redacts token-like strings and common local paths. It does not record IP
addresses, browser fingerprints, cookies, PINs, capability tokens, or proxy
assertions.

Audit persistence is best effort so a temporary HFL/Elasticsearch failure does
not expose internal errors to a guest. Operators should monitor server warnings
for `sharing audit persistence failed`.

## Security risks and mitigations

| Risk | Mitigation | Residual concern |
|---|---|---|
| QR/link forwarding | 256-bit capability token, separate PIN default, one device, single use, short expiry | A recipient with both factors can use the share first. |
| Online PIN guessing | Capability token is also required; scrypt PIN hash; five failures per grant | A link holder can deliberately lock a grant. Revoke/regenerate. |
| Model-cost abuse | Durable per-share hourly chat limit and bounded model context | An authorized guest can consume the configured allowance. |
| Approval-request flooding | At most five live manual requests per share | A link holder can occupy the queue until requests expire or the share is revoked. |
| Snapshot oversharing | Source-first filters, explicit preview, warnings, fresh generation | Owners must review broad or sensitive sources before generation. |
| Corpus prompt injection | Escaped delimiters, untrusted-context instruction, no tools, snapshot-only prompt | Model behavior is probabilistic; do not share secrets in the snapshot. |
| Local file disclosure | Disabled by default, individual opt-in, allowed-root and symlink revalidation, no canonical guest labels | The SQLite snapshot necessarily retains enabled server targets. |
| Token leakage in logs/history | Tokens are HMAC-hashed at rest; referrer policy is `no-referrer`; guest responses are `no-store` | Tunnel/access logs and recipient browser history can contain the URL. Keep expiry short. |
| Cookie theft | HTTP-only, same-site, secure behind HTTPS, server-side session hash | A compromised guest browser can act until expiry or revocation. |
| Proxy-header spoofing | Trust disabled by default; dedicated Access path; locked-down origin required | Misconfigured origin exposure invalidates this boundary. |
| Revocation race | Session validation checks grant status on every request; revocation updates all sessions transactionally | A response already in flight may complete. |
| Availability | Local durable store; portal fails closed when host/tunnel is down | This is intentionally not a high-availability cloud service. |

## Recovery and operations

- Lost PIN: revoke the grant and generate another. PINs cannot be recovered.
- Wrong scope: revoke and generate from a corrected recipe.
- Lost capability link: revoke and generate another; plaintext tokens are not
  recoverable from SQLite.
- Suspected leak: revoke immediately, inspect `sharing-audit`, and rotate
  `HFL_SHARE_SECRET_KEY` if the signing boundary may be compromised. Rotating
  the key invalidates every guest and approval cookie and makes existing
  capability hashes unreachable.
- Database loss: active grants and recipes are lost; corpus data is unchanged.
- Recipe deletion: active and historical shares remain intact by design.

Before production use, test the public hostname from a non-VPN phone, confirm
that owner paths are denied, verify PIN and revocation behavior, verify guest
pages contain no canonical paths, and confirm the tunnel forwards HTTPS
identity headers only on the email path.
