# -*- coding: utf-8 -*-
"""Selbst-enthaltene Test-Fenster mit Titel ``"METIN2"`` (800x600).

Ersetzt das externe Wegwerf-Skript ``_fake_metin2.py``: spawnt Tk-Toplevels,
deren Titel EXAKT der Spielname (:data:`constants.GAME_NAME`) ist, damit
``win32gui.FindWindow(None, 'METIN2')`` (und ``enumerate_game_windows``) sie
findet und START/Scan tatsaechlich gegen sie laufen, OHNE das echte Spiel. So
lassen sich Capture, Farb-/Board-Erkennung, der Inventar-Scanner UND der
Mehrfenster-Picker trocken ueben.

Zwei Inhalts-Varianten (``kind``):

  * ``'board'`` (Default, Rueckwaerts-Kompatibilitaet): ein farbiges 6x4-„Board"
    an der Default-Brettlage (Inhalt-Offset ``(270, 227)``), das sich mit der
    Default-Vorschau (:mod:`overlay_preview`) deckt -- echte Pixel fuer Farb-/
    Board-Erkennung. SINGLE-Instance (erneuter Aufruf holt das Fenster nach vorn).
  * ``'inventory'`` (CS5): ein INVENTAR, gezeichnet an der echten Inventar-
    Client-Lage (aus :data:`inventory.constants.DEFAULT_CALIBRATION`), indem die
    gebuendelten ``inventory_icons/*.png`` auf das dunkle Slot-Raster komponiert
    werden -- erkennbar fuer dieselbe Icon-DB, sodass ein echter Scan Items liest.
    MEHRFENSTER: jeder Druck oeffnet ein WEITERES (bis :data:`MAX_TEST_WINDOWS`),
    damit der Nutzer (a) den Inventar-Scanner und (b) den Mehrfenster-Picker
    (CS4) gegen die Fakes testen kann.

Vertrag (vom UI ``interface/app`` konsumiert)::

    open_test_window(parent=None, kind='board') -> tk.Toplevel | None
    open_inventory_test_window(parent=None)     -> tk.Toplevel | None

  * ``parent`` -- die App-Root (die App besitzt den Tk-Root; hier wird KEIN
    zweites ``tk.Tk()`` erzeugt). ``None`` ist erlaubt (eigenstaendiger Start).
  * Rueckgabe: das erzeugte (oder noch lebende) Toplevel, oder ``None`` ohne
    Display / bei Fehler. Wirft nie.

Bewusst defensiv (gleiche Disziplin wie overlay_mark/overlay_preview): Tk wird
WEICH importiert; fehlt das Display, liefert die Funktion sauber ``None`` und das
Modul bleibt importierbar/``py_compile``-bar (headless-Tests). Auch der Inventar-
Anstrich degradiert (fehlt PIL/numpy oder ein Icon -> ein beschriftetes Platzhalter-
Raster), nie eine Ausnahme.
"""

import constants

# Tk weich einbinden (kein Display unter WSL/Test -> ImportError moeglich).
try:
    import tkinter as tk
except Exception:  # pragma: no cover
    tk = None

# Logging weich einbinden -- ein kaputter Logger darf das Fenster nie stoppen.
try:
    from debuglog import log, log_event as _log_event_raw
except Exception:  # pragma: no cover - reiner Fallback
    log = None
    def _log_event_raw(state, message, **fields):
        """No-op-Fallback, falls debuglog fehlt. Wirft nie."""
        pass


# -- Konstanten ------------------------------------------------------------

WINDOW_SIZE = (800, 600)

# Lage/Groesse des farbigen Test-Boards IM Fensterinhalt -- deckt sich mit
# PuzzleBot.PUZZLE_WINDOW_POSITION/SIZE bzw. overlay_preview-Default.
BOARD_OFFSET = (270, 227)
BOARD_SIZE = (260, 170)
BOARD_COLS = 6
BOARD_ROWS = 4

# Maximale Anzahl gleichzeitig offener INVENTAR-Testfenster (CS5): ein zweiter
# Druck oeffnet ein weiteres, damit der Mehrfenster-Picker (CS4) etwas zum Waehlen
# hat. Mehr als zwei braucht der Test nicht.
MAX_TEST_WINDOWS = 2

_BG = '#101820'
_BOARD_BG = '#0b0f14'

# Lebhafte, gut unterscheidbare Zellfarben (zyklisch ueber die 24 Zellen).
_CELL_COLORS = (
    '#ef4444', '#f59e0b', '#eab308', '#22c55e', '#14b8a6', '#3b82f6',
    '#8b5cf6', '#ec4899', '#f97316', '#84cc16', '#06b6d4', '#a855f7',
)

