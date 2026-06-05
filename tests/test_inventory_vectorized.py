"""Tests for the DEFAULT page-vectorised matcher (must equal the per-slot path).

The matcher core can score a WHOLE page (all 45 slots) against the DB in ONE
batched numpy reduction (``ItemDB.match_page_distances`` / ``scored_for_page``),
and the scanner takes this path BY DEFAULT (``VECTORIZED_DEFAULT`` is True);
``recognize_page(..., vectorized=False)`` / ``recognize_pages(...,
vectorized=False)`` force the legacy per-slot loop for comparison. The headline
guarantee is byte-for-byte equivalence between the two -- it is the SAME masked
mean-abs-diff (with the SAME per-slot adaptive FULL/BAND mask), minimised over the
SAME integer shifts, so it yields identical SlotResults (state / name / distance /
margin / signature / count). It only removes the 45x Python per-slot dispatch.
These tests pin, all headless:

  * MATCHER EXACTNESS -- ``match_page_distances`` row ``i`` == the per-slot
    ``_distances_all(slot_i)`` BIT-FOR-BIT (incl. glow / number / shift / noise),
    so the stable argsort (-> names / margins) is identical too.
  * RESULT EQUALITY -- ``recognize_page(vectorized=True)`` == the default loop,
    and ``recognize_pages(vectorized=True)`` (serial AND parallel) == the
    per-slot ``recognize_pages`` -- full SlotResult tuples, on a page mixing all
    three states + stack numbers.
  * DEFAULT ON -- ``VECTORIZED_DEFAULT`` is True; the no-arg recognise takes the
    vectorised path, and because it is BIT-IDENTICAL to the loop the resulting
    map equals an explicit ``vectorized=False`` run exactly (the speed win is
    free of any result change).
  * DEFENSIVE -- a bad slot stack / empty DB / numpy-off makes the batched
    primitive return None and the scanner fall back to the per-slot loop; the
    public recognise never raises.
  * PROGRESS -- the vectorised parallel path still fires progress 1..total in
    slot units (monotone, last == total).
"""

import threading
import unittest

from inventory import scanner
from inventory.itemdb import ItemDB
from inventory.constants import PAGES, SLOTS_PER_PAGE, SHIFT_RADIUS, slot_indices
from inventory.grid import GridLattice, extract_slot
from inventory.types import STATE_ITEM, STATE_EMPTY, STATE_UNKNOWN

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

try:
    from tests import _inv_synth as synth
except Exception:  # pragma: no cover
    synth = None


_FIXED_LATTICE = GridLattice(origin=(2, 2), pitch=(32, 32))


def _fixed_align(image, db, calib):
    return _FIXED_LATTICE


def _full_tuple(s):
    """Every observable field of a SlotResult -> a comparable tuple."""
    return (s.page, s.row, s.col, s.state, s.name, s.distance, s.margin,
            s.signature, s.count, s.count_confident)


def _db_or_skip(case):
    db = ItemDB.from_bundled()
    if not db.references():
        case.skipTest('bundled icons / numpy unavailable')
    return db


