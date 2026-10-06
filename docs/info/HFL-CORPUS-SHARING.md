# Activity Corpus Sharing

The access settings include **Maximum redemptions** beside Concurrent sessions.
It defaults to **5 per browser**, accepts 0 (unlimited) through 1000, and is saved
with the recipe and copied into generated grants. Resuming an active session
is free. The optional first-successful-session checkbox overrides this allowance;
it is unchecked by default. Anonymous QR, PIN, email OTP, and manual approval
shares all enforce the configured browser allowance when issuing a session.

A one-time migration gives existing shares and legacy recipes the
five-redemption default and removes their old global single-use restriction.
Explicit browser allowances are retained. Expiry, revocation, share URLs,
content, concurrent-session caps, and existing browser counts are preserved.
New instant QR shares retain their deliberately single-use behavior. Subsequent
startups do not overwrite saved limits, including an explicit unlimited value.

For enabled grants, a signed, HttpOnly browser cookie identifies the browser;
`browser_redemptions` stores counts by grant and hashed browser identifier.
Each successful new session increments the count in the same SQLite transaction
that enforces the limit. Failed attempts and active-session resumes do not count,
and logging out or expiring a session does not reset the allowance. Counts begin
when the setting is enabled; earlier anonymous sessions cannot be attributed.
The cookie lasts one year and is renewed on the access page. Clearing cookies,
using another browser, or letting the cookie expire starts a separate allowance;
this is not a verified per-person limit. An exhausted allowance blocks new
sessions without invalidating a session already in use.

Activity Corpus Sharing creates temporary, read-only guest portals without
joining a guest device to the HARQIS VPN or exposing the HARQIS topology. A QR
code is only a convenient encoding of a high-entropy capability link. It does
not install software, enroll a device, or grant network access.

Sharing reads the configured canonical corpus, including from a remote-reader
frontend. It never substitutes a stale local corpus when the canonical read fails.

## Lifecycle

1. The owner creates or loads a reusable recipe.
2. Sources are selected as the primary authorization boundary. Tags, dates,
   topic terms, and explicit entry IDs can narrow it further.
3. Preview recalculates current corpus matches and shows counts, date range,
   source/tag distribution, context size, warnings, entry summaries, and
   eligible references.
4. Owner preview chat uses only that transient preview and does not create a
   guest audit event.
5. Generate forces a fresh corpus read and stores the matches in a SQLite
   snapshot. Frozen shares retain that exact snapshot; live shares also retain
   a copy of the recipe and refresh their stored snapshot from current corpus
   matches when opened.
6. The owner receives a QR and pasteable capability link. PIN mode additionally
   displays a random eight-digit PIN once.
7. Successful redemption binds one server session to an HTTP-only signed
   cookie. Rescanning in that browser resumes the same session; closing it or
   reaching its fixed lifetime releases the slot. No browser fingerprint is
   collected.
8. A share may have no grant expiry while its individual sessions still
   expire. Grant expiry or owner revocation makes every associated session
   invalid immediately.

Editing or deleting a recipe never changes or revokes previously generated
shares. A live share refreshes from the recipe copy saved with the grant, not
from later edits to the reusable recipe. To change an active scope, revoke it
and generate a new share.

## Recipe, snapshot, and vector storage

The vector rows are not the authoritative store for linked entry information.
Sharing uses several layers in the SQLite database configured by
`HFL_SHARE_STORE_PATH`:

| Layer | SQLite storage | Contents | Role |
|---|---|---|---|
| Canonical corpus | Outside the share database | Original Markdown entries | Source of truth from which scopes are resolved. |
| Saved recipe | `configurations.payload` | JSON filters and settings: sources, tags, dates, topic, recipient, secret/reference choices, access mode, expiry, and device limits | Reusable instructions for selecting entries; it does not contain the matching entry text. |
| Generated grant | `shares` | Hashed capability/PIN data, lifecycle settings, and the stored snapshot | Controls guest access to one resolved share. |
| Share snapshot | `shares.snapshot` | JSON copies of each selected entry's sanitized text, citation, source, tags, document path/anchor, and allowed reference metadata | The actual guest-visible information. |
| Live recipe copy | `shares.live_configuration` | JSON copy of the generation-time recipe, only for live shares | Rebuilds the stored snapshot without depending on later saved-recipe edits. |
| Retrieval cache | `share_embeddings` | Share ID, entry ID, embedding model, content hash, dimensions, and a binary numeric vector | Accelerates semantic ranking; contains no readable entry text and can be regenerated. |
| Guest state | `sessions`, `chat_messages`, and related access tables | Hashed session secrets, access lifecycle, and bounded conversation history | Authenticates guests and preserves the conversation, independently of retrieval vectors. |

