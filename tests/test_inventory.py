"""End-to-end QA guarantee for the inventory recognition engine (headless).

This is the consolidated acceptance suite the QA tooling drives. Every test is
SYNTHETIC -- each slot is the bundled icon (the DB built from ``KeyItems/`` +
``FangBilder/``) composited the way the game renders it -- so the asserts are
hard and independent of any real screenshot:

* :class:`TestSyntheticAccuracy` -- composite EVERY DB item on the DARK and on
  the lavender GLOW background ``[176, 177, 203]``, stamp a white stack-number
  block in rows 14..24, apply a +/-1px shift and small gaussian noise, and
  assert the masked + number-band + shift matcher recognises >= 95% (target
  100%) on BOTH backgrounds.
* :class:`TestAutoGridAlignment` -- synthesize a full 45-slot page, shift the
  grid origin by a few px, and assert :func:`auto_align` re-locks onto it (and
  that recognition through the re-locked lattice is accurate).
* :class:`TestGlowRegression` -- the ablation: full-icon UNMASKED matching must
  FAIL under glow while the engine's MASKED matcher PASSES (proves masking the
  glowing background is required).
* :class:`TestNumberBandRegression` -- including the white stack-number band in
  the comparison must FAIL it while the engine's number-band-zeroed mask
  PASSES (proves zeroing rows 14..24 is required).

Runs fully headless (no game / GUI / win32). Skips cleanly only when numpy/PIL
or the bundled icons are unavailable. Kept fast: the heavy per-icon sweeps build
the DB once per class and reuse it.
"""

import unittest

from inventory.itemdb import ItemDB, _shift_edge
from inventory import grid as grid_mod
from inventory.grid import extract_slot, auto_align, lattice_from_calibration
from inventory.constants import (
    SLOT_PX,
    COLS,
    ROWS,
    SLOTS_PER_PAGE,
    MATCH_THRESHOLD,
    NUMBER_BAND_ROWS,
    DEFAULT_CALIBRATION,
)
from inventory import scanner
from inventory.types import STATE_ITEM, STATE_EMPTY

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

try:
    from tests import _inv_synth as synth
except Exception:  # pragma: no cover
    synth = None


# The accuracy guard band: the spec target is 100%; we hard-require >= 95% on
# both backgrounds so a single pathological icon cannot silently rot the engine.
_ACCURACY_FLOOR = 0.95

# The full hostile slot the game actually shows: glow/dark background + a stack
# number + a +/-1px session shift + sensor noise. Used by the accuracy sweep.
_HOSTILE = dict(number=True, shift=(1, -1), noise=4.0)


def _db_or_skip():
    """Bundled DB (KeyItems + FangBilder) or a SkipTest in a lean environment."""
    db = ItemDB.from_bundled()
    if not db.references():
        raise unittest.SkipTest('bundled icons / numpy unavailable')
    return db


def _unmasked_best(refs, slot_rgb, radius=1):
    """Argmin FULL-icon (UNMASKED) mean-abs-diff over a +/-radius px shift.

    The ablation baseline: it compares the whole 32x32 composite (background
    included), so a recoloured glow background swamps the small silhouette and
    the match collapses -- which is exactly what the regression asserts.
    """
    slot = np.asarray(slot_rgb, dtype=np.float32)
    best = None
    for ref in refs:
        bd = float('inf')
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                sh = _shift_edge(slot, dy, dx)
                d = float(np.abs(sh - ref.ref_rgb).mean())
                if d < bd:
                    bd = d
        if best is None or bd < best[1]:
            best = (ref.name, bd)
    return best


