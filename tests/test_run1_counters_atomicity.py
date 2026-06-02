# -*- coding: utf-8 -*-
"""Run-1 QA: counters -- increment + persistence + ATOMICITY (stats.py).

tests/test_stats.py covers the immutable-increment basics + a happy-path
round-trip. This file hardens the parts a leaderboard cannot afford to get
wrong:

  * INCREMENT semantics accumulate correctly across many ops and stay immutable
    (the caller pattern: load -> increment -> save, repeated).
  * PERSISTENCE survives repeated save/load cycles with no drift, including
    floats, and a real "live session" simulation (catch hook + runtime adder).
  * ATOMICITY: a crash *during* serialization (json.dumps raising) must leave
    the PRE-EXISTING stats.json intact and untouched, and must NOT leave a
    dangling ``.tmp`` -- os.replace is never reached, the temp is cleaned up.
  * Concurrency: many threads each doing load->increment->save never corrupt
    the file (it always reloads as valid stats); the final increment count is
    bounded by the inherent read-modify-write race but the file is never broken.
  * save() returns a real bool and never raises on a bad destination.

Pure stdlib (json/os/threading/tempfile). Headless.
"""

import json
import os
import tempfile
import threading
import unittest
from unittest import mock

import stats


class TestIncrementAccumulation(unittest.TestCase):
    def test_many_increments_accumulate(self):
        s = stats.validate(stats.DEFAULTS)
        for _ in range(50):
            s = stats.increment_catch(s)
        self.assertEqual(s['fishing_catches'], 50)

    def test_mixed_counters_independent(self):
        s = stats.validate(stats.DEFAULTS)
        s = stats.increment_catch(s, 3)
        s = stats.increment_puzzle(s, 2)
        s = stats.add_fishing_runtime(s, 10.0)
        s = stats.add_puzzler_runtime(s, 4.0)
        self.assertEqual(s['fishing_catches'], 3)
        self.assertEqual(s['puzzles_solved'], 2)
        self.assertAlmostEqual(s['fishing_runtime_s'], 10.0)
        self.assertAlmostEqual(s['puzzler_runtime_s'], 4.0)

    def test_increment_does_not_mutate_source(self):
        a = stats.validate({'fishing_catches': 7})
        b = stats.increment_catch(a)
        self.assertEqual(a['fishing_catches'], 7)
        self.assertEqual(b['fishing_catches'], 8)
        self.assertIsNot(a, b)


class TestPersistenceDurability(unittest.TestCase):
    def test_repeated_cycles_no_drift(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'stats.json')
            s = stats.validate(stats.DEFAULTS)
            for i in range(20):
                s = stats.increment_catch(s)
                s = stats.add_fishing_runtime(s, 1.5)
                self.assertTrue(stats.save(s, path))
                s = stats.load(path)            # reload each cycle
            self.assertEqual(s['fishing_catches'], 20)
            self.assertAlmostEqual(s['fishing_runtime_s'], 30.0)

    def test_live_session_simulation(self):
        # Mirrors the bot: an on_catch hook bumps catches; a periodic adder
        # accumulates runtime; everything is persisted and reloads identically.
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'stats.json')
            stats.save(stats.DEFAULTS, path)

            def on_catch():
                cur = stats.load(path)
                stats.save(stats.increment_catch(cur), path)

            for _ in range(5):
                on_catch()
            cur = stats.load(path)
            stats.save(stats.add_fishing_runtime(cur, 123.5), path)

            final = stats.load(path)
            self.assertEqual(final['fishing_catches'], 5)
            self.assertAlmostEqual(final['fishing_runtime_s'], 123.5)

    def test_float_precision_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'stats.json')
            stats.save(stats.add_fishing_runtime(
                stats.DEFAULTS, 0.1 + 0.2), path)
            self.assertAlmostEqual(stats.load(path)['fishing_runtime_s'], 0.3)

    def test_version_stamped_on_save(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'stats.json')
            stats.save({'fishing_catches': 1}, path)
            with open(path, encoding='utf-8') as h:
                raw = json.load(h)
            self.assertEqual(raw['version'], stats.STATS_VERSION)


