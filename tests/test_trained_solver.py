"""Schnelle, headless Tests fuer den KI-optimiert-Solver (trained_solver.py).

Die exakte V-Tabelle (~12 s) wird hier NICHT berechnet -- stattdessen wird
``trained_solver._V`` mit einer kontrollierten Mock-Tabelle belegt, sodass nur
die choose_placement-LOGIK (gueltige/optimale Lage, Verwerfen-Vertrag,
Immutabilitaet, Guards) geprueft wird. Reine stdlib + numpy.
"""

import copy
import os
import sys
import unittest

import numpy as np

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import trained_solver as ts  # noqa: E402


class _Piece:
    def __init__(self, t):
        self.piece_type = t


class TestGeometryHelpers(unittest.TestCase):
    def test_idx_corners(self):
        self.assertEqual(ts._idx(0, 0), 0)
        self.assertEqual(ts._idx(3, 5), 23)

    def test_occ(self):
        board = [[0] * 6 for _ in range(4)]
        board[0][0] = 1
        board[3][5] = 1
        self.assertEqual(ts._occ(board), (1 << 0) | (1 << 23))

    def test_single_has_24_placements(self):
        self.assertEqual(len(ts._PLACE[1]), 24)

    def test_placement_masks_match_form_size_and_in_bounds(self):
        for t in range(1, 7):
            for (x, y, m) in ts._PLACE[t]:
                self.assertEqual(bin(m).count('1'), len(ts._FORMS[t]))
                self.assertEqual(m & ~((1 << 24) - 1), 0)


class TestChoosePlacement(unittest.TestCase):
    def setUp(self):
        # Mock-Wertfunktion: ueberall teuer -> 'verbessern' gezielt steuerbar.
        ts._V = np.full(1 << 24, 100.0, dtype=np.float32)

    def tearDown(self):
        ts._V = None

    def test_invalid_piece_type_returns_none(self):
        board = [[0] * 6 for _ in range(4)]
        for t in (None, 0, 7, 99, -1):
            self.assertIsNone(ts.choose_placement(board, _Piece(t)))

    def test_none_board_returns_none(self):
        self.assertIsNone(ts.choose_placement(None, _Piece(3)))

    def test_no_improvement_burns(self):
        board = [[0] * 6 for _ in range(4)]
        self.assertIsNone(ts.choose_placement(board, _Piece(1)))

    def test_finish_mode_places_when_no_improvement(self):
        # Same constant-V state where the DEFAULT policy discards (waits): in
        # FINISH mode it must place the least-bad valid anchor instead, so a
        # stuck end-game completes the board rather than discarding forever.
        board = [[0] * 6 for _ in range(4)]
        self.assertIsNone(ts.choose_placement(board, _Piece(1)))          # default: discard
        a = ts.choose_placement(board, _Piece(1), finish=True)
        self.assertIsNotNone(a)
        self.assertTrue(0 <= a[0] <= 3 and 0 <= a[1] <= 5)

    def test_finish_mode_full_board_still_none(self):
        # Finish mode never invents a move: a FULL board has no valid anchor.
        board = [[1] * 6 for _ in range(4)]
        for t in range(1, 7):
            self.assertIsNone(ts.choose_placement(board, _Piece(t), finish=True))

    def test_picks_the_improving_placement(self):
        board = [[0] * 6 for _ in range(4)]
        m = 1 << ts._idx(2, 3)  # Single an (2,3)
        ts._V[m] = 1.0
        self.assertEqual(ts.choose_placement(board, _Piece(1)), (2, 3))

    def test_returns_valid_in_bounds_anchor(self):
        board = [[0] * 6 for _ in range(4)]
        x0, y0, m = ts._PLACE[3][7]
        ts._V[m] = 0.5
        xy = ts.choose_placement(board, _Piece(3))
        self.assertEqual(xy, (x0, y0))
        self.assertTrue(0 <= xy[0] <= 3 and 0 <= xy[1] <= 5)

    def test_full_board_returns_none(self):
        board = [[1] * 6 for _ in range(4)]
        for t in range(1, 7):
            self.assertIsNone(ts.choose_placement(board, _Piece(t)))

    def test_respects_occupied_cells(self):
        board = [[0] * 6 for _ in range(4)]
        board[2][3] = 1
        ts._V[1 << ts._idx(2, 3)] = 0.1  # billige, aber belegte Lage
        self.assertIsNone(ts.choose_placement(board, _Piece(1)))

    def test_board_not_mutated(self):
        board = [[(i * 6 + j) % 2 for j in range(6)] for i in range(4)]
        snap = copy.deepcopy(board)
        ts.choose_placement(board, _Piece(3))
        self.assertEqual(board, snap)


