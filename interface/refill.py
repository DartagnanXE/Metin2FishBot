# -*- coding: utf-8 -*-
"""Auto-refill: drag a bait into the quick-slot / a puzzle box onto the board.

This is the PURE brain + the input PRIMITIVE of the refill automation, kept free
of any live dependency (no ``pydirectinput``, no ``WindowCapture``) so it is unit
tested headlessly; the live loop injects the input API + the screenshot. The two
things that genuinely need the live window -- the exact quick-slot drop pixel and
the drag timing -- are isolated as the tunables ``QUICKSLOT_XY`` / ``DRAG_*``.

Game runs FIXED at 800x600, so every UI element sits at a constant client pixel;
the only per-run variable is the window's top-left on screen (``offset_x/y``,
exactly what fishingbot/puzzle already add to every click).

Quick-slot model (per the spec): exactly 8 slots, keys ``1 2 3 4`` (slots 1-4)
and ``F1 F2 F3 F4`` (slots 5-8) -- nothing else. The configured bait key both
selects the slot to drag INTO and is the key fishing presses to bait the rod.
"""

from inventory.constants import DEFAULT_CALIBRATION, INPUT_SETTLE_S
from inventory.grid import lattice_from_calibration

try:  # pragma: no cover - numpy present in production
    import numpy as _np
except Exception:  # pragma: no cover
    _np = None

# The only 8 valid quick-slot keys (index 0 -> slot 1, ... index 7 -> slot 8).
QUICKSLOT_KEYS = ('1', '2', '3', '4', 'f1', 'f2', 'f3', 'f4')

# Drop-pixel CENTRE of each quick-slot in the 800x601 client (before the window
# offset). RE-MEASURED from a real live capture (live_capture.png, 800x601 CLIENT
# -- NOT the 802x632 reference): the quick-slot belt sits along the bottom edge,
# split by a central chevron divider into 1-4 (left) and 5-8 (right). The clean
# periodic slot borders on the empty right half land at x=455,487,519,551,583
# (pitch 32px), bracketing slots 5-8 at centres 471/503/535/567; the left half
# borders at 316/348/380/412/444 bracket slots 1-4 at 332/364/396/428. Row centre
# y~582 (icon interior spans y~568..596). The bait stack "47" sat in slot 2 here.
QUICKSLOT_XY = {
    1: (332, 582), 2: (364, 582), 3: (396, 582), 4: (428, 582),
    5: (471, 582), 6: (503, 582), 7: (535, 582), 8: (567, 582),
}

# Item names eligible for each refill (recognised by the inventory engine).
BAIT_NAMES = ('Worm',)
BOX_NAMES = ('Fischpuzzlebox', 'Fischpuzzlebox_Deluxe')
# Getrennte Namen pro PUZZLE-Box-Slot: die STANDARD-Box darf NUR in den unteren
# Standard-Slot, die DELUXE-Box NUR in den oberen Deluxe-Slot -- nie vertauscht.
# (``find_first`` matcht ``s.name in want``, also findet ein 1-Tupel ausschliesslich
# genau diese Box -> nie das jeweils andere Item.)
BOX_STD_NAMES = ('Fischpuzzlebox',)
BOX_DELUXE_NAMES = ('Fischpuzzlebox_Deluxe',)


def box_refill_due(streak, *, min_streak, done, max_done):
    """Pure Entscheidung fuers Puzzle-Box-Nachlegen (headless testbar).

    ``True`` nur, wenn die Box als leer gilt (``streak`` leere getpiece IN FOLGE
    >= ``min_streak``) UND die Sicherheits-Obergrenze noch nicht erreicht ist
    (``done < max_done``). Streak-basiert statt Slot-OCR, weil das wiederholte
    Ausbleiben eines Steins das robusteste "Box leer"-Signal des Spiels ist.
    Defensiv: nicht-numerische Eingaben -> ``False`` (nie nachlegen im Zweifel)."""
    try:
        return int(streak) >= int(min_streak) and int(done) < int(max_done)
    except (TypeError, ValueError):
        return False

# Inventory pages in scan order, and the grid shape.
PAGE_ORDER = ('I', 'II', 'III', 'IV')

# Drag timing (seconds) -- tunable on the live window.
DRAG_STEPS = 12        # intermediate moves so the game registers the drag
DRAG_SETTLE = INPUT_SETTLE_S   # pause after press / before release (speed knob)


