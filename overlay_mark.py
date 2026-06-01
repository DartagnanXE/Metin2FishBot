"""Resizable Mark-Overlay zum KALIBRIEREN des Puzzle-Boards.

Oeffnet ein transparentes, IMMER-VORNE Fenster ueber dem Spiel. Der Nutzer
zieht die **Raster-Bounding-Box** der 24 Zellmitten per 2 Eck-Griffen auf:

  * ``gridTL`` = Mitte der Zelle ``(0, 0)`` (oben-links),
  * ``gridBR`` = Mitte der Zelle ``(3, 5)`` (unten-rechts).

Zusaetzlich koennen die 4 **Sonderpunkte** (``color`` / ``getpiece`` /
``confirm`` / ``cake``) einzeln gezogen werden, um die geometry-Defaults zu
ueberschreiben. Aus ``gridTL``/``gridBR`` wird der fuer ``puzzle.py`` noetige
Board-CROP (``offset`` + ``size``) abgeleitet -- KONSISTENT zum 15+32-in-260-
Modell von ``geometry`` -- und die Sonderpunkte werden auf 260x170-REFERENZ-
Koordinaten normiert (aufloesungsunabhaengig).

Vertrag (FROZEN, vom UI ``interface/app.py`` konsumiert):

    pick_offset_interactive(default_offset=(270, 227),
                            board_size=(260, 170)) -> dict | None

  * Rueckgabe ist ein Dict (genauer: :class:`MarkResult`, eine ``dict``-
    Unterklasse)::

        {
            'offset':     (x, y),   # Fensterinhalt-Offset (int)
            'size':       (w, h),   # int-Paar
            'key_points': {         # 0..4 Eintraege, REF-Koords (float) auf 260x170
                'color': (rx, ry), 'getpiece': ..., 'confirm': ..., 'cake': ...
            },
        }

  * ``None`` bei Abbruch ODER wenn keine GUI/kein Display verfuegbar ist
    (headless). Wirft nie.

Rueckwaerts-Kompatibilitaet: :class:`MarkResult` unterstuetzt zusaetzlich die
Index-Zugriffe ``result[0]`` / ``result[1]`` (== ``offset[0]`` / ``offset[1]``)
und ``len(result) == 2``, damit ein noch nicht migrierter Aufrufer, der wie
frueher ``int(offset[0])`` erwartet, NICHT bricht. Der saubere Weg ist
``result['offset']`` / ``result['size']`` / ``result['key_points']``.

Koordinaten-Modell (siehe ``geometry.crop_from_grid_corners`` /
``geometry.pixel_to_ref``; hier nur aufgerufen, nicht dupliziert -- mit
defensivem Inline-Fallback, falls ``geometry`` die Helfer noch nicht hat):

    SPAN_X = 160 (= GRID_STEP*5),  SPAN_Y = 96 (= GRID_STEP*3)
    scaleX = (gridBR.x - gridTL.x) / 160 ;  scaleY = (gridBR.y - gridTL.y) / 96
    cropOffset = (round(gridTL.x - 15*scaleX), round(gridTL.y - 15*scaleY))
    cropSize   = (round(260*scaleX),          round(170*scaleY))
    refX = 15 + (p.x-gridTL.x)/(gridBR.x-gridTL.x) * 160   (Sonderpunkt -> Referenz)
    refY = 15 + (p.y-gridTL.y)/(gridBR.y-gridTL.y) * 96

Bei Default-Markierung (Griffe auf die Default-Zellmitten) ist ``scale == 1``
-> ``offset == (270, 227)``, ``size == (260, 170)`` und KEINE Keypoint-Overrides
-> byte-stabil zum bisherigen Verhalten.

Bewusst defensiv: Tk/CTk und der win32-Capture-Stack werden WEICH importiert.
Fehlt das Display/Tk, liefert die Funktion sauber ``None`` und das Modul bleibt
importierbar/``py_compile``-bar (passt zur headless-Testdisziplin des Projekts).
Degenerierte Eingabe (``gridBR <= gridTL``, Division durch ~0) wird verworfen
-> ``None``.
"""

import calibration
import geometry
from i18n import t
from respath import resource_path

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

