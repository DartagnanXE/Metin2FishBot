# -*- coding: utf-8 -*-
"""Run-1 QA: stats are flushed to disk on EVERY exit path.

Regression guard for the data-integrity gap where accrued runtime (and any
counters bumped within the 2s save-debounce) were lost when the app closed
without a catch/solve firing -- e.g. an idle-but-running session, a close
inside the debounce window, or the hard ``os._exit`` taken for an auto-update.

The fix wires App._on_close / App._hard_exit_for_update -> App._flush_stats ->
a hook that hack.py registers (App._stats_save_hook), which cancels any pending
debounced save and writes stats.json atomically.

App itself is CustomTkinter and not headless-constructible, but the contract is
pure Python: ``_flush_stats`` reads ``self._stats_save_hook`` and calls it,
swallowing every error. We exercise the REAL unbound App._flush_stats against a
lightweight stand-in instance (mirrors the project's fake-app test style in
test_run1_ranking_view.py), and separately verify the end-to-end "flush writes
the latest stats" behaviour against the real stats.save round-trip.

Headless: stdlib unittest only; no Tk widgets are constructed.
"""

import os
import tempfile
import types
import unittest

import stats
from interface.app import App


class TestFlushStatsContract(unittest.TestCase):
    def test_flush_calls_registered_hook(self):
        called = []
        inst = types.SimpleNamespace(_stats_save_hook=lambda: called.append(1))
        App._flush_stats(inst)
        self.assertEqual(called, [1])

    def test_flush_noop_when_hook_unset(self):
        inst = types.SimpleNamespace(_stats_save_hook=None)
        App._flush_stats(inst)            # must not raise
        # Also tolerate the attribute being entirely absent.
        App._flush_stats(types.SimpleNamespace())

    def test_flush_swallows_hook_errors(self):
        def boom():
            raise RuntimeError('exit hook blew up')

        inst = types.SimpleNamespace(_stats_save_hook=boom)
        # Must never propagate -- an exit path can never be blocked by a save.
        App._flush_stats(inst)

    def test_flush_hook_is_not_required_to_be_callable(self):
        inst = types.SimpleNamespace(_stats_save_hook='not callable')
        App._flush_stats(inst)            # must not raise


class TestExitFlushPersists(unittest.TestCase):
    def test_hook_persists_latest_stats_atomically(self):
        # Simulate hack.py's registered flush: it saves app._stats to the path.
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'stats.json')
            live = {'_stats': stats.validate({'fishing_catches': 3,
                                              'fishing_runtime_s': 99.5})}

            def flush_hook():
                stats.save(live['_stats'], path)

            inst = types.SimpleNamespace(_stats_save_hook=flush_hook)

            # Accrue more runtime AFTER the last debounced save would have run...
            live['_stats'] = stats.add_fishing_runtime(live['_stats'], 40.5)
            # ...then the exit path flushes.
            App._flush_stats(inst)

            on_disk = stats.load(path)
            self.assertEqual(on_disk['fishing_catches'], 3)
            self.assertAlmostEqual(on_disk['fishing_runtime_s'], 140.0)
            self.assertFalse(os.path.exists(path + '.tmp'))


if __name__ == '__main__':
    unittest.main()
