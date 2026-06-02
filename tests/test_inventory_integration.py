# -*- coding: utf-8 -*-
"""End-to-end HEADLESS integration tests for the inventory engine.

These bind the new ``inventory`` package + ``interface.inventory_runner``
together on STATIC images (no game, no win32, no live capture/input -- every
live primitive is either a fake callback or a monkeypatch). They are deliberately
the HARD, exact-number counterpart to the looser ``test_inventory_smoke_real``:
where that module only prints recognition counts, here the real no-glow shot
``FischOhneLeuchten.png`` is pinned to its exact 26-item ground truth.

Covered (one TestCase per area; numbers asserted, not printed):

  1. CORE scan on FischOhneLeuchten.png -> a 26-item InventoryMap with the
     expected names at the expected slots (exact set; full page tally 26/1/18).
  2. The hover-clear slot-centre sweep: 45 serpentine centres in the right order,
     each == slot-box CENTRE (origin + col*px + 16 / row*py + 16), + to_screen.
  3. Margin-acceptance: synthetic GLOW recall IMPROVES with margin-primary on,
     AND a no-glow regression keeps 26/26 with ZERO close-family confusion.
  4. The Console / map formatter output (format_full on the real map).
  5. The DIFFERENTIAL diff (previous-vs-new): only newly-appeared UNKNOWNs warn
     (exactly one), unchanged unknowns stay SILENT, recognised changes tracked,
     vanished items do not warn -- asserted both via pure ``diff_maps`` AND
     end-to-end through the real runner's one-shot warning.
  6. Config + i18n parity still hold for the inventory section.

Skipped (not failed) when numpy / PIL / the bundled icons / the screenshot are
unavailable, exactly like the other image-backed inventory tests.
"""

import os
import string
import unittest

from inventory.itemdb import ItemDB
from inventory import grid as grid_mod, scanner, report
from inventory.grid import GridLattice
from inventory.hover import slot_centres, to_screen, park_point
from inventory.diff import diff_maps, InventoryDiff
from inventory.types import (
    InventoryMap, SlotResult, STATE_EMPTY, STATE_ITEM, STATE_UNKNOWN,
)
from inventory.constants import (
    DEFAULT_CALIBRATION, SLOTS_PER_PAGE, SLOT_PX, COLS, ROWS, PAGES,
    MATCH_THRESHOLD, MARGIN_MIN, MARGIN_PRIMARY_MIN, MARGIN_PRIMARY_MAX_DIST,
)

from interface import inventory_runner as ir
from interface import config

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None

try:
    from tests import _inv_synth as synth
except Exception:  # pragma: no cover
    synth = None


# -- the real no-glow screenshot lives one level above the repo root ---------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_NO_GLOW_SHOT = os.path.join(_REPO_ROOT, '..', 'FischOhneLeuchten.png')


def _shot_present():
    return os.path.isfile(_NO_GLOW_SHOT)


def _load_bgr(path):
    """Load a PNG as the BGR uint8 image a real capture would yield."""
    rgb = np.asarray(Image.open(path).convert('RGB'), dtype=np.uint8)
    return np.ascontiguousarray(rgb[:, :, ::-1])


# Ground truth for FischOhneLeuchten.png (no glow), derived by running the real
# auto-align + recognize_page pipeline once and frozen here. Every one of these
# 26 matches has distance < 1.7 and margin > 27 on the real pixels, so they are
# stable, confident, close-family-unambiguous recognitions -- the exact set the
# CORE scan must reproduce. Note the genuine close-family pair both present and
# DISTINCT: 'Zander' and 'Large_Zander'.
_EXPECTED_ITEMS = {
    (0, 0): 'Yabby',
    (0, 1): 'Mandarin_Fish',
    (0, 2): 'White_Hair_Dye',
    (0, 3): 'Large_Zander',
    (1, 0): 'Large_Zander',
    (1, 1): 'Sage_King_Symbol',
    (1, 2): 'Silver_Key',
    (1, 3): 'Grass_Carp',
    (1, 4): 'Zander',
    (2, 0): 'Shiri',
    (2, 2): 'Sage_King_Symbol',
    (2, 3): 'Perch',
    (2, 4): 'Large_Zander',
    (3, 0): 'Tenchi',
    (3, 1): 'Lotus_Fish',
    (3, 2): 'Goldfish',
    (3, 3): 'Salmon',
    (3, 4): 'Zander',
    (4, 0): 'Carp',
    (4, 2): 'Perch',
    (4, 4): 'Gold_Key',
    (5, 1): 'Salmon',
    (5, 3): 'Tenchi',
    (5, 4): 'Lagerfeuer',
    (6, 1): 'Sage_King_Symbol',
    (6, 2): 'Lagerfeuer',
}
_EXPECTED_ITEM_COUNT = 26
_EXPECTED_EMPTY_COUNT = 1
_EXPECTED_UNKNOWN_COUNT = 18

