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
    ES_DAGGERS_MAX,
    ES_DAGGERS_MIN,
    ES_JITTER_MAX,
    ES_JITTER_MIN,
    ES_MAXACT_MAX,
    ES_MAXACT_MIN,
    ES_PAUSE_MAX,
    ES_PAUSE_MIN,
    ES_STACK_MAX,
    ES_STACK_MIN,
    ES_UNVERIF_MAX,
    ES_UNVERIF_MIN,
    EVENT_WARN_MIN_MAX,
    GOLDEN_TUNA_ACTIONS,
    HOTKEY_TOKENS,
    INSTALL_ID_MAXLEN,
    KEYPOINT_KEYS,
    OVERLAY_OPACITY_MAX,
    OVERLAY_OPACITY_MIN,
    SPEED_PROFILES,
    TIMER_ACTIONS,
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
        # Zeitlimit-Aktion: nur die bekannten Werte; alles andere -> 'stop'
        # (Default, byte-stabiles historisches Verhalten).
        if fishing.get('timer_action') not in TIMER_ACTIONS:
            fishing['timer_action'] = DEFAULTS['fishing']['timer_action']
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
        # Angel-Whitelist: reines bool (fehlend/kaputt -> False). Strikt additiv,
        # default aus -> byte-stabiler Pfad (angelt alles).
        fishing['whitelist_enabled'] = bool(
            fishing.get('whitelist_enabled',
                        DEFAULTS['fishing']['whitelist_enabled']))
        # Koeder-Nachlegen: reines bool (fehlend/kaputt -> False). Strikt additiv,
        # default aus -> byte-stabiler Pfad (Bot prueft den Koeder-Slot nie).
        fishing['bait_refill_enabled'] = bool(
            fishing.get('bait_refill_enabled',
                        DEFAULTS['fishing']['bait_refill_enabled']))

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
        # Haertung (puzzle_safety): bools + color_stat-Enum sauber clampen.
        puzzle['verify_placements'] = bool(
            puzzle.get('verify_placements',
                       DEFAULTS['puzzle']['verify_placements']))
        puzzle['board_plausibility'] = bool(
            puzzle.get('board_plausibility',
                       DEFAULTS['puzzle']['board_plausibility']))
        puzzle['color_stat'] = _enum(
            puzzle.get('color_stat'), ('mean', 'median'),
            DEFAULTS['puzzle']['color_stat'])

        # Energiesplitter: drei Sub-Dicts (hammer/dagger/shared) clampen/enumen.
        merged['energiesplitter'] = _validate_energiesplitter(
            merged.get('energiesplitter'))

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
        # Vektorisierte Erkennung ist jetzt der einzige (bit-identische) Pfad und
        # der UI-Schalter ist entfallen. MIGRATION: ein frueher gespeichertes
        # False wird stillschweigend auf True gehoben -- es war nie eine bewusste
        # User-Wahl (nur ein Default-Schalter), und der vektorisierte Pfad liefert
        # dieselbe InventoryMap, nur schneller. Damit erscheint nach dem Update
        # niemand mehr versehentlich auf dem langsamen Schleifen-Pfad. Der
        # Schluessel bleibt als interner Debug-Default True erhalten.
        inventory['fast_recognition'] = True

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

        # Multiclient (1-4): count klemmen, Modi/HWNDs normalisieren. Die reine
        # Logik lebt in multiclient_settings (eine Wahrheit, headless-testbar).
        try:
            import multiclient_settings
            merged['multiclient'] = multiclient_settings.normalize_config(
                merged.get('multiclient'))
        except Exception:
            merged['multiclient'] = copy.deepcopy(DEFAULTS['multiclient'])

        return merged
    except Exception:
        return copy.deepcopy(DEFAULTS)


