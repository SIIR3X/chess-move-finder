"""The control panel: a small dark window to toggle assistance, calibrate, and watch logs.

A single compact, portrait window - the app's only visible UI (the move arrow lives
in a separate transparent overlay). It exposes:

* a switch for **game** assistance and one for **puzzle** assistance;
* a **Calibrate board** button;
* a live **log** view.

Logging from any thread is funnelled to the view through :class:`QtLogHandler`, whose
Qt signal hops to the GUI thread. The look is dark-only, set by one stylesheet.
"""

from __future__ import annotations

import ctypes
import html
import logging
import sys

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_ACCENT = "#00c853"
_DOT_OFF = "#4a4e57"  # status dot when a setup step isn't satisfied
_LOG_TIME = "#5f6672"  # dimmed timestamp
_LOG_TEXT = "#c8ccd2"  # normal message
_LOG_WARN = "#ffd166"  # warnings
_LOG_ERROR = "#ff6b6b"  # errors


def _filename(path: str) -> str:
    """The last path component (handles both / and \\ separators)."""
    return path.replace("\\", "/").rsplit("/", 1)[-1]


_STYLESHEET = f"""
#panel {{
    background: #1b1d22;
}}
#title {{
    color: #f2f3f5;
    font-size: 16px;
    font-weight: 600;
}}
#subtitle {{
    color: #8a8f98;
    font-size: 11px;
}}
QLabel {{
    color: #d6d8dc;
    font-size: 13px;
}}
#card {{
    background: #24262d;
    border-radius: 10px;
}}
QPushButton#calibrate {{
    background: {_ACCENT};
    color: #08120a;
    border: none;
    border-radius: 8px;
    padding: 10px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#calibrate:hover {{
    background: #00e676;
}}
QPushButton#calibrate:pressed {{
    background: #00b248;
}}
QPushButton.secondary {{
    background: #2c2f37;
    color: #d6d8dc;
    border: none;
    border-radius: 8px;
    padding: 9px;
    font-size: 12px;
    font-weight: 500;
}}
QPushButton.secondary:hover {{
    background: #353945;
}}
QPushButton.secondary:pressed {{
    background: #23262d;
}}
#sectionLabel {{
    color: #8a8f98;
    font-size: 11px;
    font-weight: 600;
}}
QLineEdit {{
    background: #15161a;
    color: #c8ccd2;
    border: 1px solid #2c2f37;
    border-radius: 8px;
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: 11px;
    padding: 7px 8px;
}}
#subtle {{
    color: #7e828b;
    font-size: 11px;
}}
#hint {{
    color: #7e828b;
    font-size: 11px;
    font-style: italic;
}}
QPlainTextEdit {{
    background: #15161a;
    color: #c8ccd2;
    border: 1px solid #2c2f37;
    border-radius: 8px;
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: 11px;
    padding: 6px;
}}
"""


