"""Guarded real-screenshot validation of the full recognition pipeline.

Skips unless numpy/PIL AND the real screenshots are present. Runs auto-align +
recognize_page on FischOhneLeuchten.png (no glow) and FischLeuchten.png (heavy
glow), REPORTS the confident-recognition count / 45 and the distance & margin
distribution, and writes a labelled overlay PNG for human review.

IMPORTANT: the bundled icon art is NOT guaranteed to be the exact in-game
rendering for these particular screenshots, and there are NO ground-truth
labels -- so the HARD accuracy guarantee lives in the synthetic matcher test
(test_inventory_matcher.py). Here the assertions are deliberately LOOSE: the
pipeline must run end-to-end and return 45 results per page without raising,
and the overlay must be emitted. Recognition counts are printed, not asserted.
"""

import os
import unittest

from inventory.itemdb import ItemDB
from inventory import grid as grid_mod
from inventory import scanner, overlay
from inventory.constants import DEFAULT_CALIBRATION, SLOTS_PER_PAGE

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None


# The screenshots live next to the repo root (download folder).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SHOTS = {
    'no_glow': os.path.join(_REPO_ROOT, '..', 'FischOhneLeuchten.png'),
    'glow': os.path.join(_REPO_ROOT, '..', 'FischLeuchten.png'),
}
_OVERLAY_DIR = os.path.join(_REPO_ROOT, 'build')


def _shots_present():
    return all(os.path.isfile(p) for p in _SHOTS.values())


def _load_bgr(path):
    """Load a PNG as the BGR uint8 image a capture would yield."""
    rgb = np.asarray(Image.open(path).convert('RGB'), dtype=np.uint8)
    return np.ascontiguousarray(rgb[:, :, ::-1])


def _any_item_on_glow(image_bgr, items, lattice, glow_frac=0.15):
    """True iff at least one recognised item's slot is GLOWING.

    A glowing slot has its background recoloured toward the lavender
    ``GLOW_REF`` (176,177,203). We extract each recognised item's slot (RGB)
    and check the fraction of pixels near that lavender; >= ``glow_frac`` of the
    slot being lavender means the icon is drawn over a glowing background, so a
    correct match there proves masked matching is glow-proof on real pixels.
    """
    from inventory.grid import extract_slot
    from inventory.constants import GLOW_REF
    glow = np.array(GLOW_REF, dtype=np.float32)
    for r in items:
        slot = extract_slot(image_bgr, lattice.slot_box(r.row, r.col))
        if slot is None:
            continue
        near = (np.abs(np.asarray(slot, dtype=np.float32) - glow).mean(axis=2)
                < 40.0)
        if float(near.mean()) >= glow_frac:
            return True
    return False


@unittest.skipUnless(np is not None and Image is not None and _shots_present(),
                     'numpy/PIL/screenshots required')
class TestRealScreenshotPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = ItemDB.from_bundled()
        if not cls.db.references():
            raise unittest.SkipTest('bundled icons unavailable')

    def _run_shot(self, key):
        img = _load_bgr(_SHOTS[key])
        lattice = grid_mod.auto_align(img, self.db, DEFAULT_CALIBRATION)
        page = grid_mod.active_page(img, DEFAULT_CALIBRATION)
        results = scanner.recognize_page(img, self.db, DEFAULT_CALIBRATION,
                                         lattice=lattice, page=page)

        items = [r for r in results if r.state == 'item']
        empties = [r for r in results if r.state == 'empty']
        unknowns = [r for r in results if r.state == 'unknown']
        dists = sorted(r.distance for r in items)
        margins = sorted(r.margin for r in items)

        def stat(seq):
            if not seq:
                return 'n/a'
            return 'min={:.1f} med={:.1f} max={:.1f}'.format(
                seq[0], seq[len(seq) // 2], seq[-1])

        print('\n[{}] active_page={} origin={} pitch={}'.format(
            key, page, lattice.origin, lattice.pitch))
        print('  items={} empty={} unknown={} (of {})'.format(
            len(items), len(empties), len(unknowns), len(results)))
        print('  item distance: {}'.format(stat(dists)))
        print('  item margin:   {}'.format(stat(margins)))

        # Emit a labelled overlay PNG for human review (best-effort).
        os.makedirs(_OVERLAY_DIR, exist_ok=True)
        out = os.path.join(_OVERLAY_DIR, 'inventory_overlay_{}.png'.format(key))
        saved = overlay.save_overlay(out, img, results, lattice)
        print('  overlay -> {} (saved={})'.format(out, saved))

        # Structural assertions: the pipeline ran end-to-end and is well-formed.
        self.assertEqual(len(results), SLOTS_PER_PAGE)
        self.assertTrue(all(r.state in ('item', 'empty', 'unknown')
                            for r in results))
        self.assertTrue(saved, 'overlay PNG should be written')
        return results, lattice

    def test_no_glow_shot_runs(self):
        results, _lat = self._run_shot('no_glow')
        items = [r for r in results if r.state == 'item']
        # REGRESSION GUARD (the documented half-pitch auto-align failure): a
        # bad grid lock recognised ZERO of 45 here. With the calibration centred
        # on the empirical origin + the 10px alias-safe search, this shot locks
        # and recognises ~26 items at distance ~1. Floor at 12 (well under 26)
        # so a future drift/lock regression that collapses recognition is caught
        # while leaving generous slack for icon-art / screenshot variation.
        self.assertGreaterEqual(
            len(items), 12,
            'no-glow auto-align+recognition regressed (got {} items; the '
            'half-pitch grid-lock bug produced 0)'.format(len(items)))
        # Confident matches really are confident on real pixels.
        confident = [r for r in items if r.distance <= 6.0]
        self.assertGreaterEqual(
            len(confident), 12,
            'no-glow confident (<=6) matches regressed (got {})'.format(
                len(confident)))

    def test_glow_shot_runs(self):
        results, lattice = self._run_shot('glow')
        items = [r for r in results if r.state == 'item']
        # Glow robustness on REAL pixels: at least a handful of items must still
        # recognise despite the heavy lavender background glow.
        self.assertGreaterEqual(
            len(items), 6,
            'glow recognition regressed (got {} items)'.format(len(items)))
        # And at least one recognised item must sit on a genuinely GLOWING
        # background -- the proof that masked matching is glow-proof, not just
        # that the non-glowing slots happened to match.
        self.assertTrue(
            _any_item_on_glow(_load_bgr(_SHOTS['glow']), items, lattice),
            'expected >=1 recognised item on a glowing (lavender) background')


if __name__ == '__main__':
    unittest.main()
