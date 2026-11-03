import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from online_provider import endpoint_url, store_token, saved_token, synthesize, list_models, api_request
from install_kokoro import ASSETS, download_asset
from reader import available_voices


class ProviderTests(unittest.TestCase):
    def test_only_https_or_loopback_is_allowed(self):
        self.assertEqual(endpoint_url('https://example.org/v1/'), 'https://example.org/v1')
        self.assertEqual(endpoint_url('http://localhost:8000'), 'http://localhost:8000')
        for value in ['http://example.org', 'https://user:secret@example.org', 'file:///tmp/a', 'https://example.org?token=secret']:
            with self.assertRaises(ValueError):
                endpoint_url(value)

    def test_token_storage_is_private_and_bound_to_endpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'credentials.json'
            store_token(path, 'https://provider.test', 'test-secret', True)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(saved_token(path, 'https://provider.test'), 'test-secret')
            self.assertEqual(saved_token(path, 'https://other.test'), '')
            store_token(path, 'https://provider.test', 'test-secret', False)
            self.assertFalse(path.exists())

    def test_speech_request_and_wav_validation(self):
        config = {'online_endpoint':'https://provider.test', 'online_model':'speech-model', 'online_voice':'voice-id'}
        wav = b'RIFF' + b'\x00' * 4 + b'WAVE' + b'\x00' * 32
        with tempfile.TemporaryDirectory() as folder, patch('online_provider.api_request', return_value=wav) as request:
            output=Path(folder)/'speech.wav'
            synthesize(config, 'test-token', 'Hello', output)
            payload=request.call_args.args[3]
            self.assertEqual(payload['input'], 'Hello')
            self.assertEqual(payload['response_format'], 'wav')
            self.assertEqual(payload['speed'], 1.)
            self.assertNotIn('token', payload)
            self.assertEqual(output.read_bytes(), wav)
            request.return_value=b'not audio'
            with self.assertRaises(ValueError):
                synthesize(config, 'test-token', 'Hello', output)

    def test_models_endpoint_accepts_custom_model_ids(self):
        with patch('online_provider.api_request', return_value=b'{"data":[{"id":"custom-speech"},{"id":"custom-speech"}]}'):
            self.assertEqual(list_models('https://provider.test',''), ['custom-speech'])

    def test_authentication_is_header_only_and_api_path_is_normalized(self):
        with patch('online_provider.urllib.request.build_opener') as build:
            build.return_value.open.return_value.__enter__.return_value.read.return_value=b'data'
            api_request('https://provider.test/v1','/models','test-token')
            req=build.return_value.open.call_args.args[0]
            self.assertEqual(req.full_url,'https://provider.test/v1/models')
            self.assertEqual(req.get_header('Authorization'),'Bearer test-token')
            self.assertNotIn('test-token',req.full_url)

    def test_language_model_selection_uses_distinct_assets(self):
        self.assertEqual([a[0] for a in ASSETS['de']], ['kokoro-martin.onnx','voices-martin.npz'])
        self.assertEqual([a[0] for a in ASSETS['en']], ['kokoro-v1.0.onnx','voices-v1.0.bin'])

    def test_download_failure_preserves_existing_model(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'model.onnx';target.write_bytes(b'old model')
            with patch('install_kokoro.urllib.request.urlopen',side_effect=OSError('offline')):
                with self.assertRaises(OSError):
                    download_asset('model.onnx','https://example.org/','missing-digest',Path(folder),lambda _:None)
            self.assertEqual(target.read_bytes(),b'old model')
            self.assertEqual(list(Path(folder).iterdir()),[target])

    def test_unavailable_optional_engines_are_not_advertised(self):
        with patch('reader.voice_is_available',side_effect=lambda key:key.startswith('kokoro-')):
            self.assertEqual(set(available_voices('de')),{'kokoro-martin'})
            self.assertEqual(set(available_voices('en')),{'kokoro-heart','kokoro-nicole','kokoro-adam','kokoro-bf_emma','kokoro-bm_george'})
            self.assertEqual(set(available_voices('es')),{'kokoro-ef_dora','kokoro-em_alex'})
            self.assertEqual(set(available_voices('nl')),set())

    def test_qwen_and_custom_piper_only_for_their_languages(self):
        with patch('reader.voice_is_available', return_value=True):
            dutch = set(available_voices('nl', {'piper_model': '/v/de_DE-thorsten-high.onnx'}))
            german = set(available_voices('de', {'piper_model': '/v/de_DE-thorsten-high.onnx'}))
        self.assertFalse({'qwen-kerstin', 'qwen-custom', 'piper-custom'} & dutch)
        self.assertTrue({'qwen-kerstin', 'piper-custom'} <= german)


if __name__ == '__main__':
    unittest.main()
