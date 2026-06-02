# -*- coding: utf-8 -*-
"""Characterization tests for fishingbot.py cast / minigame / golden-tuna logic.

Pins the CURRENT behaviour of the FishingBot pieces that a behaviour-preserving
refactor (splitting fishingbot.py) must keep byte-stable:

  * ``set_to_begin`` value parsing -- the frozen-key contract: time-limit
    enable/seconds, bait/throw/start timings, golden-tuna action (with the
    defensive fallback to 3), and mount enable/key. ``WindowCapture`` is patched
    out so we test the PURE parsing without a game window.
  * the golden-tuna click geometry table (``GOLDEN_TUNA_Y`` / ``GOLDEN_TUNA_X``)
    -- the three stacked dialog buttons.
  * ``detect_minigame`` -- the clock template match with the > 0.9 confidence
    gate, and the running best-confidence diagnostic.
  * ``_match_template_max`` -- the robust matcher returns (ok, val, loc) and
    never raises on shape/type mismatches.
  * ``_on_cycle_end`` -- the consecutive-no-bite streak counter.

Headless: fishingbot imports cleanly under py.exe; the module-level
``pydirectinput`` / ``WindowCapture`` are monkeypatched so nothing real fires.
The needle/clock template images load from the repo (resource_path), so the
match-based tests run for real where the images are present and self-skip if a
template failed to load.
"""

import unittest
from unittest import mock

import numpy as np

import fishingbot
import mount


def _bare_bot():
    """A FishingBot instance WITHOUT running __init__ (no capture/needle work)."""
    return fishingbot.FishingBot.__new__(fishingbot.FishingBot)


def _values(**over):
    base = {
        '-ENDTIMEP-': False, '-ENDTIME-': '0',
        '-BAITTIME-': 2.0, '-THROWTIME-': 2.0, '-STARTGAME-': 2.0,
        '-GOLDENTUNA-': 3, '-MOUNT-': False, '-MOUNTKEY-': '3',
    }
    base.update(over)
    return base


class _StubCapture:
    """Stands in for WindowCapture so set_to_begin completes without a window."""

    offset_x = 0
    offset_y = 0

    def __init__(self, *_a, **_k):
        pass


class TestSetToBeginParsing(unittest.TestCase):
    """The frozen-key -> bot-field mapping (WindowCapture + click patched out)."""

    def _begin(self, values):
        bot = _bare_bot()
        with mock.patch.object(fishingbot, 'WindowCapture', _StubCapture), \
                mock.patch.object(fishingbot, 'pydirectinput', mock.Mock()):
            bot.set_to_begin(values)
        return bot

    def test_timings_assigned(self):
        bot = self._begin(_values(**{'-BAITTIME-': 1.5, '-THROWTIME-': 2.5,
                                     '-STARTGAME-': 3.5}))
        self.assertEqual(bot.bait_time, 1.5)
        self.assertEqual(bot.throw_time, 2.5)
        self.assertEqual(bot.game_time, 3.5)

    def test_time_limit_enabled_converts_minutes_to_seconds(self):
        bot = self._begin(_values(**{'-ENDTIMEP-': True, '-ENDTIME-': '5'}))
        self.assertTrue(bot.end_time_enable)
        self.assertEqual(bot.end_time, 300)

    def test_time_limit_disabled_resets(self):
        bot = self._begin(_values(**{'-ENDTIMEP-': False, '-ENDTIME-': '5'}))
        self.assertFalse(bot.end_time_enable)
        self.assertEqual(bot.end_time, 0)

    def test_time_limit_enabled_but_zero_minutes_stays_disabled(self):
        # Checked on, field "0" -> must NOT enable (else it would stop instantly).
        bot = self._begin(_values(**{'-ENDTIMEP-': True, '-ENDTIME-': '0'}))
        self.assertFalse(bot.end_time_enable)
        self.assertEqual(bot.end_time, 0)

    def test_time_limit_garbage_minutes_safe(self):
        bot = self._begin(_values(**{'-ENDTIMEP-': True, '-ENDTIME-': 'abc'}))
        self.assertFalse(bot.end_time_enable)
        self.assertEqual(bot.end_time, 0)

    def test_golden_tuna_valid_kept(self):
        for action in (1, 2, 3):
            bot = self._begin(_values(**{'-GOLDENTUNA-': action}))
            self.assertEqual(bot.golden_tuna_action, action)

    def test_golden_tuna_invalid_falls_back_to_three(self):
        for bad in (0, 4, 9, 'x', None):
            bot = self._begin(_values(**{'-GOLDENTUNA-': bad}))
            self.assertEqual(bot.golden_tuna_action, 3)

    def test_mount_parsed(self):
        bot = self._begin(_values(**{'-MOUNT-': True, '-MOUNTKEY-': 'r'}))
        self.assertTrue(bot.mount_enabled)
        self.assertEqual(bot.mount_key, 'r')

    def test_mount_default_off_and_key_three(self):
        bot = self._begin(_values())
        self.assertFalse(bot.mount_enabled)
        self.assertEqual(bot.mount_key, '3')

    def test_mount_empty_key_falls_back_to_three(self):
        bot = self._begin(_values(**{'-MOUNTKEY-': ''}))
        self.assertEqual(bot.mount_key, '3')

    def test_state_reset_to_zero(self):
        bot = self._begin(_values())
        self.assertEqual(bot.state, 0)


