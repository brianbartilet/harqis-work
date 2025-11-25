import subprocess
import time
from datetime import datetime
from pathlib import Path

from PIL import Image
import pytesseract

# Where to write logs (under shared storage so it can be synced / accessed)
LOG_DIR = Path.home() / "storage" / "shared" / "AndroidScreenLogs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Log file rotation: per hour
# actions-YYYYMMDD_HH.log
def current_log_file() -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H")
    return LOG_DIR / f"android_actions-{ts}.log"

# Temporary screenshot path
TMP_SCREENSHOT = LOG_DIR / "tmp_screen.png"

# How often to capture (seconds)
LOOP_DELAY = 10  # adjust as desired (e.g. 5 or 30)


# --- Helpers ---------------------------------------------------------------

def run_cmd(args):
    """Run a shell command and return stdout as text (or raise)."""
    result = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command {args} failed: {result.returncode}, stderr={result.stderr.strip()}"
        )
    return result.stdout


def get_foreground_window() -> str:
    """
    Get the current foreground window / activity via dumpsys.
    This usually gives a line like:
      mCurrentFocus=Window{... u0 com.android.chrome/com.google.android.apps.chrome.Main}
    """
    try:
        out = run_cmd(["dumpsys", "window", "windows"])
        for line in out.splitlines():
            if "mCurrentFocus" in line:
                return line.strip()
        return "<mCurrentFocus not found>"
    except Exception as e:
        return f"<error getting focus: {e}>"


def capture_screenshot(path: Path) -> None:
    """
    Capture the screen via termux-screenshot (Termux:API).
    This will prompt once for permission the first time you run it.
    """
    # termux-screenshot defaults to /sdcard/Pictures/Screenshots/...
    # but with -f we can force a filepath.
    run_cmd(["termux-screenshot", "-f", str(path)])


def ocr_image(path: Path) -> str:
    """
    Run Tesseract OCR on the given screenshot.
    """
    img = Image.open(path)

    # Optional: upscale if text is small
    # w, h = img.size
    # img = img.resize((w * 2, h * 2), Image.LANCZOS)

    text = pytesseract.image_to_string(img, config="--psm 6")
    return text.replace("\r\n", "\n").strip()


def log_line(log_file: Path, line: str) -> None:
    """Append a single line to the current log file."""
    with log_file.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


# --- Main loop -------------------------------------------------------------

def run_android_screen_logger():
    print(f"Logging Android focus + OCR to: {LOG_DIR}")
    print("Make sure Termux:API is installed and storage permission is granted.")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            now = datetime.now()
            ts = now.strftime("%Y-%m-%d %H:%M:%S")
            log_file = current_log_file()

            focus_info = get_foreground_window()

            try:
                capture_screenshot(TMP_SCREENSHOT)
                ocr_text = ocr_image(TMP_SCREENSHOT)
            except Exception as e:
                ocr_text = f"<OCR error: {e}>"

            # Console output
            print(f"[{ts}] FOCUS: {focus_info}")
            if ocr_text and not ocr_text.startswith("<OCR error:"):
                print(f"[{ts}] OCR (first 200 chars): {ocr_text[:200]}...\n")
            else:
                print(f"[{ts}] OCR: {ocr_text}\n")

            # Log to file
            log_line(log_file, f"[{ts}] FOCUS: {focus_info}")
            if ocr_text:
                if ocr_text.startswith("<OCR error:"):
                    log_line(log_file, f"[{ts}] OCR: {ocr_text}")
                else:
                    for line in ocr_text.split("\n"):
                        line = line.strip()
                        if line:
                            log_line(log_file, f"[{ts}] OCR: {line}")

            time.sleep(LOOP_DELAY)

    except KeyboardInterrupt:
        print("\nStopped by user.")


if __name__ == "__main__":
    run_android_screen_logger()
