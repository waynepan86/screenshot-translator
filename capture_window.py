import sys
import os
import math
import re
from PySide6.QtWidgets import QWidget, QLineEdit, QFileDialog, QMessageBox, QProgressDialog
from PySide6.QtCore import Qt, QPoint, QRect, QSize, QTimer, QThread, Signal
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QFont, QPixmap, QImage, QCursor, QFontMetrics, QGuiApplication, QLinearGradient, QRegion

from toolbar import AnnotationToolbar
from review_panel import OCRPanel
import translation_layout
import translation_service
import tempfile
import ocr
import translator

# Strong references while a hidden, cancelled window's worker finishes.
_retired_windows = []

# Drawing shapes definitions
class PenShape:
    def __init__(self, color, width):
        self.points = []
        self.color = color
        self.width = width
        
    def add_point(self, point):
        self.points.append(point)
        
    def draw(self, painter):
        if len(self.points) < 2:
            return
        painter.setPen(QPen(self.color, self.width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for i in range(len(self.points) - 1):
            painter.drawLine(self.points[i], self.points[i+1])

class RectShape:
    def __init__(self, start, end, color, width):
        self.start = start
        self.end = end
        self.color = color
        self.width = width
        
    def draw(self, painter):
        painter.setPen(QPen(self.color, self.width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRect(self.start, self.end))


class CoverShape(RectShape):
    def draw(self, painter):
        painter.fillRect(QRect(self.start, self.end).normalized(), self.color)

class ArrowShape:
    def __init__(self, start, end, color, width):
        self.start = start
        self.end = end
        self.color = color
        self.width = width
        
    def draw(self, painter):
        painter.setPen(QPen(self.color, self.width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(QBrush(self.color))
        painter.drawLine(self.start, self.end)
        
        # Calculate arrowhead lines
        dx = self.end.x() - self.start.x()
        dy = self.end.y() - self.start.y()
        angle = math.atan2(dy, dx)
        arrow_len = max(self.width * 3, 12)
        arrow_angle = math.pi / 6 # 30 degrees
        
        p1 = self.end - QPoint(int(arrow_len * math.cos(angle - arrow_angle)), int(arrow_len * math.sin(angle - arrow_angle)))
        p2 = self.end - QPoint(int(arrow_len * math.cos(angle + arrow_angle)), int(arrow_len * math.sin(angle + arrow_angle)))
        
        from PySide6.QtGui import QPolygon
        poly = QPolygon([self.end, p1, p2])
        painter.drawPolygon(poly)

class TextShape:
    def __init__(self, pos, text, color, size):
        self.pos = pos
        self.text = text
        self.color = color
        self.size = size
        
    def draw(self, painter):
        painter.setPen(QPen(self.color))
        font = QFont("Microsoft YaHei", self.size)
        painter.setFont(font)
        painter.drawText(self.pos, self.text)


class OCRThread(QThread):
    progress = Signal(str)
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, temp_img_path, scale_factor=1.0, review=True):
        super().__init__()
        self.temp_img_path = temp_img_path
        self.review = review
        self.scale_factor = scale_factor

    def run(self):
        try:
            result = ocr.run_ocr_sync(self.temp_img_path, scale_factor=self.scale_factor, review=self.review, progress=self.progress.emit)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class TranslationThread(QThread):
    progress = Signal(int, int)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, texts, to_lang=None, force=False, context=None):
        super().__init__()
        self.texts = texts
        self.force = force
        self.context = context
        self.to_lang = to_lang

    def run(self):
        try:
            result = translation_service.translate(self.texts, self.to_lang, self.progress.emit, self.force, self.context)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class CaptureWindow(QWidget):
    capture_done = Signal(QPixmap)
    capture_cancelled = Signal()

    def __init__(self, background_pixmap, combined_rect, config_manager):
        super().__init__()
        self.bg_pixmap = background_pixmap
        self.combined_rect = combined_rect
        self.config = config_manager
        
        # Window attributes
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.BypassWindowManagerHint)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setGeometry(self.combined_rect)
        self.setMouseTracking(True)
        
        # State variables
        self.crop_rect = QRect()
        self.is_selecting = False
        self.is_resizing = False
        self.is_moving = False
        self.drag_start = QPoint()
        self.drag_end = QPoint()
        self.window_bounds = []
        self.hover_window = QRect()
        self.click_window = QRect()
        
        # Resize handle states
        self.active_handle = None # 'TL', 'T', 'TR', 'L', 'R', 'BL', 'B', 'BR'
        self.handle_size = 8
        self.hover_handle = None
        
        # Drawing states
        self.active_tool = None # 'pen', 'rect', 'arrow', 'text'
        self.draw_color = QColor(255, 59, 48) # Default Red
        self.draw_thickness = 4
        self.shapes = [] # Undo history stack
        self.current_shape = None
        
        # Text input tool variables
        self.text_input = None
        self.text_pos = QPoint()
        
        # OCR / Translation results cached
        self.ocr_result = None
        self.translated_pixmap = None
        self.is_translated_view = False
        self.is_loading = False
        self.loading_msg = ""
        self.paragraphs = []
        self.blocks = []
        self.peek_original = False
        self._closing = False
        
        # Sub-panels
        self.toolbar = None
        self.ocr_panel = None
        
        # Set cursor to Cross (selecting mode)
        self.setCursor(Qt.CrossCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 1. Draw stitched desktop image
        painter.drawPixmap(0, 0, self.bg_pixmap)
        
        # If no crop rect selected, draw full screen translucent mask
        if self.crop_rect.isEmpty():
            painter.fillRect(self.rect(), QColor(0, 0, 0, 100))
            if not self.is_selecting and not self.hover_window.isEmpty():
                painter.drawPixmap(self.hover_window, self.bg_pixmap, self.hover_window)
                painter.setPen(QPen(QColor(26,115,232),1.5))
                painter.drawRect(self.hover_window)
            # Draw pixel magnifier
            if self.is_selecting or not self.is_moving:
                self.draw_magnifier(painter, QCursor.pos() - self.combined_rect.topLeft())
            return
            
        # 2. Draw mask outside the crop selection
        mask_color = QColor(0, 0, 0, 100)
        # Top mask
        painter.fillRect(0, 0, self.width(), self.crop_rect.top(), mask_color)
        # Bottom mask
        painter.fillRect(0, self.crop_rect.bottom() + 1, self.width(), self.height() - self.crop_rect.bottom() - 1, mask_color)
        # Left mask
        painter.fillRect(0, self.crop_rect.top(), self.crop_rect.left(), self.crop_rect.height(), mask_color)
        # Right mask
        painter.fillRect(self.crop_rect.right() + 1, self.crop_rect.top(), self.width() - self.crop_rect.right() - 1, self.crop_rect.height(), mask_color)
        
        # 3. Draw crop border
        border_pen = QPen(QColor(26, 115, 232), 1.5, Qt.SolidLine)
        painter.setPen(border_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.crop_rect)
        
        # 4. If in Translated View, draw the translated crop instead of original crop
        if self.is_translated_view and self.translated_pixmap and not self.peek_original:
            painter.drawPixmap(self.crop_rect.topLeft(), self.translated_pixmap)
            
        # 5. Draw Annotations on top of crop area
        painter.save()
        # Clip painter to crop region so drawings don't bleed out
        painter.setClipRect(self.crop_rect)
        for shape in self.shapes:
            shape.draw(painter)
        if self.current_shape:
            self.current_shape.draw(painter)
        painter.restore()
        
        # 6. Draw resize handles (only if not drawing with annotation tools)
        if not self.active_tool:
            self.draw_resize_handles(painter)
            
        # 7. Draw crop dimension text label above selection
        self.draw_dimension_label(painter)
        
        # 8. Draw loading spinner overlay if async task active
        if self.is_loading:
            self.draw_loading_overlay(painter)
            
        # 9. Draw magnifier lens if selecting initial region
        if self.is_selecting:
            self.draw_magnifier(painter, QCursor.pos() - self.combined_rect.topLeft())

    def draw_resize_handles(self, painter):
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.setBrush(QBrush(QColor(26, 115, 232)))
        
        handles = self.get_handle_rects()
        for rect in handles.values():
            painter.drawRect(rect)

    def draw_dimension_label(self, painter):
        w, h = self.crop_rect.width(), self.crop_rect.height()
        dim_str = f"{w} × {h}"
        
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Medium))
        fm = QFontMetrics(painter.font())
        rect_text = fm.boundingRect(dim_str)
        
        padding_x = 8
        padding_y = 4
        label_w = rect_text.width() + padding_x * 2
        label_h = rect_text.height() + padding_y * 2
        
        # Place label above top-left of crop rect, or inside if too close to top
        label_x = self.crop_rect.left()
        label_y = self.crop_rect.top() - label_h - 4
        if label_y < 0:
            label_y = self.crop_rect.top() + 4
            
        # Background bubble
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(32, 33, 36, 220)))
        painter.drawRoundedRect(QRect(label_x, label_y, label_w, label_h), 4, 4)
        
        # Text
        painter.setPen(QPen(QColor(241, 243, 244)))
        painter.drawText(label_x + padding_x, label_y + padding_y + fm.ascent(), dim_str)

    def draw_loading_overlay(self, painter):
        # Semi-transparent overlay inside crop region
        painter.save()
        painter.setClipRect(self.crop_rect)
        painter.fillRect(self.crop_rect, QColor(0, 0, 0, 160))
        
        # Draw text
        painter.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Medium))
        painter.setPen(QPen(QColor(255, 255, 255)))
        fm = QFontMetrics(painter.font())
        text_w = fm.horizontalAdvance(self.loading_msg)
        
        cx = self.crop_rect.left() + self.crop_rect.width() // 2
        cy = self.crop_rect.top() + self.crop_rect.height() // 2
        
        painter.drawText(cx - text_w // 2, cy + fm.ascent() // 2, self.loading_msg)
        painter.restore()

    def draw_magnifier(self, painter, pos):
        # pos is coordinates relative to widget
        raw_x = pos.x() + self.combined_rect.left()
        raw_y = pos.y() + self.combined_rect.top()
        
        # Get color of the pixel at current cursor
        qimg = self.bg_pixmap.toImage()
        if not (0 <= pos.x() < qimg.width() and 0 <= pos.y() < qimg.height()):
            return
        center_color = qimg.pixelColor(pos.x(), pos.y())
        
        # Dimensions of magnifier
        lens_size = 120
        lens_cells = 13 # Must be odd number
        cell_size = lens_size // lens_cells
        
        # Center cell index
        center_cell = lens_cells // 2
        
        # Position magnifier bubble below/right of cursor with offset
        mag_x = pos.x() + 20
        mag_y = pos.y() + 20
        
        # Bound within window
        if mag_x + lens_size + 10 > self.width():
            mag_x = pos.x() - lens_size - 20
        if mag_y + lens_size + 60 > self.height():
            mag_y = pos.y() - lens_size - 60
            
        # Draw magnifier boundary box
        painter.save()
        
        # Frame background
        border_rect = QRect(mag_x - 2, mag_y - 2, lens_size + 4, lens_size + 45)
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.setBrush(QBrush(QColor(32, 33, 36, 240)))
        painter.drawRoundedRect(border_rect, 6, 6)
        
        # Clip magnified pixel drawing inside the lens rect
        lens_rect = QRect(mag_x, mag_y, lens_size, lens_size)
        painter.setClipRect(lens_rect)
        
        # Draw magnified pixels
        for dx in range(lens_cells):
            for dy in range(lens_cells):
                cell_x = pos.x() + dx - center_cell
                cell_y = pos.y() + dy - center_cell
                
                # Check bounds
                if 0 <= cell_x < qimg.width() and 0 <= cell_y < qimg.height():
                    pixel_c = qimg.pixelColor(cell_x, cell_y)
                else:
                    pixel_c = QColor(0, 0, 0)
                    
                painter.fillRect(mag_x + dx * cell_size, mag_y + dy * cell_size, cell_size, cell_size, QBrush(pixel_c))
                
        # Draw crosshair over center cell
        painter.setPen(QPen(QColor(26, 115, 232, 180), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(mag_x + center_cell * cell_size, mag_y + center_cell * cell_size, cell_size, cell_size)
        
        painter.restore()
        
        # Draw metadata text (RGB, HEX, Coord)
        painter.setFont(QFont("Consolas", 8))
        rgb_str = f"RGB: ({center_color.red()}, {center_color.green()}, {center_color.blue()})"
        hex_str = f"HEX: {center_color.name().upper()}"
        pos_str = f"POS: ({raw_x}, {raw_y})"
        
        painter.setPen(QPen(QColor(241, 243, 244)))
        painter.drawText(mag_x + 4, mag_y + lens_size + 12, pos_str)
        painter.drawText(mag_x + 4, mag_y + lens_size + 24, rgb_str)
        painter.drawText(mag_x + 4, mag_y + lens_size + 36, hex_str)

    def get_handle_rects(self):
        r = self.crop_rect
        s = self.handle_size
        hs = s // 2
        
        return {
            'TL': QRect(r.left() - hs, r.top() - hs, s, s),
            'T': QRect(r.center().x() - hs, r.top() - hs, s, s),
            'TR': QRect(r.right() - hs, r.top() - hs, s, s),
            'L': QRect(r.left() - hs, r.center().y() - hs, s, s),
            'R': QRect(r.right() - hs, r.center().y() - hs, s, s),
            'BL': QRect(r.left() - hs, r.bottom() - hs, s, s),
            'B': QRect(r.center().x() - hs, r.bottom() - hs, s, s),
            'BR': QRect(r.right() - hs, r.bottom() - hs, s, s),
        }

    # Mouse Events
    def mousePressEvent(self, event):
        if self.is_loading:
            return
        pos = event.position().toPoint()
        
        # If writing text, confirm current text and close editor
        if self.text_input and self.text_input.isVisible():
            self.confirm_text_input()
            return

        if self.crop_rect.isEmpty():
            # First click: Start selection
            self.is_selecting = True
            self.drag_start = pos
            self.drag_end = pos
            self.click_window = next((r for r in self.window_bounds if r.contains(pos)),QRect())
            self.crop_rect = QRect(pos, QSize(0, 0))
            self.setCursor(Qt.CrossCursor)
        else:
            # Check if clicked on resize handle
            self.active_handle = self.get_handle_at(pos)
            if self.active_handle:
                self.is_resizing = True
                self.drag_start = pos
            elif self.crop_rect.contains(pos):
                if self.active_tool:
                    # Drawing mode: Draw on canvas
                    self.is_selecting = False
                    self.start_drawing(pos)
                else:
                    # Select tool is None: Move crop region
                    self.is_moving = True
                    self.drag_start = pos
                    self.drag_start_rect = QRect(self.crop_rect)
                    self.setCursor(Qt.SizeAllCursor)
            else:
                # Clicked outside selection: Reset selection and start new select
                if self.toolbar:
                    self.toolbar.hide()
                if self.ocr_panel:
                    self.ocr_panel.close()
                    self.ocr_panel = None
                self.blocks = []
                self.ocr_result = None
                self.translated_pixmap = None
                self.is_translated_view = False
                
                self.crop_rect = QRect()
                self.shapes.clear()
                self.is_selecting = True
                self.drag_start = pos
                self.drag_end = pos
                self.setCursor(Qt.CrossCursor)
        self.update()

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        
        # 1. Selecting initial crop
        if self.is_selecting:
            self.drag_end = pos
            # Keep boundaries inside widget
            x = max(0, min(pos.x(), self.width()))
            y = max(0, min(pos.y(), self.height()))
            self.crop_rect = QRect(self.drag_start, QPoint(x, y)).normalized()
            self.update()
            
        # 2. Resizing crop selection
        elif self.is_resizing and self.active_handle:
            delta = pos - self.drag_start
            previous_crop = QRect(self.crop_rect)
            self.resize_crop(delta)
            if self.crop_rect != previous_crop:
                self.invalidate_recognition()
            self.drag_start = pos
            self.update()
            self.reposition_toolbar()
            
        # 3. Moving crop selection
        elif self.is_moving:
            delta = pos - self.drag_start
            new_rect = self.drag_start_rect.translated(delta)
            # Bound within window limits
            if new_rect.left() < 0:
                new_rect.moveLeft(0)
            if new_rect.right() >= self.width():
                new_rect.moveLeft(self.width() - new_rect.width())
            if new_rect.top() < 0:
                new_rect.moveTop(0)
            if new_rect.bottom() >= self.height():
                new_rect.moveTop(self.height() - new_rect.height())
                
            if new_rect != self.crop_rect:
                self.invalidate_recognition()
            self.crop_rect = new_rect
            self.update()
            self.reposition_toolbar()
            
        # 4. Drawing annotation shapes
        elif self.current_shape:
            # Keep points bound inside the crop rect
            bounded_pos = self.clamp_point_to_crop(pos)
            if self.active_tool == 'pen':
                self.current_shape.add_point(bounded_pos)
            else:
                self.current_shape.end = bounded_pos
            self.update()
            
        # 5. Standard cursor hovers
        else:
            if self.crop_rect.isEmpty():
                self.hover_window = next((r for r in self.window_bounds if r.contains(pos)),QRect())
            if not self.crop_rect.isEmpty() and not self.active_tool:
                # Update hover handle & cursor
                handle = self.get_handle_at(pos)
                self.hover_handle = handle
                if handle:
                    if handle in ['TL', 'BR']:
                        self.setCursor(Qt.SizeFDiagCursor)
                    elif handle in ['TR', 'BL']:
                        self.setCursor(Qt.SizeBDiagCursor)
                    elif handle in ['T', 'B']:
                        self.setCursor(Qt.SizeVerCursor)
                    elif handle in ['L', 'R']:
                        self.setCursor(Qt.SizeHorCursor)
                elif self.crop_rect.contains(pos):
                    self.setCursor(Qt.SizeAllCursor)
                else:
                    self.setCursor(Qt.ArrowCursor)
            elif self.active_tool:
                if self.crop_rect.contains(pos):
                    self.setCursor(Qt.CrossCursor)
                else:
                    self.setCursor(Qt.ArrowCursor)
            self.update()

    def mouseReleaseEvent(self, event):
        pos = event.position().toPoint()
        
        if self.is_selecting:
            self.is_selecting = False
            if (pos-self.drag_start).manhattanLength() <= 4 and not self.click_window.isEmpty():
                self.crop_rect = self.click_window.intersected(self.rect())
            self.click_window = QRect()
            # If the crop is very tiny, consider it a fullscreen selection (or cancel)
            if self.crop_rect.width() < 10 or self.crop_rect.height() < 10:
                self.crop_rect = QRect()
                self.setCursor(Qt.CrossCursor)
            else:
                self.show_toolbar()
                self.setCursor(Qt.ArrowCursor)
                
        elif self.is_resizing:
            self.is_resizing = False
            self.active_handle = None
            self.reposition_toolbar()
            
        elif self.is_moving:
            self.is_moving = False
            self.reposition_toolbar()
            
        elif self.current_shape:
            # Finished drawing current shape
            if isinstance(self.current_shape, CoverShape):
                # Future OCR must not send text hidden by a cover. Keep an
                # already rendered translation available for export.
                self.ocr_result = None
                self.paragraphs = []
                self.blocks = []
                self.close_ocr_panel()
            self.shapes.append(self.current_shape)
            self.current_shape = None
            self.update()
            
        self.update()

    def get_handle_at(self, pos):
        if self.crop_rect.isEmpty():
            return None
        handles = self.get_handle_rects()
        for name, rect in handles.items():
            if rect.contains(pos):
                return name
        return None

    def resize_crop(self, delta):
        r = self.crop_rect
        h = self.active_handle
        dx, dy = delta.x(), delta.y()
        
        left, top, right, bottom = r.left(), r.top(), r.right(), r.bottom()
        
        # Apply deltas based on which handle is dragged
        if 'TL' in h or 'L' in h:
            left = max(0, min(left + dx, right - 10))
        if 'TR' in h or 'R' in h:
            right = min(self.width() - 1, max(right + dx, left + 10))
        if 'TL' in h or 'T' in h or 'TR' in h:
            top = max(0, min(top + dy, bottom - 10))
        if 'BL' in h or 'B' in h or 'BR' in h:
            bottom = min(self.height() - 1, max(bottom + dy, top + 10))
            
        self.crop_rect = QRect(QPoint(left, top), QPoint(right, bottom))

    def clamp_point_to_crop(self, point):
        # Clamps a point inside the crop boundary
        x = max(self.crop_rect.left(), min(point.x(), self.crop_rect.right()))
        y = max(self.crop_rect.top(), min(point.y(), self.crop_rect.bottom()))
        return QPoint(x, y)

    # Drawing Annotation methods
    def start_drawing(self, pos):
        bounded_pos = self.clamp_point_to_crop(pos)
        if self.active_tool == 'pen':
            self.current_shape = PenShape(self.draw_color, self.draw_thickness)
            self.current_shape.add_point(bounded_pos)
        elif self.active_tool == 'rect':
            self.current_shape = RectShape(bounded_pos, bounded_pos, self.draw_color, self.draw_thickness)
        elif self.active_tool == 'cover':
            self.current_shape = CoverShape(bounded_pos, bounded_pos, self.draw_color, self.draw_thickness)
        elif self.active_tool == 'arrow':
            self.current_shape = ArrowShape(bounded_pos, bounded_pos, self.draw_color, self.draw_thickness)
        elif self.active_tool == 'text':
            self.text_pos = bounded_pos
            self.spawn_text_editor(bounded_pos)

    def spawn_text_editor(self, pos):
        if self.text_input:
            self.text_input.deleteLater()
            
        self.text_input = QLineEdit(self)
        self.text_input.setFont(QFont("Microsoft YaHei", 12))
        
        # Stylize the editor input
        self.text_input.setStyleSheet(f"""
            QLineEdit {{
                color: {self.draw_color.name()};
                background: rgba(30, 30, 30, 0.8);
                border: 1px dashed {self.draw_color.name()};
                border-radius: 3px;
                padding: 2px;
            }}
        """)
        
        # Position editor on top of the clicked coordinate,
        # clamped so it never gets cut off by the window edge
        editor_w, editor_h = 150, 26
        ex = max(0, min(pos.x(), self.width() - editor_w - 4))
        ey = max(0, min(pos.y() - 12, self.height() - editor_h - 4))
        self.text_input.setGeometry(ex, ey, editor_w, editor_h)
        self.text_input.show()
        self.text_input.setFocus()
        
        # Hook text edit signals
        self.text_input.returnPressed.connect(self.confirm_text_input)
        self.text_input.editingFinished.connect(self.confirm_text_input)

    def confirm_text_input(self):
        if not self.text_input:
            return
            
        txt = self.text_input.text().strip()
        if txt:
            # Save the text shape to stack
            shape = TextShape(self.text_pos, txt, self.draw_color, 12)
            self.shapes.append(shape)
            
        self.text_input.hide()
        self.text_input.deleteLater()
        self.text_input = None
        self.update()

    # Toolbar management
    def show_toolbar(self):
        if not self.toolbar:
            self.toolbar = AnnotationToolbar(self)
            # Connecting Toolbar actions to local methods
            self.toolbar.tool_changed.connect(self.on_tool_changed)
            self.toolbar.color_changed.connect(self.on_color_changed)
            self.toolbar.thickness_changed.connect(self.on_thickness_changed)
            self.toolbar.undo_triggered.connect(self.on_undo)
            self.toolbar.ocr_triggered.connect(self.run_ocr)
            self.toolbar.translate_toggled.connect(self.on_translate_toggled)
            self.toolbar.save_triggered.connect(self.save_screenshot_dialog)
            self.toolbar.cancel_triggered.connect(self.close_and_cancel)
            self.toolbar.confirm_triggered.connect(self.confirm_to_clipboard)
            self.toolbar.pin_triggered.connect(self.pin_to_screen)
            
        self.reposition_toolbar()
        self.toolbar.show()

    def get_local_screen_rect(self):
        # Geometry (in widget-local coordinates) of the monitor containing the
        # selection, so floating panels stay on the same screen as the crop.
        global_center = self.combined_rect.topLeft() + self.crop_rect.center()
        screen = QGuiApplication.screenAt(global_center)
        if not screen:
            screen = QGuiApplication.primaryScreen()
        geo = screen.geometry()
        return QRect(geo.topLeft() - self.combined_rect.topLeft(), geo.size())

    def reposition_toolbar(self):
        if not self.toolbar or self.crop_rect.isEmpty():
            return
            
        self.toolbar.adjustSize()
        tb_w = self.toolbar.width()
        tb_h = self.toolbar.height()
        
        screen_rect = self.get_local_screen_rect()
        margin = 8
        
        # Snipaste-style: right-align with the selection's bottom edge,
        # clamped inside the monitor that contains the selection.
        cx = self.crop_rect.right() - tb_w + 1
        cx = max(screen_rect.left() + margin, min(cx, screen_rect.right() - tb_w - margin))
        
        # Prefer below the selection; then above; otherwise inside its bottom edge.
        cy = self.crop_rect.bottom() + margin
        if cy + tb_h > screen_rect.bottom() - margin:
            cy = self.crop_rect.top() - tb_h - margin
            if cy < screen_rect.top() + margin:
                cy = self.crop_rect.bottom() - tb_h - margin
                
        # Offset by workspace global coordinate
        global_pos = self.combined_rect.topLeft() + QPoint(cx, cy)
        self.toolbar.move(global_pos)

    # Handlers for signals from Toolbar
    def on_tool_changed(self, tool_name):
        # Confirm pending text editor if we change tools
        if self.text_input:
            self.confirm_text_input()
            
        self.active_tool = tool_name if tool_name else None
        
        if self.active_tool:
            self.setCursor(Qt.CrossCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def on_color_changed(self, color):
        self.draw_color = color
        # Update current active text editor color if visible
        if self.text_input:
            self.text_input.setStyleSheet(f"""
                QLineEdit {{
                    color: {self.draw_color.name()};
                    background: rgba(30, 30, 30, 0.8);
                    border: 1px dashed {self.draw_color.name()};
                    border-radius: 3px;
                    padding: 2px;
                }}
            """)

    def on_thickness_changed(self, size):
        self.draw_thickness = size

    def on_undo(self):
        if self.is_loading:
            return
        if self.shapes:
            removed = self.shapes.pop()
            if isinstance(removed, CoverShape):
                self.ocr_result = None
                self.paragraphs = []
                self.blocks = []
                self.close_ocr_panel()
            self.update()

    def close_and_cancel(self):
        if self.ocr_panel:
            self.ocr_panel.close()
        if self.toolbar:
            self.toolbar.close()
        self.capture_cancelled.emit()
        self.close()

    def grab_cropped_pixmap(self):
        # Stitches original pixmap along with current annotation shapes and active translated view.
        # But we do NOT bake handles, borders, or translucent screen masks.
        
        # Create a QPixmap matching the crop dimensions
        crop_pixmap = QPixmap(self.crop_rect.size())
        crop_pixmap.fill(Qt.transparent)
        
        painter = QPainter(crop_pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Offset drawings back to local (0, 0) coordinates of the crop
        offset = -self.crop_rect.topLeft()
        
        # Draw background image (or translated view)
        if self.is_translated_view and self.translated_pixmap:
            painter.drawPixmap(0, 0, self.translated_pixmap)
        else:
            painter.drawPixmap(offset, self.bg_pixmap)
            
        # Draw shapes offset
        painter.translate(offset)
        for shape in self.shapes:
            shape.draw(painter)
            
        painter.end()
        return crop_pixmap

    def pin_to_screen(self):
        if self.is_loading or self.crop_rect.isEmpty():
            return
        if self.text_input:
            self.confirm_text_input()
        from pin_window import PinWindow
        current = self.grab_cropped_pixmap()
        translated = self.is_translated_view
        self.is_translated_view = False
        original = self.grab_cropped_pixmap()
        self.is_translated_view = translated
        pin = PinWindow(current, original, self.mapToGlobal(self.crop_rect.topLeft()))
        pin.show()
        self.close_and_cancel()

    def confirm_to_clipboard(self):
        if self.is_loading:
            return
        if self.text_input:
            self.confirm_text_input()
            
        cropped = self.grab_cropped_pixmap()
        
        # Copy to system clipboard
        from PySide6.QtGui import QGuiApplication
        clipboard = QGuiApplication.clipboard()
        clipboard.setPixmap(cropped)
        
        # Check if we have settings default save path, and save a backup there if wanted?
        # User requested: "截图完成后：自动将截图保存到系统剪贴板，可直接粘贴使用；"
        # "截图编辑状态下，所有操作（标注、提取、翻译）都不自动保存文件、不关闭编辑界面；"
        # Since they confirmed, we save to clipboard and exit.
        
        self.capture_done.emit(cropped)
        
        if self.ocr_panel:
            self.ocr_panel.close()
        if self.toolbar:
            self.toolbar.close()
        self.close()

    def save_screenshot_dialog(self):
        if self.text_input:
            self.confirm_text_input()
            
        cropped = self.grab_cropped_pixmap()
        
        # Get path from config
        default_dir = self.config.get("save_dir")
        if not os.path.exists(default_dir):
            default_dir = os.path.expanduser("~")
            
        import time
        default_name = f"Screenshot_{time.strftime('%Y%m%d_%H%M%S')}.png"
        default_path = os.path.join(default_dir, default_name)
        
        save_path, _ = QFileDialog.getSaveFileName(
            self, "保存截图", default_path, "PNG Images (*.png);;JPEG Images (*.jpg);;All Files (*)"
        )
        
        if save_path:
            try:
                cropped.save(save_path, "PNG")
                # Do NOT close window after manual save, as per interactive rules:
                # "截图编辑状态下，所有操作都不自动保存文件、不关闭编辑界面"
                # Wait, manual save is an explicit user confirmation of saving, but does it close the window?
                # The user request: "支持手动保存、取消截图、确认截图到剪贴板；"
                # Standard tools close after saving, but let's keep it open, or show a small confirmation toast.
                # Actually, standard behavior: manual saving completes the capture and closes, but let's just save.
                # Let's prompt or show toast. Let's just keep editing mode open so they can continue, or close.
                # "截图编辑状态下，所有操作（标注、提取、翻译）都不自动保存文件、不关闭编辑界面；支持手动保存、取消截图、确认截图到剪贴板"
                # Let's keep it open, so they can manually save and then click Checkmark (confirm) to close, or cancel.
                pass
            except Exception as e:
                QMessageBox.critical(self, "保存失败", f"无法保存文件: {e}")

    def prepare_ocr_image(self):
        # Grabs the crop area, preprocesses it for the active OCR engine and
        # returns (path, scale_factor used).
        fd, temp_raw_path = tempfile.mkstemp(suffix=".png", prefix="snip_raw_")
        os.close(fd)
        crop_pixmap = self.bg_pixmap.copy(self.crop_rect)
        painter = QPainter(crop_pixmap)
        painter.translate(-self.crop_rect.topLeft())
        for shape in self.shapes:
            if isinstance(shape, CoverShape):
                shape.draw(painter)
        painter.end()
        crop_pixmap.save(temp_raw_path, "PNG")
        
        fd, temp_ocr_path = tempfile.mkstemp(suffix=".png", prefix="snip_ocr_")
        os.close(fd)
        
        from PIL import Image, ImageEnhance
        try:
            with Image.open(temp_raw_path) as img:
                if ocr.is_rapidocr_available():
                    # RapidOCR: keep color, upscale 2.5x for small text but cap
                    # the long side at its detection limit (2400px) so the
                    # detector never has to downscale (fast and accurate)
                    max_side = max(img.width, img.height)
                    scale_factor = max(1.0, min(2.5, 2400 / max_side))
                    if scale_factor > 1.01:
                        out = img.resize((int(img.width * scale_factor), int(img.height * scale_factor)), Image.Resampling.LANCZOS)
                    else:
                        scale_factor = 1.0
                        out = img.copy()
                else:
                    # Windows OCR: 2.5x Lanczos upscale + grayscale + mild
                    # contrast boost works best for its engine
                    scale_factor = 2.5
                    out = img.resize((int(img.width * scale_factor), int(img.height * scale_factor)), Image.Resampling.LANCZOS)
                    out = out.convert('L')
                    out = ImageEnhance.Contrast(out).enhance(1.2)
                    
            out.save(temp_ocr_path, "PNG")
            os.remove(temp_raw_path)
            return temp_ocr_path, scale_factor
        except Exception as e:
            print(f"Pillow preprocess error: {e}")
            # Fall back to the raw crop without preprocessing
            if os.path.exists(temp_ocr_path):
                os.remove(temp_ocr_path)
            return temp_raw_path, 1.0

    def group_lines_into_paragraphs(self, lines):
        # Track each column independently: another column's intervening row
        # must not break a paragraph or become its continuation.
        paragraphs = []
        heights = sorted(l['h'] for l in lines if l['h'] > 0)
        body_height = heights[len(heights)//4] if heights else 20
        for line in sorted(lines, key=lambda l: (l['y'], l['x'])):
            choices = []
            new_item = re.match(r'^(\d+[.)]|[-•*>])\s', line['text'].strip())
            for paragraph in paragraphs:
                previous = paragraph[-1]
                height = (previous['h'] + line['h']) / 2
                gap = line['y'] - previous['y'] - previous['h']
                similar_size = max(previous['h'], line['h']) / max(1, min(previous['h'], line['h'])) <= 1.3
                # Short labels and code rows are separate layout objects.
                prose = previous['w'] >= height * 5 and len(previous['text']) >= 12
                heading = (min(previous['h'], line['h']) >= 32
                           and (min(previous['h'], line['h']) >= body_height * 1.5 or len(lines) <= 2)
                           and len(previous['text'].split()) >= 3
                           and len(line['text'].split()) >= 3)
                if (not new_item and prose
                        and 0 <= gap <= height * (1.15 if heading else .7)
                        and abs(previous['x'] - line['x']) <= height * .65
                        and similar_size and self.same_script(previous['text'], line['text'])):
                    choices.append((gap, paragraph))
            if choices:
                min(choices, key=lambda item: item[0])[1].append(line)
            else:
                paragraphs.append([line])
        return paragraphs

    def same_script(self, a, b):
        """True when both lines are written in the same script. A line that is
        already in the target language must not be merged with source lines."""
        def cjk_ratio(s):
            body = re.sub(r'[\s\W_\d]+', '', s)
            if not body:
                return -1.0
            return len(re.findall(r'[\u4e00-\u9fff]', body)) / len(body)
        ra, rb = cjk_ratio(a), cjk_ratio(b)
        if ra < 0 or rb < 0:
            return True
        return (ra > 0.5) == (rb > 0.5)

    def merge_paragraph_text(self, paragraph):
        # Merges lines in a paragraph. Reconstructs hyphenated splits and spaces English words.
        merged = ""
        for i, line in enumerate(paragraph):
            text = line["text"].strip()
            if i == 0:
                merged = text
            else:
                # If both end/start with ASCII alphanumeric characters, join with space
                if merged and ord(merged[-1]) < 128 and text and ord(text[0]) < 128:
                    # Strip end-of-line hyphens (e.g. "winrt-" + "Windows" -> "winrt-Windows")
                    if merged.endswith("-"):
                        from ocr_review import join_broken_word
                        merged = join_broken_word(merged, text)
                    else:
                        merged = merged + " " + text
                else:
                    merged = merged + text
        return merged

    # OCR Operations
    def run_ocr(self):
        if self.is_loading:
            return
        if self.ocr_result:
            self.display_ocr_panel()
            return

        self.is_loading = True
        self.loading_msg = "正在识别文字，请稍候..."
        self.update()
        
        # Prepare the preprocessed upscaled image
        self.temp_ocr_path, scale_factor = self.prepare_ocr_image()
        
        # Launch background thread with scale_factor
        self.ocr_thread = OCRThread(self.temp_ocr_path, scale_factor=scale_factor, review=True)
        self.ocr_thread.progress.connect(self.on_stage_progress)
        self.ocr_thread.finished.connect(self.on_ocr_finished)
        self.ocr_thread.error.connect(self.on_ocr_error)
        self.ocr_thread.start()

    def on_ocr_finished(self, result):
        self.is_loading = False
        if self._closing:
            return
        self.ocr_result = result
        self.update()
        
        # Clean up temp file
        if os.path.exists(self.temp_ocr_path):
            try:
                os.remove(self.temp_ocr_path)
            except Exception:
                pass
                
        if result and result["text"].strip():
            self.display_ocr_panel()
        else:
            QMessageBox.information(self, "识别结果", "未能在截图区域中识别到任何文字。")

    def on_ocr_error(self, err_msg):
        if self._closing:
            return
        self.is_loading = False
        self.update()
        QMessageBox.critical(self, "识别出错", f"OCR识别失败: {err_msg}")

    def display_ocr_panel(self):
        if not self.ocr_result:
            return
        self.ensure_blocks()
        if not self.ocr_panel:
            self.ocr_panel = OCRPanel(self)
            self.ocr_panel.close_requested.connect(self.close_ocr_panel)
            self.ocr_panel.apply_requested.connect(self.apply_block)
            self.ocr_panel.retry_requested.connect(self.retry_block)
            self.ocr_panel.restore_requested.connect(self.restore_block)
        self.refresh_panel()
        self.reposition_ocr_panel()
        self.ocr_panel.show()

    def close_ocr_panel(self):
        if self.ocr_panel:
            self.ocr_panel.hide()

    def reposition_ocr_panel(self):
        if not self.ocr_panel or self.crop_rect.isEmpty():
            return
            
        screen_rect = self.get_local_screen_rect()
        margin = 12
        
        # Adapt panel height to the selection height for comfortable reading,
        # clamped to a sane range and to the monitor.
        panel_h = min(650, screen_rect.height() - margin * 2)
        self.ocr_panel.resize(390, panel_h)
        panel_w = self.ocr_panel.width()
        
        # Prefer the right side of the selection, then the left side,
        # otherwise dock to the right edge of the monitor.
        rx = self.crop_rect.right() + margin
        if rx + panel_w > screen_rect.right() - margin:
            rx = self.crop_rect.left() - panel_w - margin
            if rx < screen_rect.left() + margin:
                rx = screen_rect.right() - panel_w - margin
                
        # Align top edge with the selection (more natural to read alongside)
        ry = self.crop_rect.top()
        ry = max(screen_rect.top() + margin, min(ry, screen_rect.bottom() - panel_h - margin))
        
        # Convert to global coordinate offset
        global_pos = self.combined_rect.topLeft() + QPoint(rx, ry)
        self.ocr_panel.move(global_pos)

    # In-place Translation
    def on_translate_toggled(self, checked):
        if self.is_loading:
            # A task is already running; ignore the click and revert the button
            self.toolbar.set_translate_state(not checked)
            return
        if checked:
            # Activate translated view
            if self.translated_pixmap:
                self.is_translated_view = True
                self.update()
            else:
                # Need to run OCR first if we don't have it
                if not self.ocr_result:
                    self.is_loading = True
                    self.loading_msg = "正在进行OCR分析..."
                    self.update()
                    
                    # Prepare the upscaled image for translation OCR
                    self.temp_ocr_path, scale_factor = self.prepare_ocr_image()
                    
                    self.ocr_thread = OCRThread(self.temp_ocr_path, scale_factor=scale_factor, review=True)
                    self.ocr_thread.progress.connect(self.on_stage_progress)
                    self.ocr_thread.finished.connect(self.on_ocr_finished_for_translation)
                    self.ocr_thread.error.connect(self.on_translate_error_recovery)
                    self.ocr_thread.start()
                else:
                    self.start_translation()
        else:
            # Restore view
            self.is_translated_view = False
            self.update()

    def on_ocr_finished_for_translation(self, result):
        # Temp file cleanup
        if os.path.exists(self.temp_ocr_path):
            try:
                os.remove(self.temp_ocr_path)
            except Exception:
                pass
                
        if self._closing:
            return
        self.ocr_result = result
        if not result or not result["lines"]:
            self.is_loading = False
            self.update()
            self.toolbar.set_translate_state(False)
            QMessageBox.information(self, "翻译提示", "截图中未识别到任何文本，无法翻译。")
            return
            
        self.start_translation()

    def clean_text_for_translation(self, text):
        # Preserve camelCase, acronyms, paths and identifiers exactly.
        return re.sub(r'\s+', ' ', text).strip()

    def start_translation(self, indices=None, force=False):
        self.ensure_blocks()
        if not self.blocks:
            return
        self.is_loading = True
        self.loading_msg = '正在翻译…'
        self.pending_indices = list(range(len(self.blocks))) if indices is None else indices
        if indices is None or not hasattr(self, 'trans_target'):
            self.trans_target = translator.auto_target_lang('\n'.join(b['source'] for b in self.blocks))
        texts = [self.blocks[i]['source'] for i in self.pending_indices]
        self.trans_thread = TranslationThread(texts, self.trans_target, force, '\n'.join(b['source'] for b in self.blocks))
        self.trans_thread.progress.connect(self.on_translation_progress)
        self.trans_thread.finished.connect(self.on_translation_finished)
        self.trans_thread.error.connect(self.on_translate_error_recovery)
        self.trans_thread.start()
        if self.ocr_panel:
            self.ocr_panel.set_busy(True)
        self.update()

    def on_translation_finished(self, translations):
        if self._closing:
            return
        self.is_loading = False
        for i, result in zip(self.pending_indices, translations):
            b = self.blocks[i]
            b['result'] = result
            b['translation'] = result.get('text', '')
            b['restored'] = False
        self.render_blocks()
        self.update()

    def ensure_blocks(self):
        if self.blocks or not self.ocr_result:
            return
        self.paragraphs = self.group_lines_into_paragraphs(self.ocr_result['lines'])
        for paragraph in self.paragraphs:
            original_lines = [dict(l, text=l.get('original_text', l['text'])) for l in paragraph]
            self.blocks.append(dict(paragraph=paragraph,
                original=self.merge_paragraph_text(original_lines),
                source=self.clean_text_for_translation(self.merge_paragraph_text(paragraph)),
                translation='', badge='待核对' if any(l.get('review_status') == 'uncertain' for l in paragraph) else ('已纠错' if any(l.get('review_status') == 'corrected' for l in paragraph) else ''),
                note='；'.join(dict.fromkeys(l.get('review_note', '') for l in paragraph if l.get('review_note'))),
                status='', restored=False))

    def refresh_panel(self):
        if self.ocr_panel:
            failures = sum(not b.get('result', {}).get('ok', True) for b in self.blocks)
            overflow = sum(b.get('overflow', False) for b in self.blocks)
            uncertain = sum(b.get('badge') == '待核对' for b in self.blocks)
            self.ocr_panel.set_records(self.blocks, f'共 {len(self.blocks)} 块 · 待核对 {uncertain} · 翻译失败 {failures} · 原位放不下 {overflow}\n按住截图窗口的空格键查看原图；此处可查看完整译文。')
            self.ocr_panel.set_busy(self.is_loading)

    def render_blocks(self):
        original = self.bg_pixmap.copy(self.crop_rect).toImage()
        crop_img = original.copy()
        jobs = []
        for b in self.blocks:
            b['overflow'] = False
            r = b.get('result', {})
            status = b.get('note', '')
            if r:
                status += ('\n' if status else '') + ('引擎：' + r['engine'] if r['ok'] else '翻译失败，可重试')
                if r.get('cached'):
                    status += '（缓存）'
                if r.get('fallback'):
                    status += ' · 已切换备用引擎'
                if r.get('error'):
                    status += '\n' + r['error']
            b['status'] = status
            if b['restored']:
                b['status'] += '\n此块显示原图，点击重试可重新显示译文'
                continue
            if not r.get('ok') or not self.is_translation_usable(b['source'], b['translation']):
                continue
            layout = translation_layout.plan(b['paragraph'], b['translation'], crop_img.width(), crop_img.height())
            if layout is None:
                b['overflow'] = True
                b['status'] += '\n译文无法在原区域完整放下，已保留原图；完整译文见下方。'
                continue
            jobs.append((b, layout))
        # Repair from immutable original pixels. Draw only after ALL repairs:
        # nearby OCR padding must never sample or erase an earlier translation.
        draw_jobs = []
        for b, layout in jobs:
            regions = b['paragraph']
            erased = self.erase_text_pixels(original, regions)
            if erased is None:
                b['status'] += '\n背景修复不可用，已保留原图。'
                continue
            cleaned, inks = erased
            if any(c is None for c in inks):
                b['status'] += '\n文字与背景无法可靠分离，已保留原图。'
                continue
            painter = QPainter(crop_img)
            bounds = dict(x=min(l['x'] for l in regions),y=min(l['y'] for l in regions),
                          h=sum(l['h'] for l in regions)/len(regions))
            bounds['w'] = max(l['x']+l['w'] for l in regions)-bounds['x']
            bounds['bottom'] = max(l['y']+l['h'] for l in regions)
            for region in [bounds]:
                pad = max(6, round(region['h'] * .35))
                x0 = max(0, int(region['x'])-pad)
                y0 = max(0, int(region['y'])-pad)
                x1 = min(original.width(),int(region['x']+region['w'])+pad)
                y1 = min(original.height(),math.ceil(region['bottom'])+pad)
                rect = QRect(x0,y0,x1-x0,y1-y0)
                clip = QRegion(rect)
                for other in self.blocks:
                    if other is b:
                        continue
                    for neighbor in other['paragraph']:
                        protected_rect = QRect(math.floor(neighbor['x']),math.floor(neighbor['y']),
                                               math.ceil(neighbor['w'])+1,math.ceil(neighbor['h'])+1)
                        clip = clip.subtracted(QRegion(protected_rect))
                painter.setClipRegion(clip)
                painter.drawImage(rect,cleaned,rect)
            painter.end()
            color = inks[0]
            draw_jobs.append((layout,color))
        for layout, color in draw_jobs:
            painter = QPainter(crop_img)
            painter.setRenderHint(QPainter.TextAntialiasing)
            translation_layout.draw(painter, layout, color)
            painter.end()
        self.translated_pixmap = QPixmap.fromImage(crop_img)
        self.is_translated_view = True
        self.toolbar.set_translate_state(True)
        self.refresh_panel()
        self.update()

    def apply_block(self, index, text):
        if self.is_loading or not (0 <= index < len(self.blocks)) or not text.strip():
            return
        self.blocks[index]['source'] = self.clean_text_for_translation(text)
        self.blocks[index]['badge'] = '手动修改'
        self.start_translation([index])

    def retry_block(self, index):
        if not self.is_loading and 0 <= index < len(self.blocks):
            self.start_translation([index], force=True)

    def restore_block(self, index):
        if not self.is_loading and 0 <= index < len(self.blocks):
            self.blocks[index]['restored'] = True
            self.render_blocks()

    def on_stage_progress(self, message):
        if not self._closing:
            self.loading_msg = message
            self.update()

    def on_translation_progress(self, done, total):
        self.on_stage_progress(f'正在翻译 {done}/{total}…')

    def invalidate_recognition(self):
        self.ocr_result = None
        self.blocks = []
        self.translated_pixmap = None
        self.is_translated_view = False
        if self.ocr_panel:
            self.ocr_panel.hide()
        if self.toolbar:
            self.toolbar.set_translate_state(False)

    def erase_text_pixels(self, crop_img, lines):
        """Erases the original glyphs from the crop, WeChat-style.
        
        For each OCR line box the text strokes are segmented with Otsu. On
        uniform backgrounds (the common case for screenshots) the strokes are
        filled with the per-row median background color, which is pixel-perfect
        and leaves no smearing. Non-uniform regions (photos, gradients with
        texture) fall back to OpenCV inpainting. Returns (cleaned QImage,
        per-line ink QColor list) or None if OpenCV/numpy are unavailable.
        """
        try:
            import cv2
            import numpy as np
        except Exception:
            return None
        
        img = crop_img.convertToFormat(QImage.Format_RGB888)
        w, h = img.width(), img.height()
        if w < 2 or h < 2:
            return None
        bpl = img.bytesPerLine()
        arr = np.frombuffer(bytes(img.constBits()), np.uint8)
        arr = arr.reshape(h, bpl)[:, :w * 3].reshape(h, w, 3).copy()
        
        inpaint_mask = np.zeros((h, w), np.uint8)
        kernel = np.ones((3, 3), np.uint8)
        inks = []
        
        for l in lines:
            pad = max(6, round(l['h'] * .35))
            x0 = max(0, int(l["x"]) - pad)
            y0 = max(0, int(l["y"]) - pad)
            x1 = min(w, int(l["x"] + l["w"]) + pad)
            y1 = min(h, int(l["y"] + l["h"]) + pad)
            if x1 - x0 < 2 or y1 - y0 < 2:
                inks.append(None)
                continue
            
            region = arr[y0:y1, x0:x1]
            gray = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY)
            _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            white = bw > 0
            # Use the border as background evidence. The minority heuristic
            # incorrectly erases bold labels and dark-theme controls.
            border = np.concatenate((gray[0], gray[-1], gray[:, 0], gray[:, -1]))
            text_px = ~white if np.median(border) > _ else white

            count, labels, stats, _centers = cv2.connectedComponentsWithStats(text_px.astype(np.uint8), 8)
            for component in range(1, count):
                cx, cy, cw, ch, area = stats[component]
                # Protect rules/borders that span the OCR box.
                horizontal_edge = (cy == 0 or cy + ch == region.shape[0]) and cw > region.shape[1] * .75 and ch <= 2
                vertical_edge = (cx == 0 or cx + cw == region.shape[1]) and ch > region.shape[0] * .85 and cw <= 2
                if horizontal_edge or vertical_edge:
                    text_px[labels == component] = False
            
            if text_px.mean() > 0.75 or not text_px.any():
                # Uncertain segmentation must not erase the whole rectangle.
                inks.append(None)
                continue
            
            bg_px = ~text_px
            bg_colors = region[bg_px].astype(np.float32)
            bg_med = np.median(bg_colors, axis=0)
            
            # Ink color: strokes' cores, i.e. the 30% of stroke pixels furthest
            # from the background (anti-aliased edges would wash the color out)
            stroke = region[text_px].astype(np.float32)
            if len(stroke) >= 8:
                dist = np.abs(stroke - bg_med).sum(axis=1)
                k = max(4, int(len(stroke) * 0.3))
                core = stroke[np.argsort(dist)[-k:]]
                c = core.mean(axis=0)
                inks.append(QColor(int(c[0]), int(c[1]), int(c[2])))
            else:
                inks.append(None)

            # Smooth screenshot backgrounds can be reconstructed from their
            # perimeter, including the backing of inline code chips. Only use
            # this when every edge agrees with the fitted background surface.
            from background_repair import smooth_background
            smooth = smooth_background(region)
            if smooth is not None:
                region[1:-1, 1:-1] = smooth[1:-1, 1:-1]
                continue
            
            # Dilate mask to swallow anti-aliased stroke edges
            mask = cv2.dilate(text_px.astype(np.uint8) * 255, kernel, iterations=1) > 0
            # Do not touch the sampled exterior border or neighboring blocks.
            mask[0, :] = mask[-1, :] = False
            mask[:, 0] = mask[:, -1] = False
            
            # Uniform background -> fill with per-row median (perfectly clean)
            if bg_colors.std(axis=0).max() < 14.0:
                for ry in range(region.shape[0]):
                    row_mask = mask[ry]
                    if not row_mask.any():
                        continue
                    row_bg = region[ry][~row_mask]
                    fill = np.median(row_bg, axis=0) if len(row_bg) >= 4 else bg_med
                    region[ry][row_mask] = fill.astype(np.uint8)
            else:
                inpaint_mask[y0:y1, x0:x1] = np.maximum(inpaint_mask[y0:y1, x0:x1], mask.astype(np.uint8) * 255)
        
        if inpaint_mask.any():
            arr = cv2.inpaint(arr, inpaint_mask, 5, cv2.INPAINT_NS)

        # Inline chips extend beyond glyph bounds. Reconstruct a whole smooth
        # paragraph from clean outer edges, rather than sampling chip backing
        # as the background of each isolated text row.
        if len(lines) > 1:
            pad = max(6, round(sum(l['h'] for l in lines)/len(lines)*.35))
            x0 = max(0, math.floor(min(l['x'] for l in lines))-pad)
            y0 = max(0, math.floor(min(l['y'] for l in lines))-pad)
            x1 = min(w, math.ceil(max(l['x']+l['w'] for l in lines))+pad)
            y1 = min(h, math.ceil(max(l['y']+l['h'] for l in lines))+pad)
            source = crop_img.convertToFormat(QImage.Format_RGB888)
            original_pixels = np.frombuffer(source.constBits(),np.uint8).reshape(h,source.bytesPerLine())[:,:w*3].reshape(h,w,3)
            region = original_pixels[y0:y1,x0:x1]
            from background_repair import smooth_background
            smooth = smooth_background(region)
            if smooth is not None:
                background = np.ones(region.shape[:2],dtype=bool)
                for l in lines:
                    left=max(0,math.floor(l['x'])-pad-x0); right=min(x1-x0,math.ceil(l['x']+l['w'])+pad-x0)
                    top=max(0,math.floor(l['y'])-pad-y0); bottom=min(y1-y0,math.ceil(l['y']+l['h'])+pad-y0)
                    background[top:bottom,left:right]=False
                errors=np.abs(smooth.astype(float)-region.astype(float))[background]
                if not errors.size or np.quantile(errors,.95) <= 6:
                    arr[y0+1:y1-1,x0+1:x1-1]=smooth[1:-1,1:-1]
        
        arr = np.ascontiguousarray(arr)
        out = QImage(arr.data, w, h, w * 3, QImage.Format_RGB888).copy()
        return out, inks
    

    def on_translate_error_recovery(self, err_msg):
        if self._closing:
            return
        if self.ocr_panel:
            self.ocr_panel.set_busy(False)
        self.is_loading = False
        self.update()
        self.toolbar.set_translate_state(False)
        QMessageBox.warning(self, "翻译失败", f"无法获取翻译数据，请检查网络连接。\n错误: {err_msg}")

    _CJK_CHARS = '\u4e00-\u9fff\u3000-\u303f\uff00-\uffef'

    def wrap_text_to_width(self, text, fm, width):
        # Word-wraps text to a pixel width: CJK may break anywhere,
        # latin words are kept whole.
        tokens = re.findall(rf'[{self._CJK_CHARS}]|[^\s{self._CJK_CHARS}]+|\s+', text)
        lines = []
        current = ""
        for tok in tokens:
            trial = current + tok
            if not current.strip() or fm.horizontalAdvance(trial.rstrip()) <= width:
                current = trial
            else:
                lines.append(current.rstrip())
                current = tok.lstrip()
        if current.strip():
            lines.append(current.rstrip())
        return lines


    def is_translation_usable(self, original, translated):
        # Decides whether a paragraph translation is worth rendering.
        if not translated or not translated.strip():
            return False
        norm = lambda s: re.sub(r'[\W_]+', '', s).lower()
        # Unchanged text (numbers, code, failed engines) -> keep original pixels
        if norm(translated) == norm(original):
            return False
        cjk = len(re.findall(r'[\u4e00-\u9fff]', translated))
        total = len(re.sub(r'\s', '', translated))
        if total == 0:
            return False
        if self.trans_target == "zh-CN":
            # A "Chinese" result with almost no Chinese means the engine
            # echoed the (noisy) source text back
            return cjk >= 1 and cjk / total >= 0.10
        # English target: reject results still dominated by CJK characters
        return cjk / total <= 0.5

    def sample_edge_colors(self, image, rect):
        # Samples background just outside the rect perimeter, split into
        # left/right halves, for building a blending gradient cover.
        w, h = image.width(), image.height()
        x = max(0, min(rect.x(), w - 1))
        y = max(0, min(rect.y(), h - 1))
        rw = max(1, min(rect.width(), w - x))
        rh = max(1, min(rect.height(), h - y))
        mid = x + rw // 2
        
        left_colors, right_colors = [], []
        step = max(1, rw // 12)
        for dx in range(0, rw, step):
            px = x + dx
            bucket = left_colors if px < mid else right_colors
            if y > 2:
                bucket.append(image.pixelColor(px, y - 2))
            if y + rh < h - 2:
                bucket.append(image.pixelColor(px, y + rh + 2))
        vstep = max(1, rh // 6)
        for dy in range(0, rh, vstep):
            if x > 2:
                left_colors.append(image.pixelColor(x - 2, y + dy))
            if x + rw < w - 2:
                right_colors.append(image.pixelColor(x + rw + 2, y + dy))
                
        fallback = self.sample_bg_color(image, rect)
        
        def avg(colors):
            if not colors:
                return fallback
            return QColor(sum(c.red() for c in colors) // len(colors),
                          sum(c.green() for c in colors) // len(colors),
                          sum(c.blue() for c in colors) // len(colors))
                          
        return avg(left_colors), avg(right_colors)

    def sample_bg_color(self, image, rect):
        # Sample colors on the perimeter of the box
        w, h = image.width(), image.height()
        rx, ry, rw, rh = rect.x(), rect.y(), rect.width(), rect.height()
        
        colors = []
        
        # Adjust boundaries
        x = max(0, min(rx, w - 1))
        y = max(0, min(ry, h - 1))
        rw = max(1, min(rw, w - x))
        rh = max(1, min(rh, h - y))
        
        # Sample top border
        if y > 2:
            for dx in range(0, rw, max(1, rw // 10)):
                colors.append(image.pixelColor(x + dx, y - 2))
        # Sample bottom border
        if y + rh < h - 2:
            for dx in range(0, rw, max(1, rw // 10)):
                colors.append(image.pixelColor(x + dx, y + rh + 2))
        # Sample left border
        if x > 2:
            for dy in range(0, rh, max(1, rh // 10)):
                colors.append(image.pixelColor(x - 2, y + dy))
        # Sample right border
        if x + rw < w - 2:
            for dy in range(0, rh, max(1, rh // 10)):
                colors.append(image.pixelColor(x + rw + 2, y + dy))
                
        if not colors:
            return image.pixelColor(x, y)
            
        # Average color channels
        avg_r = sum(c.red() for c in colors) // len(colors)
        avg_g = sum(c.green() for c in colors) // len(colors)
        avg_b = sum(c.blue() for c in colors) // len(colors)
        
        return QColor(avg_r, avg_g, avg_b)

    def get_contrast_color(self, bg_color):
        # Compute brightness YUV formula
        brightness = (bg_color.red() * 299 + bg_color.green() * 587 + bg_color.blue() * 114) / 1000
        return QColor(0, 0, 0) if brightness > 128 else QColor(255, 255, 255)

    # Keypress triggers
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self.peek_original = True
            self.update()
            return
        if event.key() == Qt.Key_Escape:
            # Esc: cancel and exit screenshot
            self.close_and_cancel()
        elif event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            # Enter: confirm and copy to clipboard if selection exists
            if not self.crop_rect.isEmpty():
                self.confirm_to_clipboard()
        elif event.key() == Qt.Key_Z and event.modifiers() & Qt.ControlModifier:
            # Ctrl+Z: Undo shape
            self.on_undo()
        elif event.key() == Qt.Key_F3:
            self.pin_to_screen()
        else:
            super().keyPressEvent(event)

    # Make sure subwindows move with window
    def moveEvent(self, event):
        super().moveEvent(event)
        self.reposition_toolbar()
        self.reposition_ocr_panel()

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self.peek_original = False
            self.update()
        else:
            super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self.peek_original = False
        self.update()
        super().focusOutEvent(event)

    def closeEvent(self, event):
        # Keep QThread owners alive until workers finish. Closing never waits
        # for network I/O on the UI thread and never destroys a running worker.
        self._closing = True
        if self.ocr_panel:
            self.ocr_panel.hide()
        if self.toolbar:
            self.toolbar.hide()
        running = [getattr(self, name, None) for name in ('ocr_thread', 'trans_thread')]
        running = [t for t in running if t is not None and t.isRunning()]
        if running:
            if self not in _retired_windows:
                _retired_windows.append(self)
            event.ignore()
            self.hide()
            self._close_timer = QTimer(self)
            self._close_timer.timeout.connect(self.finish_deferred_close)
            self._close_timer.start(100)
        else:
            self.cleanup_temp()
            if self in _retired_windows:
                _retired_windows.remove(self)
            event.accept()

    def finish_deferred_close(self):
        if all(not getattr(self, n, None) or not getattr(self, n).isRunning() for n in ('ocr_thread', 'trans_thread')):
            self._close_timer.stop()
            self.close()

    def cleanup_temp(self):
        path = getattr(self, 'temp_ocr_path', None)
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
