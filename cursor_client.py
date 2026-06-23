# -*- coding: utf-8 -*-
"""CursorClient: Worker-seitiger Adapter fuer JEDEN physischen Maus-/Tasten-Burst.

Kapselt die komplette, von der adversarialen Verifikation gehaertete Sequenz:

  Lease anfordern -> [mouseUp L+R | Finding #1] -> click-to-activate (Q1-Zone)
  -> Settle -> GetForegroundWindow==hwnd-Gate (G1, retry) -> PAUSE setzen (G2)
  -> atomare Aktions-Sequenz mit Stop-Poll JE Schritt (Finding #4)
  -> finally: mouseUp L+R (Finding #1) + Lease freigeben

Alle Abhaengigkeiten sind INJIZIERBAR (Input-Backend, Foreground-Abfrage,
Lease-Funktionen, Sleep, Stop-Check, Aktivierung) -> die Sequenz ist voll
unit-testbar OHNE echten Cursor/Fenster (Findings als Assertions).

Vertraege:
  * Ein Burst, der eine Maustaste GEHALTEN ueber die Sequenz fuehrt (Drag), wird
    mit ``holds_button=True`` markiert -> der Broker behandelt ihn non-revocable.
  * ``actions`` sind zero-arg Callables, die das Input-Backend nutzen; sie laufen
    NUR innerhalb der gehaltenen Lease + verifiziertem Fokus.
"""


class FocusNotAcquired(Exception):
    """click-to-activate hat das Zielfenster nicht in den Vordergrund gebracht."""


class BurstAborted(Exception):
    """Stop (F6) waehrend der Sequenz -> Burst sauber abgebrochen."""


DEFAULT_SETTLE_S = 0.06
DEFAULT_ACTIVATE_RETRIES = 3


