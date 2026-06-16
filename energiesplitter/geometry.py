# -*- coding: utf-8 -*-
"""Geometrie-Normierung 802x632 -> 800x600 fuer den Energiesplitter.

Die echten Screenshots (``metin2client_*.png`` etc.) sind 802x632: das ist das
GANZE Fenster inklusive 1px-Aussenrahmen + 30px-Titelleiste. Der eigentliche
Spiel-CLIENT ist 800x600 und beginnt bei ``(CLIENT_X0, CLIENT_Y0) = (1, 31)``
(verifiziert: Zeile 0/801 = 1px-Rahmen, Zeilen 1..30 = Titelleiste, Spalte 0 =
linker Rahmen). ``windowcapture.WindowCapture`` croppt diesen Rahmen im Live-
Betrieb bereits weg (``BORDER_PIXELS=8``/``TITLEBAR_PIXELS=30`` -> Client
800x600); die FIXTURES dagegen sind das ungecroppte Vollfenster.

Deshalb zwei Aufgaben:

  * :func:`to_client` normiert ein ungecropptes 802x632-Fixture (oder ein bereits
    passendes 800x600-Bild) defensiv auf den 800x600-Client -> alle Pixel-ROIs
    unten gelten EINHEITLICH im Client-Koordinatensystem.
  * :func:`is_calibrated` prueft, ob ein ``WindowCapture`` auf ~800x600 steht
    (Phase-0-Gate, Toleranz ``GAME_SIZE_TOLERANCE`` wie ``_common._probe_game``).

Alle Pixel-Konstanten sind RELATIV zum 800x600-Client definiert und ausdruecklich
als ``# KALIBRIER-BAR`` markiert: sie wurden an den vorhandenen Fixtures gemessen
und MUESSEN am echten Live-Client (P0.6) re-verifiziert werden, bevor scharf
geklickt wird. Reine Funktionen auf numpy-Arrays; kein win32/IO ausser dem
``WindowCapture``-Lesen in :func:`is_calibrated`. Wirft nie.
"""

try:  # pragma: no cover - numpy ist im Test echt, defensiv fuer Import-Robustheit
    import numpy as np
except Exception:  # pragma: no cover
    np = None


# -- Client-Normierung (802x632-Vollfenster -> 800x600-Client) --------------
GAME_W = 800
GAME_H = 600
# Versatz des Client-Ursprungs im Vollfenster-Screenshot (gemessen, KALIBRIER-BAR).
CLIENT_X0 = 1
CLIENT_Y0 = 31
# Roh-Groesse der gelieferten Fixtures (Vollfenster inkl. OS-Rahmen).
RAW_W = 802
RAW_H = 632
# Toleranz fuer die Live-Kalibrierung (wie interface/app/_common._probe_game).
GAME_SIZE_TOLERANCE = 8


# -- ROIs im 800x600-CLIENT (x, y, w, h) -- alle # KALIBRIER-BAR -------------
# Spielszene (ohne HUD oben/unten/rechts) -- Suchbereich fuer den gruenen
# NPC-Namen. An ALLEN 17 NPC-Bildern gemessen (Name x 126..565 / y 106..429 je
# nach Kamerawinkel) -> grosszuegiges Fenster mit Rand; bleibt links vom rechten
# HUD-Panel (~625) und ueber der unteren Skill-Leiste (~520). == ROI_NPC_SEARCH.
ROI_SCENE = (80, 90, 540, 380)        # KALIBRIER-BAR
# Header-Streifen eines geoeffneten Panels (Laden/Inventar/Ausruestung).
ROI_PANEL_HEADER = (350, 18, 200, 24)   # KALIBRIER-BAR
# Block der Dialog-Zeilen (zentriert); Y dynamisch (6 vs 7 Zeilen) -> grosszuegig.
ROI_DIALOG = (250, 140, 320, 200)       # KALIBRIER-BAR


