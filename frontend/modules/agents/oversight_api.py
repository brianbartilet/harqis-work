"""Mounted beneath the canonical bearer-authenticated HFL API."""
from fastapi import APIRouter
from config import get_settings
from modules.agents.oversight import reconcile

router = APIRouter()


@router.post('/fleet/reconcile')
def reconcile_fleet():
    return reconcile(get_settings().app_username)
