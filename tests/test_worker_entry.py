# -*- coding: utf-8 -*-
"""T6b: Worker-Entry Startup-Invarianten (headless, keine Telemetrie, kein
stdout-Log, per-Client data_dir, Heartbeat). Bot-Lauf injiziert -> kein Spiel.
"""

import os
import time
import unittest

import worker


class FakeIpc:
    def __init__(self):
        self.heartbeats = 0
        self.closed = False
        self._stop = False

    def heartbeat(self):
        self.heartbeats += 1

    def stop_requested(self):
        return self._stop

    def close(self):
        self.closed = True


class RecordingDeps(worker.Deps):
    """Faengt alle Seiteneffekte ab; startet KEINE echten Bots/Telemetrie."""

    def __init__(self):
        self.log_path = None
        self.hwnd_set = None
        self.telemetry_started = False     # MUSS False bleiben
        self.ipc = FakeIpc()
        self.ran_mode = None

    def configure_log(self, path):
        self.log_path = path

    def set_hwnd(self, hwnd):
        self.hwnd_set = hwnd

    def make_ipc(self, fd_in, fd_out, idx):
        self.ipc.idx = idx
        return self.ipc

    def make_cursor(self, idx, hwnd, ipc):
        return ('cursor', idx, hwnd)

    def run_mode(self, mode, cursor, ipc, args):
        self.ran_mode = mode
        # kurz verweilen, damit der Heartbeat-Thread sicher >=1 Heartbeat sendet
        # (er sendet sofort bei Loop-Eintritt) -> deterministische Assertion.
        time.sleep(0.05)


class TestArgParser(unittest.TestCase):
    def test_parses_required(self):
        a = worker.build_arg_parser().parse_args(
            ['--client', '2', '--hwnd', '1050144', '--mode', 'fischen',
             '--ipc-fd-in', '5', '--ipc-fd-out', '6'])
        self.assertEqual((a.client, a.hwnd, a.mode), (2, 1050144, 'fischen'))
        self.assertEqual((a.ipc_fd_in, a.ipc_fd_out), (5, 6))

    def test_rejects_unknown_mode(self):
        with self.assertRaises(SystemExit):
            worker.build_arg_parser().parse_args(
                ['--client', '0', '--hwnd', '1', '--mode', 'quatsch'])


class TestWorkerStartupInvariants(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get('M2FB_DATA_DIR')

    def tearDown(self):
        if self._saved is None:
            os.environ.pop('M2FB_DATA_DIR', None)
        else:
            os.environ['M2FB_DATA_DIR'] = self._saved

    def test_run_sets_hwnd_logs_no_console_runs_mode(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            os.environ['M2FB_DATA_DIR'] = d
            deps = RecordingDeps()
            rc = worker.run(
                ['--client', '1', '--hwnd', '999', '--mode', 'puzzle',
                 '--ipc-fd-in', '3', '--ipc-fd-out', '4'], deps=deps)
            self.assertEqual(rc, 0)
            # Log landet im per-Client-Ordner (nicht stdout, nicht global).
            self.assertEqual(deps.log_path,
                             os.path.join(d, 'puzzle_debug.log'))
            self.assertEqual(deps.hwnd_set, 999)      # hwnd vor Capture gesetzt
            self.assertEqual(deps.ran_mode, 'puzzle')
            self.assertFalse(deps.telemetry_started)  # NIE Telemetrie (Finding #6)
            self.assertTrue(deps.ipc.closed)          # sauber geschlossen
            self.assertGreaterEqual(deps.ipc.heartbeats, 1)  # mind. 1 Heartbeat

    def test_run_closes_ipc_even_on_mode_error(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            os.environ['M2FB_DATA_DIR'] = d

            class BoomDeps(RecordingDeps):
                def run_mode(self, mode, cursor, ipc, args):
                    raise RuntimeError('bot kaputt')

            deps = BoomDeps()
            with self.assertRaises(RuntimeError):
                worker.run(['--client', '0', '--hwnd', '1', '--mode', 'seher'],
                           deps=deps)
            self.assertTrue(deps.ipc.closed)          # finally schliesst IPC


if __name__ == '__main__':
    unittest.main()
