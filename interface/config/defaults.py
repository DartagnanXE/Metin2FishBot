"""Default-Schema und erlaubte Wertebereiche/Enums fuer die Bot-Konfiguration.

Reine Daten-/Konstanten-Schicht (NUR :mod:`copy` aus der Standardbibliothek fuer
den ``DEFAULTS``-Schutz). Bewusst toolkit-frei, damit ueberall importier- und
testbar -- auch headless und aus der gepackten ``.exe`` heraus.

Diese Konstanten sind die EINE Wahrheit ueber erlaubte Werte; sowohl die
Validierung (:mod:`interface.config.validate`) als auch die UI lesen von hier.
"""

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

# -- Fish-Event-Fenster + Telemetrie (Run 1) --------------------------------
# Wochentage 0..6 (Montag=0 .. Sonntag=6, wie datetime.weekday()).
WEEKDAYS = (0, 1, 2, 3, 4, 5, 6)
# "Warnung N Minuten vor Ende" -- 0 = aus, max 24h.
EVENT_WARN_MIN_MAX = 1440
# Telemetrie-Sendeintervall (Sekunden): nicht zu aggressiv (Server-Last) und
# nicht laenger als ~1h. Default 120s (Spec).
TELEMETRY_INTERVAL_MIN = 30
TELEMETRY_INTERVAL_MAX = 3600
TELEMETRY_INTERVAL_DEFAULT = 120
# Laengenkappen (defensiv -- ein kaputtes Feld darf nichts Riesiges erzeugen).
USERNAME_MAXLEN = 32
URL_MAXLEN = 300
# Plausibilitaets-Obergrenzen fuer die Statistik (nur zur Konsistenz; der Server
# validiert hart -- hier nur, damit die UI/der Sender nichts Absurdes anzeigt).
STATS_MAX_COUNT = 100_000_000        # 100 Mio Faenge/Puzzles
STATS_MAX_RUNTIME_S = 100_000_000.0  # ~3 Jahre Laufzeit in Sekunden

# Platzhalter-URLs (KEIN Live-Server in Run 1). Der Nutzer/Build traegt die echte
# Subdomain ein; der Sender ist ohnehin opt-in + standardmaessig AUS.
DEFAULT_SUBMIT_URL = 'https://ranking.example.tld/submit'
DEFAULT_LEADERBOARD_URL = 'https://ranking.example.tld/leaderboard'

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
        # Mount-Animation-Cancel (opt-in): nach jedem Minispiel auf-/absteigen,
        # um die Fang-Animation abzubrechen -> schnelleres Neu-Auswerfen.
        # Default AUS + Taste '3' -> Verhalten byte-stabil.
        'mount_enabled': False,
        'mount_key': '3',
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
    'inventory': {                # Inventar-Scan: Hotkey + (gestubbter) Auto-Scan
        'hotkey': 'i',            # In-Game-Taste, die das Inventar oeffnet
        'auto_scan_after_fishing': False,  # vorerst nur Setting + Roadmap
    },
    # Selbstgewaehlter Ranking-Name (einzige "PII"). Leer = noch nicht gewaehlt
    # (Onboarding-Dialog beim ersten Start). Wird NICHT in to_values gereicht --
    # die Telemetrie liest ihn direkt aus der Config.
    'username': '',
    # Ranking-Telemetrie: standardmaessig AUS (GDPR-Opt-in). consented merkt sich,
    # dass der Nutzer im Onboarding entschieden hat (egal ob ja/nein) -> der
    # Dialog erscheint nur EINMAL.
    'telemetry': {
        'enabled': False,
        'consented': False,
        'submit_url': DEFAULT_SUBMIT_URL,
        'leaderboard_url': DEFAULT_LEADERBOARD_URL,
        'interval_s': TELEMETRY_INTERVAL_DEFAULT,
    },
    # Fish-Event-Fenster (zwei). Defaults laut Spec: Sonntag(6) 12:00-16:00 und
    # Mittwoch(2) 00:00-12:00, Zeitzone Europe/Berlin (DST-korrekt). warn_minutes
    # = Warnung N Minuten vor Ende (0 = aus). Die Zeitlogik liegt PUR in
    # event_window.py.
    'events': {
        'windows': [
            {'weekday': 6, 'start': '12:00', 'end': '16:00'},
            {'weekday': 2, 'start': '00:00', 'end': '12:00'},
        ],
        'warn_minutes': 0,
        'timezone': 'Europe/Berlin',
    },
}


__all__ = [
    'DETECTION_MODES', 'COLOR_MODES', 'SOLVER_MODES', 'APP_MODES',
    'COLOR_PATCHES', 'GOLDEN_TUNA_ACTIONS', 'KEYPOINT_KEYS',
    'DELAY_MIN', 'DELAY_MAX', 'OVERLAY_OPACITY_MIN', 'OVERLAY_OPACITY_MAX',
    'HOTKEY_TOKENS', 'WEEKDAYS', 'EVENT_WARN_MIN_MAX',
    'TELEMETRY_INTERVAL_MIN', 'TELEMETRY_INTERVAL_MAX',
    'TELEMETRY_INTERVAL_DEFAULT', 'USERNAME_MAXLEN', 'URL_MAXLEN',
    'STATS_MAX_COUNT', 'STATS_MAX_RUNTIME_S',
    'DEFAULT_SUBMIT_URL', 'DEFAULT_LEADERBOARD_URL', 'DEFAULT_CONFIG_PATH',
    'DEFAULTS',
]
