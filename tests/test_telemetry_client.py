# -*- coding: utf-8 -*-
"""Tests for telemetry.client WITHOUT real network (urlopen monkeypatched).

post_submit maps 200 -> 'ok', a 'banned' body -> 'banned', exceptions ->
'error' (never raises). fetch_leaderboard parses JSON and returns None on error
(and uses its cache). start_sender respects the opt-in gate (does nothing when
disabled/empty username) and stops on 'banned'. Uses a short interval + a stop
event so the threaded test finishes fast. Stdlib unittest + unittest.mock.
"""

import json
import threading
import unittest
from unittest import mock

from telemetry import client


class _FakeResp:
    """Minimal context-manager stand-in for urlopen's return value."""

    def __init__(self, body, status=200):
        self._body = body.encode('utf-8') if isinstance(body, str) else body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


class _FakeHTTPError(Exception):
    """Stands in for urllib HTTPError carrying a JSON body (e.g. a ban)."""

    def __init__(self, body):
        super().__init__('http error')
        self._body = body.encode('utf-8')

    def read(self):
        return self._body


def _clear_cache():
    client._LEADERBOARD_CACHE.clear()


class TestPostSubmit(unittest.TestCase):
    def test_ok_200(self):
        with mock.patch('urllib.request.urlopen',
                        return_value=_FakeResp(json.dumps({'status': 'ok'}))):
            status, data = client.post_submit('https://x/submit', {'hwid': 'h'})
        self.assertEqual(status, 'ok')
        self.assertEqual(data, {'status': 'ok'})

    def test_banned_body(self):
        with mock.patch('urllib.request.urlopen',
                        return_value=_FakeResp(json.dumps({'status': 'banned'}))):
            status, _ = client.post_submit('https://x/submit', {'hwid': 'h'})
        self.assertEqual(status, 'banned')

    def test_exception_is_error(self):
        with mock.patch('urllib.request.urlopen',
                        side_effect=OSError('no net')):
            status, data = client.post_submit('https://x/submit', {'hwid': 'h'})
        self.assertEqual(status, 'error')
        self.assertIsNone(data)

    def test_banned_via_httperror(self):
        err = _FakeHTTPError(json.dumps({'status': 'banned'}))
        with mock.patch('urllib.request.urlopen', side_effect=err):
            status, _ = client.post_submit('https://x/submit', {'hwid': 'h'})
        self.assertEqual(status, 'banned')

    def test_unparseable_ok_body(self):
        with mock.patch('urllib.request.urlopen',
                        return_value=_FakeResp('not json')):
            status, data = client.post_submit('https://x/submit', {})
        self.assertEqual(status, 'ok')   # 200 but body unparseable -> ok, data None
        self.assertIsNone(data)

    def test_never_raises_on_garbage_payload(self):
        with mock.patch('urllib.request.urlopen',
                        return_value=_FakeResp(json.dumps({'status': 'ok'}))):
            # non-serialisable payload -> json.dumps raises -> caught -> error
            status, _ = client.post_submit('https://x/submit', {'k': object()})
        self.assertEqual(status, 'error')


class TestFetchLeaderboard(unittest.TestCase):
    def setUp(self):
        _clear_cache()

    def tearDown(self):
        _clear_cache()

    def test_parses_json(self):
        board = {'daily': [], 'all': []}
        with mock.patch('urllib.request.urlopen',
                        return_value=_FakeResp(json.dumps(board))):
            data = client.fetch_leaderboard('https://x/leaderboard')
        self.assertEqual(data, board)

    def test_error_returns_none(self):
        with mock.patch('urllib.request.urlopen',
                        side_effect=OSError('down')):
            data = client.fetch_leaderboard('https://x/leaderboard')
        self.assertIsNone(data)

    def test_non_dict_returns_none(self):
        with mock.patch('urllib.request.urlopen',
                        return_value=_FakeResp(json.dumps([1, 2, 3]))):
            data = client.fetch_leaderboard('https://x/leaderboard')
        self.assertIsNone(data)

    def test_cache_avoids_second_call(self):
        board = {'daily': []}
        m = mock.Mock(return_value=_FakeResp(json.dumps(board)))
        with mock.patch('urllib.request.urlopen', m):
            a = client.fetch_leaderboard('https://x/lb')
            b = client.fetch_leaderboard('https://x/lb')   # served from cache
        self.assertEqual(a, board)
        self.assertEqual(b, board)
        self.assertEqual(m.call_count, 1)


