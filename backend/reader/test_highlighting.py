import unittest
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from highlighting import chunk_rectangles, visible_ocr


def tsv(words):
    header = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
    page = '1\t1\t0\t0\t0\t0\t0\t0\t1000\t800\t-1\t\n'
    return header + page + ''.join(
        f'5\t1\t1\t1\t{line}\t{i}\t{x}\t{y}\t{w}\t20\t95\t{text}\n'
        for i, (text, line, x, y, w) in enumerate(words, 1))


class HighlightTests(unittest.TestCase):
    def test_visible_ocr_preserves_literal_quotes(self):
        data = tsv([('"Hallo!"', 1, 20, 40, 70)])
        text, aligned = visible_ocr(data)
        self.assertEqual(text, '"Hallo!"')
        self.assertEqual(len(chunk_rectangles(aligned, [text], (0, 0, 1000, 800))[0]), 1)

    def test_clipped_line_removed_from_speech_and_boxes(self):
        data = tsv([('garbled', 1, 20, 0, 70), ('fragment', 1, 100, 4, 70),
                    ('Hallo.', 2, 20, 40, 70), ('clipped', 3, 20, 790, 70)])
        text, aligned = visible_ocr(data)
        self.assertEqual(text, 'Hallo.')
        self.assertNotIn('garbled', aligned)
        self.assertNotIn('fragment', aligned)
        self.assertNotIn('clipped', aligned)
        self.assertEqual(chunk_rectangles(aligned, [text], (0, 0, 1000, 800)),
                         [[dict(x=20, y=40, width=70, height=20)]])

    def test_saved_kindle_area_is_used_for_capture_and_highlight(self):
        from reader import Reader
        subject = SimpleNamespace(
            target='0x123', custom_area=None, is_kindle_target=lambda: True,
            settings={'kindle_area': [.1, .2, .7, .6], 'kindle_crop': True},
            epoch=0, playing_file=None,
            overlay=Mock())
        window = dict(address='0x123', at=[100, 200], size=[1000, 800],
                      title='Kindle', **{'class': 'Kindle'})
        subject.captured = Mock()
        with patch('reader.Task') as task:
            Reader.got_window(subject, 0, json.dumps(window), '')
        self.assertEqual(subject.capture_area, (200, 328, 700, 512))
        self.assertEqual(task.call_args.args[1][-2], '200,328 700x512')

    def playing_subject(self):
        from reader import Reader
        subject = SimpleNamespace(
            settings={'audio_output': 'auto', 'speed': 1.0, 'highlight': True}, paused=False,
            enabled=True, epoch=0, target='0x123', overlay=Mock(), queue=[], update=Mock(),
            audio_highlights={'a.wav': [dict(x=1, y=2, width=3, height=4)]}, fail=Mock())
        done = {}
        def speech_task(args, on_done, timeout):
            done['callback'] = on_done
            return object()
        subject.speech_task = speech_task
        subject.pump_pipeline = Mock()
        subject.start_player = lambda wav: Reader.start_player(subject, wav)
        with patch('reader.playback_output', return_value='auto'):
            Reader.start_player(subject, 'a.wav')
        subject.overlay.show.reset_mock()
        return subject, done['callback']

    def test_next_chunk_moves_highlight_without_blank(self):
        subject, on_done = self.playing_subject()
        subject.audio_highlights['b.wav'] = [dict(x=5, y=6, width=7, height=8)]
        pending = ['b.wav']
        def pump():
            if pending:  # start_player pumps again for look-ahead: start b only once.
                with patch('reader.playback_output', return_value='auto'):
                    subject.start_player(pending.pop())
        subject.pump_pipeline.side_effect = pump
        on_done(0, '', '')
        shown = [c.args[0] for c in subject.overlay.show.call_args_list]
        self.assertEqual(shown, [[dict(x=5, y=6, width=7, height=8)]])

    def test_last_chunk_clears_highlight(self):
        subject, on_done = self.playing_subject()
        subject.pump_pipeline.side_effect = lambda: None
        on_done(0, '', '')
        subject.overlay.show.assert_called_once_with([])

    def test_failed_playback_clears_and_reports(self):
        subject, on_done = self.playing_subject()
        subject.queue = ['x']
        on_done(1, '', 'boom')
        subject.overlay.show.assert_called_once_with([])
        self.assertEqual(subject.queue, [])
        subject.fail.assert_called_once()

    def test_kindle_headroom_stays_inside_window(self):
        from reader import Reader
        subject = SimpleNamespace(
            target='0x123', custom_area=None, is_kindle_target=lambda: True,
            settings={'kindle_area': [.1, .01, .7, .6], 'kindle_crop': True},
            epoch=0, playing_file=None, overlay=Mock(), captured=Mock())
        window = dict(address='0x123', at=[100, 200], size=[1000, 800],
                      title='Kindle', **{'class': 'Kindle'})
        with patch('reader.Task'):
            Reader.got_window(subject, 0, json.dumps(window), '')
        self.assertEqual(subject.capture_area, (200, 200, 700, 488))

    def test_multiline_hyphenation_and_hidpi(self):
        data = tsv([('Ein', 1, 20, 40, 30), ('Raum-', 1, 60, 40, 60),
                    ('schiff.', 2, 20, 70, 70), ('Weiter.', 2, 100, 70, 60)])
        boxes = chunk_rectangles(data, ['Ein Raumschiff.', 'Weiter.'], (100, 200, 500, 400))
        self.assertEqual(boxes, [[dict(x=110, y=220, width=50, height=10),
                                  dict(x=110, y=235, width=35, height=10)],
                                 [dict(x=150, y=235, width=30, height=10)]])

    def test_repeated_sentences_keep_reading_order(self):
        data = tsv([('Ja.', 1, 20, 40, 30), ('Ja.', 2, 20, 80, 30)])
        boxes = chunk_rectangles(data, ['Ja.', 'Ja.'], (-500, 0, 1000, 800))
        self.assertEqual([b[0]['y'] for b in boxes], [40, 80])
        self.assertEqual(boxes[0][0]['x'], -480)

    def test_unmatched_text_never_guesses_box(self):
        data = tsv([('Hallo.', 1, 20, 40, 70)])
        self.assertEqual(chunk_rectangles(data, ['Anders.'], (0, 0, 1000, 800)), [[]])
        self.assertEqual(chunk_rectangles('', ['Hallo.'], (0, 0, 1000, 800)), [[]])

    def test_quotes_are_literal_and_footer_can_be_skipped(self):
        data = tsv([('"Hallo!"', 1, 20, 40, 70), ('Position', 2, 20, 80, 70),
                    ('Noch', 3, 20, 120, 50), ('etwas.', 3, 80, 120, 60)])
        boxes = chunk_rectangles(data, ['"Hallo!" Noch etwas.'], (0, 0, 1000, 800))
        # A removed footer inside a chunk cannot be aligned exactly; fail closed.
        self.assertEqual(boxes, [[]])
        boxes = chunk_rectangles(data, ['"Hallo!"', 'Noch etwas.'], (0, 0, 1000, 800))
        self.assertEqual(len(boxes[0]), 1)
        self.assertEqual(boxes[1][0]['y'], 120)


if __name__ == '__main__':
    unittest.main()
