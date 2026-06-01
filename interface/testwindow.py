# -*- coding: utf-8 -*-
"""Selbst-enthaltenes Test-Fenster mit Titel ``"METIN2"`` (800x600).

Ersetzt das externe Wegwerf-Skript ``_fake_metin2.py``: spawnt ein Tk-Toplevel,
dessen Titel EXAKT der Spielname (:data:`constants.GAME_NAME`) ist, damit
``win32gui.FindWindow(None, 'METIN2')`` es findet und START tatsaechlich laeuft,
OHNE das echte Spiel. So lassen sich Capture, Farb- und Board-Erkennung trocken
ueben.

Das Fenster zeigt zur Auflockerung ein farbiges 6x4-„Board" an genau der Stelle
(Inhalt-Offset ``(270, 227)``, Groesse ``260x170``), die die Default-Vorschau
(:mod:`overlay_preview`) hervorhebt -- so deckt sich das Test-Board mit der
erwarteten Default-Board-Lage und Farb-/Erkennungslogik bekommt echte Pixel.

Vertrag (vom UI ``interface/app.py`` konsumiert)::

    open_test_window(parent=None) -> tk.Toplevel | None

  * ``parent`` -- die App-Root (die App besitzt den Tk-Root; hier wird KEIN
    zweites ``tk.Tk()`` erzeugt). ``None`` ist erlaubt (eigenstaendiger Start).
  * Rueckgabe: das erzeugte (oder noch lebende) Toplevel, oder ``None`` ohne
    Display. Wirft nie.

Bewusst defensiv (gleiche Disziplin wie overlay_mark/overlay_preview): Tk wird
WEICH importiert; fehlt das Display, liefert die Funktion sauber ``None`` und
das Modul bleibt importierbar/``py_compile``-bar (headless-Tests).
"""

import constants

# Tk weich einbinden (kein Display unter WSL/Test -> ImportError moeglich).
try:
    import tkinter as tk
except Exception:  # pragma: no cover
    tk = None

# Logging weich einbinden -- ein kaputter Logger darf das Fenster nie stoppen.
try:
    from debuglog import log
except Exception:  # pragma: no cover - reiner Fallback
    log = None


# -- Konstanten ------------------------------------------------------------

WINDOW_SIZE = (800, 600)

# Lage/Groesse des farbigen Test-Boards IM Fensterinhalt -- deckt sich mit
# PuzzleBot.PUZZLE_WINDOW_POSITION/SIZE bzw. overlay_preview-Default.
BOARD_OFFSET = (270, 227)
BOARD_SIZE = (260, 170)
BOARD_COLS = 6
BOARD_ROWS = 4

_BG = '#101820'
_BOARD_BG = '#0b0f14'

# Lebhafte, gut unterscheidbare Zellfarben (zyklisch ueber die 24 Zellen).
_CELL_COLORS = (
    '#ef4444', '#f59e0b', '#eab308', '#22c55e', '#14b8a6', '#3b82f6',
    '#8b5cf6', '#ec4899', '#f97316', '#84cc16', '#06b6d4', '#a855f7',
)

# Modul-weite Referenz auf das aktuell offene Fenster (Duplikat-Schutz).
_open_window = None


def _log_event(message, **fields):
    if log is None:
        return
    try:
        log.event(0, message, **fields)
    except Exception:
        pass


def _is_alive(win):
    """``True``, wenn ``win`` noch ein lebendes Tk-Fenster ist. Wirft nie."""
    if win is None:
        return False
    try:
        return bool(win.winfo_exists())
    except Exception:
        return False


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


def _build_window(parent):
    """Baut das Toplevel + Inhalt auf. Interner Helfer, wirft nicht nach aussen."""
    win = tk.Toplevel(parent) if parent is not None else tk.Toplevel()
    # Titel MUSS exakt der Spielname sein -> FindWindow(None, 'METIN2') trifft.
    win.title(constants.GAME_NAME)
    win.geometry('{}x{}'.format(WINDOW_SIZE[0], WINDOW_SIZE[1]))
    win.configure(bg=_BG)

    canvas = tk.Canvas(win, width=WINDOW_SIZE[0], height=WINDOW_SIZE[1],
                       highlightthickness=0, bg=_BG)
    canvas.pack(side='top', fill='both', expand=True)

    # Kurzer Hinweistext oben.
    canvas.create_text(
        WINDOW_SIZE[0] // 2, 40,
        text="FAKE 'METIN2' window (test only) -- START runs against this.",
        fill='#22c55e', font=('Segoe UI', 13, 'bold'))

    _draw_board(canvas)
    return win


def open_test_window(parent=None):
    """Oeffnet das Test-Fenster ``"METIN2"`` (800x600) und liefert das Toplevel.

    Ist bereits ein Test-Fenster offen, wird dieses nach vorne geholt und
    zurueckgegeben (kein Duplikat). Liefert ``None``, wenn kein Display
    verfuegbar ist. Wirft nie.
    """
    global _open_window
    if tk is None:
        return None

    # Bereits offenes Fenster wiederverwenden statt ein zweites zu spawnen.
    if _is_alive(_open_window):
        try:
            _open_window.deiconify()
            _open_window.lift()
        except Exception:
            pass
        return _open_window

    try:
        win = _build_window(parent)
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