# Modul-weite Referenz auf das aktuell offene BOARD-Fenster (Single-Instance,
# Duplikat-Schutz -- byte-identisches Verhalten zu frueher).
_open_window = None

# Modul-weite Liste der offenen INVENTAR-Testfenster (CS5, MEHRFENSTER). Tote
# Eintraege werden beim OEffnen/Schliessen aufgeraeumt.
_open_windows = []


def _log_event(message, **fields):
    """Strukturierte Log-Zeile (State 0); absturzsicher via debuglog.log_event."""
    _log_event_raw(0, message, **fields)


def _is_alive(win):
    """``True``, wenn ``win`` noch ein lebendes Tk-Fenster ist. Wirft nie."""
    if win is None:
        return False
    try:
        return bool(win.winfo_exists())
    except Exception:
        return False


def _prune_open_windows():
    """Entfernt tote (geschlossene) Eintraege aus ``_open_windows``. Wirft nie."""
    global _open_windows
    _open_windows = [w for w in _open_windows if _is_alive(w)]
    return _open_windows


def _draw_board(canvas):
    """Zeichnet ein farbiges 6x4-Board + Rahmen an der Default-Board-Lage.

    Liefert echte, unterscheidbare Pixel fuer Farb-/Erkennungstests. Wirft nie.
    """
    try:
        ox, oy = BOARD_OFFSET
        board_w, board_h = BOARD_SIZE

        # Board-Hintergrund + Rahmen.
        canvas.create_rectangle(
            ox, oy, ox + board_w, oy + board_h,
            fill=_BOARD_BG, outline='#14b8a6', width=2)

        cell_w = board_w / BOARD_COLS
        cell_h = board_h / BOARD_ROWS
        pad = 4
        idx = 0
        for i in range(BOARD_ROWS):
            for j in range(BOARD_COLS):
                x0 = ox + j * cell_w + pad
                y0 = oy + i * cell_h + pad
                x1 = ox + (j + 1) * cell_w - pad
                y1 = oy + (i + 1) * cell_h - pad
                color = _CELL_COLORS[idx % len(_CELL_COLORS)]
                canvas.create_rectangle(x0, y0, x1, y1,
                                        fill=color, outline='')
                idx += 1
    except Exception:
        pass


# -- Inventar-Anstrich (CS5) ----------------------------------------------

def _inventory_grid_origin():
    """Liefert ``(ox, oy, pitch_x, pitch_y, cols, rows)`` der Inventar-Lage.

    Aus :data:`inventory.constants.DEFAULT_CALIBRATION` (dieselbe Geometrie, die
    der Scanner erwartet), damit die komponierten Icons an genau den Slot-
    Koordinaten sitzen, an denen der Scanner sie sucht. Faellt der Import aus,
    Rueckfall auf vernuenftige Defaults. Wirft nie.
    """
    try:
        from inventory.constants import DEFAULT_CALIBRATION, SLOT_PX, COLS, ROWS
        tl = DEFAULT_CALIBRATION['grid']['tl']
        return (int(tl[0]), int(tl[1]), SLOT_PX, SLOT_PX, COLS, ROWS)
    except Exception:
        return (633, 275, 32, 32, 5, 9)


def _load_icon_photo(name_to_path, cache, icon_name):
    """Laedt ein Inventar-Icon als Tk ``PhotoImage`` (32x32, gecacht). Soft.

    Nutzt PIL, wenn vorhanden (RGBA -> auf dunklen Slot-Hintergrund gemischt,
    damit transparente Raender nicht schwarz werden). Liefert ``None``, wenn PIL/
    die Datei fehlt -- dann zeichnet der Aufrufer den Slot als Platzhalter. Wirft
    nie. ``cache`` haelt Referenzen, sonst raeumt Tk die Bilder weg (GC).
    """
    if icon_name in cache:
        return cache[icon_name]
    path = name_to_path.get(icon_name)
    if not path:
        cache[icon_name] = None
        return None
    try:
        from PIL import Image, ImageTk
        img = Image.open(path).convert('RGBA')
        if img.size != (32, 32):
            img = img.resize((32, 32))
        # Auf den dunklen Slot-Hintergrund mischen (EMPTY_REF-naher Ton), damit der
        # Scanner die de-glow-Erwartung (dunkler Grund) trifft und Raender nicht
        # hart schwarz sind.
        bg = Image.new('RGBA', (32, 32), (8, 10, 6, 255))
        bg.alpha_composite(img)
        photo = ImageTk.PhotoImage(bg.convert('RGB'))
        cache[icon_name] = photo
        return photo
    except Exception:
        cache[icon_name] = None
        return None


