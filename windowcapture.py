import numpy as np
import win32gui, win32ui, win32con
from i18n import t

# Optionales Diagnose-Logging. Bewusst weich eingebunden: faellt der Import
# (z.B. unter WSL/Test ohne Abhaengigkeiten) aus, bleibt die Capture-Logik
# unveraendert lauffaehig. Logging darf den Bot nie zum Absturz bringen.
try:
    from debuglog import log, log_error as _log_error
except Exception:  # pragma: no cover - nur Fallback, falls Modul fehlt
    log = None
    def _log_error(msg, exc=None):
        """No-op-Fallback, falls debuglog fehlt. Wirft nie."""
        pass


# Rand-/Titelleisten-Masse des METIN2-Fensters (Fenstermodus). Einzige
# Quelle der Wahrheit fuer den Capture-Crop UND die Resize-Mathematik unten
# (set_client_size-Fallback). Client = aussen - (2*BORDER) breit,
# aussen - TITLEBAR - BORDER hoch -> Client 800x600 == aussen 816x638.
BORDER_PIXELS = 8
TITLEBAR_PIXELS = 30


# -- Modul-weiter Zustand: bevorzugtes Fenster-Handle (Item N) -------------
# RUNTIME-ONLY. Wird NICHT persistiert (nicht in config/to_values). Ist es
# None (Default), verhaelt sich WindowCapture byte-identisch zu frueher
# (FindWindow). Wird nur waehrend eines aktiven Laufs gesetzt, wenn der
# Nutzer im Mehrfenster-Picker eine Wahl getroffen hat.
_PREFERRED_HWND = None


def set_preferred_hwnd(hwnd):
    """Setzt das bevorzugte Ziel-HWND (oder loescht es bei None/ungueltig).

    Defensiv: nicht in int wandelbare Werte loeschen die Praeferenz, statt
    einen Fehler zu werfen.
    """
    global _PREFERRED_HWND
    try:
        _PREFERRED_HWND = int(hwnd) if hwnd else None
    except Exception:
        _PREFERRED_HWND = None


def get_preferred_hwnd():
    """Liefert das aktuell bevorzugte Ziel-HWND oder None."""
    return _PREFERRED_HWND


def clear_preferred_hwnd():
    """Loescht die bevorzugte Fenster-Wahl (zurueck zu FindWindow)."""
    global _PREFERRED_HWND
    _PREFERRED_HWND = None


# Modus-Werte fuer die Fenster-Auswahl (Item N). Reine Strings, damit sie auch
# headless (ohne win32/Tk) verfuegbar + testbar sind.
MODE_LAST_FOCUSED = 'last_focused'
MODE_SPECIFIC = 'specific'


def select_target_hwnd(windows, mode, chosen_hwnd, find_fn=None):
    """REINE, stdlib-only Auswahl-Logik fuer das Ziel-HWND (Item N -- testbar).

    Entscheidet, WELCHES Fenster-Handle ``set_preferred_hwnd`` bekommen soll,
    OHNE selbst win32 zu beruehren -- die Liste sichtbarer Fenster wird injiziert
    (``windows`` aus :func:`enumerate_game_windows`), sodass diese Funktion in
    reinen Unit-Tests vollstaendig abgedeckt werden kann.

      * ``mode == 'last_focused'`` (Default): liefert ``None`` -- das signalisiert
        dem Aufrufer den LEGACY-Pfad (``set_preferred_hwnd(None)`` ->
        ``WindowCapture`` faellt auf ``FindWindow`` zurueck, byte-identisch zu
        frueher / zum zuletzt fokussierten Fenster).
      * ``mode == 'specific'``: liefert ``chosen_hwnd`` NUR, wenn es noch in
        ``windows`` (sichtbar/gueltig) vorhanden ist; sonst ``None`` (sicherer
        Rueckfall auf den Legacy-Pfad, statt ein totes Handle zu pushen).

    :param windows: Liste der aktuell sichtbaren Spiel-Fenster (Dicts mit
        ``'hwnd'``), z.B. aus :func:`enumerate_game_windows`. ``None`` -> ``[]``.
    :param mode: ``'last_focused'`` oder ``'specific'`` (unbekannt -> wie Default).
    :param chosen_hwnd: das vom Nutzer gewaehlte Handle (oder ``None``).
    :param find_fn: optionaler Haken (derzeit ungenutzt; haelt die Signatur offen
        fuer kuenftige FindWindow-Injektion in Tests). Wirft nie.
    :return: das zu praeferierende HWND (int) oder ``None`` fuer den Legacy-Pfad.
    """
    if mode != MODE_SPECIFIC:
        # 'last_focused' (oder unbekannt) -> Legacy-Pfad.
        return None
    if not chosen_hwnd:
        return None
    try:
        valid = {w.get('hwnd') for w in (windows or [])}
    except Exception:
        valid = set()
    return chosen_hwnd if chosen_hwnd in valid else None