# CustomTkinter optional bevorzugen (modernes Aussehen der Buttons). Das Overlay
# selbst bleibt ein klassischer Tk-Toplevel (overrideredirect/-alpha verhalten
# sich dort am verlaesslichsten); CTk liefert nur huebschere Buttons.
try:
    import customtkinter as ctk
except Exception:  # pragma: no cover
    ctk = None


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


class _MarkOverlay:
    """Interner Zustandshalter fuer das resizable Markier-Overlay.

    Kapselt Tk-Aufbau, die unabhaengige Drag-Logik der Griffe und das Ergebnis,
    damit ``pick_offset_interactive`` schlank bleibt. Nach ``run()`` steht in
    ``self.result`` ein Dict ``{'grid_tl', 'grid_br', 'key_points'}`` mit
    Bildschirm-Koordinaten -- oder ``None`` bei Abbruch.

    Das Overlay ist ein randloses Vollflaechen-Fenster (deckt den ganzen
    Bildschirm), auf dem die Griffe frei liegen. So kann der Nutzer die
    Raster-Bbox beliebig gross/klein und an beliebiger Stelle aufziehen
    (resizable), ohne das Fenster selbst zu skalieren.
    """

    def __init__(self, parent, default_offset, board_size, alpha=OVERLAY_ALPHA):
        self.result = None
        self.board_w, self.board_h = board_size

        grid_tl, grid_br = _default_grid_corners(self._safe_offset(default_offset))

        # Bildschirmgroesse bestimmen, um ein vollflaechiges Overlay aufzuspannen.
        self.top = tk.Toplevel(parent) if parent is not None else tk.Toplevel()
        self.top.overrideredirect(True)
        self.top.attributes('-topmost', True)
        try:
            self.top.attributes('-alpha', _clamp_alpha(alpha))
        except Exception:
            pass

        screen_w = self.top.winfo_screenwidth()
        screen_h = self.top.winfo_screenheight()
        self._screen_w = screen_w
        self._screen_h = screen_h
        self.top.geometry('{}x{}+0+0'.format(screen_w, screen_h))

        self.canvas = tk.Canvas(self.top, width=screen_w, height=screen_h,
                                highlightthickness=0, bg='#101418',
                                cursor='crosshair')
        self.canvas.pack(side='top', fill='both', expand=True)

        # Zieh-Zustand: aktuell gegriffenes Handle + Maus-Versatz.
        self._active = None         # ('grid', 'tl'|'br') | ('kp', <name>) | None
        self._grab_dx = 0
        self._grab_dy = 0

        # Griff-Positionen (Bildschirm-Koordinaten, mutable Listen [x, y]).
        self._grid = {'tl': list(grid_tl), 'br': list(grid_br)}

        # Sonderpunkte: per Default an ihrer REF-Lage relativ zum Raster
        # vorbelegt, aber initial DEAKTIVIERT (kein Override). Erst ein Klick
        # auf die Checkbox / ein Doppelklick aktiviert + zieht sie heran.
        self._kp_enabled = {k: False for k in KEYPOINT_KEYS}
        self._kp = {k: list(self._ref_to_screen(_REF_KEYPOINTS[k]))
                    for k in KEYPOINT_KEYS}

        self._load_reference()
        self._build_buttons()
        self._redraw()

        self.canvas.bind('<ButtonPress-1>', self._on_press)
        self.canvas.bind('<B1-Motion>', self._on_drag)
        self.canvas.bind('<ButtonRelease-1>', self._on_release)
        self.top.bind('<Escape>', lambda _e: self._cancel())
        self.top.bind('<Return>', lambda _e: self._confirm())

    # -- Aufbau --------------------------------------------------------

    @staticmethod
    def _safe_offset(default_offset):
        try:
            return int(default_offset[0]), int(default_offset[1])
        except Exception:
            return DEFAULT_OFFSET

    def _ref_to_screen(self, ref_point):
        """REF-Koordinate (260x170) -> Bildschirm-Punkt anhand AKTUELLER Griffe."""
        grid_tl = self._grid['tl']
        grid_br = self._grid['br']
        span_x = grid_br[0] - grid_tl[0]
        span_y = grid_br[1] - grid_tl[1]
        origin = geometry.GRID_ORIGIN
        # Robust gegen Null-Span: faellt auf gridTL zurueck.
        if _SPAN_X == 0 or _SPAN_Y == 0:
            return (grid_tl[0], grid_tl[1])
        rel_x = (ref_point[0] - origin) / _SPAN_X
        rel_y = (ref_point[1] - origin) / _SPAN_Y
        return (grid_tl[0] + rel_x * span_x, grid_tl[1] + rel_y * span_y)

    def _build_buttons(self):
        """Bedienleiste: Confirm/Cancel + 4 Sonderpunkt-Umschalter."""
        bar_bg = '#101418'
        if ctk is not None:
            bar = ctk.CTkFrame(self.top, fg_color=bar_bg, corner_radius=0)
            bar.place(relx=0.5, rely=0.02, anchor='n')
            self._kp_vars = {}
            for key in KEYPOINT_KEYS:
                var = ctk.BooleanVar(value=False)
                self._kp_vars[key] = var
                ctk.CTkCheckBox(
                    bar, text=t('mark.kp_' + key), variable=var,
                    command=lambda k=key: self._toggle_keypoint(k),
                    width=70).pack(side='left', padx=4, pady=4)
            ctk.CTkButton(bar, text=t('mark.btn_confirm'), width=110, height=26,
                          fg_color='#14b8a6', hover_color='#0d9488',
                          command=self._confirm).pack(side='left', padx=6,
                                                       pady=4)
            ctk.CTkButton(bar, text=t('mark.btn_cancel'), width=90, height=26,
                          fg_color='#374151', hover_color='#4b5563',
                          command=self._cancel).pack(side='left', padx=6,
                                                     pady=4)
        else:
            bar = tk.Frame(self.top, bg=bar_bg)
            bar.place(relx=0.5, rely=0.02, anchor='n')
            self._kp_vars = {}
            for key in KEYPOINT_KEYS:
                var = tk.BooleanVar(value=False)
                self._kp_vars[key] = var
                tk.Checkbutton(
                    bar, text=t('mark.kp_' + key), variable=var,
                    bg=bar_bg, fg='#f8fafc', selectcolor='#101418',
                    activebackground=bar_bg,
                    command=lambda k=key: self._toggle_keypoint(k)).pack(
                        side='left', padx=4, pady=4)
            tk.Button(bar, text=t('mark.btn_confirm'), command=self._confirm).pack(
                side='left', padx=6, pady=4)
            tk.Button(bar, text=t('mark.btn_cancel'), command=self._cancel).pack(
                side='left', padx=6, pady=4)

    def _toggle_keypoint(self, key):
        """Aktiviert/deaktiviert einen Sonderpunkt-Override und zeichnet neu."""
        enabled = bool(self._kp_vars[key].get())
        self._kp_enabled[key] = enabled
        if enabled:
            # Beim Aktivieren an die aktuelle REF-Lage relativ zum Raster setzen.
            self._kp[key] = list(self._ref_to_screen(_REF_KEYPOINTS[key]))
        self._redraw()

    def _load_reference(self):
        """Laedt ``images/calibration_reference.png`` als Vorschau (oben rechts).

        Defensiv: fehlt PIL/Datei, bleibt ``_ref_photo`` None -> das Overlay
        laeuft unveraendert weiter, nur ohne Bild-Vorlage."""
        self._ref_photo = None
        self._ref_w = 0
        self._ref_h = 0
        try:
            import os
            from PIL import Image, ImageTk
            path = resource_path(REFERENCE_IMAGE)
            if not os.path.exists(path):
                return
            pil = Image.open(path).convert('RGBA')
            target_w = 320
            if pil.width > target_w:
                ratio = target_w / pil.width
                pil = pil.resize((target_w, int(pil.height * ratio)))
            self._ref_photo = ImageTk.PhotoImage(pil)
            self._ref_w = pil.width
            self._ref_h = pil.height
        except Exception:
            self._ref_photo = None

    # -- Zeichnen ------------------------------------------------------

    def _redraw(self):
        """Zeichnet Bbox, Raster-Vorschau, Eckgriffe und aktive Sonderpunkte."""
        self.canvas.delete('all')
        tl = self._grid['tl']
        br = self._grid['br']

        # Board-Crop-Rechteck (aus den Griffen abgeleitet) zur Orientierung.
        crop = _crop_from_grid_corners(tl, br)
        if crop is not None:
            offset, size = crop
            # Crop-Ecke relativ zur Griff-Lage rekonstruieren (Bildschirm):
            # gridTL liegt bei offset + 15*scale; scale = size/REF.
            ref_w, ref_h = geometry.REF_SIZE
            origin = geometry.GRID_ORIGIN
            sx = size[0] / ref_w
            sy = size[1] / ref_h
            crop_x = tl[0] - origin * sx
            crop_y = tl[1] - origin * sy
            self.canvas.create_rectangle(
                crop_x, crop_y, crop_x + size[0], crop_y + size[1],
                outline='#14b8a6', width=2)

        # Bbox der Zellmitten (zwischen den beiden Griffen).
        self.canvas.create_rectangle(
            tl[0], tl[1], br[0], br[1],
            outline='#2dd4bf', width=1, dash=(4, 3))

        # Raster-Vorschau: 24 Punkte zwischen den Griffen interpolieren.
        cols = geometry.GRID_COLS
        rows = geometry.GRID_ROWS
        for i in range(rows):
            for j in range(cols):
                fx = j / (cols - 1) if cols > 1 else 0
                fy = i / (rows - 1) if rows > 1 else 0
                px = tl[0] + fx * (br[0] - tl[0])
                py = tl[1] + fy * (br[1] - tl[1])
                self.canvas.create_oval(
                    px - DOT_RADIUS, py - DOT_RADIUS,
                    px + DOT_RADIUS, py + DOT_RADIUS,
                    fill='#2dd4bf', outline='#f8fafc')

        # Eckgriffe (gridTL/gridBR) als groessere quadratische Anfasser.
        for name, label in (('tl', t('mark.handle_tl')), ('br', t('mark.handle_br'))):
            hx, hy = self._grid[name]
            self.canvas.create_rectangle(
                hx - HANDLE_HALF, hy - HANDLE_HALF,
                hx + HANDLE_HALF, hy + HANDLE_HALF,
                fill='#14b8a6', outline='#f8fafc', width=2)
            self.canvas.create_text(hx, hy - HANDLE_HALF - 8, text=label,
                                    fill='#f8fafc', font=('Segoe UI', 8, 'bold'))

        # Aktive Sonderpunkte.
        for key in KEYPOINT_KEYS:
            if not self._kp_enabled[key]:
                continue
            kx, ky = self._kp[key]
            label, color = _KEYPOINT_STYLE[key]
            self.canvas.create_oval(
                kx - HANDLE_HALF, ky - HANDLE_HALF,
                kx + HANDLE_HALF, ky + HANDLE_HALF,
                fill=color, outline='#f8fafc', width=2)
            self.canvas.create_text(kx, ky - HANDLE_HALF - 8,
                                    text=t('mark.kp_' + key),
                                    fill=color, font=('Segoe UI', 8, 'bold'))

        # Referenzbild oben rechts: zeigt, wo die 4 Sonderpunkte hingehoeren.
        if getattr(self, '_ref_photo', None) is not None:
            rx = self._screen_w - 16
            self.canvas.create_image(rx, 16, anchor='ne', image=self._ref_photo)
            self.canvas.create_text(
                rx - self._ref_w // 2, 16 + self._ref_h + 12,
                text=t('mark.reference_caption'),
                fill='#f8fafc', font=('Segoe UI', 9, 'bold'))

        # Schritt-Anleitung unten an der Bounding-Box.
        self.canvas.create_text(
            (tl[0] + br[0]) // 2, max(tl[1], br[1]) + 22,
            text=t('mark.step_instructions'),
            fill='#f8fafc', font=('Segoe UI', 9))

    # -- Drag-Logik (unabhaengige Griffe) ------------------------------

    def _hit(self, x, y):
        """Findet das Handle unter ``(x, y)``; Sonderpunkte vor Eckgriffen."""
        for key in KEYPOINT_KEYS:
            if not self._kp_enabled[key]:
                continue
            kx, ky = self._kp[key]
            if abs(x - kx) <= HANDLE_HALF and abs(y - ky) <= HANDLE_HALF:
                return ('kp', key)
        for name in ('tl', 'br'):
            hx, hy = self._grid[name]
            if abs(x - hx) <= HANDLE_HALF and abs(y - hy) <= HANDLE_HALF:
                return ('grid', name)
        return None

    def _on_press(self, event):
        self._active = self._hit(event.x, event.y)
        if self._active is None:
            return
        kind, name = self._active
        cur = self._grid[name] if kind == 'grid' else self._kp[name]
        self._grab_dx = event.x - cur[0]
        self._grab_dy = event.y - cur[1]

    def _on_drag(self, event):
        if self._active is None:
            return
        kind, name = self._active
        nx = event.x - self._grab_dx
        ny = event.y - self._grab_dy
        if kind == 'grid':
            self._grid[name][0] = nx
            self._grid[name][1] = ny
        else:
            self._kp[name][0] = nx
            self._kp[name][1] = ny
        self._redraw()

    def _on_release(self, _event):
        self._active = None

    # -- Abschluss -----------------------------------------------------

    def _confirm(self):
        key_points = {k: tuple(self._kp[k])
                      for k in KEYPOINT_KEYS if self._kp_enabled[k]}
        self.result = {
            'grid_tl': tuple(self._grid['tl']),
            'grid_br': tuple(self._grid['br']),
            'key_points': key_points,
        }
        _log_event(t('mark.overlay_confirmed'),
                   grid_tl=self.result['grid_tl'],
                   grid_br=self.result['grid_br'],
                   keypoints=list(key_points.keys()))
        self._close()

    def _cancel(self):
        self.result = None
        _log_event(t('mark.overlay_cancelled'))
        self._close()

    def _close(self):
        try:
            self.top.grab_release()
        except Exception:
            pass
        try:
            self.top.destroy()
        except Exception:
            pass

    def run(self):
        """Macht das Overlay modal und kehrt mit ``self.result`` zurueck."""
        try:
            self.top.protocol('WM_DELETE_WINDOW', self._cancel)
        except Exception:
            pass
        try:
            self.top.grab_set()
        except Exception:
            pass
        self.top.wait_window()
        return self.result


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


