# -*- coding: utf-8 -*-
"""Characterization tests for the puzzle.py glue (sampling / classify / diagnose).

tetris.py + piece.py (the pure solver) already have deep tests. This file pins
the CURRENT behaviour of the PuzzleBot GLUE that wires the vision sampling to the
solver -- the code a behaviour-preserving split of puzzle.py must keep stable:

  * ``_sample_cell_bgr`` -- 'single' returns the EXACT pixel (byte-stable), and
    'multi' returns the per-channel patch mean (clamped at the edges).
  * ``_classify_piece`` -- 'single' uses the six tight BGR windows (None on a
    miss); 'multi' returns the nearest reference colour (never None for a valid
    colour).
  * ``_is_valid_piece_color`` -- the tolerance check used by the board diagnosis.
  * ``_diagnose_board`` -- the {valid, empty, garbage} census over the 24 cells.
  * ``set_to_begin`` -- the per-run reset of offset / key_points / state (with
    the WindowCapture + log + file IO patched out).

Headless: puzzle.py imports cleanly under py.exe; the glue methods touch only
numpy arrays + the geometry helpers -- no window, no input. We use ``__new__`` to
get a bare instance and set the few attributes each method reads.
"""

import unittest
from unittest import mock

import numpy as np

import puzzle


def _bare_bot(color_mode='single', color_patch=3):
    bot = puzzle.PuzzleBot.__new__(puzzle.PuzzleBot)
    bot.color_mode = color_mode
    bot.color_patch = color_patch
    bot.board_size = puzzle.PuzzleBot.PUZZLE_WINDOW_SIZE
    return bot


class TestSampleCellBgrSingle(unittest.TestCase):
    def test_single_is_exact_pixel(self):
        bot = _bare_bot('single')
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        img[5, 4] = (10, 20, 30)
        self.assertEqual(bot._sample_cell_bgr(img, 4, 5), (10, 20, 30))

    def test_single_returns_int_tuple(self):
        bot = _bare_bot('single')
        img = np.full((4, 4, 3), 7, dtype=np.uint8)
        b, g, r = bot._sample_cell_bgr(img, 1, 1)
        self.assertIsInstance(b, int)
        self.assertEqual((b, g, r), (7, 7, 7))


class TestSampleCellBgrMulti(unittest.TestCase):
    def test_multi_is_patch_mean(self):
        bot = _bare_bot('multi', 3)
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        img[4:7, 3:6] = (30, 60, 90)        # 3x3 block centred on (4,5)
        self.assertEqual(bot._sample_cell_bgr(img, 4, 5), (30, 60, 90))

    def test_multi_mean_mixed_values(self):
        bot = _bare_bot('multi', 3)
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        # Centre cell (4,5) plus neighbours: half 0, half 100 -> rounded-down mean.
        img[4:7, 3:6, 0] = 0
        img[5, 4, 0] = 90                    # one bright pixel among nine
        b, _g, _r = bot._sample_cell_bgr(img, 4, 5)
        self.assertEqual(b, 10)             # 90 / 9 = 10 (int)

    def test_multi_clamps_at_edge(self):
        # At a corner the patch is clipped to the image; must not raise/index OOB.
        bot = _bare_bot('multi', 3)
        img = np.full((10, 10, 3), 50, dtype=np.uint8)
        self.assertEqual(bot._sample_cell_bgr(img, 0, 0), (50, 50, 50))


class TestClassifyPieceSingle(unittest.TestCase):
    """The six tight BGR windows, byte-stable to get_new_piece_color."""

    def setUp(self):
        self.bot = _bare_bot('single')

    def test_each_reference_colour_classifies(self):
        cases = {
            (37, 65, 250): 4,
            (25, 160, 250): 1,
            (42, 250, 42): 5,
            (250, 250, 25): 3,
            (250, 107, 0): 2,
            (55, 245, 255): 6,
        }
        for bgr, expected in cases.items():
            self.assertEqual(self.bot._classify_piece(bgr), expected, bgr)

    def test_black_is_none(self):
        self.assertIsNone(self.bot._classify_piece((0, 0, 0)))

    def test_off_window_colour_is_none(self):
        # Just outside every window -> no match.
        self.assertIsNone(self.bot._classify_piece((100, 100, 100)))


