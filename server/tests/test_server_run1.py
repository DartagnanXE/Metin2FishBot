# -*- coding: utf-8 -*-
"""Run-1 QA: server API in-process tests (no live box).

Extends server/tests/test_server.py. The DB-layer cases run unconditionally; the
HTTP cases use FastAPI's TestClient when fastapi is installed (else skip). This
file targets the spec's explicit asks:

  * SUBMIT VALIDATION rejects bad / oversized / IMPLAUSIBLE input (422), and the
    implausible-jump guard (_implausible) is unit-tested directly + end-to-end.
  * LEADERBOARD SHAPE: the response envelope {period, entries[]} with ranked,
    aggregated rows; period query is constrained to all|daily.
  * BAN / DELETE: a banned identity is told to stop (403) and excluded from the
    board; admin delete performs GDPR erasure; unban restores.
  * RATE-LIMIT logic: the in-process limiter both as a unit (_rate_limited) and
    end-to-end (the N+1-th submit in a window -> 429).
  * GDPR: the raw IP is never stored -- only a salted hash.

Run:  python -m pytest server/tests -q
"""

import os
import tempfile
import time
import unittest

from server.app import db
from server.app import routes_submit as rs

try:
    from server.app import routes_leaderboard as rlb
except Exception:                       # fastapi may be absent
    rlb = None


def _reset_server_state():
    """Clear all in-process module state so tests don't leak into each other:
    the rate-limit buckets AND the leaderboard response cache (30 s TTL)."""
    with rs._RATE_LOCK:
        rs._HITS.clear()
    if rlb is not None:
        with rlb._CACHE_LOCK:
            rlb._CACHE.clear()

try:
    from fastapi.testclient import TestClient
    _HAS_FASTAPI = True
except Exception:
    _HAS_FASTAPI = False


# ---------------------------------------------------------------------------
# Pure DB / guard units (no HTTP, always run)
# ---------------------------------------------------------------------------
class TestImplausibleGuard(unittest.TestCase):
    """rs._implausible: first submit always ok; huge jumps vs last -> reject."""

    class _P:                       # tiny payload stand-in (attr access)
        def __init__(self, c=0, p=0, fr=0.0, pr=0.0):
            self.fishing_catches = c
            self.puzzles_solved = p
            self.fishing_runtime_s = fr
            self.puzzler_runtime_s = pr

    def test_first_submit_never_implausible(self):
        self.assertFalse(rs._implausible(self._P(c=10 ** 6), None))

    def test_small_increment_ok(self):
        last = {'fishing_catches': 100, 'puzzles_solved': 0,
                'fishing_runtime_s': 0.0, 'puzzler_runtime_s': 0.0}
        self.assertFalse(rs._implausible(self._P(c=150), last))

    def test_huge_catch_jump_rejected(self):
        last = {'fishing_catches': 0, 'puzzles_solved': 0,
                'fishing_runtime_s': 0.0, 'puzzler_runtime_s': 0.0}
        self.assertTrue(
            rs._implausible(self._P(c=rs.MAX_DELTA_COUNT + 1), last))

    def test_huge_runtime_jump_rejected(self):
        last = {'fishing_catches': 0, 'puzzles_solved': 0,
                'fishing_runtime_s': 0.0, 'puzzler_runtime_s': 0.0}
        self.assertTrue(
            rs._implausible(self._P(fr=rs.MAX_DELTA_RUNTIME_S + 1), last))

    def test_decrease_is_not_implausible(self):
        # A lower value than last (e.g. reset) is not a forbidden *jump*.
        last = {'fishing_catches': 500, 'puzzles_solved': 0,
                'fishing_runtime_s': 0.0, 'puzzler_runtime_s': 0.0}
        self.assertFalse(rs._implausible(self._P(c=10), last))


