import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import translator
from reader import DEFAULTS, Reader, speech_language

LLM = dict(language='de', translate_to='ja', translator='llm',
           translator_endpoint='http://127.0.0.1:8080/v1', translator_model='local-model')


def reply(content):
    return json.dumps({'choices': [{'message': {'content': content}}]}).encode()


class TranslatorTests(unittest.TestCase):
    def test_llm_request_is_plain_chat_without_extra_text(self):
        with patch('translator.api_request', return_value=reply('ベルリン行きの電車です。')) as api:
            text = translator.translate({'text': 'Der Zug nach Berlin.', 'settings': LLM, 'token': ''})
        self.assertEqual(text, 'ベルリン行きの電車です。')
        endpoint, path, token, payload = api.call_args.args
        self.assertEqual((endpoint, path, token), ('http://127.0.0.1:8080/v1', '/chat/completions', ''))
        self.assertEqual(payload['model'], 'local-model')
        self.assertEqual(payload['temperature'], 0)
        self.assertIn('German', payload['messages'][0]['content'])
        self.assertIn('Japanese', payload['messages'][0]['content'])
        self.assertEqual(payload['messages'][1]['content'], 'Der Zug nach Berlin.')

    def test_reasoning_block_is_removed(self):
        with patch('translator.api_request', return_value=reply('<think>\nplan\n</think>\nHello.')):
            self.assertEqual(translator.translate({'text': 'Hallo.', 'settings': dict(LLM, translate_to='en')}), 'Hello.')

    def test_bad_replies_and_inputs_are_errors(self):
        for raw in (b'{}', json.dumps({'choices': [{'message': {'content': '  '}}]}).encode(),
                    json.dumps({'choices': [{'message': {'content': None}}]}).encode()):
            with patch('translator.api_request', return_value=raw), self.assertRaises(ValueError):
                translator.translate({'text': 'Hallo.', 'settings': LLM})
        for text in ('', '   ', 'x' * 4001, None, 7):
            with self.assertRaises(ValueError):
                translator.translate({'text': text, 'settings': LLM})
        for settings in (dict(LLM, translate_to='de'), dict(LLM, translate_to='xx'), dict(LLM, language=None),
                         dict(LLM, translator_model=''), dict(LLM, translator_model='m' * 300)):
            with patch('translator.api_request', return_value=reply('ok')), self.assertRaises(ValueError):
                translator.translate({'text': 'Hallo.', 'settings': settings})

    def test_remote_http_and_credentials_in_url_are_refused(self):
        for endpoint in ('http://example.org/v1', 'https://user:pw@example.org/v1', 'file:///etc/passwd', 'https://example.org/v1?x=1'):
            with self.assertRaises(ValueError):
                translator.translate({'text': 'Hallo.', 'settings': dict(LLM, translator_endpoint=endpoint)})

    def test_offline_translator_requires_installed_model(self):
        with patch('translator.MODEL_DIR', Path('/nonexistent-screen-narrator-nllb')):
            with self.assertRaisesRegex(ValueError, 'Install'):
                translator.translate_nllb('de', 'ja', 'Hallo.', folder=Path('/nonexistent-screen-narrator-nllb'))


class ReaderTranslationTests(unittest.TestCase):
    def test_speech_language_follows_translation_target(self):
        self.assertEqual(speech_language(dict(language='de', translate_to='')), 'de')
        self.assertEqual(speech_language(dict(language='de', translate_to='ja')), 'ja')

    def test_translation_is_off_by_default(self):
        self.assertEqual(DEFAULTS['translate_to'], '')

    def subject(self, **settings):
        values = DEFAULTS.copy()
        values.update(language='de', **settings)
        return SimpleNamespace(settings=values)

    def test_settings_validation(self):
        subject = self.subject()
        with patch('reader.available_voices', return_value={}), patch('reader.voice_is_available', return_value=True):
            accepted = Reader.validated_settings(subject, dict(translate_to='ja', translator='nllb'))
            self.assertEqual((accepted['translate_to'], accepted['translator']), ('ja', 'nllb'))
            # Translating into the text language means no translation.
            self.assertEqual(Reader.validated_settings(subject, dict(translate_to='de'))['translate_to'], '')
            for bad in (dict(translate_to='xx'), dict(translator='shell'), dict(translator_endpoint='http://example.org/v1'),
                        dict(translator_model='a\nb'), dict(translator_model=5)):
                with self.assertRaises(ValueError):
                    Reader.validated_settings(subject, bad)

    def test_chunks_are_translated_before_speech_but_not_voice_tests(self):
        subject = SimpleNamespace(queue=['Hallo Welt.'], enabled=True, paused=False, playing_file=None,
                                  highlight_queue=[[]], audio_highlights={}, testing_voice=False,
                                  settings=dict(DEFAULTS, language='de', translate_to='en'),
                                  translate_chunk=Mock(), synthesize_chunk=Mock())
        Reader.start_tts(subject)
        subject.translate_chunk.assert_called_once()
        subject.synthesize_chunk.assert_not_called()
        subject.queue, subject.testing_voice = ['Hello! This voice will read your text aloud.'], True
        Reader.start_tts(subject)
        subject.synthesize_chunk.assert_called_once()


class TranslationReadinessTests(unittest.TestCase):
    def checks(self, **settings):
        values = dict(DEFAULTS, language='de', translate_to='en', translator='llm',
                      translator_endpoint='http://127.0.0.1:8080/v1', translator_model='m')
        values.update(settings)
        return Reader.extra_checks(SimpleNamespace(settings=values))

    def test_off_means_no_check(self):
        self.assertEqual(self.checks(translate_to=''), [])

    def test_missing_model_and_stopped_server_are_reported(self):
        with patch('reader.nllb_ready', return_value=True):
            check = self.checks(translator_model='')[0]
        self.assertIn('no translator is set up', check['problem'])
        self.assertEqual([f['label'] for f in check['fixes']], ['Use the offline translator', 'Turn translation off', 'Use a translation server instead…'])
        with patch('reader.nllb_ready', return_value=False):
            first = self.checks(translator_model='')[0]['fixes'][0]
        self.assertEqual(first['command'], 'install-translator')
        with patch('reader.translator_reachable', return_value=False):
            self.assertIn('not running', self.checks()[0]['problem'])
        with patch('reader.translator_reachable', return_value=True):
            self.assertTrue(self.checks()[0]['ok'])

    def test_offline_translator_must_be_installed(self):
        with patch('reader.nllb_ready', return_value=False):
            self.assertIn('not installed', self.checks(translator='nllb')[0]['problem'])

    def test_offline_translator_is_chosen_automatically(self):
        subject = SimpleNamespace(settings=dict(DEFAULTS, language='de', translate_to='en', translator='llm', translator_model='', provider='Online'),
                                  save=Mock(), translator_models_loading=False, refresh_translator_models=Mock())
        with patch('reader.nllb_ready', return_value=True):
            Reader.auto_configure(subject)
        self.assertEqual(subject.settings['translator'], 'nllb')
        subject.save.assert_called()

    def test_probe_only_local_servers(self):
        import reader
        self.assertTrue(reader.translator_reachable('https://api.example.org/v1'))
        reader._REACHABLE.clear()
        self.assertFalse(reader.translator_reachable('http://127.0.0.1:9/v1'))


if __name__ == '__main__':
    unittest.main()
