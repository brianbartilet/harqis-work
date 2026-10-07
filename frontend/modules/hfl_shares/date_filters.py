"""Rolling share date presets, resolved in the owner's profile timezone."""
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def date_presets(today=None):
    if today is None:
        from modules.profile.store import get_profile_store
        today = datetime.now(ZoneInfo(get_profile_store().get().timezone)).date()
    return {str(days): {'date_from': (today - timedelta(days=days - 1)).isoformat(),
                        'date_to': today.isoformat()} for days in (15, 30, 90)}


def resolve_date_preset(configuration, today=None):
    if not configuration.from_days:
        return configuration
    return replace(configuration, date_field='entry',
                   **date_presets(today)[str(configuration.from_days)])
