"""Verify native mouse hit testing and sharp selected-area presentation."""

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

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


class DesktopFixture(QWidget):
    """A stable, dense text surface; the real desktop may change during a test."""

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#edf0f4'))
        painter.setPen(QColor('#151b25'))
        painter.setFont(QFont('Microsoft YaHei', 12))
        for y in range(22, self.height(), 26):
            painter.drawText(12, y, '清晰度测试 Screenshot Translator 2.0 — AI research and safety 0123456789 ' * 8)


def main():
    app = QApplication.instance() or QApplication([])
    screen = app.primaryScreen()
    geometry = screen.geometry()
    fixture = DesktopFixture()
    fixture.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
    fixture.setGeometry(geometry)
    fixture.show()
    fixture.raise_()
    QCursor.setPos(geometry.topLeft())
    QTest.qWait(300)
    pixmap = screen.grabWindow(0)
    print(f'geometry={geometry} captured={pixmap.size()} DPR={pixmap.devicePixelRatio()}')

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

    overlay_hwnd = int(overlay.winId())
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(Point)]
    user32.ClientToScreen.restype = wintypes.BOOL
    native_point = Point(round(local_center.x() * overlay.devicePixelRatioF()),
                         round(local_center.y() * overlay.devicePixelRatioF()))
    if not user32.ClientToScreen(overlay_hwnd, ctypes.byref(native_point)):
        raise SystemExit('FAIL: could not map selected center to native screen coordinates')

    def assert_overlay_hit(stage):
        hit = user32.WindowFromPoint(native_point)
        hit_root = user32.GetAncestor(hit, 2)  # GA_ROOT
        print(
            f"stage={stage} point={native_point.x},{native_point.y} "
            f"overlay={overlay_hwnd:#x} hit={int(hit):#x} root={int(hit_root):#x}"
        )
        if int(hit_root) != overlay_hwnd:
            raise SystemExit(f"FAIL: {stage} transparent area passes input through")

    assert_overlay_hit("hover")
    overlay.hover_window = QRect()
    QTest.mousePress(overlay, Qt.LeftButton, pos=test_rect.topLeft())
    QTest.mouseMove(overlay, test_rect.bottomRight())
    QTest.mouseRelease(overlay, Qt.LeftButton, pos=test_rect.bottomRight())
    if overlay.crop_rect != test_rect:
        raise SystemExit(f'FAIL: mouse drag did not select the expected area: {overlay.crop_rect}')
    overlay.update()
    QTest.qWait(250)
    app.processEvents()
    assert_overlay_hit("selected")

    composed = screen.grabWindow(0)
    original_image = pixmap.toImage()
    composed_image = composed.toImage()
    ratio = pixmap.devicePixelRatio()
    max_delta = 0
    for dx in range(-100, 101):
        for dy in range(-60, 61):
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
    fixture.close()
    app.processEvents()
    if max_delta > 1:
        raise SystemExit("FAIL: selected original area was repainted or softened")
    print("PASS: hover and selected areas stay sharp and own native mouse input")


if __name__ == "__main__":
    main()

