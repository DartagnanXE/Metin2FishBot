"""Tests fuer updater.py -- nur die NETZ-/PROZESS-FREIEN Pfade.

parse_release / check_for_update werden mit eingespeisten Daten getestet (kein
echter HTTP-Call); die Build-Modus-Erkennung per Monkeypatch von sys.frozen /
sys._MEIPASS; die .bat-Erzeugung als reiner String (kein Prozess startet).

Reine stdlib, headless -- updater importiert nur stdlib + version.
"""

import sys
import unittest

import updater


def _sample_release(tag='v1.0.4', with_asset=True):
    assets = []
    if with_asset:
        assets = [
            {'name': 'some-other-file.zip',
             'browser_download_url': 'https://example/other.zip', 'size': 10},
            {'name': updater.PORTABLE_ASSET_NAME,
             'browser_download_url':
                 'https://example/Metin2MultiTool-Portable.exe',
             'size': 12_345_678},
        ]
    return {
        'tag_name': tag,
        'html_url': 'https://github.com/DartagnanXE/Metin2MultiTool/releases/'
                    'tag/' + tag,
        'assets': assets,
    }


class TestParseRelease(unittest.TestCase):
    def test_picks_portable_asset(self):
        info = updater.parse_release(_sample_release())
        self.assertIsNotNone(info)
        self.assertEqual(info.tag, 'v1.0.4')
        self.assertEqual(info.version, '1.0.4')   # leading v stripped
        self.assertEqual(info.download_url,
                         'https://example/Metin2MultiTool-Portable.exe')
        self.assertEqual(info.size, 12_345_678)
        self.assertIn('releases', info.page_url)

    def test_no_portable_asset_yields_none_url(self):
        info = updater.parse_release(_sample_release(with_asset=False))
        self.assertIsNotNone(info)
        self.assertIsNone(info.download_url)
        self.assertIsNone(info.size)

    def test_garbage_is_safe(self):
        self.assertIsNone(updater.parse_release(None))
        self.assertIsNone(updater.parse_release({}))
        self.assertIsNone(updater.parse_release({'tag_name': ''}))
        self.assertIsNone(updater.parse_release('not a dict'))


class TestCheckForUpdate(unittest.TestCase):
    def setUp(self):
        self._orig_fetch = updater.fetch_latest_release

    def tearDown(self):
        updater.fetch_latest_release = self._orig_fetch

    def test_newer_returns_info(self):
        updater.fetch_latest_release = lambda timeout=0: _sample_release(
            'v1.0.4')
        info = updater.check_for_update(current='1.0.3')
        self.assertIsNotNone(info)
        self.assertEqual(info.tag, 'v1.0.4')

    def test_same_returns_none(self):
        updater.fetch_latest_release = lambda timeout=0: _sample_release(
            'v1.0.3')
        self.assertIsNone(updater.check_for_update(current='1.0.3'))

    def test_older_returns_none(self):
        updater.fetch_latest_release = lambda timeout=0: _sample_release(
            'v1.0.2')
        self.assertIsNone(updater.check_for_update(current='1.0.3'))

    def test_fetch_failure_returns_none(self):
        updater.fetch_latest_release = lambda timeout=0: None
        self.assertIsNone(updater.check_for_update(current='1.0.3'))


class TestModeDetection(unittest.TestCase):
    def setUp(self):
        self._had_frozen = hasattr(sys, 'frozen')
        self._frozen = getattr(sys, 'frozen', None)
        self._had_meipass = hasattr(sys, '_MEIPASS')
        self._meipass = getattr(sys, '_MEIPASS', None)

    def tearDown(self):
        if self._had_frozen:
            sys.frozen = self._frozen
        elif hasattr(sys, 'frozen'):
            del sys.frozen
        if self._had_meipass:
            sys._MEIPASS = self._meipass
        elif hasattr(sys, '_MEIPASS'):
            del sys._MEIPASS

    def _set(self, frozen, meipass):
        if frozen:
            sys.frozen = True
        elif hasattr(sys, 'frozen'):
            del sys.frozen
        if meipass:
            sys._MEIPASS = r'C:\Temp\_MEI12345'
        elif hasattr(sys, '_MEIPASS'):
            del sys._MEIPASS

    def test_source(self):
        self._set(frozen=False, meipass=False)
        self.assertFalse(updater.is_frozen())
        self.assertFalse(updater.is_onefile())
        self.assertFalse(updater.is_onedir())
        self.assertFalse(updater.can_self_replace())

    def test_onefile(self):
        self._set(frozen=True, meipass=True)
        self.assertTrue(updater.is_frozen())
        self.assertTrue(updater.is_onefile())
        self.assertFalse(updater.is_onedir())
        self.assertTrue(updater.can_self_replace())

    def test_onedir(self):
        self._set(frozen=True, meipass=False)
        self.assertTrue(updater.is_frozen())
        self.assertFalse(updater.is_onefile())
        self.assertTrue(updater.is_onedir())
        self.assertFalse(updater.can_self_replace())


