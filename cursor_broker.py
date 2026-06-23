# -*- coding: utf-8 -*-
"""Cursor-Broker: serialisiert den EINEN physischen Maus-Cursor ueber 1-4 Worker.

Hintergrund (verifiziert, siehe MULTICLIENT_PLAN.md): Metin2 ignoriert
Background-Klicks -> jeder Worker muss den ECHTEN Cursor benutzen (click-to-
activate). Es gibt aber nur EINEN OS-Cursor pro Session. Der Broker vergibt das
exklusive Recht (Lease), den Cursor fuer einen Klick-Burst zu benutzen.

Architektur (Trennung fuer Testbarkeit):
  * :class:`LeaseScheduler` -- REINE Scheduling-Logik (FIFO + Hard-Timeout +
    Force-Revoke + Drag-Schutz). Zeit wird injiziert -> deterministisch + voll
    unit-testbar OHNE Threads/Pipes/echten Cursor.
  * :class:`CursorBroker` -- duenne Huelle: nimmt acquire/release/eof/tick-Events
    entgegen und wendet die Scheduler-Ausgabe ueber injizierte Callbacks
    (``send_grant``, ``neutralize``) an. Der reale Thread-/Pipe-Loop ruft nur
    diese Methoden -> auch der Broker ist mit Fakes testbar.

KRITISCHE INVARIANTEN (aus der adversarialen Verifikation):
  * Finding #1: Vor JEDER Neuvergabe nach einem Force-Revoke wird der globale
    Maustasten-Zustand neutralisiert (``neutralize`` -> mouseUp left+right),
    sonst zieht eine vom alten Holder gedrueckt gelassene Taste quer durch das
    naechste Fenster. UND: ein Burst mit gehaltener Taste (Drag, ``holds_button``)
    ist NICHT vom normalen Hard-Timeout entziehbar (nur vom hoeheren Drag-Cap).
  * Finding #2: Der Lease-Hard-Timeout ist der EINZIGE Hang-Detektor. Pipe-EOF
    (:meth:`on_eof`) deckt nur den Crash-Fall (Prozess tot -> Pipe zu).
"""

import json

#: Default-Obergrenzen (Sekunden). Ein normaler Klick-Burst ist << 1s; der
#: Hard-Timeout faengt nur einen HAENGENDEN Worker (Finding #2). Drags halten
#: eine Taste und brauchen laenger -> eigener, deutlich hoeherer Cap, damit ein
#: legitimer Drag nicht mitten im Zug entzogen wird (Finding #1).
LEASE_HARD_TIMEOUT = 5.0
DRAG_HARD_TIMEOUT = 20.0


class LeaseScheduler:
    """Reine FIFO-Lease-Logik mit Hard-Timeout + Drag-Schutz. Zeit injiziert.

    Alle Methoden liefern eine Liste von Event-Tupeln zurueck, die der Aufrufer
    anwendet:
      * ``('grant', idx)``      -- Worker idx darf den Cursor jetzt nutzen.
      * ``('neutralize',)``     -- globalen Button-State loesen (vor Neuvergabe).
      * ``('revoke', idx, why)``-- Worker idx wurde die Lease entzogen (Log/Kill).
    """

    def __init__(self, lease_timeout=LEASE_HARD_TIMEOUT,
                 drag_timeout=DRAG_HARD_TIMEOUT):
        self.lease_timeout = lease_timeout
        self.drag_timeout = drag_timeout
        self.holder = None            # idx des aktuellen Lease-Inhabers oder None
        self.holder_since = 0.0
        self.holder_holds_button = False
        self._queue = []              # FIFO: Liste von (idx, holds_button)

    # -- Anfragen -----------------------------------------------------------
    def request(self, idx, holds_button, now):
        """Worker fordert die Lease an. Sofort-Grant wenn frei, sonst FIFO-Queue."""
        # Doppelanfragen desselben Workers ignorieren (idempotent / robust).
        if idx == self.holder:
            return []
        if any(q_idx == idx for q_idx, _ in self._queue):
            return []
        self._queue.append((idx, bool(holds_button)))
        return self._pump(now)

    def release(self, idx, now):
        """Worker gibt die Lease frei (Burst fertig)."""
        if idx == self.holder:
            self.holder = None
            return self._pump(now)
        # Freigabe aus der Warteschlange (selten) -> entfernen.
        self._queue = [q for q in self._queue if q[0] != idx]
        return []

    def drop(self, idx, now):
        """Worker ist TOT (Pipe-EOF/Crash, Finding #2): aus allem entfernen.

        Hielt der tote Worker die Lease, koennte er eine Taste gedrueckt gelassen
        haben -> wie beim Force-Revoke neutralisieren, bevor neu vergeben wird.
        """
        self._queue = [q for q in self._queue if q[0] != idx]
        if idx == self.holder:
            self.holder = None
            events = [('neutralize',)]
            events.extend(self._pump(now))
            return events
        return []

    def tick(self, now):
        """Periodischer Takt: erkennt HAENGENDE Worker per Hard-Timeout.

        Normaler Burst -> ``lease_timeout``. Drag (gehaltene Taste) -> der
        deutlich hoehere ``drag_timeout`` (Finding #1: nie mitten im Drag
        entziehen). Bei Entzug erst neutralisieren, dann neu vergeben.
        """
        if self.holder is None:
            return []
        cap = self.drag_timeout if self.holder_holds_button else self.lease_timeout
        if (now - self.holder_since) < cap:
            return []
        why = 'drag_timeout' if self.holder_holds_button else 'lease_timeout'
        revoked = self.holder
        self.holder = None
        events = [('revoke', revoked, why), ('neutralize',)]
        events.extend(self._pump(now))
        return events

    # -- intern -------------------------------------------------------------
    def _pump(self, now):
        """Vergibt die freie Lease an den naechsten Wartenden (FIFO)."""
        if self.holder is not None or not self._queue:
            return []
        idx, holds_button = self._queue.pop(0)
        self.holder = idx
        self.holder_since = now
        self.holder_holds_button = holds_button
        return [('grant', idx)]

    # -- Introspektion (Tests/Debug) ---------------------------------------
    @property
    def waiting(self):
        return [q[0] for q in self._queue]


