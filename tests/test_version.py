"""Tests fuer version.py (Single Source of Truth + version_tuple).

Reine stdlib, headless -- version.py importiert nichts.
"""

import unittest

import version


class TestVersionConstant(unittest.TestCase):
    def test_version_is_133(self):
        # Pro Release nachziehen -- der Pin verhindert ein versehentliches
        # Shipping mit alter Versionsnummer (Updater vergleicht gegen den Tag).
        self.assertEqual(version.__version__, '1.3.3')


class TestVersionTuple(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(version.version_tuple('1.0.3'), (1, 0, 3))

    def test_strips_leading_v(self):
        self.assertEqual(version.version_tuple('v1.0.4'), (1, 0, 4))
        self.assertEqual(version.version_tuple('V2.1'), (2, 1))

    def test_strips_prerelease_suffix(self):
        self.assertEqual(version.version_tuple('v1.0.4-beta'), (1, 0, 4))
        self.assertEqual(version.version_tuple('1.2.3+build7'), (1, 2, 3))
        self.assertEqual(version.version_tuple('v1.0.4 (rc1)'), (1, 0, 4))

    def test_garbage_is_safe(self):
        self.assertEqual(version.version_tuple('garbage'), (0,))
        self.assertEqual(version.version_tuple(''), (0,))
        self.assertEqual(version.version_tuple(None), (0,))

    def test_ordering(self):
        vt = version.version_tuple
        self.assertGreater(vt('v1.0.4'), vt('1.0.3'))
        self.assertGreater(vt('v1.1.0'), vt('v1.0.99'))
        self.assertFalse(vt('1.0.3') > vt('v1.0.3'))   # equal -> not newer
        self.assertGreater(vt('v1.0.3'), vt('1.0.2'))

    def test_default_arg_matches_constant(self):
        self.assertEqual(version.version_tuple(), version.version_tuple(
            version.__version__))


if __name__ == '__main__':
    unittest.main()
