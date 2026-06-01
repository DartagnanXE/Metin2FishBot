"""Konfigurations-Persistenz fuer das Metin2-Fishing-Bot-UI.

Bewusst NUR Python-Standardbibliothek (``json``), damit dieses Modul auch ohne
GUI-Toolkit ueberall importier- und testbar bleibt und aus der gepackten ``.exe``
heraus funktioniert.

Die ``config.json`` liegt neben der EXE. Sie haelt ALLE UI-Optionen
(Modus, Fishing-Timings, Puzzle-Detection/Color/Solver, Log-Sichtbarkeit).

Grundregeln:
  * Laden wirft NIE -- fehlende/kaputte Datei -> Defaults.
  * Unbekannte/fehlende Schluessel werden mit Defaults gefuellt (Vorwaerts-/
    Rueckwaertskompatibilitaet zu alten config.json-Dateien).
  * Validierung klemmt Werte in den erlaubten Bereich und ersetzt ungueltige
    Enums durch ihren Default (statt zu werfen).
  * Immutabilitaet: ``merge_defaults``/``validate`` geben NEUE Dicts zurueck und
    veraendern ihre Eingabe nicht.
"""

import copy
import json


# -- Erlaubte Wertebereiche / Enums (eine einzige Wahrheit) -----------------

DETECTION_MODES = ('default', 'auto', 'mark')
COLOR_MODES = ('single', 'multi')
SOLVER_MODES = ('standard', 'trained')
APP_MODES = ('fishing', 'puzzle')
COLOR_PATCHES = (3, 5)

# Golden-Tuna-Dialog: welcher der 3 senkrecht gestapelten Knoepfe geklickt
# wird. 1 = Freilassen, 2 = Aufschneiden, 3 = Als Koeder benutzen (Default).
GOLDEN_TUNA_ACTIONS = (1, 2, 3)

# Erlaubte Sonderpunkt-Schluessel fuer ``mark_keypoints`` (Overrides der
# geometry-Defaults). Jeder Wert ist ein [x, y]-Integer-Paar (Referenzkoordinate
# auf dem 260x170-Board). Unbekannte Schluessel werden bei der Validierung
# verworfen.
KEYPOINT_KEYS = ('color', 'getpiece', 'confirm', 'cake')

# Slider-Grenzen fuer die drei Fishing-Timings (Spec: 0.1s - 20s).
DELAY_MIN = 0.1
DELAY_MAX = 20.0

# Grenzen fuer die Overlay-Deckkraft (Mark-/Vorschau-Overlay). 0.4 = noch klar
# durchscheinend (pixelgenaues Platzieren), 1.0 = voll deckend. Default bewusst
# deckender als der historische 0.45-Wert, weil das alte Overlay zu transparent
# war. Wird via Tk-Attribut '-alpha' auf beide Overlays angewandt; kein Bot-Wert
# (taucht NICHT in to_values auf).
OVERLAY_OPACITY_MIN = 0.4
OVERLAY_OPACITY_MAX = 1.0

# Erlaubte Hotkey-Tokens fuer Angeln (pydirectinput-Keynamen). Einzelne
# Ziffern/Buchstaben + eine Whitelist gebraeuchlicher Sondertasten. Ungueltige
# Eingaben fallen auf den Default zurueck -> kein Crash mitten im Lauf.
HOTKEY_TOKENS = (
    'space', 'enter', 'tab', 'esc', 'shift', 'ctrl', 'alt',
    'f1', 'f2', 'f3', 'f4', 'f5', 'f6', 'f7', 'f8', 'f9', 'f10', 'f11', 'f12',
)

DEFAULT_CONFIG_PATH = 'config.json'

# Vollstaendiges Default-Schema. Entspricht exakt dem heutigen Verhalten:
#   * Fishing-Timings 2.0s (wie FishingBot.bait_time/throw_time/game_time = 2),
#   * Puzzle Detection 'default' (feste Position 270,227),
#   * Color 'single' (1 Pixel/Zelle), Solver 'standard' (Greedy).
DEFAULTS = {
    'version': 1,
    'language': 'en',
    'mode': 'fishing',
    'fishing': {
        'bait_time': 2.0,
        'throw_time': 2.0,
        'start_game_time': 2.0,
        'stop_after_enabled': False,
        'stop_after_minutes': 0,
        'golden_tuna_action': 3,
        'bait_key': '2',          # In-Game-Taste, die Koeder wirft
        'cast_key': '1',          # In-Game-Taste, die die Angel auswirft
    },
    'puzzle': {
        'detection_mode': 'default',
        'mark_offset': None,
        'mark_size': None,
        'mark_keypoints': {},
        'color_mode': 'single',
        'color_patch': 3,
        'solver_mode': 'standard',
        'overlay_opacity': 0.85,  # Deckkraft Mark-/Vorschau-Overlay (0.4..1.0)
    },
    'log': {
        'show_in_ui': True,
    },
    'window': {                   # Fenster-/Lifecycle-Optionen (alle Default aus)
        'always_on_top': False,
        'minimize_to_tray': False,
        'close_on_metin2_close': False,
        'close_on_timer_expire': False,
    },
}


