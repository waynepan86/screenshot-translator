import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QFontMetrics, QPixmap, QFontDatabase
from PySide6.QtCore import QRect, Qt
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
    def test_empty_selection_paints_only_translucent_mask(self):
        pix=QPixmap(200,100); pix.fill(QColor('white'))
        window=CaptureWindow(pix,QRect(0,0,200,100),Config())
        window.draw_magnifier=lambda *args:None
        image=QImage(200,100,QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        window.render(image)
        center=image.pixelColor(100,50)
        self.assertEqual(center.alpha(),100)
        self.assertLessEqual(center.red(),1)
        window.hover_window=QRect(20,20,80,40)
        image.fill(Qt.transparent); window.render(image)
        # Alpha 1 is visually transparent but remains part of the native
        # Windows layered-window hit-test region.
        self.assertEqual(image.pixelColor(50,35).alpha(),1)
        self.assertEqual(image.pixelColor(150,35).alpha(),100)
        window.close()

    def test_tight_three_line_heading_keeps_middle_row(self):
        dummy=type('Dummy',(),{'same_script':lambda s,a,b:True})()
        paragraphs=CaptureWindow.group_lines_into_paragraphs(dummy,[
            line('AI research and',x=52,y=45,w=467,h=71),
            line('products that put',x=48,y=112,w=535,h=73),
            line('safety at the frontier',x=46,y=173,w=634,h=75),
            line('AI will have a vast impact on the world.',x=752,y=114,w=399,h=28),
            line('Anthropic is a public benefit corporation',x=752,y=145,w=419,h=29)])
        self.assertEqual([len(p) for p in paragraphs],[3,2])
        self.assertEqual(CaptureWindow.merge_paragraph_text(None,paragraphs[0]),
                         'AI research and products that put safety at the frontier')
        layout=translation_layout.plan(paragraphs[0],'将安全置于前沿的人工智能研究与产品',1196,271)
        self.assertIsNotNone(layout)
        self.assertLessEqual(layout['height'],layout['box'].height()+.1)

    def test_paragraph_repair_removes_chip_backing_on_curved_gradient(self):
        import numpy as np
        y,x=np.mgrid[:110,:240]
        base=np.stack([40+x*.12+y*y*.002,65+x*.05+y*.08,80+x*.03+y*.1],axis=-1).astype(np.uint8)
        dirty=base.copy()
        dirty[22:48,80:135]=210
        dirty[28:40,20:180]=230
        dirty[68:78,20:180]=230
        image=QImage(dirty.data,240,110,dirty.strides[0],QImage.Format_RGB888).copy()
        cleaned,_=CaptureWindow.erase_text_pixels(None,image,[line('First line with PUID',x=20,y=26,w=190,h=16),line('Second line here',x=20,y=66,w=190,h=16)])
        pixels=np.frombuffer(cleaned.constBits(),np.uint8).reshape(110,cleaned.bytesPerLine())[:,:720].reshape(110,240,3)
        self.assertLessEqual(np.abs(pixels[24:46,82:132].astype(float)-base[24:46,82:132]).max(),4)

    def test_repair_padding_preserves_restored_neighbor(self):
        pix=QPixmap(300,120); pix.fill(QColor('white'))
        painter=QPainter(pix); painter.fillRect(QRect(10,31,120,20),QColor('blue')); painter.end()
        window=CaptureWindow(pix,QRect(0,0,300,120),Config()); window.crop_rect=window.rect()
        window.toolbar=type('Toolbar',(),{'set_translate_state':lambda s,v:None,'hide':lambda s:None})()
        window.trans_target='zh-CN'
        window.blocks=[dict(paragraph=[line('Hello world',y=10)],source='Hello world',translation='你好',restored=False,result=dict(ok=True,engine='test')),
                       dict(paragraph=[line('Keep original',y=31)],source='Keep original',translation='',restored=True,result={})]
        def erase(image, regions):
            repaired=image.copy(); repaired.fill(QColor('white')); return repaired,[QColor('black')]
        with patch.object(window,'erase_text_pixels',erase):
            window.render_blocks()
        self.assertEqual(window.translated_pixmap.toImage().copy(QRect(10,31,120,20)),pix.toImage().copy(QRect(10,31,120,20)))
        window.close()

    def test_large_heading_combines_without_merging_body(self):
        dummy=type('Dummy',(),{'same_script':lambda s,a,b:True})()
        paragraphs=CaptureWindow.group_lines_into_paragraphs(dummy,[
            line('AI research and',x=50,y=20,w=380,h=52),
            line('safety at the frontier',x=50,y=110,w=560,h=52),
            line('AI will have a profound impact on the world.',x=720,y=85,w=360,h=20)])
        self.assertEqual([len(p) for p in paragraphs],[2,1])
        layout=translation_layout.plan(paragraphs[0],'前沿人工智能研究与安全',1129,227)
        self.assertIsNotNone(layout)

    def test_repairs_use_original_and_finish_before_drawing(self):
        pix=QPixmap(300,120); pix.fill(QColor('white'))
        window=CaptureWindow(pix,QRect(0,0,300,120),Config())
        window.crop_rect=window.rect()
        window.toolbar=type('Toolbar',(),{'set_translate_state':lambda s,v:None,'hide':lambda s:None})()
        window.trans_target='zh-CN'
        window.blocks=[dict(paragraph=[line(text,x=10,y=y,w=120,h=20)],source=text,translation='你好',restored=False,result=dict(ok=True,engine='test')) for text,y in [('Hello world',10),('Another line',33)]]
        stages=[]
        def erase(image, regions):
            self.assertEqual(image,pix.toImage())
            stages.append('erase'); return image.copy(),[QColor('black')]
        real_draw=translation_layout.draw
        def draw(*args):
            stages.append('draw'); real_draw(*args)
        with patch.object(window,'erase_text_pixels',erase),patch.object(translation_layout,'draw',draw):
            window.render_blocks()
        self.assertEqual(stages,['erase','erase','draw','draw'])
        window.close()

    def test_inline_code_chips_rejoin_transitively_with_spaces(self):
        fragments = [line('container as non-root via the standard',x=140,y=182,w=463,h=28),
                     line('PUID',x=607,y=181,w=62,h=31),
                     line('and',x=674,y=187,w=45,h=26),
                     line('PGID',x=724,y=181,w=68,h=31),
                     line('environment variables. When using',x=794,y=181,w=428,h=32)]
        for fragment in fragments:
            fragment['words'][0]['whole_fragment'] = True
        merged = ocr.merge_line_fragments(fragments)
        self.assertEqual(len(merged),1)
        self.assertEqual(merged[0]['text'],'container as non-root via the standard PUID and PGID environment variables. When using')
        fragments = [line('a',x=139,y=503,w=21,h=24),line('.env',x=169,y=496,w=55,h=34),line('file.',x=228,y=502,w=55,h=25)]
        for fragment in fragments:
            fragment['words'][0]['whole_fragment'] = True
        merged = ocr.merge_line_fragments(fragments)
        self.assertEqual(len(merged),1)
        self.assertEqual(merged[0]['text'],'a .env file.')

    def test_cover_is_present_in_ocr_input(self):
        from capture_window import CoverShape
        from PySide6.QtCore import QPoint
        pix=QPixmap(200,100); pix.fill(QColor('white'))
        window=CaptureWindow(pix,QRect(0,0,200,100),Config())
        window.crop_rect=QRect(0,0,200,100)
        window.shapes=[CoverShape(QPoint(20,20),QPoint(60,40),QColor('black'),4)]
        path, scale = window.prepare_ocr_image()
        try:
            image = QImage(path)
            self.assertEqual(image.pixelColor(round(30*scale),round(30*scale)),QColor('black'))
        finally:
            os.unlink(path); window.close()

    def test_window_bounds_map_mixed_dpi(self):
        from window_selection import logical_bounds
        monitors = [(QRect(-1920,0,1920,1080),QRect(-1920,0,1920,1080)),
                    (QRect(0,0,2560,1440),QRect(0,0,1280,720))]
        self.assertEqual(logical_bounds(QRect(200,100,600,400),monitors),QRect(100,50,300,200))
        self.assertEqual(logical_bounds(QRect(-200,100,200,400),monitors),QRect(-200,100,200,400))

    def test_window_click_selects_and_drag_stays_manual(self):
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QEvent,QPointF,Qt
        pix=QPixmap(300,200); pix.fill(QColor('white'))
        for end, expected in [(QPointF(70,70),QRect(20,20,150,120)),(QPointF(130,110),QRect(70,70,61,41))]:
            window=CaptureWindow(pix,QRect(0,0,300,200),Config())
            window.window_bounds=[QRect(20,20,150,120)]
            window.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress,QPointF(70,70),QPointF(70,70),Qt.LeftButton,Qt.LeftButton,Qt.NoModifier))
            window.mouseMoveEvent(QMouseEvent(QEvent.MouseMove,end,end,Qt.NoButton,Qt.LeftButton,Qt.NoModifier))
            window.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease,end,end,Qt.LeftButton,Qt.NoButton,Qt.NoModifier))
            self.assertEqual(window.crop_rect,expected)
            window.close()

    def test_mixed_prose_correction_preserves_identifiers(self):
        from PIL import Image
        old = 'Set $PUID to 1000 and check the heilo message in .env'
        new = old.replace('heilo', 'hello')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'image.png'
            Image.new('RGB', (800, 100), 'white').save(path)
            result = ocr_review.review_result({'lines':[line(old, w=700, confidence=.7)]}, str(path), 1,
                                             lambda _: {'lines':[line(new, confidence=.99)]})
            self.assertEqual(result['lines'][0]['text'], new)
        self.assertFalse(ocr_review.safe_change(old, new.replace('$PUID', '$PUIO')))
        self.assertFalse(ocr_review.safe_change(old, new.replace('1000', '100')))
        self.assertFalse(ocr_review.safe_change('This sentence is unclear', 'A completely different sentence'))

    def test_linebreak_hyphens_preserve_compounds(self):
        self.assertEqual(ocr_review.join_broken_word('An environ-', 'ment variable'), 'An environment variable')
        self.assertEqual(ocr_review.join_broken_word('Run as non-', 'root'), 'Run as non-root')
        self.assertEqual(ocr_review.join_broken_word('winrt-', 'Windows'), 'winrt-Windows')

    def test_explicit_translation_linebreaks_survive(self):
        font = QFont('Microsoft YaHei'); font.setPixelSize(16)
        self.assertEqual(translation_layout.wrap('第一行\n第二行', font, 300), ['第一行', '第二行'])
        plan = translation_layout.plan([line('Label', w=120)], '标签', 300, 120)
        self.assertEqual(plan['align'], 'left')

    def test_pin_survives_capture_and_space_restores(self):
        from pin_window import _pins
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent, Qt
        original = QPixmap(300,120); original.fill(QColor('white'))
        translated = QPixmap(300,120); translated.fill(QColor('blue'))
        window = CaptureWindow(original, QRect(0,0,300,120), Config())
        window.crop_rect = QRect(10,10,100,50)
        window.translated_pixmap = translated.copy(QRect(0,0,100,50))
        window.is_translated_view = True
        window.pin_to_screen(); app.processEvents()
        self.assertEqual(len(_pins), 1)
        pin = next(iter(_pins))
        self.assertEqual(pin.image.toImage().pixelColor(20,20), QColor('blue'))
        self.assertEqual(pin.original.toImage().pixelColor(20,20), QColor('white'))
        pin.keyPressEvent(QKeyEvent(QEvent.KeyPress,Qt.Key_Space,Qt.NoModifier))
        self.assertTrue(pin.peek)
        pin.keyReleaseEvent(QKeyEvent(QEvent.KeyRelease,Qt.Key_Space,Qt.NoModifier))
        self.assertFalse(pin.peek)
        pin.close()
        from PySide6.QtCore import QCoreApplication
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(_pins)

    def test_cover_baked_into_original_and_translation(self):
        from capture_window import CoverShape
        from PySide6.QtCore import QPoint
        pix = QPixmap(200,100); pix.fill(QColor('white'))
        window = CaptureWindow(pix,QRect(0,0,200,100),Config())
        window.crop_rect=QRect(0,0,200,100)
        window.shapes=[CoverShape(QPoint(60,40),QPoint(20,20),QColor('black'),4)]
        for translated in (False,True):
            window.is_translated_view=translated; window.translated_pixmap=pix
            image=window.grab_cropped_pixmap().toImage()
            self.assertEqual(image.pixelColor(30,30),QColor('black'))
            self.assertEqual(image.pixelColor(10,10),QColor('white'))
        window.close()

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