def _icon_name_to_path():
    """Mapping ``icon_name -> dateipfad`` der gebuendelten ``inventory_icons``.

    Ueber :func:`respath.resource_path`, sodass es aus dem Quellbaum UND der
    PyInstaller-EXE funktioniert (``inventory_icons/`` ist als data gebuendelt).
    Wirft nie -> ``{}`` bei Fehler.
    """
    try:
        import os
        from respath import resource_path
        base = resource_path('inventory_icons')
        out = {}
        for fn in os.listdir(base):
            if fn.lower().endswith('.png'):
                out[os.path.splitext(fn)[0]] = os.path.join(base, fn)
        return out
    except Exception:
        return {}


def _draw_inventory(canvas, photo_cache):
    """Zeichnet ein INVENTAR an der echten Inventar-Client-Lage (CS5).

    Komponiert die gebuendelten Icons (u.a. die Key-Items Fischpuzzlebox /
    Lagerfeuer / Worm) auf das dunkle Slot-Raster, sodass ein echter Scan sie an
    den erwarteten Slot-Koordinaten erkennt. Fehlt PIL / ein Icon, wird der Slot
    als beschrifteter Platzhalter gezeichnet (nie ein Crash). ``photo_cache`` MUSS
    am Fenster gehalten werden (sonst GC der PhotoImages).
    """
    try:
        ox, oy, px, py, cols, rows = _inventory_grid_origin()
        # Panel-Hintergrund hinter dem Raster (etwas groesser als das Slot-Feld).
        pad = 6
        canvas.create_rectangle(
            ox - pad, oy - pad,
            ox + cols * px + pad, oy + rows * py + pad,
            fill='#0b0f14', outline='#3a3026', width=2)

        # Tab-Reihe I..IV aus den ECHTEN gebuendelten Templates blitten, damit
        # die Offen-Erkennung (inventory.open_probe) das Fake-Inventar als OFFEN
        # liest und der Scan nicht mit "nicht offen" abbricht. Soft: fehlt
        # PIL/ein Template, bleibt die Reihe weg (der Scan-Test skippt dann).
        try:
            import os as _os
            from PIL import Image as _PImage, ImageTk as _PImageTk
            from respath import resource_path as _res
            from inventory.constants import DEFAULT_CALIBRATION as _CAL
            from inventory.constants import PAGES as _PAGES
            from inventory.open_probe import (
                TAB_PATCH_BOX as _BOX, TEMPLATE_DIR as _TDIR,
                template_filename as _tname,
            )
            for _label in _PAGES:
                _cx, _cy = _CAL['tabs'][_label]
                _img = _PImage.open(_res(_os.path.join(
                    _TDIR, _tname(_label)))).convert('RGB')
                _photo = _PImageTk.PhotoImage(_img)
                photo_cache['tab_' + _label] = _photo
                canvas.create_image(int(_cx) + _BOX[0], int(_cy) + _BOX[2],
                                    image=_photo, anchor='nw')
        except Exception:
            pass

        name_to_path = _icon_name_to_path()
        # Eine kleine, deterministische Auswahl gut erkennbarer Items (Key-Items
        # zuerst, dann weitere, falls vorhanden), in die ersten Slots gelegt.
        from inventory.constants import KEY_ITEMS
        preferred = list(KEY_ITEMS) + sorted(
            n for n in name_to_path if n not in KEY_ITEMS)
        placed = [n for n in preferred if n in name_to_path]
        # TEST-Hilfe: ein gut erkennbares Item BEWUSST DOPPELT ablegen, damit man
        # die Mengen-Zaehlung im Management-Grid pruefen kann -- "Wels" (Catfish)
        # erscheint so ZWEIMAL und das Grid zeigt darauf nach dem Scan eine "2".
        if 'Catfish' in name_to_path:
            placed.insert(0, 'Catfish')

        idx = 0
        for r in range(rows):
            for c in range(cols):
                x0 = ox + c * px
                y0 = oy + r * py
                # Leeres Slot-Feld (dunkel) + dezenter Rahmen.
                canvas.create_rectangle(x0, y0, x0 + px, y0 + py,
                                        fill='#0a0d07', outline='#241d14')
                if idx < len(placed):
                    name = placed[idx]
                    photo = _load_icon_photo(name_to_path, photo_cache, name)
                    if photo is not None:
                        # NW-Anker: Icon deckt den 32x32-Slot exakt ab.
                        canvas.create_image(x0, y0, image=photo, anchor='nw')
                    else:
                        # Platzhalter (PIL/Datei fehlt): farbiges Kaestchen + Kuerzel.
                        col = _CELL_COLORS[idx % len(_CELL_COLORS)]
                        canvas.create_rectangle(x0 + 3, y0 + 3,
                                                x0 + px - 3, y0 + py - 3,
                                                fill=col, outline='')
                    idx += 1
    except Exception:
        pass


