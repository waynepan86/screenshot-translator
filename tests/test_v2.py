"""Migration and real request/worker boundaries added in 2.0."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs
from PySide6.QtWidgets import QApplication, QTabWidget
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtCore import QRect
from config import ConfigManager
from runtime_paths import resolve_paths
from languages import LANGUAGES
import translator
import translation_service
import ocr
from capture_window import CaptureWindow, OCRThread, TranslationThread
from settings_dialog import SettingsDialog

app = QApplication.instance() or QApplication([])


class VersionTwoTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.program = self.root / 'program'
        self.program.mkdir()
        self.user = self.root / 'user'
        self.addCleanup(self.temporary.cleanup)
        self.old_state = (translator._engine, translator._creds)
        self.addCleanup(lambda: translator.configure(*self.old_state))

    def manager(self, portable=False):
        return ConfigManager(self.program, self.user, portable)

    def test_installed_config_never_uses_program_or_current_directory(self):
        config = self.manager()
        self.assertTrue((self.user / 'config.json').exists())
        self.assertFalse((self.program / 'config.json').exists())
        self.assertEqual(config.get('trans_target'), 'zh-CN')

    def test_portable_marker_and_explicit_flag_choose_data_root(self):
        (self.program / 'portable.flag').touch()
        self.assertEqual(resolve_paths(self.program, self.user).data_dir, self.program / 'data')
        with patch('sys.argv', ['app', '--portable']):
            self.assertTrue(resolve_paths(self.root, self.user).portable)
        config = self.manager(portable=True)
        self.assertTrue(config.paths.config_file.is_file())
        self.assertFalse(self.user.exists())

    def test_legacy_migration_preserves_credentials_direction_and_original(self):
        legacy = self.program / 'config.json'
        legacy.write_text(json.dumps({'hotkey_region':'Ctrl+F1', 'trans_engine':'deepl',
                                    'trans_api':{'deepl':{'key':'fixture-only:fx'}}}), encoding='utf-8')
        original = legacy.read_bytes()
        config = self.manager()
        self.assertEqual(config.get('trans_api')['deepl']['key'], 'fixture-only:fx')
        self.assertEqual(config.get('hotkey_region'), 'Ctrl+F1')
        self.assertEqual(config.get('trans_target'), 'auto')
        self.assertEqual(config.migrated_from, legacy)
        self.assertEqual(legacy.read_bytes(), original)
        config.set('trans_target', 'ja')
        self.assertEqual(self.manager().get('trans_target'), 'ja')
        self.assertIsNone(self.manager().migrated_from)

    def test_destination_wins_over_legacy_file(self):
        config = self.manager()
        config.set('trans_target', 'fr')
        (self.program / 'config.json').write_text('{"trans_target":"de"}', encoding='utf-8')
        self.assertEqual(self.manager().get('trans_target'), 'fr')

    def test_bad_legacy_file_is_not_overwritten_or_migrated(self):
        legacy = self.program / 'config.json'
        legacy.write_text('{broken', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, '原文件已保留'):
            self.manager()
        self.assertEqual(legacy.read_text(), '{broken')
        self.assertFalse((self.user / 'config.json').exists())

    def test_atomic_save_failure_preserves_disk_and_in_memory_settings(self):
        config = self.manager()
        before = config.paths.config_file.read_bytes()
        with patch('config.os.replace', side_effect=PermissionError('fixture')):
            with self.assertRaises(PermissionError):
                config.set('trans_target', 'ja')
        self.assertEqual(config.paths.config_file.read_bytes(), before)
        self.assertEqual(config.get('trans_target'), 'zh-CN')
        self.assertEqual(list(self.user.glob('.config-*.tmp')), [])

    def test_failed_migration_leaves_legacy_and_no_partial_destination(self):
        legacy = self.program / 'config.json'
        legacy.write_text('{"hotkey_region":"F6"}', encoding='utf-8')
        with patch('config.os.replace', side_effect=PermissionError('fixture')):
            with self.assertRaises(PermissionError):
                self.manager()
        self.assertTrue(legacy.exists())
        self.assertFalse((self.user / 'config.json').exists())

    def test_import_from_another_folder_preserves_old_file(self):
        config = self.manager()
        old = self.root / 'desktop-config.json'
        old.write_text('{"hotkey_region":"F7","trans_engine":"deepl","trans_api":{"deepl":{"key":"fixture:fx"}}}', encoding='utf-8')
        before = old.read_bytes()
        config.import_legacy(old)
        self.assertEqual(self.manager().get('hotkey_region'), 'F7')
        self.assertEqual(config.get('trans_target'), 'auto')
        self.assertEqual(old.read_bytes(), before)

    def test_invalid_nested_config_is_rejected_without_migration(self):
        (self.program / 'config.json').write_text('{"trans_api":"invalid"}', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'trans_api'):
            self.manager()
        self.assertFalse((self.user / 'config.json').exists())

    def test_invalid_import_preserves_existing_config(self):
        config = self.manager()
        old = self.root / 'bad.json'
        old.write_text('[]', encoding='utf-8')
        before = config.paths.config_file.read_bytes()
        with self.assertRaises(RuntimeError):
            config.import_legacy(old)
        self.assertEqual(config.paths.config_file.read_bytes(), before)

    def test_portable_archive_cannot_include_previous_user_data(self):
        from package import create_portable_archive
        bundle = self.root / 'bundle'
        bundle.mkdir()
        (bundle / 'app.exe').write_bytes(b'fixture')
        (bundle / 'config.json').write_text('fixture-secret')
        (bundle / 'data').mkdir()
        (bundle / 'data' / 'config.json').write_text('fixture-secret')
        portable = self.root / 'portable'
        portable.mkdir()
        (portable / 'private.json').write_text('fixture-secret')
        for name in ('README.md', 'USER_GUIDE.md'):
            (self.root / name).write_text('fixture')
        archive = self.root / 'release.zip'
        create_portable_archive(bundle, portable, archive, self.root)
        with zipfile.ZipFile(archive) as output:
            names = output.namelist()
            self.assertIn('portable/app.exe', names)
            self.assertIn('portable/portable.flag', names)
            self.assertFalse(any('config.json' in name or 'private.json' in name for name in names))

    def test_deepl_traditional_target_explicit_source_and_source_sensitive_cache(self):
        translator.configure('deepl', {'deepl':{'key':'fixture:fx'}})
        payloads = []
        def post(url, body, headers, timeout):
            payloads.append(json.loads(body))
            return {'translations':[{'text':'譯文'}]}
        with patch.object(translator, '_post', side_effect=post):
            translation_service.translate(['Hello'], 'zh-TW', source='en')
            translation_service.translate(['Hello'], 'zh-TW', source='en')
            translation_service.translate(['Hello'], 'zh-TW', source='fr')
        self.assertEqual(len(payloads), 2)
        self.assertEqual(payloads[0]['target_lang'], 'ZH-HANT')
        self.assertEqual(payloads[0]['source_lang'], 'EN')
        self.assertEqual(payloads[1]['source_lang'], 'FR')

    def test_russian_text_is_translated_rather_than_treated_as_literal(self):
        translator.configure('auto', {})
        with patch.object(translator, '_google_translate', return_value='你好') as google:
            result = translation_service.translate(['Привет'], 'zh-CN', source='ru')
        google.assert_called_once_with('Привет', 'ru', 'zh-CN')
        self.assertEqual(result[0]['text'], '你好')

    def test_baidu_and_youdao_language_codes_reach_request_body(self):
        translator.configure('baidu', {'baidu':{'appid':'fixture','secret':'fixture'}})
        with patch.object(translator, '_post', return_value={'trans_result':[{'dst':'Hola'}]}) as post:
            translator._baidu_translate('Bonjour', 'fr', 'es')
        payload = parse_qs(post.call_args.args[1].decode())
        self.assertEqual((payload['from'], payload['to']), (['fra'], ['spa']))
        translator.configure('youdao', {'youdao':{'appid':'fixture','secret':'fixture'}})
        with patch.object(translator, '_post', return_value={'translation':['譯文']}) as post:
            translator._youdao_translate('Hello', 'en', 'zh-TW')
        self.assertEqual(parse_qs(post.call_args.args[1].decode())['to'], ['zh-CHT'])

    def test_unknown_language_does_not_silently_become_chinese(self):
        with self.assertRaises(ValueError):
            translator._lang('deepl', 'unsupported', 'ZH')

    def test_missing_windows_pack_never_uses_another_language(self):
        engine = Mock()
        engine.is_language_supported.return_value = False
        with self.assertRaisesRegex(RuntimeError, 'ru-RU OCR'):
            ocr.choose_windows_engine(engine, str, 'ru-RU')
        engine.try_create_from_user_profile_languages.assert_not_called()
        engine.try_create_from_language.assert_not_called()

    def test_explicit_non_english_ocr_uses_windows_and_not_english_correction(self):
        async def recognize(*args):
            return {'text':'Bonjour', 'lines':[{'text':'Bonjour'}]}
        with patch.object(ocr, 'run_ocr_rapid') as rapid, patch.object(ocr, 'ocr_image_async', side_effect=recognize) as windows:
            result = ocr.run_ocr_sync('fixture.png', language_code='fr')
        rapid.assert_not_called()
        self.assertEqual(windows.call_args.args[1], 'fr-FR')
        self.assertEqual(result['text'], 'Bonjour')

    def test_workers_forward_source_and_target_languages(self):
        worker = OCRThread('fixture.png', language='ja')
        with patch.object(ocr, 'run_ocr_sync', return_value={'text':'', 'lines':[]}) as recognize:
            worker.run()
        self.assertEqual(recognize.call_args.kwargs['language_code'], 'ja')
        worker = TranslationThread(['Hello'], 'fr', source='en')
        with patch.object(translation_service, 'translate', return_value=[]) as translate:
            worker.run()
        self.assertEqual(translate.call_args.args[1], 'fr')
        self.assertEqual(translate.call_args.args[5], 'en')

    def test_capture_uses_configured_direction_and_keeps_multilingual_results(self):
        config = self.manager()
        config.update({'trans_source':'en', 'trans_target':'fr'})
        pixmap = QPixmap(300, 100)
        pixmap.fill(QColor('white'))
        window = CaptureWindow(pixmap, QRect(0,0,300,100), config)
        window.blocks = [dict(source='Hello', original='Hello')]
        with patch.object(TranslationThread, 'start'):
            window.start_translation()
        self.assertEqual(window.trans_target, 'fr')
        self.assertEqual(window.trans_thread.source, 'en')
        for target, result in [('ja','こんにちは世界'), ('ko','안녕하세요'), ('ru','Привет'), ('zh-TW','你好世界'), ('fr','Bonjour')]:
            window.trans_target = target
            self.assertTrue(window.is_translation_usable('Hello', result))
        window.close()

    def test_settings_persists_languages_and_renders_both_pages(self):
        config = self.manager(portable=True)
        dialog = SettingsDialog(config)
        dialog.source_combo.setCurrentIndex(dialog.source_combo.findData('en'))
        dialog.target_combo.setCurrentIndex(dialog.target_combo.findData('ja'))
        dialog.save_settings()
        self.assertEqual(self.manager(portable=True).get('trans_target'), 'ja')
        self.assertEqual(config.get('trans_source'), 'en')
        self.assertEqual(dialog.target_combo.count(), len(LANGUAGES) + 1)
        dialog.show()
        app.processEvents()
        output = Path('review_artifacts')
        output.mkdir(exist_ok=True)
        tabs = dialog.findChild(QTabWidget)
        dialog.grab().save(str(output / 'settings-v2-general.png'))
        tabs.setCurrentIndex(1)
        app.processEvents()
        dialog.grab().save(str(output / 'settings-v2-translation.png'))
        dialog.close()


if __name__ == '__main__':
    unittest.main()
