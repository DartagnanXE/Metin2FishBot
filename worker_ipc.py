# -*- coding: utf-8 -*-
"""Worker-seitige IPC zum Supervisor/Broker ueber ein dediziertes Pipe-Paar.

NICHT stdin/stdout (das ist von debuglog belegt, Finding #7) -- der Supervisor
uebergibt pro Worker zwei FDs: ``fd_in`` (Worker liest: grant/stop) und
``fd_out`` (Worker schreibt: acquire/release/heartbeat).

:class:`WorkerIpc` liefert die blockierende ``acquire``-Semantik, die
:class:`cursor_client.CursorClient` erwartet: ``acquire`` schickt die Anfrage und
WARTET auf das Grant des Brokers (FIFO-fair) -- so nutzt immer nur EIN Worker den
physischen Cursor. Ein Reader-Thread verarbeitet eingehende Nachrichten.

Voll testbar mit echten ``os.pipe()`` im selben Prozess (Linux/WSL).
"""

import os
import threading

from cursor_broker import encode_msg, decode_lines


class WorkerIpc:
    def __init__(self, fd_in, fd_out, idx):
        self._fd_in = fd_in
        self._fd_out = fd_out
        self.idx = idx
        self._grant = threading.Event()
        self._stop = threading.Event()
        self._closed = threading.Event()
        self._write_lock = threading.Lock()
        self._reader = None

    # -- Lebenszyklus -------------------------------------------------------
    def start(self):
        """Startet den Reader-Thread (Daemon)."""
        self._reader = threading.Thread(target=self._read_loop, daemon=True,
                                        name=f'worker-ipc-{self.idx}')
        self._reader.start()
        return self

    def close(self):
        self._closed.set()
        for fd in (self._fd_in, self._fd_out):
            try:
                os.close(fd)
            except Exception:
                pass

    # -- Senden (vom Worker/CursorClient) ----------------------------------
    def _send(self, obj):
        try:
            with self._write_lock:
                os.write(self._fd_out, encode_msg(obj))
            return True
        except Exception:
            self._closed.set()
            return False

    def acquire(self, idx, holds_button, timeout=10.0):
        """Fordert die Cursor-Lease an und BLOCKIERT bis zum Grant (oder Timeout).

        Passt zur ``CursorClient``-Erwartung (acquire blockiert -> danach exklusiv).
        :raises TimeoutError: wenn der Broker nicht rechtzeitig grantet.
        :raises BrokenPipeError: wenn die Verbindung zu ist.
        """
        if self._closed.is_set():
            raise BrokenPipeError('IPC closed')
        self._grant.clear()
        if not self._send({'cmd': 'acquire', 'idx': idx,
                           'holds_button': bool(holds_button)}):
            raise BrokenPipeError('acquire send failed')
        if not self._grant.wait(timeout):
            raise TimeoutError(f'Lease-Grant Timeout (idx={idx})')

    def release(self, idx):
        self._send({'cmd': 'release', 'idx': idx})

    def heartbeat(self):
        self._send({'cmd': 'heartbeat', 'idx': self.idx})

    # -- Status -------------------------------------------------------------
    def stop_requested(self):
        return self._stop.is_set() or self._closed.is_set()

    @property
    def closed(self):
        return self._closed.is_set()

    # -- Empfangen ----------------------------------------------------------
    def _read_loop(self):
        buf = b''
        while not self._closed.is_set():
            try:
                chunk = os.read(self._fd_in, 4096)
            except Exception:
                break
            if not chunk:                  # EOF -> Supervisor/Pipe zu
                break
            buf += chunk
            msgs, buf = decode_lines(buf)
            for msg in msgs:
                self._dispatch(msg)
        self._closed.set()
        self._grant.set()                  # wartende acquire aufwecken (-> Timeout/Pipe)

    def _dispatch(self, msg):
        cmd = msg.get('cmd')
        if cmd == 'grant' or 'grant' in msg:
            self._grant.set()
        elif cmd == 'stop':
            self._stop.set()
            self._grant.set()              # laufende acquire freigeben (Abbruch)
