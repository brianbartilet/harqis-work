import sys
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

        self.pin_btn = QPushButton(self)
        self.pin_btn.setCheckable(True)
        self.pin_btn.setFlat(True)
        self.pin_btn.setFixedSize(22, 22)

        # GRAY PIN BUTTON (text color applies to glyph)
        self.pin_btn.setStyleSheet(
            """
            QPushButton {
                border: none;
                color: #C0C0C0;        /* gray */
                font-size: 15px;
            }
            QPushButton:hover {
                color: #E0E0E0;        /* lighter gray */
            }
            QPushButton:checked {
                color: #FFFFFF;        /* white when pinned */
            }
            """
        )

        self.pin_btn.toggled.connect(self._on_pin_toggled)
        layout.addWidget(self.pin_btn)

        self.update_pin_visual(getattr(self.parent_window, "pinned", True))

    def _on_pin_toggled(self, checked: bool):
        self.parent_window.set_pinned(checked)

    def set_pin_state(self, pinned: bool):
        self.pin_btn.blockSignals(True)
        self.pin_btn.setChecked(pinned)
        self.update_pin_visual(pinned)
        self.pin_btn.blockSignals(False)

    def update_pin_visual(self, pinned: bool):
        if pinned:
            self.setStyleSheet("background-color: rgba(20,20,20,230);")
            self.pin_btn.setText("📎")   # GRAY pin icon
        else:
            self.setStyleSheet("background-color: rgba(80,80,80,220);")
            self.pin_btn.setText("📎")   # same icon, different color via CSS

    # -------- drag behaviour --------
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
    def __init__(self, agent_id: str, script_url: str, width=270, height=430):
        super().__init__()

        self.pinned = True
        self._apply_window_flags()

        self.setStyleSheet("background-color: #111111;")
        self.setWindowOpacity(0.80)

        self.resize(width, height)

        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - width - 40,
                  (screen.height() - height) // 2)

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

    def _apply_window_flags(self):
        flags = Qt.FramelessWindowHint | Qt.Tool
        if self.pinned:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()

    def set_pinned(self, pinned: bool):
        if self.pinned == pinned:
            return
        self.pinned = pinned
        self._apply_window_flags()
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

    app = QApplication(sys.argv)
    widget = ElevenWidget(agent_id, script_url)
    widget.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
