import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QFontMetrics, QPixmap, QFontDatabase
from PySide6.QtCore import QRect
import ocr
import ocr_review
import translation_layout
import translation_service
import translator
from capture_window import CaptureWindow
from review_panel import OCRPanel

app = QApplication.instance() or QApplication([])
Path('review_artifacts').mkdir(exist_ok=True)
for font_path in ('C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/segoeui.ttf'):
    if Path(font_path).exists():
        QFontDatabase.addApplicationFont(font_path)


def line(text, x=10, y=10, w=120, h=20, confidence=.98):
    return dict(text=text, x=x, y=y, w=w, h=h, confidence=confidence,
                words=[dict(text=text, x=x, y=y, w=w, h=h)])


class Config:
    def get(self, key):
        return {'ocr_review': True, 'hotkey_region': 'Ctrl+F1', 'hotkey_fullscreen': 'F2'}.get(key)


class PipelineTests(unittest.TestCase):
    def test_translation_completion_does_not_open_panel(self):
        pix=QPixmap(300,120); pix.fill(QColor('white'))
        window=CaptureWindow(pix,QRect(0,0,300,120),Config())
        window.crop_rect=QRect(0,0,300,120)
        window.toolbar=type('Toolbar',(),{'set_translate_state':lambda s,v:None,'hide':lambda s:None})()
        window.ocr_result={'text':'Hello','lines':[line('Hello')]}
        window.ensure_blocks()
        window.pending_indices=[0]
        window.trans_target='zh-CN'
        window.on_translation_finished([dict(ok=True,text='你好',engine='test')])
        self.assertIsNone(window.ocr_panel)
        self.assertIsNotNone(window.translated_pixmap)
        window.close()

    def test_inline_identifiers_do_not_split_prose(self):
        dummy=type('Dummy',(),{'same_script':lambda s,a,b:True})()
        lines=[line('Set the $PUID and $PGID variables',w=300),
               line('in the .env file for this container.',y=38,w=300)]
        self.assertEqual(len(CaptureWindow.group_lines_into_paragraphs(dummy,lines)),1)

    def test_smooth_gradient_restores_code_chip(self):
        import numpy as np
        from background_repair import smooth_background
        y,x=np.mgrid[:50,:220]
        base=np.stack([40+x*.2+y*.1,60+x*.1,70+y*.2+0*x],axis=-1).astype(np.uint8)
        dirty=base.copy()
        dirty[12:36,60:130]=200
        dirty[18:29,70:120]=30
        repaired=smooth_background(dirty)
        self.assertIsNotNone(repaired)
        self.assertLess(np.abs(repaired.astype(float)-base).max(),3)

    def test_columns_do_not_merge(self):
        self.assertEqual(len(ocr.merge_line_fragments([line('Left', w=60), line('Right', x=500)])), 2)

    def test_paragraphs_follow_columns_and_preserve_labels(self):
        dummy=type('Dummy',(),{'same_script':lambda s,a,b:True})()
        lines=[line('A long sentence in column one',w=300),line('A long sentence in column two',x=500,w=300),
               line('continues here',y=38,w=150),line('continues there',x=500,y=38,w=150)]
        result=CaptureWindow.group_lines_into_paragraphs(dummy,lines)
        self.assertEqual([len(p) for p in result],[2,2])
        self.assertEqual(len(CaptureWindow.group_lines_into_paragraphs(dummy,[line('Yes',w=30),line('myMethod',y=38,w=100)])),2)

    def test_close_fragments_merge(self):
        self.assertEqual(len(ocr.merge_line_fragments([line('Hello', w=60), line('world', x=77)])), 1)

    def test_confidence_and_regions_preserved(self):
        result = ocr.merge_line_fragments([line('test', confidence=.6)])[0]
        self.assertEqual(result['confidence'], .6)
        self.assertEqual(result['regions'][0]['text'], 'test')

    def test_single_character_and_identifiers(self):
        dummy = type('Dummy', (), {'trans_target': 'zh-CN'})()
        self.assertTrue(CaptureWindow.is_translation_usable(dummy, 'Yes', '是'))
        self.assertTrue(CaptureWindow.is_translation_usable(dummy, 'On', '开'))
        self.assertEqual(CaptureWindow.clean_text_for_translation(dummy, 'myMethod main.py v1.2'), 'myMethod main.py v1.2')

    def test_overflow_has_no_plan(self):
        self.assertIsNone(translation_layout.plan([line('开', w=12, h=14)], 'Enable automatic synchronization for this account', 500, 300))

    def test_long_token_wraps(self):
        font = QFont('Microsoft YaHei')
        font.setPixelSize(16)
        rows = translation_layout.wrap('https://example.com/verylongidentifier', font, 70)
        self.assertGreater(len(rows), 1)
        self.assertTrue(all(QFontMetrics(font).horizontalAdvance(r) <= 71 for r in rows))

    def test_emoji_wrap_preserves_unicode(self):
        font=QFont('Microsoft YaHei'); font.setPixelSize(16)
        text='你好😀这是完整译文'
        self.assertEqual(''.join(translation_layout.wrap(text,font,45)),text)

    def test_text_draw_stays_inside_box(self):
        import numpy as np
        image = QImage(500, 200, QImage.Format_RGB888)
        image.fill(QColor('white'))
        plan = translation_layout.plan([line('Enable', w=120, h=24)], '开启同步', 500, 200)
        self.assertIsNotNone(plan)
        painter = QPainter(image)
        translation_layout.draw(painter, plan, QColor('black'))
        painter.end()
        arr = np.frombuffer(image.constBits(), np.uint8).reshape(200, image.bytesPerLine())[:, :1500].reshape(200,500,3)
        ys, xs = np.where(np.any(arr != 255, axis=2))
        self.assertGreater(len(xs), 0)
        self.assertGreaterEqual(xs.min(), 10)
        self.assertLess(xs.max(), 130)
        self.assertGreaterEqual(ys.min(), 10)
        self.assertLess(ys.max(), 34)

    def test_review_evidence_required_and_protected(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'image.png'
            Image.new('RGB', (400,100), 'white').save(path)
            def rec(_):
                return {'lines': [line('hello', confidence=.99)]}
            result = ocr_review.review_result({'lines':[line('heilo', confidence=.7)]}, str(path), 1, rec)
            self.assertEqual(result['lines'][0]['text'], 'hello')
            self.assertEqual(result['lines'][0]['original_text'], 'heilo')
            result = ocr_review.review_result({'lines':[line('myMethod', confidence=.7)]}, str(path), 1, rec)
            self.assertEqual(result['lines'][0]['text'], 'myMethod')
            responses = iter([{'lines':[line('hello')]}, {'lines':[line('help')]}])
            result = ocr_review.review_result({'lines':[line('heilo', confidence=.7)]}, str(path), 1, lambda _: next(responses))
            self.assertEqual(result['lines'][0]['text'], 'heilo')

    def test_deepl_batch_context_cache_order(self):
        translator.configure('deepl', {'deepl':{'key':'test:fx'}})
        bodies=[]
        def post(url, body, headers, timeout):
            bodies.append(json.loads(body))
            return {'translations':[{'text':'译文'+t} for t in bodies[-1]['text']]}
        with patch.object(translator, '_post', post):
            progress=[]
            results=translation_service.translate(['Hello','World','Hello'], 'zh-CN', lambda a,b:progress.append((a,b)))
            self.assertEqual([r['text'] for r in results], ['译文Hello','译文World','译文Hello'])
            self.assertEqual(len(bodies), 1)
            self.assertEqual(bodies[0]['text'], ['Hello','World'])
            self.assertIn('World', bodies[0]['context'])
            self.assertEqual(progress[-1], (3,3))
            again=translation_service.translate(['Hello','World','Hello'], 'zh-CN')
            self.assertTrue(all(r['cached'] for r in again))
            self.assertEqual(len(bodies), 1)
            translation_service.translate(['Hello','World','Hello'], 'zh-CN', force=True)
            self.assertEqual(len(bodies), 2)

    def test_fallback_explicit_and_failure_not_cached(self):
        translator.configure('deepl', {'deepl':{'key':'test:fx'}})
        with patch.object(translator, '_post', side_effect=TimeoutError()), patch.object(translator, '_google_translate', return_value='你好'), patch.object(translator, 'translate_mymemory', return_value=None):
            out=translation_service.translate(['Hello'], 'zh-CN')[0]
            self.assertTrue(out['fallback'])
            self.assertEqual(out['engine'], 'Google')
            self.assertEqual(len(translator._cache), 0)
        with patch.object(translator, '_post', side_effect=TimeoutError()), patch.object(translator, '_google_translate', return_value=None), patch.object(translator, 'translate_mymemory', return_value=None):
            self.assertFalse(translation_service.translate(['Hello'], 'zh-CN')[0]['ok'])

    def test_deepl_batches_at_fifty(self):
        translator.configure('deepl', {'deepl':{'key':'test:fx'}})
        sizes=[]
        def post(url, body, headers, timeout):
            payload=json.loads(body)
            sizes.append(len(payload['text']))
            return {'translations':[{'text':'好'} for _ in payload['text']]}
        with patch.object(translator, '_post', post):
            out=translation_service.translate(['word'+str(i) for i in range(51)], 'zh-CN')
        self.assertEqual(sorted(sizes), [1,50])
        self.assertEqual(len(out),51)

    def test_erase_light_and_dark_and_preserve_neighbor(self):
        for bg,ink in [('white','black'),('#202124','#eeeeee')]:
            image=QImage(400,120,QImage.Format_RGB888)
            image.fill(QColor(bg))
            font=QFont('Microsoft YaHei'); font.setPixelSize(22)
            painter=QPainter(image); painter.setFont(font); painter.setPen(QColor(ink))
            painter.drawText(20,45,'Hello world')
            painter.drawText(240,45,'NEXT')
            painter.end()
            rect=QFontMetrics(font).tightBoundingRect('Hello world').translated(20,45)
            info=line('Hello world',rect.x(),rect.y(),rect.width(),rect.height())
            cleaned, colors=CaptureWindow.erase_text_pixels(None,image,[info])
            image.save('review_artifacts/original_'+('light' if bg=='white' else 'dark')+'.png')
            cleaned.save('review_artifacts/erase_'+('light' if bg=='white' else 'dark')+'.png')
            self.assertIsNotNone(colors[0])
            a=cleaned.copy(QRect(230,0,170,120)).convertToFormat(QImage.Format_RGBA8888)
            b=image.copy(QRect(230,0,170,120)).convertToFormat(QImage.Format_RGBA8888)
            self.assertEqual(bytes(a.constBits()), bytes(b.constBits()))
            import numpy as np
            area=cleaned.copy(rect).convertToFormat(QImage.Format_RGB888)
            pixels=np.frombuffer(area.constBits(),np.uint8).reshape(area.height(),area.bytesPerLine())[:, :area.width()*3].reshape(-1,3)
            expected=np.array(QColor(bg).getRgb()[:3])
            self.assertLessEqual(int(np.abs(pixels.astype(int)-expected).max()), 3)
            cleaned.save('review_artifacts/erase_'+('light' if bg=='white' else 'dark')+'.png')

    def test_panel_and_help_render(self):
        panel=OCRPanel()
        panel.set_records([dict(original='heilo',source='hello',translation='你好',badge='已纠错',status='局部重识别一致')])
        self.assertEqual(panel.source.toPlainText(), 'hello')
        panel.show(); app.processEvents()
        panel.grab().save('review_artifacts/panel.png')
        panel.close()
        from help_dialog import HelpDialog
        help=HelpDialog(Config(), '1.9.0')
        self.assertIn('Ctrl+F1',help.browser.toPlainText())
        help.show(); app.processEvents(); help.grab().save('review_artifacts/help.png'); help.close()

    def test_render_overflow_retains_original_pixels(self):
        pix=QPixmap(300,120); pix.fill(QColor('white'))
        window=CaptureWindow(pix,QRect(0,0,300,120),Config())
        window.crop_rect=QRect(0,0,300,120)
        window.toolbar=type('Toolbar',(),{'set_translate_state':lambda s,v:None,'hide':lambda s:None})()
        window.trans_target='en'
        window.blocks=[dict(paragraph=[line('开',w=12,h=14)],original='开',source='开',translation='Enable automatic synchronization for this account',restored=False,note='',result=dict(ok=True,engine='test'))]
        window.render_blocks()
        self.assertTrue(window.blocks[0]['overflow'])
        self.assertEqual(window.translated_pixmap.toImage(),pix.toImage())
        window.close()

    def test_cancel_during_translation_releases_worker(self):
        import time
        from capture_window import _retired_windows
        pix=QPixmap(300,120); pix.fill(QColor('white'))
        window=CaptureWindow(pix,QRect(0,0,300,120),Config())
        window.crop_rect=QRect(0,0,300,120)
        window.toolbar=type('Toolbar',(),{'set_translate_state':lambda s,v:None,'hide':lambda s:None,'close':lambda s:None})()
        window.ocr_result={'lines':[line('Hello')],'text':'Hello'}
        def slow(*args,**kwargs):
            time.sleep(.08)
            return [dict(ok=True,text='你好',engine='test')]
        with patch.object(translation_service,'translate',slow):
            window.start_translation()
            window.close_and_cancel()
            deadline=time.monotonic()+2
            while _retired_windows and time.monotonic()<deadline:
                app.processEvents()
                time.sleep(.01)
        self.assertEqual(_retired_windows,[])

    def test_click_to_focus_keeps_translation(self):
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QEvent,QPointF,Qt
        pix=QPixmap(300,120); pix.fill(QColor('white'))
        window=CaptureWindow(pix,QRect(0,0,300,120),Config())
        window.crop_rect=QRect(0,0,300,120)
        window.ocr_result={'text':'Hello','lines':[line('Hello')]}
        window.translated_pixmap=pix
        event=QMouseEvent(QEvent.MouseButtonPress,QPointF(150,60),QPointF(150,60),Qt.LeftButton,Qt.LeftButton,Qt.NoModifier)
        window.mousePressEvent(event)
        self.assertIsNotNone(window.ocr_result)
        self.assertIsNotNone(window.translated_pixmap)
        window.close()


if __name__ == '__main__':
    unittest.main()
