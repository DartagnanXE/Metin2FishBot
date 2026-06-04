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
        '-WHITELIST-': False, '-BAITREFILL-': False,
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

    def test_whitelist_default_off(self):
        bot = self._begin(_values())
        self.assertFalse(bot.whitelist_enabled)
        # Per-cycle decision flag starts fresh.
        self.assertFalse(bot._whitelist_decided)

    def test_whitelist_enabled_parsed(self):
        bot = self._begin(_values(**{'-WHITELIST-': True}))
        self.assertTrue(bot.whitelist_enabled)

    def test_bait_refill_default_off(self):
        bot = self._begin(_values())
        self.assertFalse(bot.bait_refill_enabled)
        # Drossel startet frisch (erste Pruefung sofort).
        self.assertEqual(bot._last_bait_check, 0.0)

    def test_bait_refill_enabled_parsed(self):
        bot = self._begin(_values(**{'-BAITREFILL-': True}))
        self.assertTrue(bot.bait_refill_enabled)

    def test_state_reset_to_zero(self):
        bot = self._begin(_values())
        self.assertEqual(bot.state, 0)


class TestGoldenTunaGeometry(unittest.TestCase):
    """The three stacked golden-tuna dialog buttons (evenly DY-spaced).

    The bot clicks in CLIENT coordinates (wincap.offset = client origin). The
    buttons were measured on the 802x632 FULL-FRAME shots (client + ~31px
    titlebar + 1px border): X=400, Y={Release:268, Slice:300, Bait:332} (DY=32),
    confirm-OK (400,277). Converted to CLIENT = full-frame - (1, 31):
    X=399, Y={237, 269, 301} (DY unchanged), confirm-OK (399, 246).
    """

    def test_x_and_dy_constants(self):
        # X = 400 (full-frame) - 1 = 399; DY is a relative spacing (unchanged).
        self.assertEqual(fishingbot.FishingBot.GOLDEN_TUNA_X, 399)
        self.assertEqual(fishingbot.FishingBot.GOLDEN_TUNA_DY, 32)

    def test_y_table_is_stacked_around_269(self):
        # Full-frame {268,300,332} - 31 -> client {237,269,301}.
        y = fishingbot.FishingBot.GOLDEN_TUNA_Y
        self.assertEqual(y[1], 237)   # top    (269 - 32)  Freilassen
        self.assertEqual(y[2], 269)   # middle (269)       Aufschneiden
        self.assertEqual(y[3], 301)   # bottom (269 + 32)  Als Koeder benutzen

    def test_fields_are_evenly_spaced(self):
        y = fishingbot.FishingBot.GOLDEN_TUNA_Y
        self.assertEqual(y[2] - y[1], fishingbot.FishingBot.GOLDEN_TUNA_DY)
        self.assertEqual(y[3] - y[2], fishingbot.FishingBot.GOLDEN_TUNA_DY)

    def test_confirm_ok_position(self):
        # (400, 277) full-frame - (1, 31) -> (399, 246) client.
        self.assertEqual(fishingbot.FishingBot.GOLDEN_TUNA_CONFIRM, (399, 246))


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


