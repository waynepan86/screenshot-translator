from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


PROJECT_URL = "https://github.com/waynepan86/screenshot-translator"
HELP_URL = "app://help"


class AboutDialog(QDialog):
    help_requested = Signal()

    def __init__(self, version, parent=None):
        super().__init__(parent)
        self.setWindowTitle("关于截图工具 · Screenshot Translator")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(12)

        content = QLabel(
            f"<h3>截图工具 · Screenshot Translator</h3>"
            f"<p>版本 {version}</p>"
            "<p>一款 Windows 截图翻译工具：框选屏幕，识别并翻译文字，"
            "将译文显示在原文位置，方便阅读外文网页、软件界面和文档。</p>"
            "<b>主要功能：</b>"
            "<ul>"
            "<li>F1 区域自由截图 / F2 全屏截图</li>"
            "<li>本地 OCR 与后台小幅纠偏，支持 DeepL 等在线翻译服务</li>"
            "<li>原位译文显示，按住空格查看原图</li>"
            "<li>F3 贴图置顶，支持拖动、缩放和透明度调整</li>"
            "<li>窗口选择、常用标注及遮盖打码</li>"
            "</ul>"
        )
        content.setWordWrap(True)
        content.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(content)

        self.resource_links = QLabel(
            f"<a href='{PROJECT_URL}'>GitHub 项目</a>"
            f"&nbsp;&nbsp;·&nbsp;&nbsp;<a href='{HELP_URL}'>使用说明</a>"
        )
        self.resource_links.setObjectName("resourceLinks")
        self.resource_links.setAlignment(Qt.AlignCenter)
        self.resource_links.setOpenExternalLinks(False)
        self.resource_links.linkActivated.connect(self.open_resource)
        layout.addWidget(self.resource_links)

        author = QLabel("Created by Wayne")
        author.setObjectName("authorCredit")
        author.setAlignment(Qt.AlignCenter)
        author.setStyleSheet("color:#6b7280;")
        layout.addWidget(author)

        close = QPushButton("关闭")
        close.setObjectName("closeButton")
        close.clicked.connect(self.close)
        layout.addWidget(close, 0, Qt.AlignRight)

    def open_resource(self, url):
        if url == HELP_URL:
            self.help_requested.emit()
        elif url == PROJECT_URL:
            QDesktopServices.openUrl(QUrl(url))
