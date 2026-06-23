import pydirectinput
pydirectinput.PAUSE = 0.1  # KEYBOARD needs this hold to register in-game; 0.05 was too short for keys (fishing didn't cast). = pydirectinput default (what v1.1.0 used). Mouse-only flows (scan) lower it per-op to 0.05.
import cv2 as cv


# -- Input-Backend (Multiclient-Naht, Build-Schritt 6) ---------------------
# Single-Client (Default): _DirectBackend ruft pydirectinput FORM-EXAKT wie
# bisher -> byte- UND test-identisch (Tests patchen ``fishingbot.pydirectinput``;
# die Methoden loesen den Namen zur Laufzeit auf, der Patch greift weiter).
# Multiclient (eigener Worker-Prozess): set_input_backend() ersetzt _input durch
# einen Lease-gebundenen Backend (CursorClient). WICHTIG: zusammengehoerige
# Tastendruecke (keyDown+keyUp) laufen ueber EINE Methode (.key) -> EIN Lease,
# damit kein anderer Client mitten in den Tastendruck graetscht (Atomizitaet).
class _DirectBackend:
    def set_pause(self, value):
        pydirectinput.PAUSE = value

    def click(self, x, y, button='left'):
        # Form-exakt: ohne button (= Default 'left') KEIN button-kwarg senden,
        # damit bestehende Test-Assertions auf die Aufrufform unveraendert gelten.
        if button == 'left':
            pydirectinput.click(x=x, y=y)
        else:
            pydirectinput.click(x=x, y=y, button=button)

    def key(self, key):
        pydirectinput.keyDown(key)
        pydirectinput.keyUp(key)


_input = _DirectBackend()


def set_input_backend(backend):
    """Ersetzt das Input-Backend (Multiclient-Worker). Default = _DirectBackend."""
    global _input
    _input = backend


# Koeder-Nachlegen laeuft NICHT ueber _input (das kennt nur click/key), sondern
# braucht moveTo/mouseDown/mouseUp (gehaltener Drag, refill.py). Single-Client =
# None -> direkt das Modul ``pydirectinput`` (byte-identisch, weiter test-patchbar
# ueber ``fishingbot.pydirectinput``). Multiclient-Worker setzt hier ein
# lease-gebundenes Screen-Backend (cursor_client.LeasedScreenCursor) -> der Drag
# laeuft als EIN Lease-Burst statt roh am falschen Fenster (Finding #1).
_refill_backend = None


def set_refill_backend(backend):
    """Ersetzt das Refill-Input-Backend (Multiclient). Default None = pydirectinput."""
    global _refill_backend
    _refill_backend = backend


import cv2 as cv  # noqa: E402  (nach dem Input-Backend-Block; bewusst)
from time import time, sleep
import random
from windowcapture import WindowCapture
from hsvfilter import HsvFilter
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

# Globales Stop-Signal (Responsiveness): die schweren Refill-Ops pollen es ueber
# interruptible-sleeps + ein Zeitbudget und brechen bei F6 sofort ab. Default ist
# das NIE-gesetzte NULL_SIGNAL -> ohne Injektion aendert sich nichts (byte-stabil).
import stop_signal as _stopsig

# Chat-OCR-Kern + reine Whitelist-Entscheidung. Defensiv (soft) importiert -- die
# Whitelist ist opt-in (Default AUS), und ein fehlender Import darf das Angeln NIE
# brechen: dann bleibt die Whitelist einfach wirkungslos (es wird alles geangelt).
try:
    import fishing_chat as _fc
    import fishing_whitelist as _wl
except Exception:                       # pragma: no cover - defensiver Import
    _fc = None
    _wl = None

# Koeder-Nachlegen-Engine (opt-in, Default AUS). Soft importiert -- ein fehlender
# Import (z. B. fehlendes numpy headless) darf das Angeln NIE brechen: dann bleibt
# das Nachlegen einfach wirkungslos. Die gesamte Logik (Quickslot-Leer-Erkennung,
# Inventar-Scan + Drag) liegt fertig in interface/refill.py -- HIER nur der
# gedrosselte Trigger im Angel-Lauf.
try:
    from interface import refill as _refill
except Exception:                       # pragma: no cover - defensiver Import
    _refill = None