def pick_offset_interactive(default_offset=DEFAULT_OFFSET, board_size=BOARD_SIZE,
                            alpha=OVERLAY_ALPHA):
    """Oeffnet das resizable Markier-Overlay und liefert das Kalibrier-Ergebnis.

    :param default_offset: Startlage/Fallback ``(x, y)`` (Fensterinhalt-Offset).
    :param board_size: Referenz-Boardgroesse fuer die Vorschau (Default 260x170).
    :param alpha: Deckkraft des Overlays (0.4..1.0). Aus der Config
        (``puzzle.overlay_opacity``); nicht-numerisch -> Modul-Default. Wird
        defensiv geklemmt.
    :return: :class:`MarkResult` (Dict mit ``offset``/``size``/``key_points``)
        bei „Confirm", sonst ``None``.

    Liefert ``None`` auch dann, wenn keine GUI/kein Display verfuegbar ist
    (headless) oder die Markierung degeneriert ist. Wirft nie.
    """
    if tk is None:
        _log_event(t('mark.overlay_unavailable'))
        return None

    parent = None
    created_root = False
    try:
        try:
            parent = tk._get_default_root()
        except Exception:
            parent = None
        if parent is None:
            parent = tk.Tk()
            parent.withdraw()
            created_root = True

        overlay = _MarkOverlay(parent, default_offset, board_size, alpha=alpha)
        screen_state = overlay.run()
    except Exception as exc:
        _log_error(t('mark.overlay_error'), exc=exc)
        screen_state = None
    finally:
        if created_root and parent is not None:
            try:
                parent.destroy()
            except Exception:
                pass

    if screen_state is None:
        return None

    try:
        return _build_result(screen_state)
    except Exception as exc:
        _log_error(t('mark.result_not_derivable'), exc=exc)
        return None
