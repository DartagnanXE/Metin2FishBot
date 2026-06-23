# -*- coding: utf-8 -*-
"""Ranking telemetry IO -- stdlib urllib + ONE daemon sender (mirrors updater.py).

Two responsibilities, both designed to NEVER block or crash the Tk UI:

(a) SENDER -- :func:`start_sender` spawns a single daemon thread that, every
    ``interval`` seconds, POSTs the current stats payload (HTTPS JSON) to the
    configured ``/submit`` endpoint. It catches ALL network errors and backs off
    exponentially on failure. If the server replies ``banned`` it sets a stop
    flag, calls ``on_status('banned')`` and stops sending. The sender is GATED:
    it does NOTHING while there is no install id / submit url, or while the
    installation is blocked (the anonymous counter has no user opt-out; a chosen
    name is NOT required). ``get_state`` is a thread-safe snapshot callback the
    UI provides.

(b) LEADERBOARD -- :func:`fetch_leaderboard` does a cached GET and returns a
    dict (or ``None`` on any error). Called on a worker thread by the ranking
    tab; the UI marshals the result back via ``app.after(0, ...)`` (the worker
    NEVER touches Tk directly -- that would crash, exactly like updater.py).

No secret is embedded (open source); all abuse defence is server-side. Stdlib
only (json/urllib/threading/time).
"""

import json
import threading
import time
import urllib.request

DEFAULT_INTERVAL = 120          # seconds between submits (configurable)
HTTP_TIMEOUT = 10               # per-request timeout (never hang the thread)
BACKOFF_START = 5               # first retry delay after a failure (seconds)
BACKOFF_MAX = 600               # cap the exponential backoff (10 min)
_USER_AGENT = 'Metin2MultiTool-Telemetry'

# Module-level handle to the single running sender thread + its stop flag. A new
# start_sender replaces the previous one (stop the old, start the new).
_sender_thread = None
_stop_event = threading.Event()

# Tiny in-process leaderboard cache: {url: (fetched_at, data)}.
_LEADERBOARD_CACHE = {}
_LEADERBOARD_CACHE_TTL = 30     # seconds


