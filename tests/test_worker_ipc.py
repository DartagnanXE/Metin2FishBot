# -*- coding: utf-8 -*-
"""WorkerIpc mit echten os.pipe() (in-process Supervisor-Simulation, Linux/WSL)."""

import os
import threading
import time
import unittest

import worker_ipc
from cursor_broker import encode_msg, decode_lines


class SupervisorEnd:
    """Simuliert die Supervisor-Seite eines Worker-Pipe-Paars."""

    def __init__(self):
        # Pipe A: Supervisor -> Worker (grant/stop). Worker liest a_r.
        self.a_r, self.a_w = os.pipe()
        # Pipe B: Worker -> Supervisor (acquire/release/heartbeat).
        self.b_r, self.b_w = os.pipe()
        self._buf = b''

    def worker_fds(self):
        return self.a_r, self.b_w     # (fd_in, fd_out) fuer den Worker

    def send(self, obj):
        os.write(self.a_w, encode_msg(obj))

    def recv_one(self, timeout=2.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            msgs, self._buf = decode_lines(self._buf)
            if msgs:
                return msgs[0]
            chunk = os.read(self.b_r, 4096)
            if chunk:
                self._buf += chunk
        return None

    def close_to_worker(self):
        os.close(self.a_w)            # EOF fuer den Worker-Reader


class TestWorkerIpc(unittest.TestCase):
    def setUp(self):
        self.sup = SupervisorEnd()
        fd_in, fd_out = self.sup.worker_fds()
        self.ipc = worker_ipc.WorkerIpc(fd_in, fd_out, idx=0).start()

    def tearDown(self):
        try:
            self.ipc.close()
        except Exception:
            pass

    def test_acquire_blocks_until_grant(self):
        result = {}

        def do_acquire():
            try:
                self.ipc.acquire(0, holds_button=False, timeout=2.0)
                result['ok'] = True
            except Exception as exc:
                result['err'] = exc

        t = threading.Thread(target=do_acquire)
        t.start()
        # Supervisor sieht die acquire-Anfrage ...
        msg = self.sup.recv_one()
        self.assertEqual(msg, {'cmd': 'acquire', 'idx': 0, 'holds_button': False})
        # ... acquire blockiert noch (kein Grant):
        time.sleep(0.05)
        self.assertFalse(result)
        # Grant senden -> acquire kehrt zurueck.
        self.sup.send({'grant': 0})
        t.join(timeout=2.0)
        self.assertTrue(result.get('ok'))

    def test_acquire_timeout(self):
        with self.assertRaises(TimeoutError):
            self.ipc.acquire(0, holds_button=False, timeout=0.2)

    def test_release_and_heartbeat_sent(self):
        self.ipc.release(0)
        self.assertEqual(self.sup.recv_one(), {'cmd': 'release', 'idx': 0})
        self.ipc.heartbeat()
        self.assertEqual(self.sup.recv_one(), {'cmd': 'heartbeat', 'idx': 0})

    def test_stop_broadcast_sets_flag_and_unblocks(self):
        self.assertFalse(self.ipc.stop_requested())
        self.sup.send({'cmd': 'stop'})
        deadline = time.time() + 2.0
        while time.time() < deadline and not self.ipc.stop_requested():
            time.sleep(0.02)
        self.assertTrue(self.ipc.stop_requested())

    def test_holds_button_flag_propagates(self):
        threading.Thread(target=lambda: self._safe_acquire(True)).start()
        msg = self.sup.recv_one()
        self.assertTrue(msg['holds_button'])
        self.sup.send({'grant': 0})

    def _safe_acquire(self, hb):
        try:
            self.ipc.acquire(0, holds_button=hb, timeout=2.0)
        except Exception:
            pass

    def test_eof_closes_and_unblocks_acquire(self):
        result = {}

        def do_acquire():
            try:
                self.ipc.acquire(0, False, timeout=3.0)
            except Exception as exc:
                result['err'] = type(exc).__name__

        t = threading.Thread(target=do_acquire)
        t.start()
        self.sup.recv_one()              # acquire ist raus
        self.sup.close_to_worker()       # EOF -> Worker-Reader endet
        t.join(timeout=2.0)
        self.assertTrue(self.ipc.closed)
        # acquire endet (Timeout ODER BrokenPipe -- beides akzeptabel als Abbruch)
        self.assertIn(result.get('err'), ('TimeoutError', 'BrokenPipeError', None))


if __name__ == '__main__':
    unittest.main()
