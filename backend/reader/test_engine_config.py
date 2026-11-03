import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace
from engine_config import normalize_path, engine_ready
from reader import Reader, DEFAULTS, voice_is_available


class EngineTests(unittest.TestCase):
    def test_paths_are_files_not_shell_expressions(self):
        self.assertEqual(normalize_path('~/voice model.onnx'), str(Path.home() / 'voice model.onnx'))
        self.assertEqual(normalize_path('/tmp/$(touch nope).onnx'), '/tmp/$(touch nope).onnx')
        for value in ('relative/path', '/tmp/x\ncommand', '\x00', 42):
            with self.assertRaises(ValueError):
                normalize_path(value)

    def test_optional_voice_requires_executable_and_all_files(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            paths = [base / name for name in ('piper', 'model.onnx', 'model.json')]
            for path in paths:
                path.write_text('file')
            settings = dict(zip(('piper_runner', 'piper_model', 'piper_config'), map(str, paths)))
            self.assertFalse(engine_ready(settings, 'piper'))
            paths[0].chmod(0o700)
            self.assertTrue(voice_is_available('piper-custom', settings))
            paths[2].unlink()
            self.assertFalse(voice_is_available('piper-custom', settings))

    def test_voice_preview_does_not_scan_or_turn_page(self):
        subject = SimpleNamespace(enabled=False, settings=DEFAULTS.copy(), stop_speech=Mock(), pump_pipeline=Mock())
        with patch('reader.voice_is_available', return_value=True):
            Reader.test_voice(subject)
        self.assertTrue(subject.testing_voice)
        self.assertEqual(len(subject.queue), 1)
        subject.pump_pipeline.assert_called_once()
        subject.set_enabled = Mock(); subject.update = Mock()
        subject.do_page_turn = Mock()
        Reader.on_page_finished(subject)
        subject.set_enabled.assert_called_once_with(False)
        subject.do_page_turn.assert_not_called()

    def test_failed_optional_config_does_not_replace_active_settings(self):
        subject = SimpleNamespace(settings=DEFAULTS.copy())
        with self.assertRaises(ValueError):
            Reader.configure_settings(subject, {'voice': 'piper-custom', 'piper_runner': '/missing'})
        self.assertEqual(subject.settings['voice'], 'kokoro-martin')
