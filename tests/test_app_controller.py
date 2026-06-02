# -*- coding: utf-8 -*-
"""Characterization tests for interface/app.py controller + pure helpers.

These pin CURRENT behaviour of the parts of app.py about to be split out (the
``BotController`` run-control + config plumbing, and the module-level pure
helpers) so a behaviour-preserving refactor is caught the moment it drifts.

``BotController`` is exercised with a tiny FAKE app (a plain object exposing
only the handful of methods the controller calls: ``after`` / ``after_cancel``
/ ``sync_controls`` / ``flash_saved`` / ``_apply_preferred_hwnd`` /
``_clear_preferred_hwnd`` / ``notify_start_failed``) and FAKE bots -- so NO Tk
root is created and the tests stay headless. The module-level helpers
(``_hms`` / ``_mmss`` / ``_is_no_window_error`` / ``_probe_game`` /
``_game_window_present`` / ``_solver_pairs`` / ``_detection_pairs``) are pure
and tested directly.

importing interface.app pulls customtkinter; on the project's py.exe that is
present. If it is somehow unavailable the whole module skips (it never builds a
window, but the import alone needs the package).
"""

import unittest
from unittest import mock

try:
    import interface.app as app
    _IMPORT_OK = True
    _IMPORT_ERR = ''
except Exception as exc:  # pragma: no cover - depends on environment
    _IMPORT_OK = False
    _IMPORT_ERR = repr(exc)

from interface import config as cfgmod


class _FakeApp:
    """Minimal stand-in for the App that BotController talks back to.

    Records the side-effecting calls so the controller's run-control wiring can
    be asserted without a real Tk window. ``after`` returns a sentinel job and
    runs nothing (the debounced save is observed via the save COUNT on cfgmod,
    not by firing the timer)."""

    def __init__(self):
        self.synced = 0
        self.saved_flashed = 0
        self.apply_pref = 0
        self.clear_pref = 0
        self.start_failed = None      # set to the no_window bool on failure

    def after(self, _ms, _fn):
        return 'job-sentinel'

    def after_cancel(self, _job):
        pass

    def sync_controls(self):
        self.synced += 1

    def flash_saved(self):
        self.saved_flashed += 1

    def _apply_preferred_hwnd(self):
        self.apply_pref += 1

    def _clear_preferred_hwnd(self):
        self.clear_pref += 1

    def notify_start_failed(self, no_window):
        self.start_failed = bool(no_window)


class _FakeBot:
    """Records set_to_begin + the botting flag the controller flips."""

    def __init__(self):
        self.botting = False
        self.began_with = None

    def set_to_begin(self, values):
        self.began_with = values


def _controller(cfg=None):
    cfg = cfg if cfg is not None else cfgmod.validate(cfgmod.DEFAULTS)
    fapp = _FakeApp()
    fish = _FakeBot()
    puzzle = _FakeBot()
    return app.BotController(fapp, fish, puzzle, cfg), fapp, fish, puzzle


@unittest.skipUnless(_IMPORT_OK, 'interface.app not importable: ' + _IMPORT_ERR)
class TestHelpersFormatting(unittest.TestCase):
    def test_hms_basic(self):
        self.assertEqual(app._hms(0), '00:00:00')
        self.assertEqual(app._hms(3661), '01:01:01')
        self.assertEqual(app._hms(36000), '10:00:00')

    def test_hms_clamps_negative(self):
        self.assertEqual(app._hms(-5), '00:00:00')

    def test_hms_truncates_float(self):
        self.assertEqual(app._hms(59.9), '00:00:59')

    def test_mmss_basic(self):
        self.assertEqual(app._mmss(0), '00:00')
        self.assertEqual(app._mmss(125), '02:05')

    def test_mmss_clamps_negative(self):
        self.assertEqual(app._mmss(-9), '00:00')

    def test_mmss_large_minutes_not_wrapped_to_hours(self):
        # 90 min -> '90:00' (mm:ss has no hour rollover).
        self.assertEqual(app._mmss(90 * 60), '90:00')


@unittest.skipUnless(_IMPORT_OK, 'interface.app not importable: ' + _IMPORT_ERR)
class TestNoWindowDetection(unittest.TestCase):
    def test_german_message_is_no_window(self):
        self.assertTrue(app._is_no_window_error(Exception('Fenster nicht gefunden')))

    def test_english_message_is_no_window(self):
        self.assertTrue(app._is_no_window_error(Exception('Window not found')))

    def test_other_message_is_not_no_window(self):
        self.assertFalse(app._is_no_window_error(Exception('boom')))


