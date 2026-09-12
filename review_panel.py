from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
                             QPushButton, QLabel, QComboBox, QApplication)
from PySide6.QtCore import Qt, Signal


class OCRPanel(QWidget):
    close_requested = Signal()
    apply_requested = Signal(int, str)
    retry_requested = Signal(int)
    restore_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setWindowTitle('文字复核与翻译对照')
        self.resize(390, 600)
        self.records = []
        self.setStyleSheet('QWidget {background:#202124;color:#e8eaed;} QTextEdit,QComboBox {background:#292b30;border:1px solid #555;padding:5px;} QPushButton {padding:7px;background:#35445f;border:0;} QPushButton:disabled {color:#888;}')
        layout = QVBoxLayout(self)
        self.summary = QLabel('选择文本块，可修改识别结果后重新翻译')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.selector = QComboBox()
        self.selector.currentIndexChanged.connect(self.show_record)
        layout.addWidget(self.selector)
        self.original = self.editor(layout, '原始识别', True, 55)
        self.source = self.editor(layout, '复核结果（可编辑，点击“应用并翻译”保存）', False, 75)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.translation = self.editor(layout, '完整译文', True, 75)
        row = QHBoxLayout()
        self.apply_btn = QPushButton('应用并翻译')
        self.apply_btn.clicked.connect(lambda: self.apply_requested.emit(self.selector.currentIndex(), self.source.toPlainText()))
        self.retry_btn = QPushButton('重试本块')
        self.retry_btn.clicked.connect(lambda: self.retry_requested.emit(self.selector.currentIndex()))
        row.addWidget(self.apply_btn)
        row.addWidget(self.retry_btn)
        layout.addLayout(row)
        row2 = QHBoxLayout()
        reset = QPushButton('恢复原始识别')
        reset.clicked.connect(lambda: self.source.setPlainText(self.records[self.selector.currentIndex()]['original']) if self.records else None)
        self.restore_btn = QPushButton('此块显示原图')
        self.restore_btn.clicked.connect(lambda: self.restore_requested.emit(self.selector.currentIndex()))
        row2.addWidget(reset)
        row2.addWidget(self.restore_btn)
        layout.addLayout(row2)
        row3 = QHBoxLayout()
        for title, field in [('复制全部原文', 'source'), ('复制全部译文', 'translation')]:
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, f=field: QApplication.clipboard().setText('\n\n'.join(r.get(f, '') for r in self.records)))
            row3.addWidget(button)
        layout.addLayout(row3)

    def editor(self, layout, title, readonly, height):
        layout.addWidget(QLabel(title))
        edit = QTextEdit()
        edit.setAcceptRichText(False)
        edit.setReadOnly(readonly)
        edit.setMinimumHeight(height)
        layout.addWidget(edit)
        return edit

    def set_records(self, records, summary=''):
        index = max(0, self.selector.currentIndex())
        self.records = records
        self.selector.blockSignals(True)
        self.selector.clear()
        self.selector.addItems([f"{i+1}. {r.get('badge', '')} {r['source'][:36]}" for i, r in enumerate(records)])
        self.selector.setCurrentIndex(min(index, len(records) - 1))
        self.selector.blockSignals(False)
        self.summary.setText(summary or '选择文本块，可修改识别结果后重新翻译')
        self.show_record(self.selector.currentIndex())

    def show_record(self, index):
        if 0 <= index < len(self.records):
            record = self.records[index]
            self.original.setPlainText(record['original'])
            self.source.setPlainText(record['source'])
            self.translation.setPlainText(record.get('translation', ''))
            self.status.setText(record.get('status', ''))

    def set_busy(self, busy):
        self.apply_btn.setEnabled(not busy)
        self.retry_btn.setEnabled(not busy)
        self.restore_btn.setEnabled(not busy)
        self.source.setReadOnly(busy)

    def closeEvent(self, event):
        self.close_requested.emit()
        event.accept()
