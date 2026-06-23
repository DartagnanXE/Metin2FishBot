# -*- coding: utf-8 -*-
"""Tests fuer die stabile config.json-Position (interface/config/paths.py) und
die Legacy-Migration in io.load.

Regression gegen den "zwei FishLover"/Re-Onboarding-Bug: der Pfad war ein nackter
CWD-relativer 'config.json', der bei der Portable-EXE nicht verlaesslich getroffen
wurde. Reine Standardbibliothek -> laeuft ueberall (auch headless/WSL)."""

import json
import os
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from interface.config import io, paths  # noqa: E402


class TestConfigPath(unittest.TestCase):
    def test_dev_not_frozen_is_cwd_filename(self):
        # Dev/Test: byte-stabil das bisherige Verhalten.
        self.assertEqual(paths.config_path(frozen=False), 'config.json')

    def test_frozen_is_appdata(self):
        # FIX v2: frozen -> IMMER %APPDATA%/Metin2FishBot/config.json (versions-,
        # ordner- und rebuild-STABIL), NICHT mehr neben der EXE.
        with tempfile.TemporaryDirectory() as appd:
            p = paths.config_path(frozen=True, appdata=appd)
            self.assertEqual(p, os.path.join(appd, paths.APP_DIR, 'config.json'))
            self.assertTrue(os.path.isdir(os.path.join(appd, paths.APP_DIR)))

    def test_frozen_ignores_executable_always_appdata(self):
        # Der Pfad haengt NICHT mehr am EXE-Ordner (das war der Re-Onboarding-Bug):
        # egal welche executable -> immer derselbe %APPDATA%-Pfad.
        with tempfile.TemporaryDirectory() as appd:
            for exe in (None, '/irgend/ein/ordner/app.exe', '', 123):
                self.assertEqual(
                    paths.config_path(frozen=True, executable=exe, appdata=appd),
                    os.path.join(appd, paths.APP_DIR, 'config.json'))

    def test_never_raises_on_garbage(self):
        for kw in ({'frozen': True}, {'frozen': 'yes', 'executable': 123}):
            self.assertIsInstance(paths.config_path(**kw), str)

    def test_dir_writable_true_for_tmp(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(paths._dir_writable(d))

    def test_dir_writable_false_for_missing_or_empty(self):
        self.assertFalse(paths._dir_writable('/no/such/dir/xyz123'))
        self.assertFalse(paths._dir_writable(''))
        self.assertFalse(paths._dir_writable(None))


class TestDebugLogPath(unittest.TestCase):
    """Die Debug-Logdatei haengt am STABILEN Config-Ordner (nicht CWD-relativ),
    damit sie bei der Portable-EXE nicht in System32 o.ae. landet."""

    def test_dev_not_frozen_is_cwd_filename(self):
        # Im Dev/Test-Betrieb (nicht frozen) byte-stabil = reiner Dateiname.
        had = hasattr(sys, 'frozen')
        saved = getattr(sys, 'frozen', None)
        if had:
            del sys.frozen
        try:
            self.assertEqual(paths.debug_log_path(), 'puzzle_debug.log')
        finally:
            if had:
                sys.frozen = saved

    def test_frozen_is_in_appdata_dir(self):
        with tempfile.TemporaryDirectory() as appd:
            sys.frozen = True
            try:
                p = paths.debug_log_path(appdata=appd)
            finally:
                del sys.frozen
            self.assertEqual(os.path.basename(p), 'puzzle_debug.log')
            self.assertEqual(os.path.basename(os.path.dirname(p)),
                             paths.APP_DIR)

    def test_never_raises(self):
        self.assertIsInstance(paths.debug_log_path(), str)


class TestLegacyConfigPaths(unittest.TestCase):
    def test_returns_appdata_then_exe_dir_then_cwd(self):
        # Reihenfolge nach der Umbenennung: (1) ALTER %APPDATA%/Metin2FishBot-
        # Ordner (Rename-Migration, hoechste Praeferenz), (2) config.json IM
        # EXE-Ordner, (3) CWD-Datei. Struktur statt exaktem String pruefen
        # (os.path.abspath haengt auf Windows ein Laufwerk an).
        lst = paths.legacy_config_paths(
            executable=os.path.join('any', 'exe', 'dir', 'app.exe'))
        # (1) Alt-Appdata zuerst: Elternordner == LEGACY_APP_DIR.
        self.assertEqual(os.path.basename(lst[0]), 'config.json')
        self.assertEqual(os.path.basename(os.path.dirname(lst[0])),
                         paths.LEGACY_APP_DIR)
        # (2) EXE-Ordner ist als Eintrag mit Elternordner 'dir' enthalten.
        self.assertTrue(any(os.path.basename(os.path.dirname(p)) == 'dir'
                            for p in lst))
        # (3) CWD-Datei zuletzt.
        self.assertEqual(lst[-1], 'config.json')

    def test_never_raises(self):
        self.assertIsInstance(paths.legacy_config_paths(executable=None), list)
        self.assertIn('config.json', paths.legacy_config_paths(executable=123))


class TestLegacyMigration(unittest.TestCase):
    def test_implicit_default_migrates_legacy_cwd_config_when_frozen(self):
        # Frozen simuliert: Default-Pfad liegt anderswo + fehlt -> der implizite
        # load() zieht die alte CWD-config.json (Upgrader verliert nichts).
        with tempfile.TemporaryDirectory() as d:
            cwd = os.getcwd()
            orig = io.DEFAULT_CONFIG_PATH
            try:
                os.chdir(d)
                with open('config.json', 'w', encoding='utf-8') as handle:
                    json.dump({'username': 'LegacyName'}, handle)
                io.DEFAULT_CONFIG_PATH = os.path.join(d, 'exe', 'config.json')
                cfg = io.load()           # implizit -> Migration aktiv
                self.assertEqual(cfg.get('username'), 'LegacyName')
            finally:
                io.DEFAULT_CONFIG_PATH = orig
                os.chdir(cwd)

    def test_explicit_missing_path_does_not_migrate(self):
        # Regression: ein EXPLIZITER fehlender Pfad darf NIE die CWD-config.json
        # aufsammeln (Tests laufen aus einem Repo MIT config.json).
        with tempfile.TemporaryDirectory() as d:
            cwd = os.getcwd()
            try:
                os.chdir(d)
                with open('config.json', 'w', encoding='utf-8') as handle:
                    json.dump({'username': 'ShouldNotLeak'}, handle)
                cfg = io.load(os.path.join(d, 'explicit_missing.json'))
                self.assertEqual(cfg.get('username', ''), '')   # saubere Defaults
            finally:
                os.chdir(cwd)

    def test_explicit_existing_path_is_read(self):
        with tempfile.TemporaryDirectory() as d:
            anchored = os.path.join(d, 'anchored.json')
            with open(anchored, 'w', encoding='utf-8') as handle:
                json.dump({'username': 'AnchoredName'}, handle)
            cfg = io.load(anchored)
            self.assertEqual(cfg.get('username'), 'AnchoredName')


if __name__ == '__main__':
    unittest.main(verbosity=2)