def client_size(hwnd):
    """Liefert die WAHRE Client-Groesse ``(w, h)`` des Fensters oder ``None``.

    Nutzt ``GetClientRect`` (genauer als aussen-minus-Rand) und ist die Basis
    fuer den Groessen-Check (M) UND die im Picker (N) angezeigte Groesse.
    Defensiv: faellt der Aufruf aus (ungueltiges/zerstoertes HWND, headless)
    -> ``None``, nie eine Ausnahme.
    """
    if not hwnd:
        return None
    try:
        rect = win32gui.GetClientRect(hwnd)
        w = rect[2] - rect[0]
        h = rect[3] - rect[1]
        return (w, h)
    except Exception:
        return None


def set_client_size(hwnd, client_w, client_h):
    """Resized das Fenster, sodass seine CLIENT-Flaeche ``client_w x client_h`` wird.

    Primaer per GEMESSENER Delta (robust gegen DPI/Theme): aussen = client +
    (tatsaechliche Nicht-Client-Dicke aus Window-/Client-Rect). Sind die
    gemessenen Deltas unplausibel (<= 0), Rueckfall auf die festen
    BORDER/TITLEBAR-Masse. Behaelt die linke obere Ecke und stiehlt weder
    Z-Reihenfolge noch Fokus.

    :return: ``True`` bei Erfolg, sonst ``False``. Wirft NIE.
    """
    if not hwnd:
        return False
    try:
        cs = client_size(hwnd)
        if cs is None:
            return False
        cur_cw, cur_ch = cs
        wr = win32gui.GetWindowRect(hwnd)
        outer_w_cur = wr[2] - wr[0]
        outer_h_cur = wr[3] - wr[1]
        dx = outer_w_cur - cur_cw
        dy = outer_h_cur - cur_ch
        # Plausibilitaet der gemessenen Nicht-Client-Dicke. <= 0 ist unmoeglich
        # fuer ein normales Rahmenfenster -> Rueckfall auf die festen Masse
        # (aussen = client + 2*BORDER breit, + TITLEBAR + BORDER hoch).
        if dx <= 0 or dy <= 0:
            dx = BORDER_PIXELS * 2
            dy = TITLEBAR_PIXELS + BORDER_PIXELS
        outer_w = int(client_w) + dx
        outer_h = int(client_h) + dy
        win32gui.SetWindowPos(
            hwnd, 0, 0, 0, outer_w, outer_h,
            win32con.SWP_NOMOVE | win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
        return True
    except Exception as exc:
        # Interne Diagnose (die nutzersichtbare Meldung liefert die UI). Niemals
        # werfen -- der Resize ist eine reine Komfort-Aktion.
        _log_error('set_client_size failed', exc=exc)
        return False


def focus_window(hwnd):
    """Holt das Spiel-Fenster in den VORDERGRUND + gibt ihm den Tastatur-Fokus.

    NOETIG, weil ``pydirectinput``-TASTEN (z.B. Vogelperspektive 'g') immer an
    das FOKUSSIERTE Fenster gehen -- ohne Fokus landen sie im Bot-Fenster und
    bewirken im Spiel nichts. (Maus-Klicks aktivieren das Fenster ohnehin, Tasten
    NICHT.) Minimiertes Fenster wird wiederhergestellt. Reiner user32-Aufruf
    (kein Prozess-Zugriff, anti-cheat-neutral). Streng defensiv: liefert ``True``
    bei Erfolg, ``False`` bei Fehler/headless -- wirft NIE.
    """
    if not hwnd:
        return False
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        return True
    except Exception as exc:  # pragma: no cover - SetForegroundWindow kann je
        # nach Fokus-Situation fehlschlagen; das ist kein fataler Fehler.
        _log_error('focus_window failed', exc=exc)
        return False


def enumerate_game_windows(name):
    """Listet alle SICHTBAREN Fenster mit Titel == ``name`` (Item N).

    Spiegelt das EnumWindows-Muster von ``list_window_names``, sammelt aber
    Daten statt zu drucken. Jeder Eintrag: ``{'hwnd', 'w', 'h', 'x', 'y'}``
    (Groesse = wahre Client-Groesse via ``client_size``). Defensiv: pro
    Fenster gekapselt; bei Enum-Fehler -> ``[]``.
    """
    out = []

    def _cb(hwnd, _ctx):
        try:
            if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd) == name:
                rect = win32gui.GetWindowRect(hwnd)
                cs = client_size(hwnd)
                out.append({'hwnd': hwnd,
                            'w': cs[0] if cs else 0,
                            'h': cs[1] if cs else 0,
                            'x': rect[0], 'y': rect[1]})
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:
        return []
    return out


