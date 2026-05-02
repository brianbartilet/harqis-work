from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class DtoApifyActor:
    """Minimal metadata for an actor as returned by GET /v2/acts."""
    id: Optional[str] = None
    name: Optional[str] = None
    username: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    isPublic: Optional[bool] = None
    stats: Optional[Dict[str, Any]] = None


@dataclass
class DtoApifyActorRun:
    """Result of POST /v2/acts/{actor_id}/runs (returned in `data`)."""
    id: Optional[str] = None
    actId: Optional[str] = None
    userId: Optional[str] = None
    startedAt: Optional[str] = None
    finishedAt: Optional[str] = None
    status: Optional[str] = None
    statusMessage: Optional[str] = None
    defaultDatasetId: Optional[str] = None
    defaultKeyValueStoreId: Optional[str] = None
    defaultRequestQueueId: Optional[str] = None
    options: Optional[Dict[str, Any]] = None
    stats: Optional[Dict[str, Any]] = None
    exitCode: Optional[int] = None
