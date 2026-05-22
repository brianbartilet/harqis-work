#!/usr/bin/env python3
"""
weekly_lessons_extraction.py — Autonomous weekly pattern detection from HFL.

Scheduled: Sundays 22:00 SGT (14:00 UTC)
Runs the lessons_extractor.py to scan past 7 days of HFL reasoning entries,
detect recurring patterns, and update ~/.hermes/memory/agent_lessons.md.

This is a scheduled cron job (not interactive). It appends results to memory
for future agent consultation during complex tasks.
"""

import subprocess
import sys
from pathlib import Path

# Lessons extractor script
extractor_script = Path(__file__).parent / "lessons_extractor.py"

if not extractor_script.exists():
    print(f"Error: {extractor_script} not found")
    sys.exit(1)

# Run extractor
try:
    result = subprocess.run(
        [sys.executable, str(extractor_script)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    
    if result.returncode == 0:
        print(result.stdout)
    else:
        print(f"Extraction failed: {result.stderr}")
        sys.exit(1)

except subprocess.TimeoutExpired:
    print("Extraction timed out after 60 seconds")
    sys.exit(1)
except Exception as e:
    print(f"Error running extractor: {e}")
    sys.exit(1)
