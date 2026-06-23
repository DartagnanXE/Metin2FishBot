# -*- coding: utf-8 -*-
"""Laufzeit-Huelle des Cursor-Brokers: ein Thread bedient ALLE Worker-Pipes.

Verbindet die reine :class:`cursor_broker.CursorBroker`-Logik mit echten FDs:
liest acquire/release/heartbeat der Worker (``selectors``), schreibt Grants
zurueck, ruft periodisch ``tick`` (Hang-Hard-Timeout). EOF eines Workers ->
``on_eof`` (Lease-Drop). Der Heartbeat wird an einen optionalen Callback
weitergereicht (Supervisor-Liveness).

Bewusst getrennt von der Logik, damit Letztere ohne FDs/Threads testbar bleibt;
diese Huelle wird per Integrationstest mit echten ``os.pipe()`` geprueft.
"""

import os
import selectors
import threading
import time

from cursor_broker import CursorBroker, decode_lines, encode_msg


class BrokerServer:
    def __init__(self, neutralize=None, on_revoke=None, on_heartbeat=None,
                 lease_timeout=5.0, drag_timeout=20.0, tick_interval=0.25,
                 clock=None):
        self._sel = selectors.DefaultSelector()
        self._wfds = {}                # idx -> write_fd (Grants an Worker)
        self._bufs = {}               # idx -> Lese-Restpuffer
        self._on_heartbeat = on_heartbeat or (lambda idx, now: None)
        self._clock = clock or time.monotonic
        self._tick_interval = tick_interval
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self.broker = CursorBroker(
            send_grant=self._send_grant, neutralize=neutralize,
            on_revoke=on_revoke, lease_timeout=lease_timeout,
            drag_timeout=drag_timeout)

    # -- Registrierung ------------------------------------------------------
    def register(self, idx, read_fd, write_fd):
        """Registriert einen Worker: server liest ``read_fd``, schreibt ``write_fd``."""
        with self._lock:
            self._wfds[idx] = write_fd
            self._bufs[idx] = b''
            self._sel.register(read_fd, selectors.EVENT_READ, idx)

    def _unregister(self, idx, read_fd):
        try:
            self._sel.unregister(read_fd)
        except Exception:
            pass
        self._wfds.pop(idx, None)
        self._bufs.pop(idx, None)

    # -- Thread -------------------------------------------------------------
    def start(self):
        self._thread = threading.Thread(target=self.serve, daemon=True,
                                        name='cursor-broker')
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def serve(self):
        """Haupt-Loop: I/O + periodischer Tick bis ``stop()``."""
        next_tick = self._clock() + self._tick_interval
        while not self._stop.is_set():
            events = self._sel.select(timeout=self._tick_interval)
            for key, _mask in events:
                self._on_readable(key.fileobj, key.data)
            now = self._clock()
            if now >= next_tick:
                with self._lock:
                    self.broker.tick(now)
                next_tick = now + self._tick_interval

    def _on_readable(self, read_fd, idx):
        try:
            chunk = os.read(read_fd, 4096)
        except Exception:
            chunk = b''
        if not chunk:                          # EOF -> Worker tot (Crash)
            with self._lock:
                self.broker.on_eof(idx, self._clock())
                self._unregister(idx, read_fd)
            return
        buf = self._bufs.get(idx, b'') + chunk
        msgs, buf = decode_lines(buf)
        self._bufs[idx] = buf
        for msg in msgs:
            now = self._clock()
            if msg.get('cmd') == 'heartbeat':
                self._on_heartbeat(idx, now)
            else:
                with self._lock:
                    self.broker.on_message(idx, msg, now)

    # -- Grant-Zustellung ---------------------------------------------------
    def _send_grant(self, idx):
        fd = self._wfds.get(idx)
        if fd is None:
            return
        try:
            os.write(fd, encode_msg({'grant': idx}))
        except Exception:
            pass

    def broadcast_stop(self):
        """Schickt allen Workern ein Stop (F6-Broadcast)."""
        with self._lock:
            fds = list(self._wfds.values())
        for fd in fds:
            try:
                os.write(fd, encode_msg({'cmd': 'stop'}))
            except Exception:
                pass