class FishingBot(FishingDetectMixin):

    #properties
    fish_pos_x = None
    fish_pos_y = None
    fish_last_time = None
    botting = False

    FISH_RANGE = 74
    FISH_VELO_PREDICT = 30

    # BAIT_POSITION = (473, 750)
    # FISH_POSITION = (440, 750)

    FILTER_CONFIG = [49, 0, 58, 134, 189, 189, 0, 0, 0, 0]

    # Golden-Tuna-Dialog: 3 senkrecht gestapelte Knoepfe. 1 = Freilassen,
    # 2 = Aufschneiden, 3 = Als Koeder benutzen. Knoepfe sind gleichmaessig (DY)
    # gestapelt.
    #
    # KOORDINATEN-SYSTEM (kritisch): der Bot KLICKT in CLIENT-Koordinaten --
    # ``self.wincap.offset_{x,y}`` ist der CLIENT-Ursprung (Fensterecke + 8px
    # Rand + 30px Titelleiste), und der Klick ist ``offset + (X, Y)``. Die
    # Referenz-Screenshots (FischOCR/GoldenerThunfisch*.png) sind aber das
    # VOLLBILD 802x632 = Client + ~31px Titelleiste + 1px-Rand. Die DARAUS
    # gemessenen Knopf-Mitten sind also FULL-FRAME und liegen, 1:1 als
    # Client-Koordinate benutzt, ~31px ZU TIEF (und 1px zu weit rechts) -> der
    # Klick verfehlt den Knopf. Darum die Full-Frame-Messung in CLIENT umrechnen:
    # CLIENT = FULL_FRAME - (1, 31).
    #   gemessen FULL-FRAME : X=400, Y={Freilassen:268, Aufschneiden:300,
    #                         Koeder:332} (DY=32), Confirm-OK (400,277)
    #   -> CLIENT           : X=399, Y={237, 269, 301} (DY unveraendert=32),
    #                         Confirm-OK (399,246)
    # Klickpositionen werden geloggt (fishing.golden_tuna_clicked/_confirmed).
    GOLDEN_TUNA_X = 399                          # 400 (full-frame) - 1
    GOLDEN_TUNA_DY = 32                          # relativer Abstand (frame-unabh.)
    GOLDEN_TUNA_Y = {1: 269 - GOLDEN_TUNA_DY,   # 237 (Feld 1, oben:  Freilassen)
                     2: 269,                    # 269 (Feld 2, mitte: Aufschneiden)
                     3: 269 + GOLDEN_TUNA_DY}   # 301 (Feld 3, unten: Koeder)

    # Nach dem Options-Klick antwortet der SERVER mit einem Bestaetigungs-
    # Dialog mit EINEM OK-Knopf (z.B. die Freilassen-Bonus-Meldung). Der
    # Dialog steht NICHT an fester Position (Hoehe haengt vom Text ab, Lage
    # variiert: OK-Mitte (403,250) vs. (403,202) auf den Live-Referenzen) --
    # geklickt wird darum der per Template-SUCHE gefundene Knopf
    # (fishing_detect.golden_confirm_find), keine Konstante.

    # Wie lange nach dem Options-Klick auf das Bestaetigungs-Fenster gewartet
    # wird (Sekunden). Das Fenster kommt erst mit der SERVER-Antwort -- der
    # alte Sofort-Klick 0.1s nach dem Options-Klick feuerte praktisch immer,
    # BEVOR es existierte (-> Dialog blieb offen, Bot haengte). Jetzt klickt
    # der Loop OK erst, wenn detect_golden_confirm den Dialog WIRKLICH sieht
    # (Template der Knopf-Leiste), innerhalb dieses Zeitfensters.
    GOLDEN_CONFIRM_WAIT_S = 10.0

    # set position of the fish windows
    # this value can be diferent by the sizes of the game window

    FISH_WINDOW_SIZE = (280, 226)
    FISH_WINDOW_POSITION = (95, 80)

    wincap = None

    # Load the needle image

    # WICHTIG: resource_path() -- in der gepackten EXE liegen die Bilder im
    # PyInstaller-Bundle (sys._MEIPASS), NICHT im Arbeitsverzeichnis. Ein nackter
    # Pfad 'images/..' laedt dort None -> matchTemplate erkennt NIE etwas (das
    # Minispiel wird nie gespielt). Mit resource_path laden die Vorlagen auch aus
    # der EXE -- wie es das Puzzle (fish_jigsaw_chest) schon richtig macht.
    needle_img = cv.imread(resource_path('images/fiss.jpg'), cv.IMREAD_UNCHANGED)
    needle_img_clock = cv.imread(resource_path('images/clock.jpg'), cv.IMREAD_UNCHANGED)

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

    # Anti-Erkennungs-Jitter: RELATIVE (multiplikative) Streuung der drei Zyklus-
    # Wartezeiten (Koeder/Auswurf/Minigame-Delay). Bricht die maschinen-praezise
    # Periodizitaet (jeder Zyklus exakt gleich getaktet = der eigentliche Bot-
    # Fingerabdruck laut Recherche), OHNE den Bot zu drosseln: zentriert auf 1.0
    # -> im Schnitt keine Aenderung der eingestellten Zeit; relativ -> skaliert
    # mit ihr (0.1s -> +-0.015s, 2.0s -> +-0.3s). Das Minigame-Klicken bleibt
    # UNBERUEHRT (seine "danebens" entstehen schon natuerlich aus der Tracking-
    # Latenz). ``_TIMING_JITTER = 0`` schaltet es exakt ab (byte-stabil fuer Tests).
    _TIMING_JITTER = 0.15                 # +-15% (<= die vom User gesetzte 20%-Grenze)
    _jitter_rolled_for = None
    _action_deadline_val = 0.0

    def _roll_deadline(self, base):
        """Gejitterte Wartezeit fuer den AKTUELLEN State -- EINMAL pro State-
        Eintritt gewuerfelt (nicht jeden Frame neu, sonst flackert die Schwelle).
        ``base`` = die eingestellte Zeit; Rueckgabe = ``base * uniform(1-j, 1+j)``.
        ``_TIMING_JITTER == 0`` -> exakt ``base`` (deterministisch)."""
        if self._jitter_rolled_for != self.state:
            self._jitter_rolled_for = self.state
            j = self._TIMING_JITTER
            factor = random.uniform(1.0 - j, 1.0 + j) if j else 1.0
            self._action_deadline_val = float(base) * factor
        return self._action_deadline_val

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

    # Deadline (time()), bis zu der nach einem Golden-Tuna-Options-Klick auf
    # den Bestaetigungs-Dialog gewartet wird. 0.0 = nichts scharf.
    _golden_confirm_until = 0.0

    # Angel-Whitelist (opt-in). Default AUS -> angelt ALLES -> byte-stabil.
    #   * whitelist_enabled: nur True schaltet die Pruefung scharf.
    #   * whitelist_states: {DE-Name: KEEP|REMOVE|CAMPFIRE} aus der Inventar-
    #     Verwaltung (vom RunLoop injiziert). Fehlt ein Name -> gilt als KEEP.
    # Bei einem Biss wird NUR der kleine Chat-Streifen via fishing_chat.read_hook
    # gelesen; ist der Fang als REMOVE markiert (oder eine Niete), wird das
    # Minispiel SOFORT abgebrochen + neu ausgeworfen. UNGEWOLLT/unsicher ->
    # weiterangeln (nie versehentlich einen gewollten Fisch abbrechen).
    whitelist_enabled = False
    whitelist_states = None

    # Zuletzt fuer die Whitelist gelesener Biss -- verhindert mehrfaches
    # Auswerten/Loggen desselben Bisses pro Wurf (Reset bei jedem neuen Auswerfen).
    _whitelist_decided = False
    # Letzte geloggte Chat-Erkennung (kind, name, conf) -- Dedup fuers Diagnose-Log.
    _whitelist_last_sig = None

    # Koeder-Nachlegen (opt-in). Default AUS -> der Bot prueft den Koeder-Slot
    # NIE -> byte-stabil. Erkennt der Bot den Koeder-Quickslot (= der bait_key-
    # Slot) leer, legt er EINEN Koeder aus dem Inventar nach; ist keiner mehr da,
    # stoppt er. Die Live-Infrastruktur (Inventar-DB + Kalibrierung) injiziert der
    # RunLoop separat auf die Instanz (analog whitelist_states):
    #   * bait_refill_db:    inventory.itemdb.ItemDB (None -> Engine baut/nutzt
    #     den Bundle-Default selbst defensiv);
    #   * bait_refill_calib: Kalibrierungs-Dict (None -> DEFAULT_CALIBRATION);
    #   * inventory_hotkey:  Spiel-Taste, die das Inventar oeffnet (Default 'i').
    # Der optionale on_bait_empty-Hook (vom RunLoop gesetzt) zeigt ein Popup
    # "Koeder leer", wenn gestoppt wird -- entkoppelt (None -> nur Log).
    bait_refill_enabled = False
    bait_refill_db = None
    bait_refill_calib = None
    inventory_hotkey = 'i'
    on_bait_empty = None
    # Drossel: nicht jeden Frame pruefen -- nur, wenn seit der letzten Pruefung
    # mind. _BAIT_REFILL_INTERVAL s vergangen sind (und ohnehin nur kurz vorm
    # Baiten in State 0). 0.0 = "noch nie geprueft" -> erste Pruefung sofort.
    _last_bait_check = 0.0
    _BAIT_REFILL_INTERVAL = 5.0

    # Globales Stop-Signal (vom RunLoop injiziert). Default = NIE-gesetztes
    # NULL_SIGNAL -> die Refill-Naps blockieren wie bisher, ein Stop bricht sie
    # nie ab (byte-stabil). Mit echtem Signal pollt jede Refill-Nap es und bricht
    # bei F6 in <1 Slice ab.
    stop_signal = _stopsig.NULL_SIGNAL
    # GEBUNDENE Obergrenze fuer EINEN Refill-Versuch (Inventar oeffnen + bis zu 4
    # Seiten scannen + draggen). Auch ohne Stop endet die Op spaetestens hier mit
    # klarem Log -> nie ein stiller Haenger. Grosszuegig (4 Seiten + Drag dauern
    # real ~2-3 s); 20 s ist eine reine Sicherheits-Decke.
    _BAIT_REFILL_BUDGET = 20.0

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
        # Whitelist pro Runde frisch auswerten (der naechste Auswurf bringt einen
        # neuen Biss).
        self._whitelist_decided = False

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

    # -- Angel-Whitelist ---------------------------------------------------

    def _whitelist_active(self):
        """True nur, wenn die Whitelist scharf ist UND die Bausteine importiert
        werden konnten. Wirft nie."""
        return bool(self.whitelist_enabled) and _fc is not None and _wl is not None

    def _read_hook(self, screenshot):
        """Liest NUR den kleinen Chat-Streifen (schnell) -> HookResult oder None.
        Defensiv: jeder Fehler -> None (Whitelist greift dann nicht)."""
        try:
            return _fc.read_hook(screenshot)
        except Exception:
            return None

    def _abort_minigame(self):
        """Bricht den aktuellen Angel-Versuch SOFORT ab und startet den Zyklus neu.

        KEIN Klick mehr (die alte FISH_WINDOW_CLOSE-Koordinate war eine falsche
        Altlast, ~55px neben dem Minispielfenster). Stattdessen: ESC druecken
        (raeumt ein evtl. offenes Minispiel weg), dann -- falls Mount aktiv -- die
        Mount-Cancel-Sequenz (auf-/absteigen, setzt den Figuren-Zustand sauber
        zurueck), und auf State 0 stellen, sodass der naechste Tick Koeder setzt +
        neu auswirft. Gibt den genutzten Weg fuers Logging zurueck. Wirft nie."""
        how = 'esc'
        try:
            _input.key('esc')                 # keyDown+keyUp atomar (ein Lease)
        except Exception:
            # Geht ESC nicht, reicht der State-Reset unten -> naechster Zyklus
            # wirft ohnehin neu aus.
            how = 'recast_only'
        # Falls Mount aktiviert: wie nach einem Fang auf-/absteigen -> sauberer
        # Neustart (Pferd -> Koeder -> Auswerfen).
        if self.mount_enabled:
            try:
                self._do_mount_cancel(mount.mount_cancel_steps(self.mount_key))
            except Exception:
                pass
        # Sofort von vorne, OHNE Vorlauf: auf State 0 + den Timer so vordatieren,
        # dass der naechste Tick INSTANT neu koedert (kein bait_time-Warten). Bait
        # -> Cast -> Minispiel laufen dann mit den eingestellten (schnellen) Zeiten.
        self.state = 0
        self.timer_action = time() - max(
            self.bait_time, self.throw_time, self.game_time) - 1.0
        self._on_cycle_end()
        return how

    def _apply_whitelist(self, screenshot):
        """Wertet beim Biss den Chat-Streifen aus und bricht ab, falls der Fang
        unerwuenscht (REMOVE) oder eine Niete ist. Gibt True zurueck, wenn das
        Minispiel abgebrochen wurde (Aufrufer soll diese Runde nicht weiterspielen).

        Streng defensiv: ohne aktive Whitelist / bei jedem Fehler -> False.
        UNGEWOLLT/unsicher -> NIE abbrechen.
        """
        if not self._whitelist_active() or self._whitelist_decided:
            return False
        try:
            result = self._read_hook(screenshot)
            if result is None:
                return False

            kind = getattr(result, 'kind', _fc.NONE)
            # DIAGNOSE (temporaer): jede NEUE Chat-Erkennung loggen -> zeigt im
            # Live-Test, ob read_hook den Chat-Streifen ueberhaupt trifft
            # (Region/OCR korrekt). Dedup ueber die Signatur, kein Spam.
            sig = (kind, str(getattr(result, 'name', '')),
                   bool(getattr(result, 'confident', False)))
            if sig != self._whitelist_last_sig:
                self._whitelist_last_sig = sig
                _flog(self.state, 'WL-DBG kind=%s name=%r conf=%s'
                      % (kind, sig[1], sig[2]))
            if kind == _fc.NONE:
                # Noch nichts Sicheres am Haken -> naechsten Frame abwarten.
                return False

            decision = _wl.decide(result, states=self.whitelist_states,
                                  enabled=True)
            self._whitelist_decided = True

            if decision == _wl.ABORT:
                how = self._abort_minigame()
                name = str(getattr(result, 'name', '?'))
                if kind == _fc.NIETE:
                    _flog(0, t('fishing.whitelist_abort_niete', how=how))
                else:
                    _flog(0, t('fishing.whitelist_abort', name=name, how=how))
                return True

            # Gewollt -> nur bei sicherem Namen einmal vermerken (UNKNOWN still).
            if getattr(result, 'confident', False):
                _flog(3, t('fishing.whitelist_keep',
                           name=str(getattr(result, 'name', '?'))))
            return False
        except Exception:
            return False

    # -- Koeder-Nachlegen --------------------------------------------------

    def _bait_refill_active(self):
        """True nur, wenn das Nachlegen scharf ist UND die Engine importiert
        werden konnte UND ein Fenster-Capture existiert. Wirft nie."""
        return (bool(self.bait_refill_enabled) and _refill is not None
                and self.wincap is not None)

    def _bait_slot(self):
        """Quick-slot (1..8) des Koeders aus ``bait_key`` oder ``None``.

        Der Koeder liegt laut Spec in einem Quickslot; ``bait_key`` ist die Taste,
        die ihn wirft -- also genau der zu pruefende Slot. Eine Taste, die kein
        Quickslot ist (sollte die Validierung verhindern), liefert ``None`` ->
        kein Nachlegen. Wirft nie."""
        try:
            return _refill.quickslot_index(self.bait_key)
        except Exception:
            return None

    def _refill_sleep(self, seconds):
        """Interruptible Nap fuers Nachlegen: schlaeft ``seconds`` ueber das
        Stop-Signal (``StopSignal.wait``) und kehrt SOFORT zurueck, sobald ein
        Stop ansteht. Gibt ``False`` zurueck, wenn ein Stop die Nap abgeschnitten
        hat (Aufrufer bricht ab). Faellt ohne Signal auf ``time.sleep`` zurueck.
        Wirft nie."""
        sig = getattr(self, 'stop_signal', None)
        if sig is not None:
            try:
                return sig.wait(seconds)
            except Exception:
                pass
        try:
            sleep(seconds)
        except Exception:
            pass
        return True

    def _refill_should_stop(self):
        """Predicate fuer die Refill-Engine: True, sobald ein Stop ansteht
        (Stop-Signal gesetzt ODER botting bereits geraeumt). Wirft nie."""
        try:
            sig = getattr(self, 'stop_signal', None)
            if sig is not None and sig.stopped:
                return True
            return not self.botting
        except Exception:
            return False

    def _maybe_refill_bait(self, screenshot):
        """Gedrosselt: ist der Koeder-Quickslot leer, EINEN Koeder nachlegen.

        Streng defensiv + opt-in (Default AUS -> sofort raus -> byte-stabil).
        Prueft hoechstens alle ``_BAIT_REFILL_INTERVAL`` s (Aufruf nur kurz vorm
        Baiten in State 0) auf dem ohnehin geholten ``screenshot`` -- kein Extra-
        Capture, keine Last. Das Inventar muss beim Angeln OFFEN sein (kein
        I-Druck -- das Inventar wird nicht geoeffnet/geschlossen). Bei leerem Slot:
          * aus dem offenen Inventar ``refill.refill_from_inventory`` einen Koeder
            in den Quickslot ziehen;
          * Ergebnis ``'dragged'`` -> Log "nachgelegt";
          * ``'empty'`` (kein Koeder mehr im Inventar) -> Bot stoppen
            (``botting=False``) + klares Log und optionalen Popup-Hook
            (``on_bait_empty``);
          * ``'error'`` -> Log + diesmal ohne Nachlegen weiter (kein Stop).
        Wirft nie -- ein Vision-/Input-Fehler darf den Angel-Loop nie kippen.
        """
        if not self._bait_refill_active():
            return
        now = time()
        too_soon = (self._last_bait_check > 0
                    and now - self._last_bait_check < self._BAIT_REFILL_INTERVAL)
        if too_soon:
            return
        self._last_bait_check = now
        try:
            slot = self._bait_slot()
            if slot is None:
                return
            if not _refill.quickslot_is_empty(screenshot, slot):
                return   # Koeder noch da -> nichts tun (haeufigster Fall)

            _flog(self.state, t('fishing.bait_refill_empty_slot'))
            ox = int(getattr(self.wincap, 'offset_x', 0) or 0)
            oy = int(getattr(self.wincap, 'offset_y', 0) or 0)
            target = _refill.quickslot_screen(slot, ox, oy)
            calib = self.bait_refill_calib or _refill.DEFAULT_CALIBRATION

            # GEBUNDENE Obergrenze + interruptible: die schwere Op (Inventar
            # oeffnen + Seiten scannen + draggen) bekommt ein hartes Zeitbudget
            # UND bricht bei F6/Stop sofort ab. Klare Start-/Ende-Zeile -> der Bot
            # haengt nie stumm. ``should_stop`` faengt den Stop auch zwischen den
            # Engine-Schritten (Page-Switch/Drag) ab.
            deadline = _stopsig.Deadline(
                self._BAIT_REFILL_BUDGET, signal=getattr(self, 'stop_signal', None))
            _flog(self.state, t('fishing.bait_refill_started'),
                  budget=int(self._BAIT_REFILL_BUDGET))

            # Das Inventar ist beim Angeln IMMER offen -> KEIN I-Druck (kein
            # Oeffnen/Schliessen), direkt aus dem offenen Inventar nachlegen.
            result = _refill.refill_from_inventory(
                _refill.BAIT_NAMES, target, inp=(_refill_backend or pydirectinput),
                wincap=self.wincap, db=self.bait_refill_db, calib=calib,
                sleep=self._refill_sleep, should_stop=self._refill_should_stop)

            if result == 'dragged':
                _flog(self.state, t('fishing.bait_refill_done'),
                      secs='{:.1f}'.format(deadline.elapsed()))
            elif result == 'empty':
                _flog(self.state, t('fishing.bait_refill_none_left'))
                self.botting = False
                self._notify_bait_empty()
            elif result == 'stopped':
                # Per F6/Stop abgebrochen -- still (der Lauf endet ohnehin); nur
                # eine knappe Diagnose-Zeile, damit der Abbruch nachvollziehbar ist.
                _flog(self.state, t('fishing.bait_refill_stopped'))
            else:   # 'error' -> diesmal ohne Nachlegen weiter (kein Stop)
                _flog(self.state, t('fishing.bait_refill_failed'))

            # Sicherheits-Decke: hat die Op das harte Budget gerissen (z. B. ein
            # nie endender Drag), KLAR melden statt stumm weiterzulaufen.
            if deadline.expired() and result not in ('stopped',):
                _flog(self.state, t('fishing.bait_refill_timeout'),
                      budget=int(self._BAIT_REFILL_BUDGET))
        except Exception:
            # Niemals den Angel-Loop kippen.
            pass

    def _notify_bait_empty(self):
        """Ruft den optionalen Popup-Hook (vom RunLoop gesetzt) genau dann, wenn
        wegen leeren Koeders gestoppt wird. None -> nur Log (Entkopplung). Wirft
        nie."""
        callback = self.on_bait_empty
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
                    _input.key(value)         # keyDown+keyUp atomar (ein Lease)
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

        # Angel-Whitelist defensiv lesen (Default AUS -> byte-stabil). Der
        # konkrete Fisch-Zustands-Dict (whitelist_states) wird separat vom
        # RunLoop auf die Instanz injiziert (wie bait_key/cast_key); ein
        # fehlender Schluessel laesst die Whitelist einfach aus.
        self.whitelist_enabled = bool(values.get('-WHITELIST-',
                                                  self.whitelist_enabled))
        self._whitelist_decided = False

        # Koeder-Nachlegen defensiv aus den frozen keys lesen (Default AUS ->
        # byte-stabil). Die konkrete Live-Infrastruktur (bait_refill_db/_calib,
        # inventory_hotkey, on_bait_empty) injiziert der RunLoop separat auf die
        # Instanz -- ein fehlender Schluessel laesst das Nachlegen einfach aus.
        self.bait_refill_enabled = bool(values.get('-BAITREFILL-',
                                                    self.bait_refill_enabled))
        # Drossel pro Lauf zuruecksetzen -> direkt beim ersten Baiten geprueft.
        self._last_bait_check = 0.0

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

        # Tasten (Koeder/Auswerfen) brauchen eine echte Haltezeit, sonst sieht
        # DirectInput sie nie. Ein vorheriger Inventar-Scan kann PAUSE auf 0,05
        # gesenkt haben (ok fuer Maus, zu kurz fuer die Tastatur) -> hier den
        # bewaehrten 0,1-Wert (= v1.1.0-Default) fuer den ganzen Angel-Lauf erzwingen.
        _input.set_pause(0.1)

        mouse_x = int(self.FISH_WINDOW_POSITION[0] + self.wincap.offset_x + 200)
        mouse_y = int(self.FISH_WINDOW_POSITION[1] + self.wincap.offset_y + 200)

        _input.click(mouse_x, mouse_y, button='right')

    def runHack(self):
        screenshot = self.wincap.get_screenshot()

        # Einmal schneiden: roher Crop (fuer detect_end) + HSV-gefilterter Crop.
        x0 = self.FISH_WINDOW_POSITION[0]
        y0 = self.FISH_WINDOW_POSITION[1]
        x1 = x0 + self.FISH_WINDOW_SIZE[0]
        y1 = y0 + self.FISH_WINDOW_SIZE[1]
        detect_end_img = screenshot[y0:y1, x0:x1]
        crop_img = self.hsv_filter.apply_hsv_filter(detect_end_img)

        cv.putText(crop_img, 'FPS: ' + str(1/(time() - self.loop_time))[:2],
                (10, 200), cv.FONT_HERSHEY_SIMPLEX,  0.5, (0, 255, 0), 2)
        cv.putText(crop_img, 'State: ' + str(self.state) + ' ' + str(time() - self.timer_action)[:5],
                (10, 160), cv.FONT_HERSHEY_SIMPLEX,  0.5, (0, 255, 0), 2)
        self.loop_time = time()

        # ANGEL-WHITELIST -- ENTKOPPELT vom Minispiel: ab dem Auswerfen wird JEDEN
        # Frame der kleine Chat-Streifen ausgewertet. Wiederverwendung des oben
        # ohnehin geholten ``screenshot`` (KEIN Extra-Capture) + winzige OCR auf
        # ~290x17px -> guenstig, also volle Loop-Frequenz statt Throttle = maximaler
        # Speed ohne Delay. So wird "am Haken"/Niete erkannt, SOBALD es im Chat
        # steht (oft vor dem Minispiel), und unerwuenscht sofort abgebrochen ->
        # diese Runde hier beenden. Erst ab State 2 (nach dem Auswurf); _apply_
        # whitelist prueft "aktiv" + "schon entschieden" selbst (aus = byte-stabil).
        if self.state >= 2 and self._apply_whitelist(screenshot):
            return crop_img

        daily = self.detect_daily_reward(screenshot)

        if daily:
            field = self.golden_tuna_action
            ox, oy = self.wincap.offset_x, self.wincap.offset_y
            mouse_x = int(ox + self.GOLDEN_TUNA_X)
            mouse_y = int(oy + self.GOLDEN_TUNA_Y[field])
            _input.click(mouse_x, mouse_y)
            # Bestaetigungs-Fenster SCHARF schalten statt blind zu klicken: es
            # kommt erst mit der Server-Antwort (der alte Sofort-Klick feuerte
            # vorher ins Leere -> Dialog blieb offen). Solange das Options-
            # Fenster noch steht, verlaengert sich das Zeitfenster pro Frame.
            self._golden_confirm_until = time() + self.GOLDEN_CONFIRM_WAIT_S
            if time() - getattr(self, '_last_daily_log', 0) > 3:
                self._last_daily_log = time()
                _flog(self.state, t('fishing.golden_tuna_clicked'),
                      field=field, x=mouse_x, y=mouse_y)
        elif time() < getattr(self, '_golden_confirm_until', 0.0):
            # Optionen geklickt, Fenster zu -> auf den Bestaetigungs-Dialog
            # warten und OK erst klicken, wenn er WIRKLICH im Frame steht.
            # Geklickt wird die GEFUNDENE Knopf-Mitte (der Dialog wandert je
            # nach Textlaenge/Position). Retry-sicher: steht er im naechsten
            # Frame noch, wird erneut geklickt; danach laeuft das Fenster ab.
            found, _score, point = self.detect_golden_confirm(screenshot)
            if found and point is not None:
                ox, oy = self.wincap.offset_x, self.wincap.offset_y
                ok_x = int(ox + point[0])
                ok_y = int(oy + point[1])
                _input.click(ok_x, ok_y)
                if time() - getattr(self, '_last_confirm_log', 0) > 3:
                    self._last_confirm_log = time()
                    _flog(self.state, t('fishing.golden_tuna_confirmed',
                                        x=ok_x, y=ok_y))

        # Verify total time

        if self.end_time_enable and time() - self.initial_time > self.end_time:
            _flog(self.state, t('fishing.stop_time_limit'),
                  minutes=self.end_time // 60)
            self.botting = False

        # State to click put the bait in the rod

        if self.state == 0:

            # KOEDER-NACHLEGEN (opt-in, Default AUS -> no-op): vor dem Baiten den
            # Koeder-Quickslot pruefen und ggf. EINEN Koeder aus dem Inventar
            # nachlegen (gedrosselt; reuse des ohnehin geholten screenshot). Ist
            # kein Koeder mehr da, stoppt _maybe_refill_bait den Bot selbst.
            self._maybe_refill_bait(screenshot)

            if time() - self.timer_action > self._roll_deadline(self.bait_time):
                _input.key(self.bait_key)     # keyDown+keyUp atomar (ein Lease)
                self.state = 1
                self.timer_action = time()
                # Neuer Wurf -> Whitelist darf diesen Fang frisch bewerten.
                self._whitelist_decided = False
                self._whitelist_last_sig = None
                _flog(1, t('fishing.bait_set'))

        # State to throw the bait

        if self.state == 1:
            if time() - self.timer_action > self._roll_deadline(self.throw_time):
                _input.key(self.cast_key)     # keyDown+keyUp atomar (ein Lease)
                self.state = 2
                self.timer_action = time()
                _flog(2, t('fishing.cast_out'))

        # Delay to start the clicks

        if self.state == 2:
            if time() - self.timer_action > self._roll_deadline(self.game_time):
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

            # (Whitelist-Auswertung laeuft jetzt ENTKOPPELT am Anfang von runHack,
            # jeden Frame ab State 2 -- nicht mehr hier ans Minispiel gekoppelt.)

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

                    _input.click(mouse_x, mouse_y)
                    _flog(3, t('fishing.fish_clicked'), x=mouse_x, y=mouse_y)

        return crop_img