class WindowCapture:

    # properties
    w = 0
    h = 0
    hwnd = None
    cropped_x = 0
    cropped_y = 0
    offset_x = 0
    offset_y = 0

    # constructor
    def __init__(self, window_name):
        # find the handle for the window we want to capture.
        # Bevorzugt ein vom Nutzer im Mehrfenster-Picker (Item N) gewaehltes,
        # noch gueltiges + sichtbares HWND; sonst (Default) wie bisher
        # FindWindow nach Titel. Ist keine Praeferenz gesetzt, ist dies
        # byte-identisch zum frueheren reinen FindWindow-Pfad.
        pref = get_preferred_hwnd()
        if pref and win32gui.IsWindow(pref) and win32gui.IsWindowVisible(pref):
            self.hwnd = pref
        else:
            self.hwnd = win32gui.FindWindow(None, window_name)
        if not self.hwnd:
            msg = t('capture.window_not_found', window_name=window_name)
            _log_error(t('capture.init_failed', msg=msg))
            raise Exception(msg)

        # get the window size
        window_rect = win32gui.GetWindowRect(self.hwnd)
        self.w = window_rect[2] - window_rect[0]
        self.h = window_rect[3] - window_rect[1]

        # Plausibilitaet der Fenstergroesse pruefen: ein 0/negativ grosses
        # Fenster (minimiert/zerstoert) wuerde spaeter beim Capture zu einer
        # leeren oder fehlerhaften Bitmap fuehren -> frueh und klar melden.
        if self.w <= 0 or self.h <= 0:
            msg = t('capture.invalid_window_size',
                    window_name=window_name, w=self.w, h=self.h)
            _log_error(t('capture.init_failed', msg=msg))
            raise Exception(msg)

        # account for the window border and titlebar and cut them off.
        # Masse aus den Modul-Konstanten (eine Quelle der Wahrheit, auch fuer
        # die Resize-Mathematik). Werte byte-identisch zu frueher (8/30).
        border_pixels = BORDER_PIXELS
        titlebar_pixels = TITLEBAR_PIXELS
        self.w = self.w - (border_pixels * 2)
        self.h = self.h - titlebar_pixels - border_pixels
        self.cropped_x = border_pixels
        self.cropped_y = titlebar_pixels

        # set the cropped coordinates offset so we can translate screenshot
        # images into actual screen positions
        self.offset_x = window_rect[0] + self.cropped_x
        self.offset_y = window_rect[1] + self.cropped_y

    def resync_offsets(self):
        """Liest ``GetWindowRect`` neu und setzt ``offset_x/offset_y`` neu.

        NOETIG fuer Multiclient (G4): nach einem Tiling-``MoveWindow``/
        ``SetWindowPos`` ist die im ``__init__`` EINMALIG eingefrorene
        Bildschirm-Position veraltet -> ``get_screen_position`` liefert sonst
        Koordinaten am alten Ort -> Klick daneben. Diese Methode gleicht die
        Offsets an die aktuelle Fensterposition an (``cropped_x/cropped_y``
        bleiben konstant). Streng defensiv: ``True`` bei Erfolg, ``False`` bei
        Fehler/zerstoertem HWND -- wirft NIE.
        """
        if not self.hwnd:
            return False
        try:
            window_rect = win32gui.GetWindowRect(self.hwnd)
            self.offset_x = window_rect[0] + self.cropped_x
            self.offset_y = window_rect[1] + self.cropped_y
            return True
        except Exception as exc:  # pragma: no cover - nur defensiver Fehlerpfad
            _log_error('resync_offsets failed', exc=exc)
            return False

    def get_screenshot(self):

        # get the window image data
        wDC = win32gui.GetWindowDC(self.hwnd)
        dcObj = win32ui.CreateDCFromHandle(wDC)
        cDC = dcObj.CreateCompatibleDC()
        dataBitMap = win32ui.CreateBitmap()
        dataBitMap.CreateCompatibleBitmap(dcObj, self.w, self.h)
        cDC.SelectObject(dataBitMap)
        cDC.BitBlt((0, 0), (self.w, self.h), dcObj, (self.cropped_x, self.cropped_y), win32con.SRCCOPY)

        # convert the raw data into a format opencv can read
        #dataBitMap.SaveBitmapFile(cDC, 'debug.bmp')
        signedIntsArray = dataBitMap.GetBitmapBits(True)

        # Roh-Puffer defensiv pruefen: leere/zu kleine Bilddaten (z.B. Fenster
        # in der Zwischenzeit minimiert/geschlossen) wuerden beim Umformen unten
        # zu einem kryptischen Shape-Fehler fuehren -> hier klar melden.
        expected_bytes = self.w * self.h * 4
        if not signedIntsArray or len(signedIntsArray) < expected_bytes:
            # Ressourcen trotzdem freigeben, damit kein GDI-Leak entsteht.
            dcObj.DeleteDC()
            cDC.DeleteDC()
            win32gui.ReleaseDC(self.hwnd, wDC)
            win32gui.DeleteObject(dataBitMap.GetHandle())
            msg = t('capture.screenshot_too_little_data',
                    actual=0 if not signedIntsArray else len(signedIntsArray),
                    expected=expected_bytes)
            _log_error(t('capture.get_screenshot_failed', msg=msg))
            raise Exception(msg)

        # np.frombuffer statt des in NumPy >= 2 entfernten np.fromstring
        # (fromstring im Binaermodus wirft dort ValueError). signedIntsArray ist
        # ein bereits losgeloester Python-``bytes``-Puffer (GetBitmapBits liefert
        # eine Kopie), daher bleibt die frombuffer-Ansicht auch nach dem GDI-Free
        # gueltig -- reshape ist eine reine Sicht (keine Kopie).
        bgra = np.frombuffer(signedIntsArray, dtype='uint8').reshape(
            self.h, self.w, 4)

        # Alpha verwerfen UND zugleich C-zusammenhaengend machen, in EINER Kopie:
        # cvtColor(BGRA2BGR) erzeugt ein frisches, contiguous BGR-Array. Das
        # ersetzt das fruehere img[...,:3] (strided View) + ascontiguousarray
        # (zweite Kopie) -- byte-identisches Ergebnis, aber nur EINE Vollkopie des
        # ~1.8 MB-Puffers pro Frame statt zwei (bei ~30 Hz spuerbar weniger
        # Allokations-/GC-Druck). Der Alpha-Drop bleibt noetig, sonst wirft
        # cv.matchTemplate (Assertion: depth/type/dims). cv2 wird lokal importiert
        # (nur dieser Live-Pfad braucht es; der Modul-Import bleibt schlank).
        import cv2 as cv

        # free resources
        dcObj.DeleteDC()
        cDC.DeleteDC()
        win32gui.ReleaseDC(self.hwnd, wDC)
        win32gui.DeleteObject(dataBitMap.GetHandle())

        return cv.cvtColor(bgra, cv.COLOR_BGRA2BGR)

    # find the name of the window you're interested in.
    # once you have it, update window_capture()
    # https://stackoverflow.com/questions/55547940/how-to-get-a-list-of-the-name-of-every-open-window
    def list_window_names(self):
        def winEnumHandler(hwnd, ctx):
            if win32gui.IsWindowVisible(hwnd):
                print(hex(hwnd), win32gui.GetWindowText(hwnd))
        win32gui.EnumWindows(winEnumHandler, None)

    # translate a pixel position on a screenshot image to a pixel position on the screen.
    # pos = (x, y)
    # WARNING: if you move the window being captured after execution is started, this will
    # return incorrect coordinates, because the window position is only calculated in
    # the __init__ constructor.
    def get_screen_position(self, pos):
        return (pos[0] + self.offset_x, pos[1] + self.offset_y)