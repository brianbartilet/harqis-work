from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class DtoSpotifyArtist:
    """A Spotify artist (subset of fields relevant to HFL signal)."""
    id: Optional[str] = None
    name: Optional[str] = None
    genres: List[str] = field(default_factory=list)
    popularity: Optional[int] = None
    uri: Optional[str] = None


@dataclass
class DtoSpotifyTrack:
    """A Spotify track (subset of fields relevant to HFL signal)."""
    id: Optional[str] = None
    name: Optional[str] = None
    artists: List[DtoSpotifyArtist] = field(default_factory=list)
    album: Optional[dict] = None
    duration_ms: Optional[int] = None
    popularity: Optional[int] = None
    uri: Optional[str] = None


@dataclass
class DtoPlayHistory:
    """One entry from /me/player/recently-played.

    ``played_at`` is an ISO-8601 UTC timestamp; ``track`` is the full track
    object. The recently-played endpoint returns these newest-first.
    """
    played_at: Optional[str] = None
    track: Optional[dict] = None
    context: Optional[dict] = None
