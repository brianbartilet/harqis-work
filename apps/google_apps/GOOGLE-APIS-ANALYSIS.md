# Google APIs — Integration Analysis for `apps/google_apps`

Analysis of free/low-cost Google APIs relevant to the harqis-work platform, mapped against use cases and the existing implementation.

---

## What's Already Implemented

| API | Service File | MCP Tools | Status |
|-----|-------------|-----------|--------|
| Google Calendar | `calendar.py` | `get_google_calendar_events_today`, `get_google_calendar_holidays` | Working |
| Gmail | `gmail.py` | `get_gmail_recent_emails`, `search_gmail` | Working |
| Google Keep | `keep.py` | `list_google_keep_notes`, `get_google_keep_note`, `create_google_keep_note` | Broken on Workspace — see below |
| Google Sheets | `sheets.py` | None exposed to MCP | Working, no MCP |

Auth pattern: **OAuth2 InstalledAppFlow** (`credentials.json` + `storage.json`). All new Google integrations can reuse this same auth infrastructure.

---

## API Candidates — Feasibility Assessment

### Finance

**Verdict: No viable free Google Finance API**

Google Finance was officially deprecated and has no public API. Alternatives within the Google ecosystem:

| Option | Cost | Notes |
|--------|------|-------|
| Google Sheets + GOOGLEFINANCE formula | Free | Pull stock data into a sheet, read via Sheets API — works today with existing `sheets.py` |
| Yahoo Finance (unofficial) | Free | Not Google, but `yfinance` Python library is stable |
| OANDA (already integrated) | Free tier | Already implemented in `apps/oanda` |

**Recommendation**: Use the existing Sheets integration — create a sheet with `=GOOGLEFINANCE("GOOG")` formulas and read it via `ApiServiceGoogleSheets`. No new API needed.

---

### Translation

**Verdict: Free tier — easy to add**

| API | Free Tier | Auth | Quota |
|-----|-----------|------|-------|
| Cloud Translation API v2 (Basic) | 500,000 chars/month | API key | Paid beyond free tier |
| Cloud Translation API v3 (Advanced) | 500,000 chars/month | OAuth or Service Account | Neural MT, glossaries |

