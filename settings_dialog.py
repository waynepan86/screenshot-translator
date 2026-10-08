import os
import copy
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox,
    QFileDialog, QKeySequenceEdit, QFormLayout, QFrame, QComboBox,
    QLineEdit, QGroupBox, QMessageBox,
    QTabWidget, QWidget, QScrollArea,
)
from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QKeySequence, QDesktopServices

import translator
import ocr
from languages import LANGUAGES, ocr_tag

# Where to get a key, per engine. Shown under the credential rows.
ENGINE_HINTS = {
    "auto": "无需密钥。谷歌不可达时自动切换到 MyMemory。",
    "azure": "在 Azure 创建翻译器资源，填写订阅密钥和区域；额度以账户为准。",
    "llm": "填服务商的 OpenAI 兼容地址，注意要带 /v1 之类的版本段。",
    "baidu": "百度翻译开放平台 → 开发者信息，填写 APP ID 与密钥。",
    "youdao": "有道智云 → 自然语言翻译 → 创建应用，取应用 ID 与密钥。",
    "deepl": "填写 DeepL API 的 Auth Key，免费版密钥以 :fx 结尾；需要网络连接。",
}


class EngineTester(QThread):
    """Probes an engine off the UI thread: an LLM round-trip can take tens of
    seconds and would otherwise freeze the dialog."""

    result_ready = Signal(bool, str)

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine

    def run(self):
        try:
            ok, message = translator.test_engine(self.engine)
        except Exception as e:
            ok, message = False, f"测试过程出错：{e}"
        self.result_ready.emit(ok, message)


