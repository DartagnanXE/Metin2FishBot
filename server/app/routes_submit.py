# -*- coding: utf-8 -*-
"""POST /submit -- validate, reject banned/implausible, rate-limit, store.

Never trusts the client:
  * pydantic SubmitIn enforces schema/types/length/numeric maxima (422 on bad).
  * banned HWID or username -> {status: 'banned'} (the client stops + hides).
  * per-HWID + per-IP in-process rate-limit (in addition to nginx).
  * implausible jumps vs the last stored value for that identity are rejected.
  * the raw IP is NEVER stored -- only a salted hash (GDPR).
"""

import hashlib
import os
import time
import threading

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .schemas import SubmitIn
from . import db

router = APIRouter()

# Per-key rate limit: at most N submits per window per HWID and per IP.
RATE_WINDOW_S = int(os.environ.get('RATE_LIMIT_WINDOW_S', '60'))
RATE_MAX = int(os.environ.get('RATE_LIMIT_MAX', '5'))
# Salt for IP hashing (GDPR: store a hash, not the raw IP). MUST be set in prod.
IP_HASH_SALT = os.environ.get('IP_HASH_SALT', 'change-me-ip-salt')

# Implausible-jump guard: a single submit may not increase a cumulative counter
# by more than this (a real session cannot realistically jump by millions).
MAX_DELTA_COUNT = int(os.environ.get('MAX_DELTA_COUNT', '100000'))
MAX_DELTA_RUNTIME_S = float(os.environ.get('MAX_DELTA_RUNTIME_S', '172800'))  # 48h

_RATE_LOCK = threading.Lock()
_HITS = {}                  # key -> [timestamps within the window]
# Bound the in-process map: stale keys are otherwise only pruned when that SAME
# key is hit again, so an attacker rotating HWIDs/IPs could grow it without
# bound (slow mem-exhaustion vs the 256m container). We sweep globally every Nth
# call and whenever the map exceeds a hard ceiling, dropping keys whose bucket
# is empty after pruning. nginx's per-IP flood limit already bounds the real
# rate; this just closes the unbounded-growth vector for defence-in-depth.
_SWEEP_EVERY = 256          # run a global sweep at most every Nth checked key
_HITS_CEILING = 50000       # force a sweep once the map grows past this
_calls_since_sweep = 0


def _sweep_locked(now):
    """Drop keys with no timestamps inside the window. Caller holds _RATE_LOCK."""
    stale = [k for k, ts in _HITS.items()
             if not any(now - t < RATE_WINDOW_S for t in ts)]
    for k in stale:
        del _HITS[k]


def _rate_limited(key):
    global _calls_since_sweep
    now = time.time()
    with _RATE_LOCK:
        _calls_since_sweep += 1
        if _calls_since_sweep >= _SWEEP_EVERY or len(_HITS) > _HITS_CEILING:
            _calls_since_sweep = 0
            _sweep_locked(now)
        bucket = [t for t in _HITS.get(key, []) if now - t < RATE_WINDOW_S]
        if len(bucket) >= RATE_MAX:
            _HITS[key] = bucket
            return True
        bucket.append(now)
        _HITS[key] = bucket
        return False


def _hash_ip(ip):
    try:
        return hashlib.sha256((IP_HASH_SALT + str(ip)).encode('utf-8')).hexdigest()
    except Exception:
        return None


def _client_ip(request):
    """Best-effort REAL client IP, resistant to a forged X-Forwarded-For.

    The app sits behind our own nginx, which sets ``X-Real-IP`` to the genuine
    edge peer (``$remote_addr``, made trustworthy via ``set_real_ip_from`` +
    ``real_ip_header`` in telemetry.conf). We therefore trust ``X-Real-IP``
    FIRST. We deliberately do NOT trust the left-most ``X-Forwarded-For`` entry:
    nginx APPENDS the real peer to whatever the client sent
    (``$proxy_add_x_forwarded_for``), so the left-most value is attacker-chosen.
    If only XFF is present we take the RIGHT-MOST entry -- the hop nginx itself
    appended -- never the client-supplied left side. Falls back to the socket
    peer. This keeps the per-IP limiter and the stored ip_hash honest.
    """
    real = request.headers.get('x-real-ip')
    if real and real.strip():
        return real.strip()
    xff = request.headers.get('x-forwarded-for')
    if xff:
        parts = [p.strip() for p in xff.split(',') if p.strip()]
        if parts:
            return parts[-1]          # right-most = the hop nginx appended
    client = request.client
    return client.host if client else 'unknown'


def _implausible(payload, last):
    """True iff this submit jumps a counter implausibly vs the last stored row."""
    if last is None:
        # First-ever submit: only the absolute caps (already enforced by schema)
        # apply. Nothing to compare against.
        return False
    try:
        if (payload.fishing_catches - int(last['fishing_catches'])
                > MAX_DELTA_COUNT):
            return True
        if (payload.puzzles_solved - int(last['puzzles_solved'])
                > MAX_DELTA_COUNT):
            return True
        if (payload.fishing_runtime_s - float(last['fishing_runtime_s'])
                > MAX_DELTA_RUNTIME_S):
            return True
        if (payload.puzzler_runtime_s - float(last['puzzler_runtime_s'])
                > MAX_DELTA_RUNTIME_S):
            return True
    except Exception:
        return False
    return False


@router.post('/submit')
async def submit(payload: SubmitIn, request: Request):
    """Accept a submission. Returns {status:'ok'} or {status:'banned'}.

    422 is returned automatically by FastAPI when the body fails SubmitIn.
    """
    # 1) Bans (HWID OR username) -> tell the client to stop.
    if db.is_banned('hwid', payload.hwid) or db.is_banned('username',
                                                          payload.username):
        return JSONResponse(status_code=403, content={'status': 'banned'})

    ip = _client_ip(request)

    # 2) Rate limit per HWID and per IP (app-level; nginx adds another layer).
    if _rate_limited('hwid:' + payload.hwid) or _rate_limited('ip:' + ip):
        return JSONResponse(status_code=429,
                            content={'status': 'error', 'detail': 'rate_limited'})

    # 3) Implausible jump vs last stored value -> reject (do not poison the board).
    last = db.last_for_identity(payload.hwid)
    if _implausible(payload, last):
        return JSONResponse(status_code=422,
                            content={'status': 'error',
                                     'detail': 'implausible_jump'})

    # 4) Store (hashed IP, never raw).
    row = payload.model_dump() if hasattr(payload, 'model_dump') \
        else payload.dict()
    row['ip_hash'] = _hash_ip(ip)
    try:
        db.insert_submission(row)
    except Exception:
        return JSONResponse(status_code=500,
                            content={'status': 'error', 'detail': 'store_failed'})
    return {'status': 'ok'}