The snapshot is therefore the durable content boundary for a generated share.
Deleting a recipe does not delete an existing snapshot. Deleting embedding rows
also does not lose share content: the next question regenerates missing vectors
from the snapshot text.

The FastEmbed cache directory is different again. It contains downloaded local
embedding model files, not recipes, snapshots, corpus entries, or guest
questions. Share embeddings are also separate from the global Knowledge
workflow and its `apps/sqlite_vec` database.

### Resolution and question-answering flow

1. **Save recipe:** the owner form is validated and serialized into
   `configurations.payload`. No corpus entry text is copied at this stage.
2. **Preview:** the current corpus is read and the recipe's source, tag, date,
   topic, and secret rules are applied. Matching entries are sanitized and
   assembled into a transient `ScopeSnapshot`; preview does not create a guest
   grant.
3. **Generate:** the corpus is read again so generation cannot rely on a stale
   preview. The resolved `ScopeSnapshot` is serialized into `shares.snapshot`,
   and the capability token and optional PIN are hashed for verification.
   Newly generated non-instant shares also retain the capability link encrypted
   with a key derived from the sharing secret for owner-only QR/link retrieval.
4. **Browse:** guest pages read directly from the authorized stored snapshot.
   Browsing does not require vector retrieval and never opens arbitrary corpus
   documents.
5. **Ask a question:** the question is embedded locally. Snapshot entry vectors
   are loaded from `share_embeddings`; missing vectors or rows whose
   `content_hash` no longer matches the snapshot text are regenerated locally.
6. **Rank:** semantic similarity is combined with deterministic lexical scores.
   The configured top `HFL_SHARE_RETRIEVAL_K` entries are selected only from
   that share's snapshot.
7. **Answer:** Hermes receives the selected sanitized entries, their citations,
   bounded conversation history, and the question. It does not receive the
   whole corpus or use the global Knowledge index.

```text
Canonical Markdown corpus
          │ apply saved recipe
          ▼
Transient preview snapshot
          │ fresh read on Generate
          ▼
shares.snapshot (durable shared text)
          │ local embedding, on first question
          ▼
share_embeddings (regenerable numeric cache)
          │ hybrid semantic + lexical ranking
          ▼
Selected snapshot entries → Hermes answer with [S#] citations
```

For frozen shares, later corpus changes do not alter `shares.snapshot`. For live
shares, opening the grant rebuilds the snapshot from its stored
`live_configuration`. Stable entry citations are retained where possible, and
the content hashes ensure changed entry text receives a new vector before it is
used for semantic retrieval.

## Access modes

| Mode | Verification | Notes |
|---|---|---|
| QR + PIN | Capability token plus separately communicated eight-digit PIN | Default. Repeated failures are temporarily throttled in a rolling window. |
| Email OTP | Cloudflare Access identity header plus exact configured email | Requires the dedicated `/share/email/*` Access policy described below. |
| Manual approval | Capability token plus one owner-approved browser request | Guest waiting cookie is HTTP-only and expires after one hour. |
| QR possession | Capability token only | Suitable only for low-risk context; link possession is authorization. A no-expiry QR can issue bounded sessions as slots become free. |

