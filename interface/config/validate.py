"""Validierung und Defaults-Merge fuer die Bot-Konfiguration.

Reine Logik-Schicht (nur :mod:`copy` aus der Standardbibliothek). Liest die
erlaubten Wertebereiche/Enums + das ``DEFAULTS``-Schema aus
:mod:`interface.config.defaults`.

Grundregeln:
  * Validierung klemmt Werte in den erlaubten Bereich und ersetzt ungueltige
    Enums durch ihren Default (statt zu werfen).
  * Immutabilitaet: ``merge_defaults``/``validate`` geben NEUE Dicts zurueck und
    veraendern ihre Eingabe nicht.
"""

import copy

from .defaults import (
    APP_MODES,
    COLOR_MODES,
    COLOR_PATCHES,
    DEFAULTS,
    DELAY_MAX,
    DELAY_MIN,
    DETECTION_MODES,
    EVENT_WARN_MIN_MAX,
    GOLDEN_TUNA_ACTIONS,
    HOTKEY_TOKENS,
    INSTALL_ID_MAXLEN,
    KEYPOINT_KEYS,
    OVERLAY_OPACITY_MAX,
    OVERLAY_OPACITY_MIN,
    PUZZLE_DELAY_MAX,
    PUZZLE_DELAY_MIN,
    SOLVER_MODES,
    TELEMETRY_INTERVAL_DEFAULT,
    TELEMETRY_INTERVAL_MAX,
    TELEMETRY_INTERVAL_MIN,
    URL_MAXLEN,
    USERNAME_MAXLEN,
    WEEKDAYS,
)


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


def _validate_hhmm(value, fallback):
    """Normalisiert eine 'HH:MM'-Zeit -> 'HH:MM' (00:00..23:59). Sonst
    ``fallback``. Wirft nie. Ergebnis ist immer zweistellig genullt."""
    try:
        hh, mm = str(value).split(':')
        hour = int(hh)
        minute = int(mm)
    except (TypeError, ValueError):
        return fallback
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return '{:02d}:{:02d}'.format(hour, minute)
    return fallback


def _validate_weekday(value, fallback):
    """Wochentag 0..6 (Mo=0..So=6). Ungueltig -> ``fallback``. Wirft nie."""
    try:
        day = int(value)
    except (TypeError, ValueError):
        return fallback
    return day if day in WEEKDAYS else fallback


def _validate_url(value, fallback):
    """Akzeptiert NUR eine ``https://``-URL (auf URL_MAXLEN gekappt), sonst
    ``fallback``.

    Telemetrie sendet Username + HWID + Stats -- die Spec verlangt HTTPS. Klartext
    ``http://`` (oder andere Schemata wie ftp:/javascript:/file:) wird daher
    abgelehnt und faellt auf den HTTPS-Default zurueck, damit nie versehentlich
    unverschluesselt gesendet wird. Bewusst minimal -- nur Schema + Laenge; KEIN
    Netzwerk-/DNS-Check (rein, offline-testbar). Wirft nie."""
    try:
        s = str(value).strip()
    except Exception:
        return fallback
    if not s:
        return fallback
    if not s.lower().startswith('https://'):
        return fallback
    return s[:URL_MAXLEN]


def _validate_install_id(value):
    """Normalisiert die zufaellige install_id -> gestrippter, kleingeschriebener
    String, auf INSTALL_ID_MAXLEN gekappt; '' bei None/Junk.

    Erzeugt NIE einen Wert (das uebernimmt die App/das Thin-Modul lazy), damit
    ``validate`` rein/deterministisch/idempotent bleibt (Tests). Wirft nie."""
    if value is None:
        return ''
    try:
        s = str(value).strip().lower()
    except Exception:
        return ''
    return s[:INSTALL_ID_MAXLEN]


