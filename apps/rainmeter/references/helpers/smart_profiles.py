from __future__ import annotations

import time
import subprocess
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Mapping

from apps.google_apps.references.constants import ScheduleCategory

# 👇 EDIT THIS: mapping of Rainmeter layouts to times-of-day (24h "HH:MM")
PROFILE_SCHEDULE: Dict[str, List[ScheduleCategory]] = {
    "work": [ScheduleCategory.WORK, ],
    "home": []
}


def load_rainmeter_profile(
    config: Mapping[str, str],
    profile_name: str
) -> None:
    """
    Load a Rainmeter layout/profile by name using the Rainmeter.exe CLI.

    Args:
        profile_name: Name of the layout as it appears in Rainmeter's Layouts tab.
        rainmeter_exe: Full path to Rainmeter.exe.
        :param profile_name:
        :param config:
    """
    rainmeter_exe = Path(config["bin_path"]).resolve()
    exe = Path(rainmeter_exe)

    if not exe.exists():
        print(f"[ERROR] Rainmeter.exe not found at: {exe}")
        return

    try:
        # Rainmeter command line: Rainmeter.exe !LoadLayout "LayoutName"
        subprocess.run(
            [str(exe), "!LoadLayout", profile_name],
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,  # avoid spawning a console window
        )
        print(f"[INFO] Switched Rainmeter layout to: {profile_name}")
    except Exception as e:
        print(f"[ERROR] Failed to load layout '{profile_name}': {e}")


def run_profile_scheduler(
    profile_schedule: Dict[str, List[str]],
    rainmeter_exe: str,
    poll_seconds: int = 30,
) -> None:
    """
    Loop forever and switch Rainmeter profiles at configured times.

    profile_schedule example:
        {
            "WorkMode": ["09:00", "13:30"],
            "ChillMode": ["18:00"],
        }

    Times must be in 24h "HH:MM" format (no seconds).

    The scheduler triggers once per profile+time per calendar day.
    """
    # Track which (date, profile, time_str) we already executed today
    already_triggered = set()
    current_day: date = date.today()

    print("[INFO] Rainmeter profile scheduler started.")
    print(f"[INFO] Using Rainmeter at: {rainmeter_exe}")
    print("[INFO] Schedule:")
    for profile, times in profile_schedule.items():
        print(f"  - {profile}: {', '.join(times)}")

    while True:
        now = datetime.now()
        today = now.date()

        # Reset triggers at midnight
        if today != current_day:
            current_day = today
            already_triggered.clear()
            print("[INFO] New day detected, trigger history reset.")

        current_hhmm = now.strftime("%H:%M")

        for profile, times in profile_schedule.items():
            for t in times:
                key = (today.isoformat(), profile, t)

                if t == current_hhmm and key not in already_triggered:
                    print(f"[INFO] {current_hhmm} reached → switching to '{profile}'")
                    load_rainmeter_profile(profile, rainmeter_exe)
                    already_triggered.add(key)

        time.sleep(poll_seconds)