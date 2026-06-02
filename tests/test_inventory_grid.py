"""Tests for grid geometry, slot extraction (BGR->RGB), auto-alignment, and
active-page detection.

auto_align is exercised on a SYNTHETIC page (icons composited so they truly
match the DB) with an injected +5px origin drift -- the documented real
failure -- and must re-lock the true origin. Skipped without numpy/PIL/icons.
"""

import unittest

from inventory import grid as G
from inventory import scanner
from inventory.grid import GridLattice, lattice_from_calibration
from inventory.constants import (EMPTY_REF, GLOW_REF, DEFAULT_CALIBRATION,
                                 COLS, ROWS)
from inventory.itemdb import ItemDB
from inventory.types import STATE_ITEM

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

try:
    from tests import _inv_synth as synth
except Exception:  # pragma: no cover
    synth = None


class TestGridLatticePure(unittest.TestCase):
    """slot_box / calibration geometry need no numpy."""

    def test_slot_box_origin_and_pitch(self):
        lat = GridLattice(origin=(10, 20), pitch=(32, 33))
        self.assertEqual(lat.slot_box(0, 0), (10, 20, 32, 32))
        self.assertEqual(lat.slot_box(0, 1), (42, 20, 32, 32))   # +pitch_x
        self.assertEqual(lat.slot_box(1, 0), (10, 53, 32, 32))   # +pitch_y
        self.assertEqual(lat.slot_box(2, 3), (10 + 3 * 32, 20 + 2 * 33, 32, 32))

    def test_lattice_from_calibration_default(self):
        lat = lattice_from_calibration(DEFAULT_CALIBRATION)
        self.assertEqual(lat.origin, (633, 275))   # grid.tl (empirical centre)
        # span 761-633=128 over 4 gaps -> pitch 32; 531-275=256 over 8 -> 32.
        self.assertEqual(lat.pitch, (32, 32))

    def test_lattice_from_calibration_degenerate(self):
        calib = {'grid': {'tl': [0, 0], 'br': [0, 0], 'cols': 5, 'rows': 9}}
        lat = lattice_from_calibration(calib)
        self.assertEqual(lat.pitch, (32, 32))      # falls back to SLOT_PX


@unittest.skipUnless(np is not None, 'numpy required')
class TestExtractSlot(unittest.TestCase):
    def test_bgr_to_rgb_conversion(self):
        # A pure-blue BGR pixel (B=255) must come out RGB blue (channel 2 hot).
        img = np.zeros((40, 40, 3), dtype=np.uint8)
        img[:, :, 0] = 255          # BGR blue
        slot = G.extract_slot(img, (4, 4, 32, 32))
        self.assertEqual(slot.shape, (32, 32, 3))
        self.assertTrue(np.allclose(slot[:, :, 0], 0))      # R
        self.assertTrue(np.allclose(slot[:, :, 2], 255))    # B -> RGB[2]

    def test_out_of_frame_box_is_padded_full_size(self):
        img = np.full((20, 20, 3), 100, dtype=np.uint8)
        slot = G.extract_slot(img, (10, 10, 32, 32))        # runs off image
        self.assertEqual(slot.shape, (32, 32, 3))           # still full 32x32

    def test_none_image_returns_none(self):
        self.assertIsNone(G.extract_slot(None, (0, 0, 32, 32)))


@unittest.skipUnless(np is not None, 'numpy required')
class TestUpperRegionEmpty(unittest.TestCase):
    def test_dark_slot_is_empty(self):
        slot = np.tile(np.array(EMPTY_REF, dtype=np.float32), (32, 32, 1))
        self.assertTrue(G.upper_region_is_empty(slot, tol=18))

    def test_bright_slot_is_not_empty(self):
        slot = np.full((32, 32, 3), 180.0, dtype=np.float32)
        self.assertFalse(G.upper_region_is_empty(slot, tol=18))

    def test_glow_slot_upper_region_not_empty_ref(self):
        # A uniformly glowing slot is NOT ~empty_ref (it is lavender), so the
        # cheap probe returns False; the classifier then uses match distance.
        slot = np.tile(np.array(GLOW_REF, dtype=np.float32), (32, 32, 1))
        self.assertFalse(G.upper_region_is_empty(slot, tol=18))


