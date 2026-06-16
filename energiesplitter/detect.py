# -*- coding: utf-8 -*-
"""Reine Vision/Erkennung fuer den Energiesplitter (NCC-Template-Framework).

Im Projekt existiert KEIN freies OCR (verifiziert: 0 Treffer tesseract/easyocr;
``fishing_chat`` ist ein fester Pixel-Glyphen-Atlas). Text-/NPC-/Dialog-/Item-
Erkennung laeuft daher ueber **NCC-Bild-Templates** -- ein bekanntes, gerendertes
Wort/Icon wird als Bild per ``cv2.matchTemplate(TM_CCOEFF_NORMED)`` gesucht. Kein
neues Dependency; cv2/numpy wie im restlichen Projekt.

Dieses Modul ist **rein** (numpy/cv2 + Template-Laden von Platte; kein win32/Maus/
i18n-Pflicht). Jede Funktion ist defensiv und wirft NIE -- ein abweichendes
Capture (Form/Typ) wird als 'nicht erkannt' behandelt, nicht als Absturz.

PHASE-1-STATUS (2026-06-15): Die in :mod:`energiesplitter.calibration` gemessenen
Live-Assets liegen vor -- Item-Templates ``templates/hammer.png`` /
``templates/dolch.png``, NPC-Wortbilder ``templates/npc/{alchemist,
waffenhaendler}.png`` und das Inventar-Raster (Pitch 32, Ursprung Slot-1 (648,
258)). Damit ist die ECHTE Erkennung scharf: Slot-Klassifikation (Hammer/Dolch
via NCC ueber das kalibrierte Lattice, Glow-aware), freie Plaetze, Inventar-
Signatur/Diff, Shop-Item-Lokalisierung, NPC-Name + Selektions-Ring.

SICHERHEITS-INVARIANTE (oberste Prioritaet): **Erkennung vor Aktion.** Jede
'finde X'-Funktion liefert bei Nichttreffer ``None``/``False`` (NIE raten).
``assets_ready`` meldet fehlende Item-/NPC-Templates ehrlich als ``missing`` ->
das Phase-0-Gate bleibt korrekt rot (Stopp statt Blind-Kauf). YANG spielt seit
dem Umbau 2026-06-16 KEINE Rolle mehr (kein Gold-Reader, keine ``yang_digits``).
"""

import os

from . import geometry as _geo
from . import calibration as _cal

try:  # pragma: no cover
    import numpy as np
except Exception:  # pragma: no cover
    np = None

try:  # pragma: no cover
    import cv2 as _cv
except Exception:  # pragma: no cover
    _cv = None

try:  # pragma: no cover
    from respath import resource_path
except Exception:  # pragma: no cover
    def resource_path(rel):
        return rel


# -- Asset-Verzeichnisse (cwd-unabhaengig) ----------------------------------
TEMPLATE_DIR = os.path.join('energiesplitter', 'templates')

# Item-Templates (Dateiname ohne .png in templates/).
HAMMER_ITEMS = ('hammer',)
DAGGER_EXTRA_ITEMS = ('dolch',)
# NPC-Wortbilder (templates/npc/<name>.png).
HAMMER_NPCS = ('alchemist',)
DAGGER_EXTRA_NPCS = ('waffenhaendler',)

# -- NCC-Schwellen (KALIBRIER-BAR; an Fixtures gemessen) --------------------
# Item-Icon: Hammer-Gewinner 0.82..1.00, Dolch-Gewinner 1.00; jeweiliger
# Verlierer <= 0.46 (Schwert/leer). 0.70 trennt konfusionsfrei (CALIBRATION.md).
NCC_ITEM = 0.70
# NPC-/Header-Wortbild: self 1.00, cross <= 0.34 -> 0.80 diskriminiert klar.
NCC_WORD = 0.80
NCC_HEADER = 0.70

# Gruen-Maske fuer NPC-Namen (BGR-Schwellen wie DESIGN/calibration).
GREEN_G_MIN = 120
GREEN_GR_DELTA = 25
GREEN_GB_DELTA = 25
# Ring-Glow-Maske: der Metin2-Selektions-Ring leuchtet saturiert orange-rot
# (gemessen: R~255, G~40-110, B~1-56) -- deutlich saettiger als HUD-Rot.
RED_R_MIN = 180
RED_RG_DELTA = 90
RED_RB_DELTA = 120
RING_MIN_PX = 40
RING_NEAR_PX = 60
RING_MAX_FILL = 0.35

# Slot-Klassifikation: volle 32px-Zelle gibt matchTemplate Spielraum; an dieser
# Groesse reproduzieren die gemessenen NCC-Werte (CALIBRATION.md, Abschnitt 1).
SLOT_CELL = 32
# Maximale Slot-Nummer auf Seite I (5 Spalten x 8 Zeilen = 40).
MAX_SLOT = 40


