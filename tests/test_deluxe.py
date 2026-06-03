# -*- coding: utf-8 -*-
"""Tests fuer den DELUXE-Puzzlestein (deluxe.py): Magenta-Erkennung + 2x3-Greedy.

deluxe.py ist bewusst reine Standardbibliothek -> hier direkt importierbar und
testbar (anders als puzzle.py, das pydirectinput/cv2 voraussetzt). Geprueft wird:

  * is_magenta: das Magenta-Deluxe-Fenster trifft das gemessene (251,28,232)
    und seinen Nahbereich, KOLLIDIERT aber mit KEINER der 6 echten Steinfarben
    (PIECE_REF_BGR) und das echte Magenta faellt in KEINES der 6 engen
    single-Fenster (Drift-/Kollisions-Schutz).
  * _classify_piece (single-Pfad, gespiegelt + reale is_magenta): Magenta ->
    Typ 7, die 6 echten Farben bleiben unveraendert -> 1..6, Schwarz -> None.
  * find_free_2x3: erstes freies top-links 2x3-Loch; voll/keins -> None;
    defensiv gegen kaputte Eingaben.

stdlib-only (unittest). Lauf: python3 -m unittest tests.test_deluxe -v
"""

import copy
import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import deluxe  # noqa: E402  (reale Produktionslogik, stdlib-only)

try:  # numpy nur fuer die read_deluxe_count-Bildpfad-Tests (sonst skip)
    import numpy as np
except Exception:  # pragma: no cover
    np = None


# -- Spiegel der 6 echten Steinfarben (muss PuzzleBot.PIECE_REF_BGR gleichen) --
PIECE_REF_BGR = {
    4: (37, 65, 250),
    1: (25, 160, 250),
    5: (42, 250, 42),
    3: (250, 250, 25),
    2: (250, 107, 0),
    6: (55, 245, 255),
}


def classify_single_with_deluxe(bgr):
    """Spiegelt den 'single'-Zweig von PuzzleDetectMixin._classify_piece INKL.
    des vorangestellten realen Magenta-Checks (deluxe.is_magenta -> Typ 7)."""
    b, g, r = bgr
    if deluxe.is_magenta(b, g, r):
        return deluxe.DELUXE_PIECE_TYPE
    if b > 35 and b < 40 and g > 60 and g < 70 and r > 240 and r < 260:
        return 4
    elif b > 20 and b < 30 and g > 150 and g < 170 and r > 240 and r < 260:
        return 1
    elif b > 35 and b < 50 and g > 240 and g < 260 and r > 35 and r < 50:
        return 5
    elif b > 240 and b < 260 and g > 240 and g < 260 and r > 20 and r < 30:
        return 3
    elif b > 240 and b < 260 and g > 100 and g < 115 and r > -10 and r < 10:
        return 2
    elif b > 50 and b < 60 and g > 235 and g < 255 and r > 250 and r < 260:
        return 6
    return None


class TestIsMagenta(unittest.TestCase):
    def test_measured_magenta_is_recognized(self):
        self.assertTrue(deluxe.is_magenta(*deluxe.DELUXE_REF_BGR))
        self.assertTrue(deluxe.is_magenta(251, 28, 232))

    def test_near_magenta_still_recognized(self):
        # +-15 pro Kanal um das Zentrum darf die Erkennung nicht kippen.
        b0, g0, r0 = deluxe.DELUXE_REF_BGR
        for db in (-15, 0, 15):
            for dg in (-15, 0, 15):
                for dr in (-15, 0, 15):
                    bgr = (min(255, max(0, b0 + db)),
                           min(255, max(0, g0 + dg)),
                           min(255, max(0, r0 + dr)))
                    with self.subTest(bgr=bgr):
                        self.assertTrue(deluxe.is_magenta(*bgr))

    def test_six_real_colors_are_not_magenta(self):
        # KEINE der 6 echten Steinfarben darf ins Magenta-Fenster fallen.
        for ptype, ref in PIECE_REF_BGR.items():
            with self.subTest(ptype=ptype, ref=ref):
                self.assertFalse(deluxe.is_magenta(*ref))

    def test_black_and_grey_are_not_magenta(self):
        for bgr in [(0, 0, 0), (50, 50, 50), (128, 128, 128), (255, 255, 255)]:
            with self.subTest(bgr=bgr):
                self.assertFalse(deluxe.is_magenta(*bgr))

    def test_does_not_throw_on_bad_input(self):
        # Defensiv: nicht-numerische Eingabe -> False statt Crash.
        self.assertFalse(deluxe.is_magenta(None, None, None))


