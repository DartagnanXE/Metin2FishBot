# -*- coding: utf-8 -*-
"""Fish-event time windows -- PURE, DST-correct, fully unit-testable.

Zero IO, zero UI, zero network. Answers "is a fish event running right now?" and
"how long until it ends?" for two configurable weekly windows.

DST correctness is the whole point: Berlin is CET (+1) in winter and CEST (+2)
in summer, switching on the last Sundays of March/October. We use
``zoneinfo.ZoneInfo('Europe/Berlin')`` (NOT a hardcoded +1) so the offset is
resolved per-instant from the IANA database -> every boundary is handled.

A window is ``{'weekday': 0-6 (Mon=0..Sun=6), 'start': 'HH:MM', 'end': 'HH:MM'}``.
``end`` is EXCLUSIVE. Only same-day windows are supported (``end > start``);
a window with ``end <= start`` or a bad field is treated as INACTIVE (never
raises). Spec defaults: Sunday 12:00-16:00 and Wednesday 00:00-12:00.

Robustness: if the tz database is unavailable (Windows EXE without ``tzdata``),
:func:`localize` returns ``None`` and the status functions degrade to an
"unknown" result (``active=False``) rather than crashing the bot. The caller
(hack.py) logs that once; the EXE must never die because a tz file is missing.
"""

from datetime import datetime

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    _ZONEINFO_IMPORT_OK = True
except Exception:                       # pragma: no cover - stdlib always has it
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception
    _ZONEINFO_IMPORT_OK = False

BERLIN_TZ = 'Europe/Berlin'

# Spec defaults: Sunday(6) 12:00-16:00 and Wednesday(2) 00:00-12:00.
DEFAULT_WINDOWS = (
    {'weekday': 6, 'start': '12:00', 'end': '16:00'},
    {'weekday': 2, 'start': '00:00', 'end': '12:00'},
)

# Warning before the end is OFF by default (0). Upper bound = 24h.
WARN_MIN_DEFAULT = 0
WARN_MIN_MAX = 1440


def _berlin_zone():
    """Return the Europe/Berlin ZoneInfo, or ``None`` if tzdata is unavailable.

    Never raises -> a missing IANA database degrades to ``None`` (status
    becomes "unknown") instead of crashing the EXE.
    """
    if not _ZONEINFO_IMPORT_OK or ZoneInfo is None:
        return None
    try:
        return ZoneInfo(BERLIN_TZ)
    except Exception:
        return None


def localize(now):
    """Return ``now`` as an aware datetime in Europe/Berlin (or ``None``).

    * naive ``now`` -> interpreted as Berlin wall-clock time (DST-correct).
    * aware ``now`` -> converted into Berlin.
    Returns ``None`` if ``now`` is not a datetime or the tz database is missing.
    Never raises.
    """
    if not isinstance(now, datetime):
        return None
    zone = _berlin_zone()
    if zone is None:
        return None
    try:
        if now.tzinfo is None:
            return now.replace(tzinfo=zone)
        return now.astimezone(zone)
    except Exception:
        return None


def _parse_hhmm(text):
    """'HH:MM' -> (hour, minute) with 0<=h<=23, 0<=m<=59, or ``None``."""
    try:
        hh, mm = str(text).split(':')
        hour = int(hh)
        minute = int(mm)
    except (TypeError, ValueError):
        return None
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return (hour, minute)
    return None


def _window_bounds(local_now, window):
    """Resolve a window to (start_dt, end_dt) aware datetimes for ``local_now``'s
    matching weekday, or ``None`` if the window does not apply / is malformed.

    ``end`` is exclusive; only same-day windows (end > start) are valid. The
    bounds are anchored to ``local_now``'s date when its weekday matches the
    window's weekday. Never raises.
    """
    try:
        if not isinstance(window, dict):
            return None
        weekday = window.get('weekday')
        if not isinstance(weekday, int) or not (0 <= weekday <= 6):
            return None
        if local_now.weekday() != weekday:
            return None
        start = _parse_hhmm(window.get('start'))
        end = _parse_hhmm(window.get('end'))
        if start is None or end is None:
            return None
        start_dt = local_now.replace(hour=start[0], minute=start[1],
                                     second=0, microsecond=0)
        end_dt = local_now.replace(hour=end[0], minute=end[1],
                                   second=0, microsecond=0)
        if end_dt <= start_dt:       # same-day only; reject end<=start
            return None
        return (start_dt, end_dt)
    except Exception:
        return None


def active_window(now, windows=DEFAULT_WINDOWS):
    """Return the index of the window active at ``now``, plus its bounds.

    Returns ``(index, start_dt, end_dt)`` for the first matching window, or
    ``None`` if none is active / tz is unavailable. ``end`` is exclusive
    (start <= now < end). Never raises.
    """
    local_now = localize(now)
    if local_now is None:
        return None
    try:
        for index, window in enumerate(windows or ()):
            bounds = _window_bounds(local_now, window)
            if bounds is None:
                continue
            start_dt, end_dt = bounds
            if start_dt <= local_now < end_dt:
                return (index, start_dt, end_dt)
        return None
    except Exception:
        return None


def is_event_now(now, windows=DEFAULT_WINDOWS):
    """``True`` iff a fish event is running at ``now``. Never raises."""
    return active_window(now, windows) is not None


def minutes_until_end(now, windows=DEFAULT_WINDOWS):
    """Whole minutes (ceil) until the active window ends, or ``None``.

    ``None`` if no event is active (or tz unavailable). Always >= 1 while active
    (a partial final minute rounds UP) so a "1 min left" warning is never lost.
    Never raises.
    """
    found = active_window(now, windows)
    if found is None:
        return None
    try:
        _index, _start, end_dt = found
        local_now = localize(now)
        remaining = (end_dt - local_now).total_seconds()
        if remaining <= 0:
            return 0
        return int((remaining + 59) // 60)   # ceil to whole minutes
    except Exception:
        return None


def should_warn(now, windows=DEFAULT_WINDOWS, warn_minutes=WARN_MIN_DEFAULT):
    """``True`` iff an event is active AND <= ``warn_minutes`` remain.

    ``warn_minutes <= 0`` -> always ``False`` (warning off). Bad ``warn_minutes``
    is coerced to 0 (off). Never raises.
    """
    try:
        warn = int(warn_minutes)
    except (TypeError, ValueError):
        warn = 0
    if warn <= 0:
        return False
    left = minutes_until_end(now, windows)
    if left is None:
        return False
    return left <= warn


def status(now, windows=DEFAULT_WINDOWS, warn_minutes=WARN_MIN_DEFAULT):
    """Structured snapshot for the UI/log. Never raises.

    Returns a dict::

        {'active': bool,
         'window_index': int|None,
         'minutes_left': int|None,
         'warn': bool,
         'tz_available': bool}

    ``tz_available`` is ``False`` when the IANA database is missing (the caller
    can show/log an "event status unknown" hint instead of a wrong answer).
    """
    tz_available = _berlin_zone() is not None
    found = active_window(now, windows)
    if found is None:
        return {'active': False, 'window_index': None, 'minutes_left': None,
                'warn': False, 'tz_available': tz_available}
    index = found[0]
    left = minutes_until_end(now, windows)
    return {
        'active': True,
        'window_index': index,
        'minutes_left': left,
        'warn': should_warn(now, windows, warn_minutes),
        'tz_available': tz_available,
    }
