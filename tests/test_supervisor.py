# -*- coding: utf-8 -*-
"""T7/T8: Supervisor -- Fehler-Isolation (Crash/Hang), dynamisch 1-4, Pre-Spawn-
Gate, Restart-Policy. Fake-Prozesse + injizierte Uhr, keine echten Subprozesse.
"""

import unittest

import supervisor as sup


class FakeProc:
    """Minimaler subprocess.Popen-Ersatz fuer Tests."""

    def __init__(self):
        self._code = None          # None = laeuft
        self.terminated = False
        self.killed = False

    def poll(self):
        return self._code

    def terminate(self):
        self.terminated = True
        self._code = -15

    def kill(self):
        self.killed = True
        self._code = -9

    # Test-Helfer
    def simulate_exit(self, code=1):
        self._code = code


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class TestPreSpawnGate(unittest.TestCase):
    def test_ensure_trained_v_sets_env_once(self):
        env = {}
        calls = []

        def build():
            calls.append(1)
            return '/built/trained_V.npy'

        p1 = sup.ensure_trained_v(build, env=env)
        self.assertEqual(p1, '/built/trained_V.npy')
        self.assertEqual(env['M2FB_TRAINED_V'], '/built/trained_V.npy')
        self.assertEqual(env['M2FB_TRAINED_V_READY'], '1')
        # idempotent: zweiter Aufruf baut NICHT erneut.
        sup.ensure_trained_v(build, env=env)
        self.assertEqual(len(calls), 1)


class TestWorkerCmd(unittest.TestCase):
    def test_build_cmd_dev(self):
        cmd = sup.build_worker_cmd('python', 'worker.py', 2, 0x100820, 'fischen',
                                   ipc_fd_in=5, ipc_fd_out=6)
        self.assertEqual(cmd, ['python', 'worker.py', '--client', '2',
                               '--hwnd', str(0x100820), '--mode', 'fischen',
                               '--ipc-fd-in', '5', '--ipc-fd-out', '6'])

    def test_build_cmd_frozen(self):
        cmd = sup.build_worker_cmd('M2FB.exe', None, 0, 123, 'puzzle')
        self.assertEqual(cmd[:2], ['M2FB.exe', '--worker'])


