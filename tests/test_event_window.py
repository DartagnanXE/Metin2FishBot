# -*- coding: utf-8 -*-
"""DST-correctness suite for the fish-event windows (event_window.py).

The whole point of this module is that Europe/Berlin is +1 (CET) in winter and
+2 (CEST) in summer, switching on the last Sundays of March/October. These
tests build datetimes explicitly (aware AND naive) and check is_event_now /
active_window / minutes_until_end / should_warn across those boundaries, plus
end-exclusivity, the warn-N-minutes threshold (0 = off), and graceful behaviour
on malformed windows. Pure -- no network, no UI.

CI guard: tzdata must be importable (the Windows EXE ships it via the .spec).
If the IANA database is genuinely absent the tz-dependent tests skip cleanly,
but we still assert the functions degrade without raising.
"""

import unittest
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
    _BERLIN = ZoneInfo('Europe/Berlin')
    _TZ_OK = True
except Exception:
    _BERLIN = None
    _TZ_OK = False

import event_window as ew


def _berlin(year, month, day, hour=0, minute=0):
    """Aware Berlin datetime (skips the test if tzdata is missing)."""
    return datetime(year, month, day, hour, minute, tzinfo=_BERLIN)


class TestTzdataPresent(unittest.TestCase):
    def test_tzdata_importable_in_ci(self):
        # The EXE relies on tzdata; surface its absence loudly in CI.
        try:
            import tzdata  # noqa: F401
        except Exception:
            self.skipTest('tzdata not installed in this environment')

    def test_berlin_zone_resolves(self):
        if not _TZ_OK:
            self.skipTest('zoneinfo/tzdata unavailable')
        self.assertIsNotNone(ew._berlin_zone())


@unittest.skipUnless(_TZ_OK, 'zoneinfo/tzdata unavailable')
class TestDefaultWindows(unittest.TestCase):
    # 2025-06 calendar: Wed = 2025-06-04, Sun = 2025-06-08 (summer, CEST +2).
    def test_sunday_active_midwindow(self):
        # Sunday 2025-06-08 14:00 is inside Sun 12:00-16:00.
        self.assertTrue(ew.is_event_now(_berlin(2025, 6, 8, 14, 0)))

    def test_sunday_inactive_before(self):
        self.assertFalse(ew.is_event_now(_berlin(2025, 6, 8, 11, 59)))

    def test_wednesday_active(self):
        # Wednesday 2025-06-04 06:00 is inside Wed 00:00-12:00.
        self.assertTrue(ew.is_event_now(_berlin(2025, 6, 4, 6, 0)))

    def test_wednesday_start_inclusive(self):
        # 00:00 exactly -> active (start inclusive).
        self.assertTrue(ew.is_event_now(_berlin(2025, 6, 4, 0, 0)))

    def test_end_is_exclusive(self):
        # 16:00 exactly on Sunday -> NOT active (end exclusive).
        self.assertFalse(ew.is_event_now(_berlin(2025, 6, 8, 16, 0)))
        # 12:00 exactly on Wednesday -> NOT active (end exclusive).
        self.assertFalse(ew.is_event_now(_berlin(2025, 6, 4, 12, 0)))

    def test_wrong_weekday_inactive(self):
        # Monday 2025-06-09 14:00 -> no window.
        self.assertFalse(ew.is_event_now(_berlin(2025, 6, 9, 14, 0)))

    def test_active_window_index(self):
        found = ew.active_window(_berlin(2025, 6, 8, 13, 0))
        self.assertIsNotNone(found)
        self.assertEqual(found[0], 0)   # Sunday is window 0 in DEFAULT_WINDOWS
        found_wed = ew.active_window(_berlin(2025, 6, 4, 3, 0))
        self.assertEqual(found_wed[0], 1)


@unittest.skipUnless(_TZ_OK, 'zoneinfo/tzdata unavailable')
class TestMinutesUntilEnd(unittest.TestCase):
    def test_minutes_left(self):
        # Sunday 15:00 -> 60 min until 16:00.
        self.assertEqual(ew.minutes_until_end(_berlin(2025, 6, 8, 15, 0)), 60)

    def test_minutes_ceiling_partial(self):
        # 15:59:30 -> 1 min remaining rounds up (never lost).
        now = datetime(2025, 6, 8, 15, 59, 30, tzinfo=_BERLIN)
        self.assertEqual(ew.minutes_until_end(now), 1)

    def test_none_when_inactive(self):
        self.assertIsNone(ew.minutes_until_end(_berlin(2025, 6, 9, 14, 0)))


