"""Lauf-Verdrahtung (Tick-Schleife + Counter/Stats/Events) als RunLoop-Klasse.

Abgespaltene Wiring-Schicht des Einstiegspunkts :mod:`hack`. Buendelt die
gesamte Integrations-Logik -- Start/Stop des gewaehlten Modus, den Bot-Tick via
``after()``, die Laufzeit-/Fang-/Puzzle-Zaehler, die Fish-Event-Warnung und die
Board-Offset-/Override-Injektion -- in einer Instanz, die ueber ``app`` +
``app.controller`` arbeitet.

Bewusst eine 1:1-Strukturumstellung: der frueher in ``hack.py`` modul-globale
Lauf-Zustand (``_stop_deadline``, ``_stats_save_job`` ...) ist hier INSTANZ-
Zustand; jede Methode entspricht byte-genau der frueheren modul-globalen
Funktion. ``hack.py`` bleibt der duenne Bootstrap (Logging/Config/Stats laden,
App bauen, ``RunLoop`` verdrahten, Mainloop). Kein Verhalten, keine Reihenfolge,
keine Kadenz aendert sich.

Verdrahtung (siehe :meth:`RunLoop.wire`):
  * ``app._stats_save_hook`` -> :meth:`flush_stats_on_exit`
  * ``fishbot.on_catch``     -> :meth:`on_catch`
  * ``controller.on_start``  -> :meth:`on_start`
  * ``controller.on_stop``   -> :meth:`on_stop`
  * erster ``app.after(tick_ms, tick)`` startet die Schleife.
"""

import time
from datetime import datetime

from debuglog import log
from i18n import t
from interface import config as cfgmod
import detection
import event_window
import stats as statsmod
import stop_signal


# Tick-Kadenz: 10 ms. Reicht voellig (runHack blockiert ohnehin waehrend einer
# Aktion); ein 1-ms-after-Loop kann sich bei interaktivem Fenster-Resize mit den
# CTk-Redraws verzahnen -> 10 ms ist deutlich robuster und genauso fluessig.
TICK_MS = 10

# Bot-Stop-Hotkey: global via GetAsyncKeyState gepollt (wirkt auch, wenn das
# Spiel den Fokus hat). win32 SOFT importiert -- fehlt es, ist der Hotkey aus.
try:  # pragma: no cover - pywin32 in Produktion vorhanden
    import win32api as _win32api
    import win32con as _win32con
except Exception:  # pragma: no cover
    _win32api = None
    _win32con = None


def _key_to_vk(key):
    """Virtual-Key-Code einer Hotkey-Taste (F1-F12 / Buchstabe / Ziffer) oder
    ``None``. Reine Funktion, headless testbar (VK-Konstanten gespiegelt, falls
    win32con fehlt)."""
    vk_f1 = getattr(_win32con, 'VK_F1', 112)
    k = str(key or '').strip().lower()
    if not k:
        return None
    if k[0] == 'f' and k[1:].isdigit():
        n = int(k[1:])
        if 1 <= n <= 12:
            return vk_f1 + (n - 1)
    if len(k) == 1 and (k.isalpha() or k.isdigit()):
        return ord(k.upper())
    return None


