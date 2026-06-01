"""Einstiegspunkt: verdrahtet das CustomTkinter-Single-Window mit den Bots.

Ersetzt den alten FreeSimpleGUI-``window.read(timeout=1)``-Loop durch den
CTk-Mainloop plus einen Bot-Tick via ``after()`` (gleiche ~1ms-Kadenz wie
zuvor, single-threaded). Architektur/Vertraege siehe REDESIGN_SPEC.md und das
Build-Blueprint:

* Das UI (``interface.App``) haelt den :class:`~interface.app.BotController` mit
  beiden Bot-Instanzen (``fishbot``/``puzzlebot``) und stellt den
  Integrations-Handshake bereit: ``mode``, ``running``, ``collect_values()``,
  ``current_config()``, ``set_running()`` sowie die Callbacks ``on_start`` /
  ``on_stop`` (vom Button-Handler ``on_start_stop`` aufgerufen).
* START/STOP startet den GEWAEHLTEN Modus (Fishing | Puzzle), strikt exklusiv:
  es ist nie ``fishbot.botting`` UND ``puzzlebot.botting`` gleichzeitig wahr.
* Settings/Detection-/Color-/Solver-Mode kommen aus der validierten Config und
  werden an FishingBot/PuzzleBot durchgereicht. Angeln laeuft unveraendert ueber
  ``set_to_begin(values)`` (frozen keys) -> byte-stabil.
* Der per Detection-Modus aufgeloeste Board-Offset
  (``detection.resolve_offset``) wird NACH ``puzzlebot.set_to_begin`` auf das
  Instanz-Attribut ``puzzlebot.puzzle_offset`` injiziert (``set_to_begin`` setzt
  es auf den Default zurueck -- die Injektion muss danach erfolgen). Im
  ``mark``-Modus werden zusaetzlich die kalibrierte Board-Groesse
  (``mark_size`` -> ``puzzlebot.board_size``) und die Sonderpunkt-Overrides
  (``mark_keypoints`` -> ``puzzlebot.key_points``) durchgereicht. Ohne
  ``mark``-Modus bzw. ohne diese Felder bleiben Groesse/Sonderpunkte auf den
  Klassen-Defaults ((260,170) / {}) -> byte-stabil (rein additiv, opt-in).
* Das Live-Log-Panel haengt sich als thread-sichere Senke an ``debuglog`` (im
  UI), die Tick-Schleife leert dessen Queue periodisch (``log_panel.pump()``).

Diese Datei ist reiner Glue: keine Aenderung an Angel-/Puzzle-/Detection-Logik.
UI-Strings sind ENGLISCH (im UI-Modul), Kommentare hier deutsch (Spec).
"""

import time

from debuglog import log
from i18n import t
from interface import config as cfgmod
from interface.app import App
import detection


# Debug-Konsole einmalig beim Start verdrahten: parallel Konsole + Logdatei,
# damit Angel-/Puzzle-Fehler auch aus der gepackten .exe nachvollziehbar sind.
log.configure(to_console=True, to_file=True, path='puzzle_debug.log',
              level='DEBUG')
log.section(t('run.bot_started'))

# Persistierte Konfiguration laden (wirft nie; fehlende/kaputte Datei ->
# validierte Defaults = heutiges Verhalten).
cfg = cfgmod.load()

# Single-Window aufbauen. Die App erzeugt intern FishingBot()/PuzzleBot() und
# den BotController; das Log-Panel haengt sich (bei show_in_ui) selbst an
# debuglog. Wir greifen die fertigen Instanzen ueber den Controller ab.
app = App(cfg)
controller = app.controller
fishbot = controller.fishbot
puzzlebot = controller.puzzlebot

# Tick-Kadenz: 10 ms. Reicht voellig (runHack blockiert ohnehin waehrend einer
# Aktion); ein 1-ms-after-Loop kann sich bei interaktivem Fenster-Resize mit den
# CTk-Redraws verzahnen -> 10 ms ist deutlich robuster und genauso fluessig.
TICK_MS = 10

# Globales Zeitlimit ("Stop after X minutes"): bei START gesetzt, im Tick
# geprueft -- gilt fuer BEIDE Modi. None = kein Limit; nur positive Minuten.
_stop_deadline = None


def _arm_stop_after():
    """Setzt/loescht das globale Zeitlimit anhand der aktuellen Einstellungen."""
    global _stop_deadline
    _stop_deadline = None
    fishing = controller.current_config()['fishing']
    if fishing['stop_after_enabled'] and fishing['stop_after_minutes'] > 0:
        _stop_deadline = time.time() + fishing['stop_after_minutes'] * 60


def _apply_puzzle_config():
    """Reicht die Puzzle-Optionen aus der Config an die PuzzleBot-Instanz.

    Color-/Solver-Mode werden auf das Instanz-Attribut gesetzt; der Board-Offset
    wird separat NACH set_to_begin aufgeloest und injiziert (siehe _on_start).
    puzzle.py importiert detection NICHT -- der Offset kommt von hier (kein
    Importzyklus B<->C).
    """
    puzzle = controller.current_config()['puzzle']
    puzzlebot.color_mode = puzzle['color_mode']
    puzzlebot.color_patch = puzzle['color_patch']
    puzzlebot.solver_mode = puzzle['solver_mode']