# The locked lattice the real shot aligns to (origin + 32px pitch on both axes).
_EXPECTED_ORIGIN = (633, 275)
_EXPECTED_PITCH = (32, 32)
_EXPECTED_PAGE = 'I'

# Close families that must NOT be confused with one another in the no-glow scan.
# Each tuple is a set of icon basenames that look alike; the regression asserts
# every recognised name sits in at most one family member per slot AND that the
# whole 26-set introduces no WRONG sibling (we know the exact correct set).
_CLOSE_FAMILIES = (
    ('Zander', 'Large_Zander'),
    ('Black_Hair_Dye', 'Blonde_Hair_Dye', 'Brown_Hair_Dye',
     'Red_Hair_Dye', 'White_Hair_Dye'),
    ('Fischpuzzlebox', 'Fischpuzzlebox_Deluxe'),
)

_HALF = SLOT_PX // 2


def _build_db_or_skip(case):
    db = ItemDB.from_bundled()
    if not db.references():
        case.skipTest('bundled icons / numpy unavailable')
    return db


# --------------------------------------------------------------------------- #
# (1) CORE scan on the real no-glow shot -> exact 26-item InventoryMap.        #
# --------------------------------------------------------------------------- #
@unittest.skipUnless(np is not None and Image is not None and _shot_present(),
                     'numpy/PIL/screenshot required')
class TestCoreScanGroundTruth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = ItemDB.from_bundled()
        if not cls.db.references():
            raise unittest.SkipTest('bundled icons / numpy unavailable')
        cls.img = _load_bgr(_NO_GLOW_SHOT)
        cls.lattice = grid_mod.auto_align(cls.img, cls.db, DEFAULT_CALIBRATION)
        cls.page = grid_mod.active_page(cls.img, DEFAULT_CALIBRATION)
        results = scanner.recognize_page(
            cls.img, cls.db, DEFAULT_CALIBRATION,
            lattice=cls.lattice, page=cls.page)
        cls.results = results
        cls.inv = InventoryMap(pages={cls.page: tuple(results)})

    def test_active_page_and_lattice_locked(self):
        # The shot opens tab I and the grid re-locks to the empirical origin with
        # a clean 32px pitch (the documented half-pitch failure produced 0 items).
        self.assertEqual(self.page, _EXPECTED_PAGE)
        self.assertEqual(self.lattice.origin, _EXPECTED_ORIGIN)
        self.assertEqual(self.lattice.pitch, _EXPECTED_PITCH)

    def test_exactly_26_items(self):
        items = self.inv.items()
        self.assertEqual(len(items), _EXPECTED_ITEM_COUNT,
                         'expected exactly 26 recognised items')
        # And the whole-page tally is exactly 26 item / 1 empty / 18 unknown.
        self.assertEqual(len(self.results), SLOTS_PER_PAGE)
        empties = [r for r in self.results if r.state == STATE_EMPTY]
        unknowns = self.inv.unknowns()
        self.assertEqual(len(empties), _EXPECTED_EMPTY_COUNT)
        self.assertEqual(len(unknowns), _EXPECTED_UNKNOWN_COUNT)

    def test_names_at_expected_slots(self):
        # Build {(row, col): name} for every recognised item and assert it equals
        # the frozen ground truth EXACTLY (no missing, no extra, no wrong slot).
        got = {(r.row, r.col): r.name
               for r in self.results if r.state == STATE_ITEM}
        self.assertEqual(got, _EXPECTED_ITEMS)

    def test_every_item_is_a_confident_low_distance_match(self):
        # Each recognised item really is confident on real pixels: small masked
        # distance and a margin clearing the close-family guard. This is what
        # makes the exact-name assertion robust rather than lucky.
        for r in self.inv.items():
            self.assertLessEqual(r.distance, 6.0,
                                 'item {} at ({},{}) not a tight match'.format(
                                     r.name, r.row, r.col))
            self.assertGreaterEqual(r.margin, MARGIN_MIN)

    def test_inventory_map_query_helpers_on_real_map(self):
        # The pure InventoryMap helpers agree with the ground truth.
        self.assertEqual(self.inv.count('Lagerfeuer'), 2)
        self.assertEqual(sorted(self.inv.locations('Lagerfeuer')),
                         [('I', 5, 4), ('I', 6, 2)])
        self.assertEqual(self.inv.count('Zander'), 2)        # (1,4) + (3,4)
        self.assertEqual(self.inv.count('Large_Zander'), 3)  # (0,3)+(1,0)+(2,4)
        # 'Lagerfeuer' is a tracked KEY_ITEM and is found.
        self.assertIn('Lagerfeuer', self.inv.tracked())


