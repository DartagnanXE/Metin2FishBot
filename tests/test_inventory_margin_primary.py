"""Regression lock for MARGIN-PRIMARY acceptance (already in itemdb/constants).

Margin-primary accepts an item slightly OVER MATCH_THRESHOLD when the runner-up
reference is VERY far (large margin) -- it recovers an easy lingering-glow item
without hovering. These tests prove it CANNOT introduce a false positive:

  1. CLEAN PRIMARY: a true no-glow item is a confident ITEM the ordinary way
     (best distance well under MATCH_THRESHOLD, big margin).
  2. MARGIN-PRIMARY RECOVERY: a GLOW slot whose best distance crept just OVER
     MATCH_THRESHOLD but is still <= MARGIN_PRIMARY_MAX_DIST, with a huge margin,
     IS recovered as the correct ITEM (this is the whole point).
  3. CLOSE-FAMILY NEAR-TIE stays UNKNOWN: a near-tie between two close relatives
     -- even when the best distance lands INSIDE the margin-primary window
     (<= MARGIN_PRIMARY_MAX_DIST) -- has too SMALL a margin to fire margin-
     primary, so it is demoted to UNKNOWN, never reported as a confident WRONG
     name.

Distances/margins are COMPUTED from the bundled icons at runtime (not hard-coded
brittle numbers); the test only asserts the resulting STATE + that the scenario
genuinely exercises the margin-primary window. Skipped without numpy/PIL/icons.
The loose real-shot guard (>=12 confident no-glow items) lives in
``test_inventory_smoke_real``.
"""

import itertools
import unittest

from inventory.itemdb import ItemDB
from inventory import assets
from inventory.reference import build_reference
from inventory.constants import (
    MATCH_THRESHOLD, MARGIN_MIN, MARGIN_PRIMARY_MIN, MARGIN_PRIMARY_MAX_DIST,
)
from inventory.types import STATE_ITEM, STATE_UNKNOWN

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

try:
    from tests import _inv_synth as synth
except Exception:  # pragma: no cover
    synth = None


def _all_refs():
    """Build every bundled reference; ``{name: ItemReference}`` (or empty)."""
    refs = {}
    if np is None:
        return refs
    for path in assets.icon_paths():
        rgba = assets.load_icon_rgba(path)
        if rgba is None:
            continue
        rgba = assets.normalize_to_slot(rgba)
        if rgba is None:
            continue
        ref = build_reference(assets.name_from_path(path), rgba)
        if ref is not None:
            refs[ref.name] = ref
    return refs