The default grant lasts one hour, permits one concurrent session and five redemptions per browser, disables
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
HFL_SHARE_SESSION_TTL_SECONDS=21600
HFL_SHARE_MAX_CONCURRENT_SESSIONS=20
HFL_SHARE_CAPACITY_RETRY_SECONDS=300
HFL_SHARE_PIN_MAX_ATTEMPTS=5
HFL_SHARE_PIN_ATTEMPT_WINDOW_SECONDS=900
HFL_SHARE_MAX_GUEST_REQUEST_BYTES=16384
HFL_SHARE_MAX_QUESTION_CHARS=2000
HFL_SHARE_LIVE_REFRESH_SECONDS=300
HFL_SHARE_PROVIDER=hermes
HFL_SHARE_HERMES_BASE_URL=http://127.0.0.1:8643/v1
HFL_SHARE_HERMES_API_KEY=<dedicated-server-side-bearer>
HFL_SHARE_HERMES_MODEL=share-corpus
HFL_SHARE_AGENT_TIMEOUT_SECONDS=90
HFL_SHARE_MAX_OUTPUT_TOKENS=1200
HFL_SHARE_MAX_CONTEXT_CHARS=120000
HFL_SHARE_MAX_SNAPSHOT_CHARS=10000000
HFL_SHARE_CHAT_LIMIT_PER_HOUR=30
HFL_SHARE_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
HFL_SHARE_EMBEDDING_CACHE_DIR=/Users/harqis-one/.harqis-data/models/fastembed
HFL_SHARE_RETRIEVAL_K=8
HFL_SHARE_SEMANTIC_WEIGHT=0.75
HFL_SHARE_TRUST_PROXY_IDENTITY=false
```

The six-hour session and 20-session ceiling are operational defaults, not
hard-coded requirements. `HFL_SHARE_SESSION_TTL_SECONDS` accepts 300–86,400
seconds. `HFL_SHARE_MAX_CONCURRENT_SESSIONS` sets the highest value an owner
may select for a recipe and is safety-bounded to 1–20; each recipe may choose a
lower value. `HFL_SHARE_CAPACITY_RETRY_SECONDS` controls the public `Retry-After`
response when every slot is occupied and is bounded to 30–3,600 seconds.

For a reusable public QR, enable QR possession mode, disable grant expiry, and
set the recipe's concurrent-session count. The capability URL remains valid
until owner revocation, while each browser receives only the configured fixed
session lifetime. A rescan in the same browser resumes its existing session;
logout or expiry frees that durable slot for another browser. Increasing the
session ceiling increases concurrent request and model-cost exposure, so edge
rate limiting and monitoring remain necessary.

The remaining public-input controls are also configurable:
`HFL_SHARE_PIN_ATTEMPT_WINDOW_SECONDS` is the rolling failed-PIN window,
`HFL_SHARE_MAX_GUEST_REQUEST_BYTES` bounds public form bodies,
`HFL_SHARE_MAX_QUESTION_CHARS` bounds questions, and
`HFL_SHARE_LIVE_REFRESH_SECONDS` limits how often live grants rebuild their
snapshot.

`HFL_SHARE_PUBLIC_URL` must be HTTPS when `BEHIND_PROXY=true`. Use a dedicated
share signing key so rotating guest grants does not require rotating the owner
login session key. Back up the SQLite database with the same care as the HFL
corpus: snapshots contain the guest-visible corpus text and enabled reference
targets.

Only `HFL_SHARE_PROVIDER=hermes` is accepted. It uses the dedicated loopback
OpenAI-compatible Hermes endpoint; the frontend never calls a generation
provider directly. Hermes can still use the model provider configured inside
its isolated profile, which is a separate disclosure boundary. Provider
failure never blocks snapshot browsing; Q&A returns a generic temporary error
without exposing endpoint, credential, or upstream response details.

Share retrieval is local and isolated from the global Knowledge index. On the
first question, FastEmbed creates vectors only for entries in the immutable
share snapshot and stores them in the share SQLite database. Existing shares
index lazily. Later questions reuse those vectors, hybrid-ranked with lexical
signals; the default sends the best eight entries to Hermes. If FastEmbed or
its model cache is unavailable, Q&A falls back to bounded lexical retrieval.
The model files may be downloaded on first use, but snapshot text and visitor
questions are never sent to an embedding API.

`HFL_SHARE_MAX_CONTEXT_CHARS` bounds the ranked entry excerpt sent for each
question, not the frozen snapshot itself. The 120,000-character default is
roughly 30,000 tokens before system instructions and conversation history.
Increasing it raises latency/quota use and can dilute relevance; whole-corpus
questions still need iterative retrieval rather than one unbounded prompt.

## Dedicated Hermes profile

Never point public Share Activity Q&A at the normal Hermes profile. The standard
Hermes API server layers client instructions over its core agent and can expose
memory, skills, files, and terminal tools. HARQIS calls Hermes server-side over
loopback, but prompt injection still makes profile isolation mandatory.

Preview the setup first:

```bash
python scripts/agents/hfl/setup_hfl_share_hermes.py
```

Apply the locked-down profile and HARQIS environment:

```bash
python scripts/agents/hfl/setup_hfl_share_hermes.py --apply
python scripts/agents/hfl/setup_hfl_share_hermes.py --login  # one-time, if requested
python scripts/agents/hfl/setup_hfl_share_hermes.py --start
python scripts/agents/hfl/setup_hfl_share_hermes.py --check
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

