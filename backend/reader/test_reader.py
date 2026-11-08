import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QGuiApplication
from reader import clean_text, chunks, same_text, Task


class ReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication(['test'])

    def test_book_words_preserved(self):

        original = '21.46:08,188s Verdacht auf Reproiden-Ausbruch im\nRegenwaldgebiet.\n\n»Nate?«, fragte er. Das ist nicht die Venus.'
        cleaned = clean_text(original)
        self.assertEqual(' '.join(original.split()), ' '.join(cleaned.split()))
        self.assertEqual(' '.join(original.split()), ' '.join(chunks(cleaned, 65)))
        self.assertTrue(all(len(c) <= 65 for c in chunks(cleaned, 65)))

    def test_split_at_sentence_boundary(self):
        text = 'Die erste Geschichte endet hier. Die zweite Geschichte beginnt hier.'
        self.assertEqual(chunks(text, 55), ['Die erste Geschichte endet hier.', 'Die zweite Geschichte beginnt hier.'])

    def test_punctuation_only_chunks_do_not_reach_piper(self):
        self.assertEqual(chunks('»«\n\nHallo Welt.\n\n…'), ['Hallo Welt.'])

    def test_page_turn_for_a_hidden_book_waits(self):
        from reader import Reader
        subject = SimpleNamespace(enabled=True, paused=False, fail=Mock(), scan=Mock(), update=Mock())
        with patch('reader.QTimer.singleShot') as timer:
            Reader.page_turn_sent(subject, 1, '', 'The reading window is not on screen')
        subject.fail.assert_not_called()
        subject.update.assert_called_once_with('Waiting for the reading window')
        timer.assert_not_called()

    def test_error_notification_does_not_set_tray_attention(self):
        from reader import Reader
        subject = SimpleNamespace(update=Mock(), last_error='', tray=Mock())
        with patch('reader.subprocess.Popen') as notify:
            Reader.fail(subject, 'Speech failed')
        subject.tray.showMessage.assert_not_called()
        self.assertEqual(notify.call_args.args[0][0], 'notify-send')

    def test_error_notification_strips_markup(self):
        from reader import Reader
        subject = SimpleNamespace(update=Mock(), last_error='', tray=Mock())
        hostile = 'Provider said <img src="http://x/y.png"> &amp;\r\n\x1b[31m' + 'A' * 1000
        with patch('reader.subprocess.Popen') as notify:
            Reader.fail(subject, hostile)
        args = notify.call_args.args[0]
        for text in args[1:]:
            self.assertFalse(set(text) & set('<>&\r\n\x1b'))
        self.assertLessEqual(len(args[-1]), 300)

    def test_new_page_is_not_a_duplicate(self):
        self.assertTrue(same_text('Die Venus.\nEin neuer Tag.', 'Die Venus. Ein neuer Tag.'))
        self.assertFalse(same_text('Die Venus. Ein neuer Tag.', 'Der Mars. Eine andere Welt.'))

    def test_cancelled_child_cannot_restart_playback(self):
        app = self.app
        owner = QObject()
        owner.tasks = set()
        callbacks = []
        task = Task(owner, ['/usr/bin/sleep', '30'], lambda *args: callbacks.append(args))
        self.assertTrue(task.proc.waitForStarted(2000))
        task.cancel()
        QTimer.singleShot(10, app.quit)
        app.exec()
        self.assertEqual(callbacks, [])
        self.assertEqual(owner.tasks, set())


    def test_same_text_threshold(self):
        text_a = 'Dies ist eine Seite mit vielen Worten und einem kleinen OCR Fehler.'
        text_b = 'Dies ist eine Seite mit vielen Worten und einem kleinen 0CR Fehler.'
        self.assertTrue(same_text(text_a, text_b, threshold=0.80))
        text_c = 'Völlig anderer Text auf der nächsten Buchseite ohne Ähnlichkeit.'
        self.assertFalse(same_text(text_a, text_c, threshold=0.80))

    def test_playback_still_scans_visible_page(self):
        from reader import Reader
        subject = SimpleNamespace(
            enabled=True, paused=False, scanning=False, menu=Mock(), dialog=None,
            settings={'follow': True}, last_text='Old page', got_window=Mock(),
            is_speaking=lambda: True, target='0x123')
        subject.menu.isVisible.return_value = False
        with patch('reader.Task') as task:
            Reader.scan(subject)
        self.assertTrue(subject.scanning)
        self.assertIs(task.call_args.args[2], subject.got_window)
        self.assertEqual(task.call_args.args[1][-2:], ['window', '0x123'])

    def test_cancelling_ocr_releases_scan_flag(self):
        from reader import Reader
        task = Mock()
        subject = SimpleNamespace(
            epoch=0, scanning=True, overlay=Mock(), mpv_command=Mock(),
            speech_tasks=set(), tasks={task})
        with patch('reader.subprocess.run'):
            Reader.stop_speech(subject)
        self.assertFalse(subject.scanning)
        task.cancel.assert_called_once()

    def test_page_change_cancels_old_audio_before_stable_confirmation(self):
        from reader import Reader
        old = 'The previous page has text that should no longer be spoken.'
        new = 'Entirely different words appear after turning to the next chapter.'
        subject = SimpleNamespace(
            scanning=True, last_text=old, candidate='',
            is_speaking=lambda: True, stop_speech=Mock(), update=Mock(),
            scan=Mock(), settings={'highlight': False}, pump_pipeline=Mock())
        with patch('reader.Path.read_text'), patch('reader.visible_ocr', return_value=(new, '')), patch('reader.QTimer.singleShot'):
            Reader.recognized(subject, 0, '', '')
            subject.stop_speech.assert_called_once()
            self.assertEqual(subject.candidate, new)
            subject.pump_pipeline.assert_not_called()
            subject.is_speaking = lambda: False
            Reader.recognized(subject, 0, '', '')
        self.assertEqual(subject.last_text, new)
        self.assertEqual(' '.join(subject.queue), new)
        subject.pump_pipeline.assert_called_once()

    def test_unchanged_page_does_not_interrupt_playback(self):
        from reader import Reader
        text = 'These same words are still visible on the current book page.'
        subject = SimpleNamespace(scanning=True, last_text=text, candidate='', stop_speech=Mock())
        with patch('reader.Path.read_text'), patch('reader.visible_ocr', return_value=(text, '')):
            Reader.recognized(subject, 0, '', '')
        subject.stop_speech.assert_not_called()

    def test_obsolete_page_turn_is_cancelled(self):
        from reader import Reader
        subject = SimpleNamespace(settings={'auto_page_turn': True},
                                  is_kindle_target=lambda: True, update=Mock(),
                                  epoch=1, do_page_turn=Mock())
        with patch('reader.QTimer.singleShot') as timer:
            Reader.on_page_finished(subject)
        subject.epoch += 1
        timer.call_args.args[1]()
        subject.do_page_turn.assert_not_called()

    def test_voices_definition(self):
        from reader import VOICES
        self.assertIn('kokoro-martin', VOICES)
        self.assertIn('kokoro-heart', VOICES)
        self.assertIn('kerstin-fast', VOICES)
        self.assertIn('thorsten-fast', VOICES)
        self.assertNotIn('kerstin', VOICES)
        self.assertNotIn('thorsten', VOICES)
        for key, (label, engine, ref) in VOICES.items():
            self.assertIn(engine, ('kokoro', 'piper', 'qwen'))
            self.assertTrue(len(label) > 0)
            self.assertTrue(len(ref) > 0)

    def test_custom_area_handling(self):
        import re
        slurp_out = '120,340 800x600\n'
        match = re.match(r'^(\d+),(\d+)\s+(\d+)x(\d+)$', slurp_out.strip())
        self.assertIsNotNone(match)
        x, y, w, h = map(int, match.groups())
        self.assertEqual((x, y, w, h), (120, 340, 800, 600))
        geom = f'{x},{y} {w}x{h}'
        self.assertEqual(geom, '120,340 800x600')

    def test_kindle_area_proportions_and_scaling(self):
        # Window at (100, 100), size (1000, 800)
        win_x, win_y, win_w, win_h = 100, 100, 1000, 800
        # User selected area at (200, 180), size (700, 640)
        sel_x, sel_y, sel_w, sel_h = 200, 180, 700, 640

        # Calculate proportions
        rx = (sel_x - win_x) / win_w  # 0.10
        ry = (sel_y - win_y) / win_h  # 0.10
        rw = sel_w / win_w            # 0.70
        rh = sel_h / win_h            # 0.80

        self.assertAlmostEqual(rx, 0.10)
        self.assertAlmostEqual(ry, 0.10)
        self.assertAlmostEqual(rw, 0.70)
        self.assertAlmostEqual(rh, 0.80)

        # When window is moved to another monitor/position (1920, 0)
        moved_x, moved_y = 1920, 0
        cx = round(moved_x + rx * win_w)
        cy = round(moved_y + ry * win_h)
        cw = round(rw * win_w)
        ch = round(rh * win_h)
        self.assertEqual((cx, cy, cw, ch), (2020, 80, 700, 640))

        # When window is resized to (1200, 900)
        new_w, new_h = 1200, 900
        scaled_cw = round(rw * new_w)
        scaled_ch = round(rh * new_h)
        self.assertEqual((scaled_cw, scaled_ch), (840, 720))

    def test_defaults_include_kindle_area(self):
        from reader import DEFAULTS
        self.assertIn('kindle_area', DEFAULTS)
        self.assertIsNone(DEFAULTS['kindle_area'])