# ----------------------------------------------------------------------------
# Template-Laden
# ----------------------------------------------------------------------------
def _dir(rel):
    """Loest ein gebundeltes Verzeichnis cwd-unabhaengig auf (wie respath)."""
    base = resource_path(rel)
    if os.path.isdir(base):
        return base
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)
    cand = os.path.join(repo, rel)
    return cand if os.path.isdir(cand) else base


def _item_path(name):
    return os.path.join(_dir(TEMPLATE_DIR), name + '.png')


def _npc_path(name):
    return os.path.join(_dir(TEMPLATE_DIR), 'npc', name + '.png')


def _exists(path):
    try:
        return os.path.isfile(path)
    except Exception:
        return False


_TEMPLATE_CACHE = {}


def _imread(path):
    """Laedt + cached ein Template als BGR (oder ``None``). Wirft nie."""
    if _cv is None:
        return None
    if path in _TEMPLATE_CACHE:
        return _TEMPLATE_CACHE[path]
    img = None
    try:
        if _exists(path):
            img = _cv.imread(path, _cv.IMREAD_COLOR)
    except Exception:
        img = None
    _TEMPLATE_CACHE[path] = img
    return img


# ----------------------------------------------------------------------------
# NCC-Kernel (robust, wie fishing_match._match_template_max)
# ----------------------------------------------------------------------------
def _to_bgr(img):
    """Bringt ``img`` defensiv auf 3-Kanal-BGR (contiguous). ``None`` bei Fehler."""
    if img is None or np is None or _cv is None:
        return None
    try:
        a = np.ascontiguousarray(img)
        if a.ndim == 2:
            return _cv.cvtColor(a, _cv.COLOR_GRAY2BGR)
        if a.ndim == 3 and a.shape[2] == 4:
            return _cv.cvtColor(a, _cv.COLOR_BGRA2BGR)
        if a.ndim == 3 and a.shape[2] == 3:
            return a
        return None
    except Exception:
        return None


def match_word(haystack, template):
    """NCC eines Bild-Templates in ``haystack`` -> ``(ok, pt, ncc)``.

    ``pt`` = oben-links des besten Treffers (im ``haystack``-Koordinatensystem).
    Defensiv: passt das Template nicht (groesser als Bild, falsche Kanalzahl) ->
    ``(False, None, 0.0)``. Wirft NIE.
    """
    if np is None or _cv is None:
        return (False, None, 0.0)
    img = _to_bgr(haystack)
    tpl = _to_bgr(template)
    if img is None or tpl is None:
        return (False, None, 0.0)
    if (tpl.shape[0] > img.shape[0] or tpl.shape[1] > img.shape[1]
            or img.shape[2] != tpl.shape[2]):
        return (False, None, 0.0)
    try:
        res = _cv.matchTemplate(img, tpl, _cv.TM_CCOEFF_NORMED)
        _minv, maxv, _minl, maxl = _cv.minMaxLoc(res)
        return (True, (int(maxl[0]), int(maxl[1])), float(maxv))
    except Exception:
        return (False, None, 0.0)


def _ncc_max(haystack, template):
    """Nur der beste NCC-Score (oder ``-1.0``). Defensiv, wirft nie."""
    ok, _pt, ncc = match_word(haystack, template)
    return ncc if ok else -1.0


# ----------------------------------------------------------------------------
# Phase-0-Asset-Gate (rein)
# ----------------------------------------------------------------------------
def item_template_available(item):
    """``True``, wenn das Item-Template ``templates/<item>.png`` gebundelt ist.

    Reine Dateisystem-Pruefung -- KEINE Messung. Wirft nie.
    """
    if not item:
        return False
    return _exists(_item_path(item))


def _npc_template_available(npc):
    if not npc:
        return False
    return _exists(_npc_path(npc))


def assets_ready(mode):
    """Prueft, ob ALLE fuer ``mode`` noetigen Assets gebundelt sind.

    ``mode`` in ``('hammer', 'dagger')``. Liefert ``(ready, missing)``: ``ready``
    nur True, wenn KEIN Artefakt fehlt. Jedes fehlende landet als Klartext-String
    in ``missing`` (z.B. ``'item:hammer'``, ``'npc:waffenhaendler'``). Reine
    Dateisystem-Pruefung; wirft NIE.

    Die Item-/NPC-Templates + der Shop-Anker liegen vor (Phase 1, CALIBRATION.md).
    Yang spielt seit dem Umbau 2026-06-16 KEINE Rolle mehr -- es gibt keinen
    Gold-Reader und keine Yang-Ziffern, also auch keine ``yang_digits``-Luecke.
    """
    missing = []
    m = (mode or '').lower()
    items = list(HAMMER_ITEMS)
    npcs = list(HAMMER_NPCS)
    if m == 'dagger':
        items += list(DAGGER_EXTRA_ITEMS)
        npcs += list(DAGGER_EXTRA_NPCS)
    elif m != 'hammer':
        return (False, ['mode:%s' % mode])
    for item in items:
        if not item_template_available(item):
            missing.append('item:%s' % item)
    for npc in npcs:
        if not _npc_template_available(npc):
            missing.append('npc:%s' % npc)
    return (len(missing) == 0, missing)