def _number_band_included_best(refs, slot_rgb, radius=2):
    """Argmin masked MAD but with the stack-number band rows RE-INCLUDED.

    Uses each reference's alpha mask but does NOT zero rows 14..24, so a slot
    carrying white stack digits is scored against the (digit-free) reference
    over those rows. The bright digits inflate the true item's distance and let
    a wrong reference win -- the failure the number-band zeroing prevents.
    """
    slot = np.asarray(slot_rgb, dtype=np.float32)
    rows = [r for r in NUMBER_BAND_ROWS if 0 <= r < SLOT_PX]
    best = None
    for ref in refs:
        # Reconstruct the alpha (un-zeroed): the band rows get their alpha back.
        full_mask = ref.weight_mask.copy()
        # Where the reference is opaque outside the band we already have alpha;
        # inside the band the stored mask is 0, so approximate the digits' weight
        # by re-opening those rows wherever the icon is non-background there.
        if rows:
            band = ref.ref_rgb[rows[0]:rows[-1] + 1, :, :]
            from inventory.constants import EMPTY_REF
            bg = np.array(EMPTY_REF, dtype=np.float32).reshape(1, 1, 3)
            nonbg = (np.abs(band - bg).sum(axis=2) > 3.0).astype(np.float32)
            full_mask[rows[0]:rows[-1] + 1, :] = np.maximum(
                full_mask[rows[0]:rows[-1] + 1, :], nonbg)
        msum = float(full_mask.sum()) * 3.0
        if msum <= 0.0:
            continue
        bd = float('inf')
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                sh = _shift_edge(slot, dy, dx)
                diff = np.abs(sh - ref.ref_rgb) * full_mask[:, :, None]
                d = float(diff.sum()) / msum
                if d < bd:
                    bd = d
        if best is None or bd < best[1]:
            best = (ref.name, bd)
    return best


@unittest.skipUnless(np is not None and synth is not None, 'numpy required')
class TestSyntheticAccuracy(unittest.TestCase):
    """Per-icon masked accuracy on DARK and GLOW, with number + shift + noise."""

    @classmethod
    def setUpClass(cls):
        cls.db = _db_or_skip()
        cls.refs = cls.db.references()

    def _sweep(self, glow):
        """Return ``(hits, confident_hits, weak_margin, total)`` over all icons.

        ``hits`` = top-1 is the right name; ``confident_hits`` = right name AND
        distance under :data:`MATCH_THRESHOLD` (so the engine would actually call
        it an ITEM); ``weak_margin`` = right name but non-positive margin.
        """
        hits = confident = weak = 0
        for ref in self.refs:
            slot = synth.synth_slot(ref, glow=glow, **_HOSTILE)
            rgb = extract_slot(slot, (0, 0, SLOT_PX, SLOT_PX))
            scored = self.db.match(rgb, shift_radius=2)
            self.assertTrue(scored, 'matcher returned no candidates')
            name, dist = scored[0]
            margin = scored[1][1] - dist if len(scored) > 1 else 0.0
            if name == ref.name:
                hits += 1
                if dist <= MATCH_THRESHOLD:
                    confident += 1
                if margin <= 0:
                    weak += 1
        return hits, confident, weak, len(self.refs)

    def test_dark_background_accuracy(self):
        hits, confident, weak, total = self._sweep(glow=False)
        self.assertGreaterEqual(
            hits / total, _ACCURACY_FLOOR,
            'masked accuracy on DARK must be >= 95% (got {}/{})'.format(
                hits, total))
        # The dark target is a perfect, confident, positive-margin recovery.
        self.assertEqual(hits, total, 'DARK accuracy must be 100%')
        self.assertEqual(confident, total,
                         'every DARK match must be under MATCH_THRESHOLD')
        self.assertEqual(weak, 0, 'every DARK match must have positive margin')

    def test_glow_background_accuracy(self):
        hits, confident, weak, total = self._sweep(glow=True)
        self.assertGreaterEqual(
            hits / total, _ACCURACY_FLOOR,
            'masked accuracy on GLOW must be >= 95% (got {}/{})'.format(
                hits, total))
        # GLOW is the documented worst case; the engine still hits 100% here, so
        # assert confident recognition for essentially all icons too.
        self.assertGreaterEqual(
            confident / total, _ACCURACY_FLOOR,
            'confident GLOW recognition must be >= 95% (got {}/{})'.format(
                confident, total))

    def test_full_pipeline_classifies_items_on_both_backgrounds(self):
        # Drive the PUBLIC classifier (not just the raw matcher) per icon and
        # assert it emits STATE_ITEM with the right name -- end-to-end proof.
        for glow in (False, True):
            ok = 0
            for ref in self.refs:
                slot = synth.synth_slot(ref, glow=glow, **_HOSTILE)
                rgb = extract_slot(slot, (0, 0, SLOT_PX, SLOT_PX))
                res = scanner.classify_slot(rgb, self.db, row=0, col=0)
                if res.state == STATE_ITEM and res.name == ref.name:
                    ok += 1
            self.assertGreaterEqual(
                ok / len(self.refs), _ACCURACY_FLOOR,
                'classify_slot ITEM accuracy ({}) must be >= 95% (got {}/{})'
                .format('GLOW' if glow else 'DARK', ok, len(self.refs)))


