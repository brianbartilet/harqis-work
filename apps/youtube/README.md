# YouTube

## Description

- Integrates the [YouTube Data API v3](https://developers.google.com/youtube/v3/docs) and [YouTube Analytics API v2](https://developers.google.com/youtube/analytics) for read-only channel operations and targeted YouTube Studio-style analytics.
- Uses Google OAuth 2.0 with the existing HARQIS `credentials.json` flow and a dedicated `storage-youtube.json` token file.
- Bulk YouTube Reporting API jobs and write operations are intentionally outside the first version.

## Supported Automations

- [x] webservices — Google discovery API calls
- [ ] browser — Selenium page automation
- [ ] desktop — Local Windows automation
- [ ] mobile — Android/iOS automation
- [ ] internet of things — MQTT / hardware integration

## Directory Structure

```
apps/youtube/
├── config.py
├── mcp.py
├── references/
│   ├── dto/
│   │   ├── analytics.py
│   │   ├── channel.py
│   │   ├── playlist.py
│   │   └── video.py
│   └── web/
│       ├── base_api_service.py
│       └── api/
│           ├── analytics.py
│           └── data.py
└── tests/
    ├── test_analytics.py
    └── test_data.py
```

## Configuration

Enable **YouTube Data API v3** and **YouTube Analytics API** for the Google Cloud project associated with `.env/credentials.json`.

Add this section to `apps_config.yaml`:

```yaml
YOUTUBE:
  app_id: 'youtube'
  client: 'rest'
  parameters:
    base_url: 'https://www.googleapis.com/'
    response_encoding: 'utf-8'
    verify: True
    timeout: 60
    stream: False
  app_data:
    api_key: ${GOOGLE_APPS_API_KEY}
    scopes:
      - "https://www.googleapis.com/auth/youtube.readonly"
      - "https://www.googleapis.com/auth/yt-analytics.readonly"
    credentials: "credentials.json"
    storage: "storage-youtube.json"
  return_data_only: True
```

The shared readiness signal must exist in `.env/apps.env`:

```env
GOOGLE_APPS_API_KEY=
```

The API calls use OAuth rather than the key. On first authorization, set `GOOGLE_ALLOW_INTERACTIVE_AUTH=1` outside pytest and instantiate either service so Google can create `.env/storage-youtube.json`. YouTube does not support service-account authentication for channel access.

## Available Services

| Service | Method | Description |
|---|---|---|
| `ApiServiceYouTubeData` | `get_my_channel` | Get the authenticated channel and headline statistics |
| `ApiServiceYouTubeData` | `get_channel` | Get a channel by ID |
| `ApiServiceYouTubeData` | `list_playlists` | List channel playlists |
| `ApiServiceYouTubeData` | `list_playlist_items` | List unique playlist videos with automatic pagination |
| `ApiServiceYouTubeData` | `list_channel_videos` | List unique channel uploads with automatic pagination |
| `ApiServiceYouTubeData` | `get_video` | Get video metadata and statistics |
| `ApiServiceYouTubeData` | `search_videos` | Search public YouTube videos |
| `ApiServiceYouTubeAnalytics` | `query_channel_report` | Run a targeted Analytics query |
| `ApiServiceYouTubeAnalytics` | `get_channel_summary` | Get headline Studio metrics |
| `ApiServiceYouTubeAnalytics` | `get_top_videos` | Rank channel videos by views |

## MCP Tools

| Tool | Args | Description |
|---|---|---|
| `get_youtube_my_channel` | — | Get the authenticated channel and statistics |
| `get_youtube_channel` | `channel_id` | Get a channel by ID |
| `list_youtube_playlists` | `channel_id?`, `max_results?` | List channel playlists |
| `list_youtube_playlist_videos` | `playlist_id`, `max_results?` | List unique playlist videos; omit `max_results` to return all |
| `list_youtube_channel_videos` | `channel_id?`, `max_results?` | List unique uploads; omit `max_results` to return all |
| `get_youtube_video` | `video_id` | Get video metadata and statistics |
| `search_youtube_videos` | `query`, `channel_id?`, `max_results?` | Search public videos |
| `analyze_youtube_channel` | dates, metrics, optional dimensions/filters/sort | Run a targeted Analytics query |
| `get_youtube_channel_summary` | `start_date`, `end_date` | Get headline Studio metrics |
| `get_youtube_top_videos` | `start_date`, `end_date`, `max_results?` | Get top videos by views |

## Tests

Tests are live integration tests and require enabled APIs plus a valid `storage-youtube.json` token containing both configured scopes.

```sh
pytest apps/youtube/tests/ -m smoke
```

## Notes

- YouTube Data API quota defaults to 10,000 units per day. Search requests are substantially more expensive than list requests, so prefer channel uploads and playlist methods when possible.
- Analytics dates use `YYYY-MM-DD`. Recent data can lag behind YouTube Studio by several days.
- Revenue metrics require the separate `yt-analytics-monetary.readonly` scope and are not enabled here.
- Bulk Reporting API exports and all mutating operations are deferred.
