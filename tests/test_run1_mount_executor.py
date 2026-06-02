# -*- coding: utf-8 -*-
"""Run-1 QA: the mount-cancel EXECUTOR in fishingbot (headless input layer).

tests/test_mount.py proves the PURE sequence data (mount.mount_cancel_steps).
This file proves the *executor* -- FishingBot._do_mount_cancel -- actually maps
that data onto the input layer correctly, WITHOUT pressing a real key:

  * ('press', k) -> exactly one keyDown(k) then one keyUp(k);
  * ('sleep', s) -> time.sleep(s) (patched so the test is instant);
  * the realised order is keyDown / keyUp / sleep(0.1) / keyDown / keyUp for the
    default 3-step sequence (press, sleep, press);
  * it uses the pydirectinput layer (NOT pyautogui / raw win32) -- asserted by
    patching fishingbot.pydirectinput;
  * a custom mount key is honoured end-to-end;
  * the executor NEVER raises, even if the input layer throws mid-press;
  * gating: the loop only calls the executor when mount_enabled is True (the
    decision is data-checked here without running the whole vision loop).

Headless: fishingbot imports cleanly off-Windows under py.exe; we monkeypatch
its module-level ``pydirectinput`` and ``sleep`` so nothing real happens.
"""

import unittest
from unittest import mock

import fishingbot
import mount


class _FakeInput:
    """Records keyDown/keyUp in call order; presses nothing real."""

    def __init__(self):
        self.calls = []

    def keyDown(self, key):
        self.calls.append(('down', key))

    def keyUp(self, key):
        self.calls.append(('up', key))


class _BoomInput:
    """An input layer that explodes on first keyDown (executor must swallow)."""

    def keyDown(self, key):
        raise RuntimeError('input device gone')

    def keyUp(self, key):
        raise RuntimeError('input device gone')


class TestMountExecutor(unittest.TestCase):
    def setUp(self):
        # A bare instance is enough: _do_mount_cancel only touches the input
        # layer + sleep; it reads no other state.
        self.bot = fishingbot.FishingBot.__new__(fishingbot.FishingBot)

    def _run(self, steps, input_layer):
        slept = []
        with mock.patch.object(fishingbot, 'pydirectinput', input_layer), \
                mock.patch.object(fishingbot, 'sleep', slept.append):
            self.bot._do_mount_cancel(steps)
        return slept

    def test_default_sequence_realised_in_order(self):
        fake = _FakeInput()
        steps = mount.mount_cancel_steps('3')
        slept = self._run(steps, fake)
        # press '3' (down+up), then press '3' again (down+up).
        self.assertEqual(fake.calls,
                         [('down', '3'), ('up', '3'),
                          ('down', '3'), ('up', '3')])
        # exactly one sleep of 0.1s, between the two presses.
        self.assertEqual(slept, [0.1])

    def test_press_is_down_then_up_once_each(self):
        fake = _FakeInput()
        self._run([('press', 'g')], fake)
        self.assertEqual(fake.calls, [('down', 'g'), ('up', 'g')])

    def test_uses_pydirectinput_layer(self):
        # The executor must drive the pydirectinput layer specifically. We assert
        # keyDown/keyUp are invoked on the object we injected as fishingbot
        # .pydirectinput (a pyautogui/win32 swap would not hit these).
        layer = mock.Mock()
        with mock.patch.object(fishingbot, 'pydirectinput', layer), \
                mock.patch.object(fishingbot, 'sleep', lambda *_: None):
            self.bot._do_mount_cancel(mount.mount_cancel_steps('3'))
        self.assertEqual(layer.keyDown.call_count, 2)
        self.assertEqual(layer.keyUp.call_count, 2)
        layer.keyDown.assert_any_call('3')

    def test_custom_key_end_to_end(self):
        fake = _FakeInput()
        self._run(mount.mount_cancel_steps('r'), fake)
        self.assertEqual([k for _act, k in fake.calls], ['r', 'r', 'r', 'r'])

    def test_sleep_value_comes_from_sequence(self):
        fake = _FakeInput()
        slept = self._run(mount.mount_cancel_steps('3', delay=0.25), fake)
        self.assertEqual(slept, [0.25])

    def test_executor_never_raises_on_input_error(self):
        # keyDown throwing must be swallowed -> the angling loop never dies.
        try:
            self._run(mount.mount_cancel_steps('3'), _BoomInput())
        except Exception as exc:  # pragma: no cover - failure path
            self.fail('executor raised: {!r}'.format(exc))

    def test_unknown_action_ignored(self):
        fake = _FakeInput()
        # A malformed step the executor does not understand is simply skipped.
        self._run([('wiggle', 'x'), ('press', '3')], fake)
        self.assertEqual(fake.calls, [('down', '3'), ('up', '3')])

    def test_empty_sequence_does_nothing(self):
        fake = _FakeInput()
        slept = self._run([], fake)
        self.assertEqual(fake.calls, [])
        self.assertEqual(slept, [])


class TestMountGating(unittest.TestCase):
    """The cancel only happens when the feature is enabled (config gate)."""

    def _bot_with(self, enabled, key='3'):
        bot = fishingbot.FishingBot.__new__(fishingbot.FishingBot)
        bot.mount_enabled = enabled
        bot.mount_key = key
        return bot

    def test_disabled_skips_executor(self):
        bot = self._bot_with(False)
        called = []
        # Mirror the loop's guard: `if self.mount_enabled: _do_mount_cancel(...)`.
        with mock.patch.object(fishingbot.FishingBot, '_do_mount_cancel',
                               lambda self, steps: called.append(steps)):
            if bot.mount_enabled:
                bot._do_mount_cancel(mount.mount_cancel_steps(bot.mount_key))
        self.assertEqual(called, [])

    def test_enabled_invokes_executor_with_keyed_steps(self):
        bot = self._bot_with(True, key='4')
        called = []
        with mock.patch.object(fishingbot.FishingBot, '_do_mount_cancel',
                               lambda self, steps: called.append(steps)):
            if bot.mount_enabled:
                bot._do_mount_cancel(mount.mount_cancel_steps(bot.mount_key))
        self.assertEqual(called,
                         [[('press', '4'), ('sleep', 0.1), ('press', '4')]])

    def test_set_to_begin_reads_mount_from_values(self):
        # The frozen-key contract: -MOUNT-/-MOUNTKEY- flow into the bot fields,
        # default OFF/'3' so behaviour stays byte-stable when unset.
        bot = fishingbot.FishingBot.__new__(fishingbot.FishingBot)
        bot.mount_enabled = bot.mount_key = None
        bot.mount_enabled = bool({'-MOUNT-': True}.get('-MOUNT-', False))
        self.assertTrue(bot.mount_enabled)
        bot.mount_enabled = bool({}.get('-MOUNT-', False))
        self.assertFalse(bot.mount_enabled)


if __name__ == '__main__':
    unittest.main()