class TestClassifyPieceMulti(unittest.TestCase):
    """Nearest-reference: never None for a colour; closest centroid wins."""

    def setUp(self):
        self.bot = _bare_bot('multi')

    def test_exact_reference_nearest(self):
        self.assertEqual(self.bot._classify_piece((37, 65, 250)), 4)

    def test_near_reference_snaps(self):
        # A small drift around type 1's centroid still classifies as 1.
        self.assertEqual(self.bot._classify_piece((28, 162, 248)), 1)

    def test_black_snaps_to_a_type_not_none(self):
        # multi is nearest-colour: black is not None here (the SEPARATE black
        # guard lives in get_new_piece_color, not in _classify_piece).
        self.assertEqual(self.bot._classify_piece((0, 0, 0)), 5)


class TestIsValidPieceColor(unittest.TestCase):
    def setUp(self):
        self.bot = _bare_bot()

    def test_reference_colour_is_valid(self):
        self.assertTrue(self.bot._is_valid_piece_color(37, 65, 250))

    def test_black_is_invalid(self):
        self.assertFalse(self.bot._is_valid_piece_color(0, 0, 0))

    def test_within_tolerance_is_valid(self):
        # Default tol=45; +40 on each channel of a reference still passes.
        self.assertTrue(self.bot._is_valid_piece_color(37 + 40, 65 + 40, 250 - 40))

    def test_outside_tolerance_is_invalid(self):
        self.assertFalse(self.bot._is_valid_piece_color(150, 150, 150))


class TestDiagnoseBoard(unittest.TestCase):
    def test_all_black_is_all_empty(self):
        bot = _bare_bot('single')
        black = np.zeros((170, 260, 3), dtype=np.uint8)
        self.assertEqual(bot._diagnose_board(black),
                         {'valid': 0, 'empty': 24, 'garbage': 0})

    def test_census_counts_to_24(self):
        bot = _bare_bot('single')
        img = np.zeros((170, 260, 3), dtype=np.uint8)
        d = bot._diagnose_board(img)
        self.assertEqual(d['valid'] + d['empty'] + d['garbage'], 24)

    def test_garbage_when_occupied_but_not_piece_colour(self):
        bot = _bare_bot('single')
        # Fill bright grey everywhere (occupied, but no real piece colour) -> all
        # 24 cells count as garbage.
        img = np.full((170, 260, 3), 150, dtype=np.uint8)
        d = bot._diagnose_board(img)
        self.assertEqual(d['empty'], 0)
        self.assertEqual(d['garbage'], 24)
        self.assertEqual(d['valid'], 0)

    def test_diagnose_never_raises_on_small_image(self):
        bot = _bare_bot('single')
        tiny = np.zeros((2, 2, 3), dtype=np.uint8)
        # Out-of-range cell reads are caught internally -> returns a dict.
        d = bot._diagnose_board(tiny)
        self.assertEqual(set(d), {'valid', 'empty', 'garbage'})


class TestSetToBeginReset(unittest.TestCase):
    """Per-run reset of offset / key_points / state (IO + capture patched out)."""

    def _begin(self, bot, dictdump='{}'):
        stub_cap = type('C', (), {'offset_x': 0, 'offset_y': 0})
        with mock.patch.object(puzzle, 'WindowCapture',
                               lambda *a, **k: stub_cap()), \
                mock.patch.object(puzzle.log, 'configure',
                                  lambda *a, **k: None), \
                mock.patch.object(puzzle.log, 'section', lambda *a, **k: None), \
                mock.patch('builtins.open',
                           mock.mock_open(read_data=dictdump)):
            bot.set_to_begin({})

    def test_offset_reset_to_default(self):
        bot = puzzle.PuzzleBot.__new__(puzzle.PuzzleBot)
        bot.puzzle_offset = (1, 1)
        bot.key_points = {'color': [9, 9]}
        bot.state = 5
        self._begin(bot)
        self.assertEqual(bot.puzzle_offset,
                         puzzle.PuzzleBot.PUZZLE_WINDOW_POSITION)
        self.assertEqual(bot.key_points, {})
        self.assertEqual(bot.state, 0)

    def test_dictdump_loaded(self):
        bot = puzzle.PuzzleBot.__new__(puzzle.PuzzleBot)
        self._begin(bot, dictdump='{"a": 1}')
        self.assertEqual(bot.dictdump, {'a': 1})