if __name__ == '__main__':
    unittest.main()

class PinnedWindowTests(unittest.TestCase):
    """The window reading starts in stays the book, wherever the focus goes."""
    def subject(self, target='0x123'):
        return SimpleNamespace(target=target, epoch=7, enabled=True, paused=False,
            scanning=True, scan=Mock(), stop_speech=Mock(), playing_file=None, captured=Mock(),
            capture_window_geometry=([10, 20], [800, 600]), update=Mock(), set_enabled=Mock(),
            target_title='Kindle', target_class='kindle', settings={'kindle_crop': False},
            custom_area=None, overlay=Mock(last_payload=None), is_kindle_target=lambda: False,
            image_candidate=None, ocr_image=None, last_text='', candidate='')

    def window(self, address, **extra):
        import json
        return json.dumps(dict(address=address, pid=99999, at=[10, 20], size=[800, 600],
                               title='Kindle', **{'class': 'kindle'}, **extra))

    def test_unpinned_reader_takes_the_focused_window(self):
        from reader import Reader
        subject = SimpleNamespace(enabled=True, paused=False, scanning=False, menu=Mock(),
            settings={'follow': True}, last_text='', got_window=Mock(), target='')
        subject.menu.isVisible.return_value = False
        with patch('reader.Task') as task:
            Reader.scan(subject)
        self.assertEqual(task.call_args.args[1][-1], 'active-window')

    def test_focus_elsewhere_keeps_reading_the_book(self):
        from reader import Reader
        subject = self.subject()
        with patch('reader.Task') as task:
            Reader.got_window(subject, 0, self.window('0x123', focused=False, shown=True), '')
        subject.stop_speech.assert_not_called()
        self.assertEqual(subject.target, '0x123')
        self.assertEqual(task.call_args.args[1][2:4], ['capture-window', '0x123'])

    def test_book_off_screen_is_not_captured(self):
        from reader import Reader
        subject = self.subject()
        with patch('reader.Task') as task:
            Reader.got_window(subject, 0, self.window('0x123', focused=False, shown=False), '')
        task.assert_not_called()
        subject.stop_speech.assert_not_called()
        self.assertFalse(subject.scanning)

    def test_closed_book_stops_reading(self):
        from reader import Reader
        subject = self.subject()
        subject.book_closed = lambda: Reader.book_closed(subject)
        with patch('reader.Task') as task, patch('reader.desktop_notify'):
            Reader.got_window(subject, 0, '{}', '')
        task.assert_not_called()
        subject.set_enabled.assert_called_once_with(False)

    def test_malformed_window_answer_does_not_block_scanning(self):
        from reader import Reader
        import json
        good = json.loads(self.window('0x123'))
        answers = ['null', '[]', '"0x123"', '7', json.dumps(dict(good, title=5)),
                   json.dumps(dict(good, **{'class': ['kindle']})), json.dumps(dict(good, at=['10', 20])),
                   json.dumps(dict(good, size=[800])), json.dumps(dict(good, at=[True, 20])),
                   json.dumps(dict(good, address=['0x123'])), '{"error": "unavailable"}',
                   json.dumps({k: v for k, v in good.items() if k != 'address'}),
                   json.dumps(dict(good, address='')), json.dumps(dict(good, size=[1e309, 800])),
                   json.dumps(dict(good, size=[800.5, 600])), json.dumps(dict(good, at=[10 ** 12, 20])),
                   json.dumps(dict(good, size=[0, 600]))]
        for out in answers:
            subject = self.subject()
            subject.book_closed = Mock()
            with patch('reader.Task') as task:
                Reader.got_window(subject, 0, out, '')
            task.assert_not_called()
            subject.book_closed.assert_not_called()
            self.assertFalse(subject.scanning, out)

    def test_settings_window_is_not_pinned(self):
        from reader import Reader
        import json
        subject = self.subject(target='')
        settings = json.dumps(dict(address='0x9', pid=1, at=[0, 0], size=[800, 600], title='Maprisma Narrator',
                                   **{'class': 'com.maprisma.Narrator'}))
        with patch('reader.Task') as task:
            Reader.got_window(subject, 0, settings, '')
        task.assert_not_called()
        self.assertEqual(subject.target, '')

    def test_waiting_for_the_book_scans_with_new_pages_off(self):
        from reader import Reader
        subject = SimpleNamespace(enabled=True, paused=False, scanning=False, menu=Mock(),
            settings={'follow': False}, last_text='Read page', got_window=Mock(), target='0x123',
            status='Waiting for the reading window')
        subject.menu.isVisible.return_value = False
        with patch('reader.Task') as task:
            Reader.scan(subject)
        task.assert_called_once()

    def test_closed_book_stops_reading_with_new_pages_off(self):
        from reader import Reader
        subject = SimpleNamespace(enabled=True, paused=False, scanning=False, menu=Mock(),
            settings={'follow': False}, last_text='Read page', target='0x123', status='Reading',
            book_closed=Mock())
        subject.menu.isVisible.return_value = False
        subject.check_book_open = lambda *a: Reader.check_book_open(subject, *a)
        with patch('reader.Task') as task:
            Reader.scan(subject)
        self.assertEqual(task.call_args.args[1][-2:], ['window', '0x123'])
        task.call_args.args[2](0, self.window('0x123', focused=False, shown=True), '')
        subject.book_closed.assert_not_called()
        self.assertFalse(subject.scanning)
        # A failed look-up is not a closed book.
        subject.scanning = True
        task.call_args.args[2](1, '', 'The Maprisma Narrator extension is not running')
        subject.book_closed.assert_not_called()
        self.assertFalse(subject.scanning)
        # Only the documented {} is a closed book, not any other answer.
        task.call_args.args[2](0, '{"error": "unavailable"}', '')
        task.call_args.args[2](0, 'null', '')
        subject.book_closed.assert_not_called()
        task.call_args.args[2](0, '{}', '')
        subject.book_closed.assert_called_once()

    def test_closed_old_book_does_not_stop_a_repinned_reader(self):
        from reader import Reader
        subject = SimpleNamespace(enabled=True, paused=False, scanning=False, menu=Mock(),
            settings={'follow': False}, last_text='Read page', target='0x123', status='Reading',
            book_closed=Mock())
        subject.menu.isVisible.return_value = False
        subject.check_book_open = lambda *a: Reader.check_book_open(subject, *a)
        with patch('reader.Task') as task:
            Reader.scan(subject)
        subject.target = ''
        task.call_args.args[2](0, '{}', '')
        subject.book_closed.assert_not_called()
        self.assertFalse(subject.scanning)

    def test_read_again_repins(self):
        from reader import Reader
        subject = SimpleNamespace(enabled=True, target='0x123', stop_speech=Mock(), update=Mock(), scan=Mock())
        Reader.read_again(subject, repin=True)
        self.assertEqual(subject.target, '')
        subject.scan.assert_called_once()

    def test_read_again_menu_action_repins(self):
        import inspect
        from reader import Reader
        source = inspect.getsource(Reader.__init__)
        self.assertIn("addAction('Read active window again', lambda: self.read_again(repin=True))", source)

    def test_page_turn_goes_to_the_book_without_a_focus_check(self):
        from reader import Reader
        for target in ('0x123', '42', 'a1b2c3d4', 'ys5HHyprUKKV8GlnoU4fZ6a0et0HUg7X'):
            subject = SimpleNamespace(enabled=True, paused=False, epoch=7, target=target,
                pdf_keys=lambda: None, update=Mock(), page_turn_sent=Mock())
            with patch('reader.Task') as task:
                Reader.do_page_turn(subject)
            self.assertEqual(task.call_count, 1)
            self.assertEqual(task.call_args.args[1][-3:], ['send-key', target, 'Right'])

    def test_missed_kindle_page_turn_retries_then_stops_at_end(self):
        import hashlib, time
        from reader import Reader
        digest = hashlib.sha256(b'same page').digest()
        subject = SimpleNamespace(scanning=True, image_candidate=None, ocr_image=digest,
            status='Turning to next page…', page_turned_at=time.monotonic() - 1.5,
            turn_retries=0, is_speaking=lambda: False, do_page_turn=Mock(),
            set_enabled=Mock(), update=Mock())
        with patch('reader.Path.read_bytes', return_value=b'same page'):
            Reader.prepared(subject, 0, '', '')
            self.assertEqual(subject.turn_retries, 1)
            subject.do_page_turn.assert_called_once()
            subject.page_turned_at = time.monotonic() - 1.5
            Reader.prepared(subject, 0, '', '')
            self.assertEqual(subject.turn_retries, 2)
            self.assertEqual(subject.do_page_turn.call_count, 2)
            subject.page_turned_at = time.monotonic() - 3.5
            Reader.prepared(subject, 0, '', '')
            subject.set_enabled.assert_called_once_with(False)
            subject.update.assert_called_once_with('End of document')

    def test_turning_scans_new_page_even_with_follow_off(self):
        from reader import Reader
        subject = SimpleNamespace(enabled=True, paused=False, scanning=False, menu=Mock(),
            settings={'follow': False}, last_text='Read page', got_window=Mock(), target='0x123',
            status='Turning to next page…')
        subject.menu.isVisible.return_value = False
        with patch('reader.Task') as task:
            Reader.scan(subject)
        task.assert_called_once()
        self.assertIs(task.call_args.args[2], subject.got_window)

    def test_short_chapter_heading_and_illustration_page_after_turn(self):
        from reader import Reader
        subject = SimpleNamespace(scanning=True, last_text='Previous chapter text.', candidate='',
            status='Turning to next page…', page_turned_at=1.0, capture_stable=True,
            image_candidate=b'new', ocr_image=b'old', is_speaking=lambda: False,
            stop_speech=Mock(), settings={'highlight': False}, pump_pipeline=Mock(),
            on_page_finished=Mock(), update=Mock())
        with patch('reader.Path.read_text'), patch('reader.visible_ocr', return_value=('Chapter 4', '')):
            Reader.recognized(subject, 0, '', '')
        subject.pump_pipeline.assert_called_once()
        self.assertEqual(subject.last_text, 'Chapter 4')
        # A blank/illustration page after a turn moves on to the next page instead of stalling.
        subject.status = 'Turning to next page…'
        subject.image_candidate = b'illustration'
        with patch('reader.Path.read_text'), patch('reader.visible_ocr', return_value=('', '')):
            Reader.recognized(subject, 0, '', '')
        subject.on_page_finished.assert_called_once()

    def test_deferred_page_turn_resumes_after_focus_returns(self):
        from reader import Reader
        text = 'The same Kindle page remains visible while the reader regains focus.'
        subject = SimpleNamespace(scanning=True, last_text=text, candidate='',
            status='Waiting for the reading window', is_speaking=lambda: False,
            on_page_finished=Mock())
        with patch('reader.Path.read_text'), patch('reader.visible_ocr', return_value=(text, '')):
            Reader.recognized(subject, 0, '', '')
        subject.on_page_finished.assert_called_once()

