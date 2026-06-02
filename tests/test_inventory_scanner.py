"""Tests for the scanner orchestration.

recognize_page classifies a synthetic 45-slot page (mixing empty / known /
unknown + glow + stack numbers); the same unknown item yields a stable
signature across two scans; scan_inventory drives I->IV via fake capture/switch
callbacks and assembles a 4-page InventoryMap. Skipped without numpy/PIL/icons.
"""

import unittest

from inventory import scanner
from inventory.itemdb import ItemDB
from inventory.types import (InventoryMap, SlotResult, STATE_EMPTY,
                             STATE_ITEM, STATE_UNKNOWN)
from inventory.grid import GridLattice

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

try:
    from tests import _inv_synth as synth
except Exception:  # pragma: no cover
    synth = None


def _aligned_lattice(origin=(2, 2), pitch=(32, 32)):
    return GridLattice(origin=origin, pitch=pitch)


@unittest.skipUnless(np is not None and synth is not None, 'numpy required')
class TestRecognizePage(unittest.TestCase):
    def setUp(self):
        self.db = ItemDB.from_bundled()
        if not self.db.references():
            self.skipTest('bundled icons / numpy unavailable')
        self.refs = self.db.references()

    def test_mixed_page_states(self):
        # Slot 0 = known item with stack number; slot 1 = empty; slot 2 = known
        # item on a GLOW background; slot 3 = unknown (random noise block).
        layout = [None] * 45
        layout[0] = {'ref': self.refs[0], 'number': True}
        layout[2] = {'ref': self.refs[7], 'glow': True}
        # an "unknown" item: a bright synthetic blob not in the DB
        layout[3] = {'ref': self.refs[1]}      # placeholder, overwritten below
        page, (origin, pitch) = synth.synth_page(layout, origin=(2, 2),
                                                 pitch=(32, 32), canvas_pad=6)
        # Overwrite slot 3 with an off-distribution magenta blob (unknown).
        x = origin[0] + 3 * pitch[0]
        y = origin[1] + 0 * pitch[1]
        page[y + 4:y + 28, x + 4:x + 28, :] = np.array([200, 0, 200],
                                                       dtype=np.uint8)

        lat = _aligned_lattice(origin, pitch)
        results = scanner.recognize_page(page, self.db, lattice=lat, page='I')
        self.assertEqual(len(results), 45)
        by_idx = {(r.row, r.col): r for r in results}

        self.assertEqual(by_idx[(0, 0)].state, STATE_ITEM)
        self.assertEqual(by_idx[(0, 0)].name, self.refs[0].name)
        self.assertEqual(by_idx[(0, 1)].state, STATE_EMPTY)
        self.assertEqual(by_idx[(0, 2)].state, STATE_ITEM)
        self.assertEqual(by_idx[(0, 2)].name, self.refs[7].name)
        self.assertEqual(by_idx[(0, 3)].state, STATE_UNKNOWN)
        self.assertIsNotNone(by_idx[(0, 3)].signature)

    def test_glow_but_empty_slot_is_empty_not_unknown(self):
        # A glowing-but-EMPTY slot (uniform lavender, no item on top) must
        # classify as EMPTY via the glow-aware fallback -- not UNKNOWN with a
        # churning signature. The cheap upper-region probe returns False for it
        # (lavender != EMPTY_REF), so the fallback relies on near-uniformity +
        # no confident match. A real item on a glow background is unaffected
        # (its silhouette has high contrast), as the mixed-page test confirms.
        from inventory.grid import extract_slot
        glow_empty = synth.empty_slot(glow=True)
        rgb = extract_slot(glow_empty, (0, 0, 32, 32))
        res = scanner.classify_slot(rgb, self.db, row=0, col=0)
        self.assertEqual(res.state, STATE_EMPTY)
        self.assertIsNone(res.signature)

    def test_item_under_stack_number_still_recognized(self):
        # The bait/Worm-style case: an item carrying a stack number must still
        # be recognized (number band is excluded from the match).
        ref = self.refs[0]
        layout = [None] * 45
        layout[0] = {'ref': ref, 'number': True, 'noise': 3.0}
        page, (origin, pitch) = synth.synth_page(layout, origin=(2, 2))
        lat = _aligned_lattice(origin, pitch)
        results = scanner.recognize_page(page, self.db, lattice=lat, page='I')
        first = results[0]
        self.assertEqual(first.state, STATE_ITEM)
        self.assertEqual(first.name, ref.name)


