# -*- coding: utf-8 -*-
"""Mount animation-cancel sequence as PURE data (headless-testable).

Purpose (confirmed by the user): mounting and immediately dismounting CANCELS
the successful-catch animation after the fishing minigame, so the rod re-casts
faster. The mount key is a TOGGLE -- pressing it once mounts, pressing it again
dismounts. So the cancel is: press the mount key, wait a short moment, press it
again.

This module returns the sequence as an ordered list of steps so it can be unit-
tested WITHOUT pressing any key. The executor lives in :mod:`fishingbot`
(``_do_mount_cancel``), which maps ``('press', key)`` -> keyDown/keyUp and
``('sleep', seconds)`` -> ``time.sleep``. Stdlib only; no side effects here.
"""

# Pause between the mount and the dismount press. 0.1s is enough for the game to
# register the toggle; short enough to keep the re-cast snappy. A single source
# of truth so both the sequence and the test reference the same constant.
MOUNT_TOGGLE_DELAY = 0.1


def mount_cancel_steps(key, delay=MOUNT_TOGGLE_DELAY):
    """Return the ordered mount->dismount cancel sequence as data.

    The result is a list of ``(action, value)`` tuples:
      * ``('press', key)`` -- press (down+up) the mount key,
      * ``('sleep', delay)`` -- wait,
      * ``('press', key)`` -- press it again (the dismount toggle).

    Pure: no key is sent, no time is slept. ``key`` is coerced to ``str`` so a
    non-string config value can never crash the executor. ``delay`` is clamped
    to a non-negative float (a negative/garbage delay falls back to the default).
    Never raises.
    """
    try:
        key_token = str(key)
    except Exception:
        key_token = ''
    try:
        wait = float(delay)
        if wait < 0:
            wait = MOUNT_TOGGLE_DELAY
    except (TypeError, ValueError):
        wait = MOUNT_TOGGLE_DELAY
    return [('press', key_token), ('sleep', wait), ('press', key_token)]
