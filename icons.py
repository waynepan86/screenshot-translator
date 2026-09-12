# -*- coding: utf-8 -*-
"""Crisp vector toolbar icons drawn with QPainter.

Each icon is rendered at 2x device pixel ratio into a QIcon. Checkable
buttons get a second "On" state pixmap in the accent color, so the icon
recolors itself automatically when the button is checked.
"""
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import (QIcon, QPixmap, QPainter, QPen, QColor,
    QPainterPath, QPolygonF)

SIZE = 18  # logical icon size; buttons use setIconSize(QSize(18, 18))


def _make_pen(color, width=1.7):
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def _render(name, color):
    dpr = 2.0
    pm = QPixmap(int(SIZE * dpr), int(SIZE * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(_make_pen(color))
    p.setBrush(Qt.NoBrush)
    _DRAW[name](p, QColor(color))
    p.end()
    return pm


def make_icon(name, color="#E8EAED", checked_color=None):
    icon = QIcon()
    icon.addPixmap(_render(name, color), QIcon.Normal, QIcon.Off)
    if checked_color:
        icon.addPixmap(_render(name, checked_color), QIcon.Normal, QIcon.On)
    return icon


def _draw_pen(p, c):
    path = QPainterPath()
    path.moveTo(11.6, 3.6)
    path.lineTo(14.4, 6.4)
    path.lineTo(7.0, 13.8)
    path.lineTo(3.6, 14.4)
    path.lineTo(4.2, 11.0)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(10.2, 5.0), QPointF(13.0, 7.8))


def _draw_rect(p, c):
    p.drawRoundedRect(QRectF(3.8, 5.0, 10.4, 8.0), 1.6, 1.6)


def _draw_arrow(p, c):
    p.drawLine(QPointF(4.6, 13.4), QPointF(12.8, 5.2))
    p.drawLine(QPointF(7.6, 4.9), QPointF(13.1, 4.9))
    p.drawLine(QPointF(13.1, 4.9), QPointF(13.1, 10.4))


def _draw_text(p, c):
    p.drawLine(QPointF(4.6, 4.8), QPointF(13.4, 4.8))
    p.drawLine(QPointF(9.0, 4.8), QPointF(9.0, 13.6))
    p.drawLine(QPointF(7.0, 13.6), QPointF(11.0, 13.6))


def _draw_undo(p, c):
    path = QPainterPath()
    path.moveTo(13.2, 13.0)
    path.cubicTo(13.2, 8.2, 10.4, 6.2, 5.8, 6.2)
    p.drawPath(path)
    p.drawLine(QPointF(5.8, 6.2), QPointF(8.6, 3.6))
    p.drawLine(QPointF(5.8, 6.2), QPointF(8.6, 8.8))


def _draw_dot_s(p, c):
    p.setBrush(c)
    p.setPen(Qt.NoPen)
    p.drawEllipse(QPointF(9, 9), 1.6, 1.6)


def _draw_dot_m(p, c):
    p.setBrush(c)
    p.setPen(Qt.NoPen)
    p.drawEllipse(QPointF(9, 9), 2.7, 2.7)


def _draw_dot_l(p, c):
    p.setBrush(c)
    p.setPen(Qt.NoPen)
    p.drawEllipse(QPointF(9, 9), 3.9, 3.9)


def _draw_save(p, c):
    p.drawLine(QPointF(9.0, 3.8), QPointF(9.0, 10.6))
    p.drawLine(QPointF(6.2, 8.0), QPointF(9.0, 10.8))
    p.drawLine(QPointF(11.8, 8.0), QPointF(9.0, 10.8))
    path = QPainterPath()
    path.moveTo(4.2, 11.6)
    path.lineTo(4.2, 13.8)
    path.lineTo(13.8, 13.8)
    path.lineTo(13.8, 11.6)
    p.drawPath(path)


def _draw_cancel(p, c):
    p.drawLine(QPointF(5.4, 5.4), QPointF(12.6, 12.6))
    p.drawLine(QPointF(12.6, 5.4), QPointF(5.4, 12.6))


def _draw_confirm(p, c):
    pen = _make_pen(c, 2.0)
    p.setPen(pen)
    path = QPainterPath()
    path.moveTo(4.2, 9.6)
    path.lineTo(7.6, 12.8)
    path.lineTo(13.8, 5.4)
    p.drawPath(path)


def _draw_scan(p, c):
    # Corner brackets + text lines: "extract text from image"
    _corner(p, 3.6, 3.6, 1, 1)
    _corner(p, 14.4, 3.6, -1, 1)
    _corner(p, 3.6, 14.4, 1, -1)
    _corner(p, 14.4, 14.4, -1, -1)
    p.drawLine(QPointF(6.4, 7.4), QPointF(11.6, 7.4))
    p.drawLine(QPointF(6.4, 10.6), QPointF(10.0, 10.6))


def _corner(p, x0, y0, dx, dy):
    p.drawLine(QPointF(x0, y0), QPointF(x0 + 3.2 * dx, y0))
    p.drawLine(QPointF(x0, y0), QPointF(x0, y0 + 3.2 * dy))


def _draw_translate(p, c):
    # "A" and "文" side by side, minimalist: A-frame + horizontal strokes
    p.drawLine(QPointF(4.0, 12.6), QPointF(6.6, 5.4))
    p.drawLine(QPointF(6.6, 5.4), QPointF(9.2, 12.6))
    p.drawLine(QPointF(4.9, 10.2), QPointF(8.3, 10.2))
    p.drawLine(QPointF(10.6, 6.4), QPointF(14.6, 6.4))
    p.drawLine(QPointF(12.6, 4.8), QPointF(12.6, 6.4))
    p.drawLine(QPointF(11.0, 8.4), QPointF(14.2, 13.0))
    p.drawLine(QPointF(14.2, 8.4), QPointF(11.0, 13.0))


_DRAW = {
    "pen": _draw_pen,
    "rect": _draw_rect,
    "arrow": _draw_arrow,
    "text": _draw_text,
    "undo": _draw_undo,
    "dot_s": _draw_dot_s,
    "dot_m": _draw_dot_m,
    "dot_l": _draw_dot_l,
    "save": _draw_save,
    "cancel": _draw_cancel,
    "confirm": _draw_confirm,
    "scan": _draw_scan,
    "translate": _draw_translate,
}
