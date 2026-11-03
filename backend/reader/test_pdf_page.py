import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

import pdf_page
from pdf_page import find_page, viewer_keys


def screen(rows=300, cols=440, background=40):
    return np.full((rows, cols), background, dtype=np.uint8)


def page(img, top, bottom, left, right, text_rows=()):
    img[top:bottom, left:right] = 250
    for r in text_rows:                       # dark text lines inside the page
        img[r, left + 20:right - 20] = 20
    return img


class PageDetectionTests(unittest.TestCase):
    def test_single_page_beside_thumbnail_sidebar(self):
        img = screen()
        for t in (20, 110, 200):                  # sidebar thumbnails
            page(img, t, t + 70, 8, 60)
        page(img, 25, 280, 160, 380, text_rows=range(60, 200, 8))
        self.assertEqual(find_page(img), (160, 25, 220, 255, False))

    def test_topmost_page_piece_in_continuous_view(self):
        img = screen()
        page(img, 0, 130, 160, 380)               # rest of the current page
        page(img, 140, 300, 160, 380)             # next page, cut off
        self.assertEqual(find_page(img)[:4], (160, 0, 220, 130))
        self.assertFalse(find_page(img)[4])

    def test_tiny_leftover_is_skipped_and_cut_off_detected(self):
        img = screen()
        page(img, 0, 20, 160, 380)                # 7 % sliver of the previous page
        page(img, 30, 300, 160, 380)              # current page continues below
        x, y, w, h, cut = find_page(img)
        self.assertEqual((y, h, cut), (30, 270, True))

    def test_no_page_or_unframed_view(self):
        self.assertIsNone(find_page(screen()))                       # dark, no page
        self.assertIsNone(find_page(screen(background=250)))         # all bright: not a framed page
        self.assertIsNone(find_page(np.zeros((10, 10), dtype=np.uint8)))

    def test_known_viewers_only(self):
        self.assertEqual(viewer_keys("org.gnome.Evince", "a.pdf"), ("n", "Next"))
        self.assertEqual(viewer_keys("org.gnome.Papers", ""), ("n", "Next"))
        self.assertIsNone(viewer_keys("chromium", "a.pdf — Chromium"))
        self.assertIsNone(viewer_keys(None, None))


class PageNumberTests(unittest.TestCase):
    def test_page_numbers_at_top_and_bottom_are_not_read(self):
        from reader import clean_text
        cases = {
            'Chapter three. Nobody came.\n\n\nPage 3': 'Chapter three. Nobody came.',
            '12\nThe train left.\n- 13 -': 'The train left.',
            'Seite 3 von 10\nDer Zug fuhr ab.': 'Der Zug fuhr ab.',
            'The end.\n\n3 / 10': 'The end.',
            'Preface text.\nxiv': 'Preface text.',
        }
        for raw, spoken in cases.items():
            self.assertEqual(clean_text(raw), spoken)

    def test_text_is_kept(self):
        from reader import clean_text
        self.assertEqual(clean_text('I\nam here.'), 'I am here.')
        self.assertEqual(clean_text('Page 3 shows the map.'), 'Page 3 shows the map.')
        self.assertEqual(clean_text('One\n12 apples were left.'), 'One 12 apples were left.')


class PageTurnTests(unittest.TestCase):
    def turn(self, address, cut_off):
        from reader import Reader
        sent = []
        subject = SimpleNamespace(enabled=True, paused=False, epoch=1, target=address, pdf_cut_off=cut_off,
                                  pdf_keys=lambda: ("n", "Next"), update=Mock(), scan=Mock(), page_turn_sent=Mock())
        def task(owner, args, done, timeout=0, **kw):
            if args[-1] == 'active-window':
                done(0, '{"address": "%s"}' % address, '')
            else:
                sent.append(args)
        with patch('reader.Task', side_effect=task):
            Reader.do_page_turn(subject)
        return sent

    def test_next_page_or_scroll_sent_to_the_window(self):
        sent = self.turn('0x5d42d0731a60', False)
        self.assertEqual([args[-3:] for args in sent], [['send-key', '0x5d42d0731a60', 'n']])
        self.assertEqual(self.turn('0x5d42d0731a60', True)[0][-1], 'Next')

    def test_unexpected_window_address_is_not_formatted_into_a_command(self):
        self.assertEqual(self.turn('0x1" }) hl.dsp.exec_cmd("rm -rf ~', False), [])