class TestSupervisorLifecycle(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.procs = {}
        self.events = []

        def spawn(idx, hwnd, mode, data_dir):
            p = FakeProc()
            self.procs[idx] = p
            return p

        self.spawn = spawn
        # startup_grace_s=0 -> Hang-Tests greifen sofort (Grace separat getestet).
        self.s = sup.Supervisor(spawn_fn=spawn,
                                on_event=self.events.append,
                                clock=self.clock, heartbeat_timeout=8.0,
                                startup_grace_s=0.0)

    def _add(self, *idxs):
        for i in idxs:
            self.s.add_client(i, hwnd=1000 + i, mode='fischen',
                              data_dir=f'/d/client-{i}')

    def test_add_and_alive(self):
        self._add(0, 1, 2)
        self.assertEqual(self.s.alive_ids, [0, 1, 2])

    def test_max_clients_enforced(self):
        self._add(0, 1, 2, 3)
        with self.assertRaises(ValueError):
            self._add(4)

    def test_duplicate_idx_rejected(self):
        self._add(0)
        with self.assertRaises(ValueError):
            self._add(0)

    def test_crash_isolation_others_untouched(self):
        # KERN-TEST: Worker 1 stirbt -> nur er weg, 0 und 2 UNBERUEHRT/leben.
        self._add(0, 1, 2)
        self.procs[1].simulate_exit(code=1)
        crashed = self.s.poll(now=1.0)
        self.assertEqual(crashed, [1])
        self.assertEqual(self.s.alive_ids, [0, 2])
        # die anderen Prozesse wurden NICHT terminiert/gekillt:
        self.assertFalse(self.procs[0].terminated or self.procs[0].killed)
        self.assertFalse(self.procs[2].terminated or self.procs[2].killed)
        kinds = [e['event'] for e in self.events]
        self.assertIn('client_crashed', kinds)

    def test_hang_detected_by_heartbeat_timeout(self):
        self._add(0, 1)
        # 1 sendet Heartbeat bei t=0; 0 bleibt still.
        self.s.heartbeat(1, now=0.0)
        self.clock.t = 9.0          # > heartbeat_timeout (8)
        # 1 hat frischen Heartbeat? nein -- beide haben last_heartbeat=0 (add@0),
        # nur 1 erneuerte bei 0. Beide sind >8s alt -> beide haengen.
        self.s.heartbeat(1, now=9.0)   # 1 lebt weiter
        crashed = self.s.poll(now=9.0)
        self.assertEqual(crashed, [0])      # nur 0 haengt
        self.assertTrue(self.procs[0].killed)
        self.assertEqual(self.s.alive_ids, [1])

    def test_startup_grace_prevents_false_kill(self):
        # Devil's-Advocate-Fix: frisch gestarteter Worker (laedt cv2/Templates)
        # ohne ersten Heartbeat darf INNERHALB der Grace nicht gekillt werden.
        s = sup.Supervisor(spawn_fn=self.spawn, clock=self.clock,
                           heartbeat_timeout=8.0, startup_grace_s=15.0)
        s.add_client(0, hwnd=1, mode='puzzle', data_dir='/d/0')   # started_at=0
        self.clock.t = 12.0          # > heartbeat_timeout(8) ABER < grace(15)
        self.assertEqual(s.poll(now=12.0), [])     # lebt -> kein False-Kill
        self.assertEqual(s.alive_ids, [0])
        # nach der Grace OHNE Heartbeat -> jetzt als Haenger gekillt:
        self.clock.t = 16.0
        self.assertEqual(s.poll(now=16.0), [0])
        self.assertEqual(s.alive_ids, [])

    def test_crash_during_startup_grace_still_detected(self):
        # Crash (Exit-Code) gilt SOFORT, auch in der Grace -- nur Hang wird
        # verschont, nicht ein echter Absturz beim Start.
        s = sup.Supervisor(spawn_fn=self.spawn, clock=self.clock,
                           startup_grace_s=15.0)
        s.add_client(0, hwnd=1, mode='puzzle', data_dir='/d/0')
        self.procs[0].simulate_exit(1)
        self.assertEqual(s.poll(now=2.0), [0])     # trotz Grace erkannt
        self.assertEqual(s.alive_ids, [])

    def test_remove_client_terminates_and_drops(self):
        self._add(0, 1)
        ok = self.s.remove_client(0)
        self.assertTrue(ok)
        self.assertTrue(self.procs[0].terminated)
        self.assertEqual(self.s.alive_ids, [1])

    def test_auto_restart_respawns_same_idx(self):
        s = sup.Supervisor(spawn_fn=self.spawn, clock=self.clock,
                           auto_restart=True)
        s.add_client(0, hwnd=1, mode='puzzle', data_dir='/d/0')
        first = self.procs[0]
        first.simulate_exit(2)
        s.poll(now=1.0)
        self.assertIn(0, s.clients)                 # wieder da
        self.assertEqual(s.clients[0].restarts, 1)
        self.assertIsNot(s.clients[0].proc, first)  # neuer Prozess

    def test_no_restart_by_default(self):
        self._add(0)
        self.procs[0].simulate_exit(1)
        self.s.poll(now=1.0)
        self.assertEqual(self.s.alive_ids, [])      # bleibt weg

    def test_dispatch_heartbeat_updates_liveness(self):
        self._add(0)
        self.clock.t = 5.0
        self.s.dispatch_message(0, {'cmd': 'heartbeat'}, now=5.0)
        self.assertEqual(self.s.clients[0].last_heartbeat, 5.0)

    def test_shutdown_terminates_all(self):
        self._add(0, 1, 2)
        self.s.shutdown()
        self.assertEqual(self.s.alive_ids, [])
        self.assertTrue(all(p.terminated for p in self.procs.values()))


class TestSupervisorBrokerWiring(unittest.TestCase):
    def test_crash_drops_lease_via_broker(self):
        import cursor_broker as cb
        grants = []
        broker = cb.CursorBroker(send_grant=grants.append,
                                 neutralize=lambda: None)
        clock = Clock()
        procs = {}

        def spawn(idx, hwnd, mode, data_dir):
            procs[idx] = FakeProc()
            return procs[idx]

        s = sup.Supervisor(spawn_fn=spawn, broker=broker, clock=clock)
        s.add_client(0, 1, 'fischen', '/d/0')
        s.add_client(1, 2, 'fischen', '/d/1')
        # 0 hat die Lease, 1 wartet
        broker.on_acquire(0, False, 0.0)
        broker.on_acquire(1, False, 0.1)
        self.assertEqual(grants, [0])
        # 0 crasht -> Supervisor dropt die Lease -> 1 bekommt sie.
        procs[0].simulate_exit(1)
        s.poll(now=1.0)
        self.assertEqual(grants, [0, 1])


if __name__ == '__main__':
    unittest.main()
