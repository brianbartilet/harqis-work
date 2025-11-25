import time
from datetime import datetime
from pathlib import Path

import uiautomation as auto
import pyttsx3

from PIL import ImageGrab
import pytesseract
from _ctypes import COMError  # to catch COM-related errors explicitly

# If needed, explicitly set the tesseract.exe path, e.g.:
# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# File where we append everything the "screen reader" says
LOG_FILE = Path("screenreader_log.txt")


def get_focus_ocr_text(control) -> str:
    """
    Capture the bounding rectangle of the focused control and run OCR on it.
    Returns the recognized text (possibly empty string).
    """
    rect = getattr(control, "BoundingRectangle", None)
    if not rect:
        return ""

    left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom

    # Basic sanity check
    if right <= left or bottom <= top:
        return ""

    try:
        img = ImageGrab.grab(bbox=(left, top, right, bottom))
        text = pytesseract.image_to_string(img)
        text = text.replace("\r\n", "\n").strip()
        return text
    except Exception as e:
        # For debugging you can log this; returning empty keeps things quiet
        # return f"<OCR error: {e}>"
        return ""


def run_capture():
    engine = pyttsx3.init()

    last_name = None

    print(f"Logging focus changes to: {LOG_FILE.resolve()}")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            # Safely get the focused control
            try:
                focused = auto.GetFocusedControl()
            except Exception:
                time.sleep(0.1)
                continue

            if not focused:
                time.sleep(0.1)
                continue

            # Safely get the Name (handles COMError)
            try:
                name = focused.Name or ""
            except COMError:
                # UIA sometimes throws when querying properties; just skip this cycle
                time.sleep(0.1)
                continue
            except Exception:
                time.sleep(0.1)
                continue

            if name != last_name:
                # Speak the control name
                print(name)
                engine.say(name)
                engine.runAndWait()

                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # Run OCR on the focused control area (already wrapped in try/except)
                ocr_text = get_focus_ocr_text(focused)

                with LOG_FILE.open("a", encoding="utf-8") as f:
                    f.write(f"[{timestamp}] FOCUS: {name}\n")

                    if ocr_text:
                        for line in ocr_text.split("\n"):
                            line = line.strip()
                            if line:
                                f.write(f"[{timestamp}] OCR: {line}\n")

                last_name = name

            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\nStopped by user.")


if __name__ == "__main__":
    run_capture()