class SettingsDialog(QDialog):
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config = config_manager
        self.setWindowTitle("截图工具 - 设置")
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        self.resize(540, min(640, self.screen().availableGeometry().height() - 80))

        # Working copy of the credentials: edits are kept here while the user
        # switches between engines, and only written to disk on save.
        self.api_values = copy.deepcopy(self.config.get("trans_api") or {})
        self.cred_edits = {}
        self.shown_engine = None
        self.tester = None

        self.init_ui()

    def init_ui(self):
        # Set styling
        self.setStyleSheet("""
            QDialog {
                background-color: #202124;
                color: #E8EAED;
            }
            QLabel {
                color: #BDC1C6;
                font-family: 'Microsoft YaHei';
                font-size: 10pt;
            }
            QPushButton {
                background-color: #3C4043;
                color: #E8EAED;
                border: 1px solid #5F6368;
                border-radius: 4px;
                padding: 6px 12px;
                font-family: 'Microsoft YaHei';
                font-size: 9.5pt;
            }
            QPushButton:hover {
                background-color: #4F5357;
            }
            QPushButton:disabled {
                color: #80868B;
                border-color: #3C4043;
            }
            QPushButton#SaveBtn {
                background-color: #1A73E8;
                color: white;
                border: none;
            }
            QPushButton#SaveBtn:hover {
                background-color: #1557B0;
            }
            QCheckBox {
                color: #BDC1C6;
                font-family: 'Microsoft YaHei';
                font-size: 10pt;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
            QKeySequenceEdit, QLineEdit {
                background-color: #2D2E30;
                color: #F1F3F4;
                border: 1px solid #5F6368;
                border-radius: 4px;
                padding: 4px;
                font-family: 'Microsoft YaHei';
                font-size: 9.5pt;
            }
            QLineEdit:focus {
                border-color: #1A73E8;
            }
            QComboBox {
                background-color: #2D2E30;
                color: #F1F3F4;
                border: 1px solid #5F6368;
                border-radius: 4px;
                padding: 4px 6px;
                font-family: 'Microsoft YaHei';
                font-size: 9.5pt;
            }
            QComboBox::drop-down {
                border: none;
                width: 18px;
            }
            QComboBox QAbstractItemView {
                background-color: #2D2E30;
                color: #F1F3F4;
                selection-background-color: #1A73E8;
                border: 1px solid #5F6368;
            }
            QGroupBox {
                color: #E8EAED;
                font-family: 'Microsoft YaHei';
                font-size: 9.5pt;
                border: 1px solid #3C4043;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        tabs = QTabWidget(self)
        tabs.setStyleSheet("QTabWidget::pane {border:1px solid #3C4043;} QTabBar::tab {background:#2D2E30;color:#E8EAED;padding:8px 20px;} QTabBar::tab:selected {background:#3C4043;}")
        layout.addWidget(tabs, 1)
        general = QWidget()
        general_box = QVBoxLayout(general)
        general_box.setContentsMargins(12, 12, 12, 12)
        translation = QWidget()
        translation_box = QVBoxLayout(translation)
        translation_box.setContentsMargins(12, 12, 12, 12)
        for name, page in (("常规", general), ("翻译", translation)):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setStyleSheet("QScrollArea, QScrollArea QWidget {background:#202124;}")
            scroll.setWidget(page)
            tabs.addTab(scroll, name)

        # Form layout
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setFormAlignment(Qt.AlignLeft)
        form.setSpacing(12)

        # 1. Region Hotkey
        self.key_region_edit = QKeySequenceEdit(self)
        reg_hotkey = self.config.get("hotkey_region")
        self.key_region_edit.setKeySequence(QKeySequence(reg_hotkey))
        form.addRow("区域截图快捷键：", self.key_region_edit)

        # 2. Fullscreen Hotkey
        self.key_full_edit = QKeySequenceEdit(self)
        full_hotkey = self.config.get("hotkey_fullscreen")
        self.key_full_edit.setKeySequence(QKeySequence(full_hotkey))
        form.addRow("全屏截图快捷键：", self.key_full_edit)

        # 3. Save path row
        path_layout = QHBoxLayout()
        self.path_label = QLabel(self.shorten_path(self.config.get("save_dir")), self)
        self.path_label.setStyleSheet("color: #E8EAED; background-color: #2D2E30; border: 1px solid #5F6368; padding: 4px; border-radius: 4px; min-width: 140px;")

        self.btn_browse = QPushButton("浏览...", self)
        self.btn_browse.clicked.connect(self.browse_folder)
        path_layout.addWidget(self.path_label, 1)
        path_layout.addWidget(self.btn_browse)
        form.addRow("默认保存路径：", path_layout)

        # 4. Auto startup checkbox
        self.chk_startup = QCheckBox("开机时自动启动", self)
        self.chk_startup.setChecked(self.config.get("auto_start"))
        form.addRow("", self.chk_startup)


        general_box.addLayout(form)
        paths = getattr(self.config, 'paths', None)
        if paths:
            mode = "便携版（数据随程序保存）" if paths.portable else "标准版（数据保存在用户目录）"
            location = QLabel(f"{mode}\n数据目录：{paths.data_dir}")
            location.setWordWrap(True)
            location.setTextInteractionFlags(Qt.TextSelectableByMouse)
            general_box.addWidget(location)
            open_data = QPushButton("打开数据目录")
            open_data.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.data_dir))))
            general_box.addWidget(open_data, 0, Qt.AlignLeft)
            import_old = QPushButton("导入旧版配置…")
            import_old.clicked.connect(self.import_legacy_config)
            general_box.addWidget(import_old, 0, Qt.AlignLeft)
        general_box.addStretch()
        translation_box.addWidget(self.build_engine_group())
        translation_box.addStretch()

        # Divider Line
        line = QFrame(self)
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #3C4043;")
        layout.addWidget(line)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = QPushButton("取消", self)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_save = QPushButton("保存", self)
        self.btn_save.setObjectName("SaveBtn")
        self.btn_save.clicked.connect(self.save_settings)

        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_save)

        layout.addLayout(btn_layout)

        # Save actual absolute dir string
        self.current_save_dir = self.config.get("save_dir")

    def build_engine_group(self):
        """The translation engine picker plus its credential rows."""
        group = QGroupBox("翻译引擎", self)
        box = QVBoxLayout(group)
        box.setContentsMargins(12, 8, 12, 12)
        box.setSpacing(10)

        picker = QFormLayout()
        picker.setLabelAlignment(Qt.AlignRight)
        picker.setSpacing(10)
        self.engine_combo = QComboBox(self)
        for engine_id, label in translator.ENGINE_LABELS:
            self.engine_combo.addItem(label, engine_id)
        saved = self.config.get("trans_engine") or "auto"
        index = self.engine_combo.findData(saved)
        self.engine_combo.setCurrentIndex(index if index >= 0 else 0)
        self.engine_combo.currentIndexChanged.connect(self.on_engine_changed)
        picker.addRow("使用引擎：", self.engine_combo)
        self.source_combo = QComboBox(self)
        self.source_combo.addItem("自动识别（主要适用于中英）", "auto")
        self.target_combo = QComboBox(self)
        self.target_combo.addItem("自动（保留旧版中英互译）", "auto")
        for code, name, *_ in LANGUAGES:
            self.source_combo.addItem(name, code)
            self.target_combo.addItem(name, code)
        for combo, key, default in ((self.source_combo, 'trans_source', 'auto'), (self.target_combo, 'trans_target', 'zh-CN')):
            index = combo.findData(self.config.get(key) or default)
            combo.setCurrentIndex(max(0, index))
        picker.addRow("截图语言：", self.source_combo)
        picker.addRow("翻译成：", self.target_combo)
        box.addLayout(picker)
        self.language_note = QLabel()
        self.language_note.setWordWrap(True)
        self.language_note.setStyleSheet("color:#9AA0A6;font-size:9pt;")
        box.addWidget(self.language_note)
        self.source_combo.currentIndexChanged.connect(self.update_language_note)
        self.update_language_note()

        self.cred_form = QFormLayout()
        self.cred_form.setLabelAlignment(Qt.AlignRight)
        self.cred_form.setSpacing(8)
        box.addLayout(self.cred_form)

        test_row = QHBoxLayout()
        self.btn_test = QPushButton("测试连通性", self)
        self.btn_test.clicked.connect(self.on_test_clicked)
        test_row.addWidget(self.btn_test)
        test_row.addStretch()
        box.addLayout(test_row)

        self.status_label = QLabel("", self)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #9AA0A6; font-size: 9pt;")
        box.addWidget(self.status_label)

        self.build_cred_rows()
        return group

    def update_language_note(self):
        source = self.source_combo.currentData()
        if source in ('auto', 'en', 'zh-CN'):
            self.language_note.setText("中英截图使用内置 OCR。其他截图语言需 Windows 对应 OCR 语言包；目标语种不需要安装语言包。")
        else:
            tag = ocr_tag(source)
            installed = ocr.windows_language_supported(source)
            self.language_note.setText(f"{tag}：" + ("已检测到 Windows OCR 语言包。" if installed else "需在 Windows 设置中安装对应 OCR 语言包；未安装时会提示，不会改用其他语言识别。"))

    def import_legacy_config(self):
        filename, _ = QFileDialog.getOpenFileName(self, "选择旧版 config.json", "", "JSON 配置 (*.json)")
        if not filename:
            return
        try:
            self.config.import_legacy(filename)
        except (OSError, RuntimeError):
            QMessageBox.warning(self, "导入失败", "无法导入所选配置。请检查文件格式与数据目录权限，原文件及现有配置已保留。")
            return
        # Persisted import takes effect through ScreenshotApp.on_settings_closed.
        QMessageBox.information(self, "导入完成", "旧版配置已导入。重新打开设置可查看；旧文件保持不变。")
        self.accept()

    def current_engine(self):
        return self.engine_combo.currentData() or "auto"

    def build_cred_rows(self):
        """Rebuilds the credential inputs for the engine now selected."""
        while self.cred_form.rowCount():
            self.cred_form.removeRow(0)
        self.cred_edits = {}

        engine = self.current_engine()
        self.shown_engine = engine
        for field_id, label, placeholder, is_secret in translator.ENGINE_FIELDS.get(engine, []):
            saved = (self.api_values.get(engine) or {}).get(field_id, "")
            edit = QLineEdit(saved, self)
            edit.setPlaceholderText(placeholder)
            if is_secret:
                edit.setEchoMode(QLineEdit.Password)
            self.cred_form.addRow(f"{label}：", edit)
            self.cred_edits[field_id] = edit

        self.status_label.setStyleSheet("color: #9AA0A6; font-size: 9pt;")
        self.status_label.setText(ENGINE_HINTS.get(engine, ""))

    def commit_cred_edits(self):
        """Copies the visible inputs into api_values so that values survive
        switching engines back and forth before saving."""
        if not self.cred_edits or not self.shown_engine:
            return
        bucket = self.api_values.setdefault(self.shown_engine, {})
        for field_id, edit in self.cred_edits.items():
            bucket[field_id] = edit.text().strip()

    def on_engine_changed(self):
        self.commit_cred_edits()
        self.build_cred_rows()

    def on_test_clicked(self):
        self.commit_cred_edits()
        engine = self.current_engine()
        # The probe runs against translator's live state, so push what the user
        # just typed before firing it.
        translator.configure(engine, self.api_values)

        self.btn_test.setEnabled(False)
        self.status_label.setStyleSheet("color: #9AA0A6; font-size: 9pt;")
        self.status_label.setText("正在测试，请稍候…")

        self.tester = EngineTester(engine, self)
        self.tester.result_ready.connect(self.on_test_finished)
        self.tester.start()

    def on_test_finished(self, ok, message):
        self.btn_test.setEnabled(True)
        color = "#81C995" if ok else "#F28B82"
        self.status_label.setStyleSheet(f"color: {color}; font-size: 9pt;")
        self.status_label.setText(("✓ " if ok else "✕ ") + message)

    def shorten_path(self, path):
        # Shortens long path for display
        if len(path) > 30:
            return path[:10] + "..." + path[-17:]
        return path

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择默认保存路径", self.current_save_dir)
        if folder:
            self.current_save_dir = os.path.abspath(folder)
            self.path_label.setText(self.shorten_path(self.current_save_dir))

    def save_settings(self):
        # Retrieve key sequences
        region_seq = self.key_region_edit.keySequence().toString()
        full_seq = self.key_full_edit.keySequence().toString()

        self.commit_cred_edits()
        engine = self.current_engine()
        translator.configure(engine, self.api_values)
        if engine != "auto" and not translator.engine_ready(engine):
            QMessageBox.warning(
                self, "密钥不完整",
                "该引擎的密钥没有填全，翻译时会直接回退到谷歌 / MyMemory。")

        try:
            self.config.update(dict(hotkey_region=region_seq, hotkey_fullscreen=full_seq,
                                    save_dir=self.current_save_dir, auto_start=self.chk_startup.isChecked(),
                                    trans_engine=engine, trans_api=self.api_values,
                                    trans_source=self.source_combo.currentData(),
                                    trans_target=self.target_combo.currentData()))
        except OSError:
            translator.configure(self.config.get('trans_engine'), self.config.get('trans_api'))
            QMessageBox.warning(self, "保存失败", "无法写入配置，请检查数据目录的写入权限。原有配置已保留。")
            return

        self.accept()
