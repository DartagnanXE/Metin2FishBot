# -*- coding: utf-8 -*-
"""Minimaler CLI-Launcher fuer den Multiclient-Betrieb (Build-Schritt 11).

Verdrahtet die fertigen Bausteine zu einem startbaren Ganzen:

  BrokerServer (eine physische Maus, Lease)  +  Supervisor (1-4 Worker-Prozesse)
        ^  Heartbeat/Lease/EOF ueber je-Worker os.pipe()-Paar  ^
        └──────────────── spawn: worker.py --client/--hwnd/--mode ───────────┘

Pro Client zwei ``os.pipe()``-Paare (Worker->Broker: acquire/release/heartbeat;
Broker->Worker: grant/stop), beim Broker registriert und per ``pass_fds`` an den
Worker-Prozess vererbt. Der Broker-Thread routet eingehende Nachrichten selbst
(Heartbeat -> Supervisor, Lease -> CursorBroker, EOF -> Lease freigeben).

LIVE-ONLY: der reale Prozess-Spawn (``subprocess.Popen`` + FD-Vererbung) und die
Fenster-Enumeration sind nur am Windows-Spiel verifizierbar. Die ORCHESTRIERUNG
(Pipe-Paarung, Registrierung, Kommandozeile, Broker/Supervisor-Verdrahtung,
Lauf-/Stop-Schleife) ist ueber injizierte Bausteine (``*_factory``/``popen``/
``pipe``) unit-getestet. Hinweis: ``pass_fds`` vererbt FDs unter Unix direkt; auf
Windows nutzt CPython (>=3.7) die Handle-Vererbungsliste -- das ist am echten
Windows-Build zu bestaetigen (offene Frage des MULTICLIENT_PLAN, Schritt 11/12).
"""

import argparse
import os
import subprocess
import sys
import time

import supervisor as _sup
import cursor_broker_runtime as _broker_rt
from interface.config import paths as _paths

#: Default-Modus, wenn beim Auto-Zuordnen keiner angegeben ist.
DEFAULT_MODE = 'fischen'
VALID_MODES = ('fischen', 'puzzle', 'seher', 'energiesplitter')
POLL_INTERVAL_S = 0.5


# -- Datenisolation -----------------------------------------------------------

def client_data_dir(idx, appdata=None):
    """Privater ``%APPDATA%/<APP_DIR>/client-<idx>/``-Ordner eines Workers.

    Wird dem Worker als ``M2FB_DATA_DIR`` mitgegeben -> Config/Stats/Log isoliert.
    Legt nichts an (das macht der Worker via ``paths.client_data_dir``). Wirft nie.
    """
    try:
        base = appdata if appdata is not None else os.environ.get('APPDATA')
        if not base:
            base = os.path.expanduser('~')
        return os.path.join(base, _paths.APP_DIR, f'client-{idx}')
    except Exception:
        return os.path.join('.', f'client-{idx}')


# -- Fenster-Auswahl ----------------------------------------------------------

def list_windows(enumerate_fn=None):
    """Liefert die sichtbaren METIN2-Fenster ``[{hwnd,w,h,x,y}, ...]``."""
    if enumerate_fn is None:
        import windowcapture
        import constants
        name = getattr(constants, 'GAME_NAME', 'METIN2')
        enumerate_fn = lambda: windowcapture.enumerate_game_windows(name)
    try:
        return enumerate_fn() or []
    except Exception:
        return []


# -- Spawn (real, aber injizierbar) -------------------------------------------

def make_spawn(python_exe, worker_script, broker, *, popen=None, pipe=None,
               set_inheritable=None, closer=None, base_env=None):
    """Baut ``spawn_fn(idx, hwnd, mode, data_dir) -> proc`` fuer den Supervisor.

    Pro Aufruf: zwei ``os.pipe()``-Paare anlegen, beim ``broker`` registrieren
    (er liest die Worker->Broker-Richtung, schreibt Grants in die andere), die
    worker-seitigen FDs vererbbar machen, ``worker.py`` per ``pass_fds`` spawnen
    und die worker-seitigen FDs im Parent schliessen (nur der Worker nutzt sie).
    Alle OS-Primitiven sind injizierbar -> die Verdrahtung ist testbar.
    """
    popen = popen or subprocess.Popen
    pipe = pipe or os.pipe
    set_inheritable = set_inheritable or os.set_inheritable
    closer = closer or os.close
    base_env = base_env if base_env is not None else os.environ

    def spawn(idx, hwnd, mode, data_dir):
        # a: Worker -> Broker (Worker schreibt a_w, Broker liest a_r)
        # b: Broker -> Worker (Broker schreibt b_w, Worker liest b_r)
        a_r, a_w = pipe()
        b_r, b_w = pipe()
        broker.register(idx, a_r, b_w)          # Parent/Broker behaelt a_r + b_w
        for fd in (b_r, a_w):                    # worker-seitige FDs vererbbar
            try:
                set_inheritable(fd, True)
            except Exception:
                pass
        cmd = _sup.build_worker_cmd(
            python_exe, worker_script, idx, hwnd, mode,
            ipc_fd_in=b_r, ipc_fd_out=a_w)
        env = dict(base_env)
        if data_dir:
            env['M2FB_DATA_DIR'] = data_dir
        proc = popen(cmd, pass_fds=(b_r, a_w), env=env)
        for fd in (b_r, a_w):                    # im Parent schliessen
            try:
                closer(fd)
            except Exception:
                pass
        return proc

    return spawn


