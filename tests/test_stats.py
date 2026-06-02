# -*- coding: utf-8 -*-
"""Unit tests for the persistent stats store (stats.py).

Mirrors tests/test_config.py style: defaults/validate never raise on garbage,
increments are immutable + clamp negatives, runtime accumulates, atomic
save/load round-trips in a tempdir, load returns defaults on missing/corrupt
file. Pure stdlib unittest.
"""

import json
import os
import tempfile
import unittest

import stats


class TestDefaultsAndValidate(unittest.TestCase):
    def test_defaults_shape(self):
        d = stats.validate(stats.DEFAULTS)
        self.assertEqual(d['fishing_catches'], 0)
        self.assertEqual(d['puzzles_solved'], 0)
        self.assertEqual(d['fishing_runtime_s'], 0.0)
        self.assertEqual(d['puzzler_runtime_s'], 0.0)
        self.assertEqual(d['version'], stats.STATS_VERSION)

    def test_validate_never_raises_on_garbage(self):
        for junk in (None, 42, 'x', [], {'fishing_catches': object()},
                     {'fishing_runtime_s': 'NaN'}, float('nan')):
            d = stats.validate(junk)
            self.assertIn('fishing_catches', d)
            self.assertIn('puzzler_runtime_s', d)

    def test_negatives_clamped_to_zero(self):
        d = stats.validate({'fishing_catches': -5, 'fishing_runtime_s': -3.2})
        self.assertEqual(d['fishing_catches'], 0)
        self.assertEqual(d['fishing_runtime_s'], 0.0)

    def test_nan_runtime_clamped(self):
        d = stats.validate({'fishing_runtime_s': float('nan')})
        self.assertEqual(d['fishing_runtime_s'], 0.0)

    def test_validate_does_not_mutate_input(self):
        src = {'fishing_catches': 3}
        before = repr(src)
        stats.validate(src)
        self.assertEqual(repr(src), before)

    def test_unknown_keys_dropped(self):
        d = stats.validate({'fishing_catches': 2, 'bogus': 9})
        self.assertNotIn('bogus', d)
        self.assertEqual(d['fishing_catches'], 2)


class TestIncrements(unittest.TestCase):
    def test_increment_catch_immutable(self):
        a = stats.validate(stats.DEFAULTS)
        b = stats.increment_catch(a)
        self.assertEqual(a['fishing_catches'], 0)   # original untouched
        self.assertEqual(b['fishing_catches'], 1)

    def test_increment_puzzle(self):
        b = stats.increment_puzzle({'puzzles_solved': 4})
        self.assertEqual(b['puzzles_solved'], 5)

    def test_increment_n(self):
        b = stats.increment_catch({'fishing_catches': 10}, n=3)
        self.assertEqual(b['fishing_catches'], 13)

    def test_increment_negative_n_is_noop(self):
        b = stats.increment_catch({'fishing_catches': 10}, n=-4)
        self.assertEqual(b['fishing_catches'], 10)

    def test_add_runtime_accumulates(self):
        d = stats.validate(stats.DEFAULTS)
        d = stats.add_fishing_runtime(d, 1.5)
        d = stats.add_fishing_runtime(d, 2.0)
        self.assertAlmostEqual(d['fishing_runtime_s'], 3.5)

    def test_add_puzzler_runtime(self):
        d = stats.add_puzzler_runtime({'puzzler_runtime_s': 100.0}, 0.25)
        self.assertAlmostEqual(d['puzzler_runtime_s'], 100.25)

    def test_add_negative_runtime_is_noop(self):
        d = stats.add_fishing_runtime({'fishing_runtime_s': 5.0}, -2.0)
        self.assertAlmostEqual(d['fishing_runtime_s'], 5.0)

    def test_increment_on_garbage_starts_from_defaults(self):
        b = stats.increment_catch('not a dict')
        self.assertEqual(b['fishing_catches'], 1)


class TestIO(unittest.TestCase):
    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'stats.json')
            data = stats.validate({'fishing_catches': 7, 'puzzles_solved': 2,
                                   'fishing_runtime_s': 12.5,
                                   'puzzler_runtime_s': 3.0})
            self.assertTrue(stats.save(data, path))
            loaded = stats.load(path)
            self.assertEqual(loaded['fishing_catches'], 7)
            self.assertEqual(loaded['puzzles_solved'], 2)
            self.assertAlmostEqual(loaded['fishing_runtime_s'], 12.5)

    def test_save_is_atomic_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'stats.json')
            stats.save(stats.DEFAULTS, path)
            self.assertFalse(os.path.exists(path + '.tmp'))
            self.assertTrue(os.path.exists(path))

    def test_load_missing_returns_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            loaded = stats.load(os.path.join(d, 'does_not_exist.json'))
            self.assertEqual(loaded['fishing_catches'], 0)

    def test_load_corrupt_returns_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'stats.json')
            with open(path, 'w', encoding='utf-8') as h:
                h.write('{not valid json,,,')
            loaded = stats.load(path)
            self.assertEqual(loaded['puzzles_solved'], 0)

    def test_load_clamps_negative_persisted(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'stats.json')
            with open(path, 'w', encoding='utf-8') as h:
                json.dump({'fishing_catches': -99}, h)
            loaded = stats.load(path)
            self.assertEqual(loaded['fishing_catches'], 0)

    def test_save_to_bad_path_returns_false(self):
        # A directory path that cannot be a file -> save returns False, no raise.
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(stats.save(stats.DEFAULTS, d))


if __name__ == '__main__':
    unittest.main()
