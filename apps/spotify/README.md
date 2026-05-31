# Spotify

Read-only integration with the [Spotify Web API](https://developer.spotify.com/documentation/web-api)
for a single personal account. Built to back the HFL `ingest_spotify_activity`
source (daily listening → one Homework-for-Life beat), but the services and
MCP tools are usable standalone.

**Auth:** OAuth2 Authorization Code with a refresh token. Spotify access
tokens expire in ~1 hour, so the base service exchanges the long-lived
`refresh_token` for a fresh access token on every construction
(`POST https://accounts.spotify.com/api/token`, `grant_type=refresh_token`,
HTTP Basic client credentials). Scopes required: `user-read-recently-played`,
`user-top-read`.

## Supported Automations

- [x] webservices
- [ ] browser
- [ ] desktop
- [ ] mobile
- [ ] iot

## Directory Structure

```
apps/spotify/
├── config.py                       # APP_NAME + CONFIG (centralized loader)
├── mcp.py                          # MCP tools
├── references/
│   ├── constants.py                # token URL, time_range values, caps
│   ├── dto/
│   │   └── track.py                # DtoSpotifyArtist / Track / PlayHistory
│   └── web/
│       ├── base_api_service.py     # OAuth2 refresh-token exchange + Bearer
│       └── api/
│           ├── player.py           # recently-played, currently-playing
│           └── personalization.py  # top tracks, top artists
└── tests/
    ├── test_player.py
    └── test_personalization.py
```

## Configuration

`apps_config.yaml`:

```yaml
SPOTIFY:
  app_id: 'spotify_account_main'
  client: 'rest'
  parameters:
    base_url: 'https://api.spotify.com/v1/'
    response_encoding: 'utf-8'
    verify: True
    timeout: 60
    stream: False
  app_data:
    client_id: ${SPOTIFY_CLIENT_ID}
    client_secret: ${SPOTIFY_CLIENT_SECRET}
    refresh_token: ${SPOTIFY_REFRESH_TOKEN}
  return_data_only: True
```

Env vars (`.env/apps.env`):

```
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
SPOTIFY_REFRESH_TOKEN=
```

### One-time refresh-token handshake

`refresh_token` is minted once, out of band:

1. Create an app at the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
   to get the `client_id` / `client_secret`. Under **Settings → Redirect URIs**,
   add this **exact** loopback URI and save:
   ```
   http://127.0.0.1:8888/callback
   ```
   Spotify requires the explicit IP `127.0.0.1` — `localhost` is rejected, and
   non-loopback URIs must be HTTPS.
2. Put `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` in `.env/apps.env`.
3. Run the helper once (it opens the browser, captures the redirect, and
   prints the token):
   ```
   python apps/spotify/mint_token.py
   ```
   Paste the printed `SPOTIFY_REFRESH_TOKEN=…` line into `.env/apps.env`. The
   refresh token is long-lived; the service refreshes the short-lived access
   token from it automatically.

**Manual fallback** (if you'd rather not run the script): authorize at
`https://accounts.spotify.com/authorize?response_type=code&client_id=<ID>&scope=user-read-recently-played%20user-top-read&redirect_uri=http://127.0.0.1:8888/callback`,
copy the `code` from the redirected URL bar, then `POST https://accounts.spotify.com/api/token`
with `grant_type=authorization_code&code=<CODE>&redirect_uri=<REDIRECT>` and
HTTP Basic client auth. The response's `refresh_token` is the value you want.

## Available Services

| Service class | Method | Description |
|---|---|---|
| `ApiServiceSpotifyPlayer` | `get_recently_played(limit, after_ms)` | Last ≤50 plays, newest first, with `played_at` |
| | `get_currently_playing()` | Track playing now, or `{}` |
| `ApiServiceSpotifyPersonalization` | `get_top_tracks(time_range, limit)` | Top tracks over short/medium/long_term |
| | `get_top_artists(time_range, limit)` | Top artists over short/medium/long_term |

## MCP Tools

| Tool | Args | Description |
|---|---|---|
| `spotify_recently_played` | `limit` | List recent plays (newest first, ≤50) |
| `spotify_currently_playing` | — | Track playing now, or `{}` |
| `spotify_top_tracks` | `time_range`, `limit` | Top tracks over a rolling window |
| `spotify_top_artists` | `time_range`, `limit` | Top artists over a rolling window |

## Tests

Live integration tests (no mocking). Require a configured `SPOTIFY` block
with valid credentials:

```
pytest apps/spotify/tests/ -m smoke
```

## Notes

- **recently-played caps at 50 items** and is a time-cursor endpoint — there
  is no full-day history call. For a once-a-day digest this is fine; the
  `top_tracks` / `top_artists` calls cover the "what defined the period"
  layer independent of the cap.
- **No audio-features.** Spotify deprecated `audio-features` /
  `audio-analysis` (valence, energy, etc.) for newly created apps in
  Nov 2024, so a computed "mood" signal is not available — mood is inferred
  downstream from track/artist/genre names.
- `played_at` is UTC; map to local day before bucketing into an HFL entry.
- Access tokens expire in ~1h. Reuse a service instance across calls within
  that window rather than reconstructing it (each construction refreshes).
- Rate limits are per-app rolling-window; the daily ingest's call volume is
  negligible against them.