class TestClassifyIntegratesDeluxe(unittest.TestCase):
    def test_magenta_maps_to_type_7(self):
        self.assertEqual(classify_single_with_deluxe((251, 28, 232)), 7)
        self.assertEqual(classify_single_with_deluxe(deluxe.DELUXE_REF_BGR), 7)

    def test_six_real_centroids_still_map_to_their_type(self):
        # Der vorangestellte Magenta-Check darf die 6 echten Farben NICHT stoeren.
        for ptype, ref in PIECE_REF_BGR.items():
            with self.subTest(ptype=ptype):
                self.assertEqual(classify_single_with_deluxe(ref), ptype)

    def test_magenta_misses_all_six_tight_windows(self):
        # Ohne den Magenta-Check faellt (251,28,232) durch alle 6 Fenster (None)
        # -> beweist: der neue Typ 7 nimmt keinem bestehenden etwas weg.
        b, g, r = 251, 28, 232
        hit = None
        if b > 35 and b < 40 and g > 60 and g < 70 and r > 240 and r < 260:
            hit = 4
        elif b > 20 and b < 30 and g > 150 and g < 170 and r > 240 and r < 260:
            hit = 1
        elif b > 35 and b < 50 and g > 240 and g < 260 and r > 35 and r < 50:
            hit = 5
        elif b > 240 and b < 260 and g > 240 and g < 260 and r > 20 and r < 30:
            hit = 3
        elif b > 240 and b < 260 and g > 100 and g < 115 and r > -10 and r < 10:
            hit = 2
        elif b > 50 and b < 60 and g > 235 and g < 255 and r > 250 and r < 260:
            hit = 6
        self.assertIsNone(hit)

    def test_black_is_none(self):
        self.assertIsNone(classify_single_with_deluxe((0, 0, 0)))


class TestFindFree2x3(unittest.TestCase):
    @staticmethod
    def _empty():
        return [[0] * 6 for _ in range(4)]

    def test_empty_board_anchors_top_left(self):
        self.assertEqual(deluxe.find_free_2x3(self._empty()), (0, 0))

    def test_full_board_returns_none(self):
        self.assertIsNone(deluxe.find_free_2x3([[1] * 6 for _ in range(4)]))

    def test_finds_hole_after_left_block_is_filled(self):
        # Linke 2x3-Bloecke belegt -> erster freier Anker rueckt nach rechts.
        board = self._empty()
        for i in range(4):
            for j in range(3):
                board[i][j] = 1
        # Spalten 0..2 voll; das erste freie 2x3 beginnt bei Spalte 3.
        self.assertEqual(deluxe.find_free_2x3(board), (0, 3))

    def test_scans_rows_then_columns(self):
        # Obere zwei Zeilen ganz belegt -> Anker muss in Zeile 2 liegen.
        board = self._empty()
        for j in range(6):
            board[0][j] = 1
            board[1][j] = 1
        self.assertEqual(deluxe.find_free_2x3(board), (2, 0))

    def test_no_2x3_fits_returns_none(self):
        # Streumuster, das KEIN volles 2x3-Rechteck frei laesst: jede zweite
        # Spalte belegt -> jede 3-breite Fensterung enthaelt eine belegte Zelle.
        board = self._empty()
        for i in range(4):
            for j in range(0, 6, 2):
                board[i][j] = 1
        self.assertIsNone(deluxe.find_free_2x3(board))

    def test_anchor_keeps_block_in_bounds(self):
        # Der gelieferte Anker (x,y) muss ein 2x3 im 4x6-Brett zulassen.
        board = self._empty()
        board[0][0] = 1  # top-left blockieren -> Anker muss woanders hin
        anchor = deluxe.find_free_2x3(board)
        self.assertIsNotNone(anchor)
        x, y = anchor
        self.assertTrue(0 <= x <= 2 and 0 <= y <= 3)

    def test_does_not_mutate_board(self):
        board = [[(i + j) % 2 for j in range(6)] for i in range(4)]
        snap = copy.deepcopy(board)
        deluxe.find_free_2x3(board)
        self.assertEqual(board, snap)

    def test_defensive_on_bad_input(self):
        self.assertIsNone(deluxe.find_free_2x3(None))
        self.assertIsNone(deluxe.find_free_2x3([]))
        self.assertIsNone(deluxe.find_free_2x3([[0, 0, 0]]))  # zu klein
        self.assertIsNone(deluxe.find_free_2x3('garbage'))


class TestDeluxeForm(unittest.TestCase):
    def test_form_is_full_2x3(self):
        self.assertEqual(len(deluxe.DELUXE_FORM), 6)
        self.assertEqual(set(deluxe.DELUXE_FORM),
                         {(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2)})

    def test_type_is_disjoint_from_real_pieces(self):
        self.assertNotIn(deluxe.DELUXE_PIECE_TYPE, (1, 2, 3, 4, 5, 6))


