import sys
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QButtonGroup, QFrame, QGraphicsDropShadowEffect
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QFont
from icons import make_icon


def _apply_icon(btn, name, color="#344054", checked=None):
    btn.setText("")
    btn.setIcon(make_icon(name, color, checked))
    btn.setIconSize(QSize(18, 18))

class ColorButton(QPushButton):
    def __init__(self, color_str, parent=None):
        super().__init__(parent)
        self.color = color_str
        self.setFixedSize(18, 18)
        self.setCursor(Qt.PointingHandCursor)
        self.setCheckable(True)
        self.update_style(False)

    def update_style(self, checked):
        border = "2px solid #1A73E8" if checked else "1px solid rgba(52,64,84,0.3)"
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.color};
                border: {border};
                border-radius: 9px;
            }}
            QPushButton:hover {{
                border: 2px solid #1A73E8;
            }}
        """)

class ToolbarButton(QPushButton):
    def __init__(self, text, tooltip="", parent=None):
        super().__init__(text, parent)
        self.setFixedSize(30, 30)
        self.setToolTip(tooltip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFont(QFont("Segoe UI", 11))
        self.setCheckable(True)
        self.setStyleSheet("""
            QPushButton {
                color: #344054;
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: rgba(52, 64, 84, 0.07);
            }
            QPushButton:checked {
                background-color: rgba(26, 115, 232, 0.09);
                color: #1A73E8;
                border: 1px solid rgba(26, 115, 232, 0.3);
            }
        """)

class ActionButton(QPushButton):
    def __init__(self, text, tooltip="", color="#344054", bg_hover="rgba(52,64,84,0.07)", parent=None):
        super().__init__(text, parent)
        self.setFixedSize(32, 30)
        self.setToolTip(tooltip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFont(QFont("Microsoft YaHei", 10))
        self.setStyleSheet(f"""
            QPushButton {{
                color: {color};
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {bg_hover};
            }}
        """)

class AnnotationToolbar(QWidget):
    # Signals
    tool_changed = Signal(str)  # 'pen', 'rect', 'arrow', 'text', or None
    color_changed = Signal(QColor)
    thickness_changed = Signal(int)
    undo_triggered = Signal()
    ocr_triggered = Signal()
    translate_toggled = Signal(bool) # True = translate, False = restore
    save_triggered = Signal()
    cancel_triggered = Signal()
    confirm_triggered = Signal()
    pin_triggered = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.is_translated = False
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(4)

        # Background Frame
        frame = QFrame(self)
        frame.setObjectName("ToolbarFrame")
        frame.setStyleSheet("""
            QFrame#ToolbarFrame {
                background-color: #FFFFFF;
                border: 1px solid #DDE2E8;
                border-radius: 10px;
            }
        """)
        frame_layout = QHBoxLayout(frame)
        shadow = QGraphicsDropShadowEffect(frame)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(24, 39, 59, 48))
        frame.setGraphicsEffect(shadow)
        frame_layout.setContentsMargins(8, 4, 8, 4)
        frame_layout.setSpacing(6)

        # 1. Drawing Tools Group
        self.tools_group = QButtonGroup(self)
        self.tools_group.setExclusive(False)

        self.btn_pen = ToolbarButton("", "画笔 (Pen)", self)
        self.btn_rect = ToolbarButton("", "矩形 (Rectangle)", self)
        self.btn_arrow = ToolbarButton("", "箭头 (Arrow)", self)
        self.btn_text = ToolbarButton("", "文字 (Text)", self)
        self.btn_cover = ToolbarButton('▧', '遮盖打码：拖动遮住敏感内容', self)
        _apply_icon(self.btn_pen, "pen", checked="#1A73E8")
        _apply_icon(self.btn_rect, "rect", checked="#1A73E8")
        _apply_icon(self.btn_arrow, "arrow", checked="#1A73E8")
        _apply_icon(self.btn_text, "text", checked="#1A73E8")
        _apply_icon(self.btn_cover, "cover", checked="#1A73E8")
        
        self.tools_group.addButton(self.btn_pen)
        self.tools_group.addButton(self.btn_rect)
        self.tools_group.addButton(self.btn_arrow)
        self.tools_group.addButton(self.btn_text)
        self.tools_group.addButton(self.btn_cover)

        frame_layout.addWidget(self.btn_pen)
        frame_layout.addWidget(self.btn_rect)
        frame_layout.addWidget(self.btn_arrow)
        frame_layout.addWidget(self.btn_text)
        frame_layout.addWidget(self.btn_cover)

        # Connections for tools
        self.btn_pen.clicked.connect(lambda *_: self.on_tool_clicked('pen', self.btn_pen))
        self.btn_rect.clicked.connect(lambda *_: self.on_tool_clicked('rect', self.btn_rect))
        self.btn_arrow.clicked.connect(lambda *_: self.on_tool_clicked('arrow', self.btn_arrow))
        self.btn_text.clicked.connect(lambda *_: self.on_tool_clicked('text', self.btn_text))
        self.btn_cover.clicked.connect(lambda *_: self.on_tool_clicked('cover', self.btn_cover))

        # Undo Action
        self.btn_undo = ActionButton("", "撤销 (Undo)", parent=self)
        _apply_icon(self.btn_undo, "undo")
        self.btn_undo.clicked.connect(lambda *_: self.undo_triggered.emit())
        frame_layout.addWidget(self.btn_undo)

        # Separator
        frame_layout.addWidget(self.create_separator())

        # 2. Color selection
        self.colors = ["#FF3B30", "#34C759", "#007AFF", "#FFCC00", "#FFFFFF", "#000000"]
        self.color_group = QButtonGroup(self)
        self.color_group.setExclusive(True)
        self.color_buttons = []
        
        for c in self.colors:
            btn = ColorButton(c, self)
            self.color_group.addButton(btn)
            self.color_buttons.append(btn)
            frame_layout.addWidget(btn)
            # Signal emission on click
            btn.clicked.connect(self.on_color_clicked)
            
        # Select first color (Red) by default
        self.color_buttons[0].setChecked(True)
        self.color_buttons[0].update_style(True)

        # Separator
        frame_layout.addWidget(self.create_separator())

        # 3. Thickness Selector
        self.thick_group = QButtonGroup(self)
        self.thick_group.setExclusive(True)
        
        self.btn_thin = ToolbarButton("", "细 (Thin)", self)
        self.btn_medium = ToolbarButton("", "中 (Medium)", self)
        self.btn_thick = ToolbarButton("", "粗 (Thick)", self)
        _apply_icon(self.btn_thin, "dot_s", checked="#1A73E8")
        _apply_icon(self.btn_medium, "dot_m", checked="#1A73E8")
        _apply_icon(self.btn_thick, "dot_l", checked="#1A73E8")
        
        self.thick_group.addButton(self.btn_thin)
        self.thick_group.addButton(self.btn_medium)
        self.thick_group.addButton(self.btn_thick)
        
        self.btn_thin.clicked.connect(lambda *_: self.thickness_changed.emit(2))
        self.btn_medium.clicked.connect(lambda *_: self.thickness_changed.emit(4))
        self.btn_thick.clicked.connect(lambda *_: self.thickness_changed.emit(8))
        
        self.btn_medium.setChecked(True) # default to medium
        
        frame_layout.addWidget(self.btn_thin)
        frame_layout.addWidget(self.btn_medium)
        frame_layout.addWidget(self.btn_thick)

        # Separator
        frame_layout.addWidget(self.create_separator())

        # 4. OCR and Translation buttons
        self.btn_ocr = ActionButton("提取文字", "提取截图中的文字 (OCR)", color="#1A73E8", bg_hover="rgba(26,115,232,0.08)", parent=self)
        self.btn_ocr.clicked.connect(lambda *_: self.ocr_triggered.emit())
        self.btn_ocr.setFixedWidth(64)
        frame_layout.addWidget(self.btn_ocr)

        self.btn_translate = ActionButton("翻译", "中英互译并在原位显示 (In-place Translate)", color="#1A73E8", bg_hover="rgba(26,115,232,0.08)", parent=self)
        self.btn_translate.clicked.connect(lambda *_: self.toggle_translate())
        self.btn_translate.setFixedWidth(48)
        frame_layout.addWidget(self.btn_translate)

        # Separator
        frame_layout.addWidget(self.create_separator())

        # 5. Core actions (Save, Cancel, Confirm)
        self.btn_pin = ActionButton('贴图', '将当前截图或译文置顶 (F3)', parent=self)
        self.btn_pin.clicked.connect(lambda *_: self.pin_triggered.emit())
        frame_layout.addWidget(self.btn_pin)
        self.btn_save = ActionButton("", "保存到文件 (Save)", parent=self)
        _apply_icon(self.btn_save, "save")
        self.btn_save.clicked.connect(lambda *_: self.save_triggered.emit())
        
        self.btn_cancel = ActionButton("", "取消截图 (Cancel)", color="#FF3B30", bg_hover="rgba(255,59,48,0.2)", parent=self)
        _apply_icon(self.btn_cancel, "cancel", color="#D93025")
        self.btn_cancel.clicked.connect(lambda *_: self.cancel_triggered.emit())
   
        self.btn_confirm = ActionButton("", "完成 (Confirm to Clipboard)", color="#34C759", bg_hover="rgba(52,168,83,0.2)", parent=self)
        _apply_icon(self.btn_confirm, "confirm", color="#188038")
        self.btn_confirm.clicked.connect(lambda *_: self.confirm_triggered.emit())

        frame_layout.addWidget(self.btn_save)
        frame_layout.addWidget(self.btn_cancel)
        frame_layout.addWidget(self.btn_confirm)

        layout.addWidget(frame)
        self.adjustSize()

    def create_separator(self):
        line = QFrame(self)
        line.setFrameShape(QFrame.VLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("background-color: #E3E7ED; width: 1px; max-height: 20px;")
        return line

    def on_tool_clicked(self, tool_name, btn):
        # If the button is now checked
        if btn.isChecked():
            # Uncheck all other buttons in the group manually
            for b in self.tools_group.buttons():
                if b != btn:
                    b.setChecked(False)
            self.tool_changed.emit(tool_name)
        else:
            # If the button was unchecked (clicked again)
            self.tool_changed.emit("")

    def clear_active_tool(self):
        # Deselect all tools in the group
        checked_button = self.tools_group.checkedButton()
        if checked_button:
            # Temporarily turn off exclusivity, deselect, turn back on
            self.tools_group.setExclusive(False)
            checked_button.setChecked(False)
            self.tools_group.setExclusive(True)
        self.tool_changed.emit("")

    def on_color_clicked(self):
        btn = self.sender()
        # Reset styles of all color buttons
        for b in self.color_buttons:
            b.update_style(b == btn)
        self.color_changed.emit(QColor(btn.color))

    def _apply_translate_style(self, translated):
        if translated:
            self.btn_translate.setText("复原")
            self.btn_translate.setToolTip("恢复原始截图")
            self.btn_translate.setStyleSheet("""
                QPushButton {
                    color: #188038;
                    background-color: rgba(52, 168, 83, 0.2);
                    border: 1px solid rgba(52, 168, 83, 0.5);
                    border-radius: 4px;
                }
            """)
        else:
            self.btn_translate.setText("翻译")
            self.btn_translate.setToolTip("中英互译并在原位显示 (In-place Translate)")
            self.btn_translate.setStyleSheet("""
                QPushButton {
                    color: #1A73E8;
                    background-color: transparent;
                    border: none;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: rgba(138, 180, 248, 0.2);
                }
            """)

    def toggle_translate(self):
        self.is_translated = not self.is_translated
        self._apply_translate_style(self.is_translated)
        self.translate_toggled.emit(self.is_translated)

    def set_translate_state(self, translated):
        # Sets state programmatically without re-emitting translate_toggled
        # (e.g. when a translation fails and the view is restored)
        if self.is_translated != translated:
            self.is_translated = translated
            self._apply_translate_style(translated)
            
    # Enable dragging of the toolbar
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()
