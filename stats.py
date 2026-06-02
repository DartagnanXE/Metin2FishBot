# -*- coding: utf-8 -*-
"""Persistent cumulative counters for the ranking (PURE + IO split).

Mirrors :mod:`interface.config`'s philosophy exactly:
  * PURE layer (merge_defaults/validate/increment_*/add_*): returns NEW dicts
    (immutable), clamps negatives to 0, coerces garbage to defaults, NEVER raises.
  * IO layer (load/save): ``stats.json`` next to ``config.json``; ATOMIC write
    (``<path>.tmp`` then ``os.replace``); ``load`` returns validated defaults on
    any error, ``save`` returns ``bool`` and never raises.

Stdlib only (json/os) so it stays importable + headless-testable everywhere
(no GUI/vision deps), exactly like config.py and version.py.

The four counters fed into the leaderboard payload:
  * fishing_catches  -- confirmed fishing minigame catches
  * puzzles_solved   -- solved puzzle boards (state-9 / reward)
  * fishing_runtime_s -- wall-time the fishing bot ran (seconds)
  * puzzler_runtime_s -- wall-time the puzzle bot ran (seconds)
"""

import copy
import json
import os
import threading
import time

DEFAULT_STATS_PATH = 'stats.json'

# Schema version (bump if the shape ever changes -> validate can migrate).
STATS_VERSION = 1

DEFAULTS = {
    'version': STATS_VERSION,
    'fishing_catches': 0,
    'puzzles_solved': 0,
    'fishing_runtime_s': 0.0,
    'puzzler_runtime_s': 0.0,
}

_INT_KEYS = ('fishing_catches', 'puzzles_solved')
_FLOAT_KEYS = ('fishing_runtime_s', 'puzzler_runtime_s')


def _coerce_int_nonneg(value, fallback):
    """-> int >= 0. Garbage/negative -> fallback (which is always 0 here)."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return number if number >= 0 else fallback


def _coerce_float_nonneg(value, fallback):
    """-> float >= 0.0. Garbage/negative/NaN -> fallback."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if number != number or number < 0:   # NaN or negative
        return fallback
    return number


def merge_defaults(partial):
    """Fill missing keys from :data:`DEFAULTS`. Returns a NEW dict. Never raises."""
    result = copy.deepcopy(DEFAULTS)
    if isinstance(partial, dict):
        for key, value in partial.items():
            if key in result:
                result[key] = value
    return result


def validate(stats):
    """Normalise stats: ints/floats coerced, negatives clamped to 0. NEW dict.

    Never raises -- on total garbage returns pure defaults (mirrors config.py).
    """
    try:
        merged = merge_defaults(stats)
        merged['version'] = STATS_VERSION
        for key in _INT_KEYS:
            merged[key] = _coerce_int_nonneg(merged.get(key), 0)
        for key in _FLOAT_KEYS:
            merged[key] = _coerce_float_nonneg(merged.get(key), 0.0)
        return merged
    except Exception:
        return copy.deepcopy(DEFAULTS)


def increment_catch(stats, n=1):
    """Return a NEW stats dict with ``fishing_catches`` increased by ``n``."""
    base = validate(stats)
    base['fishing_catches'] = base['fishing_catches'] + _coerce_int_nonneg(n, 0)
    return base


def increment_puzzle(stats, n=1):
    """Return a NEW stats dict with ``puzzles_solved`` increased by ``n``."""
    base = validate(stats)
    base['puzzles_solved'] = base['puzzles_solved'] + _coerce_int_nonneg(n, 0)
    return base


def add_fishing_runtime(stats, seconds):
    """Return a NEW stats dict with ``fishing_runtime_s`` increased by seconds."""
    base = validate(stats)
    base['fishing_runtime_s'] = (
        base['fishing_runtime_s'] + _coerce_float_nonneg(seconds, 0.0))
    return base


def add_puzzler_runtime(stats, seconds):
    """Return a NEW stats dict with ``puzzler_runtime_s`` increased by seconds."""
    base = validate(stats)
    base['puzzler_runtime_s'] = (
        base['puzzler_runtime_s'] + _coerce_float_nonneg(seconds, 0.0))
    return base


def load(path=DEFAULT_STATS_PATH):
    """Load + validate stats. Never raises -> validated defaults on any error."""
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            raw = json.loads(handle.read())
    except (OSError, ValueError):
        return validate(DEFAULTS)
    except Exception:
        return validate(DEFAULTS)
    return validate(raw)


# os.replace on Windows fails with PermissionError (WinError 5 / sharing
# violation) when another thread is mid-replace on, or has open, the SAME
# destination at that instant -- even with a unique temp name and no readers.
# A short bounded retry absorbs these transient collisions so concurrent
# writers don't silently drop writes. POSIX rename is already atomic, so the
# loop simply succeeds on the first pass there.
_REPLACE_RETRIES = 10
_REPLACE_BACKOFF_S = 0.01


def save(stats, path=DEFAULT_STATS_PATH):
    """Atomically write validated stats as JSON. Returns ``bool``; never raises.

    Writes a UNIQUE temp file in the same directory then ``os.replace`` so a
    crash mid-write never leaves a truncated ``stats.json`` (same guarantee as
    updater.py's *.part rename). The temp name is per-call unique (pid + a
    monotonic counter) so concurrent writers never collide on a shared ``.tmp``.
    The ``os.replace`` is retried a few times with a tiny backoff to ride out
    Windows sharing-violation (WinError 5) races, where two simultaneous
    replaces -- or a concurrent reader -- on the destination would otherwise
    make the call fail and silently drop the write.
    """
    path = str(path)
    tmp = '{}.{}.{}.tmp'.format(path, os.getpid(), _next_tmp_seq())
    try:
        normalized = validate(stats)
        with open(tmp, 'w', encoding='utf-8') as handle:
            handle.write(json.dumps(normalized, indent=2, ensure_ascii=False))
        _replace_with_retry(tmp, path)
        return True
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


def _replace_with_retry(tmp, path):
    """``os.replace(tmp, path)`` retried on transient Windows sharing violations.

    Re-raises the last error if every attempt fails (the caller treats that as a
    failed save and cleans up the temp). On POSIX the first attempt succeeds.
    """
    last_exc = None
    for attempt in range(_REPLACE_RETRIES):
        try:
            os.replace(tmp, path)
            return
        except PermissionError as exc:   # Windows sharing violation -> retry
            last_exc = exc
            time.sleep(_REPLACE_BACKOFF_S * (attempt + 1))
    if last_exc is not None:
        raise last_exc
    # Loop body always either returns or sets last_exc; defensive fallthrough.
    os.replace(tmp, path)


_TMP_SEQ_LOCK = threading.Lock()
_TMP_SEQ = 0


def _next_tmp_seq():
    """Process-unique increasing integer for temp-file naming. Never raises."""
    global _TMP_SEQ
    try:
        with _TMP_SEQ_LOCK:
            _TMP_SEQ += 1
            return _TMP_SEQ
    except Exception:
        return 0