@unittest.skipUnless(np is not None and synth is not None, 'numpy required')
class TestAutoGridAlignment(unittest.TestCase):
    """A drifted synthetic grid must be re-locked by :func:`auto_align`."""

    @classmethod
    def setUpClass(cls):
        cls.db = _db_or_skip()
        cls.refs = cls.db.references()

    def _calib_for(self, origin, pitch=(SLOT_PX, SLOT_PX)):
        """A calibration whose grid.tl == ``origin`` (so the base lattice is
        exactly the un-drifted truth, and the search must re-find a drift)."""
        ox, oy = origin
        px, py = pitch
        return {
            'grid': {
                'tl': [ox, oy],
                'br': [ox + (COLS - 1) * px, oy + (ROWS - 1) * py],
                'cols': COLS,
                'rows': ROWS,
            },
            'tolerance': DEFAULT_CALIBRATION['tolerance'],
        }

    def _layout(self):
        """A 45-cell layout: a sprinkling of items + glow + empties (row-major)."""
        layout = []
        for i in range(SLOTS_PER_PAGE):
            if i % 3 == 0:
                layout.append(None)  # empty dark slot
            else:
                ref = self.refs[i % len(self.refs)]
                layout.append({'ref': ref, 'glow': (i % 5 == 0),
                               'number': (i % 2 == 0)})
        return layout

    def test_relocks_after_origin_drift(self):
        # Build a page whose true origin is (drift_x, drift_y) away from the
        # calibration guess; auto_align (origin jitter search) must recover it.
        true_origin = (7, 9)
        page, _meta = synth.synth_page(self._layout(), origin=true_origin)
        self.assertIsNotNone(page)

        # The calibration POINTS A FEW PX OFF (the documented session drift).
        guess_origin = (true_origin[0] - 3, true_origin[1] + 4)
        calib = self._calib_for(guess_origin)

        base = lattice_from_calibration(calib)
        self.assertEqual(base.origin, guess_origin)

        locked = auto_align(page, self.db, calib)
        # The re-locked origin must land on the true grid (exact: it is an
        # integer-pixel synthetic page within the +-5px search radius).
        self.assertEqual(locked.origin, true_origin,
                         'auto_align must re-lock the drifted grid origin')

    def test_relocked_lattice_recognizes_items(self):
        # After re-lock, recognition through the locked lattice must place items
        # in the right (row, col) -- i.e. the lock is correct, not just close.
        true_origin = (5, 6)
        layout = self._layout()
        page, _meta = synth.synth_page(layout, origin=true_origin)
        calib = self._calib_for((true_origin[0] + 4, true_origin[1] - 2))

        locked = auto_align(page, self.db, calib)
        results = scanner.recognize_page(page, self.db, calib,
                                         lattice=locked, page='I')
        self.assertEqual(len(results), SLOTS_PER_PAGE)

        # Compare each occupied cell to its planted item name. Emp? expect EMPTY.
        correct = occupied = 0
        for res, spec in zip(results, layout):
            if spec is None:
                self.assertEqual(res.state, STATE_EMPTY,
                                 'planted-empty slot must read EMPTY')
                continue
            occupied += 1
            if res.state == STATE_ITEM and res.name == spec['ref'].name:
                correct += 1
        self.assertGreaterEqual(
            correct / occupied, _ACCURACY_FLOOR,
            'recognition through the re-locked lattice must be >= 95% '
            '(got {}/{})'.format(correct, occupied))

    def test_no_drift_keeps_origin(self):
        # Sanity: a perfectly-calibrated grid stays put (zero drift recovered).
        origin = (4, 4)
        page, _meta = synth.synth_page(self._layout(), origin=origin)
        locked = auto_align(page, self.db, self._calib_for(origin))
        self.assertEqual(locked.origin, origin)