To disable Q&A without deleting the isolated profile, stop the isolated gateway
with `hermes -p sharecorpus gateway stop`. Snapshot browsing remains available
and questions fail with the generic temporary-unavailable response. Do not set
an alternate provider: the sharing boundary intentionally accepts only
`HFL_SHARE_PROVIDER=hermes`. Do not delete or copy profile credentials as part
of routine rollback.

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
| QR/link forwarding | 256-bit capability token, separate PIN default, configurable concurrent-session ceiling, fixed session lifetime, optional grant expiry | Anyone holding a QR-possession link can claim a free session slot until the owner revokes it. |
| Online PIN guessing | Capability token is also required; scrypt PIN hash; rolling failed-attempt throttle | Distributed attempts still require edge rate limiting and monitoring. |
| Model-cost abuse | Durable per-share hourly chat limit and bounded model context | An authorized guest can consume the configured allowance. |
| Oversized public input | 16 KiB public POST body cap plus exact capability/PIN formats, 2,000-character questions, and 500-character searches enforced server-side before expensive hashing, persistence, retrieval, or snapshot scans | The edge should still cap request-line size and connection rates. |
| Approval-request flooding | At most five live manual requests per share | A link holder can occupy the queue until requests expire or the share is revoked. |
| Snapshot oversharing | Source-first filters, explicit preview, warnings, fresh generation | Owners must review broad or sensitive sources before generation. |
| Corpus prompt injection | Escaped delimiters, untrusted-context instruction, no tools, snapshot-only prompt | Model behavior is probabilistic; do not share secrets in the snapshot. |
| Local file disclosure | Disabled by default, individual opt-in, allowed-root and symlink revalidation, no canonical guest labels | The SQLite snapshot necessarily retains enabled server targets. |
| Token leakage in logs/history | Tokens are HMAC-hashed for verification; new non-instant share links are also encrypted at rest; referrer policy is `no-referrer`; guest responses are `no-store` | Tunnel/access logs and recipient browser history can contain the URL. Keep expiry short. |
| Cookie theft | HTTP-only, same-site, secure behind HTTPS, server-side session hash | A compromised guest browser can act until expiry or revocation. |
| Proxy-header spoofing | Trust disabled by default; dedicated Access path; locked-down origin required | Misconfigured origin exposure invalidates this boundary. |
| Revocation race | Session validation checks grant status on every request; revocation updates all sessions transactionally | A response already in flight may complete. |
| Guest-cookie replay after logout | Closing a guest session revokes that exact durable session before clearing the browser cookie | A response already in flight may complete. |
| Capability-origin poisoning | Proxied deployments require an explicit HTTPS `HFL_SHARE_PUBLIC_URL`; credentials, paths, queries, and fragments are rejected | Non-proxied local development may derive the request origin. |
| Availability | Local durable store; portal fails closed when host/tunnel is down | This is intentionally not a high-availability cloud service. |

FastAPI interactive documentation and the OpenAPI schema are disabled on this
operator-facing deployment (`/docs`, `/redoc`, and `/openapi.json` return 404)
to avoid publishing a reconnaissance map of owner and guest routes.

## Recovery and operations

- Lost PIN: revoke the grant and generate another. PINs cannot be recovered.
- Wrong scope: revoke and generate from a corrected recipe.
- Lost capability link: use **QR & link** on a newly generated active share.
  Older shares and instant shares have no retained link; generate a new share
  when their original link is lost. PINs are never retained for recovery.
- Expired/revoked shares remain previewable by the authenticated owner using
  their last saved snapshot; guest access remains blocked.
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


## Workspace context sharing

The owner editor is named **Share Activity**, under Express. It contains:

- **Recipe:** recipient/name, verification, expiry, freezing, and live inclusion policies.
- **Filters:** sources, tags, topic, dates and inherited combined-view rules. The
  explicit Replace workspace filters control removes inherited rules/membership.
- **Entries:** full entry previews, entry exclusions, references and Include secrets.
- **Actions & Ideas:** active-object selection, optional completed/dismissed items,
  descriptions/checklists and the read-only Connections graph.
- **Boards:** board selection, draft thoughts, saved positions, member graphs and
  mapped goals; outside-workspace membership requires explicit per-board opt-in.
- **Graph:** the activity graph derived from approved objects and entry entities.

