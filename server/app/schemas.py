# -*- coding: utf-8 -*-
"""Pydantic models with STRICT validation matching the client payload.

The schema is the contract with telemetry/payload.py on the client. We never
trust the client: length caps + type coercion + sane numeric maxima at the
boundary. Implausible values are rejected (422) before they ever touch the DB.
"""

from typing import List

try:
    # pydantic v2
    from pydantic import BaseModel, Field, field_validator
    _PYDANTIC_V2 = True
except Exception:                       # pragma: no cover - v1 fallback
    from pydantic import BaseModel, Field, validator as field_validator
    _PYDANTIC_V2 = False


# Sane maxima -- reject implausible submissions outright. Mirrors the client's
# clamp ceilings (telemetry/payload.py) and interface/config.py STATS_MAX_*.
MAX_COUNT = 100_000_000          # 100M catches / puzzles
MAX_RUNTIME_S = 100_000_000.0    # ~3 years of seconds
USERNAME_MAXLEN = 32
HWID_MAXLEN = 64
APP_VERSION_MAXLEN = 32


class SubmitIn(BaseModel):
    """One ranking submission from a client (POST /submit body)."""

    username: str = Field(min_length=1, max_length=USERNAME_MAXLEN)
    hwid: str = Field(min_length=1, max_length=HWID_MAXLEN)
    fishing_catches: int = Field(ge=0, le=MAX_COUNT)
    puzzles_solved: int = Field(ge=0, le=MAX_COUNT)
    fishing_runtime_s: float = Field(ge=0, le=MAX_RUNTIME_S)
    puzzler_runtime_s: float = Field(ge=0, le=MAX_RUNTIME_S)
    app_version: str = Field(min_length=1, max_length=APP_VERSION_MAXLEN)
    ts: int = Field(ge=0, le=4_102_444_800)   # epoch seconds, < year 2100

    @field_validator('username')
    @classmethod
    def _strip_username(cls, v):
        v = (v or '').strip()
        if not v:
            raise ValueError('username must not be blank')
        return v


class LeaderboardEntry(BaseModel):
    """One row on the public leaderboard."""

    rank: int
    username: str
    fishing_catches: int
    puzzles_solved: int
    fishing_runtime_s: float
    puzzler_runtime_s: float


class LeaderboardOut(BaseModel):
    """GET /leaderboard response envelope."""

    period: str
    entries: List[LeaderboardEntry]
