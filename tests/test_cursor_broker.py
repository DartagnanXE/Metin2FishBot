# -*- coding: utf-8 -*-
"""T6: Cursor-Broker -- FIFO, Hard-Timeout, EOF-Drop, Button-Neutralisierung,
Drag-Non-Revocability. Reine Logik, keine Threads/Pipes/echter Cursor noetig.
"""

import unittest

import cursor_broker as cb


class TestLeaseScheduler(unittest.TestCase):
    def setUp(self):
        self.s = cb.LeaseScheduler(lease_timeout=5.0, drag_timeout=20.0)

    def _kinds(self, events):
        return [e[0] for e in events]

    def test_immediate_grant_when_free(self):
        ev = self.s.request(0, False, now=0.0)
        self.assertEqual(ev, [('grant', 0)])
        self.assertEqual(self.s.holder, 0)

    def test_fifo_order_no_starvation(self):
        self.assertEqual(self._kinds(self.s.request(0, False, 0.0)), ['grant'])
        self.assertEqual(self.s.request(1, False, 0.1), [])   # wartet
        self.assertEqual(self.s.request(2, False, 0.2), [])   # wartet
        self.assertEqual(self.s.waiting, [1, 2])
        # Freigabe von 0 -> der am laengsten Wartende (1) kommt dran.
        self.assertEqual(self.s.release(0, 0.3), [('grant', 1)])
        self.assertEqual(self.s.release(1, 0.4), [('grant', 2)])
        self.assertEqual(self.s.waiting, [])

    def test_duplicate_request_ignored(self):
        self.s.request(0, False, 0.0)
        self.s.request(1, False, 0.1)
        self.assertEqual(self.s.request(1, False, 0.2), [])
        self.assertEqual(self.s.waiting, [1])   # nicht doppelt

    def test_hard_timeout_revokes_and_neutralizes_then_regrants(self):
        self.s.request(0, False, 0.0)
        self.s.request(1, False, 0.1)
        # vor Ablauf: nichts
        self.assertEqual(self.s.tick(now=4.9), [])
        # nach Ablauf: revoke 0 + neutralize + grant 1 -- in DIESER Reihenfolge
        ev = self.s.tick(now=5.01)
        self.assertEqual(ev, [('revoke', 0, 'lease_timeout'),
                              ('neutralize',), ('grant', 1)])
        self.assertEqual(self.s.holder, 1)

    def test_holds_button_not_revoked_by_normal_timeout(self):
        # Finding #1: Drag (gehaltene Taste) darf NICHT vom 5s-Cap entzogen werden.
        self.s.request(0, True, 0.0)   # holds_button=True
        self.s.request(1, False, 0.1)
        self.assertEqual(self.s.tick(now=6.0), [])     # > lease, < drag
        self.assertEqual(self.s.tick(now=10.0), [])
        self.assertEqual(self.s.holder, 0)             # Drag laeuft ungestoert
        # aber der hoehere Drag-Cap greift als letzte Sicherung
        ev = self.s.tick(now=20.5)
        self.assertEqual(ev[0], ('revoke', 0, 'drag_timeout'))
        self.assertIn(('neutralize',), ev)
        self.assertEqual(self.s.holder, 1)

    def test_eof_drop_releases_held_lease_with_neutralize(self):
        # Finding #2: EOF = Crash. Hielt der Tote die Lease -> neutralize + regrant.
        self.s.request(0, False, 0.0)
        self.s.request(1, False, 0.1)
        ev = self.s.drop(0, now=0.5)
        self.assertEqual(ev, [('neutralize',), ('grant', 1)])
        self.assertEqual(self.s.holder, 1)

    def test_eof_drop_of_waiter_just_removes(self):
        self.s.request(0, False, 0.0)
        self.s.request(1, False, 0.1)
        self.assertEqual(self.s.drop(1, now=0.2), [])   # 1 wartete nur
        self.assertEqual(self.s.waiting, [])
        self.assertEqual(self.s.holder, 0)

    def test_release_by_nonholder_is_safe(self):
        self.s.request(0, False, 0.0)
        self.assertEqual(self.s.release(99, 0.1), [])
        self.assertEqual(self.s.holder, 0)


class TestCursorBrokerSideEffects(unittest.TestCase):
    """Broker-Huelle: wendet Scheduler-Events auf Callbacks an (Reihenfolge!)."""

    def setUp(self):
        self.grants = []
        self.neutralized = []
        self.revokes = []
        self.broker = cb.CursorBroker(
            send_grant=lambda idx: self.grants.append(idx),
            neutralize=lambda: self.neutralized.append(True),
            on_revoke=lambda idx, why: self.revokes.append((idx, why)),
            lease_timeout=5.0, drag_timeout=20.0)

    def test_acquire_release_grants_in_order(self):
        self.broker.on_acquire(0, False, 0.0)
        self.broker.on_acquire(1, False, 0.1)
        self.assertEqual(self.grants, [0])
        self.broker.on_release(0, 0.2)
        self.assertEqual(self.grants, [0, 1])

    def test_revoke_neutralizes_before_next_grant(self):
        self.broker.on_acquire(0, False, 0.0)
        self.broker.on_acquire(1, False, 0.1)
        self.broker.tick(5.01)
        # Button MUSS vor dem naechsten Grant geloest worden sein (Finding #1).
        self.assertEqual(self.neutralized, [True])
        self.assertEqual(self.revokes, [(0, 'lease_timeout')])
        self.assertEqual(self.grants, [0, 1])

    def test_on_message_acquire_with_holds_button(self):
        self.broker.on_message(0, {'cmd': 'acquire', 'holds_button': True}, 0.0)
        self.assertEqual(self.grants, [0])
        self.assertTrue(self.broker.sched.holder_holds_button)

    def test_eof_drops_and_regrants_with_neutralize(self):
        self.broker.on_acquire(0, False, 0.0)
        self.broker.on_acquire(1, False, 0.1)
        self.broker.on_eof(0, 0.5)
        self.assertEqual(self.neutralized, [True])
        self.assertEqual(self.grants, [0, 1])


class TestIpcCodec(unittest.TestCase):
    def test_roundtrip(self):
        raw = cb.encode_msg({'cmd': 'acquire', 'idx': 2, 'holds_button': True})
        msgs, rest = cb.decode_lines(raw)
        self.assertEqual(msgs, [{'cmd': 'acquire', 'idx': 2, 'holds_button': True}])
        self.assertEqual(rest, b'')

    def test_partial_and_multiple(self):
        buf = cb.encode_msg({'a': 1}) + cb.encode_msg({'b': 2})[:3]
        msgs, rest = cb.decode_lines(buf)
        self.assertEqual(msgs, [{'a': 1}])
        self.assertTrue(rest)   # angefangene 2. Zeile bleibt im Puffer

    def test_garbage_line_skipped(self):
        buf = b'not json\n' + cb.encode_msg({'ok': 1})
        msgs, rest = cb.decode_lines(buf)
        self.assertEqual(msgs, [{'ok': 1}])


if __name__ == '__main__':
    unittest.main()