@unittest.skipUnless(np is not None and synth is not None, 'numpy required')
class TestMatchPageDistancesExact(unittest.TestCase):
    """The batched distance matrix equals the per-slot matcher bit-for-bit."""

    def setUp(self):
        self.db = _db_or_skip(self)
        self.refs = self.db.references()

    def _hard_stack(self):
        # A page mixing glow / numbers / +-shift / noise / empties so the matcher
        # is exercised the way the live game stresses it.
        layout = []
        for i in range(SLOTS_PER_PAGE):
            if i % 6 == 0:
                layout.append(None)
            else:
                layout.append({'ref': self.refs[i % len(self.refs)],
                               'glow': (i % 2 == 0), 'number': (i % 3 == 0),
                               'shift': ((i % 3) - 1, (i % 2)),
                               'noise': 3.0, 'seed': i})
        page, _ = synth.synth_page(layout, origin=(2, 2))
        return np.stack([extract_slot(page, _FIXED_LATTICE.slot_box(r, c))
                         for (r, c) in slot_indices()]).astype(np.float32)

    def test_batched_distances_equal_per_slot_loop(self):
        # ADAPTIVE MASK: the batched matcher picks BAND/FULL per slot (auto-
        # detected); the per-slot matcher must be fed the SAME flag for each slot.
        # Under that matching mask choice the batched reduction is BIT-for-bit the
        # same masked MAD/min as the per-slot path.
        from inventory.reference import slots_have_numbers
        stack = self._hard_stack()
        flags = slots_have_numbers(stack)
        self.assertEqual(len(flags), SLOTS_PER_PAGE)
        batched = self.db.match_page_distances(stack, SHIFT_RADIUS)
        self.assertIsNotNone(batched)
        self.assertEqual(batched.shape, (SLOTS_PER_PAGE, len(self.refs)))
        for i in range(SLOTS_PER_PAGE):
            per_slot = self.db._distances_all(stack[i], SHIFT_RADIUS, flags[i])
            self.assertTrue(np.array_equal(batched[i], per_slot),
                            'row %d differs from the per-slot matcher' % i)
        # The page really exercises BOTH masks (some numbered, some not), so the
        # bit-exactness is asserted across the partition boundary, not trivially.
        self.assertIn(True, flags)
        self.assertIn(False, flags)

    def test_scored_lists_match_per_slot_match(self):
        stack = self._hard_stack()
        scored_lists = self.db.scored_for_page(stack, SHIFT_RADIUS)
        self.assertEqual(len(scored_lists), SLOTS_PER_PAGE)
        for i in range(SLOTS_PER_PAGE):
            ref_scored = self.db.match(stack[i], shift_radius=SHIFT_RADIUS)
            self.assertEqual(scored_lists[i], ref_scored)

    def test_bad_stack_returns_none(self):
        self.assertIsNone(self.db.match_page_distances(None))
        self.assertIsNone(self.db.match_page_distances(np.zeros((3, 10, 10, 3))))
        self.assertIsNone(self.db.scored_for_page(np.zeros((3, 8, 8, 3))))

    def test_empty_stack_returns_empty_matrix(self):
        out = self.db.match_page_distances(np.zeros((0, 32, 32, 3),
                                                    dtype=np.float32))
        self.assertEqual(out.shape, (0, len(self.refs)))

    def test_chunk_size_does_not_change_result(self):
        stack = self._hard_stack()
        a = self.db.match_page_distances(stack, SHIFT_RADIUS, chunk=1)
        b = self.db.match_page_distances(stack, SHIFT_RADIUS, chunk=8)
        c = self.db.match_page_distances(stack, SHIFT_RADIUS, chunk=999)
        self.assertTrue(np.array_equal(a, b))
        self.assertTrue(np.array_equal(a, c))

    def test_no_numpy_returns_none(self):
        import inventory.itemdb as itemdb
        saved = itemdb.np
        try:
            itemdb.np = None
            self.assertIsNone(
                self.db.match_page_distances(np.zeros((2, 32, 32, 3))))
        finally:
            itemdb.np = saved


