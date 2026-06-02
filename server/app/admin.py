# -*- coding: utf-8 -*-
"""Admin surface: ban/unban by HWID or username + delete entries (GDPR erasure).

Auth is a STRONG env-var token (ADMIN_TOKEN) compared with
``hmac.compare_digest`` (constant-time) -- the token is NEVER embedded in the
open-source client. Exposed both as a protected /admin/* path (token header)
AND via the CLI (server/cli.py), which imports these same functions.
"""

import hmac
import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from . import db

router = APIRouter()


def require_admin(token):
    """Constant-time check of the admin token. Raises 401/503 on failure.

    503 if ADMIN_TOKEN is unset (fail closed -- never allow admin without a
    configured secret). 401 on mismatch.
    """
    expected = os.environ.get('ADMIN_TOKEN', '')
    if not expected:
        raise HTTPException(status_code=503, detail='admin disabled (no token)')
    if not token or not hmac.compare_digest(str(token), expected):
        raise HTTPException(status_code=401, detail='unauthorized')
    return True


def ban(kind, value, reason=None):
    """Ban an HWID or username (pure DB op; used by route + CLI)."""
    _check_kind(kind)
    db.add_ban(kind, value, reason)
    return {'status': 'ok', 'banned': {'kind': kind, 'value': value}}


def unban(kind, value):
    """Remove a ban (pure DB op)."""
    _check_kind(kind)
    removed = db.remove_ban(kind, value)
    return {'status': 'ok', 'removed': removed}


def delete(kind, value):
    """Delete all submissions for an HWID or username (GDPR erasure)."""
    _check_kind(kind)
    removed = db.delete_entries(kind, value)
    return {'status': 'ok', 'deleted_rows': removed}


def _check_kind(kind):
    if kind not in ('hwid', 'username'):
        raise HTTPException(status_code=400, detail="kind must be hwid|username")


class _AdminAction(BaseModel):
    kind: str
    value: str
    reason: str = None


@router.post('/admin/ban')
async def admin_ban(body: _AdminAction, x_admin_token: str = Header(None)):
    require_admin(x_admin_token)
    return ban(body.kind, body.value, body.reason)


@router.post('/admin/unban')
async def admin_unban(body: _AdminAction, x_admin_token: str = Header(None)):
    require_admin(x_admin_token)
    return unban(body.kind, body.value)


@router.post('/admin/delete')
async def admin_delete(body: _AdminAction, x_admin_token: str = Header(None)):
    require_admin(x_admin_token)
    return delete(body.kind, body.value)


@router.get('/admin/bans')
async def admin_list_bans(x_admin_token: str = Header(None)):
    require_admin(x_admin_token)
    return {'bans': db.list_bans()}
