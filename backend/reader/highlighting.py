"""Map existing speech chunks to OCR boxes; no speech or extra OCR work."""
import bisect
import csv
import io
import json
from pathlib import Path

from PySide6.QtCore import QObject


def visible_ocr(tsv):
    """Use complete OCR lines for speech and their identical boxes for alignment.

    A crop through a glyph can produce confident-looking nonsense. Reject the
    whole clipped line rather than speaking fragments or inventing missing words.
    """
    reader = csv.DictReader(io.StringIO(tsv), delimiter='\t', quoting=csv.QUOTE_NONE)
    rows = list(reader)
    page = next(r for r in rows if r.get('level') == '1')
    width, height = int(page['width']), int(page['height'])
    lines = {}
    for row in rows:
        if row.get('level') == '5' and (row.get('text') or '').strip():
            key = tuple(row[k] for k in ('page_num', 'block_num', 'par_num', 'line_num'))
            lines.setdefault(key, []).append(row)
    kept, paragraphs = [], {}
    for key, words in lines.items():
        if any(int(w['top']) <= 1 or int(w['left']) <= 1
               or int(w['top']) + int(w['height']) >= height - 1
               or int(w['left']) + int(w['width']) >= width - 1 for w in words):
            continue
        kept.extend(words)
        paragraphs.setdefault(key[:3], []).append(' '.join(w['text'] for w in words))
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=reader.fieldnames, delimiter='\t',
                            quoting=csv.QUOTE_NONE, quotechar=None, lineterminator='\n')
    writer.writeheader()
    writer.writerows([page, *kept])
    return '\n\n'.join('\n'.join(lines) for lines in paragraphs.values()), output.getvalue()


def compact(text):
    # clean_text rejoins hyphenated line wraps and removes soft hyphens.
    return ''.join(c for c in text if not c.isspace() and c not in '-\u00ad')


def chunk_rectangles(tsv, speech_chunks, area):
    """Return screen-coordinate line rectangles for each unchanged audio chunk.

    TSV page dimensions provide the physical-to-logical scale, including HiDPI.
    Unmatched chunks get no highlight rather than a guessed location.
    """
    rows = list(csv.DictReader(io.StringIO(tsv), delimiter='\t', quoting=csv.QUOTE_NONE))
    page = next((r for r in rows if r.get('level') == '1'), None)
    if not page:
        return [[] for _ in speech_chunks]
    try:
        sx, sy = area[2] / int(page['width']), area[3] / int(page['height'])
        words, starts, ends, pieces = [], [], [], []
        offset = 0
        for r in rows:
            if r.get('level') != '5':
                continue
            word = compact(r.get('text') or '')
            if not word:
                continue
            x, y, w, h = (int(r[k]) for k in ('left', 'top', 'width', 'height'))
            words.append(((r['page_num'], r['block_num'], r['par_num'], r['line_num']), x, y, w, h))
            starts.append(offset)
            offset += len(word)
            ends.append(offset)
            pieces.append(word)
        source = ''.join(pieces)
        cursor, result = 0, []
        for chunk in speech_chunks:
            needle = compact(chunk)
            start = source.find(needle, cursor) if needle else -1
            if start < 0:
                result.append([])
                continue
            end = start + len(needle)
            cursor = end
            lines = {}
            for line, x, y, w, h in words[bisect.bisect_right(ends, start):bisect.bisect_left(starts, end)]:
                if line in lines:
                    a, b, c, d = lines[line]
                    lines[line] = min(a, x), min(b, y), max(c, x+w), max(d, y+h)
                else:
                    lines[line] = x, y, x+w, y+h
            result.append([dict(x=area[0]+x*sx, y=area[1]+y*sy,
                                width=(r-x)*sx, height=(b-y)*sy)
                           for x, y, r, b in lines.values()])
        return result
    except (KeyError, ValueError, TypeError, ZeroDivisionError):
        return [[] for _ in speech_chunks]


class HighlightOverlay(QObject):
    """The passage boxes for the COSMIC desktop service, which watches highlight.json and draws them
    over the target window while it has focus. Never awaited by playback."""
    def __init__(self, parent, runtime):
        super().__init__(parent)
        self.path = runtime / 'highlight.json'
        self.last_payload = None
        self.show([])

    def show(self, rectangles, target=''):
        payload = json.dumps(dict(rectangles=rectangles, target=target.removeprefix('0x')))
        if payload == self.last_payload:
            return
        try:
            temp = self.path.with_suffix('.tmp')
            temp.write_text(payload)
            temp.replace(self.path)
        except OSError:
            return  # Highlight failure must never interrupt narration.
        self.last_payload = payload

    def close(self):
        self.show([])