@unittest.skipUnless(np is not None and synth is not None, 'numpy required')
class TestMarginPrimary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.refs = _all_refs()
        if not cls.refs:
            raise unittest.SkipTest('bundled icons / numpy unavailable')
        cls.full = ItemDB(list(cls.refs.values()))

    def test_clean_no_glow_item_is_primary_match(self):
        # Pick a no-glow item that the FULL DB recognises with best distance well
        # under MATCH_THRESHOLD -- the ordinary primary rule, NOT margin-primary.
        chosen = None
        for name, ref in self.refs.items():
            slot = synth.synth_slot(ref, glow=False)
            scored = self.full.match(slot)
            best_name, best_dist = scored[0]
            margin = scored[1][1] - best_dist
            if best_name == name and best_dist < 15.0 and margin >= MARGIN_MIN:
                chosen = (name, ref)
                break
        self.assertIsNotNone(chosen, 'no clean no-glow item found in DB')
        name, ref = chosen
        res = self.full.best_slot_result(
            synth.synth_slot(ref, glow=False), row=0, col=0, empty=False)
        self.assertEqual(res.state, STATE_ITEM)
        self.assertEqual(res.name, name)
        self.assertLess(res.distance, MATCH_THRESHOLD)   # NOT margin-primary

    def test_margin_primary_recovers_lingering_glow_item(self):
        # A GLOW slot whose best distance creeps just OVER MATCH_THRESHOLD but is
        # still within (MATCH_THRESHOLD, MARGIN_PRIMARY_MAX_DIST] with a huge
        # margin must be recovered as the CORRECT item via margin-primary.
        chosen = None
        for name, ref in self.refs.items():
            slot = synth.synth_slot(ref, glow=True)
            scored = self.full.match(slot)
            best_name, best_dist = scored[0]
            margin = scored[1][1] - best_dist
            if (best_name == name
                    and MATCH_THRESHOLD < best_dist <= MARGIN_PRIMARY_MAX_DIST
                    and margin >= MARGIN_PRIMARY_MIN):
                chosen = (name, ref, best_dist, margin)
                break
        self.assertIsNotNone(
            chosen, 'no in-window margin-primary glow recovery candidate found')
        name, ref, best_dist, margin = chosen
        res = self.full.best_slot_result(
            synth.synth_slot(ref, glow=True), row=0, col=0, empty=False)
        # Recovered as the correct ITEM ONLY because of margin-primary: its
        # distance is over the ordinary threshold, so the primary rule alone
        # would have demoted it to UNKNOWN.
        self.assertEqual(res.state, STATE_ITEM)
        self.assertEqual(res.name, name)
        self.assertGreater(res.distance, MATCH_THRESHOLD)
        self.assertLessEqual(res.distance, MARGIN_PRIMARY_MAX_DIST)
        self.assertGreaterEqual(res.margin, MARGIN_PRIMARY_MIN)

    def test_close_family_near_tie_stays_unknown(self):
        # A 50/50 blend of two CLOSE relatives (hair dyes) in a 2-ref DB is a
        # genuine near-tie (tiny margin). Margin-primary cannot fire (margin <<
        # MARGIN_PRIMARY_MIN) so it must read UNKNOWN, not a confident WRONG
        # sibling name. Search the dye pairs for such a near-tie (the closest
        # siblings -- e.g. Black vs White -- produce the tightest margin).
        dyes = [n for n in self.refs if 'Hair_Dye' in n]
        self.assertGreaterEqual(len(dyes), 2, 'need >=2 hair-dye icons')
        near_tie = None
        for a, b in itertools.combinations(dyes, 2):
            blend = (self.refs[a].ref_rgb + self.refs[b].ref_rgb) / 2.0
            bgr = np.ascontiguousarray(
                np.clip(blend, 0, 255).astype(np.uint8)[:, :, ::-1])
            db = ItemDB([self.refs[a], self.refs[b]])
            scored = db.match(bgr)
            margin = scored[1][1] - scored[0][1]
            if margin < MARGIN_PRIMARY_MIN:
                res = db.best_slot_result(bgr, row=0, col=0, empty=False)
                near_tie = (a, b, margin, res.state)
                break
        self.assertIsNotNone(
            near_tie, 'no close-family near-tie (margin < MIN) found among dyes')
        self.assertEqual(near_tie[3], STATE_UNKNOWN,
                         'close-family near-tie must stay UNKNOWN: {}'.format(
                             near_tie))

    def test_in_window_small_margin_near_tie_is_rejected(self):
        # The decisive guard: search for ANY two-ref blend whose best distance
        # lands INSIDE the margin-primary window (<= MARGIN_PRIMARY_MAX_DIST) yet
        # whose margin is below MARGIN_PRIMARY_MIN. Such a slot MUST be UNKNOWN --
        # proving margin-primary's MIN gate blocks an in-window near-tie.
        names = list(self.refs)
        found = None
        for a, b in itertools.combinations(names, 2):
            blend = self.refs[a].ref_rgb * 0.55 + self.refs[b].ref_rgb * 0.45
            bgr = np.ascontiguousarray(
                np.clip(blend, 0, 255).astype(np.uint8)[:, :, ::-1])
            db = ItemDB([self.refs[a], self.refs[b]])
            scored = db.match(bgr)
            best_dist = scored[0][1]
            margin = scored[1][1] - best_dist
            if (MATCH_THRESHOLD < best_dist <= MARGIN_PRIMARY_MAX_DIST
                    and MARGIN_MIN <= margin < MARGIN_PRIMARY_MIN):
                res = db.best_slot_result(bgr, row=0, col=0, empty=False)
                found = (a, b, best_dist, margin, res.state)
                break
        self.assertIsNotNone(
            found, 'no in-window small-margin near-tie scenario found')
        self.assertEqual(found[4], STATE_UNKNOWN,
                         'in-window near-tie must NOT be accepted: {}'.format(
                             found))


if __name__ == '__main__':
    unittest.main()
