# -*- coding: utf-8 -*-
"""Headless Worker-Entry fuer EINEN Multiclient-Bot (Finding #5).

WICHTIG: NICHT hack.py erweitern -- hack.py baut die volle CTk-GUI mit BEIDEN
Bots (hack.py:66 App(cfg), :79 mainloop). Ein Worker startet GENAU EINEN
Modus-Bot OHNE GUI und treibt seine Klicks ueber den CursorClient -> Broker.

Startup-Invarianten (per T6b geprueft):
  * data_dir aus ENV M2FB_DATA_DIR -> config/stats/log isoliert (paths.py).
  * debuglog mit to_console=False (Finding #7: stdout ist NICHT der IPC-Kanal;
    IPC laeuft ueber das dedizierte os.pipe()-Paar --ipc-fd-in/-out).
  * Telemetrie wird NIE gestartet (Finding #6: 4 Worker unter einer install_id
    => Server-Doppelzaehlung). Nur der Supervisor sendet.
  * set_preferred_hwnd(args.hwnd) VOR jeder WindowCapture.
  * eigener Heartbeat-Thread (Supervisor-Liveness) + Stop ueber IPC.

Die Modus-Schleife (``run_mode``) und die Anbindung der bestehenden Bots an den
CursorClient (Build-Schritt 6) sind ueber ``Deps`` injizierbar -> die Startup-
Invarianten sind ohne echtes Spiel/CTk testbar.
"""

import argparse
import os
import sys
import threading

HEARTBEAT_INTERVAL_S = 2.0
VALID_MODES = ('fischen', 'puzzle', 'seher', 'energiesplitter')


def build_arg_parser():
    p = argparse.ArgumentParser(prog='worker', add_help=True)
    p.add_argument('--worker', action='store_true',
                   help='Marker fuer den EXE-internen Worker-Zweig (frozen).')
    p.add_argument('--client', type=int, required=True)
    p.add_argument('--hwnd', type=int, required=True)
    p.add_argument('--mode', required=True, choices=VALID_MODES)
    p.add_argument('--ipc-fd-in', type=int, default=None)
    p.add_argument('--ipc-fd-out', type=int, default=None)
    return p


class Deps:
    """Injizierbare Abhaengigkeiten (Default: echte Implementierungen, lazy)."""

    def configure_log(self, path):
        from debuglog import log
        log.configure(to_console=False, to_file=True, path=path, level='INFO')

    def set_hwnd(self, hwnd):
        import windowcapture
        windowcapture.set_preferred_hwnd(hwnd)

    def make_ipc(self, fd_in, fd_out, idx):
        from worker_ipc import WorkerIpc
        return WorkerIpc(fd_in, fd_out, idx).start()

    def make_cursor(self, idx, hwnd, ipc):
        import constants
        import windowcapture
        from cursor_client import CursorClient
        wincap = windowcapture.WindowCapture(constants.GAME_NAME)
        return CursorClient(
            idx=idx, hwnd=hwnd,
            to_screen=lambda cx, cy: wincap.get_screen_position((cx, cy)),
            acquire=ipc.acquire, release=ipc.release,
            stop_check=ipc.stop_requested)

    def run_mode(self, mode, cursor, ipc, args):
        # Build-Schritt 6/6b (live): den jeweiligen Bot OHNE CTk-App headless
        # ticken (worker_modes). ALLE Modi sind angebunden (fischen/puzzle/
        # energiesplitter/seher). ``cursor`` (aus make_cursor, client->screen)
        # wird hier NICHT genutzt -- worker_modes baut den modus-passenden Cursor
        # (identity-to_screen, weil die Bots bereits Bildschirm-Koordinaten liefern).
        import worker_modes
        return worker_modes.run_mode(mode, ipc, args)


def _heartbeat_loop(ipc, stop_event, interval=HEARTBEAT_INTERVAL_S):
    """Sendet regelmaessig Heartbeats, UNABHAENGIG von der Modus-Schleife.

    Eigener Thread, damit ein langer Burst/Settle den Heartbeat nicht verzoegert
    (sonst False-Hang-Kill durch den Supervisor)."""
    while not stop_event.is_set() and not ipc.stop_requested():
        ipc.heartbeat()
        stop_event.wait(interval)


def run(argv, deps=None):
    """Startet den Worker. Gibt einen Exit-Code zurueck (0 = sauberes Ende)."""
    deps = deps or Deps()
    args = build_arg_parser().parse_args(argv)

    # 1) per-Client Datenordner + isoliertes Logging (kein stdout!).
    from interface.config import paths
    data_dir = paths.client_data_dir() or os.getcwd()
    deps.configure_log(os.path.join(data_dir, paths.DEBUG_LOG_FILENAME))

    # 2) Ziel-Fenster fixieren (vor jeder WindowCapture).
    deps.set_hwnd(args.hwnd)

    # 3) IPC + Cursor-Adapter (Telemetrie wird BEWUSST NIE gestartet).
    ipc = deps.make_ipc(args.ipc_fd_in, args.ipc_fd_out, args.client)
    cursor = deps.make_cursor(args.client, args.hwnd, ipc)

    # 4) Heartbeat-Thread.
    stop_event = threading.Event()
    hb = threading.Thread(target=_heartbeat_loop, args=(ipc, stop_event),
                          daemon=True, name=f'hb-{args.client}')
    hb.start()

    # 5) Modus-Schleife (bis Stop/Fehler).
    try:
        deps.run_mode(args.mode, cursor, ipc, args)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        stop_event.set()
        try:
            ipc.close()
        except Exception:
            pass


def main():
    sys.exit(run(sys.argv[1:]))


if __name__ == '__main__':
    main()
