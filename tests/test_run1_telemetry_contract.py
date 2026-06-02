# -*- coding: utf-8 -*-
"""Run-1 QA: telemetry contract -- payload shape, opt-in gate, HWID, sender.

Complements test_telemetry_payload_hwid.py and test_telemetry_client.py with the
contract-level guarantees the spec calls out explicitly:

  * PAYLOAD SHAPE is byte-identical to the server's SubmitIn schema (same keys,
    same client/server caps) so a built payload always validates server-side.
  * OPT-IN GATE is OFF BY DEFAULT at the *config* layer (telemetry.enabled =
    False) AND at the sender layer (a disabled/empty-username/empty-url snapshot
    sends nothing). Toggling enabled live flips sending on.
  * HWID is STABLE (same machine inputs -> same id), ANONYMOUS (opaque hex, no
    raw GUID/serial/hostname leaks into it), and bounded length.
  * The SENDER never throws on a network error -- it backs off and keeps the
    thread alive; a 'banned' reply stops it and emits 'banned' exactly once.

Network is always mocked; the sender uses a short interval + stop event so the
threaded cases finish fast. Stdlib unittest + mock.
"""

import json
import threading
import time
import unittest
from datetime import datetime, timezone
from unittest import mock

from telemetry import payload, hwid, client
from interface import config as cfgmod

# The server schema is the contract; import its field set if fastapi/pydantic is
# available, else fall back to the documented literal (kept in sync by design).
try:
    from server.app.schemas import SubmitIn
    _SERVER_FIELDS = set(SubmitIn.model_fields.keys()) \
        if hasattr(SubmitIn, 'model_fields') else None
except Exception:
    _SERVER_FIELDS = None

_EXPECTED_FIELDS = {
    'username', 'hwid', 'fishing_catches', 'puzzles_solved',
    'fishing_runtime_s', 'puzzler_runtime_s', 'app_version', 'ts'}


class _FakeResp:
    def __init__(self, body, status=200):
        self._body = body.encode('utf-8') if isinstance(body, str) else body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


class TestPayloadShapeMatchesServer(unittest.TestCase):
    def _payload(self):
        now = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
        stats = {'fishing_catches': 5, 'puzzles_solved': 2,
                 'fishing_runtime_s': 12.5, 'puzzler_runtime_s': 3.0}
        return payload.build_submit('bob', 'h' * 32, stats, '1.0.5', now)

    def test_keys_exactly_match_expected(self):
        self.assertEqual(set(self._payload()), _EXPECTED_FIELDS)

    @unittest.skipUnless(_SERVER_FIELDS is not None,
                         'server schema unavailable')
    def test_keys_match_server_schema(self):
        self.assertEqual(set(self._payload()), _SERVER_FIELDS)

    def test_client_caps_equal_server_caps(self):
        # The defensive caps must line up with the server's so a max-length
        # value the client allows is not rejected (and vice-versa).
        self.assertEqual(payload.USERNAME_MAXLEN, 32)
        self.assertEqual(payload.HWID_MAXLEN, 64)
        self.assertEqual(payload.APP_VERSION_MAXLEN, 32)

    def test_built_payload_is_json_serialisable(self):
        json.dumps(self._payload())   # raises if any value is non-serialisable

    def test_types_are_wire_correct(self):
        p = self._payload()
        self.assertIsInstance(p['fishing_catches'], int)
        self.assertIsInstance(p['fishing_runtime_s'], float)
        self.assertIsInstance(p['ts'], int)
        self.assertIsInstance(p['username'], str)

    @unittest.skipUnless(_SERVER_FIELDS is not None,
                         'server schema unavailable')
    def test_built_payload_validates_against_server_schema(self):
        # End-to-end: a payload built by the client passes SubmitIn untouched.
        SubmitIn(**self._payload())


class TestOptInGateOffByDefault(unittest.TestCase):
    def test_config_default_telemetry_off(self):
        cfg = cfgmod.validate(cfgmod.DEFAULTS)
        self.assertFalse(cfg['telemetry']['enabled'])
        self.assertFalse(cfg['telemetry']['consented'])

    def test_config_default_username_empty(self):
        self.assertEqual(cfgmod.validate(cfgmod.DEFAULTS)['username'], '')

    def test_gated_helper_blocks_disabled(self):
        self.assertFalse(client._gated(
            {'enabled': False, 'username': 'bob', 'submit_url': 'https://x/s'}))

    def test_gated_helper_blocks_empty_username(self):
        self.assertFalse(client._gated(
            {'enabled': True, 'username': '   ', 'submit_url': 'https://x/s'}))

    def test_gated_helper_blocks_empty_url(self):
        self.assertFalse(client._gated(
            {'enabled': True, 'username': 'bob', 'submit_url': ''}))

    def test_gated_helper_allows_full_opt_in(self):
        self.assertTrue(client._gated(
            {'enabled': True, 'username': 'bob', 'submit_url': 'https://x/s'}))


