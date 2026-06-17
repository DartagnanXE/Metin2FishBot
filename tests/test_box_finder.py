# -*- coding: utf-8 -*-
"""Tests fuer den dedizierten Puzzle-Box-Finder (interface.refill.find_box_slot).

Kalibriert/validiert am echten Client-Screenshot (2026-06-17): am FESTEN
Kalibrier-Grid abtasten (kein Auto-Align -- der lockt ~10px daneben) + nur die
OBERE Icon-Haelfte matchen (untere traegt die grosse Stueckzahl). Diese Tests
bauen synthetische Frames mit dem echten Box-Template am bekannten Slot.
"""

import os
import unittest

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

from interface import refill
from inventory.constants import DEFAULT_CALIBRATION
from inventory.grid import lattice_from_calibration
from respath import resource_path


def _slot_center(row, col):
    lat = lattice_from_calibration(DEFAULT_CALIBRATION)
    ox, oy = lat.origin
    px, py = lat.pitch
    return int(ox + col * px + px // 2), int(oy + row * py + py // 2)


def _frame_with_box(row, col, name='Fischpuzzlebox', stack_noise=False):
    """600x800 BGR-Frame, dunkler Hintergrund, echtes Box-Icon am Slot (row,col).
    ``stack_noise`` malt helle Pixel in die UNTERE Icon-Haelfte (simuliert die
    grosse Stueckzahl) -> der Finder muss trotzdem matchen (obere Haelfte)."""
    frame = np.full((600, 800, 3), 12, np.uint8)
    tpl = cv2.imread(resource_path(os.path.join('inventory_icons', name + '.png')),
                     cv2.IMREAD_UNCHANGED)
    bgr = tpl[:, :, :3]
    alpha = tpl[:, :, 3]
    th, tw = bgr.shape[:2]
    cx, cy = _slot_center(row, col)
    y0, x0 = cy - th // 2, cx - tw // 2
    region = frame[y0:y0 + th, x0:x0 + tw]
    m = alpha > 32
    region[m] = bgr[m]
    if stack_noise:
        region[th // 2:, :] = 240   # untere Haelfte hell ueberschreiben
    return frame


@unittest.skipIf(cv2 is None, 'cv2 nicht verfuegbar')
class BoxFinderTest(unittest.TestCase):
    def test_finds_standard_box_at_exact_slot(self):
        frame = _frame_with_box(4, 2, 'Fischpuzzlebox')
        loc = refill.find_box_slot(lambda: frame, lambda p: None, ('Fischpuzzlebox',))
        self.assertIsNotNone(loc)
        _page, row, col, name = loc
        self.assertEqual((row, col, name), (4, 2, 'Fischpuzzlebox'))

    def test_matches_despite_stack_number_in_lower_half(self):
        # Genau der Client-Fall: grosse Stueckzahl in der unteren Haelfte.
        frame = _frame_with_box(4, 2, 'Fischpuzzlebox', stack_noise=True)
        loc = refill.find_box_slot(lambda: frame, lambda p: None, ('Fischpuzzlebox',))
        self.assertIsNotNone(loc, 'Box muss trotz Stueckzahl erkannt werden')
        self.assertEqual(loc[1:], (4, 2, 'Fischpuzzlebox'))

    def test_empty_inventory_returns_none(self):
        frame = np.full((600, 800, 3), 12, np.uint8)
        self.assertIsNone(
            refill.find_box_slot(lambda: frame, lambda p: None, ('Fischpuzzlebox',)))

    def test_returns_first_in_row_major_order(self):
        # Zwei Boxen: (4,2) und (1,0) -> der frueheste (row-major) gewinnt.
        frame = _frame_with_box(4, 2, 'Fischpuzzlebox')
        # zweite Box an (1,0) einbauen
        tpl = cv2.imread(resource_path(os.path.join('inventory_icons',
                         'Fischpuzzlebox.png')), cv2.IMREAD_UNCHANGED)
        bgr, alpha = tpl[:, :, :3], tpl[:, :, 3]
        cx, cy = _slot_center(1, 0)
        reg = frame[cy - 16:cy + 16, cx - 16:cx + 16]
        reg[alpha > 32] = bgr[alpha > 32]
        loc = refill.find_box_slot(lambda: frame, lambda p: None, ('Fischpuzzlebox',))
        self.assertEqual(loc[1:], (1, 0, 'Fischpuzzlebox'))


if __name__ == '__main__':
    unittest.main()
