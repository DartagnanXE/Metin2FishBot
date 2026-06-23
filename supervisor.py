# -*- coding: utf-8 -*-
"""Supervisor: startet/ueberwacht 1-4 Worker-Prozesse mit FEHLER-ISOLATION.

Kern-Anforderung: Crasht ODER haengt ein Client, laufen die UEBRIGEN ungestoert
weiter (OS-Prozessgrenze garantiert das strukturell -- ein Segfault/OOM/Hang
beendet nur den betroffenen Worker). Dynamisches Hinzufuegen/Entfernen 1-4 zur
Laufzeit. Pre-Spawn-Gate fuer trained_V (G5).

Trennung fuer Testbarkeit: die gesamte LEBENSZYKLUS-Logik (spawn/crash/restart/
heartbeat/dispatch) nutzt einen injizierten ``spawn_fn`` und injizierte Uhr ->
voll unit-testbar mit Fake-Prozessen, OHNE echte Subprozesse/Pipes/Fenster.
"""

import os
import sys

#: Worker gilt als haengend, wenn so lange (s) kein Heartbeat kam -> wird gekillt.
HEARTBEAT_TIMEOUT = 8.0

#: Schonfrist nach dem Spawn, in der NICHT per Heartbeat gekillt wird. Ein Worker
#: laedt beim Start cv2 + Templates + trained_V (mehrere Sekunden), bevor sein
#: Heartbeat-Thread laeuft -> ohne Grace wuerde poll() ihn faelschlich als
#: "haengend" toeten (Devil's-Advocate-Befund). Crash-Erkennung (Exit-Code) gilt
#: dagegen SOFORT -- ein beim Start abgestuerzter Worker wird nicht verschont.
STARTUP_GRACE_S = 15.0


def build_worker_cmd(python_exe, worker_script, idx, hwnd, mode,
                     ipc_fd_in=None, ipc_fd_out=None):
    """Baut die Kommandozeile fuer einen Worker-Prozess (rein, testbar).

    Im frozen-Zustand (PyInstaller) ist ``worker_script`` None -> der Worker-Modus
    wird ueber ein Flag der EXE selbst gestartet (``sys.executable --worker ...``).
    """
    cmd = [python_exe]
    if worker_script:
        cmd.append(worker_script)
    else:
        cmd.append('--worker')          # frozen: EXE-interner Worker-Zweig
    cmd += ['--client', str(idx), '--hwnd', str(hwnd), '--mode', str(mode)]
    if ipc_fd_in is not None:
        cmd += ['--ipc-fd-in', str(ipc_fd_in)]
    if ipc_fd_out is not None:
        cmd += ['--ipc-fd-out', str(ipc_fd_out)]
    return cmd


def ensure_trained_v(build_fn, env=None):
    """G5: trained_V GENAU EINMAL vor dem ersten Spawn bauen + ENV setzen.

    ``build_fn()`` baut/liefert den Pfad der fertigen ``trained_V.npy`` (atomar).
    Danach werden ``M2FB_TRAINED_V`` + ``M2FB_TRAINED_V_READY`` gesetzt, sodass
    die Worker NUR noch read-only laden (kein 4x-Compute, kein np.save-Race).
    Idempotent: ist READY bereits gesetzt, passiert nichts. Wirft die Exception
    von ``build_fn`` weiter (ein fehlendes V ist ein harter Startfehler).
    """
    env = env if env is not None else os.environ
    if env.get('M2FB_TRAINED_V_READY'):
        return env.get('M2FB_TRAINED_V')
    path = build_fn()
    env['M2FB_TRAINED_V'] = str(path)
    env['M2FB_TRAINED_V_READY'] = '1'
    return path


class ClientHandle:
    """Laufzeit-Zustand eines Worker-Prozesses."""

    __slots__ = ('idx', 'proc', 'hwnd', 'mode', 'data_dir', 'started_at',
                 'last_heartbeat', 'restarts', 'state')

    def __init__(self, idx, proc, hwnd, mode, data_dir, now):
        self.idx = idx
        self.proc = proc
        self.hwnd = hwnd
        self.mode = mode
        self.data_dir = data_dir
        self.started_at = now
        self.last_heartbeat = now
        self.restarts = 0
        self.state = 'running'


