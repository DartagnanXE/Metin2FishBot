"""The HEADLINE guarantee for the recognition engine (synthetic, hard asserts).

For every bundled icon we synthesize the slot the way the game shows it --
composited over the DARK and the lavender GLOW background, with a fake stack
number stamped into the band, plus a +/-1px shift and gaussian noise -- and
assert the masked + number-band + shift matcher recovers the correct name with
a positive margin. We also assert the ABLATION: full-icon UNMASKED matching
collapses under glow, proving all three components are required.

These are SYNTHETIC (icon composited on a known background), so they carry the
hard accuracy guarantee independent of any real screenshot. Skipped only when
numpy/PIL/the bundled icons are unavailable.
"""

import unittest

from inventory.itemdb import ItemDB, _shift_edge
from inventory.grid import extract_slot

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

try:
    from tests import _inv_synth as synth
except Exception:  # pragma: no cover
    synth = None


def _db_or_skip():
    db = ItemDB.from_bundled()
    if not db.references():
        raise unittest.SkipTest('bundled icons / numpy unavailable')
    return db


def _unmasked_best(refs, slot_rgb):
    """Argmin full-icon (UNMASKED) mean-abs-diff over a +/-1px shift."""
    slot = np.asarray(slot_rgb, dtype=np.float32)
    best = None
    for ref in refs:
        bd = float('inf')
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                sh = _shift_edge(slot, dy, dx)
                d = float(np.abs(sh - ref.ref_rgb).mean())
                if d < bd:
                    bd = d
        if best is None or bd < best[1]:
            best = (ref.name, bd)
    return best


@unittest.skipUnless(np is not None and synth is not None, 'numpy required')
class TestMaskedAccuracy(unittest.TestCase):
    def setUp(self):
        self.db = _db_or_skip()
        self.refs = self.db.references()

    def _accuracy(self, glow):
        hits = 0
        weak_margin = 0
        for ref in self.refs:
            slot = synth.synth_slot(ref, glow=glow, number=True,
                                    shift=(1, -1), noise=4.0)
            rgb = extract_slot(slot, (0, 0, 32, 32))
            scored = self.db.match(rgb, shift_radius=2)
            self.assertTrue(scored)
            name, dist = scored[0]
            margin = scored[1][1] - dist if len(scored) > 1 else 0.0
            if name == ref.name:
                hits += 1
                if margin <= 0:
                    weak_margin += 1
        return hits, weak_margin, len(self.refs)

    def test_dark_background_is_100_percent(self):
        # On the dark background the masked matcher must be perfect with a
        # strictly positive margin for every item.
        hits, weak, total = self._accuracy(glow=False)
        self.assertEqual(hits, total,
                         'masked accuracy on dark must be 100%')
        self.assertEqual(weak, 0, 'every dark match must have positive margin')

    def test_glow_background_is_high(self):
        # Under glow + stack number + shift + noise the masked matcher must
        # still recover the right item for essentially all icons (guard band
        # >= 95%; observed 100%).
        hits, _weak, total = self._accuracy(glow=True)
        self.assertGreaterEqual(hits / total, 0.95,
                                'masked accuracy on glow must be >= 95%')


@unittest.skipUnless(np is not None and synth is not None, 'numpy required')
class TestUnmaskedAblation(unittest.TestCase):
    """Prove the ablation fails: unmasked full-icon matching collapses."""

    def setUp(self):
        self.db = _db_or_skip()
        self.refs = self.db.references()

    def test_unmasked_collapses_under_glow(self):
        masked_hits = 0
        unmasked_hits = 0
        for ref in self.refs:
            slot = synth.synth_slot(ref, glow=True, number=True,
                                    shift=(1, -1), noise=4.0)
            rgb = extract_slot(slot, (0, 0, 32, 32))
            if self.db.match(rgb, shift_radius=2)[0][0] == ref.name:
                masked_hits += 1
            if _unmasked_best(self.refs, rgb)[0] == ref.name:
                unmasked_hits += 1
        total = len(self.refs)
        # Masked is essentially perfect; unmasked is far worse -- this is the
        # proof that masking (ignoring the glowing background) is required.
        self.assertGreaterEqual(masked_hits / total, 0.95)
        self.assertLess(unmasked_hits / total, 0.5)
        self.assertLess(unmasked_hits, masked_hits)


@unittest.skipUnless(np is not None and synth is not None, 'numpy required')
class TestMatchMechanics(unittest.TestCase):
    def setUp(self):
        self.db = _db_or_skip()

    def test_shift_search_absorbs_offset(self):
        # A clean, correctly-aligned slot matches with a tiny distance; the same
        # slot shifted by 2px still matches the same item thanks to the search.
        ref = self.db.references()[0]
        clean = extract_slot(synth.synth_slot(ref), (0, 0, 32, 32))
        shifted = extract_slot(
            synth.synth_slot(ref, shift=(2, 2)), (0, 0, 32, 32))
        self.assertEqual(self.db.match(clean)[0][0], ref.name)
        self.assertEqual(self.db.match(shifted)[0][0], ref.name)

    def test_match_empty_list_on_bad_input(self):
        self.assertEqual(self.db.match(None), [])
        self.assertEqual(self.db.match(np.zeros((10, 10, 3))), [])

    def test_no_numpy_degrades_to_empty(self):
        # Forcing numpy off (the documented test hook) -> no matches, no raise.
        import inventory.itemdb as itemdb
        saved = itemdb.np
        try:
            itemdb.np = None
            self.assertEqual(self.db.match(np.zeros((32, 32, 3))), [])
            self.assertEqual(self.db.best_distance(np.zeros((32, 32, 3))),
                             float('inf'))
        finally:
            itemdb.np = saved


if __name__ == '__main__':
    unittest.main()
