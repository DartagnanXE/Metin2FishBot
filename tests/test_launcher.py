# -*- coding: utf-8 -*-
"""Build-Schritt 11: Launcher-Orchestrierung (broker + supervisor + spawn).

Voll gemockt -- kein echter Prozess-Spawn, keine Pipes, kein Spiel. Prueft die
VERDRAHTUNG: Pipe-Paarung + Broker-Registrierung + Worker-Kommandozeile +
``pass_fds``/Env, die Broker/Supervisor-Verkabelung, Heartbeat-Routing und die
Lauf-/Stop-Schleife. Der reale OS-Spawn/FD-Vererbung bleibt live-only.
"""

import unittest

import launcher


class TestClientDataDir(unittest.TestCase):
    def test_builds_per_client_appdata_path(self):
        p = launcher.client_data_dir(2, appdata='/APPD')
        self.assertTrue(p.endswith('client-2'))
        self.assertIn(launcher._paths.APP_DIR, p)
        self.assertTrue(p.startswith('/APPD'))


class TestParseSpec(unittest.TestCase):
    def test_hwnd_and_mode(self):
        self.assertEqual(launcher._parse_spec('123:puzzle'), (123, 'puzzle'))

    def test_default_mode(self):
        self.assertEqual(launcher._parse_spec('99'),
                         (99, launcher.DEFAULT_MODE))

    def test_invalid_mode_raises(self):
        with self.assertRaises(Exception):
            launcher._parse_spec('5:nonsense')


class _FakeBroker:
    def __init__(self):
        self.registered = []
        self.broker = 'CORE'

    def register(self, idx, read_fd, write_fd):
        self.registered.append((idx, read_fd, write_fd))


class TestMakeSpawn(unittest.TestCase):
    def test_wires_pipes_registration_cmd_and_fds(self):
        broker = _FakeBroker()
        pipes = iter([(1, 2), (3, 4)])      # a=(1,2), b=(3,4)
        inh, closed, popened = [], [], {}

        def fake_popen(cmd, pass_fds=None, env=None):
            popened['cmd'] = cmd
            popened['pass_fds'] = pass_fds
            popened['env'] = env
            return 'PROC'

        spawn = launcher.make_spawn(
            'py', 'worker.py', broker,
            popen=fake_popen, pipe=lambda: next(pipes),
            set_inheritable=lambda fd, flag: inh.append((fd, flag)),
            closer=closed.append, base_env={'X': '1'})

        proc = spawn(0, 777, 'fischen', '/data/c0')
        self.assertEqual(proc, 'PROC')
        # Broker bekommt Worker->Broker-Lesefd (a_r=1) + Broker->Worker-Schreibfd (b_w=4).
        self.assertEqual(broker.registered, [(0, 1, 4)])
        # Worker-seitige FDs (b_r=3, a_w=2) vererbbar gemacht + im Parent geschlossen.
        self.assertEqual(set(fd for fd, _ in inh), {3, 2})
        self.assertEqual(set(closed), {3, 2})
        # Kommandozeile + pass_fds + Env.
        self.assertEqual(popened['pass_fds'], (3, 2))
        cmd = popened['cmd']
        self.assertIn('--client', cmd)
        self.assertIn('777', cmd)
        self.assertIn('fischen', cmd)
        self.assertIn('--ipc-fd-in', cmd)
        self.assertIn('3', cmd)            # b_r als fd-in
        self.assertIn('--ipc-fd-out', cmd)
        self.assertIn('2', cmd)            # a_w als fd-out
        self.assertEqual(popened['env']['M2FB_DATA_DIR'], '/data/c0')


class _FakeBrokerServer:
    def __init__(self, on_heartbeat):
        self.on_heartbeat = on_heartbeat
        self.broker = 'CORE'
        self.started = self.stopped = False
        self.broadcasts = 0

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def broadcast_stop(self):
        self.broadcasts += 1


class _FakeSupervisor:
    def __init__(self):
        self.added = []
        self.polls = 0
        self.shutdowns = 0
        self.heartbeats = []
        self._alive = True

    def add_client(self, idx, hwnd, mode, data_dir):
        self.added.append((idx, hwnd, mode, data_dir))

    def alive_ids(self):
        return [0] if self._alive else []

    def poll(self):
        self.polls += 1

    def shutdown(self):
        self.shutdowns += 1
        self._alive = False

    def heartbeat(self, idx, now):
        self.heartbeats.append((idx, now))


class TestRunOrchestration(unittest.TestCase):
    def _run(self, specs, **kw):
        self.broker = None
        self.sup = _FakeSupervisor()

        def broker_factory(on_heartbeat):
            self.broker = _FakeBrokerServer(on_heartbeat)
            return self.broker

        def sup_factory(spawn, core, on_event, clock):
            self.spawn = spawn
            self.core = core
            return self.sup

        return launcher.run(
            specs, broker_factory=broker_factory,
            supervisor_factory=sup_factory,
            spawn_factory=lambda b: 'SPAWN_FN',
            sleep=lambda s: None, clock=lambda: 0.0, **kw)

    def test_starts_broker_adds_clients_and_shuts_down(self):
        polls = {'n': 0}

        def should_run():
            polls['n'] += 1
            return polls['n'] <= 2          # 2 Iterationen, dann Stop

        out = self._run([(11, 'fischen'), (22, 'puzzle')], should_run=should_run)
        self.assertIs(out, self.sup)
        self.assertTrue(self.broker.started)
        self.assertEqual(self.core, 'CORE')               # Supervisor bekam broker.broker
        self.assertEqual(len(self.sup.added), 2)
        self.assertEqual(self.sup.added[0][:3], (0, 11, 'fischen'))
        self.assertEqual(self.sup.added[1][:3], (1, 22, 'puzzle'))
        self.assertTrue(self.sup.added[0][3].endswith('client-0'))
        self.assertEqual(self.sup.polls, 2)               # 2x gepollt
        self.assertEqual(self.broker.broadcasts, 1)       # Broadcast-Stop
        self.assertEqual(self.sup.shutdowns, 1)
        self.assertTrue(self.broker.stopped)

    def test_heartbeat_routes_to_supervisor(self):
        self._run([(1, 'fischen')], should_run=lambda: False)
        # Der an den Broker uebergebene Heartbeat-Hook erreicht den Supervisor.
        self.broker.on_heartbeat(0, 5.0)
        self.assertIn((0, 5.0), self.sup.heartbeats)

    def test_stops_when_no_clients_alive(self):
        self.sup = None
        sup = _FakeSupervisor()
        sup._alive = False                                # sofort keine Clients
        out = launcher.run(
            [(1, 'fischen')],
            broker_factory=lambda hb: _FakeBrokerServer(hb),
            supervisor_factory=lambda sp, core, oe, ck: sup,
            spawn_factory=lambda b: 'S', sleep=lambda s: None,
            clock=lambda: 0.0)
        self.assertEqual(sup.polls, 0)                    # Schleife nie betreten
        self.assertEqual(sup.shutdowns, 1)


if __name__ == '__main__':
    unittest.main()