Corpus, Graph and Kanban workspace handoffs preselect eligible sections and retain
workspace IDs. Current unsaved filter controls are transferred; rolling dates are
resolved once. Search text remains excluded. Source/date/tag filters select entries
and inherited intents; explicitly assigned workspace actions/ideas remain eligible
without an entry. Board eligibility follows workspace membership. Completed actions
and dismissed ideas are excluded unless requested. Individual exclusions are durable.
Board selection also authorizes its displayed eligible members; object exclusions
still win over board membership. Goals include details/milestones but never recurse
through their other linked objects. Shares need at least one entry or object.

### Snapshot and refresh behavior

Legacy recipes/grants default to entries-only; no existing share gains objects on
upgrade. Versioned `activity` recipe controls and `activity`/`activity_entries`
snapshot fields are additive JSON data in the existing SQLite store.

Freeze captures the complete mixed snapshot. A live grant stores its own recipe
copy and approved IDs. Each of Entries, Actions, Ideas and Boards can admit newly
matching objects independently; otherwise only originally approved IDs refresh.
Approved-only boards also pin their member IDs. Explicit exclusions always win.
An object that is deleted, protected or no longer eligible disappears on successful
refresh. A successful refresh may produce an empty share. Failed reads retain the
last successful snapshot and display a refresh-failure notice. Changes to a saved
recipe do not change previously generated shares.

Reference selection applies to entry references, object HTTPS links and immutable
input attachments. Attachments download through the existing authenticated share
session using opaque reference IDs; canonical paths and bearer tokens are not sent
to guests. Remote attachment bytes are checked against their captured digest.
New references in live refreshes remain disabled. Object text suppresses embedded
URLs and local paths; enabled links are exposed through reference controls.

The existing QR, PIN, email OTP, owner-approval, expiry, revocation, session and
browser-redemption controls remain in force. Public graphs support inspection,
pan and zoom without mutation controls. Object details join the existing evidence
drawer. The sharing assistant retrieves entries and object evidence together,
validates citations against that snapshot, and has no action tools.

### Secrets and canonical API compatibility

Include secrets is recipe-wide, off by default, and requires the existing owner
Activity Corpus PIN before preview/testing/generation. Live grants retain the
explicitly approved secret policy; the recipient never unlocks owner data directly.
All object source/evidence references must resolve against permitted corpus entries.
Graphs are rebuilt from approved objects; excluded nodes, labels, locators, paths,
unrelated edges and global counts are not copied from owner graphs.

The canonical API adds `GET /api/hfl/timeline/ideas/share-context`. It requires the
service bearer credential and returns input for server-side publication filtering.
It also provides a bearer-only attachment endpoint beneath
`/api/hfl/timeline/ideas/share-context/attachments/{kind}/{source_id}/{attachment_id}`.
The corresponding browser routes are explicitly forbidden, including owner-session
proxy requests. This endpoint is not a guest API and does not itself grant sharing.

A remote canonical host on an older version falls back to the existing permission-
filtered ideas snapshot for ordinary local testing. **Secret-backed workspace
objects require the canonical host update.** Attempting mixed secret sharing against
an older host gives an actionable error rather than silently omitting objects.
Entries-only secret sharing continues through its existing API. Deploying only a
remote-reader frontend does not upgrade the canonical API.

### Local acceptance checks

1. Generate an unsaved recipe from each workspace entry point; verify selection and
   combined-view filters, then test replacing inherited scope.
2. Exclude an action; verify it disappears from objects, boards, graphs and assistant
   context. Restore it and verify the preview updates.
3. Compare a board with outside-workspace inclusion off/on; verify its goal never
   brings in another board. Verify draft thoughts, lists and saved positions.
4. Toggle secrets while locked; require PIN, then check protected content across
   previews and generated pages on an updated canonical host.
5. Generate frozen and hybrid live shares; change approved objects, add matching
   objects, remove eligible objects, and verify per-section policies and exclusions.
6. Redeem QR access and inspect public object evidence, graphs and citations. Verify
   expiration/revocation still block all content and attachment access.
7. Repeat the editor and public view at desktop and mobile widths.

Focused regression: `frontend/tests/test_workspace_sharing.py`,
`frontend/tests/test_hfl_shares.py`, and `frontend/tests/test_corpus_share_handoff.py`.


For older local sharing databases, startup adds legacy columns before creating the
owner-list index. Existing recipes and grants are retained. A Windows remote-reader
installation must override `HFL_SHARE_STORE_PATH` in its machine-local configuration
if the shared environment contains a canonical host filesystem path. Local owner
Preview uses the local grant; QR links continue to use `HFL_SHARE_PUBLIC_URL`, so a
frontend-only test deployment does not move the public sharing origin.
