"""Internal bearer-authenticated command mounted beneath the canonical HFL API."""
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from modules.integrations import github_updates

router = APIRouter()


class SyncRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    pages: int = Field(default=5, ge=1, le=10)
    limit: int = Field(default=10, ge=1, le=25)
    run_id: str = Field(default='', max_length=100)


@router.post('/github-updates/sync')
def sync(payload: SyncRequest):
    return github_updates.run(**payload.model_dump())