def _inject_offset():
    """Loest den Board-Offset aus dem Detection-Modus auf und injiziert ihn.

    MUSS nach ``puzzlebot.set_to_begin`` laufen, weil set_to_begin den Offset
    auf den Klassen-Default zuruecksetzt. ``resolve_offset`` wirft nie und
    liefert nie None -- ein Fehler hier darf den Start nicht stoppen.

    Im ``mark``-Modus werden ausserdem die kalibrierte Board-Groesse
    (``mark_size``) und die Sonderpunkt-Overrides (``mark_keypoints``) auf
    ``puzzlebot.board_size`` / ``puzzlebot.key_points`` injiziert (siehe
    :func:`_inject_board_overrides`). Beides ist additiv/opt-in: ohne
    ``mark``-Modus bzw. ohne diese Felder bleiben die Klassen-Defaults
    ((260,170) / {}) -> byte-stabil.
    """
    puzzle = controller.current_config()['puzzle']
    saved = puzzle['mark_offset']
    saved_offset = tuple(saved) if saved else None
    try:
        # Screenshot fuer den auto-Modus; default/mark brauchen ihn nicht.
        screenshot = None
        if puzzle['detection_mode'] == 'auto':
            screenshot = puzzlebot.wincap.get_screenshot()
        puzzlebot.puzzle_offset = detection.resolve_offset(
            puzzle['detection_mode'], screenshot=screenshot,
            saved_offset=saved_offset)
        log.event(0, t('run.board_offset_resolved'),
                  mode=puzzle['detection_mode'], offset=puzzlebot.puzzle_offset)
    except Exception as exc:
        # Kein Stop wegen Detection: auf den (von set_to_begin gesetzten)
        # Default-Offset zuruckfallen und weiterlaufen.
        log.error(t('run.offset_resolution_failed'), exc=exc)

    # Board-Groesse + Sonderpunkte separat (eigenes try): ein Fehler hier darf
    # weder den Start noch die bereits gesetzte Offset-Aufloesung kippen.
    _inject_board_overrides(puzzle)


def _inject_board_overrides(puzzle):
    """Reicht ``mark_size``/``mark_keypoints`` an den PuzzleBot durch.

    Strikt additiv und opt-in: NUR im ``mark``-Modus und nur fuer truthy Werte
    werden ``board_size``/``key_points`` ueberschrieben. In allen anderen Faellen
    (default/auto, oder leere mark-Felder) bleiben die Klassen-Defaults stehen,
    die ``set_to_begin`` unmittelbar zuvor gesetzt hat ((260,170) / {}) --
    explizit zurueckgesetzt, damit kein Wert eines frueheren mark-Laufs ueber
    einen Modus-Wechsel hinweg haengen bleibt. Default-Pfad bleibt byte-stabil.

    ``config.validate`` hat ``mark_size`` bereits als [w,h]-Int-Paar (oder None)
    und ``mark_keypoints`` als {name: [x,y]}-Int-Dict (oder {}) normalisiert;
    hier nur die Form (Tuple) angleichen. Wirft nie -- ein Fehler faellt auf die
    Defaults zurueck und laesst den Lauf weiterlaufen.
    """
    try:
        is_mark = puzzle.get('detection_mode') == 'mark'
        size = puzzle.get('mark_size') if is_mark else None
        if size:
            puzzlebot.board_size = tuple(size)
        else:
            puzzlebot.board_size = puzzlebot.PUZZLE_WINDOW_SIZE

        keypoints = puzzle.get('mark_keypoints') if is_mark else None
        if keypoints:
            puzzlebot.key_points = {
                name: tuple(point) for name, point in keypoints.items()}
        else:
            puzzlebot.key_points = {}

        if is_mark and (size or keypoints):
            log.event(0, t('run.board_overrides_injected'),
                      board_size=puzzlebot.board_size,
                      key_points=sorted(puzzlebot.key_points))
    except Exception as exc:
        # Auf Defaults zuruckfallen (byte-stabiler Pfad) und weiterlaufen.
        puzzlebot.board_size = puzzlebot.PUZZLE_WINDOW_SIZE
        puzzlebot.key_points = {}
        log.error(t('run.board_override_injection_failed'),
                  exc=exc)


