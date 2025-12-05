import sys
import ctypes
from ctypes import wintypes
import signal  # <-- NEW

from PySide6.QtCore import Qt, QPoint, QUrl
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QFrame,
    QHBoxLayout,
    QPushButton,
)
from PySide6.QtWebEngineWidgets import QWebEngineView


def build_html(agent_id: str, script_url: str) -> str:
    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  html, body {{
    margin: 0;
    padding: 0;
    overflow: hidden;
    width: 100%;
    height: 100%;
    background: #000;
  }}

  elevenlabs-convai {{
    width: 100%;
    height: 100%;
    display: block;
  }}
</style>
</head>
<body>
  <elevenlabs-convai agent-id="{agent_id}"></elevenlabs-convai>
  <script src="{script_url}" async type="text/javascript"></script>
</body>
</html>
"""


# =======================
# Windows desktop helpers
# =======================

_is_windows = sys.platform.startswith("win")

if _is_windows:
    user32 = ctypes.windll.user32

    EnumWindowsProc = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HWND,
        wintypes.LPARAM,
    )

    def _get_workerw_hwnd() -> int | None:
        """
        Find the WorkerW window where we can parent our widget to behave
        like a desktop gadget.
        """
        progman = user32.FindWindowW("Progman", None)
        if not progman:
            return None

        # Ask Progman to spawn a WorkerW
        user32.SendMessageTimeoutW(
            progman,
            0x052C,  # 0x052C = "Progman, create WorkerW"
            0,
            0,
            0,
            1000,
            None,
        )

        workerw_out = ctypes.c_void_p(0)

        def _enum_windows(hwnd, lparam):
            # Look for a SHELLDLL_DefView child; its parent has a WorkerW sibling
            shell_dll_defview = user32.FindWindowExW(
                hwnd, 0, "SHELLDLL_DefView", None
            )
            if shell_dll_defview:
                # The WorkerW is a sibling of the window that owns SHELLDLL_DefView
                workerw = user32.FindWindowExW(
                    0, hwnd, "WorkerW", None
                )
                if workerw:
                    workerw_out.value = workerw
                    return False  # stop enumeration
            return True  # continue

        user32.EnumWindows(EnumWindowsProc(_enum_windows), 0)

        return workerw_out.value or None

    def _set_parent_to_workerw(hwnd: int, enable: bool):
        """
        If enable=True, parent hwnd to WorkerW; else reset parent to desktop.
        """
        if not hwnd:
            return

        if enable:
            workerw = _get_workerw_hwnd()
            if workerw:
                user32.SetParent(hwnd, workerw)
        else:
            # 0 = desktop / no explicit parent (back to top-level)
            user32.SetParent(hwnd, 0)


class DragBar(QFrame):
    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self._drag_pos: QPoint | None = None

        self.setFixedHeight(26)
        self.setCursor(Qt.OpenHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setSpacing(4)
        layout.addStretch(1)

        # -------- PIN BUTTON (GRAY) --------
        self.pin_btn = QPushButton("📎", self)
        self.pin_btn.setCheckable(True)
        self.pin_btn.setFlat(True)
        self.pin_btn.setFixedSize(22, 22)

        # ORIGINAL COLOR STYLE
        self.pin_btn.setStyleSheet("""
            QPushButton {
                border: none;
                color: #C0C0C0;            /* gray */
                font-size: 15px;
            }
            QPushButton:hover {
                color: #E0E0E0;            /* lighter gray */
            }
            QPushButton:checked {
                color: #FFFFFF;            /* white when pinned */
            }
        """)

        self.pin_btn.toggled.connect(self._on_pin_toggled)
        layout.addWidget(self.pin_btn)

        # -------- CLOSE BUTTON (X) --------
        self.close_btn = QPushButton("✖", self)
        self.close_btn.setFlat(True)
        self.close_btn.setFixedSize(22, 22)
        self.close_btn.setStyleSheet("""
            QPushButton {
                border: none;
                color: #C0C0C0;
                font-size: 15px;
            }
            QPushButton:hover {
                color: #FF6666;            /* soft red */
            }
        """)
        self.close_btn.clicked.connect(self._on_close_clicked)
        layout.addWidget(self.close_btn)

        # Set initial pinned-state visuals
        self.update_pin_visual(getattr(self.parent_window, "pinned", True))

    # ======================================================
    # Close action
    # ======================================================
    def _on_close_clicked(self):
        QApplication.quit()

    # ======================================================
    # Pin toggle event handler
    # ======================================================
    def _on_pin_toggled(self, checked: bool):
        self.parent_window.set_pinned(checked)
        self.update_pin_visual(checked)

    def set_pin_state(self, pinned: bool):
        self.pin_btn.blockSignals(True)
        self.pin_btn.setChecked(pinned)
        self.update_pin_visual(pinned)
        self.pin_btn.blockSignals(False)

    def update_pin_visual(self, pinned: bool):
        """Keep background same style you used originally."""
        if pinned:
            # Darker background when pinned
            self.setStyleSheet("background-color: rgba(20,20,20,230);")
        else:
            # Slightly brighter gray when unpinned
            self.setStyleSheet("background-color: rgba(80,80,80,220);")

    # ======================================================
    # Drag behavior
    # ======================================================
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setCursor(Qt.ClosedHandCursor)
            pos = event.globalPosition().toPoint()
            self._drag_pos = pos - self.parent_window.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            pos = event.globalPosition().toPoint()
            self.parent_window.move(pos - self._drag_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setCursor(Qt.OpenHandCursor)
            self._drag_pos = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.parent_window.toggle_pin()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


class ElevenWidget(QWidget):
    def __init__(self, agent_id: str, script_url: str, width=270, height=435):
        super().__init__()

        # Start pinned-to-desktop
        self.pinned = True

        self._apply_window_flags()

        self.setStyleSheet("background-color: #111111;")
        self.setWindowOpacity(0.70)

        self.resize(width, height)

        # ---- Position at bottom-right of primary monitor ----
        screen_geom = QApplication.primaryScreen().availableGeometry()
        margin = 20  # distance from screen edges

        x = screen_geom.x() + screen_geom.width() - width - margin
        y = screen_geom.y() + screen_geom.height() - height - margin

        self.move(x, y)
        # ------------------------------------------------------

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.drag_bar = DragBar(self)
        self.drag_bar.set_pin_state(self.pinned)
        layout.addWidget(self.drag_bar)

        self.view = QWebEngineView(self)
        self.view.page().setBackgroundColor(Qt.black)

        html = build_html(agent_id, script_url)
        self.view.setHtml(html, QUrl("https://unpkg.com/"))

        layout.addWidget(self.view)

        # After we have a native handle, pin/unpin appropriately
        self._update_desktop_pinning()

    def _apply_window_flags(self):
        """
        When pinned: behave like a gadget (no taskbar, not always-on-top).
        When unpinned: normal window (shows in Alt+Tab / taskbar).
        """
        if self.pinned:
            flags = Qt.FramelessWindowHint | Qt.Tool
        else:
            flags = Qt.FramelessWindowHint | Qt.Window

        self.setWindowFlags(flags)
        self.show()

    def _update_desktop_pinning(self):
        """
        Actually reparent to WorkerW on Windows when pinned.
        """
        if not _is_windows:
            return

        hwnd = int(self.winId()) if self.winId() is not None else 0
        if not hwnd:
            return

        if self.pinned:
            _set_parent_to_workerw(hwnd, True)
        else:
            _set_parent_to_workerw(hwnd, False)

    def set_pinned(self, pinned: bool):
        if self.pinned == pinned:
            return
        self.pinned = pinned

        # Re-apply flags (changes Tool/Window etc.)
        self._apply_window_flags()

        # Re-parent to desktop WorkerW or back to normal
        self._update_desktop_pinning()

        if hasattr(self, "drag_bar"):
            self.drag_bar.set_pin_state(self.pinned)

    def toggle_pin(self):
        self.set_pinned(not self.pinned)


def main():
    default_script_url = "https://unpkg.com/@elevenlabs/convai-widget-embed@beta"

    try:
        agent_id = sys.argv[1]
        script_url = sys.argv[2] if len(sys.argv) > 2 else default_script_url
    except IndexError:
        sys.exit(f"Usage: {sys.argv[0]} <agent_id>")

    print("Using:")
    print(f"  Agent ID : {agent_id}")
    print(f"  Script   : {script_url}")

    # Ensure Ctrl+C (SIGINT) is delivered so we can catch KeyboardInterrupt
    signal.signal(signal.SIGINT, signal.SIG_DFL)  # <-- NEW

    app = QApplication(sys.argv)
    widget = ElevenWidget(agent_id, script_url)
    widget.show()

    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        # Graceful shutdown on Ctrl+C
        print("\nKeyboardInterrupt received, closing widget...")
        widget.close()
        sys.exit(0)


if __name__ == "__main__":
    main()