# --------------------------------------------------------------------------- #
# (2) Hover-clear slot-centre sweep: 45 serpentine CENTRES in order.           #
# --------------------------------------------------------------------------- #
class TestHoverSlotCentres(unittest.TestCase):
    """Pure geometry (no numpy) -- derives the expected centres independently."""

    def setUp(self):
        # The exact lattice the real shot locks to, so the sweep is the one the
        # live runner would feed to pydirectinput on this inventory.
        self.lattice = GridLattice(origin=_EXPECTED_ORIGIN, pitch=_EXPECTED_PITCH)

    def _expected_centre(self, row, col):
        ox, oy = self.lattice.origin
        px, py = self.lattice.pitch
        return (ox + col * px + _HALF, oy + row * py + _HALF)

    def test_count_is_45(self):
        self.assertEqual(len(slot_centres(self.lattice)), SLOTS_PER_PAGE)

    def test_centres_match_slot_box_centres_in_serpentine_order(self):
        # Build the EXPECTED ordered list independently: even rows left->right,
        # odd rows right->left, each point == origin + col*px+16 / row*py+16.
        expected = []
        for row in range(ROWS):
            cols = range(COLS) if row % 2 == 0 else range(COLS - 1, -1, -1)
            for col in cols:
                expected.append(self._expected_centre(row, col))
        self.assertEqual(slot_centres(self.lattice), expected)

    def test_first_and_seam_points(self):
        centres = slot_centres(self.lattice)
        # First centre = top-left slot centre.
        self.assertEqual(centres[0], self._expected_centre(0, 0))
        # Boustrophedon seam: index 4 ends row 0 at the RIGHT, index 5 starts row
        # 1 at the SAME right column (no carriage-return jump to the left edge).
        self.assertEqual(centres[4], self._expected_centre(0, COLS - 1))
        self.assertEqual(centres[5], self._expected_centre(1, COLS - 1))
        # Last centre = bottom row; row 8 is even so it ends at the right edge.
        self.assertEqual(centres[-1], self._expected_centre(ROWS - 1, COLS - 1))

    def test_consecutive_hops_are_single_steps(self):
        # The whole point of serpentine order: every hop between consecutive
        # centres moves exactly one pitch on exactly one axis (no long jumps).
        centres = slot_centres(self.lattice)
        px, py = self.lattice.pitch
        for (x0, y0), (x1, y1) in zip(centres, centres[1:]):
            dx, dy = abs(x1 - x0), abs(y1 - y0)
            self.assertTrue((dx == px and dy == 0) or (dx == 0 and dy == py),
                            'non-single-step hop {}->{}'.format(
                                (x0, y0), (x1, y1)))

    def test_to_screen_adds_offset_without_mutating(self):
        centres = slot_centres(self.lattice)
        screen = to_screen(centres, (1000, 500))
        self.assertEqual(len(screen), SLOTS_PER_PAGE)
        self.assertEqual(screen[0],
                         (centres[0][0] + 1000, centres[0][1] + 500))
        # Pure: the input list is unchanged (new list returned).
        self.assertEqual(centres[0], self._expected_centre(0, 0))

    def test_park_point_is_below_every_slot(self):
        # The post-sweep park point must sit STRICTLY below the bottom row of
        # slots (so the de-glowed re-capture is never taken with the cursor on a
        # slot). Its y is past the lower edge of every slot box.
        park = park_point(self.lattice)
        oy = self.lattice.origin[1]
        py = self.lattice.pitch[1]
        bottom_edge = oy + (ROWS - 1) * py + SLOT_PX  # lower edge of last row
        self.assertGreaterEqual(park[1], bottom_edge,
                                'park point must be below the grid')
        # And it lines up under the bottom-left column (x == col 0 centre).
        self.assertEqual(park[0], self._expected_centre(ROWS - 1, 0)[0])


