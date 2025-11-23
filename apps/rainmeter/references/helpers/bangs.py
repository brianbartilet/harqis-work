#  region Try to call rainmeter without stealing focus

import ctypes
from ctypes import wintypes
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_COPYDATA = 0x004A

# -------------------------------------------------
# Rainmeter COPYDATA struct
# -------------------------------------------------
class COPYDATASTRUCT(ctypes.Structure):
    _fields_ = [
        ("dwData", ctypes.c_size_t),   # pointer-sized integer
        ("cbData", wintypes.DWORD),    # bytes
        ("lpData", ctypes.c_void_p),   # pointer
    ]


# -------------------------------------------------
# Rainmeter Window Finder
# -------------------------------------------------
def _get_rainmeter_hwnd() -> int:
    hwnd = user32.FindWindowW("DummyRainWClass", None)
    if not hwnd:
        raise RuntimeError("Rainmeter control window not found.")
    return hwnd


# -------------------------------------------------
# Foreground Save + Restore
# -------------------------------------------------
GetForegroundWindow = user32.GetForegroundWindow
GetWindowThreadProcessId = user32.GetWindowThreadProcessId
GetCurrentThreadId = kernel32.GetCurrentThreadId
AttachThreadInput = user32.AttachThreadInput
SetForegroundWindow = user32.SetForegroundWindow

def _get_foreground_hwnd() -> int:
    return GetForegroundWindow()

def _restore_foreground_hwnd(prev_hwnd: int) -> None:
    if not prev_hwnd:
        return

    curr_thread = GetCurrentThreadId()
    prev_thread = wintypes.DWORD()
    GetWindowThreadProcessId(prev_hwnd, ctypes.byref(prev_thread))

    if prev_thread.value != curr_thread:
        AttachThreadInput(prev_thread.value, curr_thread, True)

    time.sleep(0.02)

    try:
        SetForegroundWindow(prev_hwnd)
    finally:
        if prev_thread.value != curr_thread:
            AttachThreadInput(prev_thread.value, curr_thread, False)


# -------------------------------------------------
# HUD Window Finder (after activation)
# -------------------------------------------------
def _find_hud_window_by_title_contains(text: str) -> int | None:
    matches = []

    def enum_proc(hwnd, lParam):
        title_len = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(title_len + 1)
        user32.GetWindowTextW(hwnd, buf, title_len + 1)
        if text.lower() in buf.value.lower():
            matches.append(hwnd)
        return True

    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(EnumWindowsProc(enum_proc), 0)

    return matches[0] if matches else None


# -------------------------------------------------
# Make HUD window NOACTIVATE (cannot take focus)
# -------------------------------------------------
def _make_window_no_activate(hwnd: int):
    GWL_EXSTYLE = -20
    WS_EX_NOACTIVATE = 0x08000000
    WS_EX_TOOLWINDOW = 0x00000080

    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    new_style = style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_style)


# -------------------------------------------------
# Send Bang with No Focus Steal
# -------------------------------------------------
def _send_rainmeter_bang_no_focus(bang: str) -> None:
    prev_hwnd = _get_foreground_hwnd()
    hwnd = _get_rainmeter_hwnd()

    buf = ctypes.create_unicode_buffer(bang + "\0")
    cds = COPYDATASTRUCT()
    cds.dwData = 1
    cds.cbData = ctypes.sizeof(buf)
    cds.lpData = ctypes.cast(buf, ctypes.c_void_p)

    user32.SendMessageW(hwnd, WM_COPYDATA, 0, ctypes.byref(cds))

    _restore_foreground_hwnd(prev_hwnd)


# -------------------------------------------------
# Public API (unchanged signatures)
# -------------------------------------------------
def _activate_config(skin_name: str, hud_dir: str, ini_filename: str) -> None:
    config = f'{skin_name}\\{hud_dir}' if hud_dir else skin_name
    bang = f'!ActivateConfig "{config}" "{ini_filename}"'
    _send_rainmeter_bang_no_focus(bang)

    # Give Rainmeter time to create / show HUD
    time.sleep(0.05)

    # Find HUD window (title must match what your.skin shows)
    hwnd_hud = _find_hud_window_by_title_contains("calendar peek")
    if hwnd_hud:
        _make_window_no_activate(hwnd_hud)


def _deactivate_config(skin_name: str, hud_dir: str) -> None:
    config = f'{skin_name}\\{hud_dir}' if hud_dir else skin_name
    bang = f'!DeactivateConfig "{config}"'
    _send_rainmeter_bang_no_focus(bang)


def _refresh_app() -> None:
    _send_rainmeter_bang_no_focus("!RefreshApp")


# endregion