class TestBatGeneration(unittest.TestCase):
    def test_contains_values_and_labels(self):
        bat = updater.build_update_bat(
            pid=4321, target=r'C:\Apps\Metin2MultiTool.exe',
            new=r'C:\Temp\Metin2MultiTool-Portable-1.0.4.exe')
        self.assertIn('4321', bat)
        self.assertIn(r'C:\Apps\Metin2MultiTool.exe', bat)
        self.assertIn(r'C:\Temp\Metin2MultiTool-Portable-1.0.4.exe', bat)
        # die drei Schleifen-/Sprungmarken muessen vorhanden sein
        self.assertIn(':waitloop', bat)
        self.assertIn(':copyloop', bat)
        # cmd-Variablen muessen als EINFACHES % erhalten bleiben (kein %%)
        self.assertIn('%PID%', bat)
        self.assertIn('%TARGET%', bat)
        self.assertIn('%NEW%', bat)
        self.assertIn('%~f0', bat)
        self.assertNotIn('%%', bat)

    def test_loops_are_bounded(self):
        # KRITISCH (Regression): die Warte-/Kopier-Schleifen MUESSEN hart begrenzt
        # sein -- sonst kann der Helfer endlos laufen (frueherer Bug: Fenster-Flut,
        # unbeendbar). Jede Schleife braucht einen Zaehler-Abbruch + einen Ausweg.
        bat = updater.build_update_bat(
            pid=4321, target=r'C:\A\x.exe', new=r'C:\T\n.exe')
        self.assertIn('set /a N+=1', bat)           # Zaehler wird hochgezaehlt
        self.assertIn('GEQ', bat)                    # harte Obergrenze
        self.assertIn(':relaunch', bat)              # Ausweg aus beiden Schleifen
        # Keine UNBEDINGTE Endlosschleife: jedes 'goto waitloop'/'goto copyloop'
        # steht hinter einem Zaehler-Check (heuristisch: GEQ kommt davor je Label).
        self.assertGreaterEqual(bat.count('GEQ'), 2)  # waitloop + copyloop begrenzt


class TestDownloadUrlWhitelist(unittest.TestCase):
    """The download is pinned to trusted GitHub HTTPS hosts (a spoofed API
    response must not be able to steer the EXE download elsewhere)."""

    def test_accepts_github_release_url(self):
        # github.com (browser_download_url) and the redirect targets are allowed.
        updater._validate_download_url(
            'https://github.com/o/r/releases/download/v1/Metin2MultiTool.exe')
        updater._validate_download_url(
            'https://objects.githubusercontent.com/some/blob.exe')
        updater._validate_download_url(
            'https://release-assets.githubusercontent.com/x/y.exe')

    def test_rejects_untrusted_host(self):
        with self.assertRaises(updater.UpdateError) as ctx:
            updater._validate_download_url('https://evil.example/payload.exe')
        self.assertEqual(ctx.exception.args[0], 'untrusted_host')

    def test_rejects_non_https(self):
        with self.assertRaises(updater.UpdateError) as ctx:
            updater._validate_download_url(
                'http://github.com/o/r/releases/download/v1/x.exe')
        self.assertEqual(ctx.exception.args[0], 'insecure_url')

    def test_rejects_lookalike_subdomain(self):
        # github.com.evil.example must not pass the exact-host whitelist.
        with self.assertRaises(updater.UpdateError):
            updater._validate_download_url(
                'https://github.com.evil.example/x.exe')


class TestApplyGuards(unittest.TestCase):
    def test_apply_rejects_when_not_onefile(self):
        # Im Quellcode (kein _MEIPASS) darf apply_update_onefile nie ersetzen.
        had = hasattr(sys, '_MEIPASS')
        saved = getattr(sys, '_MEIPASS', None)
        if had:
            del sys._MEIPASS
        try:
            with self.assertRaises(updater.UpdateError):
                updater.apply_update_onefile(r'C:\Temp\whatever.exe')
        finally:
            if had:
                sys._MEIPASS = saved


if __name__ == '__main__':
    unittest.main()
