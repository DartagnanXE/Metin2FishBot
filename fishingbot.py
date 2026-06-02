import pydirectinput
import cv2 as cv
from time import time, sleep
from windowcapture import WindowCapture
from hsvfilter import HsvFilter
from fishfilter import Filter
from i18n import t
from respath import resource_path
import constants
import mount

# Reine Such-/Logging-Primitive (zustandslos) leben in fishing_match; HIER in den
# Namespace re-importiert, damit (a) die Detect-Methoden sie als bare globale
# Namen aufloesen und (b) Tests, die ``fishingbot._match_template_max`` direkt
# aufrufen, unveraendert funktionieren.
from fishing_match import _flog, _match_template_max  # noqa: F401  (re-export)
from fishing_detect import FishingDetectMixin


class FishingBot(FishingDetectMixin):

    #properties
    fish_pos_x = None
    fish_pos_y = None
    fish_last_time = None
    detect_text_enable = False
    botting = False

    FISH_RANGE = 74
    FISH_VELO_PREDICT = 30

    # BAIT_POSITION = (473, 750)
    # FISH_POSITION = (440, 750)

    FILTER_CONFIG = [49, 0, 58, 134, 189, 189, 0, 0, 0, 0]

    FISH_WINDOW_CLOSE = (430, 115)

    # Golden-Tuna-Dialog: 3 senkrecht gestapelte Knoepfe (Spielkoordinaten,
    # relativ zum Fenster-Offset). Feld 2 (y=280) ist der urspruengliche Klick
    # auf den mittleren Knopf. 1 = Freilassen, 2 = Aufschneiden,
    # 3 = Als Koeder benutzen. Knoepfe sind gleichmaessig (DY) gestapelt.
    GOLDEN_TUNA_X = 350
    GOLDEN_TUNA_DY = 38
    GOLDEN_TUNA_Y = {1: 280 - GOLDEN_TUNA_DY,   # 242 (Feld 1, oben)
                     2: 280,                    # 280 (Feld 2, urspruengl. Klick)
                     3: 280 + GOLDEN_TUNA_DY}   # 318 (Feld 3, unten)

    # set position of the fish windows
    # this value can be diferent by the sizes of the game window

    FISH_WINDOW_SIZE = (280, 226)
    FISH_WINDOW_POSITION = (95, 80)

    wincap = None

    fishfilter = Filter() if detect_text_enable else None

    # Load the needle image

    # WICHTIG: resource_path() -- in der gepackten EXE liegen die Bilder im
    # PyInstaller-Bundle (sys._MEIPASS), NICHT im Arbeitsverzeichnis. Ein nackter
    # Pfad 'images/..' laedt dort None -> matchTemplate erkennt NIE etwas (das
    # Minispiel wird nie gespielt). Mit resource_path laden die Vorlagen auch aus
    # der EXE -- wie es das Puzzle (fish_jigsaw_chest) schon richtig macht.
    needle_img = cv.imread(resource_path('images/fiss.jpg'), cv.IMREAD_UNCHANGED)
    needle_img_clock = cv.imread(resource_path('images/clock.jpg'), cv.IMREAD_UNCHANGED)

    # Some time cooldowns

    detect_text = True

    # Limit time

    initial_time = None

    end_time_enable = False

    end_time = 0

    # for fps

    loop_time = time()

    # The mouse click cooldown

    timer_mouse = time()

    # The timer beteween the states

    timer_action = time()

    bait_time = 2
    throw_time = 2
    game_time = 2

    # Konfigurierbare In-Game-Tasten (Default = bisheriges Verhalten '2'/'1').
    # Werden von hack._on_start aus der Config injiziert, BEVOR set_to_begin
    # laeuft. Default-Werte halten das Verhalten byte-stabil.
    bait_key = '2'
    cast_key = '1'

    # Mount-Animation-Cancel (Default AUS -> byte-stabil). Wird in set_to_begin
    # aus den values ('-MOUNT-'/'-MOUNTKEY-') gelesen. Nach einem bestaetigten
    # Minispiel-Ende drueckt der Bot die Taste, wartet 0.1s, drueckt erneut
    # (auf-/absteigen) -> bricht die Fang-Animation ab -> schneller neu auswerfen.
    mount_enabled = False
    mount_key = '3'

    # Counter-Hook: einmal pro bestaetigtem Fang aufgerufen (von hack.py gesetzt).
    # None -> kein Hook (FishingBot bleibt von stats.py entkoppelt).
    on_catch = None

    # Golden-Tuna: welches der 3 Dialogfelder geklickt wird (Default 3 = Koeder).
    golden_tuna_action = 3

    # This is the filter parameters, this help to find the right image
    hsv_filter = HsvFilter(*FILTER_CONFIG)

    state = 0

    # Selbstdiagnose: erschien in der aktuellen Angel-Runde ein echtes Minispiel
    # (Uhr)? + Zaehler aufeinanderfolgender Runden OHNE Biss -> klare Warnung
    # statt stummem Endlos-Loop, wenn nichts Echtes erkannt wird.
    _bite_seen_this_cycle = False
    _casts_without_bite = 0
    _best_minigame_conf = 0.0   # beste Uhr-Trefferguete dieser Runde (Diagnose)

    # Die reinen Erkennungs-Methoden detect / detect_minigame / detect_daily_reward
    # liefert der FishingDetectMixin (oben eingemischt) -- gleiche Methoden-
    # aufloesung, gleicher self.-Zustand. Hier verbleibt die zustandsbehaftete
    # Cast-/State-Machine.

    def _on_cycle_end(self):
        """Nach JEDER Angel-Runde aufrufen: zaehlt aufeinanderfolgende Runden
        OHNE erkanntes Minispiel/Biss und WARNT klar, sobald der Bot nur noch
        ins Leere wirft (kein echtes Spiel / falsche Position / Angel nicht
        ausgeworfen). Stoppt NICHT -- auf echtem Spiel sind einzelne Leer-
        Auswuerfe normal -- meldet aber unmissverstaendlich, dass nichts
        Echtes erkannt wird, statt stumm weiterzuloopen.
        """
        # Beste Uhr-Trefferguete der Runde melden (Diagnose: >0.90 = erkannt;
        # 0.5-0.9 = Uhr da, aber Schwelle zu hoch; ~0 = Capture/Position falsch).
        _flog(3, t('fishing.minigame_confidence',
                   conf='{:.2f}'.format(self._best_minigame_conf)))
        if self._bite_seen_this_cycle:
            self._casts_without_bite = 0
        else:
            self._casts_without_bite += 1
            if (self._casts_without_bite == 3
                    or self._casts_without_bite % 10 == 0):
                _flog('-', t('fishing.no_bite_streak',
                             n=self._casts_without_bite))
        self._bite_seen_this_cycle = False
        self._best_minigame_conf = 0.0

    def _fire_on_catch(self):
        """Ruft den (optionalen) Counter-Hook genau einmal pro Fang. Wirft nie --
        hack.py setzt ``on_catch``; ist er None, passiert nichts (Entkopplung)."""
        callback = self.on_catch
        if callback is None:
            return
        try:
            callback()
        except Exception:
            pass

    def _do_mount_cancel(self, steps):
        """Fuehrt die PURE Mount-Sequenz (mount.mount_cancel_steps) als
        Tastendruecke aus: ('press', key) -> keyDown/keyUp, ('sleep', s) ->
        sleep. Reiner Thin-Executor; die Logik liegt in mount.py. Wirft nie."""
        try:
            for action, value in steps:
                if action == 'press':
                    pydirectinput.keyDown(value)
                    pydirectinput.keyUp(value)
                elif action == 'sleep':
                    sleep(value)
        except Exception:
            pass

    def set_to_begin(self, values):

        # Zeitlimit bei JEDEM Start zuruecksetzen und NUR bei positiver
        # Minutenzahl aktivieren. Sonst (Haken an, Feld "0") waere
        # ``time()-initial > 0`` sofort wahr -> der Bot wuerde direkt stoppen;
        # und ein altes Limit aus einem frueheren Lauf darf nicht haengenbleiben.
        self.end_time_enable = False
        self.end_time = 0
        if values['-ENDTIMEP-']:
            try:
                self.end_time = int(values['-ENDTIME-']) * 60
            except Exception:
                self.end_time = 0
            self.end_time_enable = self.end_time > 0

        self.bait_time = values['-BAITTIME-']
        self.throw_time = values['-THROWTIME-']
        self.game_time = values['-STARTGAME-']

        # Golden-Tuna-Feld defensiv lesen -- ein kaputter/fehlender Wert darf das
        # Angeln NIE brechen (-> Default 3 = Koeder benutzen).
        try:
            action = int(values.get('-GOLDENTUNA-', 3))
        except (TypeError, ValueError):
            action = 3
        self.golden_tuna_action = action if action in (1, 2, 3) else 3

        # Mount-Animation-Cancel defensiv aus den frozen keys lesen (Default
        # AUS/'3' -> byte-stabil). Ein fehlender/kaputter Wert darf nichts
        # brechen.
        self.mount_enabled = bool(values.get('-MOUNT-', False))
        mkey = values.get('-MOUNTKEY-', '3')
        self.mount_key = str(mkey) if mkey else '3'

        # FRUEH loggen -- noch VOR dem Fenster-Capture, damit der Start auch dann
        # in der Console steht, wenn das Spielfenster (noch) nicht gefunden wird
        # (sonst wuerde diese Zeile bei einem Capture-Fehler nie erreicht).
        _flog(0, t('fishing.started'), bait=self.bait_time,
              throw=self.throw_time, game=self.game_time,
              golden_action=self.golden_tuna_action,
              stop_after_min=(self.end_time // 60 if self.end_time_enable else 0))

        # Defensiv: konnten die Vorlagenbilder geladen werden? In der EXE waren sie
        # frueher None (nackter Pfad) -> Minispiel nie erkannt. Jetzt klar melden.
        if self.needle_img is None or self.needle_img_clock is None:
            _flog(0, t('fishing.needles_missing'),
                  fiss=(self.needle_img is None),
                  clock=(self.needle_img_clock is None))

        try:
            self.wincap = WindowCapture(constants.GAME_NAME)
        except Exception as exc:
            _flog(0, t('fishing.game_window_not_found'),
                  fenster=constants.GAME_NAME, detail=str(exc))
            raise
        self.state = 0
        self.initial_time = time()
        self.timer_action = time()
        # Selbstdiagnose pro Lauf zuruecksetzen.
        self._bite_seen_this_cycle = False
        self._casts_without_bite = 0

        mouse_x = int(self.FISH_WINDOW_POSITION[0] + self.wincap.offset_x + 200)
        mouse_y = int(self.FISH_WINDOW_POSITION[1] + self.wincap.offset_y + 200)

        pydirectinput.click(x=mouse_x, y=mouse_y, button='right')

    def runHack(self):
        screenshot = self.wincap.get_screenshot()

        # crop and aply hsv filter
        # detect_end_img ist der ROHE Crop (View), crop_img wird gefiltert. Beide
        # gehen vom IDENTISCHEN Ausschnitt aus -> einmal schneiden statt zweimal.
        # apply_hsv_filter liefert ein NEUES Array (mutiert die Eingabe nicht), der
        # rohe Crop bleibt also unveraendert -- byte-stabil zum frueheren Verhalten.
        crop_img = screenshot[self.FISH_WINDOW_POSITION[1]:self.FISH_WINDOW_POSITION[1]+self.FISH_WINDOW_SIZE[1],
                            self.FISH_WINDOW_POSITION[0]:self.FISH_WINDOW_POSITION[0]+self.FISH_WINDOW_SIZE[0]]
        detect_end_img = crop_img
        crop_img = self.hsv_filter.apply_hsv_filter(crop_img)

        cv.putText(crop_img, 'FPS: ' + str(1/(time() - self.loop_time))[:2],
                (10, 200), cv.FONT_HERSHEY_SIMPLEX,  0.5, (0, 255, 0), 2)
        cv.putText(crop_img, 'State: ' + str(self.state) + ' ' + str(time() - self.timer_action)[:5],
                (10, 160), cv.FONT_HERSHEY_SIMPLEX,  0.5, (0, 255, 0), 2)
        self.loop_time = time()

        daily = self.detect_daily_reward(screenshot)

        if daily:
            # Konfigurierbares Feld klicken (1/2/3, Default 3 = Koeder). Das
            # gewaehlte Feld + die Koordinaten werden geloggt, damit der Nutzer
            # im Spiel pruefen/feinjustieren kann. (Ersetzt das alte feste
            # y=280-Verhalten und den 'fishing.daily_reward_confirmed'-Log.)
            field = self.golden_tuna_action
            mouse_x = int(self.wincap.offset_x + self.GOLDEN_TUNA_X)
            mouse_y = int(self.wincap.offset_y + self.GOLDEN_TUNA_Y[field])
            pydirectinput.click(x=mouse_x, y=mouse_y)
            if time() - getattr(self, '_last_daily_log', 0) > 3:
                self._last_daily_log = time()
                _flog(self.state, t('fishing.golden_tuna_clicked'),
                      field=field, x=mouse_x, y=mouse_y)

        # Verify total time

        if self.end_time_enable and time() - self.initial_time > self.end_time:
            _flog(self.state, t('fishing.stop_time_limit'),
                  minutes=self.end_time // 60)
            self.botting = False

        # State to click put the bait in the rod

        if self.state == 0:

            if time() - self.timer_action > self.bait_time:
                self.detect_text = True
                pydirectinput.keyDown(self.bait_key)
                pydirectinput.keyUp(self.bait_key)
                self.state = 1
                self.timer_action = time()
                _flog(1, t('fishing.bait_set'))

        # State to throw the bait

        if self.state == 1:
            if time() - self.timer_action > self.throw_time:
                pydirectinput.keyDown(self.cast_key)
                pydirectinput.keyUp(self.cast_key)
                self.state = 2
                self.timer_action = time()
                _flog(2, t('fishing.cast_out'))

        # Delay to start the clicks

        if self.state == 2:
            if time() - self.timer_action > self.game_time:
                self.state = 3
                self.timer_action = time()
                _flog(3, t('fishing.minigame_phase_start'))

        # Countdown to finish the state

        detected_end = self.detect_minigame(detect_end_img)

        if self.state == 3:

            # Merken, ob in DIESER Angel-Runde ueberhaupt ein echtes Minispiel
            # (Uhr) erschien -- trennt "echte Runde beendet" von "kein Biss".
            if detected_end:
                self._bite_seen_this_cycle = True

            if time() - self.timer_action > 15:
                self.timer_action = time()
                self.state = 0
                _flog(0, t('fishing.minigame_timeout'))
                self._on_cycle_end()
            if time() - self.timer_action > 5 and detected_end is False:
                self.timer_action = time()
                self.state = 0
                # SMART: echtes Rundenende vs. "nie ein Minispiel gesehen".
                if self._bite_seen_this_cycle:
                    _flog(0, t('fishing.minigame_finished'))
                    # BESTAETIGTER Fang: Counter-Hook feuern (einmal) + optional
                    # die Fang-Animation per Mount-Toggle abbrechen. Beides streng
                    # defensiv -- darf den Angel-Loop nie kippen.
                    self._fire_on_catch()
                    if self.mount_enabled:
                        self._do_mount_cancel(mount.mount_cancel_steps(
                            self.mount_key))
                else:
                    _flog(0, t('fishing.no_bite'))
                self._on_cycle_end()

            if self.detect_text_enable and time() - self.timer_action > 1.5:
                if self.detect_text:
                    if self.fishfilter.match_with_text(screenshot) is False:
                        mouse_x = int(self.wincap.offset_x + self.FISH_WINDOW_CLOSE[0])
                        mouse_y = int(self.wincap.offset_y + self.FISH_WINDOW_CLOSE[1])
                        pydirectinput.click(x=mouse_x, y=mouse_y, button='left')
                        pydirectinput.click(x=mouse_x, y=mouse_y, button='left')

                self.detect_text = False


        # make the click

        if (time() - self.timer_mouse) > 0.3 and self.state == 3 and detected_end:
            
            # Detect the fish            

            square_pos = self.detect(crop_img)

            if square_pos:

                # Recalculate the mouse position with the fish position

                pos_x = square_pos[0]
                pos_y = square_pos[1]

                center_x = self.FISH_WINDOW_SIZE[0]/2
                center_y = self.FISH_WINDOW_SIZE[1]/2

                mouse_x = int(pos_x)
                mouse_y = int(pos_y)

                # Verify if the fish is in range

                d = self.FISH_RANGE**2 - ((center_x-mouse_x)**2 + (center_y-mouse_y)**2)

                # Make the click

                if (d > 0):
                    self.timer_mouse = time()

                    mouse_x = int(pos_x + self.FISH_WINDOW_POSITION[0] + self.wincap.offset_x)
                    mouse_y = int(pos_y + self.FISH_WINDOW_POSITION[1] + self.wincap.offset_y)

                    pydirectinput.click(x=mouse_x, y=mouse_y)
                    _flog(3, t('fishing.fish_clicked'), x=mouse_x, y=mouse_y)

        return crop_img