class TestAtomicity(unittest.TestCase):
    def test_tmp_file_removed_on_success(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'stats.json')
            self.assertTrue(stats.save(stats.DEFAULTS, path))
            self.assertTrue(os.path.exists(path))
            self.assertFalse(os.path.exists(path + '.tmp'))

    def test_crash_during_serialize_keeps_old_file_intact(self):
        # Write a known-good file first, then make json.dumps raise on the next
        # save -> the original must survive byte-for-byte and no .tmp remain.
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'stats.json')
            good = stats.validate({'fishing_catches': 42,
                                   'puzzles_solved': 7})
            self.assertTrue(stats.save(good, path))
            before = open(path, encoding='utf-8').read()

            with mock.patch('stats.json.dumps',
                            side_effect=RuntimeError('disk full simulation')):
                ok = stats.save({'fishing_catches': 999}, path)
            self.assertFalse(ok)                      # reported failure
            after = open(path, encoding='utf-8').read()
            self.assertEqual(before, after)           # original untouched
            self.assertFalse(os.path.exists(path + '.tmp'))   # temp cleaned up
            # And it still loads as the old, good value.
            self.assertEqual(stats.load(path)['fishing_catches'], 42)

    def test_replace_failure_cleans_tmp(self):
        # If os.replace fails (e.g. cross-device), save returns False and removes
        # the temp it created rather than leaving a stray file behind.
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'stats.json')
            with mock.patch('stats.os.replace',
                            side_effect=OSError('EXDEV')):
                ok = stats.save(stats.DEFAULTS, path)
            self.assertFalse(ok)
            self.assertFalse(os.path.exists(path + '.tmp'))

    def test_save_to_directory_path_returns_false(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(stats.save(stats.DEFAULTS, d))


class TestConcurrentWriters(unittest.TestCase):
    def test_parallel_save_load_never_corrupts(self):
        # 12 threads hammering load->increment->save. We guard the
        # read-modify-write with a lock (mirrors production, where stats are only
        # ever mutated on the single Tk GUI thread) so the final count is
        # DETERMINISTIC -- every one of the 300 increments must survive. This
        # still exercises concurrent atomic save()/os.replace heavily (the part
        # that must never corrupt the file or leave a stray .tmp). The previous
        # lock-free version's >=1 lower bound was race-prone and could flake red.
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'stats.json')
            stats.save(stats.DEFAULTS, path)
            errors = []
            rmw_lock = threading.Lock()
            n_threads, per_thread = 12, 25

            def worker():
                try:
                    for _ in range(per_thread):
                        with rmw_lock:
                            cur = stats.load(path)
                            self.assertTrue(
                                stats.save(stats.increment_catch(cur), path))
                except Exception as exc:   # pragma: no cover - failure path
                    errors.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(n_threads)]
            for th in threads:
                th.start()
            for th in threads:
                th.join()

            self.assertEqual(errors, [])
            final = stats.load(path)                  # must parse cleanly
            self.assertIn('fishing_catches', final)
            # Deterministic: no update may be lost under the serialised RMW.
            self.assertEqual(final['fishing_catches'], n_threads * per_thread)
            self.assertFalse(os.path.exists(path + '.tmp'))

    def test_concurrent_distinct_saves_never_leave_tmp(self):
        # Lock-FREE concurrency stress on save() itself (distinct values, so no
        # read-modify-write to lose): the destination must always parse and no
        # per-call temp file may ever survive, proving the unique-tmp + atomic
        # os.replace path is concurrency-safe.
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'stats.json')
            stats.save(stats.DEFAULTS, path)
            errors = []

            def worker(base):
                try:
                    for i in range(25):
                        self.assertTrue(
                            stats.save({'fishing_catches': base + i}, path))
                except Exception as exc:   # pragma: no cover
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(b * 100,))
                       for b in range(12)]
            for th in threads:
                th.start()
            for th in threads:
                th.join()

            self.assertEqual(errors, [])
            # File parses cleanly and no stray temp from any of the 300 saves.
            with open(path, encoding='utf-8') as h:
                json.load(h)
            leftovers = [f for f in os.listdir(d) if f.endswith('.tmp')]
            self.assertEqual(leftovers, [])

    def test_file_always_parseable_after_writes(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'stats.json')
            for i in range(30):
                stats.save({'fishing_catches': i}, path)
                with open(path, encoding='utf-8') as h:
                    json.load(h)   # raises if ever truncated -> test fails


if __name__ == '__main__':
    unittest.main()
