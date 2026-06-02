"""CLI: recognise all 45 inventory slots in one captured page screenshot.

Given a screenshot path (and an OPTIONAL calibration JSON; without one the
engine's bundled :data:`inventory.constants.DEFAULT_CALIBRATION` is used and the
grid is AUTO-ALIGNED to the image), this prints one line per slot --

    [row,col] EMPTY
    [row,col] ITEM <name> dist=.. margin=..
    [row,col] UNKNOWN dist=.. margin=..

-- and writes a labelled overlay PNG next to the screenshot
(``<shot>_overlay.png``) for human review.

This is a thin driver over the headless engine (``inventory`` package): it adds
NO recognition logic of its own. It loads the PNG to the BGR uint8 array a real
capture would yield, builds the bundled :class:`~inventory.itemdb.ItemDB`,
auto-aligns the grid, classifies via :func:`~inventory.scanner.recognize_page`,
and renders via :func:`~inventory.overlay.save_overlay`.

Usage::

    py.exe tools/inv_recognize.py SHOT.png [--calib calib.json]
                                           [--page I|II|III|IV]
                                           [--overlay OUT.png] [--no-overlay]

Exit code 0 on success, 2 on a usage/IO error (e.g. missing numpy/PIL, bad
path). It runs fully headless -- no game / GUI / win32 is touched.
"""

import argparse
import json
import os
import sys

# Allow running as a loose script (``py.exe tools/inv_recognize.py``): make the
# repo root importable so ``import inventory`` works without installation.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:  # numpy/PIL are soft deps of the engine; the CLI needs them to load a PNG.
    import numpy as np
except Exception:  # pragma: no cover - reported cleanly in main()
    np = None

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None

from inventory.itemdb import ItemDB
from inventory import grid as grid_mod
from inventory import scanner, overlay
from inventory.constants import DEFAULT_CALIBRATION
from inventory.types import STATE_EMPTY, STATE_ITEM, STATE_UNKNOWN


def load_bgr(path):
    """Load a PNG as the ``(H, W, 3)`` BGR uint8 image a capture would yield.

    Mirrors the engine's capture convention (``WindowCapture.get_screenshot``
    returns BGR); the engine flips BGR->RGB once internally in ``extract_slot``.
    Raises ``RuntimeError`` with a friendly message on any failure.
    """
    if np is None or Image is None:
        raise RuntimeError('numpy and Pillow are required to load the image')
    if not os.path.isfile(path):
        raise RuntimeError('screenshot not found: {}'.format(path))
    try:
        rgb = np.asarray(Image.open(path).convert('RGB'), dtype=np.uint8)
    except Exception as exc:
        raise RuntimeError('could not read image {}: {}'.format(path, exc))
    return np.ascontiguousarray(rgb[:, :, ::-1])


def load_calibration(path):
    """Load a calibration JSON, or return the built-in default when ``path`` is
    falsy. Raises ``RuntimeError`` on a missing / malformed file."""
    if not path:
        return DEFAULT_CALIBRATION
    if not os.path.isfile(path):
        raise RuntimeError('calibration not found: {}'.format(path))
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except Exception as exc:
        raise RuntimeError('bad calibration JSON {}: {}'.format(path, exc))
    if not isinstance(data, dict):
        raise RuntimeError('calibration JSON must be an object')
    return data


def default_overlay_path(shot_path):
    """``<shot>_overlay.png`` next to the screenshot (preserves the directory)."""
    base, _ext = os.path.splitext(os.path.abspath(shot_path))
    return base + '_overlay.png'


def format_result(result):
    """One human line for a :class:`~inventory.types.SlotResult`.

    EMPTY / ITEM <name> dist=.. margin=.. / UNKNOWN dist=.. margin=.. -- prefixed
    with the slot's ``[row,col]`` so the row-major order is unambiguous.
    """
    prefix = '[{},{}]'.format(result.row, result.col)
    if result.state == STATE_EMPTY:
        return '{} EMPTY'.format(prefix)
    if result.state == STATE_ITEM:
        return '{} ITEM {} dist={:.2f} margin={:.2f}'.format(
            prefix, result.name, result.distance, result.margin)
    # UNKNOWN: occupied but no confident match (distance may be inf w/o a DB).
    dist = result.distance
    dist_s = 'inf' if dist == float('inf') else '{:.2f}'.format(dist)
    return '{} UNKNOWN dist={} margin={:.2f}'.format(
        prefix, dist_s, result.margin)


