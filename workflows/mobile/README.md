# Mobile Workflow

## Description

- Android screen activity logger running on-device via [Termux](https://termux.dev/).
- Captures the foreground app name, takes a screenshot, runs OCR (Tesseract), and appends a timestamped log line every 10 seconds.
- Logs are written to `~/storage/shared/AndroidScreenLogs/` on the Android device.
- **Not a Celery task** — runs as a standalone Python loop directly on the Android device.

## Directory Structure

```
workflows/mobile/
├── android/
│   └── tasks/
│       └── capture.py          # Main Android screen logger loop
└── __init__.py
```

## How It Works

`android/tasks/capture.py` runs an infinite loop:

1. `get_foreground_window()` — Uses Termux API (`termux-foreground-app`) to get the active app package name.
2. `capture_screenshot()` — Uses `termux-screenshot` to capture a PNG to a temp file.
3. `ocr_image(path)` — Runs Tesseract OCR on the screenshot to extract visible text.
4. `log_line(app, text)` — Appends a timestamped entry to the current log file.
5. Waits 10 seconds, then repeats.

Log files are named by the hour: `YYYY-MM-DD-HH.log`

## Setup (on Android device with Termux)

1. Install Termux and Termux:API from F-Droid.
2. Install dependencies:

   ```sh
   pkg install python tesseract termux-api
   pip install pillow
   ```

3. Grant Termux storage permission:

   ```sh
   termux-setup-storage
   ```

4. Run the logger:

   ```sh
   python android/tasks/capture.py
   ```

5. To run in background:

   ```sh
   nohup python android/tasks/capture.py &
   ```

## Log Format

Each log line:
```
2026-03-25 14:32:00 | com.example.app | [OCR text from screen...]
```

Log directory: `~/storage/shared/AndroidScreenLogs/`

## Notes

- This task is **unscheduled** — it is not in any Celery Beat configuration and not merged into `workflows/config.py`.
- Designed to run continuously on-device, not from the desktop Python environment.
- OCR quality depends on screen content and Tesseract language packs installed (`pkg install tesseract-lang`).
- The captured logs can be synced to the desktop via `workflows/desktop` file sync tasks for AI analysis.
