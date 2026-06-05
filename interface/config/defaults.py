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
# Wartezeit zwischen den Puzzle-State-Schritten (Sekunden), einstellbar.
PUZZLE_DELAY_MIN = 0.01
PUZZLE_DELAY_MAX = 1.0

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
# Random install-id (uuid4 hex = 32 Zeichen; str-Form 36) -- defensiv gekappt.
# Mirrort telemetry.hwid.INSTALL_ID_MAXLEN + server HWID_MAXLEN.
INSTALL_ID_MAXLEN = 64
# Plausibilitaets-Obergrenzen fuer die Statistik (nur zur Konsistenz; der Server
# validiert hart -- hier nur, damit die UI/der Sender nichts Absurdes anzeigt).
STATS_MAX_COUNT = 100_000_000        # 100 Mio Faenge/Puzzles
STATS_MAX_RUNTIME_S = 100_000_000.0  # ~3 Jahre Laufzeit in Sekunden

# Live-Telemetrie-Endpoint (eigene Subdomain auf dem netcup-Server, isolierter
# Container hinter kilab-nginx + Let's-Encrypt). Der anonyme Zaehler sendet erst,
# wenn eine echte URL gesetzt ist (hier immer der Fall).
DEFAULT_SUBMIT_URL = 'https://telemetry.musketier.net/submit'
DEFAULT_LEADERBOARD_URL = 'https://telemetry.musketier.net/leaderboard'

# Stabile Position: NEBEN der EXE (frozen/Portable) bzw. 'config.json' im CWD
# (Dev/Test). Der frueher nackte CWD-Pfad liess die Portable-EXE bei jedem Start
# die Config verlieren (Re-Onboarding + neue install_id). Siehe paths.py.
from .paths import config_path as _config_path  # noqa: E402

