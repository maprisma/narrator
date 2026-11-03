"""Find the page that is being read in a PDF viewer screenshot.

A PDF page is a bright area; viewer chrome (toolbar, sidebar background) and the gaps
between pages in continuous view are darker. The detector works on a downscaled
grayscale copy: the widest band of mostly bright columns is the page column (the
thumbnail sidebar is narrower and separated by a dark gutter), and inside that band the
topmost page piece that covers enough of the window is the page being read. Returns
None when no clear page is found (dark-mode viewers, slides without a border), so the
caller can fall back to the whole window.
"""

PDF_VIEWERS = {
    # window class (lower case): next-page key for hl.dsp.send_shortcut, scroll key
    "org.gnome.evince": ("n", "Next"),
    "evince": ("n", "Next"),
    "org.gnome.papers": ("n", "Next"),
    "papers": ("n", "Next"),
}
BRIGHT = 200          # gray level of a page background
COLUMN_SHARE = 0.20   # share of bright pixels that makes a column/row part of a page
MIN_PIECE = 0.15      # a page piece must cover this share of the window height
MIN_WIDTH = 0.25      # the page column must cover this share of the window width


def viewer_keys(window_class, title):
    """(next-page key, scroll key) for a known PDF viewer window, else None."""
    keys = PDF_VIEWERS.get((window_class or "").lower())
    if keys:
        return keys
    return None


def _runs(flags, min_gap=1):
    """Contiguous True runs as (start, end) with end exclusive; gaps shorter than min_gap are bridged."""
    runs, start, gap = [], None, 0
    for i, flag in enumerate(flags):
        if flag:
            if start is None:
                start = i
            gap = 0
        elif start is not None:
            gap += 1
            if gap >= min_gap:
                runs.append((start, i - gap + 1))
                start, gap = None, 0
    if start is not None:
        runs.append((start, len(flags) - gap))
    return runs


def find_page(gray):
    """gray: 2-D numpy array (rows, columns) of 0-255 values.

    Returns (x, y, width, height, cut_off) in the array's coordinates, where cut_off
    means the page continues below the visible area; or None."""
    import numpy as np
    rows, cols = gray.shape
    if rows < 40 or cols < 40:
        return None
    bright = gray >= BRIGHT
    column_share = bright.mean(axis=0)
    column_runs = [r for r in _runs(column_share >= COLUMN_SHARE, min_gap=3) if r[1] - r[0] >= MIN_WIDTH * cols]
    if not column_runs:
        return None
    left, right = max(column_runs, key=lambda r: r[1] - r[0])
    row_share = bright[:, left:right].mean(axis=1)
    pieces = _runs(row_share >= COLUMN_SHARE, min_gap=3)
    pieces = [p for p in pieces if p[1] - p[0] >= MIN_PIECE * rows] or (
        [max(pieces, key=lambda p: p[1] - p[0])] if pieces else [])
    if not pieces:
        return None
    top, bottom = pieces[0]
    # A page reaching the window's right or left edge is not a framed page (e.g. a web view).
    if left == 0 and right == cols:
        return None
    cut_off = bottom >= rows - 2
    return left, top, right - left, bottom - top, bool(cut_off)


def find_page_in_image(path, step=4):
    """find_page on an image file, downscaled by `step`; returns full-size pixel coordinates."""
    import numpy as np
    from PySide6.QtGui import QImage
    image = QImage(str(path))
    if image.isNull():
        return None
    image = image.convertToFormat(QImage.Format.Format_Grayscale8)
    width, height, stride = image.width(), image.height(), image.bytesPerLine()
    data = np.frombuffer(image.constBits(), dtype=np.uint8, count=stride * height).reshape(height, stride)[:, :width]
    found = find_page(data[::step, ::step])
    if not found:
        return None
    x, y, w, h, cut_off = found
    # Back to full size, clamped to the image.
    x, y = x * step, y * step
    w, h = min(w * step, width - x), min(h * step, height - y)
    return x, y, w, h, cut_off