@unittest.skipUnless(np is not None and synth is not None, 'numpy required')
class TestGlowRegression(unittest.TestCase):
    """Glow ablation: unmasked full-icon matching collapses; masked survives."""

    @classmethod
    def setUpClass(cls):
        cls.db = _db_or_skip()
        cls.refs = cls.db.references()

    def test_unmasked_fails_but_masked_passes_under_glow(self):
        masked_hits = unmasked_hits = 0
        for ref in self.refs:
            slot = synth.synth_slot(ref, glow=True, **_HOSTILE)
            rgb = extract_slot(slot, (0, 0, SLOT_PX, SLOT_PX))
            if self.db.match(rgb, shift_radius=2)[0][0] == ref.name:
                masked_hits += 1
            if _unmasked_best(self.refs, rgb)[0] == ref.name:
                unmasked_hits += 1
        total = len(self.refs)
        # MASKED (engine) PASSES: essentially perfect.
        self.assertGreaterEqual(masked_hits / total, _ACCURACY_FLOOR,
                                'masked must pass under glow (>=95%)')
        # UNMASKED (ablation) FAILS: the recoloured background swamps it.
        self.assertLess(unmasked_hits / total, 0.5,
                        'unmasked full-icon must collapse under glow (<50%)')
        self.assertLess(unmasked_hits, masked_hits,
                        'masked must beat unmasked under glow')

    def test_unmasked_is_fine_without_glow(self):
        # Control: without the recoloured background even the unmasked baseline
        # does well -- proving it is specifically the GLOW that breaks it.
        unmasked_hits = 0
        for ref in self.refs:
            slot = synth.synth_slot(ref, glow=False, number=False,
                                    shift=(0, 0), noise=0.0)
            rgb = extract_slot(slot, (0, 0, SLOT_PX, SLOT_PX))
            if _unmasked_best(self.refs, rgb)[0] == ref.name:
                unmasked_hits += 1
        self.assertGreaterEqual(
            unmasked_hits / len(self.refs), _ACCURACY_FLOOR,
            'unmasked should be fine on a clean dark slot')


@unittest.skipUnless(np is not None and synth is not None, 'numpy required')
class TestNumberBandRegression(unittest.TestCase):
    """Stack-number band: including it breaks matching; zeroing it fixes it."""

    @classmethod
    def setUpClass(cls):
        cls.db = _db_or_skip()
        cls.refs = cls.db.references()

    def test_band_included_degrades_vs_zeroed(self):
        zeroed_hits = included_hits = 0
        for ref in self.refs:
            # Heavy stack number on the dark background (isolate the band effect
            # from glow); a small shift keeps it realistic.
            slot = synth.synth_slot(ref, glow=False, number=True,
                                    shift=(1, -1), noise=4.0)
            rgb = extract_slot(slot, (0, 0, SLOT_PX, SLOT_PX))
            # Engine matcher (number band ZEROED in the reference mask).
            if self.db.match(rgb, shift_radius=2)[0][0] == ref.name:
                zeroed_hits += 1
            # Ablation: re-include the band in the comparison.
            if _number_band_included_best(self.refs, rgb)[0] == ref.name:
                included_hits += 1
        total = len(self.refs)
        # The engine (band zeroed) PASSES.
        self.assertGreaterEqual(zeroed_hits / total, _ACCURACY_FLOOR,
                                'number-band-zeroed matcher must pass (>=95%)')
        # Re-including the band makes it strictly WORSE (the regression we guard).
        self.assertLess(included_hits, zeroed_hits,
                        'including the stack-number band must degrade accuracy')

    def test_band_rows_are_zeroed_in_every_reference(self):
        # White-box guard: the proven recipe zeroes rows 14..24 of every mask.
        rows = [r for r in NUMBER_BAND_ROWS if 0 <= r < SLOT_PX]
        for ref in self.refs:
            band = ref.weight_mask[rows[0]:rows[-1] + 1, :]
            self.assertEqual(float(np.abs(band).sum()), 0.0,
                             'reference {} must zero the number band'.format(
                                 ref.name))


if __name__ == '__main__':
    unittest.main()