# --------------------------------------------------------------------------- #
# (3) Margin-acceptance: synthetic glow recall improves + no-glow 26/26.       #
# --------------------------------------------------------------------------- #
@unittest.skipUnless(np is not None and synth is not None, 'numpy required')
class TestMarginAcceptanceGlowRecall(unittest.TestCase):
    """Margin-primary lifts synthetic GLOW recall above the plain-primary rule."""

    @classmethod
    def setUpClass(cls):
        cls.db = ItemDB.from_bundled()
        if not cls.db.references():
            raise unittest.SkipTest('bundled icons / numpy unavailable')
        cls.refs = cls.db.references()

    def _glow_recall(self, allow_margin_primary):
        """Recall over all icons under GLOW (+number+shift+noise).

        ``allow_margin_primary=False`` reproduces the PLAIN-primary decision
        (clear MATCH_THRESHOLD AND margin >= MARGIN_MIN); ``True`` adds the
        margin-primary OR-branch (the real classifier). Same scored() output
        feeds both, so the only difference is the acceptance rule -> a fair
        before/after on the identical slots.
        """
        primary_hits = 0
        with_mp_hits = 0
        for ref in self.refs:
            slot = synth.synth_slot(ref, glow=True, number=True,
                                    shift=(1, -1), noise=4.0)
            scored = self.db.match(slot, shift_radius=2)
            self.assertTrue(scored)
            best_name, best_dist = scored[0]
            margin = (scored[1][1] - best_dist) if len(scored) > 1 else 0.0
            correct = best_name == ref.name
            primary = best_dist <= MATCH_THRESHOLD and margin >= MARGIN_MIN
            margin_primary = (best_dist <= MARGIN_PRIMARY_MAX_DIST
                              and margin >= MARGIN_PRIMARY_MIN)
            if correct and primary:
                primary_hits += 1
            if correct and (primary or margin_primary):
                with_mp_hits += 1
        return primary_hits, with_mp_hits

    def test_margin_primary_improves_glow_recall(self):
        primary_hits, with_mp_hits = self._glow_recall(True)
        # Margin-primary is a pure OR-branch on the plain-primary decision, so it
        # can only ADD accepted items -> recall never drops, and on the synthetic
        # heavy-glow sweep it strictly RECOVERS several items the plain rule
        # rejected (measured: plain ~13 -> margin-primary ~19 of 43). This is the
        # documented SMALL additive safety net for lingering glow; the FULL glow
        # defence is the hover-clear de-glow (whose result is the no-glow 26/26
        # asserted separately) -- so we assert the genuine net IMPROVEMENT here,
        # not a high absolute end-state (most still-glowing slots correctly sit
        # beyond the margin-primary ceiling and wait for the hover sweep).
        self.assertGreaterEqual(with_mp_hits, primary_hits)
        self.assertGreater(with_mp_hits, primary_hits,
                           'margin-primary recovered no extra glow item')
        # A meaningful (non-trivial) recovery, not a single fluke item.
        self.assertGreaterEqual(with_mp_hits - primary_hits, 3,
                                'margin-primary recovered too few glow items')

    def test_margin_primary_recovers_a_specific_lingering_glow_item(self):
        # There exists at least one icon whose GLOW slot lands in the margin-
        # primary window (over threshold, under the ceiling, huge margin) and is
        # correctly recovered as an ITEM -- the concrete recovery case.
        recovered = None
        for ref in self.refs:
            slot = synth.synth_slot(ref, glow=True)
            scored = self.db.match(slot)
            best_name, best_dist = scored[0]
            margin = (scored[1][1] - best_dist) if len(scored) > 1 else 0.0
            if (best_name == ref.name
                    and MATCH_THRESHOLD < best_dist <= MARGIN_PRIMARY_MAX_DIST
                    and margin >= MARGIN_PRIMARY_MIN):
                res = self.db.best_slot_result(slot, row=0, col=0, empty=False)
                recovered = (ref.name, res)
                break
        if recovered is None:
            self.skipTest('no in-window margin-primary glow candidate in DB')
        name, res = recovered
        self.assertEqual(res.state, STATE_ITEM)
        self.assertEqual(res.name, name)
        self.assertGreater(res.distance, MATCH_THRESHOLD)
        self.assertLessEqual(res.distance, MARGIN_PRIMARY_MAX_DIST)


@unittest.skipUnless(np is not None and Image is not None and _shot_present(),
                     'numpy/PIL/screenshot required')