@unittest.skipUnless(np is not None and synth is not None, 'numpy required')
class TestSignatureStability(unittest.TestCase):
    def setUp(self):
        self.db = ItemDB.from_bundled()
        if not self.db.references():
            self.skipTest('bundled icons / numpy unavailable')

    def test_same_unknown_same_signature_across_scans(self):
        # Build two independent "captures" of the SAME unknown item (a fixed
        # magenta blob) and confirm the signatures match -> trackable.
        def unknown_page():
            page = np.tile(np.array([3, 7, 5], dtype=np.uint8), (40, 40, 1))
            page[6:26, 6:26, :] = np.array([180, 20, 160], dtype=np.uint8)
            return page.copy()

        lat = _aligned_lattice(origin=(2, 2))
        r1 = scanner.recognize_page(unknown_page(), self.db, lattice=lat)[0]
        r2 = scanner.recognize_page(unknown_page(), self.db, lattice=lat)[0]
        self.assertEqual(r1.state, STATE_UNKNOWN)
        self.assertEqual(r2.state, STATE_UNKNOWN)
        self.assertIsNotNone(r1.signature)
        self.assertEqual(r1.signature, r2.signature)


@unittest.skipUnless(np is not None and synth is not None, 'numpy required')
class TestScanInventory(unittest.TestCase):
    def setUp(self):
        self.db = ItemDB.from_bundled()
        if not self.db.references():
            self.skipTest('bundled icons / numpy unavailable')

    def test_drives_all_pages_via_callbacks(self):
        refs = self.db.references()
        # One known item per page so each page is distinguishable.
        pages_layout = {}
        for i, label in enumerate(('I', 'II', 'III', 'IV')):
            layout = [None] * 45
            layout[0] = {'ref': refs[i]}
            page, _ = synth.synth_page(layout, origin=(2, 2))
            pages_layout[label] = page

        switched = []

        def switch_page_fn(page):
            switched.append(page)

        def capture_fn():
            # Return the page for the most recently switched-to tab.
            return pages_layout[switched[-1]]

        inv = scanner.scan_inventory(capture_fn, switch_page_fn, self.db)
        self.assertIsInstance(inv, InventoryMap)
        self.assertEqual(switched, ['I', 'II', 'III', 'IV'])
        self.assertEqual(set(inv.pages), {'I', 'II', 'III', 'IV'})
        for label in ('I', 'II', 'III', 'IV'):
            self.assertEqual(len(inv.pages[label]), 45)

    def test_bad_capture_skips_page_without_raising(self):
        def switch_page_fn(_page):
            pass

        def capture_fn():
            return None      # capture failure for every page

        inv = scanner.scan_inventory(capture_fn, switch_page_fn, self.db)
        self.assertEqual(inv.pages, {})     # all skipped, no raise


class TestInventoryMapHelpers(unittest.TestCase):
    """InventoryMap query helpers are pure Python (no numpy)."""

    def _slot(self, state, name, page, idx):
        return SlotResult(state=state, name=name, distance=0.0, margin=0.0,
                          signature=None, page=page, row=idx, col=0)

    def test_items_find_count_unknowns(self):
        page_i = (self._slot(STATE_ITEM, 'Worm', 'I', 0),
                  self._slot(STATE_ITEM, 'Carp', 'I', 1),
                  self._slot(STATE_EMPTY, None, 'I', 2))
        page_ii = (self._slot(STATE_ITEM, 'Worm', 'II', 0),
                   self._slot(STATE_UNKNOWN, None, 'II', 1))
        inv = InventoryMap(pages={'I': page_i, 'II': page_ii})
        self.assertEqual(len(inv.items()), 3)
        self.assertEqual(inv.count('Worm'), 2)
        self.assertEqual(len(inv.find('Carp')), 1)
        self.assertEqual(len(inv.unknowns()), 1)


if __name__ == '__main__':
    unittest.main()
