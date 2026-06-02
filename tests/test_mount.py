# -*- coding: utf-8 -*-
"""Unit tests for the PURE mount animation-cancel sequence (mount.py).

The sequence must be data-only (no key presses, no sleeps) so it is trivially
testable headless. Pure stdlib unittest.
"""

import unittest

import mount


class TestMountCancelSteps(unittest.TestCase):
    def test_default_key_3(self):
        self.assertEqual(
            mount.mount_cancel_steps('3'),
            [('press', '3'), ('sleep', 0.1), ('press', '3')])

    def test_respects_custom_key(self):
        self.assertEqual(
            mount.mount_cancel_steps('g'),
            [('press', 'g'), ('sleep', 0.1), ('press', 'g')])

    def test_delay_constant_is_used(self):
        steps = mount.mount_cancel_steps('1')
        self.assertEqual(steps[1], ('sleep', mount.MOUNT_TOGGLE_DELAY))
        self.assertEqual(mount.MOUNT_TOGGLE_DELAY, 0.1)

    def test_sequence_is_press_sleep_press(self):
        actions = [a for a, _v in mount.mount_cancel_steps('3')]
        self.assertEqual(actions, ['press', 'sleep', 'press'])

    def test_non_string_key_coerced_not_crash(self):
        self.assertEqual(
            mount.mount_cancel_steps(3),
            [('press', '3'), ('sleep', 0.1), ('press', '3')])

    def test_custom_delay(self):
        steps = mount.mount_cancel_steps('3', delay=0.25)
        self.assertEqual(steps[1], ('sleep', 0.25))

    def test_negative_delay_falls_back(self):
        steps = mount.mount_cancel_steps('3', delay=-5)
        self.assertEqual(steps[1], ('sleep', mount.MOUNT_TOGGLE_DELAY))

    def test_garbage_delay_falls_back(self):
        steps = mount.mount_cancel_steps('3', delay='x')
        self.assertEqual(steps[1], ('sleep', mount.MOUNT_TOGGLE_DELAY))

    def test_pure_no_side_effects_stable(self):
        # Calling repeatedly yields identical data (no hidden state).
        a = mount.mount_cancel_steps('k')
        b = mount.mount_cancel_steps('k')
        self.assertEqual(a, b)


if __name__ == '__main__':
    unittest.main()