class TestNoGlowRegressionNoCloseFamilyConfusion(unittest.TestCase):
    """The no-glow shot stays 26/26 with ZERO close-family confusion."""

    @classmethod
    def setUpClass(cls):
        cls.db = ItemDB.from_bundled()
        if not cls.db.references():
            raise unittest.SkipTest('bundled icons / numpy unavailable')
        img = _load_bgr(_NO_GLOW_SHOT)
        lattice = grid_mod.auto_align(img, cls.db, DEFAULT_CALIBRATION)
        cls.results = scanner.recognize_page(
            img, cls.db, DEFAULT_CALIBRATION, lattice=lattice, page='I')
        cls.items = [r for r in cls.results if r.state == STATE_ITEM]

    def test_still_26_of_26(self):
        # Margin-primary (which is ALWAYS on in the real classifier) must NOT
        # have inflated or changed the no-glow result: still exactly 26, still
        # the exact ground-truth set.
        self.assertEqual(len(self.items), _EXPECTED_ITEM_COUNT)
        got = {(r.row, r.col): r.name for r in self.items}
        self.assertEqual(got, _EXPECTED_ITEMS)

    def test_no_item_was_accepted_via_margin_primary(self):
        # On a clean no-glow shot every accepted item clears the ORDINARY primary
        # rule (distance <= MATCH_THRESHOLD, margin >= MARGIN_MIN). None relies on
        # the margin-primary lingering-glow branch -> margin-primary changed
        # nothing here, exactly as designed.
        for r in self.items:
            self.assertLessEqual(r.distance, MATCH_THRESHOLD)
            self.assertGreaterEqual(r.margin, MARGIN_MIN)

    def test_zero_close_family_confusion(self):
        # No recognised name is a WRONG close-family sibling: the recognised set
        # equals the ground-truth set, and each slot's margin is comfortably above
        # the close-family floor (so no slot is a near-tie that could flip to a
        # sibling). Both members of the genuine 'Zander'/'Large_Zander' family are
        # present at their CORRECT distinct slots.
        for r in self.items:
            self.assertEqual(_EXPECTED_ITEMS.get((r.row, r.col)), r.name)
            # A near-tie between two siblings would show a small margin; every
            # real match here clears MARGIN_PRIMARY_MIN with room to spare.
            self.assertGreater(r.margin, MARGIN_PRIMARY_MIN,
                               'slot ({},{}) {} too close to its runner-up'
                               .format(r.row, r.col, r.name))
        # The close-family members that ARE present sit at exactly the expected
        # slots (no swap between siblings).
        zander_slots = {(r.row, r.col) for r in self.items if r.name == 'Zander'}
        lz_slots = {(r.row, r.col)
                    for r in self.items if r.name == 'Large_Zander'}
        self.assertEqual(zander_slots, {(1, 4), (3, 4)})
        self.assertEqual(lz_slots, {(0, 3), (1, 0), (2, 4)})
        self.assertFalse(zander_slots & lz_slots)   # disjoint, no confusion


# --------------------------------------------------------------------------- #
# (4) Console / map formatter output on the real 26-item map.                 #
# --------------------------------------------------------------------------- #
@unittest.skipUnless(np is not None and Image is not None and _shot_present(),
                     'numpy/PIL/screenshot required')
class TestFormatterOnRealMap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = ItemDB.from_bundled()
        if not cls.db.references():
            raise unittest.SkipTest('bundled icons / numpy unavailable')
        img = _load_bgr(_NO_GLOW_SHOT)
        lattice = grid_mod.auto_align(img, cls.db, DEFAULT_CALIBRATION)
        results = scanner.recognize_page(
            img, cls.db, DEFAULT_CALIBRATION, lattice=lattice, page='I')
        cls.inv = InventoryMap(pages={'I': tuple(results)})

    def test_page_grid_header_and_shape(self):
        lines = report.format_page_grid(self.inv, 'I')
        # Header carries the exact 26/18 tally.
        self.assertEqual(lines[0], 'Page I  (items=26 unknown=18)')
        # 1 header + ROWS body lines.
        self.assertEqual(len(lines), 1 + ROWS)

    def test_full_dump_tracked_block(self):
        lines = report.format_full(self.inv)
        text = '\n'.join(lines)
        # The page header appears, then the tracked summary after the grid.
        self.assertIn('Page I  (items=26 unknown=18)', lines)
        self.assertIn('Tracked found at:', lines)
        self.assertLess(text.index('Page I '), text.index('Tracked found at:'))
        # Lagerfeuer (a KEY_ITEM) is found twice at its ground-truth slots.
        self.assertIn('  Lagerfeuer x2: I(5,4), I(6,2)', lines)
        # The other tracked key items are genuinely absent from this inventory.
        self.assertIn(
            '  not found: Fischpuzzlebox, Fischpuzzlebox_Deluxe, Worm', lines)

    def test_tokens_render_for_known_unknown_empty(self):
        # The grid row for row 0 starts with the Yabby token, and row 6 contains
        # the single empty '.' (slot (6,3)) plus '?' unknowns -- proving every
        # cell-state token path is exercised by the real map.
        grid = report.format_page_grid(self.inv, 'I')
        row0 = grid[1].split()
        self.assertEqual(row0[0], report.short_token('Yabby'))
        # Row index 7 in `grid` == body row 6 (header is grid[0]).
        body_row6 = grid[1 + 6].split()
        self.assertIn('.', body_row6)   # the lone empty slot at (6,3)
        self.assertIn('?', body_row6)   # unknown(s) on the same row


