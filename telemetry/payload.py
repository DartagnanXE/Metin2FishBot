# -*- coding: utf-8 -*-
"""Build + validate the ranking submit payload (PURE, headless-testable).

The payload schema is the EXACT contract with the server (server/app/schemas.py
SubmitIn). We enforce client-side length caps + numeric coercion BEFORE sending
(defensive, mirrors interface/config.py) so a corrupt stats.json can never push
garbage onto the wire. Pure + deterministic given ``now``; never raises. No JSON
encoding here -- the caller (client.py) encodes.

Stdlib only.
"""

# Bumped only if the wire schema changes (server must match).
SCHEMA_VERSION = 1

# Client-side caps (the server re-validates -- never trust the client, even our
# own). Kept in sync with interface.config.USERNAME_MAXLEN / hwid.HWID_HEX_LEN.
USERNAME_MAXLEN = 32
HWID_MAXLEN = 64
APP_VERSION_MAXLEN = 32

# Plausibility ceilings mirrored from stats sanity (the server enforces the hard
# maxima; here we just refuse to send absurd values).
_MAX_COUNT = 100_000_000
_MAX_RUNTIME_S = 100_000_000.0


def _clamp_int(value, lo, hi):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return lo
    if n < lo:
        return lo
    if n > hi:
        return hi
    return n


def _clamp_float(value, lo, hi):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return lo
    if f != f:            # NaN
        return lo
    if f < lo:
        return lo
    if f > hi:
        return hi
    return f


def _clean_str(value, maxlen):
    if value is None:
        return ''
    try:
        s = str(value).strip()
    except Exception:
        return ''
    return s[:maxlen]


def clamp_payload(d):
    """Return a NEW payload dict with every field coerced + capped to schema.

    Defensive normalisation of an already-shaped payload (idempotent). Unknown
    keys are dropped; missing keys get safe defaults. Never raises.
    """
    src = d if isinstance(d, dict) else {}
    return {
        'username': _clean_str(src.get('username'), USERNAME_MAXLEN),
        'hwid': _clean_str(src.get('hwid'), HWID_MAXLEN),
        'fishing_catches': _clamp_int(src.get('fishing_catches'), 0, _MAX_COUNT),
        'puzzles_solved': _clamp_int(src.get('puzzles_solved'), 0, _MAX_COUNT),
        'fishing_runtime_s': _clamp_float(
            src.get('fishing_runtime_s'), 0.0, _MAX_RUNTIME_S),
        'puzzler_runtime_s': _clamp_float(
            src.get('puzzler_runtime_s'), 0.0, _MAX_RUNTIME_S),
        'app_version': _clean_str(src.get('app_version'), APP_VERSION_MAXLEN),
        'ts': _clamp_int(src.get('ts'), 0, 4_102_444_800),   # < year 2100
    }


def build_submit(username, hwid, stats, app_version, now):
    """Build the validated submit payload from stats + identity.

    Maps the four counters from a stats dict (stats.py shape) into the wire
    schema, attaches identity + app version, and a deterministic integer
    timestamp ``ts`` derived from ``now`` (a ``datetime`` or epoch number).
    Returns a NEW dict already passed through :func:`clamp_payload`. Pure,
    deterministic given ``now``; never raises.
    """
    stats = stats if isinstance(stats, dict) else {}
    ts = _to_epoch(now)
    raw = {
        'username': username,
        'hwid': hwid,
        'fishing_catches': stats.get('fishing_catches', 0),
        'puzzles_solved': stats.get('puzzles_solved', 0),
        'fishing_runtime_s': stats.get('fishing_runtime_s', 0.0),
        'puzzler_runtime_s': stats.get('puzzler_runtime_s', 0.0),
        'app_version': app_version,
        'ts': ts,
    }
    return clamp_payload(raw)


def _to_epoch(now):
    """Turn ``now`` (datetime or epoch int/float) into an int epoch second.

    Naive datetimes are treated as UTC (deterministic for tests). Never raises;
    garbage -> 0.
    """
    try:
        # datetime?
        if hasattr(now, 'timestamp'):
            try:
                return int(now.timestamp())
            except Exception:
                # naive datetime on some platforms -> compute against epoch
                from datetime import timezone
                if getattr(now, 'tzinfo', None) is None:
                    now = now.replace(tzinfo=timezone.utc)
                return int(now.timestamp())
        return int(now)
    except Exception:
        return 0