def _validate_energiesplitter(value):
    """Normalisiert den ``energiesplitter``-Block (hammer/dagger/shared).

    int/float werden geklemmt + auf ihren Typ gebracht, Enums via ``_enum``,
    bools via ``bool()``. Unbekannte Sub-Keys werden verworfen (es wird ein
    NEUES, vollstaendiges Dict aus den Defaults heraus aufgebaut). YANG spielt
    keine Rolle mehr (kein Preis/Floor/Spend). ``max_actions`` bleibt der
    Config-Wert (0 = auto); die Auto-Ableitung passiert in ``set_to_begin``
    (validate bleibt rein/deterministisch). Wirft nie.
    """
    src = value if isinstance(value, dict) else {}
    d_h = DEFAULTS['energiesplitter']['hammer']
    d_d = DEFAULTS['energiesplitter']['dagger']
    d_s = DEFAULTS['energiesplitter']['shared']
    src_h = src.get('hammer') if isinstance(src.get('hammer'), dict) else {}
    src_d = src.get('dagger') if isinstance(src.get('dagger'), dict) else {}
    src_s = src.get('shared') if isinstance(src.get('shared'), dict) else {}

    hammer = {
        'stack_count': int(_clamp(
            _coerce_int(src_h.get('stack_count'), d_h['stack_count']),
            ES_STACK_MIN, ES_STACK_MAX, d_h['stack_count'])),
        'energie_freischalten': bool(
            src_h.get('energie_freischalten', d_h['energie_freischalten'])),
    }
    dagger = {
        'daggers_per_round': int(_clamp(
            _coerce_int(src_d.get('daggers_per_round'), d_d['daggers_per_round']),
            ES_DAGGERS_MIN, ES_DAGGERS_MAX, d_d['daggers_per_round'])),
        'buy_mode': _enum(
            src_d.get('buy_mode'), ('chat', 'click'), d_d['buy_mode']),
        'buy_delay_s': float(_clamp(
            src_d.get('buy_delay_s'), 0.0, 3.0, d_d['buy_delay_s'])),
        'process_first': bool(src_d.get('process_first', d_d['process_first'])),
        'process_pickup_s': float(_clamp(
            src_d.get('process_pickup_s'), 0.0, 3.0, d_d['process_pickup_s'])),
        'process_confirm_s': float(_clamp(
            src_d.get('process_confirm_s'), 0.0, 3.0, d_d['process_confirm_s'])),
    }
    shared = {
        'speed_profile': _enum(
            src_s.get('speed_profile'), SPEED_PROFILES, d_s['speed_profile']),
        'mouse_pause': float(_clamp(
            src_s.get('mouse_pause'), ES_PAUSE_MIN, ES_PAUSE_MAX,
            d_s['mouse_pause'])),
        'keyboard_pause': float(_clamp(
            src_s.get('keyboard_pause'), ES_PAUSE_MIN, ES_PAUSE_MAX,
            d_s['keyboard_pause'])),
        'max_actions': int(_clamp(
            _coerce_int(src_s.get('max_actions'), d_s['max_actions']),
            ES_MAXACT_MIN, ES_MAXACT_MAX, d_s['max_actions']))
        if _coerce_int(src_s.get('max_actions'), d_s['max_actions']) != 0
        else 0,
        'consecutive_unverified_stop': int(_clamp(
            _coerce_int(src_s.get('consecutive_unverified_stop'),
                        d_s['consecutive_unverified_stop']),
            ES_UNVERIF_MIN, ES_UNVERIF_MAX,
            d_s['consecutive_unverified_stop'])),
        'jitter_pct': float(_clamp(
            src_s.get('jitter_pct'), ES_JITTER_MIN, ES_JITTER_MAX,
            d_s['jitter_pct'])),
        'inventory_pages': _validate_inventory_pages(
            src_s.get('inventory_pages')),
        'dry_run': bool(src_s.get('dry_run', d_s['dry_run'])),
    }
    return {'hammer': hammer, 'dagger': dagger, 'shared': shared}


def _validate_inventory_pages(value):
    """Freigegebene Inventar-Seiten -> sortierte int-Liste aus 1..4 (nie leer).

    Delegiert an die reine Logik (energiesplitter.inventory_pages); leeres/
    ungueltiges Ergebnis faellt fail-safe auf ALLE Seiten zurueck."""
    try:
        from energiesplitter import inventory_pages as _ip
        return list(_ip.normalize_pages(value))
    except Exception:
        return [1, 2, 3, 4]


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
    '_validate_size', '_validate_keypoints', '_validate_energiesplitter',
]
