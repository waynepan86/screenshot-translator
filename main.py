import sys
import os

if __name__ == '__main__' and len(sys.argv) == 3 and sys.argv[1] == '--self-test':
    # Run before importing Qt so packaging failures are written to the report
    # instead of displaying a blocking bootloader exception dialog.
    from self_check import run
    sys.exit(run(sys.argv[2]))

import ctypes
import threading
from ctypes import wintypes

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox, QWidget, QDialog
from PySide6.QtCore import Qt, QPoint, QRect, QTimer
from PySide6.QtGui import QIcon, QAction, QGuiApplication, QPixmap, QPainter, QKeySequence, QBrush, QColor

from config import ConfigManager
from capture_window import CaptureWindow
from settings_dialog import SettingsDialog
import translator
import ocr

APP_VERSION = "1.10.0"

# Native Win32 Hotkey structures
WM_HOTKEY = 0x0312

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", ctypes.c_uint),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]

class HotkeyListenerWidget(QWidget):
    """
    Hidden window to listen for Win32 WM_HOTKEY messages.
    """
    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self.callback = callback
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.hide()

    def nativeEvent(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                self.callback(msg.wParam)
        return super().nativeEvent(event_type, message)


class ScreenshotApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        
        # Load Config
        self.config = ConfigManager()
        translator.configure(
            self.config.get("trans_engine"), self.config.get("trans_api"))
        
        # Capture windows tracking
        self.active_capture_window = None
        self.settings_dialog = None
        self.help_dialog = None
        
        # Set up hidden hotkey listener window
        self.listener_widget = HotkeyListenerWidget(self.on_hotkey_triggered)
        self.listener_hwnd = int(self.listener_widget.winId())
        
        # Initialize tray
        self.init_tray()
        
        # Register Hotkeys
        self.registered_hotkeys = {} # id -> (mods, vk, key_seq_str)
        self.register_all_hotkeys()
        
        # Pre-load the OCR engine in the background so the first capture
        # doesn't pay the model-loading cost
        threading.Thread(target=ocr.warm_up, daemon=True).start()
        
        # Check command line arguments for autostart
        if "--minimized" not in sys.argv:
            self.tray_icon.showMessage("截图工具已启动", "软件已在后台运行，按 F1 开始截图，F2 全屏截图", QSystemTrayIcon.Information, 3000)

    def load_app_icon(self):
        # Bundled app.ico (PyInstaller extracts to _MEIPASS); falls back to
        # a programmatically drawn lens icon if the file is missing.
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        ico = os.path.join(base, "app.ico")
        if os.path.exists(ico):
            return QIcon(ico)
        icon_pixmap = QPixmap(32, 32)
        icon_pixmap.fill(Qt.transparent)
        painter = QPainter(icon_pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(26, 115, 232)))
        painter.drawRoundedRect(QRect(2, 2, 28, 28), 8, 8)
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.drawEllipse(QPoint(16, 16), 7, 7)
        painter.setBrush(QBrush(QColor(26, 115, 232)))
        painter.drawEllipse(QPoint(16, 16), 3, 3)
        painter.end()
        return QIcon(icon_pixmap)
    
    def init_tray(self):
        # Create tray icon
        self.tray_icon = QSystemTrayIcon(self.app)
        
        icon = self.load_app_icon()
        self.app.setWindowIcon(icon)
        self.tray_icon.setIcon(icon)
        self.tray_icon.setToolTip("轻量级截图工具")

        # Context Menu
        menu = QMenu()
        
        act_capture = QAction("区域截图 (F1)", menu)
        act_capture.triggered.connect(lambda: self.trigger_screenshot(fullscreen=False))
        
        act_full = QAction("全屏截图 (F2)", menu)
        act_full.triggered.connect(lambda: self.trigger_screenshot(fullscreen=True))
        
        act_settings = QAction("设置...", menu)
        act_settings.triggered.connect(self.show_settings)
        
        act_about = QAction("关于", menu)
        act_about.triggered.connect(self.show_about)
        act_help = QAction("使用说明", menu)
        act_help.triggered.connect(self.show_help)
        
        act_exit = QAction("退出", menu)
        act_exit.triggered.connect(self.quit_app)

        menu.addAction(act_capture)
        menu.addAction(act_full)
        menu.addSeparator()
        menu.addAction(act_settings)
        menu.addAction(act_help)
        menu.addAction(act_about)
        menu.addSeparator()
        menu.addAction(act_exit)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def on_tray_activated(self, reason):
        if reason in [QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick]:
            self.trigger_screenshot(fullscreen=False)

    # Hotkey registration and management
    def register_all_hotkeys(self):
        # Hotkey IDs
        # 1: Region screenshot
        # 2: Fullscreen screenshot
        self.unregister_all_hotkeys()
        
        self.register_hotkey(1, self.config.get("hotkey_region"))
        self.register_hotkey(2, self.config.get("hotkey_fullscreen"))

    def parse_shortcut(self, key_str):
        # Modifiers flags
        MOD_ALT = 0x0001
        MOD_CONTROL = 0x0002
        MOD_SHIFT = 0x0004
        MOD_WIN = 0x0008
        
        mods = 0
        vk = 0
        
        parts = key_str.split("+")
        for part in parts:
            part = part.strip().upper()
            if part == "CTRL":
                mods |= MOD_CONTROL
            elif part == "ALT":
                mods |= MOD_ALT
            elif part == "SHIFT":
                mods |= MOD_SHIFT
            elif part in ["WIN", "META"]:
                mods |= MOD_WIN
            elif part.startswith("F") and len(part) > 1 and part[1:].isdigit():
                f_num = int(part[1:])
                vk = 111 + f_num # F1 is 112 (0x70)
            elif len(part) == 1:
                vk = ord(part)
            elif part == "SPACE":
                vk = 32
            elif part == "ENTER" or part == "RETURN":
                vk = 13
            elif part == "PRINTSCREEN" or part == "SNAPSHOT":
                vk = 44
                
        return mods, vk

    def register_hotkey(self, hotkey_id, key_seq_str):
        if not key_seq_str:
            return
            
        mods, vk = self.parse_shortcut(key_seq_str)
        if vk == 0:
            return
            
        # Register using user32 API bound to our hidden listener window
        res = ctypes.windll.user32.RegisterHotKey(self.listener_hwnd, hotkey_id, mods, vk)
        if res:
            self.registered_hotkeys[hotkey_id] = (mods, vk, key_seq_str)
        else:
            name = "区域截图" if hotkey_id == 1 else "全屏截图"
            self.tray_icon.showMessage(
                "快捷键冲突",
                f"{name}快捷键 ({key_seq_str}) 注册失败，可能已被其他软件占用，请进入设置修改。",
                QSystemTrayIcon.Warning,
                5000
            )

    def unregister_all_hotkeys(self):
        for hotkey_id in list(self.registered_hotkeys.keys()):
            ctypes.windll.user32.UnregisterHotKey(self.listener_hwnd, hotkey_id)
        self.registered_hotkeys.clear()

    def on_hotkey_triggered(self, hotkey_id):
        # Defer call slightly to prevent keyboard hooks blocking event delivery
        if hotkey_id == 1:
            QTimer.singleShot(50, lambda: self.trigger_screenshot(fullscreen=False))
        elif hotkey_id == 2:
            QTimer.singleShot(50, lambda: self.trigger_screenshot(fullscreen=True))

    # Core Screenshot Actions
    def trigger_screenshot(self, fullscreen=False):
        # Avoid opening multiple overlays simultaneously
        if self.active_capture_window:
            return
            
        # Temporarily hide settings panel if open to clean screen
        if self.settings_dialog and self.settings_dialog.isVisible():
            self.settings_dialog.hide()
            
        # Pause slightly so keypresses release and overlays hide completely
        QTimer.singleShot(150, lambda: self.capture_and_show(fullscreen))

    def capture_and_show(self, fullscreen):
        # Grab bounding sizes of all screens combined
        screens = QGuiApplication.screens()
        if not screens:
            return
            
        combined_rect = QRect()
        for s in screens:
            combined_rect = combined_rect.united(s.geometry())
            
        # Capture all monitors and stitch
        combined_pixmap = QPixmap(combined_rect.size())
        combined_pixmap.fill(Qt.transparent)
        
        painter = QPainter(combined_pixmap)
        for s in screens:
            # Grab full content of screen
            screen_pixmap = s.grabWindow(0)
            offset = s.geometry().topLeft() - combined_rect.topLeft()
            painter.drawPixmap(offset, screen_pixmap)
        painter.end()
        
        # Spawn Crop selector overlay window
        from window_selection import snapshot_windows
        window_bounds = snapshot_windows(screens) if not fullscreen else []
        self.active_capture_window = CaptureWindow(combined_pixmap, combined_rect, self.config)
        self.active_capture_window.window_bounds = [r.translated(-combined_rect.topLeft()) for r in window_bounds]
        self.active_capture_window.capture_done.connect(self.on_capture_completed)
        self.active_capture_window.capture_cancelled.connect(self.on_capture_cancelled)
        
        # If fullscreen shortcut (F2) is triggered
        if fullscreen:
            # Pre-select full screen bounds
            # This allows annotations, OCR, translation on fullscreen, keeping Snipaste experience
            self.active_capture_window.crop_rect = QRect(QPoint(0, 0), combined_rect.size())
            self.active_capture_window.show()
            self.active_capture_window.show_toolbar()
        else:
            self.active_capture_window.show()
            
        # Make overlay active window
        self.active_capture_window.activateWindow()

    def on_capture_completed(self, pixmap):
        self.active_capture_window = None
        self.tray_icon.showMessage("截图成功", "截图已复制到剪贴板，可直接粘贴使用", QSystemTrayIcon.Information, 1500)
        # Restore settings window if we hid it
        if self.settings_dialog:
            self.settings_dialog.show()

    def on_capture_cancelled(self):
        self.active_capture_window = None
        if self.settings_dialog:
            self.settings_dialog.show()

    # Settings and About Dialogs
    def show_settings(self):
        if self.settings_dialog:
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()
            return
            
        self.settings_dialog = SettingsDialog(self.config)
        self.settings_dialog.finished.connect(self.on_settings_closed)
        self.settings_dialog.show()

    def on_settings_closed(self, result):
        self.settings_dialog = None
        # Re-apply unconditionally: the dialog's test button configures the
        # translator with values that were never saved, so a cancelled dialog
        # must not leave them active.
        translator.configure(
            self.config.get("trans_engine"), self.config.get("trans_api"))
        if result == QDialog.Accepted:
            # Reload all hotkeys in case they were modified
            self.register_all_hotkeys()
            self.tray_icon.showMessage("设置已更新", "快捷键与配置已保存并生效", QSystemTrayIcon.Information, 1500)

    def show_help(self):
        from help_dialog import HelpDialog
        if self.help_dialog is None:
            self.help_dialog = HelpDialog(self.config, APP_VERSION)
        self.help_dialog.refresh()
        self.help_dialog.show()
        self.help_dialog.raise_()
        self.help_dialog.activateWindow()

    def show_about(self):
        QMessageBox.about(
            None,
            "关于轻量级截图工具",
            f"<h3>轻量级截图工具 v{APP_VERSION}</h3>"
            "<p>一款极致轻量化的桌面截图工具。</p>"
            "<b>核心特色：</b>"
            "<ul>"
            "<li>F1 区域自由截图 / F2 全屏截图</li>"
            "<li>RapidOCR (PP-OCRv6) 离线文字提取 (高精度/无需网络)</li>"
            "<li>中英自动互译的智能原位翻译 (可选 Azure/大模型/百度/有道/DeepL 引擎)</li>"
            "<li>基础标注工具：画笔、矩形、箭头、文字标注</li>"
            "<li>设置面板自定义快捷键、翻译引擎与自启动</li>"
            "</ul>"
            "<p>Powered by Wayne</p>"
        )

    def quit_app(self):
        self.unregister_all_hotkeys()
        self.tray_icon.hide()
        for widget in self.app.topLevelWidgets():
            widget.close()
        self._quit_timer = QTimer()
        self._quit_timer.timeout.connect(self.finish_quit)
        self._quit_timer.start(100)

    def finish_quit(self):
        from capture_window import _retired_windows
        if not _retired_windows:
            self._quit_timer.stop()
            self.app.quit()

    def run(self):
        return self.app.exec()


if __name__ == "__main__":
    # Fix High DPI scaling issues on Windows
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    
    app_instance = ScreenshotApp()
    sys.exit(app_instance.run())
