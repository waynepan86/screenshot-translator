"""Packaged runtime smoke check, invoked explicitly with --self-test PATH."""
import json
import traceback
from pathlib import Path


def run(output):
    report = {}
    try:
        import sys
        import numpy as np
        import cv2
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QImage, QFont, QPainter, QColor
        from PySide6.QtCore import QRect
        from spellchecker import SpellChecker
        from config import DEFAULT_CONFIG
        from help_dialog import HelpDialog
        from review_panel import OCRPanel
        import ocr
        app = QApplication.instance() or QApplication([])
        cfg=type('Config',(),{'get':lambda self,key:DEFAULT_CONFIG.get(key)})()
        help=HelpDialog(cfg,'1.9.0')
        assert '本地复核' in help.browser.toPlainText()
        panel=OCRPanel()
        panel.set_records([dict(original='Hello',source='Hello',translation='你好',status='测试')])
        assert panel.translation.toPlainText() == '你好'
        assert 'hello' in SpellChecker(language='en').known(['hello'])
        assert ocr.is_rapidocr_available()
        sample=QImage(350,70,QImage.Format_RGB888); sample.fill(QColor('white'))
        painter=QPainter(sample); font=QFont('Microsoft YaHei'); font.setPixelSize(26)
        painter.setFont(font); painter.setPen(QColor('black')); painter.drawText(12,42,'Hello world'); painter.end()
        arr=np.frombuffer(sample.constBits(),np.uint8).reshape(70,sample.bytesPerLine())[:,:1050].reshape(70,350,3)
        result=ocr.run_ocr_rapid(arr[:,:,::-1].copy())
        assert result['lines'], 'OCR model produced no text'
        report=dict(ok=True,help=True,spelling=True,ocr_text=result['text'],opencv=cv2.__version__)
        panel.close(); help.close()
    except Exception:
        report=dict(ok=False,error=traceback.format_exc())
    Path(output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['ok'] else 1