@unittest.skipUnless(np is not None, 'numpy required')
class TestActivePage(unittest.TestCase):
    def _calib(self):
        return {
            'tabs': {'I': [10, 10], 'II': [20, 10], 'III': [30, 10],
                     'IV': [40, 10]},
            'tab_active': {'offset': [0, 0]},
        }

    def test_brightest_tab_is_active(self):
        img = np.zeros((40, 60, 3), dtype=np.uint8)
        # Make tab III the brightest sample point.
        img[10, 30, :] = 250
        self.assertEqual(G.active_page(img, self._calib()), 'III')

    def test_none_image_returns_first_page(self):
        self.assertEqual(G.active_page(None, self._calib()), 'I')

    def test_window_mean_robust_to_single_pixel_highlight(self):
        # The active tab is a BROAD modest-bright patch (a real open-tab fill);
        # an inactive tab has a single SPIKE pixel (text/border highlight). A
        # 1-pixel sampler could be fooled by the spike, but the 3x3 window mean
        # must still pick the broadly-bright (truly open) tab.
        img = np.zeros((40, 60, 3), dtype=np.uint8)
        # Tab II (sample 20,10): fill the whole 3x3 window at a modest 120.
        img[9:12, 19:22, :] = 120
        # Tab IV (sample 40,10): one bright spike at 255, rest dark.
        img[10, 40, :] = 255
        # Single-pixel means: IV=255 > II=120 would pick IV (wrong). Window
        # means: II=120 vs IV=255/9~=28 -> II wins (correct, broadly bright).
        self.assertEqual(G.active_page(img, self._calib()), 'II')


@unittest.skipUnless(np is not None and synth is not None, 'numpy required')
class TestAutoAlign(unittest.TestCase):
    def setUp(self):
        self.db = ItemDB.from_bundled()
        if not self.db.references():
            self.skipTest('bundled icons / numpy unavailable')

    def test_recovers_injected_5px_drift(self):
        refs = self.db.references()
        layout = [None] * 45
        layout[0] = {'ref': refs[5], 'number': True}
        layout[3] = {'ref': refs[10]}
        layout[12] = {'ref': refs[20], 'glow': True}
        layout[26] = {'ref': refs[1]}
        layout[44] = {'ref': refs[2]}
        true_origin = (7, 7)
        page, _ = synth.synth_page(layout, origin=true_origin,
                                   pitch=(32, 32), canvas_pad=8)
        # Calibration guess is +5px off in BOTH axes (the documented failure).
        ox, oy = true_origin[0] + 5, true_origin[1] + 5
        calib = {'grid': {'tl': [ox, oy], 'br': [ox + 4 * 32, oy + 8 * 32],
                          'cols': 5, 'rows': 9}, 'tolerance': 18}
        lat = G.auto_align(page, self.db, calib, radius=6)
        self.assertEqual(lat.origin, true_origin)

    def test_no_numpy_returns_calibration_lattice(self):
        saved = G.np
        try:
            G.np = None
            lat = G.auto_align(object(), self.db, DEFAULT_CALIBRATION)
            self.assertEqual(lat.origin, (633, 275))
        finally:
            G.np = saved

    def test_sparse_non_glow_page_with_drift_recovers_and_recognizes(self):
        # REGRESSION GUARD for the CRITICAL sparse-page auto-align bug: a
        # partly-empty NON-glow inventory (the most common real case -- opening
        # the bag with no fresh catch) used to make the old fit slide the grid
        # until the few items fell into the dark inter-slot gaps and "won" with
        # ZERO occupied cells, so recognize_page returned 0 items. The
        # count-maximising objective must instead recover the true origin AND
        # classify every planted item. canvas_pad >= radius so the drifted
        # lattice stays on-canvas (the small pad in other tests masked the bug).
        refs = self.db.references()
        layout = [None] * (COLS * ROWS)
        planted = [0, 1, 2, 5, 6, 11, 13, 20, 26]   # 9 scattered occupied slots
        for n, i in enumerate(planted):
            layout[i] = {'ref': refs[(n * 3) % len(refs)],
                         'number': (n % 2 == 0)}
        true_origin = (20, 20)
        page, _ = synth.synth_page(layout, origin=true_origin,
                                   pitch=(32, 32), canvas_pad=32)
        # +3px session drift in both axes from the calibration guess.
        ox, oy = true_origin[0] + 3, true_origin[1] + 3
        calib = {'grid': {'tl': [ox, oy], 'br': [ox + (COLS - 1) * 32,
                                                 oy + (ROWS - 1) * 32],
                          'cols': COLS, 'rows': ROWS}, 'tolerance': 18}

        locked = G.auto_align(page, self.db, calib)
        self.assertEqual(locked.origin, true_origin,
                         'sparse-page auto-align must recover the true origin '
                         '(got {})'.format(locked.origin))

        results = scanner.recognize_page(page, self.db, calib,
                                         lattice=locked, page='I')
        items = [r for r in results if r.state == STATE_ITEM]
        self.assertEqual(len(items), len(planted),
                         'recognize_page must find all {} planted items '
                         '(got {}; the bug produced 0)'.format(
                             len(planted), len(items)))
        # Every recognised item must carry the correct planted name at its cell.
        for r in items:
            spec = layout[r.row * COLS + r.col]
            self.assertIsNotNone(spec, 'item reported in a planted-empty cell')
            self.assertEqual(r.name, spec['ref'].name,
                             'wrong name at ({},{})'.format(r.row, r.col))


if __name__ == '__main__':
    unittest.main()