@unittest.skipUnless(np is not None and synth is not None, 'numpy required')
class TestRecognizeVectorizedEqualsLoop(unittest.TestCase):
    """recognize_page / recognize_pages vectorised == the per-slot default."""

    def setUp(self):
        self.db = _db_or_skip(self)
        self.refs = self.db.references()

    def _mixed_pages(self):
        captured = {}
        for i, label in enumerate(PAGES):
            layout = [None] * SLOTS_PER_PAGE
            layout[0] = {'ref': self.refs[i % len(self.refs)], 'number': True}
            layout[5] = {'ref': self.refs[(i + 1) % len(self.refs)],
                         'glow': True}
            layout[10] = {'ref': self.refs[(i + 2) % len(self.refs)],
                          'shift': (1, -1), 'noise': 3.0, 'seed': i}
            page, _ = synth.synth_page(layout, origin=(2, 2))
            # An unknown silhouette at (1,0) (high-contrast -> UNKNOWN not EMPTY).
            x = 2 + 0 * 32
            y = 2 + 1 * 32
            page[y + 6:y + 26, x + 6:x + 26, :] = np.array(
                [160, 20, 180], dtype=np.uint8)
            captured[label] = page
        return captured

    def _full_states(self, inv):
        out = {}
        for page, slots in inv.pages.items():
            for s in slots:
                out[(page, s.row, s.col)] = _full_tuple(s)
        return out

    def test_recognize_page_vectorized_equals_loop(self):
        captured = self._mixed_pages()
        for label, image in captured.items():
            loop = scanner.recognize_page(image, self.db,
                                          lattice=_FIXED_LATTICE, page=label,
                                          vectorized=False)
            vec = scanner.recognize_page(image, self.db,
                                         lattice=_FIXED_LATTICE, page=label,
                                         vectorized=True)
            self.assertEqual([_full_tuple(s) for s in loop],
                             [_full_tuple(s) for s in vec])

    def test_recognize_pages_vectorized_serial_and_parallel_equal_loop(self):
        captured = self._mixed_pages()
        loop = scanner.recognize_pages(captured, self.db,
                                       align_fn=_fixed_align, vectorized=False)
        vec_ser = scanner.recognize_pages(captured, self.db,
                                          align_fn=_fixed_align, max_workers=1,
                                          vectorized=True)
        vec_par = scanner.recognize_pages(captured, self.db,
                                          align_fn=_fixed_align, max_workers=4,
                                          vectorized=True)
        base = self._full_states(loop)
        self.assertEqual(base, self._full_states(vec_ser))
        self.assertEqual(base, self._full_states(vec_par))

        # Sanity: the page really exercised all three states + a read count.
        states = {t[3] for t in base.values()}
        self.assertEqual(states, {STATE_ITEM, STATE_EMPTY, STATE_UNKNOWN})
        counts = [t[8] for t in base.values() if t[3] == STATE_ITEM]
        self.assertTrue(any(c is not None for c in counts))

    def test_vectorized_default_is_on_and_equals_loop(self):
        # The module default is now True: the vectorised path is bit-exact to the
        # loop, so the no-arg recognise takes the fast path AND yields a map that
        # is identical to an explicit vectorized=False run (free speed, no result
        # change). Both the default page recogniser and the default pages
        # recogniser are pinned against the explicit loop.
        self.assertIs(scanner.VECTORIZED_DEFAULT, True)
        captured = self._mixed_pages()
        default = scanner.recognize_pages(captured, self.db,
                                          align_fn=_fixed_align)
        loop = scanner.recognize_pages(captured, self.db,
                                       align_fn=_fixed_align, vectorized=False)
        self.assertEqual(self._full_states(default), self._full_states(loop))
        # Same for the single-page entry point: default == explicit loop.
        for label, image in captured.items():
            dflt = scanner.recognize_page(image, self.db,
                                          lattice=_FIXED_LATTICE, page=label)
            lp = scanner.recognize_page(image, self.db, lattice=_FIXED_LATTICE,
                                        page=label, vectorized=False)
            self.assertEqual([_full_tuple(s) for s in dflt],
                             [_full_tuple(s) for s in lp])

    def test_vectorized_falls_back_when_batch_unavailable(self):
        # With the batched primitive forced unavailable the vectorised page path
        # must transparently fall back to the per-slot loop (same result, no
        # raise) rather than degrade the page.
        captured = self._mixed_pages()
        loop = scanner.recognize_pages(captured, self.db,
                                       align_fn=_fixed_align, vectorized=False)
        orig = ItemDB.scored_for_page
        try:
            ItemDB.scored_for_page = lambda self, *a, **k: None
            vec = scanner.recognize_pages(captured, self.db,
                                          align_fn=_fixed_align, max_workers=1,
                                          vectorized=True)
        finally:
            ItemDB.scored_for_page = orig
        self.assertEqual(self._full_states(loop), self._full_states(vec))

    def test_vectorized_progress_monotonic(self):
        captured = self._mixed_pages()
        total = len(PAGES) * SLOTS_PER_PAGE
        ticks = []
        lock = threading.Lock()

        def progress(done, t):
            with lock:
                ticks.append((done, t))

        scanner.recognize_pages(captured, self.db, align_fn=_fixed_align,
                                progress_fn=progress, max_workers=4,
                                vectorized=True)
        self.assertTrue(ticks)
        self.assertTrue(all(t == total for (_d, t) in ticks))
        dones = [d for (d, _t) in ticks]
        self.assertEqual(len(dones), total)
        self.assertEqual(dones[0], 1)
        self.assertEqual(dones[-1], total)
        self.assertTrue(all(b - a == 1 for a, b in zip(dones, dones[1:])))

    def test_vectorized_empty_buffer_returns_empty_map(self):
        inv = scanner.recognize_pages({}, self.db, align_fn=_fixed_align,
                                      vectorized=True)
        self.assertEqual(inv.pages, {})

    def test_vectorized_failing_aligner_falls_back_to_calibration(self):
        captured = self._mixed_pages()

        def boom_align(image, db, calib):
            raise RuntimeError('align blew up')

        inv = scanner.recognize_pages(captured, self.db, align_fn=boom_align,
                                      vectorized=True)
        self.assertEqual(set(inv.pages), set(PAGES))
        for label in PAGES:
            self.assertEqual(len(inv.pages[label]), SLOTS_PER_PAGE)


if __name__ == '__main__':
    unittest.main()
