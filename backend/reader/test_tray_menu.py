import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from reader import Reader


class TrayMenuTests(unittest.TestCase):
    """Launch & Bind reads the tray menu over D-Bus; choices must be real, checkable actions."""

    def test_choice_menu_marks_current_and_calls_handler(self):
        menu, handler = Mock(), Mock()
        made = []
        def add_action(label):
            action = Mock(label=label)
            made.append(action)
            return action
        menu.addAction.side_effect = add_action
        with patch('reader.QActionGroup'):
            actions = Reader.fill_choice_menu(None, menu, [('de', 'German · Deutsch'), ('en', 'English')], 'en', handler)
        menu.clear.assert_called_once()
        self.assertEqual(list(actions), ['de', 'en'])
        actions['de'].setChecked.assert_called_with(False)
        actions['en'].setChecked.assert_called_with(True)
        callback = actions['de'].triggered.connect.call_args.args[0]
        callback()
        handler.assert_called_once_with('de')

    def test_menu_setting_reports_invalid_choice(self):
        subject = SimpleNamespace(configure_settings=Mock(side_effect=ValueError('Unknown language')), fail=Mock())
        Reader.menu_setting(subject, 'language', 'xx')
        subject.fail.assert_called_once_with('Unknown language')

    def test_rebuild_only_when_choices_change(self):
        subject = SimpleNamespace(settings=dict(language='de', voice='kokoro-martin', audio_output='auto', translate_to=''),
                                  choice_signature=None, voice_menu=Mock(), language_menu=Mock(), output_menu=Mock(), translate_menu=Mock(),
                                  voice_language=lambda: 'de', fill_choice_menu=Mock(return_value={}), set_voice=Mock())
        with patch('reader.available_voices', return_value={'kokoro-martin': ('Martin', 'kokoro', 'martin')}), \
             patch('reader.outputs', return_value=[dict(value='auto', label='System default')]):
            Reader.refresh_choice_menus(subject)
            Reader.refresh_choice_menus(subject)
            self.assertEqual(subject.fill_choice_menu.call_count, 4)
            subject.settings['language'] = 'en'
            Reader.refresh_choice_menus(subject)
            self.assertEqual(subject.fill_choice_menu.call_count, 8)


if __name__ == '__main__':
    unittest.main()


class StartStopTests(unittest.TestCase):
    """▶ Start, Stop and the tray actions call set_enabled(..., notify=True)."""

    def subject(self, enabled=False):
        from reader import DEFAULTS
        return SimpleNamespace(provider_status='', installing_kokoro=False, settings=dict(DEFAULTS),
                               preview_original=None, testing_voice=False, enabled=enabled, paused=False,
                               stop_speech=Mock(), tasks=set(), update=Mock(), timer=Mock(),
                               kokoro_worker=Mock(), translation_worker=Mock(), overlay=Mock(), scan=Mock(), readiness_checks=Mock(return_value=[]))

    def test_start_with_notification_starts_scanning(self):
        subject = self.subject()
        with patch('reader.voice_is_available', return_value=True), patch('reader.subprocess.Popen') as popen, \
             patch('reader.QTimer.singleShot') as single_shot:
            Reader.set_enabled(subject, True, notify=True)
        self.assertTrue(subject.enabled)
        subject.timer.start.assert_called_once()
        single_shot.assert_called_once()
        self.assertEqual(popen.call_args.args[0][0], 'notify-send')

    def test_stop_with_notification_stops_scanning(self):
        subject = self.subject(enabled=True)
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder, patch('reader.subprocess.Popen'), patch('reader.RUNTIME', Path(folder)):
            Reader.set_enabled(subject, False, notify=True)
        self.assertFalse(subject.enabled)
        subject.timer.stop.assert_called_once()


