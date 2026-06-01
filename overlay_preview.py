# -*- coding: utf-8 -*-
"""Read-only VORSCHAU-Overlay fuer die Puzzle-Board-Lage.

Anders als das interaktive Mark-Overlay (:mod:`overlay_mark`) wird hier NICHTS
gezogen oder bestaetigt: ein randloses, halbtransparentes, KLICK-DURCHLAESSIGES
Always-on-top-Fenster legt sich kurz (~5s) ueber Spiel/Desktop, HIGHLIGHTET das
Board-Rechteck + die 24 Rasterpunkte + die 4 Sonderpunkte an einem GEGEBENEN
Offset und schliesst sich dann selbst. So kann der Laie pruefen, ob

  * der Default-Offset (270, 227) zu seinem 800x600-Fenster passt, oder
  * die Auto-Erkennung das Board richtig getroffen hat.

Vertrag (vom UI ``interface/app.py`` konsumiert)::

    show_preview(offset, *, board_size=(260, 170), key_points=None,
                 alpha=0.85, duration_ms=5000, parent=None) -> bool

  * ``offset``      -- ``(x, y)`` der linken-oberen Board-Ecke IM Fensterinhalt
                       (gleiche Konvention wie detection.resolve_offset / puzzle.py).
  * ``board_size``  -- Referenz-Boardgroesse; bei (260, 170) sind alle Punkte
                       byte-identisch zur bewaehrten Geometrie.
  * ``key_points``  -- optionales Dict ``{name: (refx, refy)}`` mit 260x170-
                       REFERENZ-Overrides fuer die Sonderpunkte (z.B. aus einer
                       Mark-Kalibrierung). ``None`` -> geometry-Defaults.
  * ``alpha``       -- Deckkraft 0.4..1.0 (aus ``puzzle.overlay_opacity``),
                       defensiv geklemmt.
  * Rueckgabe ``True``, wenn das Overlay gezeigt wurde; ``False`` ohne GUI/Display.

Bewusst defensiv (gleiche Disziplin wie overlay_mark): Tk und der win32-Capture-
Stack werden WEICH importiert. Fehlt das Display, liefert die Funktion sauber
``False`` und das Modul bleibt importierbar/``py_compile``-bar (headless-Tests).
Das Klick-Durchlassen ist Best-Effort ueber die Win32-API; schlaegt es fehl,
zeigt das Overlay trotzdem und schliesst sich nach ``duration_ms`` von selbst --
der Nutzer kann nie "eingesperrt" werden.
"""

import geometry
import overlay_mark
from i18n import t

# Logging weich einbinden -- ein kaputter Logger darf das Overlay nie stoppen.
try:
    from debuglog import log
except Exception:  # pragma: no cover - reiner Fallback
    log = None

# Tk weich einbinden (kein Display unter WSL/Test -> ImportError moeglich).
try:
    import tkinter as tk
except Exception:  # pragma: no cover
    tk = None


# -- Konstanten ------------------------------------------------------------

DEFAULT_BOARD_SIZE = geometry.REF_SIZE          # (260, 170)
DEFAULT_DURATION_MS = 5000                      # ~5 Sekunden, dann Auto-Close
DEFAULT_ALPHA = 0.85

# Erlaubter Deckkraft-Bereich (deckt sich mit config.OVERLAY_OPACITY_MIN/MAX und
# overlay_mark.ALPHA_MIN/MAX). Lokal gehalten -> headless ohne interface.config.
ALPHA_MIN = 0.4
ALPHA_MAX = 1.0

# Radius der gezeichneten Rasterpunkte (wie overlay_mark.DOT_RADIUS).
DOT_RADIUS = 3
# Radius der groesseren Sonderpunkt-Marker.
KEYPOINT_RADIUS = 6

# Farben (deckungsgleich mit dem Mark-Overlay).
_BG = '#101418'
_TEAL = '#14b8a6'
_TEAL_LIGHT = '#2dd4bf'
_WHITE = '#f8fafc'

# Reihenfolge der 4 Sonderpunkte + ihre geometry-Accessor-Funktionen. So wird
# die Punkt-Arithmetik aus geometry wiederverwendet (eine Quelle der Wahrheit),
# statt sie hier zu duplizieren.
_KEYPOINT_ACCESSORS = (
    ('color',    geometry.color_sample),
    ('getpiece', geometry.get_piece_point),
    ('confirm',  geometry.confirm_point),
    ('cake',     geometry.cake_point),
)