def quickslot_index(key):
    """1..8 for a valid quick-slot key (case-insensitive), else ``None``."""
    try:
        return QUICKSLOT_KEYS.index(str(key).strip().lower()) + 1
    except (ValueError, AttributeError):
        return None


def is_quickslot_key(key):
    """True iff ``key`` is one of the 8 allowed quick-slot keys."""
    return quickslot_index(key) is not None


def quickslot_screen(slot_1to8, offset_x=0, offset_y=0):
    """Screen ``(x, y)`` to drop an item INTO quick-slot ``slot_1to8`` (1..8)."""
    cx, cy = QUICKSLOT_XY[int(slot_1to8)]
    return (int(offset_x + cx), int(offset_y + cy))


def inventory_slot_screen(row, col, offset_x=0, offset_y=0,
                          calib=DEFAULT_CALIBRATION):
    """Screen ``(x, y)`` of the CENTRE of inventory slot ``(row, col)``.

    Page-independent (switching tabs does not move the grid); the caller opens
    the right page first. Derived from the calibration grid (origin + pitch) so
    it tracks the user's own calibration, + the window offset like every other
    click in the bot.
    """
    lat = lattice_from_calibration(calib)
    ox, oy = lat.origin
    px, py = lat.pitch
    x = ox + col * px + px // 2
    y = oy + row * py + py // 2
    return (int(offset_x + x), int(offset_y + y))


def find_first(inv, names, pages=PAGE_ORDER):
    """First slot holding one of ``names``, in PAGE order then row-major.

    Returns ``(page, row, col)`` or ``None``. This is the documented refill
    order: inventory pages I->IV, each slot 1..45 top-to-bottom. Pure: works on
    any object exposing ``pages -> {page: [SlotResult]}``.
    """
    want = set(names)
    page_map = getattr(inv, 'pages', {}) or {}
    for page in pages:
        slots = page_map.get(page) or ()
        for s in slots:
            if getattr(s, 'state', None) == 'item' and getattr(s, 'name', None) in want:
                return (page, int(s.row), int(s.col))
    return None


def summarize_inventory(inv, pages=PAGE_ORDER):
    """Kompakte Debug-Zusammenfassung des Scans: pro Seite die erkannten Item-
    Namen + die Zahl NICHT erkannter (belegter, aber un-klassifizierter) Slots.

    Genau das fehlte bei "keine Box gefunden": eine present-aber-``unknown``
    klassifizierte Box taucht in keiner Item-Liste auf, wohl aber als ``?N``
    (unbekannt) -- so ist sofort sichtbar, ob die Box GAR NICHT da ist oder nur
    nicht ERKANNT wird. Rein lesend, wirft nie."""
    page_map = getattr(inv, 'pages', {}) or {}
    parts = []
    for page in pages:
        slots = page_map.get(page) or ()
        names = []
        unknown = 0
        for s in slots:
            st = getattr(s, 'state', None)
            if st == 'item':
                names.append(str(getattr(s, 'name', '?')))
            elif st == 'unknown':
                unknown += 1
        seg = '%s:[%s]' % (page, ','.join(names) if names else '-')
        if unknown:
            seg += '+?%d' % unknown
        parts.append(seg)
    return ' '.join(parts)


def plan_refill(inv, names):
    """Decide the next refill action from a scan.

    Returns ``('drag', page, row, col)`` for the first matching item, or
    ``('empty',)`` when none is left (the caller stops the bot + warns).
    """
    loc = find_first(inv, names)
    return ('drag', loc[0], loc[1], loc[2]) if loc is not None else ('empty',)


def drag(api, x1, y1, x2, y2, steps=DRAG_STEPS, settle=DRAG_SETTLE,
         sleep=None):
    """Press-hold-move-release drag from ``(x1,y1)`` to ``(x2,y2)``.

    ``api`` is any object with ``moveTo(x, y)``, ``mouseDown()``, ``mouseUp()``
    (pydirectinput in production, a recorder in tests). Intermediate moves make
    the game register the drag rather than a teleport. ``sleep`` defaults to
    ``time.sleep``; tests pass a no-op. Never raises -> a failed drag must not
    crash the bot loop (it releases the button in a finally).
    """
    if sleep is None:
        import time
        sleep = time.sleep
    try:
        api.moveTo(int(x1), int(y1))
        sleep(settle)
        api.mouseDown()
        sleep(settle)
        n = max(1, int(steps))
        for i in range(1, n + 1):
            x = x1 + (x2 - x1) * i // n
            y = y1 + (y2 - y1) * i // n
            api.moveTo(int(x), int(y))
            sleep(settle / n)
        sleep(settle)
    finally:
        try:
            api.mouseUp()
        except Exception:
            pass