def _on_start():
    """Startet den aktuell gewaehlten Modus (vom BotController-Button gerufen).

    Wirft hier nicht: der Controller umschliesst on_start mit eigenem
    try/except und setzt anschliessend den Laufzustand (set_running). Diese
    Funktion verdrahtet NUR die Bots -- das Laufflag setzt der Controller.
    Exklusivitaet wird hart erzwungen (immer genau ein Bot botting=True).
    """
    values = controller.collect_values()
    _arm_stop_after()
    if controller.mode == 'fishing':
        # Konfigurierbare Hotkeys VOR set_to_begin auf die Instanz injizieren
        # (analog zur Puzzle-Config-Injektion). Frozen keys via to_values bleiben
        # unberuehrt; Default '2'/'1' -> byte-stabil.
        fish_cfg = controller.current_config()['fishing']
        fishbot.bait_key = fish_cfg['bait_key']
        fishbot.cast_key = fish_cfg['cast_key']
        fishbot.set_to_begin(values)      # erzeugt wincap, liest frozen keys
        fishbot.botting = True
        puzzlebot.botting = False
    else:
        _apply_puzzle_config()
        puzzlebot.set_to_begin(values)    # erzeugt wincap, resettet Offset
        _inject_offset()                  # Offset NACH set_to_begin injizieren
        puzzlebot.botting = True
        fishbot.botting = False


def _on_stop():
    """Stoppt den Lauf. set_running(False) hat botting beider Bots bereits
    geleert (Exklusivitaets-Garantie) -- hier ist nichts weiter zu tun.
    """
    fishbot.botting = False
    puzzlebot.botting = False


# Integrations-Callbacks am Controller registrieren. on_start_stop ruft je nach
# Laufzustand on_start/on_stop und kuemmert sich um set_running + UI-Sync.
controller.on_start = _on_start
controller.on_stop = _on_stop


def _tick():
    """Ein Bot-Schritt pro after()-Durchlauf. Genau ein Bot tickt (exklusiv)."""
    stop_reason = None

    # 1) Globales Zeitlimit ZUERST (beide Modi) -- vor dem Bot-Schritt, damit der
    #    Grund "Zeitlimit" zuverlaessig vor einem evtl. internen Stop gemeldet wird.
    global _stop_deadline
    if (_stop_deadline is not None and (fishbot.botting or puzzlebot.botting)
            and time.time() > _stop_deadline):
        log.event('-', t('run.stop_time_limit_reached'))
        fishbot.botting = False
        puzzlebot.botting = False
        _stop_deadline = None
        stop_reason = t('run.reason_time_limit_reached')
        # Optional die App beenden statt nur stoppen (Setting #4). Default aus
        # -> reiner Stop -> byte-stabil. Strikt defensiv: nie den Tick kippen.
        try:
            if controller.current_config()['window']['close_on_timer_expire']:
                log.section(t('run.closing_timer_expired'))
                try:
                    cfgmod.save(controller.current_config())
                except Exception:
                    pass
                try:
                    app.after(150, app._on_close)   # Log flushen, dann sauber zu
                except Exception:
                    pass
                return                              # diesen Tick nicht weiterlaufen
        except Exception:
            pass

    # 2) Bot-Schritt (genau ein Bot tickt, exklusiv).
    try:
        if fishbot.botting:
            fishbot.runHack()
        elif puzzlebot.botting:
            # runHack stoppt sich bei ungueltiger Region selbst (botting=False)
            # und loggt die Ursache -- wir spiegeln das danach ins UI.
            puzzlebot.runHack()
    except Exception as exc:
        # Vollstaendige Diagnose statt stillem Stop: Traceback an Konsole+Datei,
        # kontrollierter Stop beider Bots.
        log.error(t('run.crash_in_runhack'), exc=exc)
        try:
            log.event(getattr(puzzlebot, 'state', '-'), t('run.stop_due_to_exception'),
                      new_piece=getattr(puzzlebot, 'new_piece', None))
        except Exception:
            pass
        fishbot.botting = False
        puzzlebot.botting = False
        stop_reason = t('run.reason_error_see_console')

    # 3) Laufzustand spiegeln. Hat sich ein Bot SELBST gestoppt (Zeitlimit,
    #    Region-/Truhen-Fehler, Exception), faellt das UI auf START zurueck UND der
    #    Grund wird prominent in der Statuszeile gemeldet (Nutzer-Stop ist still).
    active = fishbot.botting or puzzlebot.botting
    if controller.running != active:
        was_running = controller.running
        controller.set_running(active)   # set_running ruft sync_controls()
        if not active and was_running:
            app.notify_stop(stop_reason or t('run.reason_stopped_see_console'))
    else:
        app.sync_button()                # Button-Text/Sperren konsistent halten

    # Live-Log-Queue ins Textfeld leeren (nur GUI-Thread, wirft nie).
    try:
        app.log_panel.pump()
    except Exception:
        pass

    # Naechsten Tick planen. Ist das Fenster bereits zerstoert (Schliessen),
    # wirft after() -> Schleife endet sauber.
    try:
        app.after(TICK_MS, _tick)
    except Exception:
        pass


# Ersten Tick einreihen und in den CTk-Mainloop gehen. Das Schliessen des
# Fensters speichert die Config und loest die Log-Senke (von App._on_close
# behandelt) und beendet den Mainloop.
app.after(TICK_MS, _tick)
app.mainloop()