@unittest.skipUnless(_IMPORT_OK, 'interface.app not importable: ' + _IMPORT_ERR)
class TestProbeGameHeadless(unittest.TestCase):
    """Off-game / headless, the probe must report 'nothing there' and never raise."""

    def test_probe_returns_all_empty_tuple(self):
        result = app._probe_game()
        # Without the game window (and possibly without win32), the contract is
        # the five-tuple (present, hwnd, w, h, healthy) all falsy.
        self.assertEqual(result, (False, None, 0, 0, False))

    def test_game_window_present_is_false(self):
        self.assertFalse(app._game_window_present())


@unittest.skipUnless(_IMPORT_OK, 'interface.app not importable: ' + _IMPORT_ERR)
class TestLivePairs(unittest.TestCase):
    """The solver/detection (value, label) pairs reflect the config enums and
    are translated live (value side stable, label side a non-empty string)."""

    def tearDown(self):
        from i18n import set_lang
        set_lang('en')

    def test_solver_pairs_values(self):
        values = [v for v, _label in app._solver_pairs()]
        self.assertEqual(values, list(cfgmod.SOLVER_MODES))

    def test_detection_pairs_values(self):
        values = [v for v, _label in app._detection_pairs()]
        self.assertEqual(values, list(cfgmod.DETECTION_MODES))

    def test_pairs_have_nonempty_labels(self):
        for _v, label in app._solver_pairs() + app._detection_pairs():
            self.assertTrue(str(label).strip())

    def test_detection_internal_mark_value_stable_across_lang(self):
        # The INTERNAL enum value stays 'mark' regardless of UI language even
        # though the visible label switches (Manual/Manuell).
        from i18n import set_lang
        set_lang('de')
        self.assertIn('mark', [v for v, _ in app._detection_pairs()])
        set_lang('en')
        self.assertIn('mark', [v for v, _ in app._detection_pairs()])


@unittest.skipUnless(_IMPORT_OK, 'interface.app not importable: ' + _IMPORT_ERR)
class TestControllerConstruction(unittest.TestCase):
    def test_initial_state_from_config(self):
        cfg = cfgmod.validate({'mode': 'puzzle'})
        ctrl, _fapp, _f, _p = _controller(cfg)
        self.assertEqual(ctrl.mode, 'puzzle')
        self.assertFalse(ctrl.running)

    def test_current_config_is_validated_copy(self):
        ctrl, _fapp, _f, _p = _controller()
        cfg = ctrl.current_config()
        self.assertIn('fishing', cfg)
        self.assertIn('puzzle', cfg)


@unittest.skipUnless(_IMPORT_OK, 'interface.app not importable: ' + _IMPORT_ERR)
class TestControllerConfigWrites(unittest.TestCase):
    def test_update_config_clamps_and_returns_new_cfg(self):
        ctrl, _fapp, _f, _p = _controller()
        ret = ctrl.update_config('fishing', 'bait_time', 99)
        # 99 is clamped to the delay max; the returned cfg carries it.
        self.assertEqual(ret['fishing']['bait_time'], cfgmod.DELAY_MAX)
        self.assertEqual(
            ctrl.current_config()['fishing']['bait_time'], cfgmod.DELAY_MAX)

    def test_update_config_does_not_mutate_prior_snapshot(self):
        ctrl, _fapp, _f, _p = _controller()
        before = ctrl.current_config()
        ctrl.update_config('fishing', 'bait_time', 7.0)
        # The earlier snapshot stays at the default (immutable update).
        self.assertEqual(before['fishing']['bait_time'], 2.0)

    def test_collect_values_reflects_updates(self):
        ctrl, _fapp, _f, _p = _controller()
        ctrl.update_config('fishing', 'bait_time', 5.0)
        self.assertEqual(ctrl.collect_values()['-BAITTIME-'], 5.0)

    def test_update_username_strips_and_caps(self):
        ctrl, _fapp, _f, _p = _controller()
        ret = ctrl.update_username('  Bob123  ')
        self.assertEqual(ret['username'], 'Bob123')

    def test_set_language_persists_in_config(self):
        ctrl, _fapp, _f, _p = _controller()
        ctrl.set_language('de')
        self.assertEqual(ctrl.current_config()['language'], 'de')


@unittest.skipUnless(_IMPORT_OK, 'interface.app not importable: ' + _IMPORT_ERR)
class TestControllerModeSwitch(unittest.TestCase):
    def test_set_mode_while_idle_changes_mode(self):
        ctrl, _fapp, _f, _p = _controller()
        ctrl.set_mode('puzzle')
        self.assertEqual(ctrl.mode, 'puzzle')
        self.assertEqual(ctrl.current_config()['mode'], 'puzzle')

    def test_set_mode_while_running_is_ignored(self):
        ctrl, _fapp, _f, _p = _controller()
        ctrl.running = True
        ctrl.set_mode('puzzle')
        self.assertEqual(ctrl.mode, 'fishing')   # unchanged

    def test_set_mode_invalid_value_ignored(self):
        ctrl, _fapp, _f, _p = _controller()
        ctrl.set_mode('zzz')
        self.assertEqual(ctrl.mode, 'fishing')