# -- Logging-Helfer --------------------------------------------------------

def _log_event(message, **fields):
    if log is None:
        return
    try:
        log.event(0, message, **fields)
    except Exception:
        pass


def _log_error(message, exc=None):
    if log is None:
        return
    try:
        log.error(message, exc=exc)
    except Exception:
        pass


def _clamp_alpha(value):
    """Klemmt eine Deckkraft defensiv in [ALPHA_MIN, ALPHA_MAX].

    Nicht-numerische Eingabe -> ``DEFAULT_ALPHA``. Wirft nie.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return DEFAULT_ALPHA
    if number < ALPHA_MIN:
        return ALPHA_MIN
    if number > ALPHA_MAX:
        return ALPHA_MAX
    return number


def _safe_offset(offset):
    """Wandelt ``offset`` defensiv in ``(int, int)`` oder ``None``."""
    try:
        return (int(offset[0]), int(offset[1]))
    except Exception:
        return None


def _safe_size(board_size):
    """Wandelt ``board_size`` in ein positives ``(int, int)`` oder den Default."""
    try:
        w = int(board_size[0])
        h = int(board_size[1])
        if w > 0 and h > 0:
            return (w, h)
    except Exception:
        pass
    return DEFAULT_BOARD_SIZE


def _make_click_through(top):
    """Macht ``top`` unter Windows klick-durchlaessig (Best-Effort).

    Setzt ``WS_EX_LAYERED | WS_EX_TRANSPARENT`` ueber die Win32-API, damit Maus-
    Klicks durch das Overlay an Spiel/Desktop durchgehen. Schlaegt das fehl
    (Nicht-Windows, fehlendes ctypes), bleibt das Overlay sichtbar und schliesst
    sich trotzdem per Timer -- der Nutzer wird nie "eingesperrt". Wirft nie.
    """
    try:
        import ctypes
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020
        hwnd = top.winfo_id()
        user32 = ctypes.windll.user32
        styles = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(
            hwnd, GWL_EXSTYLE,
            styles | WS_EX_LAYERED | WS_EX_TRANSPARENT)
        return True
    except Exception:
        return False


def _resolve_origin():
    """Bildschirmursprung des Spiel-Fensterinhalts ``(ox, oy)`` oder ``(0, 0)``.

    Nutzt denselben Pfad wie das Mark-Overlay (overlay_mark.window_origin). Fehlt
    das Fenster/der Capture-Stack, wird an ROH-Koordinaten gezeichnet (Default-
    Vorschau bleibt so auch vor dem Spielstart nuetzlich) + ein Log-Hinweis.
    """
    try:
        origin = overlay_mark.window_origin()
    except Exception:
        origin = None
    if origin is None:
        _log_event(t('preview.no_window_origin'))
        return (0, 0)
    try:
        return (int(origin[0]), int(origin[1]))
    except Exception:
        return (0, 0)


def _keypoint_refs(key_points):
    """Baut ein Dict ``{name: ref|None}`` aus optionalen REF-Overrides.

    Unbekannte Namen werden ignoriert; nur die 4 bekannten Sonderpunkte sind
    relevant. Ein fehlender/kaputter Override -> ``None`` (geometry-Default).
    """
    refs = {name: None for name, _fn in _KEYPOINT_ACCESSORS}
    if not isinstance(key_points, dict):
        return refs
    for name, _fn in _KEYPOINT_ACCESSORS:
        value = key_points.get(name)
        if value is None:
            continue
        try:
            refs[name] = (float(value[0]), float(value[1]))
        except Exception:
            refs[name] = None
    return refs


def _draw(canvas, base_x, base_y, board_size, key_points):
    """Zeichnet Board-Rechteck, 24 Rasterpunkte und 4 Sonderpunkte.

    ``base_x/base_y`` = Bildschirm-Position der linken-oberen Board-Ecke
    (= origin + offset). Alle geometry-Punkte sind board-relativ und werden
    dorthin verschoben. Wirft nie (eine kaputte Zeichnung darf das Auto-Close
    nicht verhindern).
    """
    try:
        board_w, board_h = board_size

        # Board-Rechteck zur Orientierung.
        canvas.create_rectangle(
            base_x, base_y, base_x + board_w, base_y + board_h,
            outline=_TEAL, width=2)

        # 24 Rasterpunkte (board-relativ -> verschoben).
        for px, py in geometry.grid_points(board_size):
            cx = base_x + px
            cy = base_y + py
            canvas.create_oval(
                cx - DOT_RADIUS, cy - DOT_RADIUS,
                cx + DOT_RADIUS, cy + DOT_RADIUS,
                fill=_TEAL_LIGHT, outline=_WHITE)

        # 4 Sonderpunkte -- Position aus geometry (mit optionalem ref-Override),
        # Label/Farbe aus overlay_mark.KEYPOINT_STYLE (eine Quelle der Wahrheit).
        refs = _keypoint_refs(key_points)
        styles = overlay_mark.KEYPOINT_STYLE
        for name, accessor in _KEYPOINT_ACCESSORS:
            kx, ky = accessor(board_size, ref=refs[name])
            sx = base_x + kx
            sy = base_y + ky
            label, color = styles.get(name, (name, _TEAL))
            canvas.create_oval(
                sx - KEYPOINT_RADIUS, sy - KEYPOINT_RADIUS,
                sx + KEYPOINT_RADIUS, sy + KEYPOINT_RADIUS,
                fill=color, outline=_WHITE, width=2)
            canvas.create_text(
                sx, sy - KEYPOINT_RADIUS - 8, text=label,
                fill=color, font=('Segoe UI', 8, 'bold'))

        # Hinweis-Bildunterschrift mittig ueber dem Board.
        canvas.create_text(
            base_x + board_w // 2, base_y - 14,
            text=t('preview.caption'),
            fill=_WHITE, font=('Segoe UI', 10, 'bold'))
    except Exception as exc:
        _log_error(t('preview.unavailable'), exc=exc)


def show_preview(offset, *, board_size=DEFAULT_BOARD_SIZE, key_points=None,
                 alpha=DEFAULT_ALPHA, duration_ms=DEFAULT_DURATION_MS,
                 parent=None):
    """Zeigt das read-only Vorschau-Overlay fuer ~``duration_ms`` ms.

    Siehe Modul-Docstring fuer den vollstaendigen Vertrag. Liefert ``True``,
    wenn das Overlay gezeigt wurde, sonst ``False`` (kein Display). Wirft nie.

    Im Gegensatz zum Mark-Overlay ist dieses Fenster NICHT modal (kein
    ``grab_set``/``wait_window``): die App laeuft weiter und das Overlay schliesst
    sich selbst per ``after(duration_ms, destroy)``.
    """
    if tk is None:
        _log_event(t('preview.unavailable'))
        return False

    off = _safe_offset(offset)
    if off is None:
        _log_event(t('preview.unavailable'))
        return False
    size = _safe_size(board_size)
    clamped_alpha = _clamp_alpha(alpha)
    try:
        duration = int(duration_ms)
        if duration <= 0:
            duration = DEFAULT_DURATION_MS
    except Exception:
        duration = DEFAULT_DURATION_MS

    created_root = False
    root = parent
    try:
        if root is None:
            try:
                root = tk._get_default_root()
            except Exception:
                root = None
            if root is None:
                root = tk.Tk()
                root.withdraw()
                created_root = True

        ox, oy = _resolve_origin()
        base_x = ox + off[0]
        base_y = oy + off[1]

        top = tk.Toplevel(root)
        top.overrideredirect(True)
        top.attributes('-topmost', True)
        try:
            top.attributes('-alpha', clamped_alpha)
        except Exception:
            pass

        screen_w = top.winfo_screenwidth()
        screen_h = top.winfo_screenheight()
        top.geometry('{}x{}+0+0'.format(screen_w, screen_h))

        canvas = tk.Canvas(top, width=screen_w, height=screen_h,
                           highlightthickness=0, bg=_BG)
        canvas.pack(side='top', fill='both', expand=True)

        # Erst nach update_idletasks ist ein gueltiges HWND fuer das Klick-
        # Durchlassen verfuegbar.
        try:
            top.update_idletasks()
        except Exception:
            pass
        _make_click_through(top)

        _draw(canvas, base_x, base_y, size, key_points)

        # Auto-Close: schliesst das Overlay nach der Anzeigedauer. Wenn ein
        # eigener Root erzeugt wurde, raeumen wir diesen danach ebenfalls ab.
        def _close():
            try:
                top.destroy()
            except Exception:
                pass
            if created_root and root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass

        top.after(duration, _close)
        _log_event(t('preview.caption'), offset=off, size=size,
                   alpha=round(clamped_alpha, 2))
        return True
    except Exception as exc:
        _log_error(t('preview.unavailable'), exc=exc)
        if created_root and root is not None:
            try:
                root.destroy()
            except Exception:
                pass
        return False