def recognize(shot_path, calib_path=None, page=None, overlay_path=None,
              write_overlay=True, out=sys.stdout):
    """Run the full pipeline on one screenshot; print 45 lines; write overlay.

    Returns ``(results, overlay_written_path_or_None)``. Auto-aligns the grid to
    THIS image (the documented per-session drift recovery) using the supplied or
    default calibration. Raises ``RuntimeError`` for IO / dependency problems so
    :func:`main` can map it to exit code 2.
    """
    image_bgr = load_bgr(shot_path)
    calib = load_calibration(calib_path)

    db = ItemDB.from_bundled()
    if not db.references():
        # No DB -> every slot will read UNKNOWN. Warn but still run + emit lines.
        print('warning: item DB is empty (numpy/PIL or icons missing); '
              'all slots will be UNKNOWN', file=sys.stderr)

    # AUTO-ALIGN the grid for this exact image (origin jitter search).
    lattice = grid_mod.auto_align(image_bgr, db, calib)
    if page is None:
        page = grid_mod.active_page(image_bgr, calib)

    results = scanner.recognize_page(image_bgr, db, calib,
                                     lattice=lattice, page=page)

    counts = {STATE_EMPTY: 0, STATE_ITEM: 0, STATE_UNKNOWN: 0}
    print('screenshot : {}'.format(os.path.abspath(shot_path)), file=out)
    print('calibration: {}'.format(calib_path or '(built-in default)'),
          file=out)
    print('active page: {}'.format(page), file=out)
    print('grid lock  : origin={} pitch={}'.format(
        lattice.origin, lattice.pitch), file=out)
    print('slots      : {} (row-major)'.format(len(results)), file=out)
    print('-' * 56, file=out)
    for r in results:
        counts[r.state] = counts.get(r.state, 0) + 1
        print(format_result(r), file=out)
    print('-' * 56, file=out)
    print('summary    : ITEM={} EMPTY={} UNKNOWN={} (of {})'.format(
        counts[STATE_ITEM], counts[STATE_EMPTY], counts[STATE_UNKNOWN],
        len(results)), file=out)

    written = None
    if write_overlay:
        overlay_path = overlay_path or default_overlay_path(shot_path)
        if overlay.save_overlay(overlay_path, image_bgr, results, lattice):
            written = overlay_path
            print('overlay    : {}'.format(written), file=out)
        else:
            print('overlay    : FAILED (cv2/PIL missing or path unwritable)',
                  file=sys.stderr)
    return results, written


def build_parser():
    p = argparse.ArgumentParser(
        prog='inv_recognize',
        description='Recognise all 45 Metin2 inventory slots in a screenshot '
                    '(headless; auto-aligns the grid).')
    p.add_argument('screenshot', help='path to the inventory page PNG')
    p.add_argument('--calib', '--calibration', dest='calib', default=None,
                   help='optional calibration JSON (default: built-in + '
                        'auto-align)')
    p.add_argument('--page', dest='page', default=None,
                   choices=['I', 'II', 'III', 'IV'],
                   help='page label to tag results with (default: detect from '
                        'the active tab)')
    p.add_argument('--overlay', dest='overlay', default=None,
                   help='overlay PNG output path (default: <shot>_overlay.png)')
    p.add_argument('--no-overlay', dest='no_overlay', action='store_true',
                   help='do not write the labelled overlay PNG')
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        recognize(args.screenshot, calib_path=args.calib, page=args.page,
                  overlay_path=args.overlay,
                  write_overlay=not args.no_overlay)
    except RuntimeError as exc:
        print('error: {}'.format(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
