"""Packaged runtime smoke check, invoked explicitly with --self-test PATH."""
import json
import traceback
from pathlib import Path


def run(output):
    report = {}
    try:
        import sys
        import os
        import numpy as np
        import cv2
        from PySide6.QtWidgets import QApplication, QLabel
        from PySide6.QtGui import QImage, QFont, QPainter, QColor, QFontDatabase
        from PySide6.QtCore import QRect
        from spellchecker import SpellChecker
        from config import DEFAULT_CONFIG
        from app_version import APP_VERSION
        from runtime_paths import resolve_paths
        from help_dialog import HelpDialog
        from about_dialog import AboutDialog
        from review_panel import OCRPanel
        import ocr
        app = QApplication.instance() or QApplication([])
        cfg=type('Config',(),{'get':lambda self,key:DEFAULT_CONFIG.get(key)})()
        help=HelpDialog(cfg,APP_VERSION)
        assert '小幅纠偏' in help.browser.toPlainText()
        about=AboutDialog(APP_VERSION)
        assert 'GitHub 项目' in about.resource_links.text()
        assert '使用说明' in about.resource_links.text()
        assert about.findChild(QLabel, 'authorCredit').text() == 'Created by Wayne'
        from background_repair import smooth_background
        assert smooth_background(np.full((20,40,3),70,dtype=np.uint8)) is not None
        panel=OCRPanel()
        panel.set_records([dict(original='Hello',source='Hello',translation='你好',status='测试')])
        assert panel.translation.toPlainText() == '你好'
        assert 'hello' in SpellChecker(language='en').known(['hello'])
        assert ocr.is_rapidocr_available()
        # The offscreen Windows platform does not enumerate installed fonts.
        # Explicitly load a system font so the fixture contains letters,
        # rather than unsupported-glyph boxes that no OCR can recognize.
        font_id = QFontDatabase.addApplicationFont(str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/arial.ttf'))
        assert font_id >= 0, 'Could not load the system font for OCR verification'
        sample=QImage(350,70,QImage.Format_RGB888); sample.fill(QColor('white'))
        painter=QPainter(sample); font=QFont(QFontDatabase.applicationFontFamilies(font_id)[0]); font.setPixelSize(26)
        painter.setFont(font); painter.setPen(QColor('black')); painter.drawText(12,42,'Hello world'); painter.end()
        # Keep the synthetic input beside the report for diagnosing bundled
        # font/model differences without capturing any user content.
        sample.save(str(Path(output).with_suffix('.ocr.png')))
        arr=np.frombuffer(sample.constBits(),np.uint8).reshape(70,sample.bytesPerLine())[:,:1050].reshape(70,350,3)
        result=ocr.run_ocr_rapid(arr[:,:,::-1].copy())
        assert result['lines'], 'OCR model produced no text'
        from pin_window import PinWindow
        from PySide6.QtGui import QPixmap, QGuiApplication
        from PySide6.QtCore import QPoint
        pin = PinWindow(QPixmap.fromImage(sample),QPixmap.fromImage(sample),QPoint(20,20))
        pin.show(); app.processEvents(); assert pin.isVisible(); pin.close()
        from window_selection import snapshot_windows
        bounds = snapshot_windows(QGuiApplication.screens())
        from settings_dialog import SettingsDialog
        settings=SettingsDialog(cfg)
        assert settings.target_combo.currentData() == 'zh-CN'
        assert settings.target_combo.count() == 12
        paths=resolve_paths()
        report=dict(ok=True,version=APP_VERSION,portable=paths.portable,help=True,about=True,settings=True,
                    translation_languages=11,windows_ocr_languages=ocr.windows_ocr_languages(),
                    spelling=True,pin=True,window_snapshot_count=len(bounds),ocr_text=result['text'],opencv=cv2.__version__)
        settings.close()
        panel.close(); help.close(); about.close()
    except Exception:
        report=dict(ok=False,error=traceback.format_exc())
    Path(output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['ok'] else 1