class TestRateLimiterUnit(unittest.TestCase):
    def setUp(self):
        _reset_server_state()
        self._orig_max = rs.RATE_MAX

    def tearDown(self):
        rs.RATE_MAX = self._orig_max
        _reset_server_state()

    def test_allows_up_to_max_then_blocks(self):
        rs.RATE_MAX = 3
        key = 'hwid:test'
        self.assertFalse(rs._rate_limited(key))   # 1
        self.assertFalse(rs._rate_limited(key))   # 2
        self.assertFalse(rs._rate_limited(key))   # 3
        self.assertTrue(rs._rate_limited(key))    # 4 -> blocked

    def test_separate_keys_independent(self):
        rs.RATE_MAX = 1
        self.assertFalse(rs._rate_limited('hwid:a'))
        self.assertFalse(rs._rate_limited('hwid:b'))   # different key, allowed
        self.assertTrue(rs._rate_limited('hwid:a'))    # a now blocked

    def test_ip_hash_is_not_raw_ip(self):
        h = rs._hash_ip('203.0.113.7')
        self.assertNotIn('203.0.113.7', str(h))
        self.assertEqual(len(h), 64)               # sha256 hex

    def test_sweep_evicts_stale_keys(self):
        # Stale buckets (no timestamp within the window) must be globally
        # evicted so a rotating-identity attacker cannot grow the map unbounded.
        with rs._RATE_LOCK:
            rs._HITS.clear()
            old = time.time() - (rs.RATE_WINDOW_S + 100)
            rs._HITS['ip:1.1.1.1'] = [old, old]          # all expired
            rs._HITS['hwid:stale'] = [old]               # expired
            rs._HITS['ip:2.2.2.2'] = [time.time()]       # fresh -> kept
            rs._sweep_locked(time.time())
            keys = set(rs._HITS)
        self.assertIn('ip:2.2.2.2', keys)
        self.assertNotIn('ip:1.1.1.1', keys)
        self.assertNotIn('hwid:stale', keys)

    def test_periodic_sweep_bounds_map(self):
        # Drive many DISTINCT keys (each allowed once) with a tiny window so the
        # periodic sweep prunes them -> the map stays bounded, not 1 entry/key.
        orig_w, orig_every = rs.RATE_WINDOW_S, rs._SWEEP_EVERY
        try:
            rs.RATE_WINDOW_S = 0          # every bucket is immediately stale
            rs._SWEEP_EVERY = 50
            with rs._RATE_LOCK:
                rs._HITS.clear()
                rs._calls_since_sweep = 0
            for i in range(5000):
                rs._rate_limited('hwid:id-{}'.format(i))
            self.assertLessEqual(len(rs._HITS), rs._SWEEP_EVERY)
        finally:
            rs.RATE_WINDOW_S, rs._SWEEP_EVERY = orig_w, orig_every
            with rs._RATE_LOCK:
                rs._HITS.clear()


class _FakeReq:
    """Minimal Request stand-in: only .headers (dict-like) + .client are read."""

    class _Client:
        def __init__(self, host):
            self.host = host

    def __init__(self, headers=None, peer='198.51.100.9'):
        # Starlette headers are case-insensitive; mimic with lower-cased keys.
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.client = self._Client(peer) if peer else None


class TestClientIPAntiSpoof(unittest.TestCase):
    """_client_ip must not trust a forged left-most X-Forwarded-For."""

    def test_prefers_x_real_ip(self):
        req = _FakeReq(headers={'X-Real-IP': '203.0.113.5',
                                'X-Forwarded-For': '1.2.3.4, 203.0.113.5'})
        self.assertEqual(rs._client_ip(req), '203.0.113.5')

    def test_forged_leftmost_xff_is_ignored(self):
        # Attacker sends a spoofed left-most entry; nginx appends the real peer
        # on the RIGHT. With no X-Real-IP we must take the right-most hop.
        req = _FakeReq(headers={
            'X-Forwarded-For': '6.6.6.6, 203.0.113.5'}, peer=None)
        ip = rs._client_ip(req)
        self.assertEqual(ip, '203.0.113.5')
        self.assertNotEqual(ip, '6.6.6.6')

    def test_falls_back_to_socket_peer(self):
        req = _FakeReq(headers={}, peer='198.51.100.9')
        self.assertEqual(rs._client_ip(req), '198.51.100.9')

    def test_spoofed_ip_does_not_change_hashed_record(self):
        # The stored ip_hash must reflect the REAL ip (X-Real-IP), so a rotating
        # left-most XFF cannot pick the stored value or dodge the per-IP limit.
        a = _FakeReq(headers={'X-Real-IP': '203.0.113.5',
                              'X-Forwarded-For': 'aaaa, 203.0.113.5'})
        b = _FakeReq(headers={'X-Real-IP': '203.0.113.5',
                              'X-Forwarded-For': 'bbbb, 203.0.113.5'})
        self.assertEqual(rs._client_ip(a), rs._client_ip(b))
        self.assertEqual(rs._hash_ip(rs._client_ip(a)),
                         rs._hash_ip(rs._client_ip(b)))


