# -*- coding: utf-8 -*-
"""Monitor-Kachelung + Client-Auswahl (reine Geometrie/Logik, headless)."""

import unittest

import monitor_layout as ml


class TestTileLayout(unittest.TestCase):
    def test_single_window_top_left(self):
        r = ml.tile_layout(0, 0, 1920, 1080, 1)
        self.assertEqual(r['positions'], [(0, 0)])
        self.assertTrue(r['fits'])
        self.assertEqual((r['cols'], r['rows']), (1, 1))

    def test_two_side_by_side_fit(self):
        r = ml.tile_layout(0, 0, 1920, 1080, 2, win_w=816, win_h=639)
        self.assertTrue(r['fits'])
        self.assertEqual((r['cols'], r['rows']), (2, 1))   # nebeneinander
        self.assertEqual(r['positions'], [(0, 0), (816, 0)])

    def test_four_on_1080p_uses_2x2_overlap_flagged(self):
        # 4x(816x639): 2x2 braucht 1278px Hoehe > 1080 -> passt NICHT.
        r = ml.tile_layout(0, 0, 1920, 1080, 4)
        self.assertFalse(r['fits'])               # ehrliche Overlap-Meldung
        self.assertEqual(len(r['positions']), 4)
        # Positionen bleiben innerhalb des Monitors (kein Auslaufen).
        for (x, y) in r['positions']:
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x, 1920 - r['win_w'])
            self.assertLessEqual(y, 1080 - r['win_h'])

    def test_four_on_4k_fits_2x2(self):
        r = ml.tile_layout(0, 0, 3840, 2160, 4)
        self.assertTrue(r['fits'])
        self.assertEqual(len(r['positions']), 4)
        # 2x2 ODER 4x1 -- beide passen; Logik bevorzugt MAX Spalten (4x1).
        self.assertEqual(r['cols'], 4)
        self.assertEqual(r['positions'][0], (0, 0))

    def test_offset_monitor_origin_respected(self):
        # zweiter Monitor rechts (Origin 1920,0)
        r = ml.tile_layout(1920, 0, 1920, 1080, 2)
        self.assertEqual(r['positions'][0], (1920, 0))
        self.assertEqual(r['positions'][1], (1920 + 816, 0))

    def test_three_windows_count(self):
        r = ml.tile_layout(0, 0, 5760, 1080, 3)
        self.assertEqual(len(r['positions']), 3)
        self.assertTrue(r['fits'])
        self.assertEqual(r['cols'], 3)


class TestChooseClients(unittest.TestCase):
    def _wins(self, *hwnds):
        return [{'hwnd': h, 'w': 800, 'h': 600} for h in hwnds]

    def test_picks_first_n_in_order(self):
        res = ml.choose_clients(self._wins(10, 20, 30, 40, 50), 4)
        self.assertEqual([w['hwnd'] for w in res['chosen']], [10, 20, 30, 40])
        self.assertEqual([w['hwnd'] for w in res['unused']], [50])

    def test_preferred_first(self):
        res = ml.choose_clients(self._wins(10, 20, 30, 40, 50), 2,
                                preferred_hwnds=[40, 10])
        self.assertEqual([w['hwnd'] for w in res['chosen']], [40, 10])
        self.assertEqual(sorted(w['hwnd'] for w in res['unused']), [20, 30, 50])

    def test_preferred_missing_is_skipped(self):
        res = ml.choose_clients(self._wins(10, 20), 2, preferred_hwnds=[999, 20])
        self.assertEqual([w['hwnd'] for w in res['chosen']], [20, 10])

    def test_fewer_windows_than_n(self):
        res = ml.choose_clients(self._wins(10, 20), 4)
        self.assertEqual(len(res['chosen']), 2)
        self.assertEqual(res['unused'], [])

    def test_no_duplicate_when_preferred_also_in_list(self):
        res = ml.choose_clients(self._wins(10, 20, 30), 3, preferred_hwnds=[20])
        self.assertEqual(sorted(w['hwnd'] for w in res['chosen']), [10, 20, 30])
        self.assertEqual(len(res['chosen']), 3)


if __name__ == '__main__':
    unittest.main()