# -- interne Helfer ---------------------------------------------------------

def _clamp(value, low, high, fallback):
    """Klemmt ``value`` in [low, high]. Bei nicht-numerisch -> ``fallback``."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if number < low:
        return low
    if number > high:
        return high
    return number


def _enum(value, allowed, fallback):
    """Gibt ``value`` zurueck, falls in ``allowed``, sonst ``fallback``."""
    return value if value in allowed else fallback


def _coerce_int(value, fallback):
    """Wandelt nach int; bei Fehler -> ``fallback``."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _validate_key(value, fallback):
    """Normalisiert eine Hotkey-Eingabe -> lowercased str. Erlaubt: ein einzelnes
    Zeichen (Ziffer/Buchstabe/Satzzeichen) ODER ein Token aus HOTKEY_TOKENS.
    Sonst ``fallback``. Wirft nie."""
    try:
        s = str(value).strip().lower()
    except Exception:
        return fallback
    if not s:
        return fallback
    if len(s) == 1:
        return s
    if s in HOTKEY_TOKENS:
        return s
    return fallback


def _deep_merge(base, override):
    """Rekursiver Merge: Werte aus ``override`` ueberschreiben ``base``.

    Gibt ein NEUES Dict zurueck (Eingaben bleiben unveraendert). Nicht-dict-
    Werte in ``override`` ersetzen den Basiswert; verschachtelte Dicts werden
    Schluessel-fuer-Schluessel zusammengefuehrt.
    """
    result = copy.deepcopy(base)
    if not isinstance(override, dict):
        return result
    for key, value in override.items():
        if (key in result and isinstance(result[key], dict)
                and isinstance(value, dict)):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


# -- oeffentliche API -------------------------------------------------------

def merge_defaults(partial):
    """Fuellt fehlende Schluessel aus :data:`DEFAULTS` auf.

    Liefert ein NEUES, vollstaendiges Dict. Alte config.json-Dateien ohne neue
    Felder bleiben so nutzbar. Wirft nie.
    """
    try:
        return _deep_merge(DEFAULTS, partial if isinstance(partial, dict) else {})
    except Exception:
        return copy.deepcopy(DEFAULTS)


def validate(cfg):
    """Normalisiert und klemmt eine Konfiguration. Gibt ein NEUES Dict zurueck.

    Ungueltige Enums werden auf ihren Default gesetzt, numerische Werte in den
    erlaubten Bereich geklemmt. Wirft nie -- im Fehlerfall reine Defaults.
    """
    try:
        merged = merge_defaults(cfg)

        merged['mode'] = _enum(merged.get('mode'), APP_MODES, DEFAULTS['mode'])
        merged['language'] = _enum(merged.get('language'), ('en', 'de'),
                                   DEFAULTS['language'])

        fishing = merged['fishing']
        fishing['bait_time'] = _clamp(
            fishing.get('bait_time'), DELAY_MIN, DELAY_MAX,
            DEFAULTS['fishing']['bait_time'])
        fishing['throw_time'] = _clamp(
            fishing.get('throw_time'), DELAY_MIN, DELAY_MAX,
            DEFAULTS['fishing']['throw_time'])
        fishing['start_game_time'] = _clamp(
            fishing.get('start_game_time'), DELAY_MIN, DELAY_MAX,
            DEFAULTS['fishing']['start_game_time'])
        fishing['stop_after_enabled'] = bool(
            fishing.get('stop_after_enabled', False))
        minutes = _coerce_int(fishing.get('stop_after_minutes'), 0)
        fishing['stop_after_minutes'] = minutes if minutes >= 0 else 0
        action = _coerce_int(fishing.get('golden_tuna_action'),
                             DEFAULTS['fishing']['golden_tuna_action'])
        fishing['golden_tuna_action'] = (
            action if action in GOLDEN_TUNA_ACTIONS
            else DEFAULTS['fishing']['golden_tuna_action'])
        fishing['bait_key'] = _validate_key(
            fishing.get('bait_key'), DEFAULTS['fishing']['bait_key'])
        fishing['cast_key'] = _validate_key(
            fishing.get('cast_key'), DEFAULTS['fishing']['cast_key'])

        puzzle = merged['puzzle']
        puzzle['detection_mode'] = _enum(
            puzzle.get('detection_mode'), DETECTION_MODES,
            DEFAULTS['puzzle']['detection_mode'])
        puzzle['color_mode'] = _enum(
            puzzle.get('color_mode'), COLOR_MODES,
            DEFAULTS['puzzle']['color_mode'])
        puzzle['solver_mode'] = _enum(
            puzzle.get('solver_mode'), SOLVER_MODES,
            DEFAULTS['puzzle']['solver_mode'])
        patch = _coerce_int(puzzle.get('color_patch'),
                            DEFAULTS['puzzle']['color_patch'])
        puzzle['color_patch'] = (
            patch if patch in COLOR_PATCHES
            else DEFAULTS['puzzle']['color_patch'])
        puzzle['mark_offset'] = _validate_offset(puzzle.get('mark_offset'))
        puzzle['mark_size'] = _validate_size(puzzle.get('mark_size'))
        puzzle['mark_keypoints'] = _validate_keypoints(
            puzzle.get('mark_keypoints'))
        puzzle['overlay_opacity'] = _clamp(
            puzzle.get('overlay_opacity'),
            OVERLAY_OPACITY_MIN, OVERLAY_OPACITY_MAX,
            DEFAULTS['puzzle']['overlay_opacity'])

        merged['log']['show_in_ui'] = bool(merged['log'].get('show_in_ui', True))

        window = merged['window']
        window['always_on_top'] = bool(window.get('always_on_top', False))
        window['minimize_to_tray'] = bool(window.get('minimize_to_tray', False))
        window['close_on_metin2_close'] = bool(
            window.get('close_on_metin2_close', False))
        window['close_on_timer_expire'] = bool(
            window.get('close_on_timer_expire', False))

        return merged
    except Exception:
        return copy.deepcopy(DEFAULTS)


