# -*- coding: utf-8 -*-
"""Server tests runnable WITHOUT the live box.

The DB layer (sqlite, stdlib) is tested unconditionally. The HTTP routes
(schema validation, ban/rate-limit, leaderboard aggregation end-to-end) are
tested via FastAPI's TestClient IF fastapi is installed; otherwise those classes
skip cleanly so CI without server deps still passes.

Run:  python -m pytest server/tests -q
  or: python -m unittest discover -s server/tests
"""

import os
import tempfile
import time
import unittest

from server.app import db

try:
    from fastapi.testclient import TestClient
    _HAS_FASTAPI = True
except Exception:
    _HAS_FASTAPI = False


class TestDB(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        db.init_db(os.path.join(self.dir, 't.db'))

    def _sub(self, **over):
        row = {'username': 'u', 'hwid': 'h', 'fishing_catches': 1,
               'puzzles_solved': 0, 'fishing_runtime_s': 1.0,
               'puzzler_runtime_s': 0.0, 'app_version': '1.0.5',
               'ts': int(time.time()), 'ip_hash': 'x'}
        row.update(over)
        return row

    def test_aggregates_max_per_identity(self):
        db.insert_submission(self._sub(username='a', hwid='h1',
                                       fishing_catches=10))
        db.insert_submission(self._sub(username='a', hwid='h1',
                                       fishing_catches=25))
        lb = db.leaderboard('all')
        self.assertEqual(lb[0]['username'], 'a')
        self.assertEqual(lb[0]['fishing_catches'], 25)

    def test_last_for_identity_latest_wins_on_ts_tie(self):
        ts = int(time.time())
        db.insert_submission(self._sub(hwid='h1', fishing_catches=5, ts=ts))
        db.insert_submission(self._sub(hwid='h1', fishing_catches=9, ts=ts))
        self.assertEqual(db.last_for_identity('h1')['fishing_catches'], 9)

    def test_ban_excludes_and_unban_restores(self):
        db.insert_submission(self._sub(username='a', hwid='h1'))
        db.add_ban('username', 'a', 'x')
        self.assertTrue(db.is_banned('username', 'a'))
        self.assertEqual(len(db.leaderboard('all')), 0)
        db.remove_ban('username', 'a')
        self.assertFalse(db.is_banned('username', 'a'))
        self.assertEqual(len(db.leaderboard('all')), 1)

    def test_delete_entries_erasure(self):
        db.insert_submission(self._sub(hwid='h2'))
        self.assertEqual(db.delete_entries('hwid', 'h2'), 1)
        self.assertEqual(len(db.leaderboard('all')), 0)

    def test_daily_excludes_old(self):
        old = int(time.time()) - 200_000   # > 24h ago
        db.insert_submission(self._sub(username='old', hwid='ho', ts=old))
        db.insert_submission(self._sub(username='new', hwid='hn'))
        daily = [r['username'] for r in db.leaderboard('daily')]
        self.assertIn('new', daily)
        self.assertNotIn('old', daily)


@unittest.skipUnless(_HAS_FASTAPI, 'fastapi not installed')
class TestRoutes(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.environ['DB_PATH'] = os.path.join(self.dir, 'r.db')
        os.environ['ADMIN_TOKEN'] = 'secret-token'
        db.init_db(os.environ['DB_PATH'])
        from server.app.main import create_app
        self.client = TestClient(create_app())

    def _payload(self, **over):
        p = {'username': 'bob', 'hwid': 'hbob', 'fishing_catches': 3,
             'puzzles_solved': 1, 'fishing_runtime_s': 5.0,
             'puzzler_runtime_s': 0.0, 'app_version': '1.0.5',
             'ts': int(time.time())}
        p.update(over)
        return p

    def test_submit_ok_and_leaderboard(self):
        r = self.client.post('/submit', json=self._payload())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'ok')
        lb = self.client.get('/leaderboard?period=all').json()
        self.assertEqual(lb['entries'][0]['username'], 'bob')

    def test_submit_rejects_bad_schema(self):
        bad = self._payload(fishing_catches=-1)   # ge=0 violated
        r = self.client.post('/submit', json=bad)
        self.assertEqual(r.status_code, 422)

    def test_submit_rejects_oversized_username(self):
        r = self.client.post('/submit', json=self._payload(username='x' * 100))
        self.assertEqual(r.status_code, 422)

    def test_banned_identity(self):
        db.add_ban('hwid', 'hbob', 'test')
        r = self.client.post('/submit', json=self._payload())
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()['status'], 'banned')

    def test_admin_requires_token(self):
        r = self.client.post('/admin/ban',
                             json={'kind': 'hwid', 'value': 'z'})
        self.assertIn(r.status_code, (401, 422))   # missing/!match header
        r2 = self.client.post(
            '/admin/ban', headers={'X-Admin-Token': 'secret-token'},
            json={'kind': 'hwid', 'value': 'z', 'reason': 'x'})
        self.assertEqual(r2.status_code, 200)

    def test_health(self):
        self.assertEqual(self.client.get('/health').status_code, 200)


if __name__ == '__main__':
    unittest.main()
