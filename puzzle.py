import pydirectinput
pydirectinput.PAUSE = 0.05  # fast, but down->up MUST stay held >~1 frame or the game IGNORES the key/click (PAUSE=0 = 0ms hold = not registered); 0.05 = ~3 frames
import cv2 as cv
from time import time, sleep
from windowcapture import WindowCapture
from tetris import Tetris
from piece import Piece
import json
import constants
import calibration
import deluxe
import geometry
import trained_solver
import puzzle_safety
from copy import deepcopy
from debuglog import log
from respath import resource_path
from i18n import t
from interface.config.paths import debug_log_path
from puzzle_detect import PuzzleDetectMixin

# Box-Nachlegen: ENTFERNT in v1.3. Eine leere Standard-Box wird nicht mehr aus
# dem Inventar nachgelegt, sondern das Spiel via Event-Uebersicht NEU GEOEFFNET
# (ESC -> Strg+E -> FISCHPUZZLESPIEL-Label klicken). Die generische
# Event-Open-Erkennung (NCC-Templates, positionsunabhaengig) liegt im getesteten
# seher.flow-Modul und wird hier READ-ONLY mitbenutzt (gleiche Pipeline wie der
# Seherwettstreit-Selbststart). Soft importiert -> fehlt cv2/numpy bleibt
# puzzle.py headless importierbar und der Selbststart einfach inaktiv.
import stop_signal as _stopsig
try:
    from seher import flow as _flow
except Exception:  # pragma: no cover - nur ohne cv2/numpy
    _flow = None
# Fenster-Fokus fuer das Inventar-Oeffnen: pydirectinput-TASTEN gehen ans
# fokussierte Fenster. Das Puzzle spielt nur mit KLICKS (positionsbasiert,
# fokus-frei) -> das Spiel hat beim Puzzle i.d.R. KEINEN Tastatur-Fokus, der
# Inventar-Hotkey ginge sonst ins Leere (Ursache "Inventar nicht als offen
# verifizierbar"). Soft importiert -> headless ein No-op.
try:
    from windowcapture import focus_window as _focus_window
except Exception:  # pragma: no cover
    _focus_window = None

# Nach so vielen Verwerfen IN FOLGE (ohne Platzierung dazwischen) gilt der
# box-optimale Loeser als "festgefahren" (wartet auf einen perfekten Stein) und
# schaltet auf FINISH-Modus (irgendeinen least-bad Stein platzieren), damit das
# Brett fertig wird statt Boxen endlos zu verwerfen.
FINISH_AFTER_DISCARDS = 3

# Wartezeit (Sekunden) zwischen den Puzzle-State-Schritten (Maus bewegen, klicken,
# Spiel rendern lassen). War fest 0.2s -> ~6 Schritte/Stein = ~1.2s/Stein. 0.1s
# halbiert das (~2x schneller) und bleibt fuer das Client-Rendering robust; bei
# Bedarf hier feinjustieren.
PUZZLE_STEP_DELAY = 0.1

# Wie lange State 4 die Stein-Farbe WIEDERHOLT liest, bevor ein Nicht-Treffer
# als "ungueltiger Stein" verworfen wird (Sekunden). LIVE GEMESSEN 2026-06-10:
# ~0.1-0.3s nach dem Holen ist der Stein oft noch nicht gerendert -> der alte
# EINMAL-Read las das Hintergrund-Grau (31,34,36) bzw. einen Uebergangsframe
# und der Bot warf jeden Stein sofort weg. Jeder Frame liest ein FRISCHES
# Capture; der Wert deckt die Render-/Animations-Verzoegerung ab, ohne den
# Treffer-Pfad zu verlangsamen (Erfolg beendet die Schleife sofort).
# 1.0s (vorher 2.0): bei einem ECHTEN Stein endet die Schleife nach dem ersten
# gerenderten Frame -> die 2s wurden NUR bei LEEREN Boxen voll ausgereizt und
# verzoegerten die Leer-Erkennung. 1.0s ist ggue. ~0.3s Renderzeit noch >3x
# Polster; der Streak=2-Debounce faengt einen einzelnen Aussetzer ohnehin ab
# (User: Leer-Erkennung soll schnell weitergehen).
PIECE_COLOR_RETRY_S = 1.0

# -- Haertung (Sicherheits-Schicht, puzzle_safety) ------------------------
# (FINISH_HARD_CAP / FINISH_AFTER_DISCARDS [oben]: der Finish-Modus wurde
# 2026-06-17 ENTFERNT -- siehe play_game. Der Bot spielt jetzt durchgehend die
# beweisbar optimale Policy [nur legen wenn V strikt sinkt]; Monte-Carlo-belegt.)
FINISH_HARD_CAP = 10
# Safe-Fail: so viele Verwerfen IN FOLGE ohne jede Platzierung -> sauberer Stop
# (gegen ein echtes HAENGEN, z.B. ein Stein wird DAUERHAFT fehl-erkannt). Wert
# 120 per Monte-Carlo kalibriert: das OPTIMALE Spiel braucht hoechstens ~62
# Verwerfen in Folge (1/100k Spiele) und NIE >= 120 (0/100k) -> dieser Backstop
# stoppt also NIE legitimes optimales Warten ("keine Grenzen", Nutzer-Vorgabe),
# faengt aber eine echte Dauer-Fehlerkennung in endlicher Zeit ab.
DISCARD_STOP_LIMIT = 120
# Konfidenz-Gate (Toleranz-Fallback der Stein-Erkennung): Mindest-Farbabstand
# (euklidisch) zum zweitnaechsten Zentroid, sonst lieber verwerfen als raten.
PIECE_MIN_MARGIN = 30.0
# Brett-Plausibilitaet: ab so vielen "Garbage"-Zellen (belegt, aber KEINE echte
# Steinfarbe) gilt die Brett-Lesung als verdaechtig -> kurzes Re-Read-Fenster.
# Wert 4 (nicht 2): legitime UI-Ueberlagerungen (Cursor/Tooltip/Animation) ueber
# 1-3 Zellen loesen KEINEN Re-Read mehr aus -> kein unnoetiger 0.6s-Verzug pro
# Stein. Echte Fehl-Lesungen (verschobenes Fenster) faerben viele Zellen garbage.
BOARD_MAX_GARBAGE = 4
BOARD_READ_RETRY_S = 0.6

# -- Leere Box -> Spiel via Event neu oeffnen (v1.3) ----------------------
# So viele leere getpiece IN FOLGE (kein Stein erschienen) gelten als "Box im
# Puzzle-Slot leer" -> Spiel neu oeffnen (ESC -> Event-Uebersicht ->
# FISCHPUZZLESPIEL). 2 deckt einen EINZELNEN Render-/Lese-Aussetzer ab (ein
# echter Stein liest sich beim naechsten Frame), laesst den Bot bei echter Leere
# aber schnell (~1 Zyklus Polster) reagieren statt sekundenlang ins Leere zu
# klicken.
BOX_EMPTY_STREAK = 2
# So oft darf das Spiel wegen leerer Boxen NEU geoeffnet werden, OHNE dass dazwischen
# Fortschritt (ein erfolgreich gelesener Stein) passiert, bevor hart gestoppt wird.
# WICHTIG: Der Zaehler wird bei JEDEM erfolgreichen Stein-Read auf 0 zurueckgesetzt
# (s. Stein-Erfolgs-Pfad) -> er zaehlt nur AUFEINANDERFOLGENDE Neustarts OHNE
# Fortschritt = das echte "Boxen aufgebraucht". PRODUKTIVE Neustarts (Nachlegen ->
# weiterspielen) sind damit UNBEGRENZT (User-Vorgabe: unendliche Durchlaeufe bis
# wirklich leer/verifiziert). 1 reicht: bleiben die Boxen NACH einem frischen
# Event-Oeffnen SOFORT wieder leer (kein einziger Stein), sind sie wirklich
# aufgebraucht. Verhindert weiter die Endlosschleife ESC -> oeffnen -> leer.
BOX_REOPEN_MAX = 1

# -- Magenta-Leer-Erkennung der Deluxe-Box (Deluxe-SPIELEN bleibt) ---------
# So oft darf das Oeffnen der Deluxe-Box KEINEN Magenta-Stein liefern, bevor die
# Deluxe-Nutzung fuer den Lauf abgeschaltet wird (NORMALES Spiel laeuft weiter,
# kein Stop). 2 = ein einzelner Render-/Lese-Aussetzer ist ok. (Deluxe-NACHLEGEN
# aus dem Inventar wurde in v1.3 entfernt; die reaktive Leer-Erkennung bleibt,
# damit Force-Deluxe sich bei wirklich leerer Box sauber selbst abschaltet.)
DELUXE_MISS_LIMIT = 2

# -- Selbststart-/Reopen-Flow (Event-Uebersicht) --------------------------
# Strg+E-Toggle-Versuche, bis die Eventuebersicht offen ist (Seher-Lektion:
# DirectInput verschluckt Modifier-Combos -> Retry).
CTRL_E_RETRIES = 3
# Render-Floor (Sekunden) nach Strg+E / ESC / Label-Klick, bevor neu geprueft
# wird (uebernommen aus dem Seher-Flow FLOW_PACE_S).
FLOW_PACE_S = 0.75
# Wie lange nach dem Label-Klick auf das offene Brett gepollt wird (der Client
# rendert das Puzzle nicht sofort). Innerhalb des Fensters liest jeder Versuch
# ein FRISCHES Capture; danach gilt der Reopen als gescheitert (mit Diagnose).
BOARD_OPEN_POLL_S = 4.0
# NCC-Schwelle der Label-/Header-Erkennung (Seher-Konvention, seher.flow):
# self-Match ~1.0, andere Eventzeilen/Fenstertitel < 0.5 am Kalibrierbild ->
# +0.34 Abstand. Live-Render-Unterschiede koennen echte Treffer auf ~0.85
# druecken; 0.82 haelt Spielraum. Jeder Knapp-daneben-Fall ist via
# seher.flow.diagnose im Log sichtbar.
FLOW_NCC_MIN = 0.82
# Wie oft pro Tick maximal versucht wird, das Spiel selbst zu oeffnen, bevor mit
# Diagnose gestoppt wird (Selbststart-Cap gegen Endlos-Oeffnen ohne Erfolg).
GAME_OPEN_MAX_TRIES = 3