@unittest.skipUnless(_IMPORT_OK, 'interface.app not importable: ' + _IMPORT_ERR)
class TestControllerStartStop(unittest.TestCase):
    def test_start_uses_on_start_hook_when_set(self):
        ctrl, fapp, _f, _p = _controller()
        order = []
        ctrl.on_start = lambda: order.append('start')
        ctrl.on_start_stop()
        self.assertTrue(ctrl.running)
        self.assertEqual(order, ['start'])
        # Preferred-hwnd is applied before start, controls synced after.
        self.assertEqual(fapp.apply_pref, 1)
        self.assertGreaterEqual(fapp.synced, 1)

    def test_stop_uses_on_stop_hook_and_clears_pref(self):
        ctrl, fapp, _f, _p = _controller()
        order = []
        ctrl.on_start = lambda: order.append('start')
        ctrl.on_stop = lambda: order.append('stop')
        ctrl.on_start_stop()           # start
        ctrl.on_start_stop()           # stop
        self.assertFalse(ctrl.running)
        self.assertEqual(order, ['start', 'stop'])
        self.assertEqual(fapp.clear_pref, 1)

    def test_fallback_start_fishing_sets_botting_and_begins(self):
        ctrl, _fapp, fish, puzzle = _controller(cfgmod.validate({'mode': 'fishing'}))
        ctrl.on_start_stop()           # no on_start hook -> fallback
        self.assertTrue(fish.botting)
        self.assertFalse(puzzle.botting)
        self.assertIsNotNone(fish.began_with)
        # The values handed to the bot are the frozen-key values dict.
        self.assertIn('-BAITTIME-', fish.began_with)

    def test_fallback_start_puzzle_sets_botting(self):
        ctrl, _fapp, fish, puzzle = _controller(cfgmod.validate({'mode': 'puzzle'}))
        ctrl.on_start_stop()
        self.assertTrue(puzzle.botting)
        self.assertFalse(fish.botting)
        self.assertIsNotNone(puzzle.began_with)

    def test_set_running_false_clears_both_bots(self):
        ctrl, _fapp, fish, puzzle = _controller()
        fish.botting = puzzle.botting = True
        ctrl.set_running(False)
        self.assertFalse(fish.botting)
        self.assertFalse(puzzle.botting)
        self.assertFalse(ctrl.running)

    def test_start_failure_reports_no_window(self):
        # on_start raising a 'not found' error must: leave the bot stopped and
        # notify the app with no_window=True (the friendly path, no traceback).
        ctrl, fapp, _f, _p = _controller()
        ctrl.on_start = lambda: (_ for _ in ()).throw(
            RuntimeError('Window not found'))
        ctrl.on_start_stop()
        self.assertFalse(ctrl.running)
        self.assertIs(fapp.start_failed, True)

    def test_start_failure_generic_error_reports_not_no_window(self):
        ctrl, fapp, _f, _p = _controller()
        ctrl.on_start = lambda: (_ for _ in ()).throw(RuntimeError('boom'))
        ctrl.on_start_stop()
        self.assertFalse(ctrl.running)
        self.assertIs(fapp.start_failed, False)


@unittest.skipUnless(_IMPORT_OK, 'interface.app not importable: ' + _IMPORT_ERR)
class TestControllerReset(unittest.TestCase):
    # reset_to_defaults calls cfgmod.save() with the DEFAULT path synchronously;
    # patch it to a no-op so the suite never overwrites the real config.json in
    # the project root. (The debounced _do_save path is already inert here: the
    # FakeApp.after never fires the timer.)
    def setUp(self):
        self._save_patch = mock.patch.object(cfgmod, 'save', return_value=True)
        self._save_patch.start()

    def tearDown(self):
        self._save_patch.stop()

    def test_reset_while_running_returns_false_and_noop(self):
        ctrl, _fapp, _f, _p = _controller()
        ctrl.update_config('fishing', 'bait_time', 7.0)
        ctrl.running = True
        self.assertFalse(ctrl.reset_to_defaults())
        # Still the changed value -- no reset happened.
        self.assertEqual(ctrl.current_config()['fishing']['bait_time'], 7.0)

    def test_reset_while_idle_restores_defaults(self):
        ctrl, _fapp, _f, _p = _controller()
        ctrl.update_config('fishing', 'bait_time', 7.0)
        ctrl.update_config('puzzle', 'solver_mode', 'trained')
        self.assertTrue(ctrl.reset_to_defaults())
        cfg = ctrl.current_config()
        self.assertEqual(cfg['fishing']['bait_time'], 2.0)
        self.assertEqual(cfg['puzzle']['solver_mode'], 'standard')
        self.assertEqual(ctrl.mode, cfgmod.DEFAULTS['mode'])


if __name__ == '__main__':
    unittest.main()
