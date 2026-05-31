"""Spotify Web API constants."""

# OAuth2 token endpoint — distinct host from the Web API base
# (https://api.spotify.com/v1/). Access tokens minted here expire in ~1h,
# so the base service exchanges the long-lived refresh token on every init.
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"

# Valid `time_range` values for the personalization endpoints.
#   short_term  ~ last 4 weeks
#   medium_term ~ last 6 months
#   long_term   ~ several years
TIME_RANGE_SHORT = "short_term"
TIME_RANGE_MEDIUM = "medium_term"
TIME_RANGE_LONG = "long_term"

# recently-played caps at 50 items per call (time-cursor endpoint).
RECENTLY_PLAYED_MAX_LIMIT = 50