class RunLoop:
    """Haelt App/Controller/Bots + den Lauf-Zustand und treibt die Tick-Schleife.

    Eine Instanz pro Prozess. ``app`` ist die :class:`interface.app.App`;
    ``app.controller`` der BotController mit ``fishbot``/``puzzlebot``. Nach
    :meth:`wire` laufen Start/Stop ueber die Controller-Callbacks und der erste
    Tick ist eingereiht.
    """

    def __init__(self, app, tick_ms=TICK_MS):
        self.app = app
        self.controller = app.controller
        self.fishbot = self.controller.fishbot
        self.puzzlebot = self.controller.puzzlebot
        # Energiesplitter-Bot (EINE Klasse, Modus-Schalter hammer/dagger), wie
        # fishbot/puzzlebot ueber DIESEN Tick getrieben (kein Worker-Thread).
        # Soft: fehlt das Paket (Phase-0 nicht geliefert), bleibt esbot None ->
        # der Tick/on_start ueberspringt ihn (byte-stabil fuer alle Altpfade).
        self.esbot = getattr(self.controller, 'esbot', None)
        self.tick_ms = tick_ms

        # Globales Zeitlimit ("Stop after X minutes"): bei START gesetzt, im Tick
        # geprueft -- gilt fuer BEIDE Modi. None = kein Limit; nur positive Minuten.
        self._stop_deadline = None

        # -- Responsiveness: globaler Stop-Signal + Hotkey-Daemon -------------
        # EIN gemeinsames, flag-basiertes Stop-Signal fuer die ganze App. Der
        # Hotkey-Daemon (eigener High-Frequency-Thread) setzt es bei F6 SOFORT --
        # unabhaengig vom Hauptloop und von jeder schweren Op -- und ein Callback
        # raeumt dabei ``botting`` beider Bots. Schwere Ops (Refill/Inventar-Scan)
        # bekommen dieses Signal injiziert und brechen ueber seine
        # interruptible-sleeps in <1 Slice ab. Default-Signal ist NIE gesetzt ->
        # ohne laufenden Bot aendert sich nichts (byte-stabil).
        self.stop_signal = stop_signal.StopSignal()
        self._stop_watcher = None
        # Vom Daemon-Callback gesetzt, wenn die Stop-TASTE (F6) den Stop ausloeste
        # -- so kann der Tick den Hotkey-Stop (mit Grund/Log) vom stillen
        # Button-Stop unterscheiden, obwohl BEIDE das Stop-Signal setzen.
        self._hotkey_fired = False

        # -- Counter-/Stats-Zustand (single-threaded, im Tick gepflegt) -------
        # Per-Tick-Wanduhr fuer Laufzeit-Akkumulation (Delta zwischen zwei Ticks).
        self._last_tick_clock = None
        # Edge-Latch: war der PuzzleBot im letzten Tick im Loese-Zustand (state 9)?
        # So zaehlt EIN geloestes Puzzle genau einmal (state 9 haelt mehrere Ticks).
        self._puzzle_was_solving = False
        # Edge-Latch fuer die Event-Warnung: war zuletzt ein Event aktiv / eine
        # Warnung faellig? -> Warnung/Started-Log genau einmal pro Fensterwechsel.
        self._event_was_active = False
        self._event_warned = False
        # tz-unavailable nur EINMAL pro Sitzung melden (sonst Log-Spam).
        self._event_tz_warned = False
        # Entprelltes Stats-Speichern (atomar): job-Handle + letzter Speicherzeit.
        self._stats_save_job = None
        self._stats_last_save = 0.0
        # Event-Status nur ~1x/Sekunde pruefen (guenstig halten).
        self._last_event_check = 0.0

    # -- Verdrahtung -------------------------------------------------------

    def wire(self):
        """Registriert die Callbacks an App/Controller/FishingBot und startet.

        Setzt ``app._stats_save_hook`` (finaler Flush auf JEDEM Exit-Pfad),
        ``fishbot.on_catch`` (entkoppelter Counter-Hook), die Controller-
        Callbacks ``on_start``/``on_stop`` und reiht den ersten Tick ein.
        """
        # Finalen Flush an der App registrieren: App._on_close /
        # _hard_exit_for_update rufen app._flush_stats() -> diesen Callback. So
        # geht Laufzeit auf KEINEM Exit-Pfad verloren (auch nicht bei os._exit
        # fuers Update).
        self.app._stats_save_hook = self.flush_stats_on_exit
        # Counter-Hook am FishingBot registrieren (entkoppelt: der Bot kennt
        # stats.py nicht, er ruft nur diesen Callback).
        self.fishbot.on_catch = self.on_catch
        # Integrations-Callbacks am Controller registrieren. on_start_stop ruft je
        # nach Laufzustand on_start/on_stop und kuemmert sich um set_running +
        # UI-Sync.
        self.controller.on_start = self.on_start
        self.controller.on_stop = self.on_stop
        # Manage-Abbruch-Seam: das Stop-Signal (F6) setzt zusaetzlich die
        # Abbruch-Flagge der Inventar-Worker (Grillen/Wegwerfen stoppen nach
        # dem aktuellen Item). Direkt als Callback registriert, weil der Tick
        # das Signal sofort konsumiert -- ein Polling der Worker kaeme zu spaet.
        try:
            self.stop_signal.add_callback(self.app._request_manage_abort)
        except Exception:
            pass
        # Stop-Hotkey-Daemon starten: pollt F6 auf EIGENEM High-Frequency-Thread
        # und setzt bei Druck das Stop-Signal -> der ``_on_stop_signal``-Callback
        # raeumt SOFORT botting beider Bots, voellig unabhaengig davon, was der
        # Hauptloop oder eine schwere Op gerade tut. Strikt defensiv: ein Fehler
        # hier (kein win32, kein Thread) laesst den In-Tick-Fallback-Poll greifen.
        self.start_stop_watcher()
        # Ersten Tick einreihen (der Mainloop wird vom Bootstrap gestartet).
        self.app.after(self.tick_ms, self.tick)

    def start_stop_watcher(self):
        """Erzeugt + startet den Stop-Hotkey-Daemon-Thread (idempotent). Wirft nie.

        Der Daemon liest die Stop-Taste live aus der Config (``controls.stop_hotkey``,
        Default 'f6') und feuert bei der Press-Flanke das gemeinsame Stop-Signal.
        Registriert ausserdem den Botting-raeum-Callback am Signal. Ohne win32
        (headless) ist der Watcher ein No-op -> der In-Tick-Poll bleibt das Netz.
        """
        try:
            self.stop_signal.add_callback(self._on_stop_signal)
            self._stop_watcher = stop_signal.StopHotkeyWatcher(
                self.stop_signal, key_provider=self._current_stop_key)
            self._stop_watcher.start()
        except Exception:
            self._stop_watcher = None

    def _current_stop_key(self):
        """Liefert die aktuell konfigurierte Stop-Taste (Default 'f6'). Wirft nie."""
        try:
            return (self.controller.current_config()
                    .get('controls', {}).get('stop_hotkey', 'f6'))
        except Exception:
            return 'f6'

    def _on_stop_signal(self):
        """Callback des Stop-Signals (vom Daemon-Thread bei F6 gefeuert).

        Raeumt SOFORT ``botting`` beider Bots -- ein einfacher bool-Write, unter
        dem GIL atomar, also thread-sicher ohne Lock. Der Hauptloop spiegelt das
        beim naechsten Tick ins UI (notify_stop). Wirft nie -- darf den Daemon
        nie kippen.
        """
        try:
            self._hotkey_fired = True
            self.fishbot.botting = False
            self.puzzlebot.botting = False
            if self.esbot is not None:
                self.esbot.botting = False
        except Exception:
            pass

    # -- Counter / Stats ---------------------------------------------------

    def on_catch(self):
        """Counter-Hook: ein bestaetigter Fang -> fishing_catches += 1 (immutabel).

        Wird vom FishingBot (``fishbot.on_catch``) genau einmal pro Fang gerufen.
        Plant ein entprelltes atomares Speichern. Streng defensiv -- ein Fehler
        hier darf den Angel-Loop nie kippen.
        """
        try:
            self.app._stats = statsmod.increment_catch(self.app._stats)
            self.schedule_stats_save()
        except Exception:
            pass

    def schedule_stats_save(self):
        """Plant ein atomares stats.save in ~2s (entprellt, GUI-Thread via after).

        Mehrere schnelle Faenge/Solves verschieben das Speichern -- statt bei
        jedem Ereignis zu schreiben. Faellt auf Sofort-Speichern zurueck, wenn
        kein Scheduler verfuegbar ist. Wirft nie.
        """
        try:
            if self._stats_save_job is not None:
                self.app.after_cancel(self._stats_save_job)
            self._stats_save_job = self.app.after(2000, self.do_stats_save)
        except Exception:
            self.do_stats_save()

    def do_stats_save(self):
        """Schreibt die Statistik atomar auf die Platte. Wirft nie."""
        self._stats_save_job = None
        try:
            statsmod.save(self.app._stats)
            self._stats_last_save = time.time()
        except Exception:
            pass

    def flush_stats_on_exit(self):
        """Finaler Stats-Save fuer JEDEN Exit-Pfad (von App._flush_stats gerufen).

        Bricht ein evtl. anstehendes entprelltes Speichern ab und schreibt sofort
        atomar -- so erreicht die seit dem letzten Fang/Loesen akkumulierte
        Laufzeit die stats.json auch beim Fenster-Schliessen, Tray-Quit, Timer-
        Auto-Close und beim harten Update-Exit. Streng defensiv; wirft nie (darf
        den Exit nie blockieren)."""
        try:
            if self._stats_save_job is not None:
                try:
                    self.app.after_cancel(self._stats_save_job)
                except Exception:
                    pass
                self._stats_save_job = None
            statsmod.save(self.app._stats)
        except Exception:
            pass

    def accrue_runtime(self):
        """Akkumuliert Wand-Zeit auf den aktiven Modus (fishing/puzzler runtime).

        Single-threaded: misst das Delta seit dem letzten Tick und addiert es auf
        den laufenden Bot. Laeuft kein Bot, wird die Uhr nur fortgeschrieben (kein
        Delta angerechnet). Wirft nie.
        """
        now = time.time()
        if self._last_tick_clock is None:
            self._last_tick_clock = now
            return
        delta = now - self._last_tick_clock
        self._last_tick_clock = now
        # Unplausibles Delta (Schlaf/Standby/Sprung) verwerfen.
        if delta <= 0 or delta > 5:
            return
        try:
            if self.fishbot.botting:
                self.app._stats = statsmod.add_fishing_runtime(self.app._stats, delta)
            elif self.puzzlebot.botting:
                self.app._stats = statsmod.add_puzzler_runtime(self.app._stats, delta)
        except Exception:
            pass

    def detect_puzzle_solved(self):
        """Erkennt die Flanke 'Puzzle geloest' (PuzzleBot state == 9) und zaehlt
        sie genau einmal. state 9 haelt mehrere Ticks -> Edge-Latch verhindert
        Doppelzaehlung. Wirft nie.
        """
        try:
            solving = (bool(self.puzzlebot.botting)
                       and getattr(self.puzzlebot, 'state', 0) == 9)
            if solving and not self._puzzle_was_solving:
                self.app._stats = statsmod.increment_puzzle(self.app._stats)
                self.schedule_stats_save()
                # One-shot "rate on GitHub" prompt after the 10th solved puzzle
                # (the method gates on count + the persisted flag). Tk must be
                # touched on the GUI thread -> schedule via after.
                try:
                    self.app.after(0, self.app._maybe_show_rating_prompt)
                except Exception:
                    pass
            self._puzzle_was_solving = solving
        except Exception:
            pass

    # -- Events ------------------------------------------------------------

    def check_event_warning(self):
        """Loggt EINMAL pro Fensterwechsel, wenn ein Fish-Event startet bzw. die
        'N Minuten vor Ende'-Warnung faellig wird. ~1x/Sekunde gegated (guenstig).
        Streng defensiv; degradiert leise, wenn die Zeitzone fehlt. Wirft nie.
        """
        now = time.time()
        if now - self._last_event_check < 1.0:
            return
        self._last_event_check = now
        try:
            events = self.controller.current_config()['events']
            windows = events.get('windows') or ()
            warn_minutes = events.get('warn_minutes', 0)
            snap = event_window.status(datetime.now(), windows, warn_minutes)
            if not snap.get('tz_available', True):
                if not self._event_tz_warned:
                    self._event_tz_warned = True
                    log.event('-', t('events.tz_unavailable'))
                return
            active = snap.get('active', False)
            left = snap.get('minutes_left')
            # Start-Flanke: gerade aktiv geworden -> einmal melden.
            if active and not self._event_was_active:
                log.event('-', t('events.event_started',
                                 minutes=(left if left is not None else 0)))
            if not active:
                self._event_warned = False
            # Warn-Flanke: Warnung faellig + noch nicht gemeldet (pro Fenster).
            if snap.get('warn', False) and not self._event_warned:
                self._event_warned = True
                log.event('-', t('events.warning_before_end',
                                 minutes=(left if left is not None else 0)))
            self._event_was_active = active
        except Exception:
            pass

    # -- Start/Stop-Verdrahtung der Bots -----------------------------------

    def arm_stop_after(self):
        """Setzt/loescht das globale Zeitlimit anhand der aktuellen Einstellungen."""
        self._stop_deadline = None
        fishing = self.controller.current_config()['fishing']
        if fishing['stop_after_enabled'] and fishing['stop_after_minutes'] > 0:
            self._stop_deadline = time.time() + fishing['stop_after_minutes'] * 60

    def apply_puzzle_config(self):
        """Reicht die Puzzle-Optionen aus der Config an die PuzzleBot-Instanz.

        Color-/Solver-Mode werden auf das Instanz-Attribut gesetzt; der Board-
        Offset wird separat NACH set_to_begin aufgeloest und injiziert (siehe
        on_start). puzzle.py importiert detection NICHT -- der Offset kommt von
        hier (kein Importzyklus B<->C).
        """
        puzzle = self.controller.current_config()['puzzle']
        self.puzzlebot.color_mode = puzzle['color_mode']
        self.puzzlebot.color_patch = puzzle['color_patch']
        self.puzzlebot.solver_mode = puzzle['solver_mode']
        self.puzzlebot.step_delay = puzzle['step_delay']
        # Force Deluxe (V3-Reservat): nur wirksam bei solver_mode=='trained' +
        # vorhandener Deluxe-Box (der PuzzleBot prueft das selbst). Default aus.
        self.puzzlebot.force_deluxe = puzzle.get('force_deluxe', False)
        # Haertung (puzzle_safety): additiv mit .get-Defaults -> fehlende Keys in
        # bestehenden Configs aendern nichts. verify_placements/board_plausibility
        # sind reine Beobachtungs-/Absicherungs-Schichten (Default AN); color_stat
        # 'median' wirkt nur im 'multi'-Modus (Default 'mean' = byte-stabil).
        self.puzzlebot.verify_placements = puzzle.get('verify_placements', True)
        self.puzzlebot.board_plausibility = puzzle.get('board_plausibility', True)
        self.puzzlebot.color_stat = puzzle.get('color_stat', 'mean')

    def apply_energiesplitter_config(self, values, mode):
        """Legt die Energiesplitter-Optionen als ``-ES_*-``-Keys in ``values`` ab.

        Bruecke analog ``apply_puzzle_config``/``to_values``: liest die drei
        Sub-Dicts (hammer/dagger/shared) der validierten Config und schreibt die
        modus-passenden Werte unter den ``-ES_*-``-Schluesseln, die
        ``EnergiesplitterBot.set_to_begin(values)`` liest. ``mode`` ist
        ``'energiesplitter_hammer'`` oder ``'energiesplitter_dagger'`` -> der
        bot-interne Modus (``'hammer'``/``'dagger'``) wird daraus abgeleitet und
        als ``-ES_MODE-`` mitgegeben (set_to_begin liest den Modus von der
        Instanz; ``-ES_MODE-`` ist die redundante, robuste Quelle).

        MUTIERT ``values`` in-place (wie der fishing-Pfad ``-ENDTIMEP-`` setzt)
        und gibt es der Bequemlichkeit halber zurueck. Wirft nie -- ein Fehler
        hier faellt auf die Bot-Defaults zurueck (der Bot bleibt dank dry_run
        ohnehin sicher).
        """
        es = self.controller.current_config()['energiesplitter']
        is_dagger = (mode == 'energiesplitter_dagger')
        shared = es['shared']
        try:
            values['-ES_MODE-'] = 'dagger' if is_dagger else 'hammer'
            # hammer-spezifisch (im dagger-Modus dennoch gesetzt -> der Bot
            # ignoriert die unzutreffenden, friert aber konsistent ein).
            values['-ES_STACK_COUNT-'] = int(es['hammer']['stack_count'])
            values['-ES_FREISCHALTEN-'] = bool(
                es['hammer']['energie_freischalten'])
            # dagger-spezifisch.
            values['-ES_DAGGERS_PER_ROUND-'] = int(
                es['dagger']['daggers_per_round'])
            values['-ES_BUY_MODE-'] = str(es['dagger'].get('buy_mode', 'chat'))
            values['-ES_BUY_DELAY_S-'] = float(
                es['dagger'].get('buy_delay_s', 0.35))
            values['-ES_PROCESS_FIRST-'] = bool(
                es['dagger'].get('process_first', False))
            values['-ES_PROC_PICKUP_S-'] = float(
                es['dagger'].get('process_pickup_s', 0.15))
            values['-ES_PROC_CONFIRM_S-'] = float(
                es['dagger'].get('process_confirm_s', 0.4))
            # shared.
            values['-ES_SPEED-'] = str(shared['speed_profile'])
            values['-ES_MOUSE_PAUSE-'] = float(shared['mouse_pause'])
            values['-ES_KB_PAUSE-'] = float(shared['keyboard_pause'])
            values['-ES_MAX_ACTIONS-'] = int(shared['max_actions'])
            values['-ES_UNVERIF_STOP-'] = int(
                shared['consecutive_unverified_stop'])
            values['-ES_JITTER-'] = float(shared['jitter_pct'])
            values['-ES_DRY_RUN-'] = bool(shared['dry_run'])
        except Exception as exc:
            log.error(t('run.crash_in_runhack'), exc=exc)
        return values

    def inject_offset(self):
        """Loest den Board-Offset aus dem Detection-Modus auf und injiziert ihn.

        MUSS nach ``puzzlebot.set_to_begin`` laufen, weil set_to_begin den Offset
        auf den Klassen-Default zuruecksetzt. ``resolve_offset`` wirft nie und
        liefert nie None -- ein Fehler hier darf den Start nicht stoppen.

        Im ``mark``-Modus werden ausserdem die kalibrierte Board-Groesse
        (``mark_size``) und die Sonderpunkt-Overrides (``mark_keypoints``) auf
        ``puzzlebot.board_size`` / ``puzzlebot.key_points`` injiziert (siehe
        :meth:`inject_board_overrides`). Beides ist additiv/opt-in: ohne
        ``mark``-Modus bzw. ohne diese Felder bleiben die Klassen-Defaults
        ((260,170) / {}) -> byte-stabil.
        """
        puzzle = self.controller.current_config()['puzzle']
        saved = puzzle['mark_offset']
        saved_offset = tuple(saved) if saved else None
        try:
            # Screenshot fuer den auto-Modus; default/mark brauchen ihn nicht.
            screenshot = None
            if puzzle['detection_mode'] == 'auto':
                screenshot = self.puzzlebot.wincap.get_screenshot()
            self.puzzlebot.puzzle_offset = detection.resolve_offset(
                puzzle['detection_mode'], screenshot=screenshot,
                saved_offset=saved_offset)
            log.event(0, t('run.board_offset_resolved'),
                      mode=puzzle['detection_mode'],
                      offset=self.puzzlebot.puzzle_offset)
        except Exception as exc:
            # Kein Stop wegen Detection: auf den (von set_to_begin gesetzten)
            # Default-Offset zuruckfallen und weiterlaufen.
            log.error(t('run.offset_resolution_failed'), exc=exc)

        # Board-Groesse + Sonderpunkte separat (eigenes try): ein Fehler hier darf
        # weder den Start noch die bereits gesetzte Offset-Aufloesung kippen.
        self.inject_board_overrides(puzzle)

    def inject_board_overrides(self, puzzle):
        """Reicht ``mark_size``/``mark_keypoints`` an den PuzzleBot durch.

        Strikt additiv und opt-in: NUR im ``mark``-Modus und nur fuer truthy
        Werte werden ``board_size``/``key_points`` ueberschrieben. In allen
        anderen Faellen (default/auto, oder leere mark-Felder) bleiben die Klassen-
        Defaults stehen, die ``set_to_begin`` unmittelbar zuvor gesetzt hat
        ((260,170) / {}) -- explizit zurueckgesetzt, damit kein Wert eines
        frueheren mark-Laufs ueber einen Modus-Wechsel hinweg haengen bleibt.
        Default-Pfad bleibt byte-stabil.

        ``config.validate`` hat ``mark_size`` bereits als [w,h]-Int-Paar (oder
        None) und ``mark_keypoints`` als {name: [x,y]}-Int-Dict (oder {})
        normalisiert; hier nur die Form (Tuple) angleichen. Wirft nie -- ein
        Fehler faellt auf die Defaults zurueck und laesst den Lauf weiterlaufen.
        """
        try:
            is_mark = puzzle.get('detection_mode') == 'mark'
            size = puzzle.get('mark_size') if is_mark else None
            if size:
                self.puzzlebot.board_size = tuple(size)
            else:
                self.puzzlebot.board_size = self.puzzlebot.PUZZLE_WINDOW_SIZE

            keypoints = puzzle.get('mark_keypoints') if is_mark else None
            if keypoints:
                self.puzzlebot.key_points = {
                    name: tuple(point) for name, point in keypoints.items()}
            else:
                self.puzzlebot.key_points = {}

            if is_mark and (size or keypoints):
                log.event(0, t('run.board_overrides_injected'),
                          board_size=self.puzzlebot.board_size,
                          key_points=sorted(self.puzzlebot.key_points))
        except Exception as exc:
            # Auf Defaults zuruckfallen (byte-stabiler Pfad) und weiterlaufen.
            self.puzzlebot.board_size = self.puzzlebot.PUZZLE_WINDOW_SIZE
            self.puzzlebot.key_points = {}
            log.error(t('run.board_override_injection_failed'),
                      exc=exc)

    def _collect_whitelist_states(self):
        """Baut die Angel-Whitelist-Abbildung ``{DE-Name: KEEP|REMOVE|CAMPFIRE}``
        aus der Inventar-Verwaltung der App.

        Quelle ist das in der GUI gehaltene ``_inv_manage_states``
        ({Item-Schluessel -> Zustand}); jeder Schluessel wird ueber
        ``inventory_manage.ITEM_NAMES`` auf den offiziellen DE-Namen abgebildet
        (das, was ``fishing_chat.read_hook`` als Name liefert). Fehlt das Grid
        (Inventar-Tab nie geoeffnet) oder das interface-Paket, kommt ``{}`` zurueck
        -> die Whitelist behandelt dann jeden Fang als KEEP (es wird alles
        geangelt). Wirft NIE.
        """
        try:
            from interface import inventory_manage as im
        except Exception:
            return {}
        raw = getattr(self.app, '_inv_manage_states', None)
        if not raw:
            return {}
        out = {}
        for key, state in raw.items():
            try:
                _en, de = im.ITEM_NAMES.get(key, (None, None))
                if de:
                    out[de] = int(state)
            except Exception:
                continue
        return out

    def _bait_refill_db(self):
        """Liefert die gebuendelte Inventar-Item-DB fuers Koeder-Nachlegen (oder
        ``None``). Soft importiert -- fehlt das interface-Inventarpaket oder
        numpy/PIL, kommt ``None`` zurueck; die Refill-Engine baut/nutzt dann den
        Bundle-Default selbst (und meldet leise, falls auch das fehlschlaegt).
        Wirft NIE."""
        try:
            from interface.inventory_io import _get_db
            return _get_db()
        except Exception:
            return None

    def _on_bait_empty(self):
        """Popup-Hook fuers Koeder-Nachlegen: zeigt prominent in der Detection-
        Note, dass der Bot mangels Koeder gestoppt hat. Wird vom FishingBot genau
        dann gerufen, wenn kein Koeder mehr im Inventar ist. Tk nur auf dem GUI-
        Thread -> via ``after`` planen. Wirft NIE."""
        try:
            self.app.after(
                0, lambda: self.app.notify_stop(t('fishing.bait_refill_none_left')))
        except Exception:
            pass

    def on_start(self):
        """Startet den aktuell gewaehlten Modus (vom BotController-Button gerufen).

        Wirft hier nicht: der Controller umschliesst on_start mit eigenem
        try/except und setzt anschliessend den Laufzustand (set_running). Diese
        Methode verdrahtet NUR die Bots -- das Laufflag setzt der Controller.
        Exklusivitaet wird hart erzwungen (immer genau ein Bot botting=True).
        """
        values = self.controller.collect_values()
        self.arm_stop_after()
        # EINZIGE Timer-Autoritaet ist das RunLoop-Deadline (oben armiert): nur
        # dieser Pfad kennt die Zeitlimit-AKTION (Stoppen vs. Inventar-Cleanup).
        # Der historische bot-INTERNE Zeitlimit-Stop (fishingbot.runHack prueft
        # end_time selbst) wuerde Cleanup-blind stoppen, wenn er zuerst feuert
        # -> nach set_to_begin unten hart deaktivieren (set_to_begin liest
        # -ENDTIMEP- aus values und wuerde ihn sonst wieder scharf schalten).
        values['-ENDTIMEP-'] = False
        # Stop-Signal + Hotkey-Marke fuer den NEUEN Lauf frisch zuruecksetzen (ein
        # evtl. noch gesetztes Flag aus einem frueheren Stop darf den neuen Start
        # nicht sofort kippen). Danach erst botting=True setzen.
        self.stop_signal.clear()
        self._hotkey_fired = False
        mode = self.controller.mode
        if mode in ('energiesplitter_hammer', 'energiesplitter_dagger'):
            # Energiesplitter: derselbe Tick-getriebene Pfad wie fishing/puzzle.
            # Fehlt der Bot (Phase-0-Paket nicht geliefert), still NICHTS starten
            # -- der Tick laesst dann ohnehin keinen Bot laufen (Controller faellt
            # in Schritt 3 auf den Leerlauf zurueck).
            if self.esbot is None:
                self.fishbot.botting = False
                self.puzzlebot.botting = False
                return
            # bot-internen Modus VOR set_to_begin setzen (set_to_begin liest
            # self.mode), Stop-Signal injizieren (Quelle fuer abort_fn) und den
            # abort-Seam wie Manage v1.1.6 verdrahten (das Stop-Signal feuert den
            # Callback -> der Bot pollt NICHT, sondern wird via abort_fn gestoppt).
            self.esbot.mode = ('dagger'
                               if mode == 'energiesplitter_dagger'
                               else 'hammer')
            self.esbot.stop_signal = self.stop_signal
            # Inventar-Toggle-Taste aus der Config (Default 'i') injizieren --
            # der Energiesplitter oeffnet die Tasche selbst (open_probe).
            try:
                self.esbot.inventory_hotkey = (
                    self.controller.current_config()
                    .get('inventory', {}).get('hotkey', 'i'))
            except Exception:
                self.esbot.inventory_hotkey = 'i'
            self.apply_energiesplitter_config(values, mode)
            self.esbot.set_to_begin(values)   # erzeugt wincap, friert Config ein,
            #                                    ruft phase0_gate -> self.armed
            self.esbot.botting = True
            self.fishbot.botting = False
            self.puzzlebot.botting = False
        elif mode == 'fishing':
            # Konfigurierbare Hotkeys VOR set_to_begin auf die Instanz injizieren
            # (analog zur Puzzle-Config-Injektion). Frozen keys via to_values
            # bleiben unberuehrt; Default '2'/'1' -> byte-stabil.
            fish_cfg = self.controller.current_config()['fishing']
            self.fishbot.bait_key = fish_cfg['bait_key']
            self.fishbot.cast_key = fish_cfg['cast_key']
            # Mount-Taste fuer Symmetrie auf die Instanz spiegeln (set_to_begin
            # liest zusaetzlich -MOUNT-/-MOUNTKEY- aus values -> beides konsistent).
            self.fishbot.mount_key = fish_cfg['mount_key']
            # Angel-Whitelist: den an/aus-Schalter spiegeln (set_to_begin liest
            # zusaetzlich -WHITELIST- aus values) und die konkreten Fisch-
            # Entscheidungen (DE-Name -> KEEP/REMOVE/CAMPFIRE) aus der Inventar-
            # Verwaltung auf die Instanz injizieren. Default AUS/leer -> es wird
            # alles geangelt (byte-stabil). Wirft nie.
            self.fishbot.whitelist_enabled = bool(fish_cfg['whitelist_enabled'])
            self.fishbot.whitelist_states = self._collect_whitelist_states()
            # Koeder-Nachlegen: den an/aus-Schalter spiegeln (set_to_begin liest
            # zusaetzlich -BAITREFILL- aus values) und die Live-Infrastruktur
            # injizieren -- Inventar-DB (gebuendelt), Kalibrierung (Default), die
            # Inventar-Hotkey und den Popup-Hook. Default AUS/leer -> der Bot
            # prueft den Koeder-Slot nie (byte-stabil). Wirft nie.
            self.fishbot.bait_refill_enabled = bool(
                fish_cfg['bait_refill_enabled'])
            self.fishbot.bait_refill_db = self._bait_refill_db()
            self.fishbot.bait_refill_calib = None   # Engine-Default (DEFAULT_CALIBRATION)
            self.fishbot.inventory_hotkey = (
                self.controller.current_config()
                .get('inventory', {}).get('hotkey', 'i'))
            self.fishbot.on_bait_empty = self._on_bait_empty
            # Gemeinsames Stop-Signal injizieren: die schwere Refill-Op (Inventar
            # oeffnen/scannen/draggen) pollt es ueber interruptible-sleeps und
            # bricht bei F6 in <1 Slice ab -- der Bot haengt nie in einem Refill.
            self.fishbot.stop_signal = self.stop_signal
            self.fishbot.set_to_begin(values)   # erzeugt wincap, liest frozen keys
            self.fishbot.botting = True
            self.puzzlebot.botting = False
            if self.esbot is not None:
                self.esbot.botting = False
        else:
            self.apply_puzzle_config()
            # v1.3: Box-Nachlegen aus dem Inventar entfernt -> keine Refill-
            # Infrastruktur mehr injizieren. Leere Boxen behandelt der PuzzleBot
            # jetzt selbst per Spiel-Neustart (ESC -> Eventuebersicht ->
            # FISCHPUZZLESPIEL). Nur das gemeinsame Stop-Signal bleibt (F6 bricht
            # einen laufenden Selbststart-/Reopen-Flow ab).
            self.puzzlebot.stop_signal = self.stop_signal
            self.puzzlebot.set_to_begin(values)  # erzeugt wincap, resettet Offset
            self.inject_offset()                 # Offset NACH set_to_begin injizieren
            self.puzzlebot.botting = True
            self.fishbot.botting = False
            if self.esbot is not None:
                self.esbot.botting = False

    def on_stop(self):
        """Stoppt den Lauf. set_running(False) hat botting beider Bots bereits
        geleert (Exklusivitaets-Garantie) -- hier ist nichts weiter zu tun.

        Setzt zusaetzlich das Stop-Signal, damit eine evtl. GERADE laufende
        schwere Op (Refill mitten im Inventar-Scan/Drag) sofort abbricht, auch
        wenn der Stop ueber den UI-Button statt ueber F6 kam. Das Flag wird beim
        naechsten Tick / on_start wieder geraeumt.
        """
        self.fishbot.botting = False
        self.puzzlebot.botting = False
        if self.esbot is not None:
            self.esbot.botting = False
        try:
            self.stop_signal.request_stop()
        except Exception:
            pass

    # -- Tick --------------------------------------------------------------

    def _stop_hotkey_down(self):
        """``True``, wenn die konfigurierte Stop-Taste GERADE gedrueckt ist.

        Global (GetAsyncKeyState) -> wirkt auch bei Spiel-Fokus. Der VK wird nur
        ~4x/s aus der Config aufgefrischt (kein ``validate()`` pro 10ms-Tick),
        aber JEDEN Tick gepollt. Strikt defensiv -> nie den Tick kippen."""
        if _win32api is None:
            return False
        try:
            self._stop_vk_tick = getattr(self, '_stop_vk_tick', 99) + 1
            if self._stop_vk_tick >= 25 or not hasattr(self, '_stop_vk'):
                self._stop_vk_tick = 0
                key = (self.controller.current_config()
                       .get('controls', {}).get('stop_hotkey', 'f6'))
                self._stop_vk = _key_to_vk(key)
            if self._stop_vk is None:
                return False
            return bool(_win32api.GetAsyncKeyState(self._stop_vk) & 0x8000)
        except Exception:
            return False

    def tick(self):
        """Ein Bot-Schritt pro after()-Durchlauf. Genau ein Bot tickt (exklusiv)."""
        stop_reason = None

        # 0) Globaler Stop-Hotkey (Default F6): wirkt auch wenn das Spiel den
        #    Fokus hat. ZWEI Quellen, beide flag-/poll-basiert und defensiv:
        #    (a) der High-Frequency-Daemon hat das Stop-Signal bereits gesetzt
        #        (er hat botting schon via Callback geraeumt -- hier nur noch den
        #        Grund melden + das Signal konsumieren), ODER
        #    (b) der In-Tick-Fallback-Poll (greift, falls der Daemon nicht laufen
        #        kann, z. B. ohne win32). Nur relevant, solange ein Bot laeuft.
        es_botting = (self.esbot is not None and self.esbot.botting)
        bot_active = (self.fishbot.botting or self.puzzlebot.botting
                      or es_botting)
        if self.stop_signal.stopped:
            # Stop-Signal bricht auch einen wartenden Inventar-Cleanup ab
            # (Countdown/Auto-Neustart) -- der Nutzer will ALLES anhalten.
            try:
                self.app._cancel_timer_cleanup()
            except Exception:
                pass
            # Das Signal wurde gesetzt (Daemon-F6 ODER Button-Stop). Es hat seinen
            # Zweck (schwere Op abbrechen + botting raeumen) erfuellt -> hier
            # konsumieren. NUR wenn die Stop-TASTE die Quelle war (``_hotkey_fired``)
            # melden wir das mit Grund/Log; der Button-Stop bleibt still (er laeuft
            # ohnehin ueber set_running). botting defensiv nachziehen.
            self.fishbot.botting = False
            self.puzzlebot.botting = False
            if self.esbot is not None:
                self.esbot.botting = False
            if self._hotkey_fired and (bot_active or self.controller.running):
                log.event('-', t('run.stop_hotkey'))
                stop_reason = t('run.reason_stop_hotkey')
            self._hotkey_fired = False
            self.stop_signal.clear()
        elif bot_active and self._stop_hotkey_down():
            log.event('-', t('run.stop_hotkey'))
            self.fishbot.botting = False
            self.puzzlebot.botting = False
            if self.esbot is not None:
                self.esbot.botting = False
            stop_reason = t('run.reason_stop_hotkey')

        # 1) Globales Zeitlimit ZUERST (beide Modi) -- vor dem Bot-Schritt, damit
        #    der Grund "Zeitlimit" zuverlaessig vor einem evtl. internen Stop
        #    gemeldet wird.
        if (self._stop_deadline is not None
                and (self.fishbot.botting or self.puzzlebot.botting
                     or (self.esbot is not None and self.esbot.botting))
                and time.time() > self._stop_deadline):
            log.event('-', t('run.stop_time_limit_reached'))
            fishing_was_active = self.fishbot.botting
            self.fishbot.botting = False
            self.puzzlebot.botting = False
            if self.esbot is not None:
                self.esbot.botting = False
            self._stop_deadline = None
            stop_reason = t('run.reason_time_limit_reached')
            # ZEITLIMIT-AKTION 'cleanup' (nur Angel-Modus): statt endgueltig zu
            # stoppen den Inventar-Cleanup-Ablauf anstossen (Inventar sicher
            # oeffnen -> Scan -> Markierungen anwenden -> 40s-Countdown ->
            # Auto-Neustart; siehe views_inventory._start_timer_cleanup). Der
            # after()-Aufruf laeuft erst NACH diesem Tick, wenn set_running
            # (Schritt 3) den Leerlauf bereits gespiegelt hat. Hat bei
            # gleichzeitig gesetztem close_on_timer_expire VORRANG (Cleanup
            # impliziert Weiterlaufen). Strikt defensiv: nie den Tick kippen.
            cleanup_armed = False
            try:
                cfg_f = self.controller.current_config()['fishing']
                if (fishing_was_active
                        and cfg_f.get('timer_action', 'stop') == 'cleanup'):
                    cleanup_armed = True
                    stop_reason = t('run.reason_time_limit_cleanup')
                    self.app.after(300, self.app._start_timer_cleanup)
            except Exception:
                pass
            # Optional die App beenden statt nur stoppen (Setting #4). Default aus
            # -> reiner Stop -> byte-stabil. Strikt defensiv: nie den Tick kippen.
            # Bei aktivem Cleanup uebersprungen (Cleanup impliziert Weiterlaufen).
            try:
                if (not cleanup_armed
                        and self.controller.current_config()['window']['close_on_timer_expire']):
                    log.section(t('run.closing_timer_expired'))
                    try:
                        cfgmod.save(self.controller.current_config())
                    except Exception:
                        pass
                    try:
                        self.app.after(150, self.app._on_close)  # Log flushen, dann zu
                    except Exception:
                        pass
                    return                          # diesen Tick nicht weiterlaufen
            except Exception:
                pass

        # 2) Bot-Schritt (genau ein Bot tickt, exklusiv).
        try:
            if self.fishbot.botting:
                self.fishbot.runHack()
            elif self.puzzlebot.botting:
                # runHack stoppt sich bei ungueltiger Region selbst (botting=False)
                # und loggt die Ursache -- wir spiegeln das danach ins UI.
                self.puzzlebot.runHack()
            elif self.esbot is not None and self.esbot.botting:
                # Energiesplitter: EIN blockierender Tick (Erkennung->Entscheidung
                # ->eine Aktion). Stoppt sich bei Phase-0-Block/Stop-Bedingung
                # selbst (botting=False) und loggt die Ursache.
                self.esbot.runHack()
        except Exception as exc:
            # Vollstaendige Diagnose statt stillem Stop: Traceback an
            # Konsole+Datei, kontrollierter Stop beider Bots.
            log.error(t('run.crash_in_runhack'), exc=exc)
            try:
                log.event(getattr(self.puzzlebot, 'state', '-'),
                          t('run.stop_due_to_exception'),
                          new_piece=getattr(self.puzzlebot, 'new_piece', None))
            except Exception:
                pass
            self.fishbot.botting = False
            self.puzzlebot.botting = False
            if self.esbot is not None:
                self.esbot.botting = False
            stop_reason = t('run.reason_error_see_console')

        # 2b) Stats/Events (single-threaded, alle defensiv): Laufzeit anrechnen,
        #     Puzzle-Loesen-Flanke zaehlen, Event-Warnung loggen. Der Fang-Zaehler
        #     laeuft ueber den fishbot.on_catch-Callback (on_catch).
        self.accrue_runtime()
        self.detect_puzzle_solved()
        self.check_event_warning()

        # 2c) Stop-Signal, das WAEHREND dieses Ticks gefeuert wurde (der Daemon
        #     hat F6 mitten in einer schweren Op in Schritt 2 erkannt -> botting
        #     bereits geraeumt, die Op brach ueber das interruptible-sleep ab):
        #     hier konsumieren + korrekt attribuieren, damit die Statuszeile in
        #     Schritt 3 den Hotkey-Grund zeigt statt des generischen Fallbacks.
        if self.stop_signal.stopped:
            self.fishbot.botting = False
            self.puzzlebot.botting = False
            if self.esbot is not None:
                self.esbot.botting = False
            if stop_reason is None and self._hotkey_fired:
                log.event('-', t('run.stop_hotkey'))
                stop_reason = t('run.reason_stop_hotkey')
            self._hotkey_fired = False
            self.stop_signal.clear()

        # 3) Laufzustand spiegeln. Hat sich ein Bot SELBST gestoppt (Zeitlimit,
        #    Region-/Truhen-Fehler, Exception), faellt das UI auf START zurueck UND
        #    der Grund wird prominent in der Statuszeile gemeldet (Nutzer-Stop ist
        #    still).
        active = (self.fishbot.botting or self.puzzlebot.botting
                  or (self.esbot is not None and self.esbot.botting))
        if self.controller.running != active:
            was_running = self.controller.running
            self.controller.set_running(active)  # set_running ruft sync_controls()
            if not active and was_running:
                self.app.notify_stop(stop_reason or t('run.reason_stopped_see_console'))
                # Beim Stop die Statistik atomar sichern (nicht erst beim
                # Schliessen) -- so geht ein laufender Fortschritt bei Absturz
                # nicht verloren.
                self.do_stats_save()
        else:
            self.app.sync_button()              # Button-Text/Sperren konsistent halten

        # Live-Log-Queue ins Textfeld leeren (nur GUI-Thread, wirft nie).
        try:
            self.app.log_panel.pump()
        except Exception:
            pass

        # Naechsten Tick planen. Ist das Fenster bereits zerstoert (Schliessen),
        # wirft after() -> Schleife endet sauber.
        try:
            self.app.after(self.tick_ms, self.tick)
        except Exception:
            pass
