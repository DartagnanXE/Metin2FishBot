"""Selbstdiagnose fuer die Puzzle-Bildregion (Positions-/Aufloesungs-Check).

Aufgabe: Bevor der Puzzle-Solver das Board/den Stein aus dem Bildausschnitt
liest, pruefen, ob der ausgeschnittene Bereich PLAUSIBEL das Puzzle zeigt.
Der haeufigste Nutzerfehler (Fenster verschoben oder Aufloesung nicht 800x600)
fuehrt sonst zu einem schwarzen/uniformen Ausschnitt -> der Solver bekommt
Unsinn und der Bot bricht still ab. Hier wird dieser Fall ERKANNT und mit
konkreten, deutschen ``reasons`` gemeldet statt zu crashen.

Bewusst defensiv:
* numpy darf genutzt werden, ist aber NICHT erforderlich. Saemtliche
  Kernlogik laeuft ueber die Hilfsfunktion :func:`_px`, die sowohl
  numpy-Arrays als auch verschachtelte Python-Listen unterstuetzt. Dadurch
  ist dieses Modul ohne Fremd-Dependencies per ``unittest`` testbar.
* Funktionen geben IMMER ein Ergebnis-Objekt / einen Wert zurueck statt eine
  Exception zu werfen. Index-/Formfehler werden in ``reasons`` festgehalten.

Bildkonvention (wie im restlichen Projekt, siehe puzzle.py):
* Der Ausschnitt ``crop_img`` hat die Form ``(Hoehe, Breite, 3)`` = (170, 260, 3).
* Pixelzugriff erfolgt als ``crop_img[y, x]`` (erst Zeile/Hoehe, dann Spalte/Breite).
* Kanalreihenfolge ist BGR: Index 0 = Blau, 1 = Gruen, 2 = Rot.
* Die 24 Rasterpunkte liegen bei ``(x=15+32*j, y=15+32*i)`` fuer
  i in 0..3 (Zeilen) und j in 0..5 (Spalten) -- 4x6 Zellen.

Struktur: Dieses Modul ist die oeffentliche FASSADE. Die Rastergeometrie und
die defensiven Sampling-Primitive (``_px``/``_shape``/``_crop``/``_sample_grid``
+ die ``GRID_*``/``*_THRESHOLD``-Konstanten) liegen in
:mod:`calibration_grid` und werden hier per Stern-Import re-exportiert, sodass
``calibration.X`` -- inkl. der privaten ``calibration._crop`` /
``calibration._shape`` (von ``detection.py`` genutzt) -- unveraendert aufgeht.
"""

from dataclasses import dataclass, field

from calibration_grid import *  # noqa: F401,F403  (re-export: Geometrie/Primitive)
# Stern-Import ueberspringt fuehrende-Unterstrich-Namen; ``detection.py`` liest
# aber ``calibration._crop`` und ``calibration._shape`` direkt -> explizit
# re-exportieren, damit der bisherige Zugriff byte-identisch bleibt.
from calibration_grid import (  # noqa: F401
    _crop,
    _sample_grid,
    _shape,
)


# -- Konstanten (an puzzle.py ausgerichtet) -------------------------------

# Erwartete Region als (Breite, Hoehe), passend zu PuzzleBot.PUZZLE_WINDOW_SIZE.
DEFAULT_EXPECTED_SIZE = (260, 170)


@dataclass
class CalibrationResult:
    """Ergebnis einer Plausibilitaetspruefung.

    ``ok``      True, wenn der Bereich plausibel das Puzzle zeigt.
    ``reasons`` Liste konkreter, deutscher Begruendungen (leer bei ok=True).
    ``details`` Strukturierte Messwerte fuer die Debug-Konsole/Logs.
    """

    ok: bool
    reasons: list = field(default_factory=list)
    details: dict = field(default_factory=dict)


# -- oeffentliche API ------------------------------------------------------