# Empty-slot probe tunables (calibrated on live_capture.png, 800x601 CLIENT).
# An EMPTY slot is not merely dark -- it is DARK *and* FLAT (uniform background,
# no icon highlights). An OCCUPIED slot -- even a dark, thin reddish bait icon
# like the "47" worm stack -- always carries BRIGHT pixels (icon highlights /
# white stack digits) and high local contrast. The old test (patch mean < 42)
# wrongly flagged the worm slot as empty (its patch mean was only ~25, barely
# above a truly empty ~9), so the bot refilled CONSTANTLY. We instead require
# all three empty signals to agree, with wide margins measured on the live frame:
#   empty patch:  mean ~9,  std ~7,   bright(>70) px = 0
#   worm patch:   mean ~25, std ~46,  bright(>70) px ~38
QUICKSLOT_PROBE_RADIUS = 11   # half-size of the sampled square (px)
QUICKSLOT_DARK_MEAN = 45      # slot mean grayscale must be below this to be empty
QUICKSLOT_FLAT_STD = 14       # ... and contrast (std) below this (flat background)
QUICKSLOT_BRIGHT_VALUE = 70   # a pixel brighter than this counts as "icon ink"
QUICKSLOT_MAX_BRIGHT_PX = 4   # ... and fewer than this many bright px present


def quickslot_is_empty(screenshot_bgr, slot_1to8, radius=QUICKSLOT_PROBE_RADIUS,
                       dark_mean=QUICKSLOT_DARK_MEAN, flat_std=QUICKSLOT_FLAT_STD,
                       bright_value=QUICKSLOT_BRIGHT_VALUE,
                       max_bright_px=QUICKSLOT_MAX_BRIGHT_PX):
    """True iff quick-slot ``slot_1to8`` is CONFIDENTLY EMPTY (no item icon).

    Samples a small patch at the slot's client pixel on the captured window
    (the screenshot IS the 800x601 client, so client == screenshot coords) and
    calls it empty ONLY when that patch is at once DARK (low mean), FLAT (low
    std) and free of bright "icon ink" pixels -- the fingerprint of the empty
    slot background. Any item, even a dark bait icon with a stack count, breaks
    at least one of those, so it reads as occupied. Channel-order agnostic
    (uses the per-pixel channel mean), so it works on BGR captures or RGB alike.

    Strictly conservative for the refill loop: returns ``False`` (assume
    OCCUPIED -> do NOT refill) whenever numpy/the image is unavailable, the
    patch is degenerate, or anything raises. In doubt we never refill.
    """
    if _np is None or screenshot_bgr is None:
        return False
    try:
        cx, cy = QUICKSLOT_XY[int(slot_1to8)]
        arr = _np.asarray(screenshot_bgr)
        if arr.ndim != 3 or arr.shape[2] < 3:
            return False
        h, w = arr.shape[0], arr.shape[1]
        r = max(1, int(radius))
        y0, y1 = max(0, cy - r), min(h, cy + r)
        x0, x1 = max(0, cx - r), min(w, cx + r)
        if y1 <= y0 or x1 <= x0:
            return False
        patch = arr[y0:y1, x0:x1, :3].astype(_np.float32)
        gray = patch.mean(axis=2)
        bright_px = int((gray > float(bright_value)).sum())
        is_dark = float(gray.mean()) < float(dark_mean)
        is_flat = float(gray.std()) < float(flat_std)
        return is_dark and is_flat and bright_px < int(max_bright_px)
    except Exception:
        return False


def tab_click(inp, calib, offset_x, offset_y, page):
    """Click an inventory page tab (I..IV) via the injected input api.

    Defensive (wie der ganze Refill-Pfad): ein fehlender Tab-Punkt oder ein
    Input-Fehler darf den Scan NIE abreissen -- still no-op statt Exception.
    """
    try:
        pt = ((calib or {}).get('tabs', {}) or {}).get(page)
        if pt:
            inp.click(x=int(offset_x + pt[0]), y=int(offset_y + pt[1]),
                      button='left')
    except Exception:
        pass


