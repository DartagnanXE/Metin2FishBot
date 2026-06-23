# -*- coding: utf-8 -*-
"""End-to-End: BrokerServer (echter Thread) + mehrere WorkerIpc ueber echte
os.pipe() -- beweist die Cursor-Serialisierung ueber den ganzen Stack
(IPC + Broker-Lease + Grant-Zustellung). Linux/WSL.
"""

import os
import threading
import time
import unittest

import worker_ipc
from cursor_broker_runtime import BrokerServer


def _make_pair():
    """(server_read, server_write, worker_fd_in, worker_fd_out) fuer einen Worker."""
    w2s_r, w2s_w = os.pipe()      # Worker -> Server
    s2w_r, s2w_w = os.pipe()      # Server -> Worker
    return w2s_r, s2w_w, s2w_r, w2s_w


class TestBrokerIntegration(unittest.TestCase):
    def setUp(self):
        self.server = BrokerServer(neutralize=lambda: None,
                                   tick_interval=0.05)
        self.server.start()
        self._fds = []
        self._workers = {}

    def tearDown(self):
        self.server.stop()
        for fd in self._fds:
            try:
                os.close(fd)
            except Exception:
                pass

    def _add_worker(self, idx):
        s_r, s_w, w_in, w_out = _make_pair()
        self._fds += [s_r, s_w, w_in, w_out]
        self.server.register(idx, read_fd=s_r, write_fd=s_w)
        ipc = worker_ipc.WorkerIpc(w_in, w_out, idx=idx).start()
        self._workers[idx] = ipc
        return ipc

    def test_two_workers_never_hold_simultaneously(self):
        w0 = self._add_worker(0)
        w1 = self._add_worker(1)
        active = {'n': 0, 'max': 0}
        lock = threading.Lock()
        errors = []

        def hammer(ipc, rounds):
            for _ in range(rounds):
                try:
                    ipc.acquire(ipc.idx, holds_button=False, timeout=3.0)
                except Exception as exc:
                    errors.append(exc)
                    return
                with lock:
                    active['n'] += 1
                    active['max'] = max(active['max'], active['n'])
                time.sleep(0.005)           # "Burst"
                with lock:
                    active['n'] -= 1
                ipc.release(ipc.idx)

        t0 = threading.Thread(target=hammer, args=(w0, 15))
        t1 = threading.Thread(target=hammer, args=(w1, 15))
        t0.start(); t1.start()
        t0.join(timeout=10); t1.join(timeout=10)

        self.assertEqual(errors, [])
        # KERN-GARANTIE: zu keinem Zeitpunkt hielten zwei Worker den Cursor.
        self.assertEqual(active['max'], 1)

    def test_fifo_grant_after_release(self):
        w0 = self._add_worker(0)
        w1 = self._add_worker(1)
        # w0 nimmt die Lease.
        w0.acquire(0, False, timeout=3.0)
        got = {}

        def w1_acquire():
            try:
                w1.acquire(1, False, timeout=3.0)
                got['ok'] = True
            except Exception as exc:
                got['err'] = exc

        t = threading.Thread(target=w1_acquire)
        t.start()
        time.sleep(0.1)
        self.assertFalse(got)          # w1 wartet (w0 haelt die Lease)
        w0.release(0)
        t.join(timeout=3.0)
        self.assertTrue(got.get('ok'))

    def test_worker_crash_drops_lease_others_continue(self):
        w0 = self._add_worker(0)
        w1 = self._add_worker(1)
        w0.acquire(0, False, timeout=3.0)   # w0 haelt die Lease
        got = {}

        def w1_acquire():
            try:
                w1.acquire(1, False, timeout=3.0)
                got['ok'] = True
            except Exception as exc:
                got['err'] = type(exc).__name__

        t = threading.Thread(target=w1_acquire)
        t.start()
        time.sleep(0.1)
        self.assertFalse(got)
        # w0 "crasht": IPC schliessen -> EOF am Server -> Lease-Drop -> w1 dran.
        w0.close()
        t.join(timeout=3.0)
        self.assertTrue(got.get('ok'), f'w1 bekam die Lease nicht: {got}')

    def test_broadcast_stop_reaches_workers(self):
        w0 = self._add_worker(0)
        self.server.broadcast_stop()
        deadline = time.time() + 2.0
        while time.time() < deadline and not w0.stop_requested():
            time.sleep(0.02)
        self.assertTrue(w0.stop_requested())


if __name__ == '__main__':
    unittest.main()
