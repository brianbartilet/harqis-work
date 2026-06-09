from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class DtoPlaudRecording:
    """A single Plaud recording, normalized across the cloud API and the
    local export-folder fallback so downstream callers never branch on origin.

    ``transcript`` / ``summary`` are populated only when Plaud already produced
    them (cloud) or a sibling text file is present (folder). When both are
    ``None`` the ingest pipeline transcribes the audio itself (Whisper).
    """
    id: Optional[str] = None              # stable, deterministic id (cloud id or folder slug)
    title: Optional[str] = None           # human label / filename stem
    started_at: Optional[str] = None      # ISO 8601 UTC ("YYYY-MM-DDTHH:MM:SS")
    duration_seconds: Optional[int] = None
    audio_url: Optional[str] = None       # remote download URL (cloud only)
    audio_path: Optional[str] = None      # local path once downloaded / for folder source
    audio_format: Optional[str] = None    # "mp3" | "wav" | "m4a" | ...
    transcript: Optional[str] = None      # Plaud's transcript text, if available
    summary: Optional[str] = None         # Plaud's summary text, if available
    tags: List[str] = field(default_factory=list)
    origin: Optional[str] = None          # "cloud" | "folder" — provenance, for logs/debug

    @property
    def has_transcript(self) -> bool:
        return bool(self.transcript and self.transcript.strip())