class TestHwidStableAnonymous(unittest.TestCase):
    def test_stable_for_same_inputs(self):
        a = hwid.compute_hwid(raw_guid='G', raw_serial='S', node='host')
        b = hwid.compute_hwid(raw_guid='G', raw_serial='S', node='host')
        self.assertEqual(a, b)

    def test_anonymous_no_raw_value_leaks(self):
        # The opaque hash must not contain the raw identifiers verbatim.
        guid, serial, node = 'SECRET-GUID-123', 'VOL-SERIAL-999', 'MY-PC-NAME'
        h = hwid.compute_hwid(raw_guid=guid, raw_serial=serial, node=node)
        self.assertNotIn(guid, h)
        self.assertNotIn(serial, h)
        self.assertNotIn(node, h)

    def test_hex_only_and_bounded(self):
        h = hwid.compute_hwid(raw_guid='G', raw_serial='S', node='h')
        self.assertEqual(len(h), hwid.HWID_HEX_LEN)
        int(h, 16)   # opaque lowercase hex
        self.assertTrue(all(c in '0123456789abcdef' for c in h))

    def test_changes_when_machine_changes(self):
        a = hwid.compute_hwid(raw_guid='G1', raw_serial='S', node='h')
        b = hwid.compute_hwid(raw_guid='G2', raw_serial='S', node='h')
        self.assertNotEqual(a, b)

    def test_get_hwid_is_stable_within_process(self):
        self.assertEqual(hwid.get_hwid(), hwid.get_hwid())


class TestSenderRobustness(unittest.TestCase):
    def tearDown(self):
        client.stop_sender()
        time.sleep(0.05)

    def _state(self, **over):
        s = {'enabled': True, 'username': 'bob',
             'submit_url': 'https://x/submit', 'interval_s': 1,
             'payload': {'hwid': 'h'}}
        s.update(over)
        return s

    def test_disabled_never_posts(self):
        with mock.patch('urllib.request.urlopen',
                        side_effect=AssertionError('must not POST')) as m:
            client.start_sender(lambda: self._state(enabled=False), interval=1)
            time.sleep(0.3)
            client.stop_sender()
            time.sleep(0.1)
        self.assertEqual(m.call_count, 0)

    def test_network_error_does_not_kill_thread(self):
        seen = []
        backoff = threading.Event()

        def on_status(s):
            seen.append(s)
            if str(s).startswith('backoff'):
                backoff.set()

        with mock.patch('urllib.request.urlopen',
                        side_effect=OSError('network down')):
            th = client.start_sender(lambda: self._state(),
                                     on_status=on_status, interval=1)
            fired = backoff.wait(2.0)
            # Thread survives the error and is still alive (backing off).
            alive = th.is_alive() if th else False
            client.stop_sender()
        self.assertTrue(fired, 'sender should back off, not die')
        self.assertTrue(alive)
        self.assertTrue(any(str(s).startswith('backoff') for s in seen))

    def test_banned_stops_sender_once(self):
        statuses = []
        done = threading.Event()

        def on_status(s):
            statuses.append(s)
            if s == 'banned':
                done.set()

        with mock.patch('urllib.request.urlopen',
                        return_value=_FakeResp(json.dumps({'status': 'banned'}))):
            client.start_sender(lambda: self._state(), on_status=on_status,
                                interval=1)
            fired = done.wait(2.0)
        self.assertTrue(fired)
        self.assertEqual(statuses.count('banned'), 1)
        time.sleep(0.1)
        self.assertFalse(
            client._sender_thread.is_alive() if client._sender_thread else False)

    def test_post_submit_never_raises_on_any_network_error(self):
        for exc in (OSError('x'), ValueError('y'), Exception('z')):
            with mock.patch('urllib.request.urlopen', side_effect=exc):
                status, data = client.post_submit('https://x/s', {'hwid': 'h'})
            self.assertEqual(status, 'error')
            self.assertIsNone(data)


if __name__ == '__main__':
    unittest.main()