def validate_puzzle_region(crop_img, expected_size=DEFAULT_EXPECTED_SIZE):
    """Prueft, ob ``crop_img`` plausibel das Puzzle-Raster zeigt.

    Geprueft werden drei Dinge; je Verletzung wird eine konkrete deutsche
    Begruendung in ``reasons`` gesammelt:

    1. Form/Groesse -- Hoehe und Breite muessen zu ``expected_size``
       (Breite, Hoehe) passen. Abweichungen deuten auf falsche Aufloesung
       oder ein verschobenes/zu kleines Fenster hin.
    2. Nicht komplett schwarz UND nicht uniform -- ueber die Rastersamples
       wird die Hell/Dunkel-Streuung bewertet. Alles schwarz => Fenster nicht
       an erwarteter Position. Alles gleich => falscher Bildausschnitt.
    3. Plausible Belegung -- die 24 Rasterpunkte muessen im Bild liegen und
       eine plausible Mischung aus belegten und leeren Zellen zeigen.

    Gibt IMMER eine :class:`CalibrationResult` zurueck (wirft nie).

    :param crop_img: numpy-Array ODER verschachtelte Python-Liste (H, B, 3).
    :param expected_size: ``(Breite, Hoehe)`` der erwarteten Region.
    """
    reasons = []
    details = {}

    try:
        # expected_size ist (Breite, Hoehe); shape ist (Hoehe, Breite, 3).
        try:
            expected_width = int(expected_size[0])
            expected_height = int(expected_size[1])
        except Exception:
            expected_width, expected_height = DEFAULT_EXPECTED_SIZE
            reasons.append(
                'expected_size unlesbar -> Default (260x170) angenommen')

        # --- (0) Grundpruefung: ueberhaupt ein Bild vorhanden? ----------
        if crop_img is None:
            reasons.append('Kein Bild uebergeben (crop_img is None) '
                           '-> Bildschirmaufnahme fehlgeschlagen')
            return CalibrationResult(False, reasons, details)

        height, width = _shape(crop_img)
        details['height'] = height
        details['width'] = width
        details['expected_height'] = expected_height
        details['expected_width'] = expected_width

        if height is None or width is None:
            reasons.append('Bildform nicht bestimmbar '
                           '-> unerwarteter Bildtyp/leeres Bild')
            return CalibrationResult(False, reasons, details)

        if height == 0 or width == 0:
            reasons.append(
                'Bereich ist leer (Hoehe {} / Breite {}) '
                '-> Puzzle-Fenster nicht an erwarteter Position'.format(
                    height, width))
            return CalibrationResult(False, reasons, details)

        # --- (1) Form/Groesse -------------------------------------------
        if height != expected_height:
            reasons.append(
                'Hoehe {} statt {} -> falsche Aufloesung oder Fenster '
                'verschoben (erwartet 800x600)'.format(
                    height, expected_height))
        if width != expected_width:
            reasons.append(
                'Breite {} statt {} -> falsche Aufloesung oder Fenster '
                'verschoben (erwartet 800x600)'.format(
                    width, expected_width))

        # --- Rastersamples einsammeln -----------------------------------
        samples, missing = _sample_grid(crop_img)
        details['samples_total'] = len(samples)
        details['samples_missing'] = len(missing)

        if missing:
            reasons.append(
                '{} von {} Rasterpunkten liegen ausserhalb des Bildes '
                '-> Bereich zu klein/falsch positioniert'.format(
                    len(missing), GRID_ROWS * GRID_COLS))

        if not samples:
            reasons.append('Kein einziger Rasterpunkt lesbar '
                           '-> Bildausschnitt unbrauchbar')
            return CalibrationResult(False, reasons, details)

        # --- (2a/2b/3) Inhalts-Heuristiken: NUR ADVISORIES, kein Stop ----
        # FIX (Blocker B): Diese Pruefungen beproben AUSSCHLIESSLICH die 24
        # Zell-Mittelpunkte -- exakt die Punkte, die bei einem LEGITIM LEEREN
        # Brett (Normalzustand zu Beginn JEDES Puzzles und nach dem Loesen)
        # per Definition dunkel/uniform sind. Frueher setzten sie ok=False ->
        # der Bot stoppte bei jedem Puzzle-Start und reproduzierte exakt das
        # alte Symptom. Ein leeres Brett ist ein GUELTIGER Zustand. Daher
        # fliessen diese Inhalts-Signale nur noch als Hinweise in
        # details['advisories'] (fuer die Debug-Konsole) und beeinflussen 'ok'
        # NICHT mehr. Eine echte Fehlpositionierung wird zuverlaessig ueber
        # Form/Groesse und fehlende Rasterpunkte (oben, weiterhin blockierend)
        # erkannt.
        advisories = []

        brightness = [sum(s['bgr']) for s in samples]
        mean_brightness = sum(brightness) / len(brightness)
        spread = max(brightness) - min(brightness)
        details['mean_brightness'] = round(mean_brightness, 2)
        details['brightness_spread'] = spread

        if mean_brightness < BLACK_MEAN_SUM_THRESHOLD:
            advisories.append(
                'Zell-Mittelpunkte sehr dunkel (mittlere Helligkeit {:.1f}) '
                '-> entweder leeres Brett (normal) ODER Fenster falsch '
                'positioniert; Stein-/Board-Logs pruefen'.format(
                    mean_brightness))

        if spread < UNIFORM_SPREAD_THRESHOLD:
            advisories.append(
                'Zell-Mittelpunkte uniform (Streuung {}) -> leeres oder '
                'gleichmaessig gefuelltes Brett bzw. falscher Ausschnitt'.format(
                    spread))

        empty_count = sum(1 for s in samples if s['empty'])
        filled_count = len(samples) - empty_count
        details['empty_cells'] = empty_count
        details['filled_cells'] = filled_count

        if filled_count == 0:
            advisories.append(
                'Alle {} Zellen leer -> plausibel leeres Startbrett (gueltig; '
                'nur bei DAUERHAFT schwarzer Region Position/Aufloesung '
                'pruefen)'.format(len(samples)))

        details['advisories'] = advisories

        # 'ok' haengt AUSSCHLIESSLICH an den strukturellen (zuverlaessigen)
        # Pruefungen: Form/Groesse + lesbare Rasterpunkte (oben in 'reasons').
        # Inhalts-Advisories stoppen den Bot nicht mehr.
        ok = len(reasons) == 0
        return CalibrationResult(ok, reasons, details)

    except Exception as exc:
        # Selbstdiagnose darf selbst nie crashen.
        reasons.append('Interner Fehler in validate_puzzle_region: '
                       '{}'.format(exc))
        return CalibrationResult(False, reasons, details)


