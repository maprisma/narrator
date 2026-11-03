import os
import re
import unittest
from unittest.mock import patch
import languages
from languages import KOKORO, LANGUAGES, PIPER

HEX = re.compile(r'^[0-9a-f]{64}$')


class LanguageCatalogTests(unittest.TestCase):
    def test_every_language_has_ocr_sample_and_a_local_voice(self):
        for code, (english, native, ocr, sample) in LANGUAGES.items():
            self.assertRegex(code, r'^[a-z]{2}$')
            self.assertRegex(ocr, r'^[a-z_]+$')
            self.assertTrue(english and native and sample.strip())
            self.assertTrue(code in PIPER or code in KOKORO, code)
        self.assertLessEqual(set(KOKORO) | set(PIPER), set(LANGUAGES))
        self.assertIn('ja', KOKORO)
        self.assertNotIn('ja', PIPER)  # Piper 1.8 cannot run its Japanese voice

    def test_piper_assets_are_pinned_and_checksummed(self):
        for code, (prefix, name, model, config, size) in PIPER.items():
            self.assertRegex(prefix, r'^[a-z]{2}/[a-z]{2}_[A-Z]{2}/[a-z0-9_]+/(x_low|low|medium|high)/$')
            self.assertTrue(name.startswith(prefix.split('/')[1] + '-') and name.endswith('.onnx'))
            self.assertRegex(model, HEX)
            self.assertRegex(config, HEX)
            self.assertGreater(size, 0)
        self.assertRegex(languages.PIPER_REVISION, r'^[0-9a-f]{40}$')

    def test_kokoro_voices_belong_to_one_language(self):
        seen = [voice for _, _, voices in KOKORO.values() for voice, _ in voices]
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(languages.kokoro_voice_language('martin'), 'de')
        self.assertEqual(languages.kokoro_voice_language('ef_dora'), 'es')
        self.assertIsNone(languages.kokoro_voice_language('unknown'))
        self.assertEqual(languages.kokoro_family('fr'), 'en')
        self.assertEqual(languages.kokoro_phonemes('en', 'bf_emma'), 'en-gb')
        self.assertEqual(languages.kokoro_phonemes('zh', 'zf_xiaobei'), 'cmn')

    def test_default_language_follows_locale(self):
        for value, expected in (('fr_FR.UTF-8', 'fr'), ('nb_NO.UTF-8', 'no'), ('C.UTF-8', 'en'), ('xx_YY', 'en'), ('', 'en')):
            with patch.dict(os.environ, {'LC_ALL': '', 'LC_MESSAGES': '', 'LANG': value}):
                self.assertEqual(languages.default_language(), expected)

    def test_untrusted_codes_fall_back_safely(self):
        for value in (None, 7, '../de', 'de\n', 'xx'):
            self.assertFalse(languages.valid(value))
            self.assertEqual(languages.ocr_language(value), 'eng')