def refill_from_inventory(item_names, target_xy, *, inp, wincap, db,
                          calib=DEFAULT_CALIBRATION, sleep=None,
                          should_stop=None):
    """Scan the (already open) inventory + drag the first matching item to
    ``target_xy``. Returns ``'dragged'`` / ``'empty'`` / ``'error'`` / ``'stopped'``.

    Reuses the headless scanner (tab-click page switch built from the
    calibration + window offset) + the tested find/coordinate/drag helpers.
    Strictly defensive -- a vision/input failure returns ``'error'`` and never
    raises into the bot loop.

    ``should_stop`` is an optional no-arg predicate (the live loop passes the
    global Stop-Signal). When it goes truthy the op aborts at the NEXT checkpoint
    -- between page switches, before the drag -- and returns ``'stopped'`` so a
    panic-stop (F6) is honoured within one page-switch nap instead of blocking
    the loop for the whole multi-page scan + drag. Off (``None``) -> unchanged.
    """
    if sleep is None:
        import time
        sleep = time.sleep
    stop = should_stop if callable(should_stop) else (lambda: False)

    def _napped(seconds):
        """Sleep ``seconds`` but bail the instant a stop is requested.

        Returns ``False`` if a stop interrupted the nap (caller aborts). The
        injected ``sleep`` is the interruptible Stop-Signal.wait in production
        (returns False on a stop) and a plain/​no-op sleep in tests; either way we
        re-check ``stop`` after it so the abort is honoured regardless.
        """
        result = sleep(seconds)
        if result is False:
            return False
        return not stop()

    try:
        if stop():
            return 'stopped'
        from inventory.scanner import scan_inventory
        # Vertrag (vgl. fishingbot.bait_refill_db / run_loop._bait_refill_db):
        # db=None -> Engine baut/nutzt den gebuendelten Default selbst. Der
        # serielle scan_inventory-Pfad ruft classify_slot -> db.best_slot_result
        # ungeschuetzt auf; mit db=None wuerde das jeden Slot mit AttributeError
        # abbrechen (vom aeusseren except als 'error' verschluckt -> Nachlegen
        # stumm tot). Hier EINMAL defensiv die Bundle-DB nachladen; klappt auch
        # das nicht (z. B. numpy/PIL fehlt), sauber 'error' melden.
        if db is None:
            try:
                from interface.inventory_io import _get_db
                db = _get_db()
            except Exception:
                return 'error'
        ox = int(getattr(wincap, 'offset_x', 0) or 0)
        oy = int(getattr(wincap, 'offset_y', 0) or 0)

        # Abbruch-Marke fuer den seriellen Page-Scan: ``_switch_page`` ist der
        # einzige Hook waehrend des Scans -- wird hier zwischen den Seiten
        # gesetzt, falls ein Stop kam, damit der Scan nach der aktuellen Seite
        # zuegig endet (statt alle 4 Seiten + Drag durchzuziehen).
        aborted = {'stop': False}

        def _switch_page(page):
            # MUSS die Tab navigieren: scan_inventory ruft switch_page_fn(page),
            # um auf Seite ``page`` zu wechseln, BEVOR es den Frame greift. Ohne
            # den Klick blieb dieselbe (Start-)Seite offen -> der Scanner sah I..IV
            # alle als Seite I, Items auf II/III/IV wurden nie gefunden -> der Bot
            # meldete faelschlich 'empty'. Erst klicken, dann die (interruptible)
            # Settle-Nap fuer den Stop-Check.
            tab_click(inp, calib, ox, oy, page)
            if not _napped(0.2):
                aborted['stop'] = True

        inv = scan_inventory(
            capture_fn=wincap.get_screenshot,
            switch_page_fn=_switch_page,
            db=db, calib=calib)
        if aborted['stop'] or stop():
            return 'stopped'
        loc = find_first(inv, item_names)
        if loc is None:
            # DIAGNOSE: was hat der Scan ueberhaupt gefunden? Eine present-aber-
            # 'unknown' klassifizierte Box (z.B. Stack-Zahl wirft das Template-
            # Matching) erscheint hier als '?N' -> sofort erkennbar, ob die Box
            # FEHLT oder nur nicht ERKANNT wird. Soft -- Logging darf nie kippen.
            try:
                from debuglog import log as _dbg
                _dbg.event('refill', 'Inventar-Scan: gesucht={} | gefunden: {}'.format(
                    list(item_names), summarize_inventory(inv)))
            except Exception:
                pass
            return 'empty'
        page, row, col = loc
        tab_click(inp, calib, ox, oy, page)
        if not _napped(0.25):
            return 'stopped'
        fx, fy = inventory_slot_screen(row, col, ox, oy, calib)
        # Den Drag selbst mit der interruptiblen Sleep ausstatten: bricht ein Stop
        # mitten in den Zwischen-Moves, gibt der finally-Block in ``drag`` die
        # Maustaste trotzdem frei (kein haengender Mausknopf).
        drag(inp, fx, fy, int(target_xy[0]), int(target_xy[1]), sleep=sleep)
        _napped(0.15)
        return 'dragged'
    except Exception:
        return 'error'