def check_name(leaderboard_url, username, hwid, timeout=HTTP_TIMEOUT):
    """Ask the server whether a self-chosen ``username`` is still available.

    Derives the ``/check_name`` endpoint from the leaderboard URL (same host) and
    GETs it. Returns ``{'available': bool, 'owner_is_self': bool, 'name': str}``.
    NEVER raises: on ANY problem (offline, timeout, bad body, empty URL) it returns
    ``available=True`` so a network hiccup can never trap a user out of choosing a
    name -- the SERVER still enforces uniqueness at display time, this call is only
    a proactive convenience. An empty name is always available (anonymous). Stdlib
    only (urllib + json).
    """
    name = (username or '').strip()
    if not name:
        return {'available': True, 'owner_is_self': False, 'name': ''}
    try:
        from urllib.parse import urlencode, urlsplit, urlunsplit
        base = str(leaderboard_url or '').strip()
        if not base:
            return {'available': True, 'owner_is_self': False, 'name': name}
        parts = urlsplit(base)
        # same host/scheme, swap the last path segment -> .../check_name
        path = parts.path.rsplit('/', 1)[0] + '/check_name'
        query = urlencode({'username': name, 'hwid': str(hwid or '')[:64]})
        url = urlunsplit((parts.scheme, parts.netloc, path, query, ''))
        req = urllib.request.Request(
            url, method='GET', headers={'User-Agent': _USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        if not isinstance(data, dict):
            return {'available': True, 'owner_is_self': False, 'name': name}
        return {'available': bool(data.get('available', True)),
                'owner_is_self': bool(data.get('owner_is_self', False)),
                'name': name}
    except Exception:
        return {'available': True, 'owner_is_self': False, 'name': name}


def post_submit(url, payload, timeout=HTTP_TIMEOUT):
    """POST ``payload`` (dict) as JSON to ``url``. Returns ``(status, data)``.

    ``status`` is one of ``'ok'`` | ``'banned'`` | ``'error'`` and never raises:
      * HTTP 200 with a normal body  -> ``('ok', data)``
      * a body whose ``status`` is ``'banned'`` (any HTTP code) -> ``('banned', data)``
      * any exception / non-200 / unparseable -> ``('error', None)``

    The ``banned`` signal lets the sender stop + the UI hide the ranking.
    """
    try:
        body = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            url, data=body, method='POST',
            headers={'User-Agent': _USER_AGENT,
                     'Content-Type': 'application/json',
                     # Pass the install id as a header too, so nginx can
                     # rate-limit per install (the X-HWID header name is kept
                     # to avoid churn; it now carries the random install id,
                     # not a device id) without parsing the body.
                     'X-HWID': str(payload.get('hwid', ''))[:64]})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = getattr(resp, 'status', 200)
            raw = resp.read()
        data = None
        try:
            data = json.loads(raw.decode('utf-8'))
        except Exception:
            data = None
        if isinstance(data, dict) and data.get('status') == 'banned':
            return ('banned', data)
        if status_code in (200, None):
            return ('ok', data)
        return ('error', None)
    except Exception as exc:
        # A banned response may arrive as an HTTPError (e.g. 403) with a JSON
        # body -> inspect it before giving up so a ban is honoured.
        banned = _banned_from_exception(exc)
        if banned is not None:
            return ('banned', banned)
        return ('error', None)


def _banned_from_exception(exc):
    """If ``exc`` is an HTTPError carrying a ``status: banned`` body, return that
    dict; else ``None``. Never raises."""
    try:
        read = getattr(exc, 'read', None)
        if not callable(read):
            return None
        data = json.loads(read().decode('utf-8'))
        if isinstance(data, dict) and data.get('status') == 'banned':
            return data
    except Exception:
        return None
    return None


def fetch_leaderboard(url, timeout=HTTP_TIMEOUT, force=False):
    """GET the leaderboard JSON from ``url`` (cached). Returns a dict or ``None``.

    Caches per-URL for :data:`_LEADERBOARD_CACHE_TTL` seconds to blunt rapid
    refresh clicks / scraping. Never raises (any error -> ``None``). MUST be
    called from a worker thread; the caller marshals the result into the UI.

    ``force=True`` BYPASSES the cache READ (always re-fetches over the network)
    while still WRITING the fresh result back to the cache. This is what the
    explicit Refresh button uses: Refresh first POSTs the user's current stats
    out-of-band, so the freshly fetched board must reflect that submit -- the 30s
    TTL would otherwise return a stale pre-submit snapshot and the user's own row
    would lag (the very confusion the submit-then-fetch flow exists to avoid).
    The auto-load on tab-open leaves ``force=False`` so rapid re-opens still hit
    the cache.
    """
    try:
        if not force:
            cached = _LEADERBOARD_CACHE.get(url)
            if cached is not None:
                fetched_at, data = cached
                if time.time() - fetched_at < _LEADERBOARD_CACHE_TTL:
                    return data
        req = urllib.request.Request(
            url, headers={'User-Agent': _USER_AGENT,
                          'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if getattr(resp, 'status', 200) not in (200, None):
                return None
            raw = resp.read()
        data = json.loads(raw.decode('utf-8'))
        if not isinstance(data, dict):
            return None
        _LEADERBOARD_CACHE[url] = (time.time(), data)
        return data
    except Exception:
        return None


def _gated(state):
    """True iff a snapshot permits sending (anonymous always-on counter).

    Requires a submit URL AND a non-empty install id (carried as ``state['hwid']``
    -- the wire field is unchanged, it now holds the random install id). A chosen
    ``username`` is NOT required (everyone with an id+url submits anonymously).
    ``enabled`` is honoured ONLY as the BLOCKED stop-signal: the app sets it
    False when the installation was blocked, which halts sending."""
    try:
        if not state.get('enabled'):
            return False
        if not str(state.get('hwid') or '').strip():
            return False
        if not str(state.get('submit_url') or '').strip():
            return False
        return True
    except Exception:
        return False


def start_sender(get_state, on_status=None, interval=DEFAULT_INTERVAL,
                 idle_poll=2.0):
    """Start the single daemon sender thread. Returns the ``Thread`` (or ``None``).

    ``get_state`` -> a thread-safe snapshot dict the UI provides::

        {'enabled': bool, 'username': str, 'hwid': str, 'submit_url': str,
         'interval_s': int, 'payload': dict}

    where ``payload`` is the already-built submit dict (telemetry.payload). The
    sender:
      * does NOTHING while ``enabled`` is False (blocked) or the install id/url
        is empty (re-checked every loop, so a name set later / a block takes
        effect live);
      * POSTs ``payload`` every ``interval_s`` (snapshot value wins; falls back
        to ``interval``);
      * on a network error backs off exponentially up to :data:`BACKOFF_MAX`;
      * on a ``banned`` reply sets the stop flag, calls ``on_status('banned')``
        once, and exits.

    ``on_status`` runs on the WORKER thread -> the UI must marshal via
    ``app.after(0, ...)``. ``idle_poll`` is the re-check cadence while gated/
    disabled (default 2 s; lowered only by tests for deterministic timing).
    Never raises; on any setup failure returns ``None``.
    """
    global _sender_thread, _stop_event
    stop_sender()                       # replace any previous sender
    _stop_event = threading.Event()
    stop_event = _stop_event
    try:
        idle_poll = float(idle_poll)
        if idle_poll <= 0:
            idle_poll = 2.0
    except Exception:
        idle_poll = 2.0

    def _emit(status):
        if callable(on_status):
            try:
                on_status(status)
            except Exception:
                pass

    def _worker():
        backoff = BACKOFF_START
        # idle_poll (gated re-check cadence) is captured from the enclosing
        # start_sender scope: cheap polling that lets opt-in flip live.
        started_logged = False
        while not stop_event.is_set():
            try:
                state = get_state() if callable(get_state) else None
            except Exception:
                state = None
            if not isinstance(state, dict) or not _gated(state):
                if stop_event.wait(idle_poll):
                    break
                continue
            if not started_logged:
                started_logged = True
                _emit('started')
            try:
                payload = state.get('payload') or {}
                url = state.get('submit_url')
                status, _data = post_submit(url, payload)
            except Exception:
                status = 'error'
            if status == 'banned':
                _emit('banned')
                stop_event.set()
                break
            if status == 'ok':
                backoff = BACKOFF_START
                _emit('ok')
                wait_s = _interval_of(state, interval)
            else:
                # exponential backoff on failure (capped)
                wait_s = backoff
                _emit('backoff:{}'.format(backoff))
                backoff = min(backoff * 2, BACKOFF_MAX)
            if stop_event.wait(max(1, wait_s)):
                break
        _emit('stopped')

    try:
        _sender_thread = threading.Thread(
            target=_worker, name='telemetry-sender', daemon=True)
        _sender_thread.start()
        return _sender_thread
    except Exception:
        return None


def _interval_of(state, fallback):
    try:
        v = int(state.get('interval_s', fallback))
        return v if v > 0 else fallback
    except Exception:
        return fallback


def stop_sender():
    """Signal the running sender thread to stop (non-blocking). Never raises."""
    try:
        _stop_event.set()
    except Exception:
        pass
