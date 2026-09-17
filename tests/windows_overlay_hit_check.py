"""Verify native mouse hit testing and sharp selected-area presentation."""

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
    pixmap = screen.grabWindow(0)

    overlay = CaptureWindow(pixmap, geometry, Config())
    overlay.draw_magnifier = lambda *_: None
    local_center = overlay.rect().center()
    test_rect = QRect(
        local_center.x() - 150, local_center.y() - 100, 300, 200
    )
    overlay.hover_window = test_rect
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
    overlay_hwnd = int(overlay.winId())

    def assert_overlay_hit(stage):
        hit = user32.WindowFromPoint(Point(native_point.x(), native_point.y()))
        hit_root = user32.GetAncestor(hit, 2)  # GA_ROOT
        print(
            f"stage={stage} point={native_point.x()},{native_point.y()} "
            f"overlay={overlay_hwnd:#x} hit={int(hit):#x} root={int(hit_root):#x}"
        )
        if int(hit_root) != overlay_hwnd:
            raise SystemExit(f"FAIL: {stage} transparent area passes input through")

    assert_overlay_hit("hover")
    overlay.hover_window = QRect()
    overlay.crop_rect = test_rect
    overlay.update()
    QTest.qWait(250)
    app.processEvents()
    assert_overlay_hit("selected")

    composed = screen.grabWindow(0)
    original_image = pixmap.toImage()
    composed_image = composed.toImage()
    ratio = pixmap.devicePixelRatio()
    max_delta = 0
    for dx in range(-100, 101, 20):
        for dy in range(-60, 61, 20):
            x = round((local_center.x() + dx) * ratio)
            y = round((local_center.y() + dy) * ratio)
            before = original_image.pixelColor(x, y)
            after = composed_image.pixelColor(x, y)
            max_delta = max(
                max_delta,
                abs(before.red() - after.red()),
                abs(before.green() - after.green()),
                abs(before.blue() - after.blue()),
            )
    print(f"selected-area max RGB delta={max_delta}")
    overlay.close()
    app.processEvents()
    if max_delta > 1:
        raise SystemExit("FAIL: selected original area was repainted or softened")
    print("PASS: hover and selected areas stay sharp and own native mouse input")


if __name__ == "__main__":
    main()