class TestWhitelistDecision(unittest.TestCase):
    """``_apply_whitelist`` aborts unwanted catches / nibbles and keeps the rest.

    ``fishing_chat.read_hook`` is patched so we control exactly WHAT hangs on the
    hook; ``_abort_minigame`` is checked end-to-end (ESC keypress + state reset,
    NO click). The decision logic itself lives in ``fishing_whitelist`` (pure).
    """

    def _bot(self, enabled=True, states=None):
        bot = _bare_bot()
        bot.whitelist_enabled = enabled
        bot.whitelist_states = states or {}
        bot._whitelist_decided = False
        bot._bite_seen_this_cycle = False
        bot._casts_without_bite = 0
        bot._best_minigame_conf = 0.0
        bot.state = 3
        bot.wincap = _StubCapture()
        return bot

    def _hook(self, **kw):
        import fishing_chat as fc
        defaults = dict(kind=fc.FISH, name='Lachs', confident=True)
        defaults.update(kw)
        return fc.HookResult(**defaults)

    def _run(self, bot, hook):
        clicks, keys = [], []
        fake = mock.Mock()
        fake.click.side_effect = lambda **k: clicks.append(k)
        fake.keyDown.side_effect = lambda k: keys.append(k)
        with mock.patch.object(fishingbot, 'pydirectinput', fake), \
                mock.patch('fishing_chat.read_hook', return_value=hook):
            aborted = bot._apply_whitelist(object())   # screenshot ignored (patched)
        self._last_keys = keys      # ESC-Pruefung ohne die (aborted, clicks)-Signatur
        return aborted, clicks

    def test_unwanted_fish_aborts_and_resets_state(self):
        import fishing_chat as fc
        from interface import inventory_manage as im
        bot = self._bot(states={'Lachs': im.REMOVE})
        aborted, clicks = self._run(bot, self._hook(kind=fc.FISH, name='Lachs'))
        self.assertTrue(aborted)
        self.assertEqual(bot.state, 0)              # back to recast
        self.assertEqual(clicks, [])                # NO click (legacy coord removed)
        self.assertIn('esc', self._last_keys)       # ESC presses the abort instead
        # The abort ENDS the cycle (_on_cycle_end), which clears the per-cycle
        # decision flag so the NEXT cast re-evaluates from scratch.
        self.assertFalse(bot._whitelist_decided)

    def test_wanted_keep_fish_keeps_playing(self):
        import fishing_chat as fc
        from interface import inventory_manage as im
        bot = self._bot(states={'Lachs': im.KEEP})
        aborted, clicks = self._run(bot, self._hook(kind=fc.FISH, name='Lachs'))
        self.assertFalse(aborted)
        self.assertEqual(bot.state, 3)              # still in the minigame
        self.assertEqual(clicks, [])

    def test_campfire_fish_keeps_playing(self):
        import fishing_chat as fc
        from interface import inventory_manage as im
        bot = self._bot(states={'Lachs': im.CAMPFIRE})
        aborted, _ = self._run(bot, self._hook(kind=fc.FISH, name='Lachs'))
        self.assertFalse(aborted)

    def test_niete_aborts(self):
        import fishing_chat as fc
        bot = self._bot(states={})
        aborted, clicks = self._run(bot, self._hook(kind=fc.NIETE, name=None,
                                                    confident=False))
        self.assertTrue(aborted)
        self.assertEqual(bot.state, 0)

    def test_unknown_name_never_aborts(self):
        import fishing_chat as fc
        from interface import inventory_manage as im
        # Bite recognised but name unsure -> NEVER abort a possibly-wanted fish,
        # even if every known fish were marked REMOVE.
        bot = self._bot(states={'Lachs': im.REMOVE, 'Zander': im.REMOVE})
        aborted, _ = self._run(bot, self._hook(kind=fc.FISH, name=fc.UNKNOWN,
                                               confident=False))
        self.assertFalse(aborted)

    def test_unmapped_fish_defaults_to_keep(self):
        import fishing_chat as fc
        # A confident fish not present in the states map = KEEP (fish on).
        bot = self._bot(states={'Zander': 1})
        aborted, _ = self._run(bot, self._hook(kind=fc.FISH, name='Lachs'))
        self.assertFalse(aborted)

    def test_disabled_whitelist_is_noop(self):
        import fishing_chat as fc
        from interface import inventory_manage as im
        bot = self._bot(enabled=False, states={'Lachs': im.REMOVE})
        aborted, clicks = self._run(bot, self._hook(kind=fc.FISH, name='Lachs'))
        self.assertFalse(aborted)
        self.assertEqual(clicks, [])

    def test_none_kind_does_not_decide(self):
        import fishing_chat as fc
        # Nothing solid on the hook yet -> keep reading (do NOT lock the round).
        bot = self._bot(states={})
        aborted, _ = self._run(bot, self._hook(kind=fc.NONE, name=None,
                                               confident=False))
        self.assertFalse(aborted)
        self.assertFalse(bot._whitelist_decided)

    def test_decides_only_once_per_cycle(self):
        import fishing_chat as fc
        from interface import inventory_manage as im
        bot = self._bot(states={'Lachs': im.KEEP})
        # First read: wanted -> keep, marks decided.
        self._run(bot, self._hook(kind=fc.FISH, name='Lachs'))
        self.assertTrue(bot._whitelist_decided)
        # Second read in the SAME cycle is short-circuited (returns False, no work)
        # even if it were unwanted -- the round is already decided.
        aborted, clicks = self._run(bot, self._hook(kind=fc.FISH, name='Lachs'))
        self.assertFalse(aborted)
        self.assertEqual(clicks, [])


