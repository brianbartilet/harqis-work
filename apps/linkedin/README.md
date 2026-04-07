# LinkedIn Integration (`apps/linkedin`)

LinkedIn REST API v2 integration for profile reading and posting.

References:
- [Authentication Guide](https://learn.microsoft.com/en-gb/linkedin/shared/authentication/getting-access)
- [API Guide](https://learn.microsoft.com/en-gb/linkedin/shared/api-guide/concepts?context=linkedin/context)
- [Developer Portal](https://www.linkedin.com/developers/apps)

---

## Setup

### 1. Create a LinkedIn App

1. Go to [https://www.linkedin.com/developers/apps](https://www.linkedin.com/developers/apps)
2. Click **"Create app"** — a LinkedIn Company Page is required
3. Fill in app name, LinkedIn Page, and app logo
4. Go to the **Products** tab and request access to:
   - **Sign In with LinkedIn using OpenID Connect** — grants `openid`, `profile`, `email` scopes
   - **Share on LinkedIn** — grants `w_member_social` scope

   Both products are approved instantly for self-serve. After adding them, confirm the scopes appear under **Auth → OAuth 2.0 scopes**.

5. Under **Auth → OAuth 2.0 settings**, add your redirect URI (e.g. `http://localhost:8099`)

---

### 2. OAuth2 Authorization Code Flow

LinkedIn does not support password grant. You must obtain a token via browser redirect. Do this once — the token is valid for **60 days**.

#### Step 1 — Start a local listener to capture the redirect

```sh
python -c "
from http.server import HTTPServer, BaseHTTPRequestHandler
print('Waiting on :8099...')
HTTPServer(('', 8099), type('H', (BaseHTTPRequestHandler,), {
    'do_GET': lambda s: (
        print('Redirect URL:', s.path),
        s.send_response(200), s.end_headers(),
        s.wfile.write(b'Got it! Check terminal.')
    )
})).handle_request()
"
```

#### Step 2 — Open the authorization URL in your browser

```
https://www.linkedin.com/oauth/v2/authorization?response_type=code&client_id={your_client_id}&redirect_uri=http://localhost:8099&scope=openid%20profile%20email%20w_member_social&state=abc123
```

Approve the LinkedIn consent screen. The terminal prints the redirect URL — copy the `code` value from it:
```
Redirect URL: /?code=AQRXGlRc61Gn...&state=abc123
```

> Authorization codes expire in **30 minutes** and are **single-use**. Exchange immediately.

#### Step 3 — Exchange the code for an access token

The client secret may contain `=` characters — use `--data-urlencode` to avoid encoding issues:

```sh
curl -X POST https://www.linkedin.com/oauth/v2/accessToken \
  --data-urlencode "grant_type=authorization_code" \
  --data-urlencode "code={code_from_step_2}" \
  --data-urlencode "client_id={your_client_id}" \
  --data-urlencode "client_secret={your_client_secret}" \
  --data-urlencode "redirect_uri=http://localhost:8099"
```

Successful response:
```json
{
  "access_token": "AQXVPLm...",
  "expires_in": 5183999,
  "scope": "email,openid,profile,w_member_social",
  "token_type": "Bearer"
}
```

Copy `access_token` → `LINKEDIN_ACCESS_TOKEN` in `.env/apps.env`.

> **Token validity: 60 days** (`expires_in` ≈ 5,183,999 seconds). There is no automatic refresh for self-serve apps. When the token expires, repeat steps 1–3 to obtain a new one.

#### Step 4 — Get your person ID

The `sub` field from the OpenID Connect userinfo endpoint is your person ID — needed for post authorship:

```sh
curl -H "Authorization: Bearer {access_token}" \
     -H "X-Restli-Protocol-Version: 2.0.0" \
     https://api.linkedin.com/v2/userinfo
```

Response includes `sub` (e.g. `BYMJHytmYr`) — copy it to `LINKEDIN_PERSON_ID`.

#### Step 5 — (Optional) Get a post URN for testing

To configure `LINKEDIN_DEFAULT_POST_URN`, find any post URL on your LinkedIn profile:
```
https://www.linkedin.com/posts/username_...-activity-7442954012154523651-NbRb
```
The numeric ID after `activity-` is the post ID. The URN is:
```
urn:li:ugcPost:7442954012154523651
```

> Reading posts back via the API (`GET /v2/ugcPosts`) requires LinkedIn Partner Program access — not available for self-serve. The URN is only used if Partner access is granted.

---

### 3. Environment Variables

Add to `.env/apps.env`:

```env
# LINKEDIN
LINKEDIN_CLIENT_ID=your_client_id
LINKEDIN_CLIENT_SECRET=your_client_secret
LINKEDIN_ACCESS_TOKEN=your_access_token        # valid 60 days — re-authorize when expired
LINKEDIN_REDIRECT_URI=http://localhost:8099
LINKEDIN_PERSON_ID=your_sub_from_userinfo      # e.g. BYMJHytmYr
LINKEDIN_DEFAULT_POST_URN=                     # optional — urn:li:ugcPost:{id}
```

### 4. Config (`apps_config.yaml`)

```yaml
LINKEDIN:
  app_id: 'linkedin'
  client: 'rest'
  parameters:
    base_url: 'https://api.linkedin.com/v2/'
    response_encoding: 'utf-8'
    verify: True
    timeout: 30
    stream: False
  app_data:
    client_id: ${LINKEDIN_CLIENT_ID}
    client_secret: ${LINKEDIN_CLIENT_SECRET}
    access_token: ${LINKEDIN_ACCESS_TOKEN}
    redirect_uri: ${LINKEDIN_REDIRECT_URI}
    person_id: ${LINKEDIN_PERSON_ID}
    default_post_urn: ${LINKEDIN_DEFAULT_POST_URN}
  return_data_only: True
```

---

## API Services

### `ApiServiceLinkedInProfile`

Requires scopes: `openid`, `profile`, `email`

| Method | Description | Self-serve |
|--------|-------------|-----------|
| `get_me()` | Authenticated member's profile via OpenID Connect (`/v2/userinfo`) | Yes |
| `get_email()` | Same as `get_me()` — email is included in the userinfo response | Yes |
| `get_profile(person_id)` | Any member's profile by person ID (`/v2/people`) | No — Partner only |

### `ApiServiceLinkedInPosts`

Requires scope: `w_member_social`

| Method | Description | Self-serve |
|--------|-------------|-----------|
| `create_post(text, visibility, article_url, ...)` | Publish a text or article post | Yes |
| `get_post(post_urn)` | Retrieve a post by URN | No — Partner only |
| `delete_post(post_urn)` | Delete your own post | Yes |

---

## Tests

```sh
# Run all LinkedIn tests
pytest apps/linkedin/tests/ -v

# Smoke tests only (auth + connectivity)
pytest apps/linkedin/tests/ -m smoke -v

# Sanity tests
pytest apps/linkedin/tests/ -m sanity -v
```

Tests are live integration tests — requires valid credentials in `.env/apps.env`.

Tests that call Partner-only endpoints (`get_profile`, `get_post`) skip automatically with a descriptive message rather than failing.

---

## MCP Tools

| Tool | Description |
|------|-------------|
| `get_linkedin_me` | Get authenticated member's profile (name, email, photo) |
| `get_linkedin_email` | Get authenticated member's email address |
| `get_linkedin_profile` | Get any member's profile by person ID (Partner only) |
| `create_linkedin_post` | Publish a text or article post |
| `get_linkedin_post` | Retrieve a post by URN (Partner only) |
| `delete_linkedin_post` | Delete your own post |

---

## Notes

- **Token expiry**: Access tokens are valid for **60 days**. No silent refresh is available for self-serve apps — re-run the OAuth flow (steps 1–3) when expired.
- **URN format**: LinkedIn identifiers use `urn:li:person:{id}`, `urn:li:ugcPost:{id}`, etc. When URNs appear in URL paths they are percent-encoded (`urn%3Ali%3AugcPost%3A123`).
- **Post ID from URL**: Extract from LinkedIn post URLs — the numeric value after `activity-` in the URL is the post ID.
- **Post creation response**: `create_post` returns an empty body (HTTP 201). The new post's URN is in the `X-RestLi-Id` response header.
- **Rate limits**: 150 posts/day per member, 100,000/day per application. Exceeding returns HTTP 429.
- **Partner-only endpoints**: Reading posts (`GET /v2/ugcPosts`), reading other members' profiles (`GET /v2/people`), and messaging (InMail) all require LinkedIn Partner Program access — not available for self-serve apps.
