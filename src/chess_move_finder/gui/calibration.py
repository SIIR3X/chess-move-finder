"""Full-screen overlay to calibrate the board by clicking its two corners.

Spans the whole virtual desktop, so the board is reachable on any monitor. The
user clicks the top-left then bottom-right corner; the resulting rectangle (in Qt
screen coordinates) is saved and emitted. Escape cancels.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..overlay.calibration_store import rect_from_corners, save_calibration


class CalibrationOverlay(QWidget):
    done = Signal(object)  # BoardRect, or None if cancelled

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        self._first: tuple[int, int] | None = None
        # Cover the union of every screen so the board is clickable anywhere.
        area = QRect()
        for screen in QGuiApplication.screens():
            area = area.united(screen.geometry())
        self._origin = area.topLeft()
        self.setGeometry(area)

    def mousePressEvent(self, event: object) -> None:
        point = event.globalPosition().toPoint()  # type: ignore[attr-defined]
        if self._first is None:
            self._first = (point.x(), point.y())
            self.update()
            return
        rect = rect_from_corners(self._first[0], self._first[1], point.x(), point.y())
        if rect.w < 10 or rect.h < 10:
            return  # ignore a stray second click too close to the first
        save_calibration(rect)
        self.done.emit(rect)
        self.close()

    def keyPressEvent(self, event: object) -> None:
        if event.key() == Qt.Key_Escape:  # type: ignore[attr-defined]
            self.done.emit(None)
            self.close()

    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        message = (
            "Click the TOP-LEFT corner of the board"
            if self._first is None
            else "Now click the BOTTOM-RIGHT corner   (Esc to cancel)"
        )
        painter.drawText(self.rect(), Qt.AlignCenter, message)
        if self._first is not None:
            lx = self._first[0] - self._origin.x()
            ly = self._first[1] - self._origin.y()
            painter.drawLine(lx - 12, ly, lx + 12, ly)
            painter.drawLine(lx, ly - 12, lx, ly + 12)
        painter.end()