class ToggleSwitch(QCheckBox):
    """A small pill switch (a self-painted checkbox), for a modern on/off control."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(46, 26)

    def sizeHint(self) -> QSize:
        return QSize(46, 26)

    def hitButton(self, pos: object) -> bool:
        return self.contentsRect().contains(pos)  # type: ignore[arg-type]

    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        if not self.isEnabled():  # dimmed while assistance is locked
            track, knob = QColor("#26282e"), QColor("#5a5e66")
        elif self.isChecked():
            track, knob = QColor(_ACCENT), QColor("#ffffff")
        else:
            track, knob = QColor("#3a3d45"), QColor("#ffffff")
        painter.setBrush(track)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        diameter = rect.height() - 6
        x = rect.width() - diameter - 3 if self.isChecked() else 3
        painter.setBrush(knob)
        painter.drawEllipse(x, 3, diameter, diameter)
        painter.end()


class _LogBridge(QObject):
    message = Signal(int, str)  # (levelno, formatted text)


class QtLogHandler(logging.Handler):
    """A logging handler that forwards records to the GUI thread via a Qt signal."""

    def __init__(self) -> None:
        super().__init__()
        self.bridge = _LogBridge()

    def emit(self, record: logging.LogRecord) -> None:
        self.bridge.message.emit(record.levelno, self.format(record))


class ControlPanel(QWidget):
    """The main window: a setup checklist (with status), assistance switches, logs.

    The assistance switches stay disabled until all three setup steps are green:
    Stockfish working, Chrome reachable on the debug port, and the board calibrated.
    """

    games_toggled = Signal(bool)
    puzzles_toggled = Signal(bool)
    calibrate_requested = Signal()
    stockfish_chosen = Signal(str)
    launch_chrome_requested = Signal()
    chrome_status = Signal(bool)  # emit-safe from any thread (status monitor)
    closed = Signal()

    def __init__(
        self,
        games_on: bool,
        puzzles_on: bool,
        stockfish_path: str = "",
        chrome_port: int = 9222,
    ) -> None:
        super().__init__()
        self.setObjectName("panel")
        self.setWindowTitle("Chess Move Finder")
        self.setStyleSheet(_STYLESHEET)
        self.resize(360, 620)
        self.setMinimumSize(320, 520)

        self._chrome_port = chrome_port
        self._stockfish_path = stockfish_path
        self._status = {"stockfish": False, "chrome": False, "calibration": False}
        self._dots: dict[str, QLabel] = {}
        self._subs: dict[str, QLabel] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        title = QLabel("Chess Move Finder")
        title.setObjectName("title")
        subtitle = QLabel("Stockfish best-move overlay")
        subtitle.setObjectName("subtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        root.addWidget(self._section_label("SETUP"))
        root.addWidget(
            self._card(
                [
                    self._setup_row(
                        "stockfish",
                        "Stockfish engine",
                        _filename(stockfish_path) or "Not selected",
                        "Browse",
                        self._browse_stockfish,
                    ),
                    self._setup_row(
                        "chrome",
                        "Chrome (debug)",
                        "Not running",
                        "Launch",
                        self.launch_chrome_requested.emit,
                    ),
                    self._setup_row(
                        "calibration",
                        "Board calibration",
                        "Not calibrated",
                        "Calibrate",
                        self.calibrate_requested.emit,
                    ),
                ]
            )
        )

        root.addWidget(self._section_label("ASSISTANCE"))
        self._games = ToggleSwitch()
        self._games.setChecked(games_on)
        self._games.toggled.connect(self.games_toggled)
        self._puzzles = ToggleSwitch()
        self._puzzles.setChecked(puzzles_on)
        self._puzzles.toggled.connect(self.puzzles_toggled)
        root.addWidget(
            self._card(
                [
                    self._toggle_row("Game assistance", self._games),
                    self._toggle_row("Puzzle assistance", self._puzzles),
                ]
            )
        )
        self._hint = QLabel("Complete the setup above to enable assistance.")
        self._hint.setObjectName("hint")
        root.addWidget(self._hint)

        root.addWidget(self._section_label("LOGS"))
        self._logs = QPlainTextEdit()
        self._logs.setReadOnly(True)
        self._logs.setMaximumBlockCount(1000)
        root.addWidget(self._logs, stretch=1)

        self.chrome_status.connect(self.set_chrome_status)  # thread-safe entry point
        self._update_ready()  # nothing green yet: assistance disabled

    # --- setup status ---

    def set_stockfish_status(self, ok: bool) -> None:
        self._set_status("stockfish", ok)  # keep the filename as the subtitle

    def set_chrome_status(self, ok: bool) -> None:
        self._set_status(
            "chrome", ok, f"Running (port {self._chrome_port})" if ok else "Not running"
        )

    def set_calibration_status(self, ok: bool) -> None:
        self._set_status("calibration", ok, "Calibrated" if ok else "Not calibrated")

    def _set_status(self, name: str, ok: bool, subtitle: str | None = None) -> None:
        self._status[name] = ok
        self._dots[name].setStyleSheet(
            f"background: {_ACCENT if ok else _DOT_OFF}; border-radius: 5px;"
        )
        if subtitle is not None:
            self._subs[name].setText(subtitle)
        self._update_ready()

    def _update_ready(self) -> None:
        ready = all(self._status.values())
        self._games.setEnabled(ready)
        self._puzzles.setEnabled(ready)
        self._hint.setVisible(not ready)

    # --- widgets ---

    def _card(self, rows: list[QWidget]) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 4, 14, 4)
        layout.setSpacing(0)
        for i, row in enumerate(rows):
            if i:
                line = QFrame()
                line.setFixedHeight(1)
                line.setStyleSheet("background: #2c2f37;")
                layout.addWidget(line)
            layout.addWidget(row)
        return card

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionLabel")
        return label

    def _secondary_button(self, text: str, on_click: object) -> QPushButton:
        button = QPushButton(text)
        button.setProperty("class", "secondary")
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(on_click)  # type: ignore[arg-type]
        return button

    def _status_dot(self) -> QLabel:
        dot = QLabel()
        dot.setFixedSize(10, 10)
        dot.setStyleSheet(f"background: {_DOT_OFF}; border-radius: 5px;")
        return dot

    def _setup_row(
        self, name: str, title: str, subtitle: str, button_text: str, on_click: object
    ) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setSpacing(10)
        dot = self._status_dot()
        self._dots[name] = dot
        layout.addWidget(dot, alignment=Qt.AlignVCenter)

        texts = QVBoxLayout()
        texts.setSpacing(1)
        texts.addWidget(QLabel(title))
        sub = QLabel(subtitle)
        sub.setObjectName("subtle")
        sub.setToolTip(subtitle)
        self._subs[name] = sub
        texts.addWidget(sub)
        layout.addLayout(texts)

        layout.addStretch(1)
        layout.addWidget(self._secondary_button(button_text, on_click))
        return row

    def _browse_stockfish(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select the Stockfish executable", self._stockfish_path
        )
        if path:
            self.set_stockfish_path(path)
            self.stockfish_chosen.emit(path)

    def set_stockfish_path(self, path: str) -> None:
        self._stockfish_path = path
        self._subs["stockfish"].setText(_filename(path) or "Not selected")
        self._subs["stockfish"].setToolTip(path)

    def _toggle_row(self, label: str, switch: ToggleSwitch) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.addWidget(QLabel(label))
        layout.addStretch(1)
        layout.addWidget(switch)
        return row

    def append_log(self, level: int, text: str) -> None:
        # Split "HH:MM:SS  message" so the timestamp can be dimmed.
        stamp, _, body = text.partition("  ")
        if not body:
            stamp, body = "", text
        if level >= logging.ERROR:
            color = _LOG_ERROR
        elif level >= logging.WARNING:
            color = _LOG_WARN
        else:
            color = _LOG_TEXT
        self._logs.appendHtml(
            f'<span style="color:{_LOG_TIME}">{html.escape(stamp)}</span>&nbsp;&nbsp;'
            f'<span style="color:{color}">{html.escape(body)}</span>'
        )
        bar = self._logs.verticalScrollBar()
        bar.setValue(bar.maximum())  # keep the latest line in view

    def showEvent(self, event: object) -> None:
        super().showEvent(event)  # type: ignore[arg-type]
        self._apply_dark_titlebar()

    def _apply_dark_titlebar(self) -> None:
        """Paint the Windows title bar dark to match the app (no-op elsewhere)."""
        if sys.platform != "win32":
            return
        try:
            hwnd = ctypes.c_void_p(int(self.winId()))
            enabled = ctypes.c_int(1)
            # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE (Win10 20H1+); 19 = older builds.
            for attribute in (20, 19):
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, ctypes.c_int(attribute), ctypes.byref(enabled), ctypes.sizeof(enabled)
                )
        except Exception:  # missing dwmapi / unsupported: keep the default title bar
            pass

    def closeEvent(self, event: object) -> None:
        self.closed.emit()
        super().closeEvent(event)  # type: ignore[arg-type]