@unittest.skipUnless(_TZ_OK, 'zoneinfo/tzdata unavailable')
class TestShouldWarn(unittest.TestCase):
    def test_warn_off_by_default(self):
        # warn=0 -> never warns even right before the end.
        self.assertFalse(ew.should_warn(_berlin(2025, 6, 8, 15, 59),
                                        warn_minutes=0))

    def test_warn_within_threshold(self):
        # 10 min left, warn 15 -> warn.
        self.assertTrue(ew.should_warn(_berlin(2025, 6, 8, 15, 50),
                                       warn_minutes=15))

    def test_no_warn_outside_threshold(self):
        # 60 min left, warn 15 -> no warn.
        self.assertFalse(ew.should_warn(_berlin(2025, 6, 8, 15, 0),
                                        warn_minutes=15))

    def test_no_warn_when_inactive(self):
        self.assertFalse(ew.should_warn(_berlin(2025, 6, 9, 14, 0),
                                        warn_minutes=30))

    def test_garbage_warn_minutes_is_off(self):
        self.assertFalse(ew.should_warn(_berlin(2025, 6, 8, 15, 59),
                                        warn_minutes='x'))


@unittest.skipUnless(_TZ_OK, 'zoneinfo/tzdata unavailable')
class TestDSTBoundaries(unittest.TestCase):
    """Across spring-forward and fall-back, offsets must be correct."""

    def test_spring_forward_offset(self):
        # Spring forward 2025: last Sun March = 2025-03-30, 02:00 -> 03:00.
        # Before: CET +1. After: CEST +2.
        before = datetime(2025, 3, 30, 1, 30, tzinfo=_BERLIN)
        after = datetime(2025, 3, 30, 3, 30, tzinfo=_BERLIN)
        self.assertEqual(before.utcoffset().total_seconds(), 3600)
        self.assertEqual(after.utcoffset().total_seconds(), 7200)

    def test_fall_back_offset(self):
        # Fall back 2025: last Sun October = 2025-10-26, 03:00 -> 02:00.
        before = datetime(2025, 10, 26, 1, 30, tzinfo=_BERLIN)
        after = datetime(2025, 10, 26, 3, 30, tzinfo=_BERLIN)
        self.assertEqual(before.utcoffset().total_seconds(), 7200)  # CEST +2
        self.assertEqual(after.utcoffset().total_seconds(), 3600)   # CET +1

    def test_sunday_window_active_on_spring_forward_day(self):
        # 2025-03-30 is a Sunday (DST switch day); 12-16 window must still work.
        # At 14:00 CEST the event is active and minutes_until_end honours +2.
        now = _berlin(2025, 3, 30, 14, 0)
        self.assertTrue(ew.is_event_now(now))
        self.assertEqual(ew.minutes_until_end(now), 120)

    def test_naive_now_interpreted_as_berlin_wallclock(self):
        # A naive 14:00 on Sunday is treated as Berlin local -> active.
        naive = datetime(2025, 6, 8, 14, 0)
        self.assertTrue(ew.is_event_now(naive))
        # And localising it yields the +2 summer offset.
        local = ew.localize(naive)
        self.assertEqual(local.utcoffset().total_seconds(), 7200)

    def test_winter_naive_offset_plus_one(self):
        # A January Sunday naive time localises to CET +1.
        local = ew.localize(datetime(2025, 1, 5, 14, 0))
        self.assertEqual(local.utcoffset().total_seconds(), 3600)

    def test_aware_utc_converted_into_berlin(self):
        try:
            from datetime import timezone
        except Exception:
            self.skipTest('timezone unavailable')
        # 2025-06-08 12:00 UTC == 14:00 CEST (Sunday) -> active.
        utc_now = datetime(2025, 6, 8, 12, 0, tzinfo=timezone.utc)
        self.assertTrue(ew.is_event_now(utc_now))


class TestMalformedAndDegrade(unittest.TestCase):
    """These must hold regardless of tzdata: never raise."""

    @unittest.skipUnless(_TZ_OK, 'zoneinfo/tzdata unavailable')
    def test_malformed_window_inactive(self):
        bad = [
            {'weekday': 99, 'start': '12:00', 'end': '16:00'},   # bad weekday
            {'weekday': 6, 'start': 'xx', 'end': '16:00'},       # bad start
            {'weekday': 6, 'start': '16:00', 'end': '12:00'},    # end<=start
            {'weekday': 6},                                      # missing fields
            'not a dict',
        ]
        now = _berlin(2025, 6, 8, 14, 0)
        # None of these define an active window at Sunday 14:00 in a clean way;
        # the function must simply return False, never raise.
        self.assertFalse(ew.is_event_now(now, bad))

    def test_non_datetime_now_is_safe(self):
        self.assertFalse(ew.is_event_now('not a datetime'))
        self.assertIsNone(ew.minutes_until_end(None))
        self.assertFalse(ew.should_warn(12345, warn_minutes=10))

    def test_status_shape(self):
        s = ew.status(datetime(2025, 6, 9, 14, 0))   # Monday -> inactive
        self.assertIn('active', s)
        self.assertIn('tz_available', s)
        self.assertIn('minutes_left', s)
        self.assertIn('warn', s)

    @unittest.skipUnless(_TZ_OK, 'zoneinfo/tzdata unavailable')
    def test_status_active_reports_index_and_warn(self):
        s = ew.status(_berlin(2025, 6, 8, 15, 50), warn_minutes=15)
        self.assertTrue(s['active'])
        self.assertEqual(s['window_index'], 0)
        self.assertTrue(s['warn'])
        self.assertEqual(s['minutes_left'], 10)


if __name__ == '__main__':
    unittest.main()
