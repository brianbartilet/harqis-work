# apps/clerk

Minimal Clerk integration: verify JWTs issued by Clerk against the
publishable JWKS endpoint. Used by `frontend/auth.py` for the multi-tenant
auth path; the legacy username/password path keeps working unchanged.

## Why Clerk

Multi-tenant AaaS MVP needs email + magic-link + SSO + org support without
us building it. Clerk's free tier covers <10k MAU and ships a drop-in
`<SignIn />` widget — we get from zero to "someone can sign up" in roughly
50 lines of integration code.

When/if the cost or vendor-lock-in becomes a problem, this module is the
only thing to swap out: `verify_jwt()` is the only function the rest of
the codebase calls. Vault / Auth0 / Supabase migrations replace this file
and leave `tenant/` untouched.

## Env

| Var                       | Required | Notes                                              |
|---------------------------|----------|----------------------------------------------------|
| `CLERK_PUBLISHABLE_KEY`   | yes      | Used to derive the JWKS URL                        |
| `CLERK_JWKS_URL`          | no       | Overrides the derived URL                          |
| `CLERK_AUDIENCE`          | no       | Optional aud claim check                           |
| `CLERK_SECRET_KEY`        | no       | Reserved for webhook validation (follow-up PR)     |

## Usage

```python
from apps.clerk.references.jwt_verify import verify_jwt, ClerkAuthError

try:
    claims = verify_jwt(bearer_token)
except ClerkAuthError as exc:
    return 401, str(exc)

user_id  = claims["sub"]
org_id   = claims.get("org_id")
email    = claims.get("email")
```

JWKS is cached in-process for 60 minutes; rotate keys by waiting out the
cache or restarting the process.
