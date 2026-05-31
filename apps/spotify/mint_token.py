"""
apps/spotify/mint_token.py

One-time helper to mint SPOTIFY_REFRESH_TOKEN for the Spotify ingest source.

Run it ONCE, interactively, on a machine with a browser:

    python apps/spotify/mint_token.py

It reads SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET from .env/apps.env, opens
the Spotify authorize page in your browser, captures the redirect on a
throwaway local listener (127.0.0.1:8888), exchanges the code for tokens, and
prints the long-lived refresh token for you to paste into .env/apps.env:

    SPOTIFY_REFRESH_TOKEN=<printed value>

Scopes requested: user-read-recently-played, user-top-read.

Prerequisites (see apps/spotify/README.md):
  - A Spotify app at https://developer.spotify.com/dashboard
  - Its Redirect URIs MUST include the loopback URI below EXACTLY:
        http://127.0.0.1:8888/callback
    (Spotify requires the explicit IP 127.0.0.1 — "localhost" is rejected.)

Nothing is written to disk and no secrets are logged beyond the final token
print to your own terminal. The local listener shuts down as soon as the
redirect is received.
"""

from __future__ import annotations

import base64
import os
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env" / "apps.env"

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
SCOPES = "user-read-recently-played user-top-read"
DEFAULT_REDIRECT = "http://127.0.0.1:8888/callback"


def _load_credentials() -> tuple[str, str, str]:
    """Resolve (client_id, client_secret, redirect_uri) from .env/apps.env.

    Prefers python-dotenv (no os.environ mutation); falls back to a tiny
    line parser, then to anything already exported in the environment.
    """
    values: dict[str, str] = {}
    try:
        from dotenv import dotenv_values
        if ENV_FILE.exists():
            values = {k: v for k, v in dotenv_values(ENV_FILE).items() if v is not None}
    except Exception:
        if ENV_FILE.exists():
            for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                values[key.strip()] = val.strip()

    def pick(name: str, default: str = "") -> str:
        return (values.get(name) or os.environ.get(name) or default).strip()

    client_id = pick("SPOTIFY_CLIENT_ID")
    client_secret = pick("SPOTIFY_CLIENT_SECRET")
    redirect_uri = pick("SPOTIFY_REDIRECT_URI", DEFAULT_REDIRECT)

    missing = [n for n, v in (("SPOTIFY_CLIENT_ID", client_id),
                              ("SPOTIFY_CLIENT_SECRET", client_secret)) if not v]
    if missing:
        sys.exit(
            f"Missing {', '.join(missing)} in {ENV_FILE}.\n"
            "Set them from your Spotify app (https://developer.spotify.com/dashboard) "
            "and re-run."
        )
    return client_id, client_secret, redirect_uri


class _CallbackHandler(BaseHTTPRequestHandler):
    # Filled in by the server loop once a request lands.
    result: dict = {}

    def do_GET(self):  # noqa: N802 - stdlib signature
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != urllib.parse.urlparse(self.server.redirect_uri).path:
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(parsed.query)
        _CallbackHandler.result = {k: v[0] for k, v in params.items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        ok = "code" in _CallbackHandler.result
        body = (
            "<h2>Spotify authorization received ✅</h2>"
            "<p>You can close this tab and return to the terminal.</p>"
            if ok else
            f"<h2>Authorization failed ❌</h2><pre>{_CallbackHandler.result}</pre>"
        )
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, *args):  # silence the default stderr access log
        pass


def _capture_code(redirect_uri: str, authorize_url: str) -> str:
    parsed = urllib.parse.urlparse(redirect_uri)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8888

    try:
        server = HTTPServer((host, port), _CallbackHandler)
    except OSError as exc:
        sys.exit(
            f"Could not bind {host}:{port} ({exc}). Close whatever is using the "
            f"port, or set SPOTIFY_REDIRECT_URI to a free loopback port (and add "
            f"that exact URI to your Spotify app's Redirect URIs)."
        )
    server.redirect_uri = redirect_uri  # type: ignore[attr-defined]

    print(f"Listening on {host}:{port} for the Spotify redirect…")
    print("Opening the authorize page in your browser. If it doesn't open, "
          "paste this URL manually:\n")
    print(f"  {authorize_url}\n")
    webbrowser.open(authorize_url)

    # Serve exactly one request (the redirect), then stop.
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    while not _CallbackHandler.result:
        t.join(timeout=0.5)
    server.shutdown()

    result = _CallbackHandler.result
    if "error" in result:
        sys.exit(f"Spotify returned an error: {result['error']}")
    code = result.get("code")
    if not code:
        sys.exit(f"No authorization code in the redirect: {result}")
    return code


def _exchange_code(code: str, client_id: str, client_secret: str,
                   redirect_uri: str) -> dict:
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=30.0,
    )
    if resp.status_code != 200:
        sys.exit(f"Token exchange failed (HTTP {resp.status_code}): {resp.text}")
    return resp.json()


def main() -> None:
    client_id, client_secret, redirect_uri = _load_credentials()

    authorize_url = AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "scope": SCOPES,
        "redirect_uri": redirect_uri,
        "show_dialog": "true",
    })

    code = _capture_code(redirect_uri, authorize_url)
    tokens = _exchange_code(code, client_id, client_secret, redirect_uri)

    refresh = tokens.get("refresh_token")
    if not refresh:
        sys.exit(f"No refresh_token in the response: {tokens}")

    print("\n" + "=" * 70)
    print("SUCCESS — paste this into .env/apps.env:\n")
    print(f"SPOTIFY_REFRESH_TOKEN={refresh}")
    print("=" * 70)
    print(f"\n(access token good for ~{tokens.get('expires_in', 3600)}s; the "
          "service refreshes it automatically from the refresh token above.)")


if __name__ == "__main__":
    main()
