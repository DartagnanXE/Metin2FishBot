# -*- coding: utf-8 -*-
"""GET /leaderboard?period=daily|all -- cached, aggregated, excludes banned.

A short in-process cache (CACHE_TTL_S, default 30s) blunts scraping and repeated
refresh clicks. The aggregation (MAX counters per identity, banned excluded)
lives in db.leaderboard.
"""

import os
import time
import threading

from fastapi import APIRouter, Query

from .schemas import LeaderboardOut, LeaderboardEntry
from . import db

router = APIRouter()

CACHE_TTL_S = int(os.environ.get('CACHE_TTL_S', '30'))
_CACHE_LOCK = threading.Lock()
_CACHE = {}                 # period -> (fetched_at, payload)


def _cached(period):
    now = time.time()
    with _CACHE_LOCK:
        hit = _CACHE.get(period)
        if hit and now - hit[0] < CACHE_TTL_S:
            return hit[1]
    rows = db.leaderboard(period=period)
    entries = [
        LeaderboardEntry(
            rank=r['rank'], username=r['username'],
            fishing_catches=r['fishing_catches'],
            puzzles_solved=r['puzzles_solved'],
            fishing_runtime_s=r['fishing_runtime_s'],
            puzzler_runtime_s=r['puzzler_runtime_s'])
        for r in rows
    ]
    payload = LeaderboardOut(period=period, entries=entries)
    with _CACHE_LOCK:
        _CACHE[period] = (now, payload)
    return payload


@router.get('/leaderboard', response_model=LeaderboardOut)
async def leaderboard(period: str = Query('all', pattern='^(all|daily)$')):
    """Return the cached aggregated leaderboard for the requested period."""
    return _cached(period)