class CursorBroker:
    """Duenne Huelle um :class:`LeaseScheduler` mit angewandten Seiteneffekten.

    :param send_grant: ``callable(idx)`` -- schickt dem Worker das Grant.
    :param neutralize: ``callable()`` -- loest den globalen Maustasten-Zustand
        (real: ``pydirectinput.mouseUp(left)+mouseUp(right)``). Default: echtes
        pydirectinput (lazy importiert), damit der Broker im Test ohne die
        Abhaengigkeit konstruiert werden kann.
    :param on_revoke: optional ``callable(idx, why)`` -- Log/Eskalation.
    """

    def __init__(self, send_grant, neutralize=None, on_revoke=None,
                 lease_timeout=LEASE_HARD_TIMEOUT, drag_timeout=DRAG_HARD_TIMEOUT):
        self.sched = LeaseScheduler(lease_timeout, drag_timeout)
        self._send_grant = send_grant
        self._neutralize = neutralize or _default_neutralize
        self._on_revoke = on_revoke or (lambda idx, why: None)

    def on_acquire(self, idx, holds_button, now):
        self._apply(self.sched.request(idx, holds_button, now))

    def on_release(self, idx, now):
        self._apply(self.sched.release(idx, now))

    def on_eof(self, idx, now):
        self._apply(self.sched.drop(idx, now))

    def tick(self, now):
        self._apply(self.sched.tick(now))

    def on_message(self, idx, msg, now):
        """Verarbeitet eine dekodierte IPC-Nachricht eines Workers."""
        cmd = msg.get('cmd')
        if cmd == 'acquire':
            self.on_acquire(idx, bool(msg.get('holds_button')), now)
        elif cmd == 'release':
            self.on_release(idx, now)
        # unbekannte cmds bewusst ignorieren (robust gegen Protokoll-Drift)

    def _apply(self, events):
        for ev in events:
            kind = ev[0]
            if kind == 'grant':
                self._send_grant(ev[1])
            elif kind == 'neutralize':
                self._neutralize()
            elif kind == 'revoke':
                self._on_revoke(ev[1], ev[2])


def _default_neutralize():
    """Echtes Loesen beider Maustasten am globalen Cursor. Wirft nie."""
    try:
        import pydirectinput
        pydirectinput.mouseUp(button='left')
        pydirectinput.mouseUp(button='right')
    except Exception:
        pass


# -- IPC-Hilfen (newline-delimited JSON ueber die dedizierte Pipe) ----------
def encode_msg(obj):
    """Kodiert eine IPC-Nachricht als eine newline-terminierte JSON-Zeile."""
    return (json.dumps(obj, separators=(',', ':')) + '\n').encode('utf-8')


def decode_lines(buffer):
    """Zerlegt einen Byte-Puffer in (vollstaendige Nachrichten, Rest-Puffer).

    Tolerant: kaputte Zeilen werden uebersprungen (Protokoll-Robustheit).
    """
    msgs = []
    while b'\n' in buffer:
        line, buffer = buffer.split(b'\n', 1)
        line = line.strip()
        if not line:
            continue
        try:
            msgs.append(json.loads(line.decode('utf-8')))
        except Exception:
            continue
    return msgs, buffer