class PageLatencyTests(unittest.TestCase):
    def test_short_opening_preserves_every_word(self):
        from reader import page_chunks
        text = 'A first sentence ends here. ' + 'The next sentence has a longer explanation about this story. '*8
        result=page_chunks(text)
        self.assertLessEqual(len(result[0]),110)
        self.assertEqual(' '.join(' '.join(result).split()), ' '.join(text.split()))

    def test_stability_checks_images_before_single_ocr_pass(self):
        from reader import Reader
        subject=SimpleNamespace(scanning=True, image_candidate=None, ocr_image=None,
            epoch=1, scan=Mock(), settings={'language':'en'}, recognized=Mock())
        with patch('reader.Path.read_bytes',return_value=b'new page'), patch('reader.QTimer.singleShot') as timer, patch('reader.Task') as task:
            Reader.prepared(subject,0,'','')
            task.assert_not_called()
            self.assertFalse(subject.scanning)
            subject.scanning=True
            Reader.prepared(subject,0,'','')
            task.assert_called_once()
            self.assertTrue(subject.capture_stable)
            self.assertEqual(task.call_args.args[0],subject)

    def test_unchanged_image_skips_ocr(self):
        import hashlib
        from reader import Reader
        subject=SimpleNamespace(scanning=True, image_candidate=None,
            ocr_image=hashlib.sha256(b'same page').digest(), status='Reading')
        with patch('reader.Path.read_bytes',return_value=b'same page'), patch('reader.Task') as task:
            Reader.prepared(subject,0,'','')
        self.assertFalse(subject.scanning)
        task.assert_not_called()

    def test_image_confirmed_page_does_not_need_second_ocr(self):
        from reader import Reader
        text='A new page with enough words for the reader to recognize and speak.'
        subject=SimpleNamespace(scanning=True,last_text='The old page',candidate='',
            capture_stable=True, image_candidate=b'new', stop_speech=Mock(),
            settings={'highlight':False}, pump_pipeline=Mock())
        with patch('reader.Path.read_text'), patch('reader.visible_ocr',return_value=(text,'')),patch('reader.QTimer.singleShot') as timer:
            Reader.recognized(subject,0,'','')
        timer.assert_not_called()
        subject.pump_pipeline.assert_called_once()
        self.assertEqual(subject.last_text,text)