# ---------------------------------------------------------------------------
# DEDIZIERTER PUZZLE-BOX-FINDER (robust, client-kalibriert)
#
# Warum nicht der itemdb-Scan? Auf dem echten Client (Screenshot 2026-06-17)
# erkannte ``scan_inventory`` GAR NICHTS (alle Slots 'unknown'): (1) der Grid-
# Auto-Align lockt ~10px daneben (Default-Grid 633,244 ist korrekt -> Box-Zentrum
# 713,388 ✓), und (2) die Box traegt eine GROSSE Stueckzahl (57/104/200) in der
# UNTEREN Haelfte -> Voll-Icon-MAD 41 (> Schwelle). Loesung (Bild-validiert):
# am FESTEN Kalibrier-Grid abtasten + nur die OBERE Icon-Haelfte matchen
# (Stueckzahl ignoriert). Messwerte: Standard-Box topMAD~1.0, Deluxe-Box ~24.8,
# JEDER Nicht-Box-Slot >=39 -> Schwelle 28 trennt sauber.
# ---------------------------------------------------------------------------
BOX_MATCH_TOP_ROWS = 16   # nur die oberen 16 Zeilen matchen (untere = Stueckzahl)
BOX_MATCH_MAX_MAD = 28.0  # bild-validiert: Box <=24.8, alles andere >=39
BOX_MATCH_SHIFT = 3       # +-px Suchfenster (wie itemdb-Shift, gegen Sub-Pixel-Drift)

_BOX_TPL_CACHE = {}


def _box_template(name):
    """``(bgr_float32[32,32,3], top_mask_bool[32,32])`` fuer
    ``inventory_icons/<name>.png`` -- nur die obere Haelfte der Alpha-Maske aktiv
    (untere traegt die variable Stueckzahl). Gecacht; ``None`` bei Fehler/headless.
    BGR (cv2), passend zum BGR-Screenshot der WindowCapture."""
    if name in _BOX_TPL_CACHE:
        return _BOX_TPL_CACHE[name]
    result = None
    try:
        import os
        import cv2
        from respath import resource_path
        path = resource_path(os.path.join('inventory_icons', name + '.png'))
        bgra = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if bgra is not None and bgra.ndim == 3 and bgra.shape[2] >= 4 \
                and bgra.shape[0] >= BOX_MATCH_TOP_ROWS and _np is not None:
            bgr = bgra[:, :, :3].astype(_np.float32)
            mask = bgra[:, :, 3] > 32
            mask[BOX_MATCH_TOP_ROWS:, :] = False   # untere Haelfte (Zahl) ignorieren
            if mask.any():
                result = (bgr, mask)
    except Exception:
        result = None
    _BOX_TPL_CACHE[name] = result
    return result


def _box_slot_mad(frame, cx, cy, tpl_bgr, tpl_mask, shift=BOX_MATCH_SHIFT):
    """Kleinste maskierte MAD (obere Haelfte) eines ``tpl``-Icons um Slot-Zentrum
    ``(cx, cy)`` mit ``+-shift`` px Suchfenster. ``1e9`` wenn nicht auswertbar."""
    th, tw = tpl_bgr.shape[0], tpl_bgr.shape[1]
    h, w = frame.shape[0], frame.shape[1]
    best = 1e9
    for dy in range(-shift, shift + 1):
        for dx in range(-shift, shift + 1):
            y0 = cy + dy - th // 2
            x0 = cx + dx - tw // 2
            if y0 < 0 or x0 < 0 or y0 + th > h or x0 + tw > w:
                continue
            patch = frame[y0:y0 + th, x0:x0 + tw, :3].astype(_np.float32)
            d = _np.abs(patch - tpl_bgr)[tpl_mask]
            if d.size:
                m = float(d.mean())
                if m < best:
                    best = m
    return best