class TestSenderGate(unittest.TestCase):
    def tearDown(self):
        client.stop_sender()
        if client._sender_thread is not None:
            client._sender_thread.join(timeout=2.0)

    @staticmethod
    def _state_factory(state, looped, min_loops=3):
        """Return a get_state that signals ``looped`` once the worker has polled
        it ``min_loops`` times -- so a negative test can wait on real loop
        iterations instead of a wall-clock sleep (no thread-timing flakiness)."""
        count = {'n': 0}

        def get_state():
            count['n'] += 1
            if count['n'] >= min_loops:
                looped.set()
            return dict(state)

        return get_state

    def test_disabled_sends_nothing(self):
        # Gated OFF: drive the worker, wait until it has actually evaluated the
        # gate several times (event-driven, not sleep-based), then assert it
        # never POSTed and never emitted 'started'.
        calls = []
        looped = threading.Event()
        get_state = self._state_factory(
            {'enabled': False, 'username': 'bob',
             'submit_url': 'https://x/submit', 'interval_s': 1,
             'payload': {'hwid': 'h'}}, looped)

        with mock.patch('urllib.request.urlopen',
                        side_effect=AssertionError('should not POST')) as m:
            client.start_sender(get_state, on_status=calls.append, interval=1,
                                idle_poll=0.01)
            self.assertTrue(looped.wait(2.0), 'worker never polled the gate')
            client.stop_sender()
            if client._sender_thread is not None:
                client._sender_thread.join(timeout=2.0)
        self.assertEqual(m.call_count, 0)
        self.assertNotIn('started', calls)

    def test_empty_username_sends_nothing(self):
        looped = threading.Event()
        get_state = self._state_factory(
            {'enabled': True, 'username': '   ',
             'submit_url': 'https://x/submit', 'interval_s': 1,
             'payload': {'hwid': 'h'}}, looped)

        with mock.patch('urllib.request.urlopen',
                        side_effect=AssertionError('should not POST')) as m:
            client.start_sender(get_state, interval=1, idle_poll=0.01)
            self.assertTrue(looped.wait(2.0), 'worker never polled the gate')
            client.stop_sender()
            if client._sender_thread is not None:
                client._sender_thread.join(timeout=2.0)
        self.assertEqual(m.call_count, 0)

    def test_enabled_sends_and_banned_stops(self):
        statuses = []
        done = threading.Event()

        def on_status(s):
            statuses.append(s)
            if s == 'banned':
                done.set()

        def get_state():
            return {'enabled': True, 'username': 'bob',
                    'submit_url': 'https://x/submit', 'interval_s': 1,
                    'payload': {'hwid': 'h'}}

        with mock.patch('urllib.request.urlopen',
                        return_value=_FakeResp(json.dumps({'status': 'banned'}))):
            client.start_sender(get_state, on_status=on_status, interval=1)
            fired = done.wait(2.0)
        self.assertTrue(fired, 'sender should have hit banned')
        self.assertIn('banned', statuses)
        # After a ban the thread stops itself -> join deterministically instead
        # of sleeping and racing is_alive().
        th = client._sender_thread
        if th is not None:
            th.join(timeout=2.0)
            self.assertFalse(th.is_alive())

    def test_ok_submit_emits_started_and_ok(self):
        statuses = []
        seen_ok = threading.Event()

        def on_status(s):
            statuses.append(s)
            if s == 'ok':
                seen_ok.set()

        def get_state():
            return {'enabled': True, 'username': 'bob',
                    'submit_url': 'https://x/submit', 'interval_s': 1,
                    'payload': {'hwid': 'h'}}

        with mock.patch('urllib.request.urlopen',
                        return_value=_FakeResp(json.dumps({'status': 'ok'}))):
            client.start_sender(get_state, on_status=on_status, interval=1,
                                idle_poll=0.01)
            fired = seen_ok.wait(2.0)
            client.stop_sender()
        self.assertTrue(fired)
        self.assertIn('started', statuses)
        self.assertIn('ok', statuses)

    def test_bad_idle_poll_does_not_crash_sender(self):
        # A garbage / non-positive idle_poll must be coerced to the safe default,
        # never raise, and the gate must still work (no POST while disabled).
        looped = threading.Event()
        get_state = self._state_factory(
            {'enabled': False, 'username': 'bob',
             'submit_url': 'https://x/submit', 'interval_s': 1,
             'payload': {'hwid': 'h'}}, looped, min_loops=1)
        with mock.patch('urllib.request.urlopen',
                        side_effect=AssertionError('should not POST')) as m:
            th = client.start_sender(get_state, interval=1, idle_poll='nonsense')
            self.assertIsNotNone(th)
            # The very first loop polls the gate immediately on entry.
            self.assertTrue(looped.wait(4.0))
            client.stop_sender()
            if client._sender_thread is not None:
                client._sender_thread.join(timeout=2.0)
        self.assertEqual(m.call_count, 0)


if __name__ == '__main__':
    unittest.main()
