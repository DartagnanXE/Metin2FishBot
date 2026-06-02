"""Tests for the pure change-aware diff (:mod:`inventory.diff`).

Hand-built InventoryMaps from SlotResult (no numpy / game). Locks:
  * appeared / changed / vanished classification,
  * the SILENCE rule -- an unchanged UNKNOWN slot (same signature) is in NO list,
  * unknown identity via signature (new signature => changed + new_unknown),
  * item -> unknown is reported as new_unknown,
  * previous_map=None => every occupied slot is appeared (and new_unknown lists
    the unknowns, which the RUNNER -- not this module -- suppresses on scan 1).
"""

import unittest

from inventory.diff import diff_maps, InventoryDiff, Change, _fingerprint
from inventory.types import (
    InventoryMap, SlotResult, STATE_EMPTY, STATE_ITEM, STATE_UNKNOWN,
)


def _item(name, page='I', row=0, col=0):
    return SlotResult(state=STATE_ITEM, name=name, distance=1.0, margin=20.0,
                      signature=None, page=page, row=row, col=col)


def _empty(page='I', row=0, col=0):
    return SlotResult(state=STATE_EMPTY, name=None, distance=0.0, margin=0.0,
                      signature=None, page=page, row=row, col=col)


def _unknown(sig, page='I', row=0, col=0):
    return SlotResult(state=STATE_UNKNOWN, name=None, distance=35.0, margin=2.0,
                      signature=sig, page=page, row=row, col=col)


def _map(*slots):
    """Build a single-page ('I') InventoryMap from the given SlotResults."""
    return InventoryMap(pages={'I': tuple(slots)})


def _keys(changes):
    return {(c.page, c.row, c.col) for c in changes}


class TestFingerprint(unittest.TestCase):
    def test_states(self):
        self.assertEqual(_fingerprint(_item('Worm')), ('item', 'Worm'))
        self.assertEqual(_fingerprint(_unknown((1, 2, 3))),
                         ('unknown', (1, 2, 3)))
        self.assertEqual(_fingerprint(_empty()), ('empty', None))
        self.assertEqual(_fingerprint(None), ('empty', None))


class TestDiffMaps(unittest.TestCase):
    def test_appeared_when_empty_becomes_item(self):
        prev = _map(_empty(row=0))
        new = _map(_item('Carp', row=0))
        d = diff_maps(prev, new)
        self.assertEqual(_keys(d.appeared), {('I', 0, 0)})
        self.assertEqual(d.changed, ())
        self.assertEqual(d.vanished, ())
        self.assertEqual(d.new_unknown, ())

    def test_changed_when_name_differs(self):
        prev = _map(_item('Carp', row=0))
        new = _map(_item('Eel', row=0))
        d = diff_maps(prev, new)
        self.assertEqual(_keys(d.changed), {('I', 0, 0)})
        self.assertEqual(d.appeared, ())
        self.assertEqual(d.vanished, ())
        self.assertEqual(d.new_unknown, ())

    def test_vanished_when_item_leaves(self):
        prev = _map(_item('Carp', row=0))
        new = _map(_empty(row=0))
        d = diff_maps(prev, new)
        self.assertEqual(_keys(d.vanished), {('I', 0, 0)})
        self.assertEqual(d.appeared, ())
        self.assertEqual(d.changed, ())
        self.assertEqual(d.new_unknown, ())

    def test_unchanged_item_is_silent(self):
        prev = _map(_item('Carp', row=0))
        new = _map(_item('Carp', row=0))
        d = diff_maps(prev, new)
        self.assertEqual(d.appeared, ())
        self.assertEqual(d.changed, ())
        self.assertEqual(d.vanished, ())
        self.assertEqual(d.new_unknown, ())

    def test_unchanged_unknown_is_silent(self):
        # The core spam guard: an unknown slot whose SIGNATURE is unchanged must
        # not be reported -- long-standing unknowns stay quiet.
        sig = (10, 20, 30, 40)
        prev = _map(_unknown(sig, row=0))
        new = _map(_unknown(sig, row=0))
        d = diff_maps(prev, new)
        self.assertEqual(d.appeared, ())
        self.assertEqual(d.changed, ())
        self.assertEqual(d.vanished, ())
        self.assertEqual(d.new_unknown, ())

    def test_unknown_with_new_signature_is_changed_and_new_unknown(self):
        prev = _map(_unknown((1, 1, 1), row=0))
        new = _map(_unknown((9, 9, 9), row=0))
        d = diff_maps(prev, new)
        self.assertEqual(_keys(d.changed), {('I', 0, 0)})
        self.assertEqual(_keys(d.new_unknown), {('I', 0, 0)})
        self.assertEqual(d.appeared, ())
        self.assertEqual(d.vanished, ())

    def test_empty_to_unknown_appears_and_is_new_unknown(self):
        prev = _map(_empty(row=0))
        new = _map(_unknown((5, 5, 5), row=0))
        d = diff_maps(prev, new)
        self.assertEqual(_keys(d.appeared), {('I', 0, 0)})
        self.assertEqual(_keys(d.new_unknown), {('I', 0, 0)})
        self.assertEqual(d.changed, ())

    def test_item_to_unknown_is_changed_and_new_unknown(self):
        prev = _map(_item('Carp', row=0))
        new = _map(_unknown((7, 7, 7), row=0))
        d = diff_maps(prev, new)
        self.assertEqual(_keys(d.changed), {('I', 0, 0)})
        self.assertEqual(_keys(d.new_unknown), {('I', 0, 0)})
        self.assertEqual(d.appeared, ())

    def test_unknown_to_item_is_changed_not_new_unknown(self):
        # An unknown that became a RECOGNISED item changed, but must NOT warn.
        prev = _map(_unknown((3, 3, 3), row=0))
        new = _map(_item('Carp', row=0))
        d = diff_maps(prev, new)
        self.assertEqual(_keys(d.changed), {('I', 0, 0)})
        self.assertEqual(d.new_unknown, ())

    def test_first_scan_all_occupied_appear(self):
        # previous_map=None: every occupied slot is appeared; new_unknown lists
        # the unknowns (the runner suppresses the warning on scan 1, not here).
        new = _map(_item('Carp', row=0), _empty(row=1), _unknown((1,), row=2))
        d = diff_maps(None, new)
        self.assertEqual(_keys(d.appeared), {('I', 0, 0), ('I', 2, 0)})
        self.assertEqual(_keys(d.new_unknown), {('I', 2, 0)})
        self.assertEqual(d.changed, ())
        self.assertEqual(d.vanished, ())

    def test_mixed_multi_slot(self):
        prev = _map(_item('Carp', row=0), _item('Eel', row=1),
                    _unknown((2, 2), row=2), _empty(row=3))
        new = _map(_item('Carp', row=0),            # unchanged -> silent
                   _empty(row=1),                    # vanished
                   _unknown((2, 2), row=2),          # unchanged unknown -> silent
                   _unknown((8, 8), row=3))          # appeared unknown
        d = diff_maps(prev, new)
        self.assertEqual(_keys(d.vanished), {('I', 1, 0)})
        self.assertEqual(_keys(d.appeared), {('I', 3, 0)})
        self.assertEqual(_keys(d.new_unknown), {('I', 3, 0)})
        self.assertEqual(d.changed, ())

    def test_returns_inventory_diff_type(self):
        d = diff_maps(_map(_empty()), _map(_empty()))
        self.assertIsInstance(d, InventoryDiff)
        self.assertIsInstance(d.appeared, tuple)


if __name__ == '__main__':
    unittest.main()