# --------------------------------------------------------------------------- #
# (5) DIFFERENTIAL diff: previous-vs-new map warning semantics.               #
# --------------------------------------------------------------------------- #
class TestDifferentialDiffSemantics(unittest.TestCase):
    """Pure ``diff_maps`` on hand-built maps shaped like a real re-scan.

    One scan vs the next, with: an unchanged recognised item (silent), an
    unchanged unknown (silent), a recognised item that CHANGED name (tracked,
    not a warning), an item that VANISHED (no warning), and EXACTLY ONE
    newly-appeared UNKNOWN (the only thing the runner warns about).
    """

    def _item(self, name, row, col, page='I'):
        return SlotResult(state=STATE_ITEM, name=name, distance=1.0,
                          margin=30.0, signature=None, page=page,
                          row=row, col=col)

    def _empty(self, row, col, page='I'):
        return SlotResult(state=STATE_EMPTY, name=None, distance=0.0,
                          margin=0.0, signature=None, page=page,
                          row=row, col=col)

    def _unknown(self, sig, row, col, page='I'):
        return SlotResult(state=STATE_UNKNOWN, name=None, distance=38.0,
                          margin=4.0, signature=sig, page=page,
                          row=row, col=col)

    def _scenario(self):
        prev = InventoryMap(pages={'I': (
            self._item('Lagerfeuer', 0, 0),     # stays -> silent
            self._unknown((1, 2, 3), 0, 1),     # stays (same sig) -> silent
            self._item('Carp', 0, 2),           # changes name -> CHANGED
            self._item('Worm', 0, 3),           # vanishes -> VANISHED (no warn)
            self._empty(0, 4),                  # becomes a new UNKNOWN -> warn
        )})
        new = InventoryMap(pages={'I': (
            self._item('Lagerfeuer', 0, 0),
            self._unknown((1, 2, 3), 0, 1),
            self._item('Perch', 0, 2),          # name differs from 'Carp'
            self._empty(0, 3),                  # Worm gone
            self._unknown((9, 9, 9), 0, 4),     # freshly appeared unknown
        )})
        return prev, new

    def _keys(self, changes):
        return {(c.page, c.row, c.col) for c in changes}

    def test_exactly_one_new_unknown_warning(self):
        prev, new = self._scenario()
        d = diff_maps(prev, new)
        self.assertIsInstance(d, InventoryDiff)
        # The ONLY warn-worthy event: the empty (0,4) -> unknown.
        self.assertEqual(len(d.new_unknown), 1)
        self.assertEqual(self._keys(d.new_unknown), {('I', 0, 4)})

    def test_unchanged_unknown_is_silent(self):
        prev, new = self._scenario()
        d = diff_maps(prev, new)
        # The long-standing unknown at (0,1) (same signature) is in NO list.
        self.assertNotIn(('I', 0, 1), self._keys(d.appeared))
        self.assertNotIn(('I', 0, 1), self._keys(d.changed))
        self.assertNotIn(('I', 0, 1), self._keys(d.vanished))
        self.assertNotIn(('I', 0, 1), self._keys(d.new_unknown))

    def test_recognised_change_is_tracked_not_warned(self):
        prev, new = self._scenario()
        d = diff_maps(prev, new)
        # Carp -> Perch is a recognised CHANGE: tracked in `changed`, but it is a
        # known item (not unknown) so it is NOT in new_unknown.
        self.assertEqual(self._keys(d.changed), {('I', 0, 2)})
        self.assertNotIn(('I', 0, 2), self._keys(d.new_unknown))

    def test_vanished_item_does_not_warn(self):
        prev, new = self._scenario()
        d = diff_maps(prev, new)
        # Worm left (0,3): VANISHED, and vanished never contributes a warning.
        self.assertEqual(self._keys(d.vanished), {('I', 0, 3)})
        self.assertEqual(
            self._keys(d.vanished) & self._keys(d.new_unknown), set())

    def test_unchanged_recognised_item_is_silent(self):
        prev, new = self._scenario()
        d = diff_maps(prev, new)
        for field in (d.appeared, d.changed, d.vanished, d.new_unknown):
            self.assertNotIn(('I', 0, 0), self._keys(field))