class TestReservatMask(unittest.TestCase):
    """_reservat_mask: (row,col)-Iterable -> Bitmaske im _occ/_idx-Layout."""

    def test_none_and_empty_are_zero(self):
        self.assertEqual(ts._reservat_mask(None), 0)
        self.assertEqual(ts._reservat_mask([]), 0)
        self.assertEqual(ts._reservat_mask(frozenset()), 0)

    def test_known_cells_map_to_idx_bits(self):
        m = ts._reservat_mask([(0, 0), (3, 5)])
        self.assertEqual(m, (1 << ts._idx(0, 0)) | (1 << ts._idx(3, 5)))

    def test_six_reservat_cells_set_six_bits(self):
        # Das V3-Reservat (unten-rechts) -> genau 6 gesetzte Bits.
        reservat = frozenset({(2, 3), (2, 4), (2, 5), (3, 3), (3, 4), (3, 5)})
        m = ts._reservat_mask(reservat)
        self.assertEqual(bin(m).count('1'), 6)
        for (r, c) in reservat:
            self.assertTrue(m & (1 << ts._idx(r, c)))

    def test_out_of_bounds_cells_ignored(self):
        # Zellen ausserhalb 4x6 werden ignoriert (kein Bit, kein Crash).
        m = ts._reservat_mask([(0, 0), (9, 9), (-1, 2), (4, 0), (0, 6)])
        self.assertEqual(m, 1 << ts._idx(0, 0))

    def test_garbage_iterable_is_defensive_zero(self):
        self.assertEqual(ts._reservat_mask('garbage'), 0)
        self.assertEqual(ts._reservat_mask([None, 5, 'x']), 0)


class TestChoosePlacementReservat(unittest.TestCase):
    """choose_placement(..., reservat=...): Reservat-Zellen gelten als belegt."""

    def setUp(self):
        ts._V = np.full(1 << 24, 100.0, dtype=np.float32)
        # Das V3-Reservat unten-rechts (muss deluxe.reservat_2x3() spiegeln).
        self.reservat = frozenset({(2, 3), (2, 4), (2, 5),
                                   (3, 3), (3, 4), (3, 5)})
        self.res_mask = ts._reservat_mask(self.reservat)

    def tearDown(self):
        ts._V = None

    def test_never_places_into_reservat(self):
        # Billigste Lage liegt MITTEN im Reservat -> ohne Reservat wird sie
        # gewaehlt, MIT Reservat darf der Solver dort nie hin (kein anderer
        # billiger Zug -> None). Hinweis: mit aktivem Reservat ist das Reservat
        # bereits Teil von occ -> die V-Lookups muessten die Reservat-Bits
        # enthalten; eine Lage IM Reservat ist aber per (occ & m)==0 ohnehin
        # ausgeschlossen, daher None.
        board = [[0] * 6 for _ in range(4)]
        ts._V[1 << ts._idx(2, 3)] = 0.1
        self.assertEqual(ts.choose_placement(board, _Piece(1)), (2, 3))
        self.assertIsNone(
            ts.choose_placement(board, _Piece(1), reservat=self.reservat))

    def test_places_outside_reservat_when_improving(self):
        # Billige Lage AUSSERHALB des Reservats (oben-links). Mit aktivem
        # Reservat ist occ schon = res_mask -> der Kandidat-Lookup ist
        # V[res_mask | bit(0,0)]; GENAU diesen Index billig machen.
        board = [[0] * 6 for _ in range(4)]
        ts._V[self.res_mask | (1 << ts._idx(0, 0))] = 0.1
        self.assertEqual(
            ts.choose_placement(board, _Piece(1), reservat=self.reservat),
            (0, 0))

    def test_block_piece_cannot_straddle_reservat_edge(self):
        # Ein 2x2-Block (Typ 3) mit Anker (1,2) wuerde die Zelle (2,3) (im
        # Reservat) ueberdecken -> diese Lage ist per (occ & m)!=0 ausgeschlossen,
        # selbst wenn ihr (kombinierter) V-Wert billig waere.
        board = [[0] * 6 for _ in range(4)]
        straddle = None
        for (x, y, m) in ts._PLACE[3]:
            if (x, y) == (1, 2):
                straddle = m
                break
        self.assertIsNotNone(straddle)
        ts._V[self.res_mask | straddle] = 0.1
        a = ts.choose_placement(board, _Piece(3), reservat=self.reservat)
        self.assertNotEqual(a, (1, 2))

    def test_reservat_does_not_mutate_board(self):
        board = [[0] * 6 for _ in range(4)]
        snap = copy.deepcopy(board)
        ts.choose_placement(board, _Piece(3), reservat=self.reservat)
        self.assertEqual(board, snap)

    def test_none_reservat_is_unchanged_behaviour(self):
        # reservat=None muss byte-gleich zum Aufruf ohne den Parameter sein.
        board = [[0] * 6 for _ in range(4)]
        ts._V[1 << ts._idx(2, 3)] = 0.1
        self.assertEqual(
            ts.choose_placement(board, _Piece(1)),
            ts.choose_placement(board, _Piece(1), reservat=None))


if __name__ == '__main__':
    unittest.main(verbosity=2)