class TestReservat2x3(unittest.TestCase):
    """V3-Reservat: feste 6 Zellen unten-rechts, frozenset, ins Brett passend."""

    def test_anchor_is_bottom_right(self):
        self.assertEqual(deluxe.RESERVAT_ANCHOR, (2, 3))

    def test_exact_six_cells(self):
        self.assertEqual(
            deluxe.reservat_2x3(),
            frozenset({(2, 3), (2, 4), (2, 5), (3, 3), (3, 4), (3, 5)}))

    def test_is_frozenset(self):
        self.assertIsInstance(deluxe.reservat_2x3(), frozenset)

    def test_cells_are_in_bounds(self):
        for (r, c) in deluxe.reservat_2x3():
            self.assertTrue(0 <= r < 4 and 0 <= c < 6)

    def test_matches_find_free_2x3_on_otherwise_full_board(self):
        # Sind die 18 Nicht-Reservat-Zellen voll, MUSS find_free_2x3 genau den
        # Reservat-Anker liefern -> _place_deluxe trifft das Reservat.
        reservat = deluxe.reservat_2x3()
        board = [[0 if (i, j) in reservat else 1 for j in range(6)]
                 for i in range(4)]
        self.assertEqual(deluxe.find_free_2x3(board), deluxe.RESERVAT_ANCHOR)

    def test_form_matches_anchor_plus_deluxe_form(self):
        # reservat_2x3 == RESERVAT_ANCHOR + DELUXE_FORM (konsistente Definition).
        ar, ac = deluxe.RESERVAT_ANCHOR
        expected = frozenset((ar + dr, ac + dc) for (dr, dc) in deluxe.DELUXE_FORM)
        self.assertEqual(deluxe.reservat_2x3(), expected)


class TestReservatIsEmpty(unittest.TestCase):
    @staticmethod
    def _empty():
        return [[0] * 6 for _ in range(4)]

    def test_empty_board_reservat_empty(self):
        self.assertTrue(deluxe.reservat_is_empty(self._empty()))

    def test_one_reservat_cell_set_is_not_empty(self):
        for (r, c) in deluxe.reservat_2x3():
            board = self._empty()
            board[r][c] = 1
            with self.subTest(cell=(r, c)):
                self.assertFalse(deluxe.reservat_is_empty(board))

    def test_non_reservat_cells_full_but_reservat_empty(self):
        # Die 18 Nicht-Reservat-Zellen belegt, Reservat frei -> empty == True.
        reservat = deluxe.reservat_2x3()
        board = [[0 if (i, j) in reservat else 1 for j in range(6)]
                 for i in range(4)]
        self.assertTrue(deluxe.reservat_is_empty(board))

    def test_defensive_on_bad_input(self):
        # Kein/zu kleines/kaputtes Brett -> False (nicht leer), nie Crash.
        self.assertFalse(deluxe.reservat_is_empty(None))
        self.assertFalse(deluxe.reservat_is_empty([]))
        self.assertFalse(deluxe.reservat_is_empty([[0, 0, 0]]))
        self.assertFalse(deluxe.reservat_is_empty('garbage'))

    def test_does_not_mutate_board(self):
        board = [[(i + j) % 2 for j in range(6)] for i in range(4)]
        snap = copy.deepcopy(board)
        deluxe.reservat_is_empty(board)
        self.assertEqual(board, snap)


class TestReadDeluxeCount(unittest.TestCase):
    """read_deluxe_count: STRIKT defensiv -- Fehler/None -> 0 (nie Crash)."""

    def test_none_screenshot_is_zero(self):
        self.assertEqual(deluxe.read_deluxe_count(None), 0)

    def test_none_with_explicit_center_is_zero(self):
        self.assertEqual(deluxe.read_deluxe_count(None, (503, 271)), 0)

    @unittest.skipUnless(np is not None, 'numpy required for image path')
    def test_garbage_shapes_return_zero(self):
        # 1D / 2D / leeres Array: extract_slot lehnt ab oder OCR scheitert -> 0.
        for bad in (np.zeros((5,), dtype=np.uint8),
                    np.zeros((4, 4), dtype=np.uint8)):
            with self.subTest(shape=getattr(bad, 'shape', None)):
                self.assertEqual(deluxe.read_deluxe_count(bad), 0)

    @unittest.skipUnless(np is not None, 'numpy required for image path')
    def test_returns_int_and_never_raises_on_full_frame(self):
        # Ein dunkles 800x600-BGR-Vollbild darf nie werfen und liefert einen
        # int >= 0 (der genaue Wert haengt von der OCR ab -- die ECHTE Box-Zahl-
        # Position/Schwelle ist live zu kalibrieren, siehe Modul-Docstring).
        img = np.zeros((600, 800, 3), dtype=np.uint8)
        out = deluxe.read_deluxe_count(img, (503, 271))
        self.assertIsInstance(out, int)
        self.assertGreaterEqual(out, 0)

    @unittest.skipUnless(np is not None, 'numpy required for image path')
    def test_default_center_used_when_omitted(self):
        # Ohne center-Argument wird der Default (503,271) genutzt -> kein Crash.
        img = np.zeros((600, 800, 3), dtype=np.uint8)
        self.assertIsInstance(deluxe.read_deluxe_count(img), int)


if __name__ == '__main__':  # pragma: no cover
    unittest.main(verbosity=2)
