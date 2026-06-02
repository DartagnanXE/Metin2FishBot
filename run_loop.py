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


# Tick-Kadenz: 10 ms. Reicht voellig (runHack blockiert ohnehin waehrend einer
# Aktion); ein 1-ms-after-Loop kann sich bei interaktivem Fenster-Resize mit den
# CTk-Redraws verzahnen -> 10 ms ist deutlich robuster und genauso fluessig.
TICK_MS = 10


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
        self.tick_ms = tick_ms

        # Globales Zeitlimit ("Stop after X minutes"): bei START gesetzt, im Tick
        # geprueft -- gilt fuer BEIDE Modi. None = kein Limit; nur positive Minuten.
        self._stop_deadline = None

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
        # Ersten Tick einreihen (der Mainloop wird vom Bootstrap gestartet).
        self.app.after(self.tick_ms, self.tick)

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

    def on_start(self):
        """Startet den aktuell gewaehlten Modus (vom BotController-Button gerufen).

        Wirft hier nicht: der Controller umschliesst on_start mit eigenem
        try/except und setzt anschliessend den Laufzustand (set_running). Diese
        Methode verdrahtet NUR die Bots -- das Laufflag setzt der Controller.
        Exklusivitaet wird hart erzwungen (immer genau ein Bot botting=True).
        """
        values = self.controller.collect_values()
        self.arm_stop_after()
        if self.controller.mode == 'fishing':
            # Konfigurierbare Hotkeys VOR set_to_begin auf die Instanz injizieren
            # (analog zur Puzzle-Config-Injektion). Frozen keys via to_values
            # bleiben unberuehrt; Default '2'/'1' -> byte-stabil.
            fish_cfg = self.controller.current_config()['fishing']
            self.fishbot.bait_key = fish_cfg['bait_key']
            self.fishbot.cast_key = fish_cfg['cast_key']
            # Mount-Taste fuer Symmetrie auf die Instanz spiegeln (set_to_begin
            # liest zusaetzlich -MOUNT-/-MOUNTKEY- aus values -> beides konsistent).
            self.fishbot.mount_key = fish_cfg['mount_key']
            self.fishbot.set_to_begin(values)   # erzeugt wincap, liest frozen keys
            self.fishbot.botting = True
            self.puzzlebot.botting = False
        else:
            self.apply_puzzle_config()
            self.puzzlebot.set_to_begin(values)  # erzeugt wincap, resettet Offset
            self.inject_offset()                 # Offset NACH set_to_begin injizieren
            self.puzzlebot.botting = True
            self.fishbot.botting = False

    def on_stop(self):
        """Stoppt den Lauf. set_running(False) hat botting beider Bots bereits
        geleert (Exklusivitaets-Garantie) -- hier ist nichts weiter zu tun.
        """
        self.fishbot.botting = False
        self.puzzlebot.botting = False

    # -- Tick --------------------------------------------------------------

    def tick(self):
        """Ein Bot-Schritt pro after()-Durchlauf. Genau ein Bot tickt (exklusiv)."""
        stop_reason = None

        # 1) Globales Zeitlimit ZUERST (beide Modi) -- vor dem Bot-Schritt, damit
        #    der Grund "Zeitlimit" zuverlaessig vor einem evtl. internen Stop
        #    gemeldet wird.
        if (self._stop_deadline is not None
                and (self.fishbot.botting or self.puzzlebot.botting)
                and time.time() > self._stop_deadline):
            log.event('-', t('run.stop_time_limit_reached'))
            self.fishbot.botting = False
            self.puzzlebot.botting = False
            self._stop_deadline = None
            stop_reason = t('run.reason_time_limit_reached')
            # Optional die App beenden statt nur stoppen (Setting #4). Default aus
            # -> reiner Stop -> byte-stabil. Strikt defensiv: nie den Tick kippen.
            try:
                if self.controller.current_config()['window']['close_on_timer_expire']:
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
            stop_reason = t('run.reason_error_see_console')

        # 2b) Stats/Events (single-threaded, alle defensiv): Laufzeit anrechnen,
        #     Puzzle-Loesen-Flanke zaehlen, Event-Warnung loggen. Der Fang-Zaehler
        #     laeuft ueber den fishbot.on_catch-Callback (on_catch).
        self.accrue_runtime()
        self.detect_puzzle_solved()
        self.check_event_warning()

        # 3) Laufzustand spiegeln. Hat sich ein Bot SELBST gestoppt (Zeitlimit,
        #    Region-/Truhen-Fehler, Exception), faellt das UI auf START zurueck UND
        #    der Grund wird prominent in der Statuszeile gemeldet (Nutzer-Stop ist
        #    still).
        active = self.fishbot.botting or self.puzzlebot.botting
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
