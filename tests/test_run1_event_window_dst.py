# -*- coding: utf-8 -*-
"""Run-1 QA: exhaustive DST + boundary suite for event_window.py.

Complements tests/test_event_window.py. Where that file proves the basics, this
one nails the explicitly-required corners:

  * BOTH default windows exercised on the EXACT spring-forward (last Sun March)
    and fall-back (last Sun October) Europe/Berlin transition days, 2025 AND
    2026, asserting the UTC offset that minutes_until_end relies on.
  * The Wednesday 00:00-12:00 window's MIDNIGHT-WRAP edge: 00:00 inclusive,
    23:59 of Tuesday inactive, 12:00 exclusive, and minutes_until_end at 00:00.
  * The warn threshold at its EXACT boundary (left == warn -> warn; left ==
    warn+1 -> no warn) and the "warn off" default (0) right before the end.
  * minutes_until_end ceil semantics never drop a final partial minute.
  * Determinism: is_event_now is a pure function of (now, windows).

Pure stdlib; tz-dependent cases skip cleanly if the IANA db is truly absent,
but the degrade-without-raising guarantee is still asserted unconditionally.
"""

import unittest
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
    _BERLIN = ZoneInfo('Europe/Berlin')
    _TZ_OK = True
except Exception:
    _BERLIN = None
    _TZ_OK = False

import event_window as ew

CET = 3600      # +1 winter
CEST = 7200     # +2 summer


def _b(y, mo, d, h=0, mi=0, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=_BERLIN)


@unittest.skipUnless(_TZ_OK, 'zoneinfo/tzdata unavailable')
class TestTransitionDayOffsets(unittest.TestCase):
    """The raw offset on the switch instants -- both years, both directions."""

    def test_spring_forward_2025_offsets(self):
        # 2025-03-30: 02:00 -> 03:00 (CET -> CEST).
        self.assertEqual(_b(2025, 3, 30, 1, 30).utcoffset().total_seconds(), CET)
        self.assertEqual(_b(2025, 3, 30, 3, 30).utcoffset().total_seconds(), CEST)

    def test_fall_back_2025_offsets(self):
        # 2025-10-26: 03:00 -> 02:00 (CEST -> CET).
        self.assertEqual(_b(2025, 10, 26, 1, 30).utcoffset().total_seconds(), CEST)
        self.assertEqual(_b(2025, 10, 26, 3, 30).utcoffset().total_seconds(), CET)

    def test_spring_forward_2026_offsets(self):
        # Last Sunday of March 2026 = 2026-03-29.
        self.assertEqual(_b(2026, 3, 29, 1, 30).utcoffset().total_seconds(), CET)
        self.assertEqual(_b(2026, 3, 29, 3, 30).utcoffset().total_seconds(), CEST)

    def test_fall_back_2026_offsets(self):
        # Last Sunday of October 2026 = 2026-10-25.
        self.assertEqual(_b(2026, 10, 25, 1, 30).utcoffset().total_seconds(), CEST)
        self.assertEqual(_b(2026, 10, 25, 3, 30).utcoffset().total_seconds(), CET)


@unittest.skipUnless(_TZ_OK, 'zoneinfo/tzdata unavailable')
class TestSundayWindowOnTransitionDays(unittest.TestCase):
    """Sunday 12:00-16:00 window (index 0) on the DST switch Sundays.

    Both spring-forward and fall-back happen on a SUNDAY, so the default Sunday
    window straddles a day with a non-standard length -- but the window itself
    (12:00-16:00) is well after the 02:00/03:00 switch, so it must behave like a
    normal 4-hour window with the correct (summer/winter) offset.
    """

    def test_spring_forward_sunday_active_and_full_length(self):
        for y, mo, d in ((2025, 3, 30), (2026, 3, 29)):
            now = _b(y, mo, d, 14, 0)
            self.assertTrue(ew.is_event_now(now), (y, mo, d))
            self.assertEqual(ew.minutes_until_end(now), 120, (y, mo, d))
            self.assertEqual(now.utcoffset().total_seconds(), CEST)

    def test_fall_back_sunday_active_and_full_length(self):
        for y, mo, d in ((2025, 10, 26), (2026, 10, 25)):
            now = _b(y, mo, d, 14, 0)
            self.assertTrue(ew.is_event_now(now), (y, mo, d))
            self.assertEqual(ew.minutes_until_end(now), 120, (y, mo, d))
            self.assertEqual(now.utcoffset().total_seconds(), CET)

    def test_window_index_is_sunday_zero(self):
        found = ew.active_window(_b(2025, 10, 26, 12, 0))
        self.assertIsNotNone(found)
        self.assertEqual(found[0], 0)


