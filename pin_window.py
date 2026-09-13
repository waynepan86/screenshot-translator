"""Independent image pins; closing the capture never closes its pin."""
from PySide6.QtCore import Qt, QPoint, QRect, Signal
from PySide6.QtGui import QPainter, QGuiApplication
from PySide6.QtWidgets import QWidget, QMenu

_pins = set()


class PinWindow(QWidget):
    def __init__(self, pixmap, original, position):
        super().__init__()
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.image = pixmap.copy()
        self.original = original.copy()
        self.peek = False
        self.drag = None
        self.zoom = 1.0
        self.setToolTip('拖动移动 · 滚轮缩放 · 空格查看原图 · 双击关闭 · 右键更多操作')
        self.resize(self.image.deviceIndependentSize().toSize())
        screen = QGuiApplication.screenAt(position) or QGuiApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            self.zoom = min(1., available.width()/self.width(), available.height()/self.height())
            self.resize(self.image.deviceIndependentSize().toSize() * self.zoom)
            position = QPoint(max(available.left(), min(position.x(), available.right()-self.width()+1)),
                              max(available.top(), min(position.y(), available.bottom()-self.height()+1)))
        self.move(position)
        _pins.add(self)
        self.destroyed.connect(lambda: _pins.discard(self))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawPixmap(self.rect(), self.original if self.peek else self.image)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag = event.globalPosition().toPoint() - self.pos()
            self.setFocus()

    def mouseMoveEvent(self, event):
        if self.drag is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag)

    def mouseReleaseEvent(self, event):
        self.drag = None

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.close()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            self.setWindowOpacity(max(.2, min(1., self.windowOpacity() + (.05 if event.angleDelta().y()>0 else -.05))))
        elif event.angleDelta().y():
            anchor = event.position().toPoint()
            old_size = self.size()
            self.zoom = max(.15, min(4., self.zoom * (1.1 if event.angleDelta().y()>0 else 1/1.1)))
            self.resize(self.image.deviceIndependentSize().toSize() * self.zoom)
            self.move(self.pos() + anchor - QPoint(round(anchor.x()*self.width()/old_size.width()), round(anchor.y()*self.height()/old_size.height())))
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            self.peek = True; self.update()
        elif event.key() == Qt.Key_Escape:
            self.close()
        elif event.key() == Qt.Key_C and event.modifiers() & Qt.ControlModifier:
            QGuiApplication.clipboard().setPixmap(self.image)
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self.peek = False; self.update()

    def focusOutEvent(self, event):
        self.peek = False; self.drag = None; self.update()
        super().focusOutEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction('复制图片', lambda: QGuiApplication.clipboard().setPixmap(self.image))
        menu.addAction('恢复原始大小', self.reset_size)
        menu.addAction('关闭贴图', self.close)
        menu.exec(event.globalPos())

    def reset_size(self):
        self.zoom = 1.; self.resize(self.image.deviceIndependentSize().toSize())