class TestGoldenTunaGeometry(unittest.TestCase):
    """The three stacked golden-tuna dialog buttons (evenly DY-spaced)."""

    def test_x_and_dy_constants(self):
        self.assertEqual(fishingbot.FishingBot.GOLDEN_TUNA_X, 350)
        self.assertEqual(fishingbot.FishingBot.GOLDEN_TUNA_DY, 38)

    def test_y_table_is_stacked_around_280(self):
        y = fishingbot.FishingBot.GOLDEN_TUNA_Y
        self.assertEqual(y[1], 242)   # top   (280 - 38)
        self.assertEqual(y[2], 280)   # middle (original click)
        self.assertEqual(y[3], 318)   # bottom (280 + 38)

    def test_fields_are_evenly_spaced(self):
        y = fishingbot.FishingBot.GOLDEN_TUNA_Y
        self.assertEqual(y[2] - y[1], fishingbot.FishingBot.GOLDEN_TUNA_DY)
        self.assertEqual(y[3] - y[2], fishingbot.FishingBot.GOLDEN_TUNA_DY)


class TestMatchTemplateMax(unittest.TestCase):
    """The robust matcher -- exact match high, mismatch never raises."""

    def test_identical_images_match_high(self):
        img = np.zeros((20, 20, 3), dtype=np.uint8)
        img[5:15, 5:15] = 200
        ok, val, _loc = fishingbot._match_template_max(img, img.copy())
        self.assertTrue(ok)
        self.assertGreater(val, 0.99)

    def test_none_inputs_safe(self):
        self.assertEqual(fishingbot._match_template_max(None, None),
                         (False, 0.0, (0, 0)))

    def test_template_larger_than_image_not_ok(self):
        small = np.zeros((4, 4, 3), dtype=np.uint8)
        big = np.zeros((10, 10, 3), dtype=np.uint8)
        ok, _val, _loc = fishingbot._match_template_max(small, big)
        self.assertFalse(ok)

    def test_grayscale_haystack_coerced_not_raise(self):
        # 2-D haystack is up-converted to BGR; must not raise.
        gray = np.zeros((20, 20), dtype=np.uint8)
        needle = np.zeros((5, 5, 3), dtype=np.uint8)
        ok, _val, _loc = fishingbot._match_template_max(gray, needle)
        self.assertIn(ok, (True, False))   # no exception is the point


class TestDetectMinigame(unittest.TestCase):
    """The clock-template gate (> 0.9) + the best-confidence diagnostic."""

    @classmethod
    def setUpClass(cls):
        cls.bot = fishingbot.FishingBot()
        cls.clock = cls.bot.needle_img_clock

    def setUp(self):
        if self.clock is None:
            self.skipTest('clock template image did not load')
        self.bot._best_minigame_conf = 0.0

    def test_exact_clock_detected(self):
        self.assertTrue(self.bot.detect_minigame(self.clock.copy()))

    def test_black_frame_not_detected(self):
        black = np.zeros_like(self.clock)
        self.assertFalse(self.bot.detect_minigame(black))

    def test_best_confidence_tracks_high_on_match(self):
        self.bot.detect_minigame(self.clock.copy())
        self.assertGreater(self.bot._best_minigame_conf, 0.9)


class TestCycleEndStreak(unittest.TestCase):
    """Consecutive-no-bite counter: increments on a dry cycle, resets on a bite."""

    def _bot(self):
        bot = _bare_bot()
        bot._casts_without_bite = 0
        bot._bite_seen_this_cycle = False
        bot._best_minigame_conf = 0.0
        return bot

    def test_no_bite_increments_streak(self):
        bot = self._bot()
        bot._on_cycle_end()
        self.assertEqual(bot._casts_without_bite, 1)
        bot._on_cycle_end()
        self.assertEqual(bot._casts_without_bite, 2)

    def test_bite_resets_streak(self):
        bot = self._bot()
        bot._on_cycle_end()
        self.assertEqual(bot._casts_without_bite, 1)
        bot._bite_seen_this_cycle = True
        bot._on_cycle_end()
        self.assertEqual(bot._casts_without_bite, 0)

    def test_cycle_end_clears_per_cycle_flags(self):
        bot = self._bot()
        bot._bite_seen_this_cycle = True
        bot._best_minigame_conf = 0.95
        bot._on_cycle_end()
        # Both per-cycle markers are reset for the next round.
        self.assertFalse(bot._bite_seen_this_cycle)
        self.assertEqual(bot._best_minigame_conf, 0.0)


class TestFireOnCatch(unittest.TestCase):
    """The optional catch counter-hook fires exactly once, and never raises."""

    def test_hook_called_once(self):
        bot = _bare_bot()
        calls = []
        bot.on_catch = lambda: calls.append(1)
        bot._fire_on_catch()
        self.assertEqual(calls, [1])

    def test_no_hook_is_safe(self):
        bot = _bare_bot()
        bot.on_catch = None
        bot._fire_on_catch()   # must not raise

    def test_hook_exception_swallowed(self):
        bot = _bare_bot()
        bot.on_catch = lambda: (_ for _ in ()).throw(RuntimeError('boom'))
        bot._fire_on_catch()   # must not propagate


if __name__ == '__main__':
    unittest.main()