def to_client(bgr):
    """Normiert ``bgr`` defensiv auf den 800x600-Client.

    * Vollfenster-Fixture (>= 802x632) -> Crop ``[CLIENT_Y0:+600, CLIENT_X0:+800]``.
    * Bereits 800x600 (Live-``WindowCapture``-Frame) -> unveraendert.
    * Andere/None/zu kleine Eingabe -> unveraendert zurueck (Detektor faellt
      dann sauber auf 'kein Treffer' zurueck, statt zu werfen).

    Gibt eine Sicht/Array gleicher Channel-Zahl zurueck; wirft nie.
    """
    if np is None or bgr is None:
        return bgr
    try:
        h, w = bgr.shape[:2]
    except Exception:
        return bgr
    if w == GAME_W and h == GAME_H:
        return bgr
    if w >= CLIENT_X0 + GAME_W and h >= CLIENT_Y0 + GAME_H:
        return bgr[CLIENT_Y0:CLIENT_Y0 + GAME_H, CLIENT_X0:CLIENT_X0 + GAME_W]
    return bgr


def crop(bgr, roi):
    """Schneidet ``roi=(x,y,w,h)`` aus einem CLIENT-Bild (vorher to_client).

    Defensiv geklemmt auf die Bildgrenzen; leerer/ungueltiger Ausschnitt ->
    ``None``. Wirft nie.
    """
    if np is None or bgr is None or roi is None:
        return None
    try:
        x, y, w, h = (int(v) for v in roi)
        H, W = bgr.shape[:2]
        x0 = max(0, min(x, W)); y0 = max(0, min(y, H))
        x1 = max(x0, min(x + w, W)); y1 = max(y0, min(y + h, H))
        if x1 <= x0 or y1 <= y0:
            return None
        return bgr[y0:y1, x0:x1]
    except Exception:
        return None


def slot_center(slot):
    """Mittelpunkt ``(x, y)`` eines Inventar-Slots im 800x600-Client.

    Ist ``slot`` bereits ein ``(x, y)``-Punkt (so liefern die Detektoren ihre
    Slot-Treffer in Phase-0), wird er unveraendert als Client-Punkt
    zurueckgegeben -- saubere, echte Geometrie.

    Ein abstrakter Raster-Index ``(col, row)`` kann ohne kalibriertes
    Inventar-Lattice NICHT in Pixel aufgeloest werden (Live-Asset, P0.4 -- das
    Tagedieb-/Taschen-Raster ist nicht Teil dieses Phase-0-Frameworks). In dem
    Fall liefert die Funktion defensiv ``(0, 0)`` (NotReady) -- der GATE haelt
    jeden scharfen Lauf ohnehin zurueck, solange die Assets fehlen. Wirft nie.
    # TODO-live-asset: Inventar-Lattice (col,row -> Pixel) kalibrieren (P0.4).
    """
    try:
        if isinstance(slot, (tuple, list)) and len(slot) == 2:
            return int(slot[0]), int(slot[1])
    except Exception:
        pass
    return 0, 0


def is_calibrated(wincap):
    """``True`` nur, wenn der Client ~800x600 ist (Phase-0-Gate, Teil 2).

    Liest die WAHRE Client-Groesse defensiv: bevorzugt ``wincap.hwnd`` ->
    ``windowcapture.client_size`` (wie ``_probe_game``); faellt das aus, die
    ``wincap.w/h``-Attribute (die ``WindowCapture`` bereits Rahmen-bereinigt
    fuehrt). Kein Fenster/keine messbare Groesse -> ``False``. Wirft nie.
    """
    w = h = None
    try:
        import windowcapture as _wc
        hwnd = getattr(wincap, 'hwnd', None)
        cs = _wc.client_size(hwnd) if hwnd else None
        if cs:
            w, h = cs
    except Exception:
        w = h = None
    if w is None or h is None:
        try:
            w = int(getattr(wincap, 'w'))
            h = int(getattr(wincap, 'h'))
        except Exception:
            return False
    try:
        return (abs(int(w) - GAME_W) <= GAME_SIZE_TOLERANCE
                and abs(int(h) - GAME_H) <= GAME_SIZE_TOLERANCE)
    except Exception:
        return False


__all__ = [
    'GAME_W', 'GAME_H', 'CLIENT_X0', 'CLIENT_Y0', 'RAW_W', 'RAW_H',
    'GAME_SIZE_TOLERANCE', 'ROI_SCENE', 'ROI_PANEL_HEADER',
    'ROI_DIALOG', 'to_client', 'crop', 'is_calibrated',
    'slot_center',
]