def _build_window(parent, kind='board'):
    """Baut das Toplevel + Inhalt auf. Interner Helfer, wirft nicht nach aussen.

    ``kind='board'`` -> farbiges Puzzle-Board (Default, Back-Compat).
    ``kind='inventory'`` -> komponiertes Inventar an der echten Inventar-Lage.
    """
    win = tk.Toplevel(parent) if parent is not None else tk.Toplevel()
    # Titel MUSS exakt der Spielname sein -> FindWindow(None, 'METIN2') trifft.
    win.title(constants.GAME_NAME)
    win.geometry('{}x{}'.format(WINDOW_SIZE[0], WINDOW_SIZE[1]))
    win.configure(bg=_BG)

    canvas = tk.Canvas(win, width=WINDOW_SIZE[0], height=WINDOW_SIZE[1],
                       highlightthickness=0, bg=_BG)
    canvas.pack(side='top', fill='both', expand=True)

    if kind == 'inventory':
        canvas.create_text(
            WINDOW_SIZE[0] // 2, 24,
            text="FAKE 'METIN2' inventory (test only) -- scan runs against this.",
            fill='#22c55e', font=('Segoe UI', 12, 'bold'))
        # PhotoImage-Referenzen am Fenster halten (sonst GC -> leere Slots).
        win._inv_photos = {}
        _draw_inventory(canvas, win._inv_photos)
    else:
        canvas.create_text(
            WINDOW_SIZE[0] // 2, 40,
            text="FAKE 'METIN2' window (test only) -- START runs against this.",
            fill='#22c55e', font=('Segoe UI', 13, 'bold'))
        _draw_board(canvas)
    return win


def open_test_window(parent=None, kind='board'):
    """Oeffnet das BOARD-Test-Fenster ``"METIN2"`` (800x600) und liefert es.

    Rueckwaerts-kompatibel: Default ``kind='board'`` ist SINGLE-Instance -- ist
    bereits ein Board-Fenster offen, wird dieses nach vorne geholt und
    zurueckgegeben (kein Duplikat). Fuer das mehrfenstrige INVENTAR-Fenster siehe
    :func:`open_inventory_test_window` (bzw. ``kind='inventory'`` delegiert dorthin).
    Liefert ``None`` ohne Display. Wirft nie.
    """
    if kind == 'inventory':
        return open_inventory_test_window(parent)

    global _open_window
    if tk is None:
        return None

    # Bereits offenes Board-Fenster wiederverwenden statt ein zweites zu spawnen.
    if _is_alive(_open_window):
        try:
            _open_window.deiconify()
            _open_window.lift()
        except Exception:
            pass
        return _open_window

    try:
        win = _build_window(parent, kind='board')
    except Exception:
        _open_window = None
        return None

    _open_window = win

    # Beim Schliessen die Modul-Referenz freigeben (sonst „lebt" sie scheinbar).
    def _on_close():
        global _open_window
        try:
            win.destroy()
        except Exception:
            pass
        _open_window = None

    try:
        win.protocol('WM_DELETE_WINDOW', _on_close)
    except Exception:
        pass

    _log_event('Test window opened', title=constants.GAME_NAME,
               size=WINDOW_SIZE)
    return win


def open_inventory_test_window(parent=None):
    """Oeffnet ein FAKE-„METIN2"-INVENTAR-Fenster (800x600); MEHRFENSTER (CS5).

    Jeder Aufruf oeffnet ein WEITERES Fenster (bis :data:`MAX_TEST_WINDOWS`), damit
    der Nutzer (a) den Inventar-Scanner gegen das gemalte Inventar und (b) den
    Mehrfenster-Picker (CS4) testen kann. Tote Eintraege werden vorher aufgeraeumt;
    ist das Maximum bereits offen, wird das zuletzt geoeffnete nach vorne geholt
    (statt ein drittes zu spawnen). Liefert ``None`` ohne Display / bei Fehler;
    wirft nie. Der Titel ist exakt ``constants.GAME_NAME``, sodass
    ``enumerate_game_windows`` jedes Fenster findet und ``FindWindow`` eines trifft.
    """
    global _open_windows
    if tk is None:
        return None

    alive = _prune_open_windows()
    if len(alive) >= MAX_TEST_WINDOWS:
        last = alive[-1]
        try:
            last.deiconify()
            last.lift()
        except Exception:
            pass
        return last

    try:
        win = _build_window(parent, kind='inventory')
    except Exception:
        return None

    _open_windows.append(win)

    def _on_close():
        try:
            win.destroy()
        except Exception:
            pass
        _prune_open_windows()

    try:
        win.protocol('WM_DELETE_WINDOW', _on_close)
    except Exception:
        pass

    _log_event('Inventory test window opened', title=constants.GAME_NAME,
               size=WINDOW_SIZE, count=len(_open_windows))
    return win