class TestDBLeaderboardShape(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        db.init_db(os.path.join(self.dir, 'lb.db'))

    def _sub(self, **over):
        row = {'username': 'u', 'hwid': 'h', 'fishing_catches': 1,
               'puzzles_solved': 0, 'fishing_runtime_s': 1.0,
               'puzzler_runtime_s': 0.0, 'app_version': '1.0.5',
               'ts': int(time.time()), 'ip_hash': 'x'}
        row.update(over)
        return row

    def test_rows_ranked_and_ordered(self):
        db.insert_submission(self._sub(username='low', hwid='h1',
                                       fishing_catches=5))
        db.insert_submission(self._sub(username='high', hwid='h2',
                                       fishing_catches=50))
        lb = db.leaderboard('all')
        self.assertEqual([r['username'] for r in lb], ['high', 'low'])
        self.assertEqual(lb[0]['rank'], 1)
        self.assertEqual(lb[1]['rank'], 2)

    def test_row_has_all_counter_fields(self):
        db.insert_submission(self._sub(username='a', hwid='h1'))
        row = db.leaderboard('all')[0]
        for k in ('username', 'fishing_catches', 'puzzles_solved',
                  'fishing_runtime_s', 'puzzler_runtime_s', 'rank'):
            self.assertIn(k, row)

    def test_delete_then_unban_roundtrip(self):
        db.insert_submission(self._sub(username='a', hwid='h1'))
        db.add_ban('hwid', 'h1', 'spam')
        self.assertEqual(len(db.leaderboard('all')), 0)
        self.assertEqual(db.remove_ban('hwid', 'h1'), 1)
        self.assertEqual(len(db.leaderboard('all')), 1)
        self.assertEqual(db.delete_entries('hwid', 'h1'), 1)
        self.assertEqual(len(db.leaderboard('all')), 0)


# ---------------------------------------------------------------------------
# HTTP route tests (need fastapi)
# ---------------------------------------------------------------------------
@unittest.skipUnless(_HAS_FASTAPI, 'fastapi not installed')
class TestSubmitValidationHTTP(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.environ['DB_PATH'] = os.path.join(self.dir, 'r.db')
        os.environ['ADMIN_TOKEN'] = 'secret-token'
        db.init_db(os.environ['DB_PATH'])
        _reset_server_state()
        from server.app.main import create_app
        self.client = TestClient(create_app())

    def _payload(self, **over):
        p = {'username': 'bob', 'hwid': 'hbob', 'fishing_catches': 3,
             'puzzles_solved': 1, 'fishing_runtime_s': 5.0,
             'puzzler_runtime_s': 0.0, 'app_version': '1.0.5',
             'ts': int(time.time())}
        p.update(over)
        return p

    def test_rejects_negative_count(self):
        self.assertEqual(
            self.client.post('/submit',
                             json=self._payload(fishing_catches=-1)).status_code,
            422)

    def test_rejects_over_max_count(self):
        self.assertEqual(
            self.client.post(
                '/submit',
                json=self._payload(fishing_catches=10 ** 12)).status_code, 422)

    def test_rejects_oversized_hwid(self):
        self.assertEqual(
            self.client.post('/submit',
                             json=self._payload(hwid='h' * 200)).status_code,
            422)

    def test_rejects_oversized_app_version(self):
        self.assertEqual(
            self.client.post(
                '/submit',
                json=self._payload(app_version='v' * 200)).status_code, 422)

    def test_rejects_blank_username(self):
        self.assertEqual(
            self.client.post('/submit',
                             json=self._payload(username='   ')).status_code,
            422)

    def test_rejects_missing_field(self):
        bad = self._payload()
        del bad['ts']
        self.assertEqual(self.client.post('/submit', json=bad).status_code, 422)

    def test_rejects_future_ts_over_2100(self):
        self.assertEqual(
            self.client.post('/submit',
                             json=self._payload(ts=5_000_000_000)).status_code,
            422)

    def test_implausible_jump_rejected_end_to_end(self):
        # Seed a low baseline, then submit an enormous jump -> 422.
        self.assertEqual(
            self.client.post('/submit',
                             json=self._payload(fishing_catches=1)).status_code,
            200)
        big = self._payload(fishing_catches=rs.MAX_DELTA_COUNT + 5)
        r = self.client.post('/submit', json=big)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()['detail'], 'implausible_jump')


@unittest.skipUnless(_HAS_FASTAPI, 'fastapi not installed')
class TestLeaderboardAndBanHTTP(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.environ['DB_PATH'] = os.path.join(self.dir, 'r.db')
        os.environ['ADMIN_TOKEN'] = 'secret-token'
        db.init_db(os.environ['DB_PATH'])
        _reset_server_state()
        from server.app.main import create_app
        self.client = TestClient(create_app())

    def _payload(self, **over):
        p = {'username': 'bob', 'hwid': 'hbob', 'fishing_catches': 3,
             'puzzles_solved': 1, 'fishing_runtime_s': 5.0,
             'puzzler_runtime_s': 0.0, 'app_version': '1.0.5',
             'ts': int(time.time())}
        p.update(over)
        return p

    def test_leaderboard_envelope_shape(self):
        self.client.post('/submit', json=self._payload())
        lb = self.client.get('/leaderboard?period=all').json()
        self.assertEqual(lb['period'], 'all')
        self.assertIsInstance(lb['entries'], list)
        entry = lb['entries'][0]
        for k in ('rank', 'username', 'fishing_catches', 'puzzles_solved',
                  'fishing_runtime_s', 'puzzler_runtime_s'):
            self.assertIn(k, entry)
        self.assertEqual(entry['rank'], 1)

    def test_leaderboard_rejects_bad_period(self):
        self.assertEqual(
            self.client.get('/leaderboard?period=weekly').status_code, 422)

    def test_banned_identity_told_to_stop(self):
        db.add_ban('hwid', 'hbob', 'cheating')
        r = self.client.post('/submit', json=self._payload())
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()['status'], 'banned')

    def test_admin_delete_erases_entries(self):
        self.client.post('/submit', json=self._payload(hwid='herase'))
        r = self.client.post(
            '/admin/delete', headers={'X-Admin-Token': 'secret-token'},
            json={'kind': 'hwid', 'value': 'herase'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['deleted_rows'], 1)

    def test_admin_unban_restores_board(self):
        self.client.post('/submit', json=self._payload(username='z', hwid='hz'))
        self.client.post('/admin/ban',
                         headers={'X-Admin-Token': 'secret-token'},
                         json={'kind': 'hwid', 'value': 'hz', 'reason': 'x'})
        # banned -> excluded
        self.assertEqual(
            len(self.client.get('/leaderboard?period=all').json()['entries']), 0)
        self.client.post('/admin/unban',
                         headers={'X-Admin-Token': 'secret-token'},
                         json={'kind': 'hwid', 'value': 'hz'})
        # restored (cache TTL is 30s; force a fresh period to avoid the cache)
        self.assertGreaterEqual(
            len(self.client.get(
                '/leaderboard?period=daily').json()['entries']), 1)

    def test_admin_delete_requires_token(self):
        r = self.client.post('/admin/delete',
                             headers={'X-Admin-Token': 'wrong'},
                             json={'kind': 'hwid', 'value': 'x'})
        self.assertEqual(r.status_code, 401)


@unittest.skipUnless(_HAS_FASTAPI, 'fastapi not installed')
class TestRateLimitHTTP(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.environ['DB_PATH'] = os.path.join(self.dir, 'r.db')
        os.environ['ADMIN_TOKEN'] = 'secret-token'
        db.init_db(os.environ['DB_PATH'])
        _reset_server_state()
        self._orig_max = rs.RATE_MAX
        rs.RATE_MAX = 3
        from server.app.main import create_app
        self.client = TestClient(create_app())

    def tearDown(self):
        rs.RATE_MAX = self._orig_max
        _reset_server_state()

    def test_n_plus_one_in_window_is_429(self):
        payload = {'username': 'rl', 'hwid': 'hrl', 'fishing_catches': 1,
                   'puzzles_solved': 0, 'fishing_runtime_s': 1.0,
                   'puzzler_runtime_s': 0.0, 'app_version': '1.0.5',
                   'ts': int(time.time())}
        codes = [self.client.post('/submit', json=payload).status_code
                 for _ in range(4)]
        self.assertEqual(codes[:3], [200, 200, 200])
        self.assertEqual(codes[3], 429)
        self.assertEqual(
            self.client.post('/submit', json=payload).json()['detail'],
            'rate_limited')

    def test_oversized_body_413(self):
        # Content-Length over MAX_BODY_BYTES -> early 413 from the middleware.
        big = 'x' * 9000
        r = self.client.post(
            '/submit', content=big,
            headers={'Content-Type': 'application/json'})
        self.assertEqual(r.status_code, 413)


if __name__ == '__main__':
    unittest.main()