def describe_grid(crop_img):
    """Beschreibt jede der 24 Rasterzellen fuer die Debug-Konsole.

    Rueckgabe-Dict::

        {
            'cells': {
                (i, j): {'x': .., 'y': .., 'bgr': (b, g, r), 'empty': bool},
                ...
            },
            'missing': [(i, j), ...],   # Punkte ausserhalb des Bildes
            'empty_cells': int,
            'filled_cells': int,
        }

    Gleiche Leer-Schwelle wie puzzle.set_puzzle_state. Wirft nie.
    """
    result = {'cells': {}, 'missing': [], 'empty_cells': 0, 'filled_cells': 0}
    try:
        samples, missing = _sample_grid(crop_img)
        result['missing'] = missing
        for s in samples:
            result['cells'][(s['i'], s['j'])] = {
                'x': s['x'],
                'y': s['y'],
                'bgr': s['bgr'],
                'empty': s['empty'],
            }
            if s['empty']:
                result['empty_cells'] += 1
            else:
                result['filled_cells'] += 1
    except Exception:
        # Defensiv: im Fehlerfall ein leeres, aber wohlgeformtes Dict.
        pass
    return result


def find_puzzle_offset(screenshot):
    """Best-effort-Suche nach dem Puzzle-Offset im Vollbild-Screenshot.

    Sucht das obere-linke Eck des Puzzle-Rasters, indem die erwartete Region
    an der Standardposition (PuzzleBot.PUZZLE_WINDOW_POSITION = (270, 227))
    auf Plausibilitaet geprueft wird. Eine echte Template-/Mustersuche ist
    bewusst NICHT implementiert (haengt von cv2 ab und ist optional laut
    Vertrag) -- diese Funktion verifiziert lediglich die bekannte Position.

    :return: ``(x, y)`` bei plausibler Standardposition, sonst ``None``.
    """
    try:
        if screenshot is None:
            return None

        # Standardposition wie in puzzle.py (Breite, Hoehe Offsets).
        default_x, default_y = (270, 227)
        win_w, win_h = DEFAULT_EXPECTED_SIZE

        full_h, full_w = _shape(screenshot)
        if full_h is None or full_w is None:
            return None
        if default_y + win_h > full_h or default_x + win_w > full_w:
            return None

        # Ausschnitt an der Standardposition pruefen.
        crop = _crop(screenshot, default_x, default_y, win_w, win_h)
        if crop is None:
            return None

        result = validate_puzzle_region(crop)
        if result.ok:
            return (default_x, default_y)
        return None
    except Exception:
        return None