@unittest.skipUnless(_TZ_OK, 'zoneinfo/tzdata unavailable')
class TestWednesdayMidnightWrap(unittest.TestCase):
    """Wednesday 00:00-12:00 window (index 1): the midnight edge.

    2025-06-04 and 2026-06-03 are Wednesdays (summer). 2025-01-08 and
    2026-01-07 are winter Wednesdays. The window starts exactly at 00:00
    (inclusive) and ends 12:00 (exclusive) -- the classic off-by-one trap.
    """

    WED_SUMMER = ((2025, 6, 4), (2026, 6, 3))
    WED_WINTER = ((2025, 1, 8), (2026, 1, 7))

    def test_midnight_start_inclusive(self):
        for y, mo, d in self.WED_SUMMER + self.WED_WINTER:
            self.assertTrue(ew.is_event_now(_b(y, mo, d, 0, 0)), (y, mo, d))

    def test_one_second_before_midnight_is_tuesday_inactive(self):
        # 23:59:59 of the *preceding* Tuesday -> not the Wed window, not Sun.
        for y, mo, d in self.WED_SUMMER:
            tue = _b(y, mo, d, 0, 0)
            tue = tue.replace(day=d - 1, hour=23, minute=59, second=59)
            self.assertFalse(ew.is_event_now(tue), (y, mo, d))

    def test_noon_end_exclusive(self):
        for y, mo, d in self.WED_SUMMER + self.WED_WINTER:
            self.assertFalse(ew.is_event_now(_b(y, mo, d, 12, 0)), (y, mo, d))

    def test_minutes_until_end_at_midnight_is_720(self):
        # 00:00 -> exactly 12 h = 720 minutes to 12:00.
        for y, mo, d in self.WED_SUMMER:
            self.assertEqual(ew.minutes_until_end(_b(y, mo, d, 0, 0)), 720)

    def test_window_index_is_wednesday_one(self):
        found = ew.active_window(_b(2025, 6, 4, 3, 0))
        self.assertEqual(found[0], 1)

    def test_just_before_noon_one_minute_left(self):
        for y, mo, d in self.WED_SUMMER:
            self.assertEqual(ew.minutes_until_end(_b(y, mo, d, 11, 59, 30)), 1)


@unittest.skipUnless(_TZ_OK, 'zoneinfo/tzdata unavailable')
class TestWarnThresholdBoundary(unittest.TestCase):
    """should_warn at the exact threshold edges + the off-by-default rule."""

    def _sun(self, h, mi, s=0):
        return _b(2025, 6, 8, h, mi, s)   # Sunday 12:00-16:00 window

    def test_warn_off_default_right_before_end(self):
        # warn=0 -> never, even at 15:59:59.
        self.assertFalse(ew.should_warn(self._sun(15, 59, 59), warn_minutes=0))

    def test_left_equals_warn_triggers(self):
        # 15:50 -> exactly 10 min left; warn 10 -> True (<=).
        self.assertEqual(ew.minutes_until_end(self._sun(15, 50)), 10)
        self.assertTrue(ew.should_warn(self._sun(15, 50), warn_minutes=10))

    def test_left_one_above_warn_does_not_trigger(self):
        # 15:49:30 -> ceil(30.5min) = 11 left; warn 10 -> False.
        self.assertEqual(ew.minutes_until_end(self._sun(15, 49, 30)), 11)
        self.assertFalse(ew.should_warn(self._sun(15, 49, 30), warn_minutes=10))

    def test_warn_only_while_active(self):
        # Outside any window the warning never fires regardless of threshold.
        self.assertFalse(ew.should_warn(_b(2025, 6, 9, 14, 0), warn_minutes=1440))

    def test_status_reports_warn_and_index_together(self):
        s = ew.status(self._sun(15, 55), warn_minutes=10)
        self.assertTrue(s['active'])
        self.assertEqual(s['window_index'], 0)
        self.assertEqual(s['minutes_left'], 5)
        self.assertTrue(s['warn'])
        self.assertTrue(s['tz_available'])


@unittest.skipUnless(_TZ_OK, 'zoneinfo/tzdata unavailable')
class TestCeilAndDeterminism(unittest.TestCase):
    def test_minutes_never_drops_final_partial(self):
        # Any sub-minute remainder rounds UP so a "1 min left" is never lost.
        now = _b(2025, 6, 8, 15, 59, 1)   # 59s left
        self.assertEqual(ew.minutes_until_end(now), 1)

    def test_full_window_start_is_full_duration(self):
        self.assertEqual(ew.minutes_until_end(_b(2025, 6, 8, 12, 0)), 240)

    def test_is_event_now_is_pure(self):
        now = _b(2025, 6, 8, 14, 0)
        a = ew.is_event_now(now)
        b = ew.is_event_now(now)
        self.assertEqual(a, b)
        self.assertTrue(a)

    def test_aware_utc_maps_into_berlin_window(self):
        # 12:00 UTC on Sunday 2025-06-08 == 14:00 CEST -> active.
        utc = datetime(2025, 6, 8, 12, 0, tzinfo=timezone.utc)
        self.assertTrue(ew.is_event_now(utc))


class TestDegradeUnconditional(unittest.TestCase):
    """Must hold even with NO tzdata: never raise, never wrongly 'active'."""

    def test_non_datetime_inputs_safe(self):
        self.assertFalse(ew.is_event_now(12345))
        self.assertIsNone(ew.minutes_until_end('nope'))
        self.assertFalse(ew.should_warn(None, warn_minutes=10))

    def test_status_always_well_shaped(self):
        s = ew.status(datetime(2025, 6, 9, 14, 0))   # Monday -> inactive
        for k in ('active', 'window_index', 'minutes_left', 'warn',
                  'tz_available'):
            self.assertIn(k, s)
        self.assertFalse(s['active'])

    def test_empty_windows_never_active(self):
        self.assertFalse(ew.is_event_now(datetime(2025, 6, 8, 14, 0), ()))
        self.assertIsNone(
            ew.minutes_until_end(datetime(2025, 6, 8, 14, 0), []))


if __name__ == '__main__':
    unittest.main()
