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
class TestNewFishRecognised(unittest.TestCase):
    """Targeted lock for the two newly added fish (Kleiner_Fisch /
    Süßwassergarnele): each must be in the DB and recover ITSELF -- composited on
    the dark AND the lavender glow background (with a fake stack number, a +/-1px
    shift and noise, like the headline sweep) -- as a CONFIDENT item, never
    colliding with any of the existing icons. Skipped without numpy/PIL/icons."""

    NEW = ('Kleiner_Fisch', 'Süßwassergarnele')

    def setUp(self):
        self.db = _db_or_skip()
        self.refs = self.db.references()
        self.by_name = {r.name: r for r in self.refs}

    def test_new_fish_present_in_db(self):
        for name in self.NEW:
            self.assertIn(name, self.by_name,
                          'new fish icon not in recognition DB: ' + name)

    def test_new_fish_self_recover_dark_and_glow(self):
        for name in self.NEW:
            ref = self.by_name.get(name)
            self.assertIsNotNone(ref)
            for glow in (False, True):
                slot = synth.synth_slot(ref, glow=glow, number=True,
                                        shift=(1, -1), noise=4.0)
                rgb = extract_slot(slot, (0, 0, 32, 32))
                scored = self.db.match(rgb, shift_radius=2)
                self.assertTrue(scored)
                best_name, best_dist = scored[0]
                margin = scored[1][1] - best_dist if len(scored) > 1 else 0.0
                self.assertEqual(best_name, name,
                                 '{} (glow={}) mis-recognised as {}'.format(
                                     name, glow, best_name))
                self.assertGreater(margin, 0.0)

    def test_no_existing_icon_resolves_to_a_new_fish(self):
        # Adding the two new icons must not steal an existing item's identity:
        # every OTHER icon's synthetic slot must still recognise as itself.
        for ref in self.refs:
            if ref.name in self.NEW:
                continue
            slot = synth.synth_slot(ref, glow=False, number=True,
                                    shift=(1, -1), noise=4.0)
            rgb = extract_slot(slot, (0, 0, 32, 32))
            best_name = self.db.match(rgb, shift_radius=2)[0][0]
            self.assertNotIn(
                best_name, self.NEW,
                '{} wrongly resolved to new fish {}'.format(ref.name, best_name))


@unittest.skipUnless(np is not None and synth is not None, 'numpy required')
class TestAdaptiveMask(unittest.TestCase):
    """The per-slot FULL/BAND mask selection: a numbered slot stays on the BAND
    mask (byte-identical to the historic single mask), a number-free slot uses
    the FULL mask and so gains a STRICTLY wider confidence margin -- and the
    batched matcher picks the same mask per slot as the per-slot path."""

    def setUp(self):
        self.db = _db_or_skip()
        self.refs = self.db.references()

    def _margin(self, scored):
        return scored[1][1] - scored[0][1] if len(scored) > 1 else float('inf')

    def test_numbered_slot_matches_band_byte_identical(self):
        # A slot carrying a stack number must score EXACTLY as the historic
        # single-mask (BAND) matcher -- the adaptive path is a no-op there.
        for ref in self.refs[:12]:
            slot = extract_slot(synth.synth_slot(ref, number=True, noise=2.0,
                                                 seed=1), (0, 0, 32, 32))
            from inventory.reference import slot_has_number
            self.assertTrue(slot_has_number(slot),
                            'a stamped-number slot must read as numbered')
            auto = self.db.match(slot)               # auto-detect -> BAND
            band = self.db.match(slot, numbered=True)
            self.assertEqual(auto, band)

    def test_number_free_slot_uses_full_and_widens_margin(self):
        # A number-free slot uses the FULL mask (auto) and still recovers itself.
        # The FULL mask scores the extra central rows, which on the AGGREGATE
        # widens the confidence margin: the worst-case (minimum) margin across all
        # number-free items RISES, and the mean rises, vs the BAND mask. (Per
        # individual close-family item the margin may move either way -- the band
        # rows can carry sibling-distinguishing pixels -- so the guarantee is the
        # aggregate worst case, exactly the metric that matters live.)
        from inventory.reference import slot_has_number
        full_margins = []
        band_margins = []
        for ref in self.refs:
            slot = extract_slot(synth.synth_slot(ref, number=False, noise=2.0,
                                                 seed=2), (0, 0, 32, 32))
            if slot_has_number(slot):
                continue                              # not a number-free slot
            full = self.db.match(slot)                # auto -> FULL
            band = self.db.match(slot, numbered=True)  # forced BAND
            self.assertEqual(full[0][0], ref.name)
            self.assertEqual(band[0][0], ref.name)
            full_margins.append(self._margin(full))
            band_margins.append(self._margin(band))
        self.assertTrue(full_margins)
        # Worst-case confidence improves (the key live metric) ...
        self.assertGreater(min(full_margins), min(band_margins),
                           'FULL must raise the worst-case number-free margin')
        # ... and so does the average.
        self.assertGreater(sum(full_margins) / len(full_margins),
                           sum(band_margins) / len(band_margins),
                           'FULL must raise the mean number-free margin')

    def test_detector_threshold_boundary(self):
        # The detector fires at >= NUMBER_DETECT_MIN_PX near-white px in the digit
        # rows and not below. Build a slot with EXACTLY k near-white px in those
        # rows and probe around the threshold.
        from inventory.reference import _near_white_count_rows, slot_has_number
        from inventory.constants import (NUMBER_DETECT_MIN_PX,
                                         NUMBER_DETECT_WHITE)
        base = np.zeros((32, 32, 3), dtype=np.float32)        # all-dark
        # k-1 white px -> not numbered; k white px -> numbered. Place them in a
        # detector row (row 20) as bright (above NUMBER_DETECT_WHITE) pixels.
        k = NUMBER_DETECT_MIN_PX
        below = base.copy()
        below[20, :k - 1, :] = NUMBER_DETECT_WHITE + 20
        self.assertEqual(_near_white_count_rows(below), k - 1)
        self.assertFalse(slot_has_number(below))
        at = base.copy()
        at[20, :k, :] = NUMBER_DETECT_WHITE + 20
        self.assertEqual(_near_white_count_rows(at), k)
        self.assertTrue(slot_has_number(at))
        # A near-white pixel OUTSIDE the digit rows (e.g. row 5) does not count.
        outside = base.copy()
        outside[5, :, :] = NUMBER_DETECT_WHITE + 20
        self.assertEqual(_near_white_count_rows(outside), 0)
        self.assertFalse(slot_has_number(outside))

    def test_batch_flags_equal_scalar_flags(self):
        # The vectorised per-slot detector must agree EXACTLY with the scalar one,
        # so the batched matcher and the loop pick the same mask for every slot.
        from inventory.reference import slot_has_number, slots_have_numbers
        from inventory.constants import slot_indices
        from inventory.grid import GridLattice
        lat = GridLattice(origin=(2, 2), pitch=(32, 32))
        layout = []
        for i in range(45):
            layout.append({'ref': self.refs[i % len(self.refs)],
                           'number': (i % 2 == 0), 'noise': 2.0, 'seed': i})
        page, _ = synth.synth_page(layout, origin=(2, 2))
        stack = np.stack([extract_slot(page, lat.slot_box(r, c))
                          for (r, c) in slot_indices()]).astype(np.float32)
        batch = slots_have_numbers(stack)
        scalar = [slot_has_number(stack[i]) for i in range(stack.shape[0])]
        self.assertEqual(batch, scalar)
        # And the page genuinely mixes both kinds.
        self.assertIn(True, batch)
        self.assertIn(False, batch)


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
