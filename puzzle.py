import pydirectinput
import cv2 as cv
from time import time
from windowcapture import WindowCapture
from tetris import Tetris
from piece import Piece
import json
import constants
import calibration
import geometry
import trained_solver
from debuglog import log
from respath import resource_path
from i18n import t
from puzzle_detect import PuzzleDetectMixin


fish_jigsaw_chest = cv.imread(resource_path("images/fish_jigsaw_chest.png"))

class PuzzleBot(PuzzleDetectMixin):

    #properties
    
    botting = False

    PUZZLE_WINDOW_SIZE = (260, 170)
    PUZZLE_WINDOW_POSITION = (270, 227)

    PUZZLE_GET_NEW_PIECE = (230, 85)
    PUZZLE_COMFIRM = (100, 90)
    PUZZLE_GET_NEW_PIECE_COLOR = (110, 150)

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

    state = 0

    end = False
    dictdump = None

    def set_to_begin(self, values):
        # Logdatei pro Lauf frisch initialisieren (auch aus der .exe nutzbar).
        log.configure(to_console=True, to_file=True,
                      path='puzzle_debug.log', level='DEBUG')
        log.section(t('puzzle.start_section'))
        self.wincap = WindowCapture(constants.GAME_NAME)
        self.state = 0
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

    # Die reinen Vision-Bausteine _sample_cell_bgr / _classify_piece /
    # _is_valid_piece_color / _diagnose_board / detect_end_game liefert der
    # PuzzleDetectMixin (oben eingemischt) -- gleiche Methodenaufloesung, gleicher
    # self.-Zustand. Hier verbleibt die Solver-Glue-/Klick-State-Machine.

    def set_puzzle_state(self, crop_img):

        board = [[0,0,0,0,0,0],
                [0,0,0,0,0,0],
                [0,0,0,0,0,0],
                [0,0,0,0,0,0]]

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

                cv.rectangle(crop_img, (cx, cy), (cx, cy),
                            color=(0, 255, 255), thickness=4, lineType=cv.LINE_4)

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

    def press_comfirm(self):
        self._click_board_point(geometry.confirm_point, 'confirm', 'left')

    def press_comfirm_cake(self):
        self._click_board_point(geometry.cake_point, 'cake', 'left')

    def throw_pice(self):
        self._click_board_point(geometry.confirm_point, 'confirm', 'right')

    def get_new_piece_color(self, crop_image):

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
            return piece_type

        # Keine der 6 engen BGR-Ranges getroffen -> None (Solver faengt das ab).
        # Echte BGR-Werte protokollieren, damit der Nutzer Schwarz/Garbage
        # (Position/Aufloesung falsch) von plausibler Farbe (Range-Drift)
        # unterscheiden kann.
        log.event(self.state, t('puzzle.piece_color_not_detected'), x=x, y=y, b=b, g=g, r=r)
        log.snapshot('PIECE_COLOR_MISS', bgr=(b, g, r), screen_xy=(x, y),
                     extra='keine der 6 BGR-Ranges getroffen -> new_piece=None')
        return None

    def play_game(self):

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
            a = trained_solver.choose_placement(self.tetris.board, piece, False)
            if a is None:
                log.event(self.state,
                          t('puzzle.ai_no_improving_placement'),
                          piece_type=piece.piece_type, solver_mode='trained')
                return None

            log.event(self.state, t('puzzle.placement_chosen'), piece_type=piece.piece_type,
                      pos=a, solver_mode='trained')
            self.tetris.insert_piece(a[0], a[1], piece)
            if self.tetris.verify_end():
                self.end = True
            px, py = geometry.cell_point(a[0], a[1], self.board_size)
            mouse_x = px + self.puzzle_offset[0] + self.wincap.offset_x
            mouse_y = py + self.puzzle_offset[1] + self.wincap.offset_y
            pydirectinput.click(mouse_x, mouse_y)

            return True

        decision, pos = self.tetris.find_first(piece, self.dictdump)
        if decision == 1:

            log.event(self.state, t('puzzle.opening_book_move'), piece_type=piece.piece_type,
                      pos=pos)
            self.tetris.insert_piece(pos[0], pos[1], piece)
            if self.tetris.verify_end():
                self.end = True
            px, py = geometry.cell_point(pos[0], pos[1], self.board_size)
            mouse_x = px + self.puzzle_offset[0] + self.wincap.offset_x
            mouse_y = py + self.puzzle_offset[1] + self.wincap.offset_y
            pydirectinput.click(mouse_x, mouse_y)

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
            self.tetris.insert_piece(a[0], a[1], piece)
            if self.tetris.verify_end():
                self.end = True
            px, py = geometry.cell_point(a[0], a[1], self.board_size)
            mouse_x = px + self.puzzle_offset[0] + self.wincap.offset_x
            mouse_y = py + self.puzzle_offset[1] + self.wincap.offset_y
            pydirectinput.click(mouse_x, mouse_y)

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

        timep = 0.2

        # Selbstdiagnose VOR dem Auslesen von Board/Stein: zeigt der Ausschnitt
        # ueberhaupt plausibel das Puzzle? Bei verschobenem Fenster / falscher
        # Aufloesung ist er schwarz/uniform -> frueher stiller Crash, jetzt ein
        # sauberer, GELOGGTER Stop mit klarer Ursache fuer den Nutzer.
        calib = calibration.validate_puzzle_region(
            crop_image, expected_size=self.board_size)
        if not calib.ok:
            log.error(t('puzzle.region_invalid_stop', reasons='; '.join(calib.reasons)))
            log.snapshot('CALIB_FAIL', screen_xy=self.puzzle_offset,
                         extra=calib.details)
            self.botting = False
            return None

        # Inhalts-Hinweise (z.B. "plausibel leeres Startbrett") sind KEIN
        # Stopgrund mehr (FIX Blocker B), werden aber fuer die Debug-Konsole
        # protokolliert, damit der Nutzer dauerhaft schwarze Regionen erkennt.
        if calib.details.get('advisories'):
            log.event(self.state, t('puzzle.calibration_ok_with_advisories'),
                      advisories='; '.join(calib.details['advisories']))

        if self.state == 0:
            log.event(self.state, t('puzzle.request_new_piece'))
            gx, gy = geometry.get_piece_point(self.board_size, self.key_points.get('getpiece'))
            mouse_x = int(gx + self.puzzle_offset[0] + self.wincap.offset_x)
            mouse_y = int(gy + self.puzzle_offset[1] + self.wincap.offset_y)

            if time() - self.timer_action > timep:

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

        if self.state == 4:

            if time() - self.timer_action > timep:
                log.event(self.state, t('puzzle.read_piece_color'))
                self.state = 5
                self.timer_action = time()
                self.new_piece = self.get_new_piece_color(crop_image)

        if self.state == 5:
            if time() - self.timer_action > timep:
                log.event(self.state, t('puzzle.read_board_compute_move'),
                          new_piece=self.new_piece)
                self.timer_action = time()
                self.set_puzzle_state(crop_image)
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
