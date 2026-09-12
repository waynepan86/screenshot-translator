import sys
from pathlib import Path
from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextBrowser, QPushButton


class HelpDialog(QDialog):
    def __init__(self, config, version):
        super().__init__()
        self.config = config
        self.version = version
        self.setWindowTitle('截图工具 · 使用说明')
        self.resize(720, 650)
        layout = QVBoxLayout(self)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setStyleSheet('QTextBrowser {background:#fafafa;color:#202124;padding:18px;font-size:15px;}')
        layout.addWidget(self.browser)
        close = QPushButton('关闭')
        close.clicked.connect(self.close)
        layout.addWidget(close)
        self.refresh()

    def refresh(self):
        base = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
        path = base / 'USER_GUIDE.md'
        guide = path.read_text(encoding='utf-8') if path.exists() else '说明文件缺失，请重新下载完整版本。'
        guide = guide.replace('{{region}}', self.config.get('hotkey_region')).replace('{{fullscreen}}', self.config.get('hotkey_fullscreen')).replace('{{version}}', self.version)
        self.browser.setMarkdown(guide)