class TestOpeningPositionGate(unittest.TestCase):
    """set_puzzle_state couples to Tetris.is_opening_position for the book move.

    We assert the gate the glue relies on directly (no window needed)."""

    def test_empty_board_is_opening(self):
        from tetris import Tetris
        t = Tetris()
        t.board = [[0] * 6 for _ in range(4)]
        self.assertTrue(t.is_opening_position())

    def test_nonempty_board_is_not_opening(self):
        from tetris import Tetris
        t = Tetris()
        t.board = [[0] * 6 for _ in range(4)]
        t.board[0][0] = 1
        self.assertFalse(t.is_opening_position())


class _FakeWincap:
    """Minimal stand-in for WindowCapture (only the click offsets are read)."""

    def __init__(self, offset_x, offset_y):
        self.offset_x = offset_x
        self.offset_y = offset_y


class TestButtonClickMethods(unittest.TestCase):
    """Pin the EXACT screen (x, y, button) of the three one-shot click helpers.

    press_comfirm / press_comfirm_cake / throw_pice each map a board reference
    point (via the geometry accessor + optional key_points override) into screen
    coordinates ``int(point + puzzle_offset + wincap.offset)`` and click. These
    are not otherwise unit-tested (they need a live window), so this nails their
    output -- any behaviour-preserving deduplication must keep it identical.
    """

    def _bot(self, key_points=None, offset=(270, 227), wincap=(1000, 500),
             board_size=None):
        bot = puzzle.PuzzleBot.__new__(puzzle.PuzzleBot)
        bot.board_size = board_size or puzzle.PuzzleBot.PUZZLE_WINDOW_SIZE
        bot.key_points = key_points or {}
        bot.puzzle_offset = offset
        bot.wincap = _FakeWincap(*wincap)
        return bot

    def _expected(self, bot, accessor, kp_name):
        import geometry
        cx, cy = accessor(bot.board_size, bot.key_points.get(kp_name))
        return (int(cx + bot.puzzle_offset[0] + bot.wincap.offset_x),
                int(cy + bot.puzzle_offset[1] + bot.wincap.offset_y))

    def _capture_click(self, fn):
        calls = []
        with mock.patch.object(puzzle.pydirectinput, 'click',
                               lambda **kw: calls.append(kw)):
            fn()
        self.assertEqual(len(calls), 1)
        return calls[0]

    def test_press_comfirm_left_at_confirm_point(self):
        import geometry
        bot = self._bot()
        call = self._capture_click(bot.press_comfirm)
        ex, ey = self._expected(bot, geometry.confirm_point, 'confirm')
        self.assertEqual((call['x'], call['y'], call['button']), (ex, ey, 'left'))

    def test_throw_pice_right_at_confirm_point(self):
        import geometry
        bot = self._bot()
        call = self._capture_click(bot.throw_pice)
        ex, ey = self._expected(bot, geometry.confirm_point, 'confirm')
        self.assertEqual((call['x'], call['y'], call['button']), (ex, ey, 'right'))

    def test_press_comfirm_cake_left_at_cake_point(self):
        import geometry
        bot = self._bot()
        call = self._capture_click(bot.press_comfirm_cake)
        ex, ey = self._expected(bot, geometry.cake_point, 'cake')
        self.assertEqual((call['x'], call['y'], call['button']), (ex, ey, 'left'))

    def test_keypoint_override_is_honoured(self):
        import geometry
        # A 'confirm' override must shift both confirm-based clicks identically.
        bot = self._bot(key_points={'confirm': (40, 55)})
        ex, ey = self._expected(bot, geometry.confirm_point, 'confirm')
        c1 = self._capture_click(bot.press_comfirm)
        c2 = self._capture_click(bot.throw_pice)
        self.assertEqual((c1['x'], c1['y']), (ex, ey))
        self.assertEqual((c2['x'], c2['y']), (ex, ey))

    def test_scaled_board_size_scales_points(self):
        import geometry
        # Non-reference board size exercises the geometry scaling path.
        bot = self._bot(board_size=(520, 340))
        call = self._capture_click(bot.press_comfirm_cake)
        ex, ey = self._expected(bot, geometry.cake_point, 'cake')
        self.assertEqual((call['x'], call['y']), (ex, ey))


if __name__ == '__main__':
    unittest.main()