DEFAULT_CONFIG_PATH = _config_path()

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
        # Angel-Whitelist (opt-in): liest beim Biss den Chat-Streifen und bricht
        # das Minispiel ab, wenn der Fang im Inventar als "entfernen" markiert ist
        # (oder eine Niete). Default AUS -> angelt ALLES -> byte-stabil. Welche
        # Fische gewollt sind, kommt aus den Inventar-3-Zustaenden (KEEP/CAMPFIRE
        # = angeln, REMOVE = abbrechen), die der RunLoop auf die Bot-Instanz
        # injiziert (kein eigener Config-Block noetig).
        'whitelist_enabled': False,
        # Koeder-Nachlegen (opt-in): erkennt der Bot waehrend des Angelns den
        # Koeder-Quickslot (= der bait_key-Slot) leer, legt er EINEN Koeder aus
        # dem Inventar nach (refill.refill_from_inventory). Ist kein Koeder mehr
        # da, stoppt der Bot mit klarem Hinweis. Default AUS -> byte-stabil (der
        # Bot prueft den Slot dann nie). Reuse der fertigen Engine interface/
        # refill.py; der RunLoop injiziert wincap/db/calib analog zur Whitelist.
        'bait_refill_enabled': False,
    },
    'puzzle': {
        'detection_mode': 'default',
        'mark_offset': None,
        'mark_size': None,
        'mark_keypoints': {},
        'color_mode': 'single',
        'color_patch': 3,
        'solver_mode': 'standard',
        # Force Deluxe (V3-Reservat-Strategie): reserviert ein 2x3-Feld fuer den
        # Deluxe-Stein -> mehr grosse 25+-Boxen. Nur wirksam bei 'trained' +
        # vorhandener Deluxe-Box. Default AUS -> Verhalten unveraendert.
        'force_deluxe': False,
        'overlay_opacity': 0.85,  # Deckkraft Mark-/Vorschau-Overlay (0.4..1.0)
        'step_delay': 0.1,        # Wartezeit zwischen Puzzle-Schritten (0.01..1.0 s)
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
        # Vektorisierte Erkennung -- jetzt der EINZIGE Pfad (kein UI-Schalter mehr).
        # Statt die 45 Slots/Seite einzeln in einer Python-Schleife zu matchen,
        # wird die maskierte Differenz fuer ALLE Slots einer Seite in EINER
        # gebatchten numpy-Operation berechnet (s. inventory.itemdb.
        # match_page_distances) und die 4 Seiten ueberlappen im Thread-Pool.
        # Ergebnis ist BIT-IDENTISCH zum Schleifen-Pfad (gleiche InventoryMap),
        # nur schneller -> als Default sicher. Die Validierung migriert ein
        # frueheres False stillschweigend auf True (es war nie eine bewusste
        # User-Wahl); der Schluessel bleibt nur als interner Debug-Default
        # erhalten, falls man den Schleifen-Pfad je wieder einschalten will.
        'fast_recognition': True,
    },
    # Selbstgewaehlter Ranking-Name (einzige "PII"). Leer = anonym (man erscheint
    # unter dem generierten Anon-Namen). Setzen = Opt-in, diesen Namen zu zeigen.
    # Wird NICHT in to_values gereicht -- die Telemetrie liest ihn direkt aus der
    # Config.
    'username': '',
    # Ranking-Telemetrie: ANONYMER, IMMER-AN Zaehler (keine Opt-out-Wahl mehr).
    #   * install_id: zufaellige uuid4, EINMAL beim ersten Lauf erzeugt + hier
    #     gespeichert (leer = noch nicht erzeugt; wird beim ersten Senden lazy
    #     gefuellt). KEINE Hardware-/Geraete-Ableitung.
    #   * enabled: VESTIGIAL (Rueckwaerts-Kompat alter config.json) -- default
    #     True, wird NICHT mehr als Opt-out-Gate gelesen. Das echte "senden wir?"
    #     ist: install_id + submit_url vorhanden UND nicht blockiert.
    #   * consented: merkt, dass das Onboarding entschieden wurde -> Dialog nur
    #     EINMAL.
    'telemetry': {
        'install_id': '',
        'enabled': True,
        'consented': False,
        'submit_url': DEFAULT_SUBMIT_URL,
        'leaderboard_url': DEFAULT_LEADERBOARD_URL,
        'interval_s': TELEMETRY_INTERVAL_DEFAULT,
        # One-shot: the "rate this on GitHub" prompt is shown ONCE after the
        # 10th solved puzzle; this flag (set then) keeps it from re-appearing.
        'rating_prompted': False,
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
    # Bot-Stop-Hotkey -- global gepollt (GetAsyncKeyState) im Tick, wirkt auch
    # wenn das Spiel den Fokus hat. Default F6, in den Einstellungen aenderbar
    # und im laufenden Stop-Button angezeigt.
    'controls': {
        'stop_hotkey': 'f6',
    },
}


__all__ = [
    'DETECTION_MODES', 'COLOR_MODES', 'SOLVER_MODES', 'APP_MODES',
    'COLOR_PATCHES', 'GOLDEN_TUNA_ACTIONS', 'KEYPOINT_KEYS',
    'DELAY_MIN', 'DELAY_MAX', 'OVERLAY_OPACITY_MIN', 'OVERLAY_OPACITY_MAX',
    'PUZZLE_DELAY_MIN', 'PUZZLE_DELAY_MAX',
    'HOTKEY_TOKENS', 'WEEKDAYS', 'EVENT_WARN_MIN_MAX',
    'TELEMETRY_INTERVAL_MIN', 'TELEMETRY_INTERVAL_MAX',
    'TELEMETRY_INTERVAL_DEFAULT', 'USERNAME_MAXLEN', 'URL_MAXLEN',
    'INSTALL_ID_MAXLEN',
    'STATS_MAX_COUNT', 'STATS_MAX_RUNTIME_S',
    'DEFAULT_SUBMIT_URL', 'DEFAULT_LEADERBOARD_URL', 'DEFAULT_CONFIG_PATH',
    'DEFAULTS',
]