def find_box_slot(capture_fn, switch_page_fn, box_names, calib=DEFAULT_CALIBRATION,
                  pages=PAGE_ORDER, should_stop=None):
    """ERSTE Box (eines der ``box_names``) im Inventar -- Seite ``pages`` in
    Reihenfolge, je Seite row-major -- per OBERE-HAELFTE-Template-Match am
    KALIBRIER-Grid (kein Auto-Align). Rueckgabe ``(page, row, col, name)`` oder
    ``None``. Streng defensiv: wirft nie."""
    if _np is None:
        return None
    tpls = [(n, _box_template(n)) for n in box_names]
    tpls = [(n, t) for n, t in tpls if t is not None]
    if not tpls:
        return None
    grid = (calib or {}).get('grid', {}) or {}
    cols = int(grid.get('cols', 5))
    rows = int(grid.get('rows', 9))
    try:
        lat = lattice_from_calibration(calib)
        ox0, oy0 = lat.origin
        px, py = lat.pitch
    except Exception:
        return None
    stop = should_stop if callable(should_stop) else (lambda: False)
    for page in pages:
        try:
            switch_page_fn(page)
        except Exception:
            pass
        if stop():
            return None
        try:
            frame = capture_fn()
        except Exception:
            frame = None
        if frame is None or getattr(frame, 'ndim', 0) != 3:
            continue
        for row in range(rows):
            for col in range(cols):
                cx = int(ox0 + col * px + px // 2)
                cy = int(oy0 + row * py + py // 2)
                for name, (tb, tm) in tpls:
                    if _box_slot_mad(frame, cx, cy, tb, tm) <= BOX_MATCH_MAX_MAD:
                        return (page, row, col, name)
    return None


def box_refill_from_inventory(box_names, target_xy, *, inp, wincap,
                              calib=DEFAULT_CALIBRATION, sleep=None,
                              should_stop=None):
    """Wie ``refill_from_inventory``, aber mit dem dedizierten, client-robusten
    ``find_box_slot`` (fester Grid + obere-Haelfte-Match) statt dem itemdb-Scan,
    der auf dem echten Client nichts erkennt. Findet die erste Box, wechselt auf
    deren Seite, zieht sie an ``target_xy``. Rueckgabe
    ``'dragged'|'empty'|'error'|'stopped'``. Wirft nie."""
    if sleep is None:
        import time
        sleep = time.sleep
    stop = should_stop if callable(should_stop) else (lambda: False)

    def _napped(seconds):
        result = sleep(seconds)
        if result is False:
            return False
        return not stop()

    try:
        if stop():
            return 'stopped'
        ox = int(getattr(wincap, 'offset_x', 0) or 0)
        oy = int(getattr(wincap, 'offset_y', 0) or 0)
        aborted = {'stop': False}

        def _switch_page(page):
            tab_click(inp, calib, ox, oy, page)
            if not _napped(0.2):
                aborted['stop'] = True

        loc = find_box_slot(wincap.get_screenshot, _switch_page, box_names,
                            calib=calib, should_stop=lambda: aborted['stop'] or stop())
        if aborted['stop'] or stop():
            return 'stopped'
        if loc is None:
            try:
                from debuglog import log as _dbg
                _dbg.event('refill', 'Box-Scan (obere-Haelfte-Match): gesucht={} '
                           '-> keine Box gefunden'.format(list(box_names)))
            except Exception:
                pass
            return 'empty'
        page, row, col, name = loc
        try:
            from debuglog import log as _dbg
            _dbg.event('refill', 'Box gefunden: {} auf Seite {} Slot (r{},c{})'.format(
                name, page, row, col))
        except Exception:
            pass
        tab_click(inp, calib, ox, oy, page)
        if not _napped(0.25):
            return 'stopped'
        fx, fy = inventory_slot_screen(row, col, ox, oy, calib)
        drag(inp, fx, fy, int(target_xy[0]), int(target_xy[1]), sleep=sleep)
        _napped(0.15)
        return 'dragged'
    except Exception:
        return 'error'
