"""A frameless, transparent, click-through, always-on-top arrow overlay.

It covers the monitor that contains the arrow and paints a single arrow from the
source square to the target square. It never steals focus or clicks: events pass
straight through to the browser underneath.

Drive it from any thread via the :attr:`arrow_changed` signal: emit ``(fx, fy, tx,
fy)`` screen-coordinate tuples to show an arrow, or ``None`` to hide it.
"""

from __future__ import annotations

import logging
import math
import sys

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

logger = logging.getLogger("chess_move_finder")


class ArrowOverlay(QWidget):
    arrow_changed = Signal(object)  # (fx, fy, tx, ty) in screen coords, or None to hide

    def __init__(self, color: tuple[int, int, int], thickness: int) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._color = QColor(*color)
        self._thickness = thickness
        self._line: tuple[float, float, float, float] | None = None
        self.arrow_changed.connect(self._apply)

    def _apply(self, payload: object) -> None:
        if payload is None:
            self._line = None
            self.hide()
            return
        fx, fy, tx, ty = payload  # type: ignore[misc]
        at = QGuiApplication.screenAt(QPoint(int(fx), int(fy)))
        screen = at or QGuiApplication.primaryScreen()
        geo = screen.geometry()
        self.setGeometry(geo)
        ox, oy = geo.x(), geo.y()
        self._line = (fx - ox, fy - oy, tx - ox, ty - oy)
        logger.info(
            "Overlay: screen at point=%s geom=(%d,%d %dx%d) local=(%.0f,%.0f)->(%.0f,%.0f)",
            at is not None,
            geo.x(),
            geo.y(),
            geo.width(),
            geo.height(),
            self._line[0],
            self._line[1],
            self._line[2],
            self._line[3],
        )
        self.show()
        self.raise_()
        self._make_click_through()
        self.update()

    def paintEvent(self, event: object) -> None:
        if self._line is None:
            return
        fx, fy, tx, ty = self._line
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(self._color, self._thickness, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(self._color)

        angle = math.atan2(ty - fy, tx - fx)
        head = max(3 * self._thickness, 18.0)
        # Stop the shaft at the base of the arrowhead so they don't overlap.
        base_x = tx - head * math.cos(angle)
        base_y = ty - head * math.sin(angle)
        painter.drawLine(int(fx), int(fy), int(base_x), int(base_y))

        spread = math.radians(26)
        left = QPoint(
            int(tx - head * math.cos(angle - spread)),
            int(ty - head * math.sin(angle - spread)),
        )
        right = QPoint(
            int(tx - head * math.cos(angle + spread)),
            int(ty - head * math.sin(angle + spread)),
        )
        painter.drawPolygon(QPolygonF([QPoint(int(tx), int(ty)), left, right]))
        painter.end()

    def _make_click_through(self) -> None:
        """On Windows, force the window to be transparent to mouse input."""
        if sys.platform != "win32":
            return
        try:
            import ctypes

            gwl_exstyle = -20
            ws_ex_layered = 0x00080000
            ws_ex_transparent = 0x00000020
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            current = user32.GetWindowLongW(hwnd, gwl_exstyle)
            user32.SetWindowLongW(hwnd, gwl_exstyle, current | ws_ex_layered | ws_ex_transparent)
        except Exception:
            pass
