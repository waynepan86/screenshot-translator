"""Plan bounded text before erasing pixels; dimensions use image pixels."""
from PySide6.QtCore import QRectF, QPointF
from PySide6.QtGui import QFont, QFontMetricsF, QTextLayout, QTextOption


def wrap(text, font, width):
    if '\n' in text:
        return [row for part in text.split('\n') for row in (wrap(part, font, width) if part else [''])]
    utf16 = text.encode('utf-16-le')
    layout = QTextLayout(text, font)
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    rows = []
    layout.beginLayout()
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(max(1, width))
        start = line.textStart() * 2
        end = (line.textStart() + line.textLength()) * 2
        rows.append(utf16[start:end].decode('utf-16-le').strip())
    layout.endLayout()
    return rows


def plan(paragraph, text, image_width, image_height):
    left = max(0, min(l['x'] for l in paragraph))
    top = max(0, min(l['y'] for l in paragraph))
    right = min(image_width, max(l['x'] + l['w'] for l in paragraph))
    bottom = min(image_height, max(l['y'] + l['h'] for l in paragraph))
    box = QRectF(left, top, right - left, bottom - top)
    avg_h = sum(l['h'] for l in paragraph) / len(paragraph)
    if box.width() <= 0 or box.height() <= 0:
        return None
    font = QFont('Microsoft YaHei')
    start = max(9, round(avg_h * .95))
    floor = max(9, round(avg_h * .60))
    for size in range(start, floor - 1, -1):
        font.setPixelSize(size)
        fm = QFontMetricsF(font)
        rows = wrap(text, font, box.width())
        ink_h = max((fm.tightBoundingRect(row).height() for row in rows), default=0)
        spacing = fm.lineSpacing()
        # Preserve the original line rhythm when translation keeps its rows.
        if len(rows) == len(paragraph) and len(rows) > 1:
            source_spacing = (bottom - top - avg_h) / (len(rows) - 1)
            spacing = max(ink_h, source_spacing)
        total_h = ink_h + max(0, len(rows) - 1) * spacing
        if rows and total_h <= box.height() + .1 and all(fm.horizontalAdvance(row) <= box.width() + .1 for row in rows):
            centers = [l['x'] + l['w'] / 2 for l in paragraph]
            centered = len(paragraph) > 1 and max(centers) - min(centers) < avg_h * .4 and max(l['x'] for l in paragraph) - left > avg_h * .5
            align = 'center' if centered else 'left'
            return dict(box=box, font=QFont(font), rows=rows, height=total_h, spacing=spacing, align=align)
    return None


def draw(painter, layout, color):
    painter.save()
    painter.setClipRect(layout['box'])
    painter.setFont(layout['font'])
    painter.setPen(color)
    fm = QFontMetricsF(layout['font'])
    top = layout['box'].top() + (layout['box'].height() - layout['height']) / 2
    for i, row in enumerate(layout['rows']):
        ink = fm.tightBoundingRect(row)
        x = layout['box'].left()
        if layout['align'] == 'center':
            x += (layout['box'].width() - fm.horizontalAdvance(row)) / 2
        painter.drawText(QPointF(x, top - ink.top() + i * layout['spacing']), row)
    painter.restore()