- Auth: API key only (no OAuth needed) — simplest integration pattern
- Endpoint: `https://translation.googleapis.com/language/translate/v2`
- Enable: [Cloud Translation API](https://console.cloud.google.com/apis/library/translate.googleapis.com)
- **Feasibility: High** — straightforward REST, fits existing harqis-core pattern

---

### Google Drive (File Storage)

**Verdict: Free — strong candidate**

| Capability | Notes |
|-----------|-------|
| List files/folders | Free |
| Upload files | Free (within your 15GB Drive quota) |
| Download files | Free |
| Search by name/MIME type | Free |
| Share / permissions | Free |

- Auth: OAuth (`https://www.googleapis.com/auth/drive`) — reuses existing `GoogleApiClient`
- Discovery: `build('drive', 'v3', credentials=creds)`
- Enable: [Drive API](https://console.cloud.google.com/apis/library/drive.googleapis.com)
- **Feasibility: High** — same auth pattern as Calendar/Gmail

---

### Google Keep Notes

**Verdict: Working for personal accounts — broken for Google Workspace**

#### Why Keep Doesn't Work on Workspace

The Keep API scope (`https://www.googleapis.com/auth/keep`) is **not available to Google Workspace accounts** by default. This is a Google policy restriction, not a code issue:

- Keep API is limited to **consumer Gmail accounts** (`@gmail.com`)
- Workspace admins *can* enable it under **Admin Console → Apps → Google Workspace → Google Keep → API Access**, but most Workspace configurations leave it disabled
- Even when enabled by admin, the Keep API may have restricted functionality in managed environments

#### Fix / Workarounds

**Option A — Use a personal Gmail account for Keep**
- Create a separate `credentials.json` scoped to a personal `@gmail.com` account
- Keep all Keep operations under that account
- Practical if personal notes are separate from work Workspace

**Option B — Switch to Google Tasks** (Workspace-safe alternative)
- Tasks API works on all accounts including Workspace
- Free, OAuth-based, similar note/checklist capability
- Scope: `https://www.googleapis.com/auth/tasks`
- Discovery: `build('tasks', 'v1', credentials=creds)`

**Option C — Store notes in Google Docs or Sheets**
- Both fully supported on Workspace
- More structured but loses Keep's simplicity

**Recommended**: Implement Tasks API as the Workspace-compatible replacement. Keep the existing Keep implementation for personal accounts but add a Tasks service alongside it.

---

### YouTube Data API

**Verdict: Free tier (10,000 units/day) — good candidate**

| Capability | Units/call | Notes |
|-----------|-----------|-------|
| Search videos | 100 | Most expensive operation |
| Get video details | 1 | Cheap |
| List channel videos | 1 | Cheap |
| List subscriptions | 1 | Requires OAuth |
| List playlists | 1 | Read-only possible with API key |

- Auth: API key for public data; OAuth for personal subscriptions/history
- Discovery: `build('youtube', 'v3', credentials=creds)` or API key
- Free quota: 10,000 units/day resets at midnight PT
- Enable: [YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com)
- **Feasibility: High** — well-documented, stable API, large Python community

**YouTube RSS feeds (no auth)**: Public channels expose RSS at:
```
https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}
```
Zero quota cost, no auth needed — useful for monitoring specific channels.

---

### Android Device Management

**Verdict: Technically free — complex setup, enterprise-focused**

| API | Use Case | Complexity |
|-----|----------|-----------|
| Android Management API | Manage enterprise devices, policies, apps | High — requires EMM enrollment |
| Firebase Cloud Messaging | Push notifications to Android devices | Medium — different paradigm |
| Android Device Policy | Enforce work profiles, remote wipe | High — requires Google Workspace EMM |

- Requires enrolling devices in an enterprise via Google Play EMM
- Not suitable for personal device management
- **Feasibility: Low** for personal/automation use — this is an enterprise MDM tool, not a personal device API

**Alternative for personal Android device data**: OwnTracks is already implemented (`apps/own_tracks`) and handles GPS/location. For app data/automation, consider ADB over TCP instead.

---

### Geolocation (Maps) API

**Verdict: Free up to $200/month credit — effectively free for low volume**

| API | Pricing | Free Equivalent |
|-----|---------|----------------|
| Geocoding API | $5/1,000 requests | 40,000 requests/month free |
| Maps Geolocation API | $5/1,000 requests | 40,000 requests/month free |
| Places API | $17/1,000 requests | ~11,700 requests/month free |
| Distance Matrix | $5/1,000 elements | 40,000 elements/month free |
| Elevation API | $5/1,000 requests | 40,000 requests/month free |
| Timezone API | $5/1,000 requests | 40,000 requests/month free |

Google provides **$200/month free credit** automatically to all accounts with a billing method on file.

- Auth: API key only (no OAuth)
- Enable: [Maps Platform](https://console.cloud.google.com/google/maps-apis/overview)
- **Feasibility: High** — simple REST, API key auth, very useful for enriching OwnTracks location data (reverse geocoding lat/lon → address)

**Synergy with OwnTracks**: Pass `lat`/`lon` from `ApiServiceOwnTracksLocations.get_last()` to the Geocoding API to get a human-readable address.

---

### Gemini API

**Verdict: Free tier available — separate from Google Cloud**

| Model | Free Tier | Rate Limit |
|-------|-----------|-----------|
| `gemini-1.5-flash` | Free (Google AI Studio) | 15 RPM, 1M tokens/day |
| `gemini-1.5-pro` | Free (Google AI Studio) | 2 RPM, 50 requests/day |
| `gemini-2.0-flash` | Free (Google AI Studio) | 15 RPM |

- Auth: **API key from Google AI Studio** (`aistudio.google.com`) — NOT the same as Google Cloud API key
- Python SDK: `google-generativeai`
- Endpoint: `https://generativelanguage.googleapis.com/v1beta/`
- **This is separate from the OpenAI integration** (`apps/open_ai`) — different SDK, different endpoint
- **Feasibility: High** — free tier is generous, Python SDK is well-maintained

**Consideration**: If `apps/open_ai` already handles AI tasks, Gemini would be a parallel option or a fallback. Most useful if you want Google-native AI (better at Google Workspace data, multimodal).

---

### Google Analytics

**Verdict: Free — requires GA4 property**

| API | Use Case | Auth |
|-----|----------|------|
| Google Analytics Data API v1 (GA4) | Report on website/app traffic | OAuth or Service Account |
| Google Analytics Admin API | Manage GA4 properties | OAuth or Service Account |

- Scope: `https://www.googleapis.com/auth/analytics.readonly`
- Discovery: `build('analyticsdata', 'v1beta', credentials=creds)`
- Enable: [Google Analytics Data API](https://console.cloud.google.com/apis/library/analyticsdata.googleapis.com)
- Requires an existing GA4 property with data
- **Feasibility: Medium** — useful if you have a website/app tracked in GA4, otherwise nothing to query

---

### Google Wallet

**Verdict: Free — niche use case**

| Capability | Notes |
|-----------|-------|
| Create passes (loyalty, tickets, boarding passes, coupons) | Free |
| Issue passes to users | Free |
| Update/expire passes | Free |

- Auth: **Service Account** (JWT-based) — different from OAuth flow
- API: `https://walletobjects.googleapis.com/walletobjects/v1/`
- Use case: Creating digital loyalty cards, event tickets, or coupons
- **Feasibility: Medium** — functional but narrow use case for personal automation

---

### Google Photos

**Verdict: NOT viable for automated library read (post-2025 restriction)**

> **Probed 2026-05-18 against this repo's own OAuth client** (`.env/credentials.json`):
> OAuth granted `photoslibrary.readonly`, but `mediaItems:search` returned
> **HTTP 403 `PERMISSION_DENIED` — "Request had insufficient authentication
> scopes."** Confirmed: Google's **31 Mar 2025** change removed library-wide
> read from `photoslibrary.readonly`.

| Capability | Notes |
|-----------|-------|
| List albums | Free |
| **List/search library media items** | **Restricted since 2025-03-31** — `mediaItems.list`/`.search` over the full library no longer work with `photoslibrary.readonly`. Requires the interactive **Picker API** (user picks per session — not automatable) or `photoslibrary.readonly.appcreateddata` (only media THIS app uploaded). |
| Upload photos | Free (`.appendonly`) |
| Create albums | Free |
| **Download original files** | **Not supported via API** (deprecated 2020) |
| **Delete photos** | **Not supported via API** |

- Auth: OAuth — but `photoslibrary.readonly` no longer implies full-library read.
- **For an HFL "what did I shoot today" ingest this API is a dead end.** Use a
  local sync/Takeout folder fed into `workflows/dumps` → `analyze_hfl_media`
  instead (no Photos API).
- Enable: [Photos Library API](https://console.cloud.google.com/apis/library/photoslibrary.googleapis.com)
- **Feasibility: Low** — uploads/albums only; no automated personal-library read.

---

## Priority Recommendations for `apps/google_apps`

| Priority | API | Effort | Value |
|----------|-----|--------|-------|
| High | **Google Drive** | Low — same auth as existing | File storage, backup, sync |
| High | **Maps Geocoding** | Low — API key only | Enrich OwnTracks location data |
| High | **Google Tasks** | Low — same auth as existing | Workspace-safe Keep replacement |
| High | **YouTube Data API** | Low — API key or OAuth | Feed monitoring, search |
| Medium | **Gemini API** | Low — separate SDK | AI alternative/complement to OpenAI |
| Medium | **Translation API** | Low — API key only | Text translation in workflows |
| Medium | **Google Photos** | Medium — new OAuth scope | Album/photo listing |
| Medium | **Google Analytics** | Medium — needs GA4 property | Traffic reporting |
| Low | **Google Wallet** | Medium — service account auth | Pass creation (niche) |
| Low | **Android Device Management** | High — EMM enrollment required | Enterprise MDM, not personal use |

---

## Google Keep — Workspace Fix Requirements

If you want to use Keep with your Workspace account:

1. **Google Workspace Admin** must go to:
   `Admin Console → Apps → Google Workspace → Google Keep → Settings → API Access`
   and enable Keep API for the domain

2. Re-authorize your `credentials.json` with the `keep` scope after admin enables it

3. If admin access is unavailable, use the **personal Gmail workaround**: maintain a separate `credentials_personal.json` pointed at an `@gmail.com` account, and route all Keep calls through that

4. Alternatively, migrate note storage to **Google Tasks** (works on all Workspace accounts out of the box, same auth flow)
