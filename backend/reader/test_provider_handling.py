import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import audio_output
from reader import Reader, DEFAULTS


class ProviderHandlingTests(unittest.TestCase):
    def test_audio_devices_exclude_disconnected_ports_and_keep_default(self):
        sinks = [dict(name='speakers', description='Desk speakers'),
                 dict(name='headset', active_port='phones',
                      ports=[dict(name='phones', availability='not available')])]
        with patch('audio_output.subprocess.run', return_value=SimpleNamespace(stdout=json.dumps(sinks))):
            choices = audio_output.outputs(refresh=True)
        self.assertEqual([v['value'] for v in choices], ['auto', 'pulse/speakers'])

    def test_missing_selected_output_does_not_fall_back_to_speakers(self):
        with patch('audio_output.outputs', return_value=[dict(value='auto')]):
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                audio_output.playback_output('pulse/disconnected-headset')
            self.assertEqual(audio_output.playback_output('auto'), 'auto')

    def subject(self):
        return SimpleNamespace(settings=DEFAULTS.copy(), enabled=False,
                               installing_kokoro=False, kokoro_checking=False,
                               online_token='current-secret', test_voice=Mock())

    def test_failed_preview_restores_provider_and_token_without_saving(self):
        subject = self.subject()
        subject.test_voice.side_effect = ValueError('speech server failed')
        candidate = dict(provider='Online', online_endpoint='https://speech.example/v1',
                         online_model='speech', online_voice='voice')
        with self.assertRaisesRegex(ValueError, 'failed'):
            Reader.test_provider(subject, candidate, 'candidate-secret')
        self.assertEqual(subject.settings, DEFAULTS)
        self.assertEqual(subject.online_token, 'current-secret')
        self.assertIsNone(subject.preview_original)

    def test_preview_uses_candidate_without_writing_active_settings(self):
        subject = self.subject()
        candidate = dict(provider='Online', online_endpoint='https://speech.example/v1',
                         online_model='speech', online_voice='voice')
        Reader.test_provider(subject, candidate, 'candidate-secret')
        self.assertEqual(subject.settings['provider'], 'Online')
        self.assertEqual(subject.preview_original, DEFAULTS)
        self.assertEqual(subject.preview_token, 'current-secret')
        with tempfile.TemporaryDirectory() as folder, patch('reader.CONFIG', Path(folder) / 'settings.json'):
            Reader.save(subject)
            saved = json.loads((Path(folder) / 'settings.json').read_text())
        self.assertEqual(saved, DEFAULTS)
        self.assertNotIn('candidate-secret', json.dumps(saved))

    def test_activation_requires_successful_test_and_unchanged_token(self):
        subject = self.subject()
        candidate = dict(provider='Online', online_endpoint='https://speech.example/v1',
                         online_model='speech', online_voice='voice')
        with self.assertRaisesRegex(ValueError, 'Test this provider'):
            Reader.use_provider(subject, candidate, 'candidate-secret')
        subject.verified_provider = candidate
        subject.verified_token_digest = hashlib.sha256(b'candidate-secret').hexdigest()
        subject.configure_settings = Mock()
        subject.configure_token = Mock()
        with self.assertRaisesRegex(ValueError, 'token'):
            Reader.use_provider(subject, candidate, 'different-secret')
        subject.configure_settings.assert_not_called()
        Reader.use_provider(subject, candidate, 'candidate-secret', False)
        subject.configure_settings.assert_called_once_with(candidate)
        subject.configure_token.assert_called_once_with('candidate-secret', False)

    def test_draft_files_do_not_change_active_provider(self):
        subject = self.subject()
        subject.settings['voice'] = 'piper-custom'
        original = subject.settings.copy()
        with patch('reader.available_voices', return_value={}), patch('reader.normalize_path', side_effect=lambda s: s):
            Reader.probe_provider(subject, {'piper_model': '/tmp/new-model.onnx'})
        self.assertEqual(subject.settings, original)
        self.assertEqual(subject.probed_voices, [])

    def test_incomplete_online_provider_cannot_be_activated(self):
        subject = self.subject()
        with self.assertRaisesRegex(ValueError, 'speech model'):
            Reader.validated_settings(subject, {'provider': 'Online'})
        self.assertEqual(subject.settings, DEFAULTS)


if __name__ == '__main__':
    unittest.main()
