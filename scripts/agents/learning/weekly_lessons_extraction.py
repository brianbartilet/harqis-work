#!/usr/bin/env python3
"""
weekly_lessons_extraction.py — Cron wrapper for autonomous lessons extraction.

Scheduled to run Sundays 22:00 SGT (14:00 UTC).
Calls lessons_extractor.py; captures output for logging.

Location: ~/.hermes/scripts/weekly_lessons_extraction.py
Cron entry: 0 14 * * 0 python ~/.hermes/scripts/weekly_lessons_extraction.py
(or via hermes cronjob integration)
"""

import subprocess
import sys
from pathlib import Path
from datetime import datetime


def main():
    """Run weekly lessons extraction and log results."""
    
    # Path to lessons extractor
    extractor = Path.home() / ".hermes" / "scripts" / "lessons_extractor.py"
    
    if not extractor.exists():
        print(f"ERROR: lessons_extractor.py not found at {extractor}")
        sys.exit(1)
    
    # Log file location
    log_dir = Path.home() / ".hermes" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "weekly_lessons_extraction.log"
    
    print(f"[{datetime.now().isoformat()}] Starting weekly lessons extraction...")
    
    # Run extraction
    try:
        result = subprocess.run(
            [sys.executable, str(extractor)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        
        # Log output
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*70}\n")
            f.write(f"[{datetime.now().isoformat()}] Run started\n")
            f.write(f"{'='*70}\n")
            f.write(result.stdout)
            if result.stderr:
                f.write(f"\nSTDERR:\n{result.stderr}\n")
            f.write(f"\nExit code: {result.returncode}\n")
        
        if result.returncode == 0:
            print(f"✓ Extraction completed. Log: {log_file}")
        else:
            print(f"✗ Extraction failed (exit {result.returncode})")
            print(f"See log: {log_file}")
            sys.exit(result.returncode)
    
    except subprocess.TimeoutExpired:
        print("✗ Extraction timed out after 60 seconds")
        sys.exit(1)
    except Exception as e:
        print(f"✗ Error running extraction: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