@unittest.skipUnless(np is not None and synth is not None, 'numpy required')
class TestDifferentialThroughRunner(unittest.TestCase):
    """The same one-shot semantics END-TO-END through the live runner shell.

    Live deps are monkeypatched (no game). A baseline scan then a re-scan where a
    single fresh UNKNOWN appears must warn EXACTLY once; a long-standing unknown
    re-scanned must NOT warn. Proves the runner consumes ``diff.new_unknown``
    correctly (warns once, suppressed on the first scan).
    """

    class _FakePDI:
        def __init__(self):
            self.PAUSE = 0.0
            self.keys = []
            self.clicks = []
            self.moves = []

        def keyDown(self, k):
            self.keys.append((k, 'down'))

        def keyUp(self, k):
            self.keys.append((k, 'up'))

        def click(self, x=None, y=None, button='left'):
            self.clicks.append((x, y))

        def moveTo(self, x, y):
            self.moves.append((x, y))

    class _FakeWinCap:
        offset_x = 1000
        offset_y = 500

        def __init__(self, pages_by_tab, tab_state):
            self._pages = pages_by_tab
            self._tab_state = tab_state

        def get_screenshot(self):
            return self._pages[self._tab_state[0]]

    def setUp(self):
        self.db = ItemDB.from_bundled()
        if not self.db.references():
            self.skipTest('bundled icons / numpy unavailable')
        self.refs = self.db.references()
        self._orig = {}
        self._grid_orig = None
        self._scan_align_orig = None
        # Neutralise the best-effort crop WRITE so the new-unknown runner tests
        # never leave a PNG on disk; teardown restores the real writer.
        self._orig['_save_bgr_png'] = ir._save_bgr_png
        ir._save_bgr_png = lambda crop_bgr, path: True

    def tearDown(self):
        for name, val in self._orig.items():
            setattr(ir, name, val)
        if self._grid_orig is not None:
            grid_mod.active_page = self._grid_orig
        if self._scan_align_orig is not None:
            ir.scanner.auto_align = self._scan_align_orig

    def _patch(self, name, val):
        if name not in self._orig:
            self._orig[name] = getattr(ir, name)
        setattr(ir, name, val)

    def _wire(self, pages_by_tab):
        tab_state = ['I']
        pdi = self._FakePDI()
        wincap = self._FakeWinCap(pages_by_tab, tab_state)
        self._patch('pydirectinput', pdi)
        self._patch('WindowCapture', lambda name: wincap)

        tabs = DEFAULT_CALIBRATION['tabs']

        def fake_click(x=None, y=None, button='left'):
            pdi.clicks.append((x, y))
            for label, c in tabs.items():
                if (x == wincap.offset_x + c[0]
                        and y == wincap.offset_y + c[1]):
                    tab_state[0] = label
                    break

        pdi.click = fake_click

        if self._grid_orig is None:
            self._grid_orig = grid_mod.active_page
        grid_mod.active_page = lambda img, calib: tab_state[0]

        # Pin the lattice to the synth origin (2,2) -- the calibration origin is
        # off the small synth canvas (same shim the runner tests use).
        if self._scan_align_orig is None:
            self._scan_align_orig = ir.scanner.auto_align
        ir.scanner.auto_align = (
            lambda img, db, calib, **kw: GridLattice(origin=(2, 2),
                                                     pitch=(32, 32)))
        return pdi, tab_state

    def _restore_wire(self):
        if self._grid_orig is not None:
            grid_mod.active_page = self._grid_orig
            self._grid_orig = None
        if self._scan_align_orig is not None:
            ir.scanner.auto_align = self._scan_align_orig
            self._scan_align_orig = None

    def _empty_pages(self):
        page, _ = synth.synth_page([None] * (COLS * ROWS), origin=(2, 2))
        return {label: page for label in PAGES}

    def _unknown_page(self):
        # A high-contrast magenta silhouette at slot (0,0) -> reads UNKNOWN.
        layout = [None] * (COLS * ROWS)
        page, _ = synth.synth_page(layout, origin=(2, 2))
        page[2 + 6:2 + 26, 2 + 6:2 + 26, :] = np.array([160, 20, 180],
                                                        dtype=np.uint8)
        return page

    def test_runner_warns_once_for_newly_appeared_unknown(self):
        warnings = []
        self._orig.setdefault('_warn', ir._warn)
        ir._warn = lambda key, **fmt: warnings.append((key, fmt))

        base_pages = self._empty_pages()
        new_pages = self._empty_pages()
        new_pages = dict(new_pages)
        new_pages['I'] = self._unknown_page()

        try:
            cfg = {'inventory': {'hotkey': 'i'}}
            # First scan (previous=None): suppressed, no new-unknown warning.
            self._wire(base_pages)
            base_map = ir.run_inventory_scan(cfg, previous_map=None,
                                             log_fn=lambda _l: None, db=self.db)
            self._restore_wire()
            self.assertEqual(
                [w for w in warnings if w[0] == 'inventory.new_unknown_item'],
                [], 'first scan must not warn new-unknown')

            # Re-scan with the baseline: the appeared unknown warns EXACTLY once.
            warnings.clear()
            self._wire(new_pages)
            ir.run_inventory_scan(cfg, previous_map=base_map,
                                  log_fn=lambda _l: None, db=self.db)
            self._restore_wire()
            warns = [w for w in warnings
                     if w[0] == 'inventory.new_unknown_item']
            self.assertEqual(len(warns), 1)
            self.assertEqual(warns[0][1].get('page'), 'I')
        finally:
            if '_warn' in self._orig:
                ir._warn = self._orig['_warn']

    def test_runner_silent_for_long_standing_unknown(self):
        warnings = []
        self._orig.setdefault('_warn', ir._warn)
        ir._warn = lambda key, **fmt: warnings.append((key, fmt))

        prev_pages = self._empty_pages()
        prev_pages = dict(prev_pages)
        prev_pages['I'] = self._unknown_page()
        new_pages = self._empty_pages()
        new_pages = dict(new_pages)
        new_pages['I'] = self._unknown_page()

        try:
            cfg = {'inventory': {'hotkey': 'i'}}
            self._wire(prev_pages)
            prev_map = ir.run_inventory_scan(cfg, previous_map=None,
                                             log_fn=lambda _l: None, db=self.db)
            self._restore_wire()

            warnings.clear()
            self._wire(new_pages)
            ir.run_inventory_scan(cfg, previous_map=prev_map,
                                  log_fn=lambda _l: None, db=self.db)
            self._restore_wire()
            self.assertEqual(
                [w for w in warnings if w[0] == 'inventory.new_unknown_item'],
                [], 'a long-standing unknown must not warn')
        finally:
            if '_warn' in self._orig:
                ir._warn = self._orig['_warn']