def _validate_event_window(value, default):
    """Normalisiert EIN Event-Fenster ``{weekday,start,end}`` gegen ``default``.

    Jedes Feld faellt einzeln auf den passenden Default zurueck (nie werfen).
    Gibt immer ein NEUES, vollstaendiges Dict zurueck."""
    src = value if isinstance(value, dict) else {}
    return {
        'weekday': _validate_weekday(src.get('weekday'), default['weekday']),
        'start': _validate_hhmm(src.get('start'), default['start']),
        'end': _validate_hhmm(src.get('end'), default['end']),
    }


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
        # Bait lives in a QUICK-SLOT, so its key is FIXED to one of the only 8
        # quick-slot keys -- 1-4 (slots 1-4) / F1-F4 (slots 5-8); anything else
        # falls back to the default. This is what the settings dropdown offers
        # and the slot auto-refill drags the bait into. (cast/mount stay free.)
        if str(fishing['bait_key']).strip().lower() not in (
                '1', '2', '3', '4', 'f1', 'f2', 'f3', 'f4'):
            fishing['bait_key'] = DEFAULTS['fishing']['bait_key']
        fishing['cast_key'] = _validate_key(
            fishing.get('cast_key'), DEFAULTS['fishing']['cast_key'])
        # Mount: bool + Hotkey ueber denselben Validator wie Bait/Cast
        # (ungueltig -> Default '3'). Default AUS -> byte-stabil.
        fishing['mount_enabled'] = bool(fishing.get('mount_enabled', False))
        fishing['mount_key'] = _validate_key(
            fishing.get('mount_key'), DEFAULTS['fishing']['mount_key'])

        # Bot-Stop-Hotkey (frei waehlbare Taste, Default F6).
        controls = merged.setdefault('controls', {})
        controls['stop_hotkey'] = _validate_key(
            controls.get('stop_hotkey'), DEFAULTS['controls']['stop_hotkey'])

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
        # Force Deluxe: reines bool (ungueltig/fehlend -> False). Strikt
        # additiv; default aus -> byte-stabiler Pfad.
        puzzle['force_deluxe'] = bool(
            puzzle.get('force_deluxe', DEFAULTS['puzzle']['force_deluxe']))
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
        puzzle['step_delay'] = _clamp(
            puzzle.get('step_delay'),
            PUZZLE_DELAY_MIN, PUZZLE_DELAY_MAX,
            DEFAULTS['puzzle']['step_delay'])

        merged['log']['show_in_ui'] = bool(merged['log'].get('show_in_ui', True))

        window = merged['window']
        window['always_on_top'] = bool(window.get('always_on_top', False))
        window['minimize_to_tray'] = bool(window.get('minimize_to_tray', False))
        window['close_on_metin2_close'] = bool(
            window.get('close_on_metin2_close', False))
        window['close_on_timer_expire'] = bool(
            window.get('close_on_timer_expire', False))

        # Inventar: Hotkey ueber denselben Validator wie Bait/Cast ('i' gueltig;
        # ungueltig -> 'i'); Auto-Scan ist ein reines bool (vorerst gestubbt).
        inventory = merged.setdefault('inventory',
                                      copy.deepcopy(DEFAULTS['inventory']))
        inventory['hotkey'] = _validate_key(
            inventory.get('hotkey'), DEFAULTS['inventory']['hotkey'])
        inventory['auto_scan_after_fishing'] = bool(
            inventory.get('auto_scan_after_fishing', False))

        # -- Username (einzige PII): gestrippt + auf USERNAME_MAXLEN gekappt.
        try:
            name = str(merged.get('username', '')).strip()
        except Exception:
            name = ''
        merged['username'] = name[:USERNAME_MAXLEN]

        # -- Telemetrie: anonymer Immer-An-Zaehler. install_id (zufaellig)
        #    gestrippt/gekappt (NIE hier erzeugt). 'enabled' ist vestigial ->
        #    default True, KEIN Opt-out mehr. consented merkt die Onboarding-
        #    Entscheidung. URLs HTTPS-only, Intervall geklemmt.
        telemetry = merged.setdefault('telemetry',
                                      copy.deepcopy(DEFAULTS['telemetry']))
        telemetry['install_id'] = _validate_install_id(
            telemetry.get('install_id'))
        telemetry['enabled'] = bool(telemetry.get('enabled', True))
        telemetry['consented'] = bool(telemetry.get('consented', False))
        telemetry['submit_url'] = _validate_url(
            telemetry.get('submit_url'), DEFAULTS['telemetry']['submit_url'])
        telemetry['leaderboard_url'] = _validate_url(
            telemetry.get('leaderboard_url'),
            DEFAULTS['telemetry']['leaderboard_url'])
        interval = _coerce_int(telemetry.get('interval_s'),
                               TELEMETRY_INTERVAL_DEFAULT)
        telemetry['interval_s'] = int(_clamp(
            interval, TELEMETRY_INTERVAL_MIN, TELEMETRY_INTERVAL_MAX,
            TELEMETRY_INTERVAL_DEFAULT))

        # -- Fish-Event-Fenster: GENAU zwei (gegen die jeweiligen Defaults
        #    validiert), warn_minutes geklemmt (0=aus), Zeitzone fix.
        events = merged.setdefault('events', copy.deepcopy(DEFAULTS['events']))
        raw_windows = events.get('windows')
        if not isinstance(raw_windows, list):
            raw_windows = []
        default_windows = DEFAULTS['events']['windows']
        events['windows'] = [
            _validate_event_window(
                raw_windows[i] if i < len(raw_windows) else None,
                default_windows[i])
            for i in range(len(default_windows))
        ]
        warn = _coerce_int(events.get('warn_minutes'), 0)
        events['warn_minutes'] = int(_clamp(
            warn, 0, EVENT_WARN_MIN_MAX, 0))
        # Zeitzone bleibt fix auf Europe/Berlin (Spec) -- kein freies Feld.
        events['timezone'] = DEFAULTS['events']['timezone']

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


__all__ = [
    'merge_defaults', 'validate',
    '_clamp', '_enum', '_coerce_int', '_validate_key', '_validate_hhmm',
    '_validate_weekday', '_validate_url', '_validate_install_id',
    '_validate_event_window', '_deep_merge', '_validate_offset',
    '_validate_size', '_validate_keypoints',
]
