"""Reine Koordinaten-Mathematik + Konstanten fuer das Mark-Overlay (KEIN Tk).

Abgespaltene, toolkit-freie Schicht von :mod:`overlay_mark`. Enthaelt die
Modell-Arithmetik (Griffe -> Board-Crop, Sonderpunkt -> 260x170-Referenz), den
Ergebnis-Typ :class:`MarkResult`, die Konstanten/Stil-Tabellen sowie den
Fensterursprung-Helfer und den Ergebnis-Builder.

Bewusst ohne ``tkinter``/``customtkinter`` -- damit dieser Teil headless
importier- und testbar bleibt (``py.exe -c "import overlay_geometry"``). Die
eigentliche Tk-Overlay-Schicht (``_MarkOverlay`` + ``pick_offset_interactive``)
lebt weiter in :mod:`overlay_mark` und re-exportiert die hiesigen Namen, sodass
``overlay_mark.X`` -- inkl. ``overlay_mark.window_origin`` /
``overlay_mark.KEYPOINT_STYLE`` (von ``overlay_preview`` genutzt) -- unveraendert
aufgeht.

Koordinaten-Modell (siehe ``geometry.crop_from_grid_corners`` /
``geometry.pixel_to_ref``; hier nur aufgerufen, nicht dupliziert -- mit
defensivem Inline-Fallback, falls ``geometry`` die Helfer noch nicht hat):

    SPAN_X = 160 (= GRID_STEP*5),  SPAN_Y = 96 (= GRID_STEP*3)
    scaleX = (gridBR.x - gridTL.x) / 160 ;  scaleY = (gridBR.y - gridTL.y) / 96
    cropOffset = (round(gridTL.x - 15*scaleX), round(gridTL.y - 15*scaleY))
    cropSize   = (round(260*scaleX),          round(170*scaleY))
    refX = 15 + (p.x-gridTL.x)/(gridBR.x-gridTL.x) * 160   (Sonderpunkt -> Referenz)
    refY = 15 + (p.y-gridTL.y)/(gridBR.y-gridTL.y) * 96
"""

import calibration
import geometry
from i18n import t

# Logging weich einbinden -- ein kaputter Logger darf das Overlay nie stoppen.
try:
    from debuglog import log
except Exception:  # pragma: no cover - reiner Fallback
    log = None


# -- Konstanten ------------------------------------------------------------

DEFAULT_OFFSET = (270, 227)
BOARD_SIZE = calibration.DEFAULT_EXPECTED_SIZE          # (260, 170)
REFERENCE_IMAGE = 'images/calibration_reference.png'    # Vorlage fuer die Punkte

# Transparenz des Overlays (0..1). Deckender als frueher (0.45 war zu durch-
# sichtig), aber noch genug Durchblick fuer pixelgenaues Platzieren. Dient nur
# als Modul-Default; der konkrete Wert kommt zur Laufzeit aus der Config
# (puzzle.overlay_opacity) und wird an pick_offset_interactive(alpha=..) gereicht.
OVERLAY_ALPHA = 0.85
# Halber Kantenmass der quadratischen Griff-Anfasser (in Bildschirm-Pixeln).
HANDLE_HALF = 7
# Radius der gezeichneten Raster-Vorschau-Punkte.
DOT_RADIUS = 3

# Erlaubter Deckkraft-Bereich (deckt sich mit config.OVERLAY_OPACITY_MIN/MAX).
# Hier bewusst lokal gehalten, damit overlay_mark headless ohne interface.config
# importierbar bleibt.
ALPHA_MIN = 0.4
ALPHA_MAX = 1.0