class _FakeRefill:
    """Stand-in for ``interface.refill`` with just the surface the trigger uses.

    ``refill_from_inventory`` returns a scripted result (or raises if asked), and
    records that it was called so a test can assert the inventory path ran.
    """

    BAIT_NAMES = ('Worm',)
    DEFAULT_CALIBRATION = {'sentinel': True}

    def __init__(self, empty, result='dragged', raise_on_refill=False):
        self._empty = empty
        self._result = result
        self._raise = raise_on_refill
        self.refill_calls = []

    def quickslot_index(self, key):
        # Mirror the real mapping enough for the bait key '2' -> slot 2.
        keys = ('1', '2', '3', '4', 'f1', 'f2', 'f3', 'f4')
        try:
            return keys.index(str(key).strip().lower()) + 1
        except ValueError:
            return None

    def quickslot_is_empty(self, screenshot, slot, **_kw):
        return self._empty

    def quickslot_screen(self, slot, ox=0, oy=0):
        return (300 + ox, 580 + oy)

    def refill_from_inventory(self, names, target, **kw):
        self.refill_calls.append((names, target, kw))
        if self._raise:
            raise RuntimeError('boom')
        return self._result


class TestBaitRefillTrigger(unittest.TestCase):
    """``_maybe_refill_bait`` -- throttled, opt-in, strictly defensive.

    The whole refill engine (``interface.refill``) is swapped for a fake so we
    drive exactly what the bait quick-slot 'looks like' and what the inventory
    refill returns; ``pydirectinput`` is mocked so no key/click fires for real.
    """

    def _bot(self, enabled=True):
        bot = _bare_bot()
        bot.bait_refill_enabled = enabled
        bot.bait_key = '2'
        bot.inventory_hotkey = 'i'
        bot.bait_refill_db = object()
        bot.bait_refill_calib = None
        bot.on_bait_empty = None
        bot._last_bait_check = 0.0
        bot.botting = True
        bot.state = 0
        bot.wincap = _StubCapture()
        return bot

    def _run(self, bot, fake):
        with mock.patch.object(fishingbot, '_refill', fake), \
                mock.patch.object(fishingbot, 'pydirectinput', mock.Mock()), \
                mock.patch.object(fishingbot, 'sleep', lambda *_a, **_k: None):
            bot._maybe_refill_bait(object())

    def test_disabled_is_noop(self):
        bot = self._bot(enabled=False)
        fake = _FakeRefill(empty=True)
        self._run(bot, fake)
        self.assertEqual(fake.refill_calls, [])   # never scanned
        self.assertTrue(bot.botting)

    def test_no_module_is_noop(self):
        bot = self._bot(enabled=True)
        with mock.patch.object(fishingbot, '_refill', None), \
                mock.patch.object(fishingbot, 'pydirectinput', mock.Mock()):
            bot._maybe_refill_bait(object())   # must not raise
        self.assertTrue(bot.botting)

    def test_no_wincap_is_noop(self):
        bot = self._bot(enabled=True)
        bot.wincap = None
        fake = _FakeRefill(empty=True)
        self._run(bot, fake)
        self.assertEqual(fake.refill_calls, [])

    def test_slot_not_empty_does_nothing(self):
        bot = self._bot()
        fake = _FakeRefill(empty=False)
        self._run(bot, fake)
        self.assertEqual(fake.refill_calls, [])   # no inventory work
        self.assertTrue(bot.botting)

    def test_empty_slot_refills_and_keeps_fishing(self):
        bot = self._bot()
        fake = _FakeRefill(empty=True, result='dragged')
        self._run(bot, fake)
        self.assertEqual(len(fake.refill_calls), 1)
        # Engine called with the BAIT names + the quick-slot screen target.
        names, target, kw = fake.refill_calls[0]
        self.assertEqual(names, _FakeRefill.BAIT_NAMES)
        self.assertEqual(target, (300, 580))      # offset 0 in the stub
        self.assertIs(kw['wincap'], bot.wincap)
        self.assertIs(kw['db'], bot.bait_refill_db)
        self.assertTrue(bot.botting)              # still fishing

    def test_calib_falls_back_to_engine_default(self):
        bot = self._bot()
        bot.bait_refill_calib = None
        fake = _FakeRefill(empty=True)
        self._run(bot, fake)
        _names, _target, kw = fake.refill_calls[0]
        # None on the instance -> the engine's DEFAULT_CALIBRATION is passed.
        self.assertEqual(kw['calib'], _FakeRefill.DEFAULT_CALIBRATION)

    def test_empty_inventory_stops_bot_and_fires_hook(self):
        bot = self._bot()
        fired = []
        bot.on_bait_empty = lambda: fired.append(1)
        fake = _FakeRefill(empty=True, result='empty')
        self._run(bot, fake)
        self.assertFalse(bot.botting)             # stopped: no bait left
        self.assertEqual(fired, [1])              # popup hook fired once

    def test_refill_error_does_not_stop(self):
        bot = self._bot()
        fake = _FakeRefill(empty=True, result='error')
        self._run(bot, fake)
        self.assertTrue(bot.botting)              # error != empty -> keep fishing

    def test_engine_exception_swallowed(self):
        bot = self._bot()
        fake = _FakeRefill(empty=True, raise_on_refill=True)
        self._run(bot, fake)                      # must not propagate
        self.assertTrue(bot.botting)              # a crash must not stop the bot

    def test_throttled_within_interval(self):
        bot = self._bot()
        fake = _FakeRefill(empty=True, result='dragged')
        self._run(bot, fake)                      # first check: runs
        self.assertEqual(len(fake.refill_calls), 1)
        self._run(bot, fake)                      # immediate second: throttled
        self.assertEqual(len(fake.refill_calls), 1)

    def test_bad_bait_key_no_refill(self):
        bot = self._bot()
        bot.bait_key = 'q'                        # not a quick-slot key
        fake = _FakeRefill(empty=True)
        self._run(bot, fake)
        self.assertEqual(fake.refill_calls, [])

    # -- Responsiveness: the heavy refill op is interruptible + bounded ----

    def test_stop_signal_passed_as_should_stop_and_sleep(self):
        # The bot must hand the engine an interruptible sleep + a should_stop
        # predicate so a panic-stop aborts the multi-page scan.
        import stop_signal
        bot = self._bot()
        bot.stop_signal = stop_signal.StopSignal()
        fake = _FakeRefill(empty=True, result='dragged')
        self._run(bot, fake)
        _names, _target, kw = fake.refill_calls[0]
        self.assertTrue(callable(kw.get('sleep')))
        self.assertTrue(callable(kw.get('should_stop')))
        # should_stop reflects the signal.
        self.assertFalse(kw['should_stop']())
        bot.stop_signal.request_stop()
        self.assertTrue(kw['should_stop']())

    def test_stopped_result_keeps_bot_state_and_no_crash(self):
        # 'stopped' (engine aborted by F6) must not be treated as 'empty'; it
        # just logs. botting is whatever the stop path already set (here True,
        # since we only simulate the engine result).
        bot = self._bot()
        fake = _FakeRefill(empty=True, result='stopped')
        self._run(bot, fake)                      # must not raise
        self.assertTrue(bot.botting)              # not stopped *by refill*

    def test_refill_should_stop_true_when_signal_set(self):
        import stop_signal
        bot = self._bot()
        bot.stop_signal = stop_signal.StopSignal()
        self.assertFalse(bot._refill_should_stop())
        bot.stop_signal.request_stop()
        self.assertTrue(bot._refill_should_stop())

    def test_refill_should_stop_true_when_not_botting(self):
        bot = self._bot()
        bot.botting = False
        self.assertTrue(bot._refill_should_stop())

    def test_refill_sleep_interrupts_on_signal(self):
        import stop_signal, time as _t
        bot = self._bot()
        bot.stop_signal = stop_signal.StopSignal()
        import threading
        threading.Timer(0.02, bot.stop_signal.request_stop).start()
        t0 = _t.monotonic()
        result = bot._refill_sleep(5.0)
        self.assertFalse(result)                  # cut short by the stop
        self.assertLess(_t.monotonic() - t0, 0.5)

    def test_refill_sleep_without_signal_uses_plain_sleep(self):
        # Default NULL_SIGNAL is never set -> wait returns True (uninterrupted)
        # for a tiny duration without blocking the test meaningfully.
        bot = self._bot()
        # bot.stop_signal defaults to the never-set NULL_SIGNAL on the class.
        self.assertTrue(bot._refill_sleep(0.001))


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