def grid_present():
    """``True``, wenn die Inventar-Grid-Geometrie aufloesbar ist (Slot 1 -> Pixel).

    Reiner Kalibrier-Check (``calibration.slot_center``) -- die NICHT-Yang-Saeule
    des Phase-0-GATE (sichere Drag-/Slot-Ziele). Loest die Kalibrierung nicht in
    einen plausiblen Punkt auf -> ``False``. Read-only, wirft nie.
    """
    if _cal is None:
        return False
    try:
        c = _cal.slot_center(1)
    except Exception:  # pragma: no cover - defensiv
        return False
    return (isinstance(c, (tuple, list)) and len(c) == 2
            and all(isinstance(v, int) for v in c)
            and c[0] > 0 and c[1] > 0)


# ----------------------------------------------------------------------------
# Inventar-Geometrie (kalibriert) -- Slot <-> Zelle
# ----------------------------------------------------------------------------
def _slot_index(slot):
    """Normiert ``slot`` (int-Index 1..40 ODER (x,y)-Punkt) -> int-Index|None.

    Ein Punkt wird auf den naechsten Raster-Slot zurueckgerechnet; abseits des
    Rasters / ungueltig -> ``None`` (defensiv, kein Raten).
    """
    if isinstance(slot, (tuple, list)) and len(slot) == 2:
        try:
            x, y = int(slot[0]), int(slot[1])
        except Exception:
            return None
        col = round((x - _cal.GRID_SLOT_CENTER_X0) / float(_cal.GRID_PITCH_X))
        row = round((y - _cal.GRID_SLOT_CENTER_Y0) / float(_cal.GRID_PITCH_Y))
        if col < 0 or col >= _cal.GRID_COLS or row < 0:
            return None
        idx = int(row * _cal.GRID_COLS + col + 1)
        return idx if 1 <= idx <= MAX_SLOT else None
    try:
        idx = int(slot)
    except Exception:
        return None
    return idx if 1 <= idx <= MAX_SLOT else None


def _slot_cell_bgr(client, slot, size=SLOT_CELL):
    """Schneidet die ``size``x``size``-Zelle eines Slots aus dem CLIENT-Bild."""
    roi = _cal.slot_cell(slot, size)
    if roi is None:
        return None
    return _geo.crop(client, roi)


def _slot_glowing(cell):
    """``True``, wenn die Zelle 'frisch gekauft' leuchtet (Glow-Randring-Anteil).

    Metrik = Anteil Pixel mit ``min(B,G,R) > GLOW_MINCH_THR`` im ``GLOW_RING_PX``-
    Randring. Nicht-leuchtend <= 0.115, leuchtend >= 0.65 (konfusionsfrei,
    CALIBRATION.md). Defensiv ``False`` bei zu kleiner Zelle. Wirft nie.
    """
    if cell is None:
        return False
    try:
        h, w = cell.shape[:2]
        p = _cal.GLOW_RING_PX
        if h <= 2 * p or w <= 2 * p:
            return False
        mn = cell.min(axis=2)
        mask = np.ones((h, w), dtype=bool)
        mask[p:h - p, p:w - p] = False
        ring = mn[mask]
        if ring.size == 0:
            return False
        frac = float((ring > _cal.GLOW_MINCH_THR).mean())
        return frac >= _cal.GLOW_FRACTION_THR
    except Exception:
        return False


def _classify_slot(client, slot):
    """Bestes Item-Label einer Slot-Zelle -> ``(item, ncc)`` oder ``(None, ncc)``.

    Vergleicht die volle 32px-Zelle gegen Hammer- UND Dolch-Template; das Item
    mit hoechstem NCC gewinnt, sofern ``>= NCC_ITEM`` (sonst leer/Fremd-Item ->
    ``(None, best_ncc)``). Glow-tolerant (Template-NCC matcht leuchtende Slots
    ~0.74..0.82). Defensiv, wirft nie.
    """
    cell = _slot_cell_bgr(client, slot)
    if cell is None:
        return (None, -1.0)
    ham = _imread(_item_path('hammer'))
    dol = _imread(_item_path('dolch'))
    n_ham = _ncc_max(cell, ham) if ham is not None else -1.0
    n_dol = _ncc_max(cell, dol) if dol is not None else -1.0
    best_item, best = (None, -1.0)
    if n_ham >= best:
        best_item, best = 'hammer', n_ham
    if n_dol > best:
        best_item, best = 'dolch', n_dol
    if best < NCC_ITEM:
        return (None, best)
    return (best_item, best)