class ReadinessTests(unittest.TestCase):
    def subject(self, **settings):
        from reader import DEFAULTS
        values = dict(DEFAULTS, language='de', voice='kokoro-martin', provider='Local', audio_output='auto')
        values.update(settings)
        return SimpleNamespace(settings=values, voice_language=lambda: values['language'], extra_checks=lambda: [])

    def run_checks(self, subject, voice_ok=True, ocr={'deu', 'eng'}, outs=('auto',)):
        with patch('reader.voice_is_available', return_value=voice_ok), \
             patch('reader.available_voices', return_value={'kokoro-martin': ('Martin', 'kokoro', 'martin')} if voice_ok else {}), \
             patch('reader.ocr_languages', return_value=set(ocr)), \
             patch('reader.outputs', return_value=[dict(value=v, label=v) for v in outs]):
            return Reader.readiness_checks(subject)

    def test_all_ready(self):
        checks = self.run_checks(self.subject())
        self.assertTrue(all(c['ok'] for c in checks))
        self.assertEqual([c['label'] for c in checks], ['Voice · German', 'Text recognition · German', 'Audio output'])

    def test_each_problem_is_named(self):
        self.assertIn('no German voice', self.run_checks(self.subject(), voice_ok=False)[0]['problem'])
        self.assertIn('Text recognition for German', self.run_checks(self.subject(), ocr={'eng'})[1]['problem'])
        self.assertIn('not connected', self.run_checks(self.subject(audio_output='pulse/gone'))[2]['problem'])

    def test_failed_checks_offer_fixes(self):
        checks = self.run_checks(self.subject(audio_output='pulse/gone'), voice_ok=False, ocr={'eng'})
        # The first fix does the job in place: install the voice / OCR data for that language.
        self.assertEqual(checks[0]['fixes'][0], dict(label='Install German voice (about 340 MB)', command='setup', args=dict(language='de')))
        self.assertEqual(checks[1]['fixes'][0]['args'], dict(language='de', backend_only=True))
        self.assertEqual(checks[2]['fixes'], [dict(label='Use the system default output', settings=dict(audio_output='auto'))])

    def test_installed_voice_is_selected_automatically(self):
        subject = self.subject(voice='kokoro-heart')
        subject.save = Mock()
        with patch('reader.available_voices', return_value={'thorsten-fast': ('Thorsten', 'piper', 'x'), 'kokoro-martin': ('Martin', 'kokoro', 'martin')}):
            Reader.auto_configure(subject)
        self.assertEqual(subject.settings['voice'], 'kokoro-martin')
        subject.save.assert_called_once()
        self.assertTrue(all(c['fixes'] == [] for c in self.run_checks(self.subject())))

    def test_start_is_refused_with_the_reason(self):
        subject = StartStopTests().subject()
        subject.readiness_checks = Mock(return_value=[dict(ok=False, label='Voice', problem='No German voice selected')])
        with patch('reader.voice_is_available', return_value=True), patch('reader.subprocess.Popen'), \
             self.assertRaisesRegex(ValueError, 'No German voice'):
            Reader.set_enabled(subject, True, notify=True)
        self.assertFalse(subject.enabled)
        subject.timer.start.assert_not_called()


class NoticeTests(unittest.TestCase):
    def test_errors_are_kept_for_the_popup_and_info_is_not(self):
        import reader
        reader.NOTICES.clear()
        with patch('reader.subprocess.Popen'):
            reader.desktop_notify('Screen Narrator: ON', icon='audio-headphones')
            reader.desktop_notify('Screen Narrator cannot start', 'No <b>model</b> chosen', level='error')
            reader.desktop_notify('Screen Narrator', 'Area too small', level='warning')
        notices = reader.recent_notices()
        self.assertEqual([n['level'] for n in notices], ['error', 'warning'])
        self.assertEqual(notices[0]['title'], 'Screen Narrator cannot start')
        self.assertNotIn('<', notices[0]['text'])
        self.assertLess(notices[0]['id'], notices[1]['id'])
        for _ in range(10):
            with patch('reader.subprocess.Popen'):
                reader.desktop_notify('x', 'y', level='error')
        self.assertEqual(len(reader.NOTICES), 5)


class ManagedPiperTests(unittest.TestCase):
    """Piper voices installed by guided setup are listed and chosen like any other voice."""

    def test_installed_basque_voice_is_offered_and_chosen(self):
        import reader
        ready = lambda settings, engine: engine == 'piper' and str(settings.get('piper_model', '')).endswith('eu_ES-antton-medium.onnx')
        with patch('reader.engine_ready', side_effect=ready):
            voices = reader.available_voices('eu', {})
            self.assertIn('piper-eu', voices)
            self.assertEqual(voices['piper-eu'][0], 'Antton · Piper')
            self.assertNotIn('piper-eu', reader.available_voices('de', {}))
            subject = SimpleNamespace(settings=dict(reader.DEFAULTS, language='de', translate_to='eu', voice='kokoro-martin', provider='Local'),
                                      save=Mock(), voice_language=lambda: 'eu')
            Reader.auto_configure(subject)
        self.assertEqual(subject.settings['voice'], 'piper-eu')
