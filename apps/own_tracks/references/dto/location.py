from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DtoOwnTracksLocation:
    """A single location fix from an OwnTracks device."""
    username: Optional[str] = None
    device: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    tst: Optional[int] = None       # Unix timestamp
    acc: Optional[int] = None       # Accuracy in metres
    tid: Optional[str] = None       # Tracker ID (2-char label shown on map)
    alt: Optional[float] = None     # Altitude in metres
    vel: Optional[int] = None       # Speed in km/h
    batt: Optional[int] = None      # Battery level (0-100)
    topic: Optional[str] = None     # MQTT topic: owntracks/<user>/<device>


@dataclass
class DtoOwnTracksDevice:
    """A known user/device pair registered with the Recorder."""
    username: Optional[str] = None
    device: Optional[str] = None
    topic: Optional[str] = None