# ----------------------------------------------------------------------------
# NPC-Name (Wortbild-NCC ueber die Szene)
# ----------------------------------------------------------------------------
def _green_mask(bgr):
    """Binaere Gruen-Maske (uint8 0/255) fuer NPC-Namen (DESIGN-Schwellen)."""
    b = bgr[:, :, 0].astype(np.int16)
    g = bgr[:, :, 1].astype(np.int16)
    r = bgr[:, :, 2].astype(np.int16)
    m = ((g > GREEN_G_MIN) & (g - r > GREEN_GR_DELTA) & (g - b > GREEN_GB_DELTA))
    return (m.astype(np.uint8)) * 255


def find_npc_name(bgr, word_template, roi=None, thresh=NCC_WORD):
    """Sucht den gruenen NPC-Schriftzug ``word_template`` in der Szene.

    ``bgr`` wird ``geometry.to_client``-normiert; im Szenen-ROI wird
    ``word_template`` per NCC gesucht. Liefert ``(ok, pt, ncc)`` mit ``pt`` im
    CLIENT-Koordinatensystem (NPC-Punkt = Treffer-Mitte). ``word_template`` None /
    kein Treffer >= thresh -> ``(False, None, ncc)``. KEIN Blind-Fallback. Wirft NIE.

    Die gelieferten NPC-Wortbilder (``templates/npc/*.png``) sind direkte Roh-
    Crops des gruenen Labels; das volle Farb-Template diskriminiert bereits
    konfusionsfrei (self 1.00, cross 0.30). Liegt ein bereits gruen-maskiertes
    Template vor (Test-Pfad), funktioniert die NCC trotzdem.
    """
    if np is None or _cv is None or bgr is None or word_template is None:
        return (False, None, 0.0)
    client = _geo.to_client(bgr)
    roi = roi if roi is not None else _cal.ROI_NPC_SEARCH
    region = _geo.crop(client, roi)
    if region is None:
        return (False, None, 0.0)
    tpl = _to_bgr(word_template)
    if tpl is None:
        return (False, None, 0.0)
    # Primaer: Farb-NCC (Live-Asset). Faellt der Treffer durch (z.B. ein bereits
    # gruen-maskiertes Test-Template), zusaetzlich auf der Gruen-Maske matchen.
    ok, pt, ncc = match_word(region, tpl)
    if not ok or pt is None or ncc < thresh:
        try:
            region_m = _cv.cvtColor(_green_mask(region), _cv.COLOR_GRAY2BGR)
            tpl_m = _cv.cvtColor(_green_mask(tpl), _cv.COLOR_GRAY2BGR)
            ok2, pt2, ncc2 = match_word(region_m, tpl_m)
            if ok2 and pt2 is not None and ncc2 >= thresh and ncc2 > ncc:
                ok, pt, ncc = ok2, pt2, ncc2
        except Exception:
            pass
    if not ok or pt is None or ncc < thresh:
        return (False, None, ncc)
    rx, ry, _, _ = roi
    th, tw = tpl.shape[:2]
    center = (rx + pt[0] + tw // 2, ry + pt[1] + th // 2)
    return (True, center, ncc)


# ----------------------------------------------------------------------------
# Selektions-Ring (Rot-Maske + Ring-Form)
# ----------------------------------------------------------------------------
def _red_mask(bgr):
    b = bgr[:, :, 0].astype(np.int16)
    g = bgr[:, :, 1].astype(np.int16)
    r = bgr[:, :, 2].astype(np.int16)
    m = ((r > RED_R_MIN) & (r - g > RED_RG_DELTA) & (r - b > RED_RB_DELTA))
    return m


def selection_ring_present(bgr, near, y_min=240):
    """``True``, wenn um ``near=(x,y)`` ein roter Selektions-Ring liegt.

    Sucht im Fenster ``RING_NEAR_PX`` um ``near`` (nur Zeilen ``>= y_min``) rote
    Pixel und verlangt eine RING-Form: genug rote Pixel, die einen Rand bilden
    (grosse Spannweite in beiden Achsen, niedriger Fuell-Grad). Defensiv
    ``False`` bei fehlendem/ungueltigem ``near``. Wirft NIE.
    """
    if np is None or bgr is None or near is None:
        return False
    try:
        client = _geo.to_client(bgr)
        H, W = client.shape[:2]
        cx, cy = int(near[0]), int(near[1])
        x0 = max(0, cx - RING_NEAR_PX); x1 = min(W, cx + RING_NEAR_PX)
        y0 = max(int(y_min), cy - RING_NEAR_PX); y1 = min(H, cy + RING_NEAR_PX)
        if x1 - x0 < 8 or y1 - y0 < 8:
            return False
        win = client[y0:y1, x0:x1]
        rm = _red_mask(win)
        total = int(rm.sum())
        if total < RING_MIN_PX:
            return False
        hh, ww = rm.shape
        ys, xs = np.where(rm)
        if len(xs) == 0:
            return False
        span_x = int(xs.max() - xs.min() + 1)
        span_y = int(ys.max() - ys.min() + 1)
        bbox_area = max(1, span_x * span_y)
        fill = total / bbox_area
        if span_x < ww // 2 or span_y < hh // 2:
            return False
        return fill <= RING_MAX_FILL
    except Exception:
        return False


# ----------------------------------------------------------------------------
# Dialog-Zustand / Shop / Panel
# ----------------------------------------------------------------------------
# Der Dialog hat KEINE Wortbild-Templates in der neuen Asset-Lieferung (nur
# Item-/NPC-Templates + Yang-Ziffern). Bis ein Marker-Crop vorliegt, kann der
# 'Test-injizierte Template'-Seam ueber _load_template weiter genutzt werden.
def _load_template(lang, word):
    """Marker-Wortbild-Template (Test-Injektions-Seam) -> BGR | None.

    Phase 1 buendelt KEINE Dialog-/Header-Wortbilder (nur Item/NPC/Yang). Diese
    Funktion existiert als kompatibler Lade-Seam (Tests injizieren echte Crops,
    um die Diskriminierung zu beweisen). Ohne gebundeltes Template -> ``None``
    (NotReady). Wirft nie.
    """
    if _cv is None:
        return None
    path = os.path.join(_dir(TEMPLATE_DIR), lang, word + '.png')
    if not _exists(path):
        return None
    try:
        return _cv.imread(path, _cv.IMREAD_COLOR)
    except Exception:
        return None


def _word_in_region(bgr, roi, word, thresh):
    """``(ok, ncc)``: sucht ``word`` (de ODER en) im ROI per NCC. NotReady -> None."""
    region = _geo.crop(_geo.to_client(bgr), roi)
    if region is None:
        return None
    best = None
    for lang in ('de', 'en'):
        tpl = _load_template(lang, word)
        if tpl is None:
            continue
        ok, _pt, ncc = match_word(region, tpl)
        if ok and (best is None or ncc > best):
            best = ncc
    if best is None:
        return None
    return (best >= thresh, best)


def dialog_state(bgr):
    """``'locked'`` | ``'unlocked'`` | ``None`` per NCC-Marker-Templates.

    LOCKED = Zeile ``eine_neue_technik`` (Erstgespraech, Energie-Freischalt-
    Option), UNLOCKED = Zeile ``energiesplitter_extrahieren``. Fehlen BEIDE
    Marker-Templates ODER ist kein Dialog erkennbar -> ``None`` (NotReady/kein
    Dialog). Wirft NIE.
    """
    if bgr is None:
        return None
    unlocked = _word_in_region(bgr, _geo.ROI_DIALOG, 'energiesplitter_extrahieren',
                               NCC_WORD)
    locked = _word_in_region(bgr, _geo.ROI_DIALOG, 'eine_neue_technik', NCC_WORD)
    if unlocked is None and locked is None:
        return None
    if unlocked is not None and unlocked[0]:
        return 'unlocked'
    if locked is not None and locked[0]:
        return 'locked'
    return None


def shop_open(bgr):
    """``True``, wenn ein Shop offen ist (``laden_header``-NCC). NotReady -> False.

    Fehlt das Header-Template, liefert die Funktion ``False`` (sicher: 'nicht
    offen' -> kein Kauf), NICHT True. Wirft NIE.
    """
    if bgr is None:
        return False
    res = _word_in_region(bgr, _geo.ROI_PANEL_HEADER, 'laden_header', NCC_HEADER)
    return bool(res is not None and res[0])


def panel_is_bag(bgr):
    """``True``, wenn das rechte Panel die Tasche (``inventar_header``) ist.

    Unterscheidet Inventar von Ausruestungsfenster per Header-NCC. NotReady ->
    ``False`` (sicher: nicht als Tasche behandeln). Wirft NIE.
    """
    if bgr is None:
        return False
    inv = _word_in_region(bgr, _geo.ROI_PANEL_HEADER, 'inventar_header', NCC_HEADER)
    return bool(inv is not None and inv[0])


# ----------------------------------------------------------------------------
# Shop-Item / Stack
# ----------------------------------------------------------------------------
# Default-Such-ROI fuer das Shop-Item: ENG um den kalibrierten Hammer-Shop-Anker
# (CALIBRATION.md: 200er-Stack-Zell-Mitte (425,121)). Das Shop-Panel zeigt mehrere
# hammeraehnliche Icons; nur der gemessene 200er-Slot ist der buyable Anker. Eine
# weite ROI wuerde ein anderes Hammer-Icon (oder den Inventar-Bestand) treffen ->
# der bridges-Anker-Cross-Check wuerde dann ablehnen (kein Kauf). Anker-zentriert
# liefert ``find_shop_item`` direkt den buyable Slot (~(426,122), NCC 0.91).
def _shop_default_roi():
    a = getattr(_cal, 'SHOP_HAMMER_ANCHOR', None)
    if a is None:
        return (360, 70, 230, 200)
    half = 20
    return (int(a[0]) - half, int(a[1]) - half, 2 * half, 2 * half)


SHOP_PANEL_ROI = _shop_default_roi()   # KALIBRIER-BAR (anker-zentriert)


def shop_item_roi(anchor, half=20):
    """Enge, ANKER-zentrierte Such-ROI ``(x,y,w,h)`` um einen Shop-Slot.

    So sucht ``find_shop_item`` das Item GENAU an seinem gemessenen Slot (Hammer
    ODER Dolch) und verwechselt es nicht mit demselben Icon an anderer Stelle
    (Erkennung vor Aktion). ``anchor=None`` -> ``None`` (der Aufrufer faellt dann
    auf die Default-ROI zurueck bzw. lehnt mangels Anker ab). Wirft nie."""
    if not (isinstance(anchor, (tuple, list)) and len(anchor) == 2):
        return None
    try:
        return (int(anchor[0]) - half, int(anchor[1]) - half, 2 * half, 2 * half)
    except Exception:  # pragma: no cover - defensiv
        return None


def find_shop_item(bgr, item_template, roi=None, thresh=NCC_ITEM):
    """Sucht ``item_template`` (Item-Icon) im Shop-Panel -> ``(ok, pt, ncc)``.

    ``pt`` = Icon-Mitte im CLIENT-Koordinatensystem. Ohne Template / kein Treffer
    -> ``(False, None, ncc)``. Wirft NIE. Default-ROI ist das Shop-Panel
    (``SHOP_PANEL_ROI``) -- so wird der Shop-Anker NICHT mit demselben Item im
    Inventar verwechselt (Erkennung vor Aktion).
    """
    if np is None or _cv is None or bgr is None or item_template is None:
        return (False, None, 0.0)
    client = _geo.to_client(bgr)
    roi = roi if roi is not None else SHOP_PANEL_ROI
    region = _geo.crop(client, roi)
    if region is None:
        return (False, None, 0.0)
    ok, pt, ncc = match_word(region, item_template)
    if not ok or pt is None or ncc < thresh:
        return (False, None, ncc)
    ox, oy = roi[0], roi[1]
    tpl = _to_bgr(item_template)
    th, tw = tpl.shape[:2]
    center = (ox + pt[0] + tw // 2, oy + pt[1] + th // 2)
    return (True, center, ncc)


def read_shop_stack(slot_bgr):
    """Liest die Stack-Groesse auf einem Shop-Slot -> ``int | None``.

    Die Shop-Stack-Zahl steht in EINER anderen Geometrie/Font als der Inventar-
    Zaehler; ohne kalibrierte Shop-Digit-Crops ist ein confidenter Read nicht
    moeglich. Liefert daher defensiv ``None`` (NotReady) -> der Aufrufer waehlt
    den kleinsten sicheren Stack ODER stoppt, kauft NIE auf Basis einer
    geratenen Menge. Wirft nie.
    # TODO-live-asset: Shop-Stack-Digit-Templates + ROI kalibrieren.
    """
    return None


def read_shop_stack_sizes(bgr):
    """Liest die zur Laufzeit angebotenen Stack-Groessen aus dem Shop -> tuple|None.

    Die Stack-Zahlen brauchen kalibrierte Shop-Digit-Crops (vgl.
    :func:`read_shop_stack`). Liefert defensiv ``None`` (NotReady) -> der Bot
    faellt auf das gemessene Shop-Bild-Tupel (1/50/200) zurueck. Wirft nie.
    # TODO-live-asset: Shop-Stack-Digit-Templates + Slot-ROIs.
    """
    return None


def read_splitter_growth(before, after):
    """Zuwachs am Splitter-Slot zwischen ``before`` und ``after`` -> ``int``.

    Der Energiesplitter (Ergebnis) muss laut neuer Grundwahrheit NICHT gezaehlt
    werden -- die Verarbeitung wird ueber Re-Read (Dolch-Slot leer + Hammer-Stack
    dekrementiert) verifiziert. Diese Funktion liefert daher defensiv ``0``
    ('kein messbarer Zuwachs') -> die 1:1-Verifikation verlangt einen positiven
    Wert und stoppt damit sicher, statt blind zu dekrementieren. Wirft nie.
    """
    return 0


# ----------------------------------------------------------------------------
# Inventar-Erkennung (kalibriertes Lattice, Glow-aware) -- Vertrags-API
# ----------------------------------------------------------------------------
def load_template(key):
    """Laedt ein Item- ODER NPC-Template per Schluessel als BGR -> ``ndarray|None``.

    Reihenfolge: erst ein Item-Template ``templates/<key>.png``, dann ein NPC-
    Wortbild ``templates/npc/<key>.png``. Fehlt beides -> ``None`` (der Detektor
    behandelt None defensiv als 'kein Treffer'). Wirft nie.
    """
    if _cv is None or not key:
        return None
    item = _imread(_item_path(key))
    if item is not None:
        return item
    npc = _imread(_npc_path(key))
    if npc is not None:
        return npc
    # Robustheit: ein versehentlich mit 'npc_' praefixierter Schluessel (das
    # npc/-Verzeichnis liefert _npc_path schon) -> Prefix strippen und erneut
    # versuchen. Verhindert das stille None (-> find_npc_name ncc=0.0), das den
    # NPC frueher 'nicht gefunden' erscheinen liess, obwohl die Vorlage da ist.
    if key.startswith('npc_'):
        return _imread(_npc_path(key[len('npc_'):]))
    return None


def count_item(bgr, item):
    """Zaehlt Inventar-Slots, die ``item`` tragen -> ``int`` (0..40).

    Klassifiziert JEDE Slot-Zelle ueber das kalibrierte Lattice per Template-NCC
    (Glow-tolerant). Zaehlt einen Slot als ``item``, wenn dessen NCC der
    Gewinner ist und ``>= NCC_ITEM``. Defensiv ``0`` bei fehlendem Bild/Template
    (NotReady -> der Dolch-Modus stoppt sauber 'done', statt blind zu draggen).
    Wirft nie.

    HINWEIS: zaehlt SLOTS, nicht Stueck (eine 2er-Stack-Zelle = 1 Slot). Das
    deckt den Bot-Bedarf (Bestand-da/-weg + Slot-Lokalisierung); die Stack-Zahl
    ist eine separate Messung (read_shop_stack, P0.3-Luecke).
    """
    if np is None or _cv is None or bgr is None or not item:
        return 0
    if _imread(_item_path(item)) is None:
        return 0
    client = _geo.to_client(bgr)
    n = 0
    for slot in range(1, MAX_SLOT + 1):
        lbl, _ncc = _classify_slot(client, slot)
        if lbl == item:
            n += 1
    return n


def free_slot_count(bgr):
    """Zaehlt freie (leere) Inventar-Slots auf Seite I -> ``int`` (0..40).

    Ein Slot gilt als frei, wenn KEIN Item-Template ueber ``NCC_ITEM`` matcht UND
    die Zelle nicht leuchtet (Glow = belegt durch frisch gekauftes Item) UND der
    Zellen-Inhalt keine nennenswerte Struktur hat (leere Zelle ~ uniform dunkel).
    Konservativ: im Zweifel NICHT als frei zaehlen (lieber 'kein Platz' melden
    als blind in einen vermeintlich leeren Slot kaufen). Defensiv ``0`` bei
    fehlendem Bild. Wirft nie.
    """
    if np is None or _cv is None or bgr is None:
        return 0
    client = _geo.to_client(bgr)
    free = 0
    for slot in range(1, MAX_SLOT + 1):
        cell = _slot_cell_bgr(client, slot)
        if cell is None:
            continue
        if _slot_glowing(cell):
            continue  # frisch gekauftes Item -> belegt
        lbl, _ncc = _classify_slot(client, slot)
        if lbl is not None:
            continue  # erkanntes Item -> belegt
        if _cell_is_empty(cell):
            free += 1
    return free


def _cell_is_empty(cell):
    """Heuristik: leere Inventar-Zelle ~ uniform dunkel (kein Icon-Inhalt).

    Misst die Helligkeits-Streuung der Zellen-Mitte (laesst den Slot-Rahmen aus).
    Ein Item-Icon hat hohe Streuung; eine leere Zelle ist flach. Defensiv
    ``False`` (NICHT leer) bei zu kleiner Zelle. Wirft nie.
    """
    if cell is None:
        return False
    try:
        h, w = cell.shape[:2]
        m = 4
        if h <= 2 * m or w <= 2 * m:
            return False
        inner = cell[m:h - m, m:w - m]
        return float(inner.std()) < 14.0
    except Exception:
        return False


def find_inventory_item(bgr, item):
    """Sucht ``item`` im Inventar -> ``(ok: bool, slot_point)``.

    Durchlaeuft das kalibrierte Lattice und gibt den ERSTEN Slot zurueck, dessen
    Zelle als ``item`` klassifiziert (NCC-Gewinner >= NCC_ITEM). ``slot_point``
    ist der **Pixel-Mittelpunkt** des Slots (so kann ``geometry.slot_center`` ihn
    unveraendert durchreichen). Kein Treffer / fehlendes Template -> ``(False,
    None)`` (NotReady -> der Drag-Pfad stoppt 'drag_unsafe', kein Drag). Wirft nie.
    """
    if np is None or _cv is None or bgr is None or not item:
        return (False, None)
    if _imread(_item_path(item)) is None:
        return (False, None)
    client = _geo.to_client(bgr)
    for slot in range(1, MAX_SLOT + 1):
        lbl, _ncc = _classify_slot(client, slot)
        if lbl == item:
            return (True, _cal.slot_center(slot))
    return (False, None)


def slot_is(bgr, slot, item):
    """``True``, wenn auf ``slot`` das Icon ``item`` liegt (Drag-Quelle/Ziel-Check).

    ``slot`` ist ein int-Index (1..40) ODER ein (x,y)-Punkt. Klassifiziert die
    Slot-Zelle per Template-NCC (Glow-tolerant) und vergleicht den Gewinner mit
    ``item``. Ungueltiger Slot / kein Bild / fehlendes Template -> ``False``
    (NotReady -> der Drag wird als unsicher abgebrochen). Wirft nie.
    """
    if np is None or _cv is None or bgr is None or not item:
        return False
    idx = _slot_index(slot)
    if idx is None:
        return False
    if _imread(_item_path(item)) is None:
        return False
    client = _geo.to_client(bgr)
    lbl, _ncc = _classify_slot(client, idx)
    return lbl == item


def slot_is_empty(bgr, slot):
    """``True``, wenn ``slot`` jetzt LEER ist (Drag-Erfolgs-Beleg).

    Neue Grundwahrheit: nach erfolgreicher Verarbeitung ist der Dolch-Slot leer.
    Leer = KEIN Item-Template ueber NCC_ITEM, NICHT leuchtend, und Zelle flach.
    Ungueltiger Slot / kein Bild -> ``False`` (sicher: NICHT als leer behandeln
    -> verify_process schlaegt fehl, kein Blind-Dekrement). Wirft nie.
    """
    if np is None or _cv is None or bgr is None:
        return False
    idx = _slot_index(slot)
    if idx is None:
        return False
    client = _geo.to_client(bgr)
    cell = _slot_cell_bgr(client, idx)
    if cell is None:
        return False
    if _slot_glowing(cell):
        return False
    lbl, _ncc = _classify_slot(client, idx)
    if lbl is not None:
        return False
    return _cell_is_empty(cell)


def inventory_signature(bgr):
    """Kompakte Signatur des Inventars (Slot-Belegung) fuer Vor/Nach-Diff.

    Liefert ein Tupel aus ``(slot, label_or_glow)`` fuer alle belegten Slots:
    ``label`` = ``'hammer'``/``'dolch'``, sonst ``'glow'`` (leuchtende, nicht
    klassifizierte Zelle = frisch gekauftes Item) oder ``'item'`` (belegt, aber
    weder Hammer noch Dolch). Leere Slots erscheinen NICHT -> ein neuer Eintrag
    nach einem Kauf ist der Lande-Slot. Defensiv ``None`` bei fehlendem Bild.
    Wirft nie.
    """
    if np is None or _cv is None or bgr is None:
        return None
    client = _geo.to_client(bgr)
    sig = []
    for slot in range(1, MAX_SLOT + 1):
        cell = _slot_cell_bgr(client, slot)
        if cell is None:
            continue
        lbl, _ncc = _classify_slot(client, slot)
        if lbl is not None:
            sig.append((slot, lbl))
        elif _slot_glowing(cell):
            sig.append((slot, 'glow'))
        elif not _cell_is_empty(cell):
            sig.append((slot, 'item'))
    return tuple(sig)


def diff_landing_slot(before, after):
    """Bestimmt den Slot, in dem ein gekauftes Item gelandet ist (Signatur-Diff).

    Vergleicht zwei :func:`inventory_signature`-Werte und gibt den **Pixel-
    Mittelpunkt** des EINEN neu belegten Slots zurueck (Lande-Slot des Kaufs).
    Bevorzugt einen Slot, der jetzt leuchtet ('glow' = frisch gekauft). Mehr-
    deutig (0 oder >1 neue Slots) oder fehlende Signatur -> ``None`` (NotReady ->
    der Bot draggt NICHT). Wirft nie.
    """
    if not isinstance(before, tuple) or not isinstance(after, tuple):
        return None
    before_slots = {s for s, _ in before}
    new_entries = [(s, lbl) for s, lbl in after if s not in before_slots]
    if not new_entries:
        return None
    glow_new = [s for s, lbl in new_entries if lbl == 'glow']
    if len(glow_new) == 1:
        return _cal.slot_center(glow_new[0])
    if len(new_entries) == 1:
        return _cal.slot_center(new_entries[0][0])
    return None


__all__ = [
    'assets_ready', 'grid_present', 'match_word', 'find_npc_name', 'selection_ring_present',
    'dialog_state', 'shop_open', 'panel_is_bag', 'find_shop_item', 'shop_item_roi',
    'read_shop_stack', 'read_shop_stack_sizes', 'read_splitter_growth',
    'load_template', 'item_template_available', 'count_item',
    'free_slot_count', 'inventory_signature', 'diff_landing_slot',
    'find_inventory_item', 'slot_is', 'slot_is_empty',
    'HAMMER_ITEMS', 'DAGGER_EXTRA_ITEMS', 'HAMMER_NPCS', 'DAGGER_EXTRA_NPCS',
    'NCC_WORD', 'NCC_HEADER', 'NCC_ITEM', 'SLOT_CELL', 'MAX_SLOT',
]