class Supervisor:
    """Verwaltet die Client-Handles + Crash/Hang-Erkennung + Restart-Policy.

    :param spawn_fn: ``callable(idx, hwnd, mode, data_dir) -> proc`` -- erzeugt
        den Worker-Prozess. ``proc`` muss ``poll()`` (None=laeuft, sonst
        Exit-Code), ``terminate()`` und ``kill()`` bieten (subprocess.Popen-API).
    :param broker: optionaler :class:`cursor_broker.CursorBroker` -- bekommt
        ``on_eof(idx)`` wenn ein Worker stirbt (Lease sofort freigeben).
    :param on_event: optional ``callable(event_dict)`` -- UI/Log-Haken.
    :param auto_restart: bei Crash automatisch neu starten (Default aus -- ein
        Crash ist meist reproduzierbar; verhindert Restart-Sturm).
    :param clock: ``callable() -> float`` -- injizierbare Uhr fuer Tests.
    """

    def __init__(self, spawn_fn, broker=None, on_event=None, auto_restart=False,
                 heartbeat_timeout=HEARTBEAT_TIMEOUT, clock=None, max_clients=4,
                 startup_grace_s=STARTUP_GRACE_S):
        self._spawn = spawn_fn
        self._broker = broker
        self._on_event = on_event or (lambda ev: None)
        self.auto_restart = auto_restart
        self.heartbeat_timeout = heartbeat_timeout
        self.startup_grace_s = startup_grace_s
        self._clock = clock or (lambda: 0.0)
        self.max_clients = max_clients
        self.clients = {}      # idx -> ClientHandle

    # -- Lebenszyklus -------------------------------------------------------
    def add_client(self, idx, hwnd, mode, data_dir):
        """Startet einen Worker (dynamisch zur Laufzeit). Idempotent pro idx."""
        if idx in self.clients:
            raise ValueError(f'Client {idx} laeuft bereits')
        if len(self.clients) >= self.max_clients:
            raise ValueError(f'max_clients={self.max_clients} erreicht')
        now = self._clock()
        proc = self._spawn(idx, hwnd, mode, data_dir)
        self.clients[idx] = ClientHandle(idx, proc, hwnd, mode, data_dir, now)
        self._emit('client_started', idx=idx, mode=mode, hwnd=hwnd)
        return self.clients[idx]

    def remove_client(self, idx, reason='user'):
        """Beendet einen Worker sauber (dynamisch). Lease wird freigegeben."""
        h = self.clients.pop(idx, None)
        if h is None:
            return False
        _safe_terminate(h.proc)
        self._drop_lease(idx)
        self._emit('client_removed', idx=idx, reason=reason)
        return True

    def heartbeat(self, idx, now=None):
        """Markiert einen Worker als lebendig (per IPC-Heartbeat aufgerufen)."""
        h = self.clients.get(idx)
        if h is not None:
            h.last_heartbeat = now if now is not None else self._clock()

    def dispatch_message(self, idx, msg, now=None):
        """Leitet eine IPC-Nachricht: Heartbeat -> Supervisor, Lease -> Broker."""
        now = now if now is not None else self._clock()
        cmd = msg.get('cmd')
        if cmd == 'heartbeat':
            self.heartbeat(idx, now)
        elif cmd in ('acquire', 'release') and self._broker is not None:
            self._broker.on_message(idx, msg, now)

    # -- Crash-/Hang-Erkennung ---------------------------------------------
    def poll(self, now=None):
        """Prueft ALLE Clients auf Tod (Exit) oder Haenger (Heartbeat-Timeout).

        Gibt die Liste der entfernten/abgestuerzten idx zurueck. GARANTIE: ein
        toter/haengender Client beruehrt die anderen Handles NICHT -- nur er wird
        behandelt (Fehler-Isolation).
        """
        now = now if now is not None else self._clock()
        crashed = []
        # ueber eine Kopie iterieren -- wir veraendern self.clients dabei.
        for idx, h in list(self.clients.items()):
            code = _safe_poll(h.proc)
            if code is not None:
                self._handle_crash(idx, reason=f'exit:{code}')
                crashed.append(idx)
                continue
            # Schonfrist: ein frisch gestarteter Worker lebt evtl. (laedt noch),
            # hat aber noch keinen Heartbeat geschickt -> nicht killen.
            if (now - h.started_at) <= self.startup_grace_s:
                continue
            if (now - h.last_heartbeat) > self.heartbeat_timeout:
                # Haenger: hart killen, dann wie Crash behandeln (Finding #2:
                # Heartbeat-Timeout ist der Hang-Detektor auf Supervisor-Ebene).
                _safe_kill(h.proc)
                self._handle_crash(idx, reason='heartbeat_timeout')
                crashed.append(idx)
        return crashed

    def _handle_crash(self, idx, reason):
        h = self.clients.pop(idx, None)
        if h is None:
            return
        self._drop_lease(idx)          # toter Worker haelt evtl. die Lease
        self._emit('client_crashed', idx=idx, reason=reason, mode=h.mode)
        if self.auto_restart:
            self._respawn(h, reason)

    def _respawn(self, old, reason):
        now = self._clock()
        try:
            proc = self._spawn(old.idx, old.hwnd, old.mode, old.data_dir)
        except Exception as exc:        # Respawn-Fehler darf Supervisor nicht toeten
            self._emit('client_restart_failed', idx=old.idx, error=str(exc))
            return
        nh = ClientHandle(old.idx, proc, old.hwnd, old.mode, old.data_dir, now)
        nh.restarts = old.restarts + 1
        self.clients[old.idx] = nh
        self._emit('client_restarted', idx=old.idx, restarts=nh.restarts,
                   reason=reason)

    def shutdown(self):
        """Beendet alle Worker (z.B. bei F6/Programmende)."""
        for idx in list(self.clients):
            self.remove_client(idx, reason='shutdown')

    # -- intern -------------------------------------------------------------
    def _drop_lease(self, idx):
        if self._broker is not None:
            try:
                self._broker.on_eof(idx, self._clock())
            except Exception:
                pass

    def _emit(self, event, **kw):
        try:
            self._on_event(dict(event=event, **kw))
        except Exception:
            pass

    @property
    def alive_ids(self):
        return sorted(self.clients)


# -- defensive Prozess-Helfer (None-/Fehler-tolerant) -----------------------
def _safe_poll(proc):
    try:
        return proc.poll()
    except Exception:
        return -1          # nicht abfragbar -> als tot behandeln


def _safe_terminate(proc):
    try:
        proc.terminate()
    except Exception:
        pass


def _safe_kill(proc):
    try:
        proc.kill()
    except Exception:
        pass


def default_python_exe():
    """Der Interpreter/EXE-Pfad fuer Worker-Spawns (frozen-bewusst)."""
    return sys.executable
