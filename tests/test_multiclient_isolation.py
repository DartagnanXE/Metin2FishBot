# -*- coding: utf-8 -*-
"""Multiclient-Isolation: per-Client Datenordner + trained_V-Gate + per-Instanz
Puzzle-State + WindowCapture.resync_offsets (Build-Schritte 1-4 / Tests T1-T4).

Reine stdlib + Mocks; laeuft headless (win32/pydirectinput sind in conftest.py
gestubt). KEIN echtes Spiel/Fenster noetig.
"""

import os
import types
import unittest
from unittest import mock

from interface.config import paths


class TestClientDataDir(unittest.TestCase):
    """T1: M2FB_DATA_DIR routet config/stats/log in einen privaten Ordner."""

    def setUp(self):
        self._saved = os.environ.get(paths.ENV_DATA_DIR)
        os.environ.pop(paths.ENV_DATA_DIR, None)

    def tearDown(self):
        os.environ.pop(paths.ENV_DATA_DIR, None)
        if self._saved is not None:
            os.environ[paths.ENV_DATA_DIR] = self._saved

    def test_unset_returns_none_and_keeps_legacy(self):
        self.assertIsNone(paths.client_data_dir())
        # Ohne ENV bleibt config_path der reine Dateiname (Dev/CWD) -> unveraendert.
        self.assertEqual(paths.config_path(frozen=False), paths.FILENAME)

    def test_set_creates_dir_and_routes_all_siblings(self):
        import tempfile
        with tempfile.TemporaryDirectory() as base:
            target = os.path.join(base, 'client-2')
            os.environ[paths.ENV_DATA_DIR] = target
            self.assertEqual(paths.client_data_dir(), target)
            self.assertTrue(os.path.isdir(target))  # idempotent angelegt
            # config + ALLE Geschwister landen im Client-Ordner.
            self.assertEqual(paths.config_path(),
                             os.path.join(target, paths.FILENAME))
            self.assertEqual(paths.sibling_path('stats.json'),
                             os.path.join(target, 'stats.json'))
            self.assertEqual(paths.debug_log_path(),
                             os.path.join(target, paths.DEBUG_LOG_FILENAME))

    def test_client_dir_overrides_frozen(self):
        import tempfile
        with tempfile.TemporaryDirectory() as base:
            os.environ[paths.ENV_DATA_DIR] = base
            # Selbst im frozen-Fall hat der Client-Ordner Vorrang (Isolation).
            self.assertEqual(paths.config_path(frozen=True),
                             os.path.join(base, paths.FILENAME))

    def test_blank_env_is_treated_as_unset(self):
        os.environ[paths.ENV_DATA_DIR] = ''
        self.assertIsNone(paths.client_data_dir())


class TestTrainedVGate(unittest.TestCase):
    """T3: M2FB_TRAINED_V_READY -> nur np.load, NIE _compute_V/np.save (G5)."""

    def setUp(self):
        import trained_solver
        self.ts = trained_solver
        self._saved_V = trained_solver._V
        trained_solver._V = None
        self._env = {k: os.environ.get(k)
                     for k in ('M2FB_TRAINED_V_READY', 'M2FB_TRAINED_V')}

    def tearDown(self):
        self.ts._V = self._saved_V
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_ready_loads_only_never_computes_or_saves(self):
        os.environ['M2FB_TRAINED_V_READY'] = '1'
        os.environ['M2FB_TRAINED_V'] = '/pre/built/trained_V.npy'
        sentinel = object()

        def _boom_compute():
            raise AssertionError('_compute_V darf im READY-Modus NIE laufen')

        def _boom_save(*a, **k):
            raise AssertionError('np.save darf im READY-Modus NIE laufen')

        loaded = {}

        def _fake_load(path):
            loaded['path'] = path
            return sentinel

        with mock.patch.object(self.ts, '_compute_V', _boom_compute), \
                mock.patch.object(self.ts.np, 'save', _boom_save), \
                mock.patch.object(self.ts.np, 'load', _fake_load):
            result = self.ts.load_V()

        self.assertIs(result, sentinel)
        self.assertEqual(loaded['path'], '/pre/built/trained_V.npy')

    def test_not_ready_still_uses_normal_path(self):
        # Ohne READY bleibt das alte Verhalten: existiert die Cache-Datei, wird
        # sie geladen (kein harter Fail), sonst Fallback. Wir mocken nur den
        # schnellen .npy-Cache-Pfad als vorhanden.
        os.environ.pop('M2FB_TRAINED_V_READY', None)
        sentinel = object()
        with mock.patch.object(self.ts.os.path, 'exists', return_value=True), \
                mock.patch.object(self.ts.np, 'load', return_value=sentinel):
            result = self.ts.load_V()
        self.assertIs(result, sentinel)


class TestResyncOffsets(unittest.TestCase):
    """T2: resync_offsets liest GetWindowRect neu und setzt Offsets korrekt."""

    def test_resync_recomputes_offsets(self):
        import windowcapture as wc
        cap = wc.WindowCapture.__new__(wc.WindowCapture)  # __init__ umgehen
        cap.hwnd = 1234
        cap.cropped_x = wc.BORDER_PIXELS      # 8
        cap.cropped_y = wc.TITLEBAR_PIXELS    # 30
        cap.offset_x = -999
        cap.offset_y = -999
        with mock.patch.object(wc.win32gui, 'GetWindowRect',
                               return_value=(100, 200, 916, 839), create=True):
            ok = cap.resync_offsets()
        self.assertTrue(ok)
        self.assertEqual(cap.offset_x, 100 + wc.BORDER_PIXELS)
        self.assertEqual(cap.offset_y, 200 + wc.TITLEBAR_PIXELS)

    def test_resync_no_hwnd_is_false_not_raise(self):
        import windowcapture as wc
        cap = wc.WindowCapture.__new__(wc.WindowCapture)
        cap.hwnd = None
        self.assertFalse(cap.resync_offsets())


class TestPuzzleTetrisPerInstance(unittest.TestCase):
    """T4: tetris ist KEIN geteilter Klassen-Default mehr."""

    def test_class_level_tetris_is_none(self):
        import puzzle
        # Frueher Tetris() auf Klassenebene (von allen Instanzen geteilt).
        self.assertIsNone(puzzle.PuzzleBot.tetris)
        self.assertEqual(puzzle.PuzzleBot.timer_action, 0.0)

    def test_two_instances_do_not_share_board(self):
        import puzzle
        from tetris import Tetris
        a = puzzle.PuzzleBot.__new__(puzzle.PuzzleBot)
        b = puzzle.PuzzleBot.__new__(puzzle.PuzzleBot)
        a.tetris = Tetris()
        b.tetris = Tetris()
        self.assertIsNot(a.tetris, b.tetris)


if __name__ == '__main__':
    unittest.main()