# -- Default-Factories (echte Bausteine) --------------------------------------

def _default_neutralize():
    """Maustasten loesen (bei Force-Revoke) -- lazy, damit headless importierbar."""
    def _neutral():
        try:
            import pydirectinput
            pydirectinput.mouseUp(button='left')
            pydirectinput.mouseUp(button='right')
        except Exception:
            pass
    return _neutral


def _default_broker_factory(on_heartbeat):
    return _broker_rt.BrokerServer(
        neutralize=_default_neutralize(), on_heartbeat=on_heartbeat)


def _default_supervisor_factory(spawn, broker_core, on_event, clock):
    return _sup.Supervisor(spawn, broker=broker_core, on_event=on_event,
                           clock=clock)


# -- Orchestrierung -----------------------------------------------------------

def run(specs, *, python_exe=None, worker_script='worker.py',
        broker_factory=None, supervisor_factory=None, spawn_factory=None,
        sleep=None, poll_interval=POLL_INTERVAL_S, should_run=None,
        on_event=None, clock=None):
    """Startet ``specs`` = ``[(hwnd, mode), ...]`` und ueberwacht bis Ende/Stop.

    Lauf endet, wenn kein Client mehr lebt, ``should_run()`` False wird oder
    Ctrl+C kommt -> Broadcast-Stop + sauberes Herunterfahren. Gibt den Supervisor
    zurueck. Alle Bausteine sind injizierbar (Tests).
    """
    sleep = sleep or time.sleep
    clock = clock or time.monotonic
    should_run = should_run or (lambda: True)

    holder = {}

    def _heartbeat(idx, now):
        sup = holder.get('sup')
        if sup is not None:
            sup.heartbeat(idx, now)

    broker = (broker_factory or _default_broker_factory)(_heartbeat)
    broker.start()
    try:
        spawn = (spawn_factory
                 or (lambda b: make_spawn(
                     python_exe or sys.executable, worker_script, b)))(broker)
        sup = (supervisor_factory or _default_supervisor_factory)(
            spawn, broker.broker, on_event, clock)
        holder['sup'] = sup

        for idx, (hwnd, mode) in enumerate(specs):
            sup.add_client(idx, hwnd, mode, client_data_dir(idx))

        try:
            while sup.alive_ids() and should_run():
                sup.poll()
                sleep(poll_interval)
        except KeyboardInterrupt:
            pass
        finally:
            try:
                broker.broadcast_stop()
            except Exception:
                pass
            sup.shutdown()
        return sup
    finally:
        try:
            broker.stop()
        except Exception:
            pass


# -- CLI ----------------------------------------------------------------------

def _parse_spec(text):
    """``"<hwnd>:<mode>"`` -> ``(hwnd:int, mode:str)``. Modus optional (Default)."""
    parts = text.split(':', 1)
    hwnd = int(parts[0])
    mode = parts[1] if len(parts) > 1 and parts[1] else DEFAULT_MODE
    if mode not in VALID_MODES:
        raise argparse.ArgumentTypeError(
            f'Modus {mode!r} unbekannt (erlaubt: {", ".join(VALID_MODES)})')
    return (hwnd, mode)


def build_arg_parser():
    p = argparse.ArgumentParser(
        prog='launcher',
        description='Metin2 MultiTool -- Multiclient-Launcher (1-4 Clients).')
    p.add_argument('--list', action='store_true',
                   help='sichtbare METIN2-Fenster auflisten und beenden')
    p.add_argument('--client', action='append', default=[], metavar='HWND[:MODE]',
                   type=_parse_spec,
                   help='Client: Fenster-HWND + Modus (mehrfach; Default-Modus '
                        f'{DEFAULT_MODE}). Bsp: --client 12345:puzzle')
    p.add_argument('--auto', type=int, default=0, metavar='N',
                   help=f'die ersten N gefundenen Fenster im Modus {DEFAULT_MODE} '
                        'starten')
    p.add_argument('--mode', default=DEFAULT_MODE, choices=VALID_MODES,
                   help=f'Modus fuer --auto (Default {DEFAULT_MODE})')
    p.add_argument('--worker-script', default='worker.py',
                   help='Pfad zu worker.py (frozen: leer lassen)')
    return p


def main(argv=None):                                   # pragma: no cover - CLI/live
    args = build_arg_parser().parse_args(argv)
    if args.list:
        wins = list_windows()
        if not wins:
            print('Keine sichtbaren METIN2-Fenster gefunden.')
            return 0
        print(f'{len(wins)} Fenster:')
        for w in wins:
            print(f"  hwnd={w['hwnd']}  {w['w']}x{w['h']}  @({w['x']},{w['y']})")
        return 0

    specs = list(args.client)
    if args.auto:
        wins = list_windows()
        for w in wins[:args.auto]:
            specs.append((w['hwnd'], args.mode))
    if not specs:
        print('Nichts zu starten. --list zum Anzeigen, --client/--auto zum Start.')
        return 1
    if len(specs) > 4:
        print('Maximal 4 Clients.')
        return 1
    print(f'Starte {len(specs)} Client(s): '
          + ', '.join(f'{h}:{m}' for (h, m) in specs) + '  (Ctrl+C = Stop)')
    run(specs, worker_script=(args.worker_script or None))
    return 0


if __name__ == '__main__':                             # pragma: no cover
    raise SystemExit(main())