class CursorClient:
    def __init__(self, idx, hwnd, to_screen, acquire, release,
                 inp=None, foreground_fn=None, activate_fn=None,
                 stop_check=None, sleep=None, settle_s=DEFAULT_SETTLE_S,
                 activate_retries=DEFAULT_ACTIVATE_RETRIES, mouse_pause=0.0,
                 needs_activation=False):
        """:param needs_activation: Multiclient -> True: vor jedem Burst
        click-to-activate + Fokus-Gate (das Fenster ist evtl. nicht vorn).
        Single-Client -> False (Default): KEINE Aktivierung/Fokus-Gate ->
        VERHALTENS-IDENTISCH zu den bisherigen direkten Klicks (das Spiel ist
        ohnehin fokussiert). So ist die Bot-Anbindung (Schritt 6) regressionsfrei
        fuer den Single-Client-Pfad und das Neue rein additiv fuer Multiclient.
        """
        """:param to_screen: ``callable(cx,cy)->(sx,sy)`` Client->Bildschirm
        (i.d.R. ``WindowCapture.get_screen_position``).
        :param acquire/release: Lease-Funktionen (IPC zum Broker bzw. Stub).
        :param inp: Input-Backend (Default: lazy ``pydirectinput``).
        :param foreground_fn: ``callable()->hwnd`` (Default: win32gui).
        :param activate_fn: ``callable(hwnd)`` click-to-activate (Default: intern).
        :param stop_check: ``callable()->bool`` True = Stop angefordert (F6).
        """
        self.idx = idx
        self.hwnd = hwnd
        self._to_screen = to_screen
        self._acquire = acquire
        self._release = release
        self._inp = inp or _lazy_pdi()
        self._foreground = foreground_fn or _lazy_foreground()
        self._activate = activate_fn or self._default_activate
        self._stop_check = stop_check or (lambda: False)
        self._sleep = sleep or _lazy_sleep()
        self.settle_s = settle_s
        self.activate_retries = activate_retries
        self.mouse_pause = mouse_pause
        self.needs_activation = needs_activation

    # -- High-Level-Aktionen -----------------------------------------------
    def click(self, cx, cy, button='left'):
        sx, sy = self._to_screen(cx, cy)
        self._run([lambda: self._inp.moveTo(sx, sy),
                   lambda: self._inp.click(button=button)])

    def right_click(self, cx, cy):
        sx, sy = self._to_screen(cx, cy)
        self._run([lambda: self._inp.moveTo(sx, sy),
                   lambda: self._inp.click(button='right')])

    def key(self, key, hold_s=0.0):
        def _press():
            self._inp.keyDown(key)
            if hold_s:
                self._sleep(hold_s)
            self._inp.keyUp(key)
        self._run([_press])

    def drag(self, points, button='left'):
        """Gehaltener Drag ueber ``points`` (Client-Koord) -> holds_button=True."""
        scr = [self._to_screen(cx, cy) for (cx, cy) in points]
        actions = [lambda p=scr[0]: self._inp.moveTo(*p),
                   lambda: self._inp.mouseDown(button=button)]
        for p in scr[1:]:
            actions.append(lambda p=p: self._inp.moveTo(*p))
        actions.append(lambda: self._inp.mouseUp(button=button))
        self._run(actions, holds_button=True)

    def chord(self, seq):
        """Tasten-Akkord (z.B. Ctrl+E) als EINEN Burst.

        ``seq`` ist eine geordnete Liste von ``('down', key)`` / ``('up', key)``
        -- exakt die keyDown/keyUp-Reihenfolge, die der Modus-Code erzeugt. Eine
        ueber mehrere Tasten GEHALTENE Sequenz darf nicht mitten drin entzogen
        werden -> ``holds_button=True`` (Broker behandelt sie non-revocable wie
        einen Drag). Der Stop-Poll je Schritt bleibt aktiv.
        """
        actions = []
        for kind, key in seq:
            if kind == 'down':
                actions.append(lambda k=key: self._inp.keyDown(k))
            else:
                actions.append(lambda k=key: self._inp.keyUp(k))
        self._run(actions, holds_button=True)

    # -- Kern: die gehaertete Burst-Sequenz --------------------------------
    def _run(self, actions, holds_button=False):
        self._acquire(self.idx, holds_button)
        try:
            # (Finding #1) globalen Button-State neutralisieren, BEVOR irgendetwas
            # passiert -- ein vorheriger (zwangsentzogener) Holder koennte eine
            # Taste gedrueckt gelassen haben.
            self._neutralize_buttons()
            # click-to-activate + Fokus-Gate NUR im Multiclient (needs_activation).
            # Single-Client: das Spiel ist fokussiert -> direkt klicken (legacy).
            if self.needs_activation:
                self._activate_with_gate()
            if self.mouse_pause:
                try:
                    self._inp.PAUSE = self.mouse_pause      # G2: nur in der Lease
                except Exception:
                    pass
            for act in actions:
                if self._stop_check():                      # Finding #4
                    raise BurstAborted()
                act()
        finally:
            # (Finding #1) Tasten IMMER loesen -- auch bei Focus-Fail/Stop/Crash.
            self._neutralize_buttons()
            self._release(self.idx)

    def _activate_with_gate(self):
        """click-to-activate + Settle + Fokus-Gate (G1) mit Retry."""
        last = None
        for _ in range(max(1, self.activate_retries)):
            self._activate(self.hwnd)
            self._sleep(self.settle_s)
            last = self._foreground()
            if last == self.hwnd:
                return
        raise FocusNotAcquired(f'fg={last!r} != hwnd={self.hwnd!r}')

    def _neutralize_buttons(self):
        try:
            self._inp.mouseUp(button='left')
            self._inp.mouseUp(button='right')
        except Exception:
            pass

    def _default_activate(self, hwnd):
        """Klick in die Titelleiste (harmlose Aktivierungszone, Q1).

        HINWEIS: Q1 (welche Zone aktiviert OHNE Spielaktion) ist als harte
        Vorbedingung am Live-Spiel zu bestaetigen; die Titelleiste ist der
        sichere Default (keine Spielflaeche -> keine Spielaktion).
        """
        try:
            import win32gui
            r = win32gui.GetWindowRect(hwnd)
            self._inp.moveTo((r[0] + r[2]) // 2, r[1] + 15)
            self._inp.click()
        except Exception:
            pass


class LeasedInput:
    """Multiclient-Input-Backend fuer die bestehenden Bots (Build-Schritt 6).

    Erfuellt das Bot-Backend-Protokoll (``set_pause``/``click``/``key``) wie
    ``fishingbot._DirectBackend``, fuehrt aber JEDE Aktion als EINEN Lease-Burst
    ueber einen :class:`CursorClient` aus (Cursor-Serialisierung + click-to-
    activate + Fokus-Gate). Der Worker injiziert es per ``set_input_backend``.

    Der Bot rechnet Koordinaten bereits via ``wincap.offset`` in Bildschirm-
    Koordinaten um -> der ``CursorClient`` wird mit ``to_screen=identity`` gebaut.
    """

    def __init__(self, cursor):
        self._c = cursor

    def set_pause(self, value):
        self._c.mouse_pause = value

    def click(self, x, y, button='left'):
        self._c.click(x, y, button=button)

    def key(self, key):
        self._c.key(key)


class LeasedScreenCursor:
    """Refill-/Drag-faehiges Screen-Koordinaten-Backend (Build-Schritt 6).

    Erfuellt den ``inp``/``api``-Vertrag von ``interface/refill.py``
    (``set_pause``/``click(x=,y=,button=)``/``moveTo``/``mouseDown``/``mouseUp``),
    fuehrt ihn aber ueber einen :class:`CursorClient` aus. Ein gehaltener Drag
    (``moveTo``* -> ``mouseDown`` -> ``moveTo``* -> ``mouseUp``) wird zu EINEM
    nicht-entziehbaren Lease-Burst (``CursorClient.drag``, ``holds_button=True``)
    gebuendelt -- so graetscht kein anderer Client mitten in den Drag (Finding #1).
    Die Koordinaten sind bereits Bildschirm-Koordinaten -> der ``CursorClient``
    laeuft mit identity-``to_screen``.
    """

    def __init__(self, cursor):
        self._c = cursor
        self._last = (0, 0)
        self._drag = None       # None = kein Drag aktiv; sonst Punkt-Liste

    def set_pause(self, value):
        self._c.mouse_pause = value

    def moveTo(self, x, y):
        self._last = (int(x), int(y))
        if self._drag is not None:
            self._drag.append(self._last)

    def mouseDown(self, button='left'):
        # Drag beginnt am zuletzt angefahrenen Punkt.
        self._drag = [self._last]

    def mouseUp(self, button='left'):
        pts, self._drag = self._drag, None
        if not pts:
            return                          # mouseUp ohne Drag -> defensiv ignorieren
        if pts[-1] != self._last:
            pts = pts + [self._last]
        if len(pts) == 1:                   # CursorClient.drag braucht >= 2 Punkte
            pts = pts + [pts[0]]
        self._c.drag(pts, button=button)

    def click(self, x=None, y=None, button='left'):
        cx, cy = (self._last if x is None or y is None
                  else (int(x), int(y)))
        self._c.click(cx, cy, button=button)


class LeasedPydirectinput(LeasedScreenCursor):
    """pydirectinput-API-kompatibles Lease-Backend fuer Puzzle/Seher/
    Energiesplitter (Build-Schritt 6b -- Multiclient fuer ALLE Modi).

    Diese Module sprechen ``pydirectinput`` direkt an (``_input.click`` /
    ``moveTo`` / ``mouseDown`` / ``mouseUp`` / ``keyDown`` / ``keyUp`` /
    ``press`` + Attribut ``PAUSE``). Dieser Shim spiegelt GENAU diese Oberflaeche,
    fuehrt aber jede logische Aktion als EINEN Lease-Burst ueber einen
    :class:`CursorClient` aus (Cursor-Serialisierung + click-to-activate +
    Fokus-Gate). So wird ein Modus multiclient-faehig, indem nur sein ``_input``
    getauscht wird -- die Aufruf-Stellen bleiben byte-identisch.

    Buendelung von Halte-Sequenzen zu je EINEM nicht-entziehbaren Burst:
      * Maus-Drag  ``moveTo*`` -> ``mouseDown`` -> ``moveTo*`` -> ``mouseUp``
        (von :class:`LeasedScreenCursor` geerbt).
      * Tasten-Akkord ``keyDown(ctrl)`` -> ``keyDown(e)`` -> ``keyUp(e)`` ->
        ``keyUp(ctrl)`` -> ein ``CursorClient.chord``-Burst.

    Eigenstaendiges ``moveTo`` (Cursor-Parken / Farbprobe) bewegt den physischen
    Cursor NICHT -- im Multiclient ist die Erkennung screenshot-basiert
    (PrintWindow/BitBlt je Client), nicht cursor-positions-abhaengig; ein solches
    ``moveTo`` merkt nur das Ziel fuer ein folgendes ``click``/Drag (geerbtes
    Verhalten von :class:`LeasedScreenCursor`).
    """

    def __init__(self, cursor):
        super().__init__(cursor)
        self._chord = None      # None = kein Akkord aktiv; sonst Event-Liste
        self._held = 0          # Anzahl aktuell gedrueckter Tasten

    # -- PAUSE als les-/schreibbares Attribut (Module setzen + restaurieren es) -
    @property
    def PAUSE(self):
        return self._c.mouse_pause

    @PAUSE.setter
    def PAUSE(self, value):
        self._c.mouse_pause = value or 0.0

    # -- Tasten: keyDown/keyUp zu einem Akkord-Burst buendeln ------------------
    def keyDown(self, key):
        if self._chord is None:
            self._chord = []
        self._chord.append(('down', key))
        self._held += 1

    def keyUp(self, key):
        if self._chord is None:
            # keyUp ohne vorheriges keyDown -> defensiv als Einzel-Tap.
            self._c.key(key)
            return
        self._chord.append(('up', key))
        self._held -= 1
        if self._held <= 0:
            seq, self._chord, self._held = self._chord, None, 0
            self._c.chord(seq)

    def press(self, key):
        """Einzel-Tastendruck (pydirectinput.press) -> ein key-Burst."""
        self._c.key(key)


def make_leased_pdi(idx, hwnd, acquire, release, stop_check=None,
                    inp=None, foreground_fn=None, activate_fn=None):
    """Baut ein :class:`LeasedPydirectinput` (pydirectinput-Shim) auf einem
    eigenen :class:`CursorClient`. Ein Modus tauscht damit nur sein ``_input``.
    """
    return LeasedPydirectinput(make_leased_cursor(
        idx, hwnd, acquire, release, stop_check=stop_check, inp=inp,
        foreground_fn=foreground_fn, activate_fn=activate_fn))


def make_leased_cursor(idx, hwnd, acquire, release, stop_check=None,
                       inp=None, foreground_fn=None, activate_fn=None):
    """Baut einen :class:`CursorClient` mit identity-to_screen + Aktivierung.

    Der Bot (und ``refill.py``) liefern bereits Bildschirm-Koordinaten, daher
    ``to_screen`` = Identitaet; Multiclient -> ``needs_activation=True``. Ein
    EINZIGER Cursor pro Worker -> dieselbe Lease serialisiert Bot-Klicks UND
    Refill-Drags.
    """
    return CursorClient(
        idx=idx, hwnd=hwnd, to_screen=lambda x, y: (x, y),
        acquire=acquire, release=release, inp=inp, foreground_fn=foreground_fn,
        activate_fn=activate_fn, stop_check=stop_check or (lambda: False),
        needs_activation=True)


def make_leased_backend(idx, hwnd, acquire, release, stop_check=None,
                        inp=None, foreground_fn=None, activate_fn=None):
    """Baut ein :class:`LeasedInput` mit identity-to_screen + Aktivierung an.

    Bequemer Konstruktor fuer den Worker: der Bot liefert Screen-Koordinaten,
    daher ``to_screen`` = Identitaet; Multiclient -> ``needs_activation=True``.
    """
    return LeasedInput(make_leased_cursor(
        idx, hwnd, acquire, release, stop_check=stop_check, inp=inp,
        foreground_fn=foreground_fn, activate_fn=activate_fn))


# -- lazy Defaults (echte Abhaengigkeiten erst zur Laufzeit) ----------------
def _lazy_pdi():
    import pydirectinput
    return pydirectinput


def _lazy_foreground():
    def _fg():
        try:
            import win32gui
            return win32gui.GetForegroundWindow()
        except Exception:
            return None
    return _fg


def _lazy_sleep():
    import time
    return time.sleep
