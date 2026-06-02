"""Rastergeometrie + defensive Sampling-Primitive fuer die Puzzle-Kalibrierung.

Tieferliegende, abhaengigkeitsarme Schicht von :mod:`calibration`. Enthaelt die
4x6-Rastergeometrie, die Schwellwerte und die defensiven Pixel-/Form-/Crop-
Zugriffe, die sowohl numpy-Arrays als auch verschachtelte Python-Listen
unterstuetzen. Bewusst ohne Fremd-Dependencies -> per ``unittest`` testbar.

Bildkonvention (wie im restlichen Projekt, siehe puzzle.py):
* Der Ausschnitt ``crop_img`` hat die Form ``(Hoehe, Breite, 3)`` = (170, 260, 3).
* Pixelzugriff erfolgt als ``crop_img[y, x]`` (erst Zeile/Hoehe, dann Spalte/Breite).
* Kanalreihenfolge ist BGR: Index 0 = Blau, 1 = Gruen, 2 = Rot.
* Die 24 Rasterpunkte liegen bei ``(x=15+32*j, y=15+32*i)`` fuer
  i in 0..3 (Zeilen) und j in 0..5 (Spalten) -- 4x6 Zellen.
"""


# -- Konstanten (an puzzle.py ausgerichtet) -------------------------------

# Rastergeometrie der 4x6-Zellen.
GRID_ROWS = 4          # i: 0..3 (Hoehe / Zeilen)
GRID_COLS = 6          # j: 0..5 (Breite / Spalten)
GRID_ORIGIN = 15       # erster Sample-Offset in Pixeln
GRID_STEP = 32         # Abstand zwischen den Sample-Punkten

# Schwelle wie in puzzle.set_puzzle_state: alle Kanaele < 50 => Zelle leer.
EMPTY_CHANNEL_THRESHOLD = 50

# Ein Bereich gilt als "komplett schwarz", wenn die mittlere Helligkeit der
# Samples darunter liegt (Summe aller drei Kanaele pro Pixel).
BLACK_MEAN_SUM_THRESHOLD = 12

# Uniform = zu geringe Streuung der Sample-Helligkeiten -> falscher Ausschnitt.
UNIFORM_SPREAD_THRESHOLD = 8


# -- defensiver Pixelzugriff ----------------------------------------------

def _px(img, x, y):
    """Liest ein Pixel als ``(b, g, r)``-Tupel.

    Unterstuetzt numpy-Arrays (``img[y, x]``) UND verschachtelte Python-Listen
    (``img[y][x]``). Bei Index-/Typfehlern wird ``None`` zurueckgegeben statt
    eine Exception zu werfen -- so bleibt die Kernlogik crash-frei.

    Wichtig: Reihenfolge der Indizes ist (Zeile=y, Spalte=x), passend zur
    Bildkonvention des Projekts.
    """
    try:
        try:
            # numpy-Array: zwei-Index-Zugriff liefert das Pixel direkt.
            pixel = img[y, x]
        except (TypeError, IndexError, KeyError):
            # verschachtelte Python-Liste.
            pixel = img[y][x]
        b = int(pixel[0])
        g = int(pixel[1])
        r = int(pixel[2])
        return (b, g, r)
    except Exception:
        return None


def _shape(img):
    """Ermittelt ``(hoehe, breite)`` defensiv fuer numpy ODER Listen.

    Gibt ``(None, None)`` zurueck, wenn die Form nicht bestimmbar ist.
    """
    # numpy-Array bevorzugt ueber .shape auswerten.
    try:
        shp = img.shape
        if len(shp) >= 2:
            return int(shp[0]), int(shp[1])
    except Exception:
        pass
    # verschachtelte Python-Listen.
    try:
        height = len(img)
        if height == 0:
            return 0, 0
        width = len(img[0])
        return int(height), int(width)
    except Exception:
        return None, None


def _is_empty_cell(bgr):
    """True, wenn alle drei Kanaele unter der Leer-Schwelle liegen.

    Identische Logik wie puzzle.set_puzzle_state (Zelle gilt als leer/0).
    """
    if bgr is None:
        return True
    b, g, r = bgr
    return (b < EMPTY_CHANNEL_THRESHOLD
            and g < EMPTY_CHANNEL_THRESHOLD
            and r < EMPTY_CHANNEL_THRESHOLD)


def _grid_point(i, j):
    """Liefert die ``(x, y)``-Bildkoordinate des Rasterpunktes (i, j)."""
    x = GRID_ORIGIN + GRID_STEP * j
    y = GRID_ORIGIN + GRID_STEP * i
    return x, y


def _sample_grid(crop_img):
    """Sammelt die 24 Rasterpunkte defensiv ein.

    Rueckgabe: Tupel ``(samples, missing)`` mit
      * ``samples`` -- Liste von Dicts ``{i, j, x, y, bgr, empty}`` fuer alle
        Punkte, die im Bild lagen,
      * ``missing`` -- Liste ``(i, j)`` der Punkte ausserhalb des Bildes.
    """
    samples = []
    missing = []
    for i in range(GRID_ROWS):
        for j in range(GRID_COLS):
            x, y = _grid_point(i, j)
            bgr = _px(crop_img, x, y)
            if bgr is None:
                missing.append((i, j))
                continue
            samples.append({
                'i': i,
                'j': j,
                'x': x,
                'y': y,
                'bgr': bgr,
                'empty': _is_empty_cell(bgr),
            })
    return samples, missing


def _crop(img, x, y, width, height):
    """Schneidet defensiv einen Bereich aus numpy ODER Listen aus.

    Gibt bei numpy-Arrays einen Slice zurueck, bei Python-Listen eine neue
    verschachtelte Liste. ``None`` bei Fehlern.
    """
    try:
        # numpy-Slicing zuerst versuchen.
        try:
            return img[y:y + height, x:x + width]
        except (TypeError, KeyError):
            pass
        # verschachtelte Python-Liste.
        rows = []
        for row in img[y:y + height]:
            rows.append(list(row[x:x + width]))
        return rows
    except Exception:
        return None


__all__ = [
    'GRID_ROWS', 'GRID_COLS', 'GRID_ORIGIN', 'GRID_STEP',
    'EMPTY_CHANNEL_THRESHOLD', 'BLACK_MEAN_SUM_THRESHOLD',
    'UNIFORM_SPREAD_THRESHOLD',
    '_px', '_shape', '_is_empty_cell', '_grid_point', '_sample_grid', '_crop',
]
