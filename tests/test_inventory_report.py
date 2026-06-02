"""Lock the Console readout format (:mod:`inventory.report`).

PURE (no numpy / game): hand-built InventoryMaps from SlotResult. Locks the dump
SHAPE so users / log scrapers can rely on it:

  * format_page_grid -- 'Page <label>  (items=.. unknown=..)' header + ROWS rows
    of COLS tokens ('.', '?', '-', or a short item token);
  * format_tracked   -- 'Tracked found at:' + per-found-item line + 'not found:';
  * format_full      -- pages I..IV in order, then the tracked block.
"""

import unittest

from inventory import report
from inventory.report import (
    format_page_grid, format_tracked, format_full, short_token,
)
from inventory.constants import COLS, ROWS
from inventory.types import (
    InventoryMap, SlotResult, STATE_EMPTY, STATE_ITEM, STATE_UNKNOWN,
)


def _slot(state, name, page, row, col, sig=None):
    return SlotResult(state=state, name=name, distance=0.0, margin=0.0,
                      signature=sig, page=page, row=row, col=col)


def _full_page(page, overrides):
    """A complete ROWS*COLS page of empties with ``overrides`` applied.

    ``overrides`` maps ``(row, col) -> SlotResult`` (replacing that empty).
    """
    slots = []
    for r in range(ROWS):
        for c in range(COLS):
            slots.append(overrides.get((r, c),
                                       _slot(STATE_EMPTY, None, page, r, c)))
    return tuple(slots)


class TestShortToken(unittest.TestCase):
    def test_single_word_truncated(self):
        self.assertEqual(short_token('Fischpuzzlebox'), 'Fisc')

    def test_multi_word_acronym(self):
        self.assertEqual(short_token('Red_Hair_Dye'), 'RHD')

    def test_none_is_unknown_token(self):
        self.assertEqual(short_token(None), '?')

    def test_max_four_chars(self):
        for name in ('Worm', 'Lagerfeuer', 'A_B_C_D_E', 'X'):
            self.assertLessEqual(len(short_token(name)), 4)


class TestFormatPageGrid(unittest.TestCase):
    def setUp(self):
        overrides = {
            (0, 0): _slot(STATE_ITEM, 'Worm', 'I', 0, 0),
            (0, 1): _slot(STATE_UNKNOWN, None, 'I', 0, 1, sig=(1, 2)),
        }
        self.inv = InventoryMap(pages={'I': _full_page('I', overrides)})

    def test_header_line(self):
        lines = format_page_grid(self.inv, 'I')
        self.assertEqual(lines[0], 'Page I  (items=1 unknown=1)')

    def test_row_count(self):
        lines = format_page_grid(self.inv, 'I')
        self.assertEqual(len(lines), 1 + ROWS)

    def test_tokens(self):
        lines = format_page_grid(self.inv, 'I')
        first = lines[1].split()
        self.assertEqual(first[0], 'Worm')
        self.assertEqual(first[1], '?')
        # Remaining cells in row 0 are empty.
        self.assertEqual(first[2], '.')

    def test_absent_page_all_missing(self):
        lines = format_page_grid(self.inv, 'IV')   # page IV not in the map
        self.assertEqual(lines[0], 'Page IV  (items=0 unknown=0)')
        # Every cell renders as the missing token '-'.
        body = ' '.join(lines[1:]).split()
        self.assertTrue(all(tok == '-' for tok in body))


class TestFormatTracked(unittest.TestCase):
    def test_found_and_not_found(self):
        page_i = _full_page('I', {
            (0, 0): _slot(STATE_ITEM, 'Worm', 'I', 0, 0),
            (1, 2): _slot(STATE_ITEM, 'Worm', 'I', 1, 2),
        })
        inv = InventoryMap(pages={'I': page_i})
        lines = format_tracked(inv, names=('Worm', 'Lagerfeuer'))
        self.assertEqual(lines[0], 'Tracked found at:')
        self.assertIn('  Worm x2: I(0,0), I(1,2)', lines)
        self.assertIn('  not found: Lagerfeuer', lines)

    def test_none_found(self):
        inv = InventoryMap(pages={'I': _full_page('I', {})})
        lines = format_tracked(inv, names=('Worm',))
        self.assertEqual(lines[0], 'Tracked found at:')
        self.assertIn('  (none)', lines)
        self.assertIn('  not found: Worm', lines)


class TestFormatFull(unittest.TestCase):
    def test_pages_in_order_then_tracked(self):
        inv = InventoryMap(pages={
            'II': _full_page('II', {}),
            'I': _full_page('I', {(0, 0): _slot(STATE_ITEM, 'Worm', 'I', 0, 0)}),
        })
        lines = format_full(inv, names=('Worm',))
        text = '\n'.join(lines)
        # Page I header must come before Page II (canonical I->IV order).
        self.assertLess(text.index('Page I '), text.index('Page II '))
        # Tracked block comes after all page grids.
        self.assertLess(text.index('Page II '), text.index('Tracked found at:'))
        self.assertIn('  Worm x1: I(0,0)', text)


if __name__ == '__main__':
    unittest.main()