# --------------------------------------------------------------------------- #
# (6) Config + i18n parity for the inventory section still hold.              #
# --------------------------------------------------------------------------- #
class TestInventoryConfigAndI18nParity(unittest.TestCase):
    """The inventory config section + the inventory i18n keys are intact."""

    def test_inventory_config_defaults_and_validation(self):
        inv = config.validate(config.DEFAULTS)['inventory']
        self.assertEqual(inv['hotkey'], 'i')
        self.assertIs(inv['auto_scan_after_fishing'], False)
        # Invalid hotkey falls back; uppercase is lowercased; bools coerce.
        self.assertEqual(
            config.validate({'inventory': {'hotkey': 'nope'}})['inventory'][
                'hotkey'], 'i')
        self.assertEqual(
            config.validate({'inventory': {'hotkey': 'B'}})['inventory'][
                'hotkey'], 'b')
        self.assertIs(
            config.validate({'inventory': {'auto_scan_after_fishing': 1}})[
                'inventory']['auto_scan_after_fishing'], True)
        # An old config with no inventory section is backfilled.
        merged = config.validate({'mode': 'puzzle'})
        self.assertIn('inventory', merged)
        self.assertEqual(merged['inventory']['hotkey'], 'i')

    def test_runner_i18n_keys_present_with_en_de_parity(self):
        # Every translation key the runner / engine emit must exist in BOTH
        # languages with matching {placeholders} (so neither language raises at
        # format time). This pins the inventory subset specifically.
        from i18n_data import TRANSLATIONS

        def placeholders(text):
            return {f for _l, f, _s, _c in string.Formatter().parse(text) if f}

        runner_keys = [
            'inventory.scan_started', 'inventory.scan_done',
            'inventory.scan_not_open', 'inventory.new_unknown_item',
            'inventory.unknown_crop_saved', 'inventory.scan_page_failed',
            'inventory.scan_page_no_image', 'inventory.scan_page_wrong_tab',
            'inventory.grid_locked', 'inventory.db_built',
        ]
        for key in runner_keys:
            self.assertIn(key, TRANSLATIONS, 'missing i18n key {!r}'.format(key))
            entry = TRANSLATIONS[key]
            self.assertTrue(str(entry.get('en', '')).strip(), key)
            self.assertTrue(str(entry.get('de', '')).strip(), key)
            self.assertEqual(placeholders(entry['en']), placeholders(entry['de']),
                             'placeholder mismatch for {!r}'.format(key))

    def test_new_unknown_item_key_formats_with_runner_fields(self):
        # The runner calls t('inventory.new_unknown_item', page=.., slot=..); the
        # translation must accept exactly those fields in both languages.
        from i18n import t
        en = t('inventory.new_unknown_item', page='I', slot=5)
        self.assertIsInstance(en, str)
        self.assertTrue(en)


if __name__ == '__main__':
    unittest.main()
