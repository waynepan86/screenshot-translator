"""Verify that the transparent capture overlay still owns native mouse hit tests."""

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QRect
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from capture_window import CaptureWindow


class Config:
    def get(self, key):
        return {
            "ocr_review": True,
            "hotkey_region": "F1",
            "hotkey_fullscreen": "F2",
        }.get(key)


class Point(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


def main():
    app = QApplication.instance() or QApplication([])
    screen = app.primaryScreen()
    geometry = screen.geometry()
    pixmap = QPixmap(geometry.size())
    pixmap.fill()

    overlay = CaptureWindow(pixmap, geometry, Config())
    overlay.draw_magnifier = lambda *_: None
    local_center = overlay.rect().center()
    overlay.hover_window = QRect(
        local_center.x() - 150, local_center.y() - 100, 300, 200
    )
    overlay.show()
    overlay.raise_()
    overlay.activateWindow()
    overlay.update()
    QTest.qWait(250)
    app.processEvents()

    user32 = ctypes.windll.user32
    user32.WindowFromPoint.argtypes = [Point]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND

    native_point = geometry.topLeft() + local_center
    hit = user32.WindowFromPoint(Point(native_point.x(), native_point.y()))
    hit_root = user32.GetAncestor(hit, 2)  # GA_ROOT
    overlay_hwnd = int(overlay.winId())
    print(
        f"point={native_point.x()},{native_point.y()} "
        f"overlay={overlay_hwnd:#x} hit={int(hit):#x} root={int(hit_root):#x}"
    )
    overlay.close()
    app.processEvents()
    if int(hit_root) != overlay_hwnd:
        raise SystemExit("FAIL: highlighted transparent area passes input through")
    print("PASS: highlighted transparent area belongs to capture overlay")


if __name__ == "__main__":
    main()