fish_jigsaw_chest = cv.imread(resource_path("images/fish_jigsaw_chest.png"))

class PuzzleBot(PuzzleDetectMixin):

    #properties
    
    botting = False

    PUZZLE_WINDOW_SIZE = (260, 170)
    PUZZLE_WINDOW_POSITION = (270, 227)

    PUZZLE_GET_NEW_PIECE = (230, 85)
    PUZZLE_COMFIRM = (100, 90)
    PUZZLE_GET_NEW_PIECE_COLOR = (110, 150)

    # Box-Klickpunkte im 800x600-Client (volle Fenster-Inhalts-Koordinaten, NICHT
    # board-relativ): die STANDARD-Puzzlebox liegt im unteren Slot ~ (503, 328),
    # die DELUXE-Box im Slot DARUEBER ~ (503, 271). Geliefert wird nur die
    # Konstante (+ _deluxe_box_screen_point/_standard_box_screen_point fuer den
    # Bildschirm-Punkt inkl. wincap-Rand); die Box-OEFFNUNGS-/Strategie-Logik
    # ist bewusst NICHT Teil dieses Moduls.
    PUZZLE_BOX = (503, 328)
    PUZZLE_DELUXE_BOX = (503, 271)

    # Aktiv genutzter Board-Offset (oben-links der 260x170-Region im
    # Fensterinhalt). Default = feste Standardposition; die Integration
    # (hack.py) ueberschreibt dieses INSTANZ-Attribut zur Laufzeit mit dem aus
    # dem gewaehlten Detection-Modus aufgeloesten Offset
    # (detection.resolve_offset). puzzle.py importiert detection NICHT (kein
    # Importzyklus B<->C) -- der Offset wird von aussen injiziert.
    puzzle_offset = PUZZLE_WINDOW_POSITION

    # Aktiv genutzte Board-Groesse (Breite, Hoehe). Default = bewaehrte
    # 800x600-Referenz (260x170). Die Integration (hack.py) kann eine manuell
    # markierte Groesse setzen (variable Fenstergroessen); alle Sample-/Klick-
    # Koordinaten werden dann ueber geometry.py linear daraus abgeleitet. Bei
    # 260x170 ist die Ableitung die Identitaet -> byte-stabil zum Bisherigen.
    board_size = PUZZLE_WINDOW_SIZE

    # Optionale kalibrierte Referenz-Overrides fuer die 4 Sonderpunkte
    # (color/getpiece/confirm/cake). Default = leeres Dict -> keine Overrides ->
    # geometry.py nutzt seine REF_*-Konstanten -> byte-stabil. Die Integration
    # (hack.py) injiziert hier im 'mark'-Modus die im Overlay gesetzten
    # Referenzkoordinaten (auf 260x170 normiert, vgl. geometry.pixel_to_ref);
    # die Aufrufstellen reichen sie per self.key_points.get(name) durch.
    key_points = {}

    # -- Umschaltbare Verfahren (von der Integration aus config.json gesetzt) --
    # color_mode : 'single' = aktuelles Verhalten (1 Pixel/Zelle, enge BGR-
    #              Fenster, byte-stabil). 'multi' = Patch-Mittelwert + naechste
    #              Referenzfarbe.
    # color_patch: Kantenlaenge des Patches im 'multi'-Modus (3 oder 5).
    # solver_mode: 'standard' = Greedy (tetris.py) direkt. 'trained' = ueber
    #              trained_solver.choose_placement (vorerst verhaltensgleich).
    color_mode = 'single'
    color_patch = 3
    solver_mode = 'standard'

    # -- Haertung: umschaltbare Schutz-Schichten (puzzle_safety) ----------
    # color_stat: Statistik des 'multi'-Patches -- 'mean' (DEFAULT, byte-stabil
    #             zum bisherigen Verhalten) oder 'median' (robust gegen ein
    #             einzelnes Glanz-/Cursor-Pixel; empfohlen NACH Live-Test). Wirkt
    #             NUR im 'multi'-Modus; 'single' bleibt ohnehin 1 Pixel.
    # verify_placements: Closed-Loop -- erwartetes Footprint gegen das in der
    #             naechsten Runde frisch gelesene Brett pruefen und Abweichungen
    #             loggen (reine Beobachtung, aendert kein Verhalten).
    # board_plausibility: belegte Zellen ohne echte Steinfarbe als "Garbage"
    #             zaehlen und bei Verdacht das Brett kurz neu lesen.
    color_stat = 'mean'
    verify_placements = True
    board_plausibility = True

    # -- Force Deluxe (V3-Reservat-Strategie, opt-in) ---------------------
    # force_deluxe: reserviert ein festes 2x3-Feld (deluxe.reservat_2x3) und
    # laesst den trainierten Solver NUR die 18 anderen Zellen fuellen; der
    # Deluxe-Stein (Magenta 2x3) fuellt das Reservat. Maximiert grosse 25+-Boxen
    # (siehe deluxe.py + UI-Hilfetext). NUR wirksam, wenn solver_mode=='trained'
    # UND mindestens 1 Deluxe-Box im Inventar liegt -- sonst laeuft der normale
    # trained-Modus (kein Reservat). Default AUS -> Verhalten byte-stabil.
    # Wird von run_loop.apply_puzzle_config aus der Config gesetzt.
    force_deluxe = False

    # Referenz-BGR-Zentroide der 6 Steintypen fuer den 'multi'-Modus
    # (naechste-Referenzfarbe). Abgeleitet aus den Mittelpunkten der engen
    # BGR-Fenster in get_new_piece_color (single-Pfad) -- so klassifiziert
    # 'multi' dieselben Farben, nur robuster gegen leichte Drift.
    PIECE_REF_BGR = {
        4: (37, 65, 250),    # b35-40  g60-70   r240-260
        1: (25, 160, 250),   # b20-30  g150-170 r240-260
        5: (42, 250, 42),    # b35-50  g240-260 r35-50
        3: (250, 250, 25),   # b240-260 g240-260 r20-30
        2: (250, 107, 0),    # b240-260 g100-115 r~0
        6: (55, 245, 255),   # b50-60  g235-255 r250-260
    }

    wincap = None

    tetris = Tetris()

    timer_action = time()

    get_piece_time = 2

    new_piece = None

    # Farb-Lese-Retry (State 4): Deadline + Einmal-Log-Flagge pro Lese-Zyklus.
    _color_retry_until = 0.0
    _color_read_announced = False

    # -- Haertung: Laufzeit-Zustand der Schutz-Schichten ------------------
    # Closed-Loop: nach einer Platzierung gemerktes Soll-Brett + Metadaten,
    # gegen die die naechste frische Brett-Lesung geprueft wird.
    _expected_board = None
    _expected_meta = None
    # Brett-Plausibilitaet: Garbage-Zaehlung der letzten Lesung + Re-Read-Deadline.
    _last_board_garbage = 0
    _board_retry_until = 0.0

    # -- Leere Box -> Spiel neu oeffnen (v1.3; Default-Verhalten) -----------
    stop_signal = _stopsig.NULL_SIGNAL  # gemeinsames Stop-Signal (F6)
    _empty_getpiece_streak = 0        # leere getpiece IN FOLGE (Box-leer-Signal)
    _box_reopen_tries = 0             # so oft schon wegen leerer Box neu geoeffnet
    _game_open_tries = 0             # Selbststart-Versuche im laufenden Tick (Cap)

    # -- Opportunistische Deluxe-Nutzung (Laufzeit-Zustand; SPIELEN bleibt) -
    _awaiting_deluxe = False          # gerade die Deluxe-Box geoeffnet? (Magenta erwartet)
    _deluxe_miss_streak = 0           # Deluxe geoeffnet, aber KEIN Magenta -> Zaehler
    _deluxe_disabled = False          # nach zu vielen Fehlversuchen fuer den Lauf aus

    state = 0

    end = False
    dictdump = None

    def set_to_begin(self, values):
        # Logdatei pro Lauf frisch initialisieren (auch aus der .exe nutzbar).
        # Stabiler Pfad (frozen -> %APPDATA%) statt CWD-relativ, s. debug_log_path.
        log.configure(to_console=True, to_file=True,
                      path=debug_log_path(), level='DEBUG')
        log.section(t('puzzle.start_section'))
        self.wincap = WindowCapture(constants.GAME_NAME)
        self.state = 0
        self._discard_streak = 0      # Verwerfen-in-Folge (Finish-Modus-Trigger)
        self._fd_avail_cache = None   # Force-Deluxe: Box-Verfuegbarkeits-Cache
        # Haertung: Closed-Loop-/Plausibilitaets-Zustand pro Lauf zuruecksetzen.
        self._expected_board = None
        self._expected_meta = None
        self._last_board_garbage = 0
        self._board_retry_until = 0.0
        # Leere-Box-/Selbststart-Zustand pro Lauf frisch (sonst zaehlt ein alter
        # Lauf weiter -> verfruehter Reopen-Stop / Open-Cap).
        self._empty_getpiece_streak = 0
        self._box_reopen_tries = 0
        self._game_open_tries = 0
        # Opportunistische Deluxe-Nutzung pro Lauf zuruecksetzen (SPIELEN bleibt).
        self._awaiting_deluxe = False
        self._deluxe_miss_streak = 0
        self._deluxe_disabled = False
        # Offset auf den Klassen-Default zuruecksetzen; die Integration setzt
        # danach den aus dem Detection-Modus aufgeloesten Offset (falls
        # abweichend). Garantiert einen wohldefinierten Startwert pro Lauf.
        self.puzzle_offset = self.PUZZLE_WINDOW_POSITION
        # Sonderpunkt-Overrides auf neutral zuruecksetzen (analog zum Offset-
        # Reset); die Integration injiziert danach ggf. die kalibrierten
        # Referenzen. Leeres Dict -> geometry-Defaults -> byte-stabil.
        self.key_points = {}
        with open(resource_path('pieces_second.json')) as handle:
            self.dictdump = json.loads(handle.read())
        # KI-Wertfunktion EINMALIG vorab laden, BEVOR der erste Zug sie braucht.
        # Sonst blockiert der erste 'KI optimiert'-Zug ~19s mit der Berechnung
        # (sah aus wie "haengt beim ersten Start"). Die gebuendelte trained_V.npz
        # laedt in ~0.2s; nur fuer den trained-Modus relevant. Wirft nie.
        if getattr(self, 'solver_mode', '') == 'trained':
            try:
                log.event(self.state, t('puzzle.loading_ai_model'))
                trained_solver.load_V()
                log.event(self.state, t('puzzle.ai_model_ready'))
            except Exception:
                pass

    # Die reinen Vision-Bausteine _sample_cell_bgr / _classify_piece /
    # _is_valid_piece_color / _diagnose_board / detect_end_game liefert der
    # PuzzleDetectMixin (oben eingemischt) -- gleiche Methodenaufloesung, gleicher
    # self.-Zustand. Hier verbleibt die Solver-Glue-/Klick-State-Machine.

    def set_puzzle_state(self, crop_img):

        board = [[0,0,0,0,0,0],
                [0,0,0,0,0,0],
                [0,0,0,0,0,0],
                [0,0,0,0,0,0]]

        garbage = 0
        for i in range(0, 4):
            for j in range(0, 6):
                cx, cy = geometry.cell_point(i, j, self.board_size)
                # Zellfarbe ueber den umschaltbaren Sampler holen: 'single' =
                # exakt der eine Pixel (byte-stabil), 'multi' = Patch-Mittel.
                cb, cg, cr = self._sample_cell_bgr(crop_img, cx, cy)
                # Leer-Schwelle unveraendert (alle Kanaele < 50 => leere Zelle).
                if cb < 50 and cg < 50 and cr < 50:
                    board[i][j] = 0
                else:
                    board[i][j] = 1
                    # Plausibilitaet (④): eine belegte Zelle MUSS eine echte
                    # Steinfarbe sein. Belegt-aber-keine-Steinfarbe = Garbage
                    # (Cursor/Tooltip/Truhe/Animation ueber der Zelle) -> die
                    # binaere Belegung allein wuerde das fuer "belegt" halten.
                    if self.board_plausibility and not self._is_valid_piece_color(
                            cb, cg, cr):
                        garbage += 1

                cv.rectangle(crop_img, (cx, cy), (cx, cy),
                            color=(0, 255, 255), thickness=4, lineType=cv.LINE_4)

        self._last_board_garbage = garbage

        # Closed-Loop (①): das in der VORrunde gesetzte Soll-Brett gegen das
        # jetzt frisch gelesene Ist-Brett pruefen, BEVOR es ueberschrieben wird.
        # Reine Beobachtung -- die Re-Synchronisation (frische Lesung) bleibt der
        # eigentliche Schutz; hier wird sie nur AUDITIERBAR gemacht.
        if self.verify_placements and self._expected_board is not None:
            self._verify_last_placement(board)
        self._expected_board = None
        self._expected_meta = None

        self.tetris.board = board
        # Eroeffnungsbuch (pieces_second.json) gilt fuer das LEERE Startbrett.
        # FIX (Blocker A): Bedingung war invertiert (== 0 = VOLLES Brett, und
        # urspruenglich sogar ohne Klammern) -> das Buch war toter Code. Jetzt
        # ueber die getestete Hilfsfunktion is_opening_position(): leeres Brett
        # -> first/second = 0 -> find_first nutzt das Buch fuer den Eroeffnungszug.
        if self.tetris.is_opening_position():
            self.tetris.first = 0
            self.tetris.second = 0
        else:
            self.tetris.first = 1
            self.tetris.second = 1

        log.snapshot('BOARD_STATE', board=self.tetris.board,
                     extra='leere Zellen={}'.format(self.tetris.count_zeros()))

    # -- Haertung: Closed-Loop + Plausibilitaet ---------------------------

    def _arm_placement_verify(self, piece_type, anchor):
        """Merkt das Brett VOR der Platzierung + Stein/Anker, damit die naechste
        frische Lesung gegen das erwartete Footprint geprueft werden kann (①).

        ``self.tetris.board`` ist hier noch der Zustand VOR ``insert_piece``
        (Aufruf erfolgt vor dem Einsetzen). Wirft nie."""
        try:
            if not self.verify_placements:
                return
            self._expected_board = deepcopy(self.tetris.board)
            self._expected_meta = {'piece_type': piece_type, 'anchor': anchor}
        except Exception:
            self._expected_board = None
            self._expected_meta = None

    def _verify_last_placement(self, actual_board):
        """Vergleicht Soll (gemerktes Brett + Stein/Anker) mit dem frisch
        gelesenen Ist-Brett und LOGGT Abweichungen (reine Beobachtung)."""
        try:
            meta = self._expected_meta or {}
            res = puzzle_safety.verify_placement(
                self._expected_board, meta.get('piece_type'),
                meta.get('anchor'), actual_board)
            if res['severity'] != 'ok':
                log.snapshot(
                    'PLACEMENT_VERIFY', board=actual_board,
                    piece_type=meta.get('piece_type'),
                    extra=('severity={} anchor={} fehlende_footprint={} '
                           'unerwartet={}').format(
                               res['severity'], meta.get('anchor'),
                               res['missing_footprint'], res['unexpected']))
        except Exception:
            pass

    def _board_suspicious(self):
        """True, wenn die letzte Brett-Lesung verdaechtig viele Garbage-Zellen
        hatte (belegt, aber keine echte Steinfarbe) -> kurz neu lesen (④).

        Endgame-Guard: bei VOLLEM Brett (keine leeren Zellen) erscheint die Truhe
        und ueberlagert Zellen -> die werden als garbage gelesen. Das ist KEIN
        Lesefehler, sondern der normale Abschluss -> kein Re-Read (sonst kollidiert
        das mit dem Truhen-Einsammel-Pfad)."""
        try:
            if self.tetris.count_zeros() == 0:
                return False
        except Exception:
            pass
        return (self.board_plausibility
                and getattr(self, '_last_board_garbage', 0) >= BOARD_MAX_GARBAGE)

    def _log_color_confidence(self, piece_type, bgr):
        """Schreibt die Erkennungs-Konfidenz (rohe BGR + Distanz/Margin zu den
        Zentroiden) als Audit-Snapshot (①). Wirft nie."""
        try:
            m = puzzle_safety.centroid_metrics(bgr, self.PIECE_REF_BGR)
            log.snapshot(
                'PIECE_COLOR_OK', bgr=bgr, piece_type=piece_type,
                extra=('naechster={} dist={:.1f} zweiter={} margin={:.1f}'
                       ).format(m['nearest'], m['nearest_dist'] or 0.0,
                                m['second'], m['margin'] or 0.0))
        except Exception:
            pass

    def get_image(self):

        screenshot = self.wincap.get_screenshot()

        crop_img = screenshot[self.puzzle_offset[1]:self.puzzle_offset[1]+self.board_size[1],
                            self.puzzle_offset[0]:self.puzzle_offset[0]+self.board_size[0]]

        return crop_img

    def _click_board_point(self, accessor, keypoint_name, button):
        """Klickt einen board-relativen geometry-Referenzpunkt im Fenster.

        Loest ``accessor(board_size, key_points.get(keypoint_name))`` zum
        Board-Punkt auf, verschiebt ihn um ``puzzle_offset`` + den Fenster-Rand
        (``wincap.offset_*``) auf Bildschirm-Koordinaten und klickt mit
        ``button``. Buendelt die zuvor in press_comfirm / press_comfirm_cake /
        throw_pice woertlich duplizierte Koordinaten-Arithmetik -- byte-stabil
        (gleiche ``int()``-Rundung, gleicher Klick).
        """
        cx, cy = accessor(self.board_size, self.key_points.get(keypoint_name))
        mouse_x = int(cx + self.puzzle_offset[0] + self.wincap.offset_x)
        mouse_y = int(cy + self.puzzle_offset[1] + self.wincap.offset_y)
        pydirectinput.click(x=mouse_x, y=mouse_y, button=button)

    def _cell_screen_point(self, i, j):
        """Bildschirm-Klickpunkt der Brett-Zelle ``(i, j)`` als Int-Paar.

        Loest die Zellmitte ueber ``geometry.cell_point(i, j, board_size)`` auf
        und verschiebt sie um ``puzzle_offset`` + den Fenster-Rand
        (``wincap.offset_*``) auf Bildschirm-Koordinaten. Buendelt die zuvor in
        play_game (trained/Buch/greedy) und _place_deluxe woertlich duplizierte
        Anker-Arithmetik -- byte-stabil (gleiche ``int()``-Rundung).
        """
        px, py = geometry.cell_point(i, j, self.board_size)
        mouse_x = int(px + self.puzzle_offset[0] + self.wincap.offset_x)
        mouse_y = int(py + self.puzzle_offset[1] + self.wincap.offset_y)
        return (mouse_x, mouse_y)

    def _click_cell(self, i, j):
        """Klickt die Brett-Zelle ``(i, j)`` (Platzierungs-Klick).

        Wie die bisherigen Inline-Aufrufe ein POSITIONALER Links-Klick
        ``pydirectinput.click(x, y)`` (ohne ``button``-Kwarg) auf den von
        :meth:`_cell_screen_point` gelieferten Punkt -- byte-stabil.
        """
        mouse_x, mouse_y = self._cell_screen_point(i, j)
        pydirectinput.click(mouse_x, mouse_y)

    def _box_screen_point(self, box_point):
        """Rechnet einen Box-Slot (Fenster-INHALT-Koordinate, z.B. PUZZLE_BOX /
        PUZZLE_DELUXE_BOX) in einen Bildschirm-Klickpunkt um.

        Die Box-Slots sind feste Client-Positionen (kein board-relativer
        ``puzzle_offset``) -> es wird NUR der Fenster-Rand ``wincap.offset_*``
        addiert, identisch zur Truhen-Logik in ``try_to_put_chest``. Defensiv:
        ohne ``wincap`` (vor ``set_to_begin``) faellt der Offset auf 0 zurueck,
        statt zu crashen. Rueckgabe: ``(mouse_x, mouse_y)`` als Ints."""
        off_x = getattr(self.wincap, 'offset_x', 0) or 0
        off_y = getattr(self.wincap, 'offset_y', 0) or 0
        return (int(box_point[0] + off_x), int(box_point[1] + off_y))

    def deluxe_box_screen_point(self):
        """Bildschirm-Klickpunkt der DELUXE-Box (Slot ueber der Standard-Box)."""
        return self._box_screen_point(self.PUZZLE_DELUXE_BOX)

    def standard_box_screen_point(self):
        """Bildschirm-Klickpunkt der STANDARD-Puzzlebox (unterer Slot)."""
        return self._box_screen_point(self.PUZZLE_BOX)

    def press_comfirm(self):
        self._click_board_point(geometry.confirm_point, 'confirm', 'left')

    def press_comfirm_cake(self):
        self._click_board_point(geometry.cake_point, 'cake', 'left')

    def throw_pice(self):
        self._click_board_point(geometry.confirm_point, 'confirm', 'right')

    def get_new_piece_color(self, crop_image, quiet=False):

        x, y = geometry.color_sample(self.board_size, self.key_points.get('color'))

        # Gemessene BGR-Werte am Sample (110,150) ueber den umschaltbaren
        # Sampler auslesen: 'single' = exakt dieser eine Pixel (byte-stabil),
        # 'multi' = Patch-Mittelwert um den Punkt.
        b, g, r = self._sample_cell_bgr(crop_image, x, y)

        # Im 'multi'-Modus klassifiziert _classify_piece nach naechster
        # Referenzfarbe und liefert daher fuer ECHTES Schwarz/Garbage
        # (verschobenes Fenster) faelschlich einen Steintyp. Darum hier dieselbe
        # Schwarz-Schwelle wie bei der Board-Leererkennung: alle Kanaele < 50 ->
        # als "nicht erkannt" behandeln (None), statt Unsinn zu klassifizieren.
        # Der 'single'-Pfad bleibt davon unberuehrt (enge BGR-Fenster treffen
        # Schwarz ohnehin nicht).
        if self.color_mode == 'multi' and b < 50 and g < 50 and r < 50:
            piece_type = None
        else:
            piece_type = self._classify_piece((b, g, r))

        if piece_type is not None:
            log.event(self.state, t('puzzle.piece_color_detected'),
                      piece_type=piece_type, x=x, y=y)
            # Audit (①): rohe BGR + Konfidenz (Distanz/Margin zum naechsten vs
            # zweitnaechsten Zentroid) mitschreiben, damit eine spaetere
            # Fehlklassifikation aus dem Log rekonstruierbar wird -- bisher
            # wurden diese Werte NUR im Miss-Fall geloggt.
            self._log_color_confidence(piece_type, (b, g, r))
            return piece_type

        # Toleranz-Klassifikation ('single'-Modus, JEDER Versuch): bevor ein
        # GERENDERTER Stein wegen Farbton-Drift in den Retry/Verwerfen-Pfad
        # faellt, gegen die 6 Zentroide mit +-40/Kanal pruefen -- eindeutig
        # oder gar nicht. Verwechslung ist konstruktiv UNMOEGLICH (kleinste
        # Einzelkanal-Luecke zweier Zentroide = 85 > 2*40) und Hintergrund/
        # Garbage trifft nie (jedes Zentroid hat einen Kanal >= 160); auch ein
        # halb eingeblendeter Stein kann nur SEINEM Zentroid nahekommen (die
        # Kanal-Verhaeltnisse bleiben beim Fade erhalten). Drift wird damit
        # SOFORT erkannt statt erst nach abgelaufenem Retry -> schneller UND
        # robuster; die strikten Fenster bleiben der byte-stabile Normalpfad.
        if self.color_mode != 'multi':
            fallback = self._classify_piece_tolerant((b, g, r))
            if fallback is not None:
                # Konfidenz-Gate (③): die Disjunktheits-Begruendung im Toleranz-
                # Fallback ist faktisch falsch (kleinste Kanal-Luecke ist real 0,
                # nicht 85; naechstes Paar 1<->6 ~90 euklidisch). Darum hier den
                # Margin zum zweitnaechsten Zentroid verlangen: ist die Messung
                # nicht klar einem Typ zugeordnet, lieber VERWERFEN als einen
                # womoeglich FALSCHEN Stein setzen (Verwerfen ist billig).
                m = puzzle_safety.centroid_metrics((b, g, r), self.PIECE_REF_BGR)
                if m['margin'] is not None and m['margin'] < PIECE_MIN_MARGIN:
                    log.snapshot(
                        'PIECE_COLOR_LOWCONF', bgr=(b, g, r), screen_xy=(x, y),
                        extra=('Toleranz-Treffer Typ {} verworfen: margin={:.1f}'
                               ' < {} (naechster={} zweiter={})').format(
                                   fallback, m['margin'], PIECE_MIN_MARGIN,
                                   m['nearest'], m['second']))
                    return None
                log.event(self.state, t('puzzle.piece_color_tolerant_fallback'),
                          piece_type=fallback, b=b, g=g, r=r)
                self._log_color_confidence(fallback, (b, g, r))
                return fallback

        # Keine der 6 engen BGR-Ranges getroffen -> None (Solver faengt das ab).
        # Echte BGR-Werte protokollieren, damit der Nutzer Schwarz/Garbage
        # (Position/Aufloesung falsch) von plausibler Farbe (Range-Drift)
        # unterscheiden kann. ``quiet`` unterdrueckt die Miss-Zeilen waehrend
        # der Retry-Schleife in State 4 (der Stein ist nach dem Holen oft noch
        # nicht gerendert -> jeder Zwischenframe wuerde sonst Log-Spam) -- der
        # LETZTE Versuch laeuft mit quiet=False und loggt den Miss vollstaendig.
        if not quiet:
            log.event(self.state, t('puzzle.piece_color_not_detected'), x=x, y=y, b=b, g=g, r=r)
            log.snapshot('PIECE_COLOR_MISS', bgr=(b, g, r), screen_xy=(x, y),
                         extra='keine der 6 BGR-Ranges getroffen -> new_piece=None')
        return None

    # -- Force Deluxe (V3-Reservat) ---------------------------------------

    def _deluxe_count(self):
        """Rohe Anzahl der Deluxe-Boxen im Slot ``PUZZLE_DELUXE_BOX`` (>=0).

        Liest einen frischen Screenshot und gibt ihn an ``deluxe.read_deluxe_count``
        (32x32-Slot auf ``(503,271)``, font-unabhaengiges OCR). STRIKT defensiv --
        jeder Fehler -> ``0``. DIES ist der einzige Verfuegbarkeits-Sensor; sein
        Rohwert wird bewusst geloggt (``puzzle.deluxe_decision``), weil eine
        stille 0 bisher die einzige Ursache war, dass Deluxe NIE genutzt wurde."""
        try:
            shot = self.wincap.get_screenshot()
            return int(deluxe.read_deluxe_count(shot, self.PUZZLE_DELUXE_BOX))
        except Exception:
            return 0

    def _read_deluxe_available(self):
        """``True``, wenn >= 1 Deluxe-Box im Slot liegt (Wrapper um ``_deluxe_count``)."""
        return self._deluxe_count() >= 1

    def _register_deluxe_result(self, piece):
        """REAKTIVE Leer-Erkennung der Deluxe-Box (ersetzt die Box-Zahl-OCR).

        Nur aktiv, wenn gerade die Deluxe-Box geoeffnet wurde (``_awaiting_deluxe``).
        Kommt der Magenta-Stein (Typ 7) -> alles gut, Zaehler zuruecksetzen. Kommt
        KEINER (None/normaler 1-6) -> der Deluxe-Slot war LEER (genau das Signal
        "es kommt nichts" -> erst JETZT reagieren): nach ``DELUXE_MISS_LIMIT``
        leeren Oeffnungen wird die Deluxe-Nutzung fuer den Lauf abgeschaltet und
        NORMAL weitergespielt (Bot wird NICHT gestoppt). (Das frueher hier
        verdrahtete Deluxe-Box-NACHLEGEN aus dem Inventar wurde in v1.3 entfernt --
        Deluxe-SPIELEN bleibt, nur die Inventar-Nachlege-Maschinerie faellt weg.)
        Rueckgabe ``True``, wenn es ein Deluxe-Versuch war (Aufrufer ueberspringt
        dann den Standard-Box-Streak). Wirft nie."""
        if not getattr(self, '_awaiting_deluxe', False):
            return False
        self._awaiting_deluxe = False
        if piece == deluxe.DELUXE_PIECE_TYPE:
            self._deluxe_miss_streak = 0
            return True
        # Kein Magenta -> Deluxe-Slot leer (reaktiv erkannt, ohne OCR).
        self._deluxe_miss_streak = getattr(self, '_deluxe_miss_streak', 0) + 1
        log.event(self.state, t('puzzle.deluxe_empty_detected'), got=piece,
                  misses=self._deluxe_miss_streak, limit=DELUXE_MISS_LIMIT)
        # Deluxe abschalten und NORMAL weiterspielen, sobald die Box mehrfach
        # leer war (kein Inventar-Nachlegen mehr in v1.3).
        if self._deluxe_miss_streak >= DELUXE_MISS_LIMIT:
            self._deluxe_disabled = True
            log.event(self.state, t('puzzle.deluxe_disabled'))
        return True

    def _force_deluxe_active(self):
        """``True``, wenn die V3-Force-Deluxe-Strategie GERADE greifen soll.

        Bedingungen: ``force_deluxe`` an UND ``solver_mode == 'trained'`` UND
        mindestens eine Deluxe-Box im Inventar. Die teure Inventar-OCR wird PRO
        STEIN-ZYKLUS nur EINMAL ausgewertet und gecacht (``_fd_avail_cache``);
        der Cache wird beim Anfordern eines neuen Steins (State 0) invalidiert
        (siehe ``_reset_force_deluxe_cache``). So liest ein Brett-Durchlauf die
        Box-Zahl genau einmal statt in jedem Teil-State. Wirft nie."""
        try:
            if not self.force_deluxe or self.solver_mode != 'trained':
                return False
            cached = getattr(self, '_fd_avail_cache', None)
            if cached is None:
                cached = self._read_deluxe_available()
                self._fd_avail_cache = cached
            return bool(cached)
        except Exception:
            return False

    def _reset_force_deluxe_cache(self):
        """Invalidiert den pro-Zyklus-Cache der Deluxe-Verfuegbarkeit.

        Beim Start eines neuen Stein-Zyklus (State 0) gerufen, damit die naechste
        ``_force_deluxe_active``-Abfrage die Box-Zahl frisch liest (eine geoeffnete
        Box veraendert den Bestand). Wirft nie."""
        self._fd_avail_cache = None

    def _non_reservat_full(self):
        """``True``, wenn die 18 Nicht-Reservat-Zellen ALLE belegt sind.

        Prueft das interne ``tetris.board`` gegen ``deluxe.reservat_2x3()``: jede
        Zelle, die NICHT zum Reservat gehoert, muss belegt sein. Genau dann ist
        der Solver mit den 18 Zellen fertig und der Deluxe-Stein kann ins Reservat
        gesetzt werden. Defensiv -> ``False`` (nicht voll -> Box bleibt zu)."""
        try:
            reservat = deluxe.reservat_2x3()
            board = self.tetris.board
            for i in range(4):
                for j in range(6):
                    if (i, j) not in reservat and not board[i][j]:
                        return False
            return True
        except Exception:
            return False

    def _open_deluxe_box_and_place(self):
        """Oeffnet die DELUXE-Box und setzt den Magenta-Stein ins Reservat.

        Aufrufkontext (State 0): Force-Deluxe ist aktiv, die 18 Nicht-Reservat-
        Zellen sind voll und das Reservat ist leer -> jetzt die Deluxe-Box
        anklicken (``deluxe_box_screen_point``). Der dadurch erscheinende
        Magenta-2x3-Stein wird ueber den bestehenden Stein-Pfad (Farb-Erkennung
        Typ 7 -> ``_place_deluxe`` -> erstes freies 2x3 = das Reservat) gesetzt.

        Hier wird NUR die Box geoeffnet und der Cache invalidiert (der Bestand
        sinkt); die eigentliche Platzierung laeuft danach durch die normale
        State-Machine. STRIKT defensiv -- ein Fehler hier darf den Loop nie
        kippen. Rueckgabe ``True`` bei ausgefuehrtem Klick, sonst ``False``."""
        try:
            mx, my = self.deluxe_box_screen_point()
            log.event(self.state, t('puzzle.force_deluxe_open_box'),
                      pos=(mx, my))
            pydirectinput.click(x=mx, y=my, button='left')
            # Bestand hat sich geaendert -> Cache fuer den naechsten Zyklus frisch.
            self._reset_force_deluxe_cache()
            return True
        except Exception as exc:
            log.error(t('puzzle.force_deluxe_open_failed'), exc=exc)
            return False

    def _focus_game(self):
        """Holt das Spiel-Fenster in den VORDERGRUND (Tastatur-Fokus).

        NOETIG fuer Strg+E / ESC: ``pydirectinput``-TASTEN gehen ans fokussierte
        Fenster. Das Puzzle spielt sonst nur mit KLICKS (positions-basiert,
        fokus-frei) -> das Spiel hat beim Puzzle i.d.R. KEINEN Fokus und ein
        Hotkey ginge ins Leere. Defensiv: ohne Modul/HWND ein No-op, wirft NIE.
        Liefert ``True`` bei Erfolg."""
        if _focus_window is None:
            return False
        hwnd = getattr(self.wincap, 'hwnd', None)
        if not hwnd:
            return False
        try:
            return bool(_focus_window(hwnd))
        except Exception:
            return False

    # -- Spiel selbst oeffnen via Event-Uebersicht (v1.3) -----------------
    # Generischer Selbststart/Reopen: Strg+E -> Eventuebersicht -> das Label
    # "FISCHPUZZLESPIEL" positionsunabhaengig per NCC finden -> auf den NAMEN
    # klicken (nicht "Ansehen") -> verifizieren, dass das Brett offen ist. Die
    # NCC-Pipeline (Templates flow_event_title + flow_fisch_label) liegt im
    # getesteten seher.flow-Modul und wird READ-ONLY mitbenutzt. Erkennung VOR
    # Aktion: nie blind klicken, Doppel-Guard (Header UND Label muessen matchen).

    def _press_ctrl_e(self):
        """Strg+E mit expliziten Holds (Seher-Lektion: DirectInput verschluckt
        Modifier-Combos bei zu kurzem Druck). Fokus davor (Tasten brauchen ihn).
        Wirft nie."""
        self._focus_game()
        old = getattr(pydirectinput, 'PAUSE', 0.05)
        try:
            pydirectinput.PAUSE = 0.1
            pydirectinput.keyDown('ctrl')
            sleep(0.06)
            pydirectinput.keyDown('e')
            sleep(0.06)
            pydirectinput.keyUp('e')
            sleep(0.06)
            pydirectinput.keyUp('ctrl')
        except Exception:
            pass
        finally:
            pydirectinput.PAUSE = old
        sleep(FLOW_PACE_S)

    def _press_esc(self):
        """ESC drueckt (schliesst das offene Fenster/Spiel). Fokus davor. Wirft nie."""
        self._focus_game()
        old = getattr(pydirectinput, 'PAUSE', 0.05)
        try:
            pydirectinput.PAUSE = 0.1
            pydirectinput.press('esc')
        except Exception:
            pass
        finally:
            pydirectinput.PAUSE = old
        sleep(FLOW_PACE_S)

    def _overview_state(self, frame):
        """Lage der Eventuebersicht als ``(offen?, gemessene_ncc)``.

        Gibt die ROHE Header-NCC mit zurueck (nicht nur den bool), damit jeder
        Strg+E-Versuch den gemessenen Wert loggen kann -> ein Knapp-daneben
        (z.B. 0.79 bei Schwelle 0.82) ist im Log sofort als Render-/Schwellen-
        Problem ablesbar statt als stummes "nicht offen". Wirft nie -> (False,
        0.0)."""
        if _flow is None or frame is None:
            return (False, 0.0)
        try:
            ok, _pos, ncc = _flow.find(frame, 'flow_event_title', FLOW_NCC_MIN)
            return (bool(ok), float(ncc))
        except Exception:
            return (False, 0.0)

    def _find_fisch_label(self, frame):
        """Sucht das FISCHPUZZLESPIEL-Namensfeld in der Eventuebersicht.

        Doppel-Guard (Seher-Muster find_seher_click): nur ein Treffer, wenn das
        Label UND der Uebersichts-Header matchen -> nie ins falsche/zugedeckte
        Fenster klicken (der reine Schriftzug koennte den Fenstertitel matchen).
        Klickziel = Template-Zentrum (im Frame-Koordinatenraum, OHNE wincap-Rand).
        Rueckgabe (ok, (x, y), dbg). Wirft nie."""
        if _flow is None or frame is None:
            return (False, (0, 0), {})
        try:
            ok_l, pos_l, ncc_l = _flow.find(frame, 'flow_fisch_label', FLOW_NCC_MIN)
            ok_t, _pt, ncc_t = _flow.find(frame, 'flow_event_title', FLOW_NCC_MIN)
            dbg = {'label_ncc': round(ncc_l, 4), 'title_ncc': round(ncc_t, 4)}
            if not ok_l:
                return (False, (0, 0), dbg)
            if not ok_t:
                # Label gematcht, aber KEINE Uebersicht offen -> kein Klick.
                dbg['no_overview'] = True
                return (False, (0, 0), dbg)
            return (True, _flow.center('flow_fisch_label', pos_l), dbg)
        except Exception:
            return (False, (0, 0), {})

    def _board_open(self, frame=None):
        """True, wenn das Puzzle-Brett bereits offen/spielbar ist
        (calibration.validate_puzzle_region ok). Liest bei Bedarf einen frischen
        Ausschnitt. Wirft nie -> False."""
        try:
            if frame is None:
                frame = self.get_image()
            calib = calibration.validate_puzzle_region(
                frame, expected_size=self.board_size)
            return bool(calib.ok)
        except Exception:
            return False

    def _flow_ncc_brief(self):
        """Rohe Best-NCC ALLER Flow-Templates + Anker/Spielfeld als EIN String
        (fuer Snapshot-``extra``). Macht jeden Reopen-Fehlschritt ablesbar: alle
        Werte niedrig -> erwarteter Bildschirm gar nicht da (Klick verschluckt /
        falsches Fenster); ein Wert knapp unter der Schwelle -> Render-
        Unterschied am echten Client.

        Bewusst OHNE ``validate_puzzle_region`` (entkoppelt von der Brett-
        Kalibrierung), damit die Diagnose die Anzahl der Kalibrier-Aufrufe im
        Control-Flow nicht verschiebt. Wirft nie -> Fehlertext."""
        try:
            if _flow is None or self.wincap is None:
                return 'flow=unavailable'
            shot = self.wincap.get_screenshot()
            d = _flow.diagnose(shot)
            try:
                fish = float(_flow.find(shot, 'flow_fisch_label', 0.0)[2])
            except Exception:
                fish = -1.0
            return ('thresh={} fisch_label={:.3f} event_title={} anchor={} '
                    'game={}').format(FLOW_NCC_MIN, fish,
                                      d.get('flow_event_title'),
                                      d.get('anchor'), d.get('game'))
        except Exception:
            return 'flow=diag_error'

    def _open_puzzle_game(self, force=False):
        """Oeffnet das Fisch-Puzzle SELBST ueber die Eventuebersicht.

        Ablauf (Toggle-Muster wie der Seher-Selbststart):
          1. Ist das Brett schon offen -> nichts tun, True. ABER nur wenn NICHT
             ``force``: nach einem ESC (Box-leer-Neustart) meldet das rein
             STRUKTURELLE ``_board_open`` jede board-foermige Region als "offen"
             (auch das verbrauchte/leere Brett oder den Hintergrund) -> ein
             Kurzschluss hier wuerde den Neustart ueberspringen. GENAU das war der
             v1.3.0-Bug ("oeffnet das Eventboard nicht, klickt in die Gegend").
             Im ``force``-Pfad wird der Eventlisten-Neustart daher erzwungen.
          2. Strg+E (<=CTRL_E_RETRIES), bis die Eventuebersicht sichtbar ist.
          3. FISCHPUZZLESPIEL-Label robust per NCC finden (Doppel-Guard) und auf
             den NAMEN klicken (nicht "Ansehen").
          4. Verifizieren, dass das Brett jetzt offen ist.

        SOTA-Debug: jeder Schritt schreibt einen strukturierten ``SNAP``-Block
        (REOPEN_BEGIN / _NO_OVERVIEW / _NO_LABEL / _OK / _BOARD_MISS) mit den
        rohen Flow-NCCs -> bei einem erneuten Fehlschlag steht im Log GENAU, an
        welchem Schritt und warum (Uebersicht nicht erkannt? Label unter
        Schwelle? Klick lieferte kein Brett?). Erkennung VOR Aktion -> nie blind
        klicken. Rueckgabe ``bool`` (offen?). Wirft nie."""
        try:
            if _flow is None or self.wincap is None:
                log.event(self.state, t('puzzle.game_open_unavailable'))
                return False
            board_now = self._board_open()
            log.snapshot('REOPEN_BEGIN', screen_xy=self.puzzle_offset,
                         extra='force={} board_open={} | {}'.format(
                             force, board_now, self._flow_ncc_brief()))
            # (1) schon offen? (im force-Pfad NICHT vertrauen, s. Docstring)
            if not force and board_now:
                log.event(self.state, t('puzzle.game_already_open'))
                return True
            log.event(self.state, t('puzzle.open_game'))
            # (2) Eventuebersicht oeffnen (Toggle nur wenn nicht schon offen).
            shot = self.wincap.get_screenshot()
            ov_ok, ov_ncc = self._overview_state(shot)
            if not ov_ok:
                opened = False
                for attempt in range(1, CTRL_E_RETRIES + 1):
                    self._press_ctrl_e()
                    shot = self.wincap.get_screenshot()
                    ov_ok, ov_ncc = self._overview_state(shot)
                    log.event(self.state, t('puzzle.open_ctrl_e',
                              attempt=attempt, max=CTRL_E_RETRIES,
                              title_ncc=round(ov_ncc, 3)))
                    if ov_ok:
                        opened = True
                        break
                if not opened:
                    log.snapshot('REOPEN_NO_OVERVIEW',
                                 screen_xy=self.puzzle_offset,
                                 extra=self._flow_ncc_brief())
                    return False
            # (3) Label finden + auf den NAMEN klicken (Doppel-Guard schuetzt).
            ok, pt, dbg = self._find_fisch_label(shot)
            if not ok:
                log.event(self.state, t('puzzle.fisch_label_missing',
                          label_ncc=dbg.get('label_ncc'),
                          title_ncc=dbg.get('title_ncc')))
                log.snapshot('REOPEN_NO_LABEL', screen_xy=self.puzzle_offset,
                             extra=self._flow_ncc_brief())
                return False
            mx = int(pt[0] + getattr(self.wincap, 'offset_x', 0))
            my = int(pt[1] + getattr(self.wincap, 'offset_y', 0))
            log.event(self.state, t('puzzle.fisch_label_click',
                      pos=(mx, my), label_ncc=dbg.get('label_ncc')))
            pydirectinput.click(x=mx, y=my, button='left')
            sleep(FLOW_PACE_S)
            # (4) Erfolg = Brett offen UND Eventuebersicht wieder ZU. Das rein
            # strukturelle board_open meldet auch die noch offene Uebersicht als
            # "board-foermig" -> als alleiniges Signal LUEGT es (real beobachtet:
            # Fehlklick auf "Name", Uebersicht blieb offen, board_open=True ->
            # falsches REOPEN_OK). Der erfolgreiche Klick auf den
            # FISCHPUZZLESPIEL-Button SCHLIESST die Uebersicht und oeffnet das
            # Brett -> beide Bedingungen zusammen sind das verlaessliche Signal.
            deadline = time() + BOARD_OPEN_POLL_S
            while time() < deadline:
                overview_open = self._overview_state(
                    self.wincap.get_screenshot())[0]
                if self._board_open() and not overview_open:
                    log.event(self.state, t('puzzle.game_opened'))
                    log.snapshot('REOPEN_OK', screen_xy=self.puzzle_offset,
                                 extra=self._flow_ncc_brief())
                    return True
                sleep(0.2)
            # Deadline abgelaufen: Brett nicht sauber offen (Uebersicht evtl. noch
            # offen -> Klick verfehlt / Button nicht gestartet). Voll diagnostiziert.
            still_ov = self._overview_state(self.wincap.get_screenshot())[0]
            log.snapshot('REOPEN_BOARD_MISS', screen_xy=self.puzzle_offset,
                         extra='overview_still_open={} | {}'.format(
                             still_ov, self._flow_ncc_brief()))
            return False
        except Exception as exc:
            log.error(t('puzzle.game_open_failed', exc=exc), exc=exc)
            return False

    def _place_deluxe(self):
        """Setzt den DELUXE-Stein (volles 2x3-Magenta) DETERMINISTISCH.

        Der Deluxe-Stein hat eine feste Form und gehoert NICHT in den MDP
        (trained_solver) oder den Greedy-/Eroeffnungsbuch-Pfad: er wird GREEDY in
        das erste freie 2x3-Loch gesetzt (deluxe.find_free_2x3). Passt keiner ->
        ``None`` (Stein wird in State 7 weggeworfen). Bei Erfolg werden die 6
        Zellen auf dem Brett belegt, ``self.end`` ggf. gesetzt und die Anker-
        Zelle geklickt; Rueckgabe ``True``. Wirft nie."""
        anchor = deluxe.find_free_2x3(self.tetris.board)
        if anchor is None:
            log.event(self.state, t('puzzle.deluxe_no_2x3_slot'),
                      piece_type=deluxe.DELUXE_PIECE_TYPE)
            return None

        ax, ay = anchor
        # Bounds/Overlap-Guard (F9): dieser Pfad schrieb bisher blind ins Brett
        # und klickte. find_free_2x3 sollte gueltige Anker liefern, aber defensiv
        # pruefen, bevor 6 Zellen gesetzt + geklickt werden.
        fp = puzzle_safety.footprint_from_cells(deluxe.DELUXE_FORM, anchor)
        if fp is None or any(self.tetris.board[r][c] for (r, c) in fp):
            log.error('Deluxe-Platzierung abgebrochen: ungueltiger/'
                      'ueberlappender Anker {}'.format(anchor))
            return None
        # Die 6 Zellen des 2x3-Rechtecks im internen Brett belegen (der Solver
        # nutzt Tetris.insert_piece nur fuer die echten Typen 1..6; hier setzen
        # wir direkt, da Piece(7) bewusst leer/ungueltig ist).
        for (dr, dc) in deluxe.DELUXE_FORM:
            self.tetris.board[ax + dr][ay + dc] = 1
        if self.tetris.verify_end():
            self.end = True

        log.event(self.state, t('puzzle.deluxe_placed'),
                  piece_type=deluxe.DELUXE_PIECE_TYPE, pos=anchor)
        self._click_cell(ax, ay)
        return True

    def play_game(self):

        # -- DELUXE-Stein (Typ 7, Magenta) ------------------------------------
        # Deterministisch ein volles 2x3-Rechteck: NICHT durch trained_solver
        # (MDP kennt nur Typ 1..6) und NICHT durch den Greedy-/Buch-Pfad routen.
        # Vor der 1..6-Pruefung abfangen, sonst wuerde Typ 7 unten als
        # 'ungueltig' weggeworfen.
        if self.new_piece == deluxe.DELUXE_PIECE_TYPE:
            return self._place_deluxe()

        # Ungueltiger Stein (None / ausserhalb 1..6) -> NICHT an den Solver
        # geben. Frueher fuehrte Piece(None) zu TypeError/KeyError und einem
        # stillen Stop. Hier: protokollieren und Stein wegwerfen (State 7).
        if self.new_piece not in (1, 2, 3, 4, 5, 6):
            log.warning(t('puzzle.invalid_piece_discarded', new_piece=self.new_piece))
            return None

        piece = Piece(self.new_piece)

        # -- Frueh-Branch: trainierte KI (solver_mode == 'trained') -----------
        # choose_placement liefert bereits gueltige, ueberlappungsfreie Lagen
        # (oder None = Verwerfen ist optimal). Daher KEIN possibilites-Filter,
        # KEIN Eroeffnungsbuch/find_first, KEINE Typ-1-Isolation -- der
        # gesamte Greedy-Pfad unten bleibt ausschliesslich dem 'standard'-Modus
        # vorbehalten und unveraendert.
        if self.solver_mode == 'trained':
            # PERFEKTES Spiel BIS ZUM SCHLUSS, OHNE GRENZEN (Nutzer-Vorgabe
            # 2026-06-17): immer die BEWEISBAR optimale Policy -> platziere NUR,
            # wenn es die erwarteten Rest-Steine (Wertfunktion V) STRIKT senkt,
            # sonst verwerfen und auf den optimalen Stein warten. Das minimiert
            # die Steine bis zum Sieg ZU JEDER ZEIT.
            #
            # KEIN Finish-Modus mehr (frueher: ab FINISH_AFTER_DISCARDS Verwerfen
            # den "am wenigsten schlechten" Stein erzwingen). Der legte absichtlich
            # SUBOPTIMALE, FRAGMENTIERENDE Steine (V STEIGT) und machte das Spiel
            # nachweislich schlechter -- der gemeldete Fall: 1-Zug-L-Loch V=6 ->
            # nach Monomino V=12 = ein Stein/Zug MEHR. Die optimale Policy beendet
            # das Brett mit Wahrscheinlichkeit 1 von allein (der komplettierende
            # Stein kommt; p>=1/6 pro Stein). Gegen ein echtes HAENGEN (ein Stein
            # wird DAUERHAFT FEHL-ERKANNT) bleibt der harte DISCARD_STOP_LIMIT-
            # Backstop -- er zaehlt nur Verwerfen-IN-FOLGE und wird bei jeder
            # Platzierung genullt, greift also NICHT in normales Warten ein.
            streak = getattr(self, '_discard_streak', 0)
            finish = False
            # KEIN festes Reservat mehr: die Deluxe-Nutzung ist jetzt
            # OPPORTUNISTISCH (State 0 oeffnet die Deluxe-Box, sobald irgendwo ein
            # freies 2x3-Loch liegt UND eine Box da ist) statt ein fixes Feld zu
            # reservieren. Die alte Reservat-Strategie blieb haengen, sobald die
            # Box-Zahl-OCR 0 las (Reservat nie befuellt) -> der Solver fuellt jetzt
            # immer normal, Deluxe schnappt sich Loecher proaktiv davor.
            a = trained_solver.choose_placement(self.tetris.board, piece,
                                                finish=finish, reservat=None)
            if a is None:
                self._discard_streak = streak + 1
                log.event(self.state,
                          t('puzzle.ai_no_improving_placement'),
                          piece_type=piece.piece_type, solver_mode='trained')
                # Safe-Fail (⑥): zu viele Verwerfen IN FOLGE ohne jede
                # Platzierung -> sauberer Stop statt Boxen endlos zu verbrennen
                # (z.B. bei dauerhaft fehl-erkanntem Stein).
                if self._discard_streak >= DISCARD_STOP_LIMIT:
                    log.error('Safe-Fail: {} Steine in Folge verworfen ohne '
                              'Platzierung -> Stop (moegliche Dauer-Fehl'
                              'erkennung)'.format(self._discard_streak))
                    self.botting = False
                return None

            self._discard_streak = 0
            log.event(self.state, t('puzzle.placement_chosen'), piece_type=piece.piece_type,
                      pos=a, solver_mode='trained')
            # Closed-Loop (①) scharf schalten: Soll-Brett VOR dem Einsetzen merken.
            self._arm_placement_verify(piece.piece_type, a)
            self.tetris.insert_piece(a[0], a[1], piece)
            if self.tetris.verify_end():
                self.end = True
            self._click_cell(a[0], a[1])

            return True

        decision, pos = self.tetris.find_first(piece, self.dictdump)
        if decision == 1:

            log.event(self.state, t('puzzle.opening_book_move'), piece_type=piece.piece_type,
                      pos=pos)
            self._arm_placement_verify(piece.piece_type, pos)
            self.tetris.insert_piece(pos[0], pos[1], piece)
            if self.tetris.verify_end():
                self.end = True
            self._click_cell(pos[0], pos[1])

            return None

        if decision == 2:
            return None

        possibilites = self.tetris.find_possibles(piece)

        pices_count = 0

        for i in range(1,7):
            if i != piece.piece_type:
                possis = self.tetris.find_possibles(Piece(i))
                if len(possis):
                    pices_count += 1

        if piece.piece_type == 1 and pices_count != 0:
            possibilites = [i for i in possibilites if self.tetris.verify_isolated(i[0], i[1])]

        if len(possibilites):

            a = self.tetris.choose_better(piece, possibilites)

            # choose_better kann None liefern (kein gueltiger Kandidat) ->
            # nicht ueber None indizieren, sondern sauber wegwerfen.
            if a is None:
                log.event(self.state, t('puzzle.choose_better_no_placement'), piece_type=piece.piece_type)
                return None

            log.event(self.state, t('puzzle.placement_chosen'), piece_type=piece.piece_type,
                      pos=a, solver_mode=self.solver_mode)
            self._arm_placement_verify(piece.piece_type, a)
            self.tetris.insert_piece(a[0], a[1], piece)
            if self.tetris.verify_end():
                self.end = True
            self._click_cell(a[0], a[1])

            return True

        # Keine gueltige Platzierung gefunden -> Stein wird weggeworfen (State 7).
        log.event(self.state, t('puzzle.no_valid_placement'),
                  piece_type=piece.piece_type)
        return None

    def try_to_put_chest(self):
        screenshot = self.wincap.get_screenshot()
        result = cv.matchTemplate(screenshot, fish_jigsaw_chest, cv.TM_CCOEFF_NORMED)
        threshold = 0.7

        min_val, max_val, min_loc, max_loc = cv.minMaxLoc(result)

        if max_val < threshold:
            return False
        mouse_x = int(
            max_loc[0] + fish_jigsaw_chest.shape[1] / 2 + self.wincap.offset_x
        )
        mouse_y = int(
            max_loc[1] + fish_jigsaw_chest.shape[0] / 2 + self.wincap.offset_y
        )
        # click the chest
        pydirectinput.click(x=mouse_x, y=mouse_y, button="left")

        gx, gy = geometry.get_piece_point(self.board_size, self.key_points.get('getpiece'))
        mouse_x = int(gx + self.puzzle_offset[0] + self.wincap.offset_x)
        mouse_y = int(gy + self.puzzle_offset[1] + self.wincap.offset_y)
        # click the place where the piece will be
        pydirectinput.click(x=mouse_x, y=mouse_y, button="left")
        # click the board
        pydirectinput.click(
            self.wincap.offset_x + self.puzzle_offset[0],
            self.wincap.offset_y + self.puzzle_offset[1],
            button="left",
        )
        return True


    def runHack(self):

        crop_image = self.get_image()

        timep = getattr(self, 'step_delay', PUZZLE_STEP_DELAY)

        # Selbstdiagnose VOR dem Auslesen von Board/Stein: zeigt der Ausschnitt
        # ueberhaupt plausibel das Puzzle? Bei verschobenem Fenster / falscher
        # Aufloesung ist er schwarz/uniform.
        #
        # SELBSTSTART (v1.3): Ist das Brett (noch) NICHT da, wird nicht mehr hart
        # gestoppt, sondern das Spiel SELBST ueber die Eventuebersicht geoeffnet
        # (Strg+E -> FISCHPUZZLESPIEL -> Klick aufs Namensfeld). Klappt das
        # GAME_OPEN_MAX_TRIES Mal in Folge nicht -> sauberer, gelogger Stop mit
        # Diagnose. Der Versuchszaehler wird genullt, sobald das Brett offen ist
        # (s. unten), damit ein spaeteres Schliessen wieder oeffnen darf.
        calib = calibration.validate_puzzle_region(
            crop_image, expected_size=self.board_size)
        if not calib.ok:
            if self._game_open_tries >= GAME_OPEN_MAX_TRIES:
                log.error(t('puzzle.region_invalid_stop',
                            reasons='; '.join(calib.reasons)))
                log.snapshot('CALIB_FAIL', screen_xy=self.puzzle_offset,
                             extra=calib.details)
                self.botting = False
                return None
            self._game_open_tries += 1
            log.event(self.state, t('puzzle.board_closed_open_retry'),
                      attempt=self._game_open_tries, max=GAME_OPEN_MAX_TRIES)
            if self._open_puzzle_game():
                # Brett offen -> Zaehler nullen, naechster Tick spielt normal.
                self._game_open_tries = 0
                self.timer_action = time()
            return None
        # Brett ist offen -> Selbststart-Zaehler zuruecksetzen.
        self._game_open_tries = 0

        # Inhalts-Hinweise (z.B. "plausibel leeres Startbrett") sind KEIN
        # Stopgrund mehr (FIX Blocker B), werden aber fuer die Debug-Konsole
        # protokolliert, damit der Nutzer dauerhaft schwarze Regionen erkennt.
        if calib.details.get('advisories'):
            log.event(self.state, t('puzzle.calibration_ok_with_advisories'),
                      advisories='; '.join(calib.details['advisories']))

        if self.state == 0:
            log.event(self.state, t('puzzle.request_new_piece'))
            # Neuer Stein-Zyklus -> Deluxe-Verfuegbarkeits-Cache invalidieren
            # (eine zuvor geoeffnete Box hat den Bestand veraendert). No-op,
            # wenn Force-Deluxe aus ist.
            self._reset_force_deluxe_cache()
            gx, gy = geometry.get_piece_point(self.board_size, self.key_points.get('getpiece'))
            mouse_x = int(gx + self.puzzle_offset[0] + self.wincap.offset_x)
            mouse_y = int(gy + self.puzzle_offset[1] + self.wincap.offset_y)

            if time() - self.timer_action > timep:

                # OPPORTUNISTISCHE Deluxe-Nutzung -- REAKTIV, OHNE Box-Zahl-OCR
                # (Nutzer-Vorgabe): liegt JETZT ein freies 2x3-Loch, dann NICHT
                # einen Zufallsstein anfordern, sondern die Deluxe-Box EINFACH
                # OEFFNEN -- sie ist "fast immer" voll. Der Magenta-2x3-Stein
                # fuellt das Loch deterministisch (6 Zellen). KEINE pro-Zyklus-
                # Box-Zahl-Lesung mehr (war unzuverlaessig -> las leeren Slot als 0
                # -> Deluxe nie genutzt; und kostete Speed). Ist die Box doch leer,
                # faengt das ``_register_deluxe_result`` (State 4) reaktiv ab:
                # kein Magenta -> nachlegen (falls aktiv) bzw. Deluxe abschalten.
                if (getattr(self, 'force_deluxe', False)
                        and self.solver_mode == 'trained'
                        and not getattr(self, '_deluxe_disabled', False)):
                    hole = deluxe.find_free_2x3(self.tetris.board)
                    if hole is not None:
                        log.event(self.state, t('puzzle.deluxe_try_open'),
                                  hole=hole,
                                  misses=getattr(self, '_deluxe_miss_streak', 0))
                        self._awaiting_deluxe = True
                        self._open_deluxe_box_and_place()
                        self.state = 1
                        self.timer_action = time()
                        return None

                if self.detect_end_game(crop_image):
                    if not self.try_to_put_chest():
                        # SUPER-SMARTE Diagnose ueber die 24 Zell-Reads:
                        #   alles leer        -> kein aktives Puzzle / leeres Brett
                        #   ueberwiegend Steine-> echtes volles Brett ohne Truhe
                        #   Mischung/Garbage  -> gar kein gueltiges Board erkannt
                        d = self._diagnose_board(crop_image)
                        v, e, g = d['valid'], d['empty'], d['garbage']
                        if v == 0 and g == 0:
                            log.error(t('puzzle.no_active_puzzle',
                                        filled=v + g, empty=e))
                        elif v >= 18:
                            log.error(t('puzzle.board_full_no_chest'))
                        else:
                            log.error(t('puzzle.board_not_recognized',
                                        valid=v, garbage=g, empty=e))
                        log.event(self.state, t('puzzle.stop_no_progress',
                                  valid=v, garbage=g, empty=e))
                        self.botting = False
                        return None

                pydirectinput.click(x=mouse_x, y=mouse_y, button='left')
                self.state = 1
                self.timer_action = time()

        if self.state == 1:

            if time() - self.timer_action > timep:
                log.event(self.state, t('puzzle.confirm_selection_get_piece'))
                self.press_comfirm()
                self.state = 2
                self.timer_action = time()

        if self.state == 2:

            csx, csy = geometry.color_sample(self.board_size, self.key_points.get('color'))
            mouse_x = int(csx + self.puzzle_offset[0] + self.wincap.offset_x)
            mouse_y = int(csy + self.puzzle_offset[1] + self.wincap.offset_y)

            if time() - self.timer_action > timep:
                log.event(self.state, t('puzzle.move_mouse_to_color_sample'))
                self.state = 4
                self.timer_action = time()
                pydirectinput.moveTo(mouse_x, mouse_y)
                # Farb-Lese-Retry scharf schalten: bis zu dieser Deadline wird
                # in State 4 pro Frame neu gelesen statt sofort zu verwerfen
                # (der Stein ist nach dem Holen oft noch nicht gerendert).
                self._color_retry_until = time() + PIECE_COLOR_RETRY_S
                self._color_read_announced = False

        if self.state == 4:

            if time() - self.timer_action > timep:
                if not self._color_read_announced:
                    log.event(self.state, t('puzzle.read_piece_color'))
                    self._color_read_announced = True
                retrying = time() < self._color_retry_until
                piece = self.get_new_piece_color(crop_image, quiet=retrying)
                if piece is None and retrying:
                    # Noch kein Treffer, Deadline laeuft -> naechster Frame
                    # liest ein FRISCHES Capture. Kein State-Wechsel, kein
                    # Verwerfen, kein Log-Spam (quiet). Erst nach Ablauf der
                    # Deadline geht ein echter Miss (voll geloggt) in den
                    # bestehenden Verwerfen-Pfad.
                    return None
                # Deluxe-Guard ZUERST: haben wir gerade die DELUXE-Box geoeffnet?
                # (getrennte Methode -> testbar). True = es war ein Deluxe-Versuch
                # (anderer Slot als getpiece) -> zaehlt NICHT als Standard-Box-Miss.
                deluxe_attempt = self._register_deluxe_result(piece)

                # Leere Box -> Spiel NEU OEFFNEN (v1.3): ein ECHTER Miss (kein
                # Stein nach Ablauf des Retry-Fensters) bedeutet, der getpiece-
                # Klick lieferte nichts -> moeglicher Hinweis auf eine LEERE
                # Standard-Box. Streak zaehlen; ein erfolgreicher Read setzt sie
                # zurueck (nur AUFEINANDER folgende Leerschuesse gelten als "Box
                # leer"). Deluxe-Versuche zaehlen hier NICHT mit (oben separat).
                if piece is not None:
                    # Erfolgreicher Stein = (evtl. nach Neustart) wieder spielbar
                    # -> BEIDE Zaehler nullen. _box_reopen_tries zaehlt dadurch nur
                    # AUFEINANDERFOLGENDE Neustarts OHNE Fortschritt (echtes "Boxen
                    # leer"); produktive Neustarts sind UNBEGRENZT. Vorher
                    # akkumulierte der Zaehler ueber die Session -> Stop schon nach
                    # dem 1. Nachlegen (genau der gemeldete Bug 2026-06-20).
                    self._empty_getpiece_streak = 0
                    self._box_reopen_tries = 0
                elif deluxe_attempt:
                    pass  # Deluxe-Fehlversuch -> kein Standard-Box-Streak
                else:
                    self._empty_getpiece_streak = (
                        getattr(self, '_empty_getpiece_streak', 0) + 1)
                    log.event(self.state, t('puzzle.box_empty_probe',
                              streak=self._empty_getpiece_streak,
                              threshold=BOX_EMPTY_STREAK,
                              reopen=self._box_reopen_tries))
                    if self._empty_getpiece_streak >= BOX_EMPTY_STREAK:
                        # Boxen wirklich leer. Schon einmal (oder oefter) neu
                        # geoeffnet und es bleibt leer -> Boxen aufgebraucht: hart
                        # stoppen (kein ESC<->Open-Endlos-Loop).
                        if self._box_reopen_tries >= BOX_REOPEN_MAX:
                            log.error(t('puzzle.boxes_empty_stop'))
                            log.snapshot('BOXES_EMPTY',
                                         screen_xy=self.puzzle_offset,
                                         extra='reopen_tries={}'.format(
                                             self._box_reopen_tries))
                            self.botting = False
                            return None
                        # ESC (Spiel/leere Boxen schliessen) -> via Event neu
                        # oeffnen -> weiterspielen mit frisch gefuellten Boxen.
                        self._box_reopen_tries += 1
                        log.event(self.state, t('puzzle.box_empty_reopen',
                                  tries=self._box_reopen_tries,
                                  max=BOX_REOPEN_MAX))
                        self._press_esc()
                        sleep(FLOW_PACE_S)
                        # force=True: nach dem ESC NICHT auf board_open kurz-
                        # schliessen -> den Eventlisten-Neustart erzwingen.
                        if self._open_puzzle_game(force=True):
                            self._empty_getpiece_streak = 0
                            self.state = 0
                            self.timer_action = time()
                            return None
                        # Reopen fehlgeschlagen -> Diagnose, dann Stop.
                        log.error(t('puzzle.boxes_empty_stop'))
                        self.botting = False
                        return None
                self.state = 5
                self.timer_action = time()
                self.new_piece = piece

        if self.state == 5:
            if time() - self.timer_action > timep:
                log.event(self.state, t('puzzle.read_board_compute_move'),
                          new_piece=self.new_piece)
                self.timer_action = time()
                self.set_puzzle_state(crop_image)
                # Plausibilitaet (④): verdaechtige Brett-Lesung (zu viele
                # Garbage-Zellen) -> kurz neu lesen, statt auf einem Fehl-Brett
                # zu entscheiden. Nach Ablauf des Fensters best-effort weiter.
                if self._board_suspicious():
                    if self._board_retry_until == 0.0:
                        self._board_retry_until = time() + BOARD_READ_RETRY_S
                    if time() < self._board_retry_until:
                        log.event(self.state, 'Brett verdaechtig -> erneut lesen',
                                  garbage=self._last_board_garbage)
                        return None
                    log.event(self.state, 'Brett weiter verdaechtig -> '
                              'best-effort fortfahren',
                              garbage=self._last_board_garbage)
                self._board_retry_until = 0.0
                if self.play_game():
                    self.state = 6
                else:
                    self.state = 7

        if self.state == 6:
            if time() - self.timer_action > timep:
                log.event(self.state, t('puzzle.confirm_move'))
                self.press_comfirm()
                self.timer_action = time()
                if self.end:
                    self.state = 9
                else:
                    self.state = 0

        if self.state == 7:
            if time() - self.timer_action > timep:
                log.event(self.state, t('puzzle.discard_piece_no_placement'))
                self.throw_pice()
                self.timer_action = time()
                self.state = 8

        if self.state == 8:
            if time() - self.timer_action > timep:
                log.event(self.state, t('puzzle.confirm_discard'))
                self.press_comfirm()
                self.timer_action = time()
                self.state = 0

        if self.state == 9:
            if time() - self.timer_action > 2:
                log.event(self.state, t('puzzle.puzzle_solved_collect_reward'))
                self.end = False
                self.press_comfirm_cake()
                self.timer_action = time()
                self.state = 0

        return None