def _validate_offset(value):
    """``None`` oder ein 2-Element-[x, y]-Integer-Paar; sonst ``None``."""
    if value is None:
        return None
    try:
        x, y = value  # entpackt Liste oder Tuple der Laenge 2
        return [int(x), int(y)]
    except (TypeError, ValueError):
        return None


def _validate_size(value):
    """``None`` oder ein 2-Element-[w, h]-Integer-Paar mit w>0 und h>0.

    Andernfalls ``None`` (faellt zur Laufzeit auf die Default-Boardgroesse
    260x170 zurueck). Nicht-positive oder nicht-ganzzahlige Masse werden
    verworfen statt geklemmt -- eine kaputte Markierung soll keine plausibel
    aussehende, aber falsche Groesse erzeugen.
    """
    if value is None:
        return None
    try:
        width, height = value  # entpackt Liste oder Tuple der Laenge 2
        width = int(width)
        height = int(height)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return [width, height]


def _validate_keypoints(value):
    """Normalisiert ``mark_keypoints`` zu einem sauberen Override-Dict.

    Behaelt nur bekannte Schluessel aus :data:`KEYPOINT_KEYS`, deren Wert ein
    2-Element-[x, y]-Integer-Paar ist. Unbekannte Schluessel und kaputte Werte
    werden verworfen. ``None`` oder Nicht-Dict -> ``{}``. Gibt immer ein NEUES
    Dict zurueck (Eingabe bleibt unveraendert).
    """
    if not isinstance(value, dict):
        return {}
    result = {}
    for key in KEYPOINT_KEYS:
        if key not in value:
            continue
        try:
            x, y = value[key]  # entpackt Liste oder Tuple der Laenge 2
            result[key] = [int(x), int(y)]
        except (TypeError, ValueError):
            continue
    return result


def load(path=DEFAULT_CONFIG_PATH):
    """Laedt und validiert die Konfiguration. Wirft NIE.

    Fehlende oder fehlerhafte Datei -> validierte Defaults (es wird nichts auf
    die Platte geschrieben; das uebernimmt erst :func:`save`).
    """
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            raw = json.loads(handle.read())
    except (OSError, ValueError):
        return validate(DEFAULTS)
    except Exception:
        return validate(DEFAULTS)
    return validate(raw)


def save(cfg, path=DEFAULT_CONFIG_PATH):
    """Schreibt die (validierte) Konfiguration als JSON. Wirft NIE.

    Gibt ``True`` bei Erfolg, sonst ``False`` (Aufrufer darf den Rueckgabewert
    ignorieren -- ein Speicherfehler darf den Bot nicht stoppen).
    """
    try:
        normalized = validate(cfg)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(json.dumps(normalized, indent=2, ensure_ascii=False))
        return True
    except Exception:
        return False


def to_values(cfg):
    """Baut den Fishing-``values``-Dict (frozen keys) aus der Konfiguration.

    Liefert exakt die Schluessel, die ``FishingBot.set_to_begin(values)`` liest
    (und die ``PuzzleBot.set_to_begin`` ignoriert). So bleibt die Wertekompati-
    bilitaet zu beiden Bots gewahrt, ohne FreeSimpleGUI.
    """
    normalized = validate(cfg)
    fishing = normalized['fishing']
    return {
        '-ENDTIMEP-': bool(fishing['stop_after_enabled']),
        '-ENDTIME-': str(fishing['stop_after_minutes']),
        '-BAITTIME-': float(fishing['bait_time']),
        '-THROWTIME-': float(fishing['throw_time']),
        '-STARTGAME-': float(fishing['start_game_time']),
        '-GOLDENTUNA-': int(fishing['golden_tuna_action']),
    }