def _clamp_alpha(value):
    """Klemmt eine Deckkraft defensiv in [ALPHA_MIN, ALPHA_MAX].

    Nicht-numerische Eingabe -> Modul-Default ``OVERLAY_ALPHA``. Wirft nie, damit
    ein kaputter Config-Wert das Overlay nie blockiert.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return OVERLAY_ALPHA
    if number < ALPHA_MIN:
        return ALPHA_MIN
    if number > ALPHA_MAX:
        return ALPHA_MAX
    return number

# Reihenfolge/Namen der 4 Sonderpunkte (deckt sich mit config.KEYPOINT_KEYS).
KEYPOINT_KEYS = ('color', 'getpiece', 'confirm', 'cake')

# Kurze, gut lesbare Labels + Farben fuer die Sonderpunkt-Marker.
_KEYPOINT_STYLE = {
    'color':    ('Color',   '#f59e0b'),   # Amber
    'getpiece': ('Piece',   '#3b82f6'),   # Blue
    'confirm':  ('OK',      '#22c55e'),   # Green
    'cake':     ('Cake',    '#ec4899'),   # Pink
}

# Oeffentlicher Alias: damit overlay_preview.py die Sonderpunkt-Stile (Label +
# Farbe) aus EINER Quelle wiederverwendet, statt sie zu duplizieren.
KEYPOINT_STYLE = _KEYPOINT_STYLE

# REF-Koordinaten der Sonderpunkte (Default-Startlage relativ zum Raster).
# Aus geometry, mit defensivem Fallback auf die bekannten Konstanten.
_REF_KEYPOINTS = {
    'color':    getattr(geometry, 'REF_COLOR_SAMPLE', (110, 150)),
    'getpiece': getattr(geometry, 'REF_GET_PIECE', (230, 85)),
    'confirm':  getattr(geometry, 'REF_CONFIRM', (100, 90)),
    'cake':     getattr(geometry, 'REF_CAKE', (120, 90)),
}


# -- Modell-Arithmetik (Aufruf von geometry, mit Inline-Fallback) ----------
#
# Die Mathe gehoert laut Blueprint in geometry (headless-getestet bei Engineer
# A). Da geometry diese Helfer evtl. noch nicht enthaelt (additiver Umbau),
# rufen wir sie wenn vorhanden auf und nutzen sonst die IDENTISCHEN Formeln
# inline -- so bleibt das Overlay funktionsfaehig und das Ergebnis byte-gleich.

_SPAN_X = getattr(geometry, 'SPAN_X', geometry.GRID_STEP * (geometry.GRID_COLS - 1))
_SPAN_Y = getattr(geometry, 'SPAN_Y', geometry.GRID_STEP * (geometry.GRID_ROWS - 1))


def _crop_from_grid_corners(grid_tl, grid_br):
    """``(gridTL, gridBR)`` -> ``(offset, size)`` oder ``None`` bei Null-Span.

    Delegiert an :func:`geometry.crop_from_grid_corners`, falls vorhanden;
    sonst identische Inline-Arithmetik.
    """
    fn = getattr(geometry, 'crop_from_grid_corners', None)
    if fn is not None:
        return fn(grid_tl, grid_br)
    span_x = grid_br[0] - grid_tl[0]
    span_y = grid_br[1] - grid_tl[1]
    if span_x <= 0 or span_y <= 0:
        return None
    scale_x = span_x / _SPAN_X
    scale_y = span_y / _SPAN_Y
    origin = geometry.GRID_ORIGIN
    ref_w, ref_h = geometry.REF_SIZE
    offset = (int(round(grid_tl[0] - origin * scale_x)),
              int(round(grid_tl[1] - origin * scale_y)))
    size = (int(round(ref_w * scale_x)), int(round(ref_h * scale_y)))
    return (offset, size)


def _pixel_to_ref(point, grid_tl, grid_br):
    """Sonderpunkt ``point`` -> 260x170-REF-Koordinate oder ``None``.

    Delegiert an :func:`geometry.pixel_to_ref`, falls vorhanden; sonst
    identische Inline-Arithmetik.
    """
    fn = getattr(geometry, 'pixel_to_ref', None)
    if fn is not None:
        return fn(point, grid_tl, grid_br)
    span_x = grid_br[0] - grid_tl[0]
    span_y = grid_br[1] - grid_tl[1]
    if span_x <= 0 or span_y <= 0:
        return None
    origin = geometry.GRID_ORIGIN
    rel_x = (point[0] - grid_tl[0]) / span_x
    rel_y = (point[1] - grid_tl[1]) / span_y
    return (origin + rel_x * _SPAN_X, origin + rel_y * _SPAN_Y)


# -- Ergebnis-Typ ----------------------------------------------------------

class MarkResult(dict):
    """Mark-Ergebnis als ``dict`` mit rueckwaerts-kompatiblem Index-Zugriff.

    Enthaelt die Schluessel ``'offset'``, ``'size'`` und ``'key_points'``.
    Zusaetzlich liefern ``result[0]`` / ``result[1]`` die Offset-Komponenten und
    ``len(result) == 2``, damit ein noch nicht migrierter Aufrufer, der wie
    frueher das Offset-Tupel erwartet (``int(offset[0])``), unveraendert
    funktioniert. Ueber String-Schluessel verhaelt es sich wie ein normales
    Dict.
    """

    __slots__ = ()

    def __getitem__(self, key):
        if key == 0:
            return dict.__getitem__(self, 'offset')[0]
        if key == 1:
            return dict.__getitem__(self, 'offset')[1]
        return dict.__getitem__(self, key)

    def __len__(self):
        # Legacy-Konsumenten interpretieren das Ergebnis als 2er-Offset-Tupel.
        return 2

    def __iter__(self):
        # Iteration liefert die Offset-Komponenten (Tupel-Semantik), damit
        # ``x, y = result`` weiterhin funktioniert.
        offset = dict.__getitem__(self, 'offset')
        yield offset[0]
        yield offset[1]


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


def _window_origin():
    """Liefert den Bildschirmursprung des Spiel-Fensterinhalts ``(ox, oy)``.

    Nutzt denselben oeffentlichen Weg wie der Rest des Codes
    (``WindowCapture.offset_x/offset_y``). Gibt ``None`` zurueck, wenn der
    Capture-/win32-Stack fehlt oder das Fenster nicht gefunden wird -- der
    Aufrufer faellt dann auf die rohe Screen-Koordinate zurueck.
    """
    try:
        import constants
        from windowcapture import WindowCapture
        wincap = WindowCapture(constants.GAME_NAME)
        return (int(wincap.offset_x), int(wincap.offset_y))
    except Exception as exc:
        _log_error(t('mark.window_origin_unavailable'), exc=exc)
        return None


def window_origin():
    """Oeffentlicher Wrapper um :func:`_window_origin`.

    Liefert den Bildschirmursprung des Spiel-Fensterinhalts ``(ox, oy)`` oder
    ``None``, wenn das Fenster/der Capture-Stack fehlt. Damit
    :mod:`overlay_preview` den GLEICHEN Ursprung-Pfad wie das Mark-Overlay nutzt
    (eine Quelle der Wahrheit), ohne auf das private ``_window_origin``
    zuzugreifen.
    """
    return _window_origin()


def _default_grid_corners(default_offset):
    """Default-Bildschirmlage der beiden Raster-Eckgriffe.

    ``gridTL`` = Mitte Zelle (0,0), ``gridBR`` = Mitte Zelle (3,5), bezogen auf
    ``default_offset`` als Fensterinhalt-Offset und die 15+32-Referenz. Liefert
    Bildschirmnahe Startpunkte (Default ist nur ein sinnvoller Startpunkt nahe
    der ueblichen Board-Lage).
    """
    ox, oy = default_offset
    tl_ref = geometry.cell_ref(0, 0)                       # (15, 15)
    br_ref = geometry.cell_ref(geometry.GRID_ROWS - 1, geometry.GRID_COLS - 1)
    grid_tl = (ox + tl_ref[0], oy + tl_ref[1])
    grid_br = (ox + br_ref[0], oy + br_ref[1])
    return grid_tl, grid_br


def _build_result(screen_state):
    """Baut aus den Bildschirm-Griffen das Ergebnis-Dict (Fensterinhalt).

    Uebersetzt die Griffe via :func:`_window_origin` in Fensterinhalt-
    Koordinaten und leitet ``offset``/``size`` sowie die normierten Keypoints
    ab. Liefert ``None`` bei degenerierter Markierung (Null-Span).
    """
    grid_tl = screen_state['grid_tl']
    grid_br = screen_state['grid_br']

    origin = _window_origin()
    if origin is None:
        _log_event(t('mark.no_window_origin'))
        ox, oy = 0, 0
    else:
        ox, oy = origin

    content_tl = (grid_tl[0] - ox, grid_tl[1] - oy)
    content_br = (grid_br[0] - ox, grid_br[1] - oy)

    crop = _crop_from_grid_corners(content_tl, content_br)
    if crop is None:
        _log_error(t('mark.degenerate_marking'))
        return None
    offset, size = crop

    key_points = {}
    for key, screen_pt in screen_state['key_points'].items():
        content_pt = (screen_pt[0] - ox, screen_pt[1] - oy)
        ref = _pixel_to_ref(content_pt, content_tl, content_br)
        if ref is not None:
            key_points[key] = ref

    result = MarkResult()
    result['offset'] = (int(offset[0]), int(offset[1]))
    result['size'] = (int(size[0]), int(size[1]))
    result['key_points'] = key_points
    _log_event(t('mark.overlay_result'), offset=result['offset'],
               size=result['size'], keypoints=list(key_points.keys()),
               origin=origin)
    return result


__all__ = [
    'DEFAULT_OFFSET', 'BOARD_SIZE', 'REFERENCE_IMAGE', 'OVERLAY_ALPHA',
    'HANDLE_HALF', 'DOT_RADIUS', 'ALPHA_MIN', 'ALPHA_MAX',
    'KEYPOINT_KEYS', 'KEYPOINT_STYLE', 'MarkResult',
    '_clamp_alpha', '_KEYPOINT_STYLE', '_REF_KEYPOINTS', '_SPAN_X', '_SPAN_Y',
    '_crop_from_grid_corners', '_pixel_to_ref', '_default_grid_corners',
    '_window_origin', 'window_origin', '_build_result',
    '_log_event', '_log_error', 'log',
]
