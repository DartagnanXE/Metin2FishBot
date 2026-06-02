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
Die gesamte Lauf-Verdrahtung (Tick-Schleife + Counter/Stats/Events + Start/Stop)
liegt in :class:`run_loop.RunLoop`; ``hack.py`` ist nur noch der duenne
Bootstrap, der Logging/Config/Statistik laedt, die App baut, die ``RunLoop``
verdrahtet und in den Mainloop geht. UI-Strings sind ENGLISCH (im UI-Modul),
Kommentare hier deutsch (Spec).
"""

from debuglog import log
from i18n import t
from interface import config as cfgmod
from interface.app import App
import stats as statsmod
from run_loop import RunLoop


# Debug-Konsole einmalig beim Start verdrahten: parallel Konsole + Logdatei,
# damit Angel-/Puzzle-Fehler auch aus der gepackten .exe nachvollziehbar sind.
log.configure(to_console=True, to_file=True, path='puzzle_debug.log',
              level='DEBUG')
log.section(t('run.bot_started'))

# Persistierte Konfiguration laden (wirft nie; fehlende/kaputte Datei ->
# validierte Defaults = heutiges Verhalten).
cfg = cfgmod.load()

# Persistente Statistik (stats.json neben config.json) laden -- wirft nie;
# fehlende/kaputte Datei -> validierte Defaults (alle Zaehler 0).
_stats = statsmod.load()

# Single-Window aufbauen. Die App erzeugt intern FishingBot()/PuzzleBot() und
# den BotController; das Log-Panel haengt sich (bei show_in_ui) selbst an
# debuglog. Wir greifen die fertigen Instanzen ueber den Controller ab.
app = App(cfg)

# Statistik auf der App ablegen, damit der Ranking-Tab (interface.ranking_view)
# und der Telemetrie-Snapshot (app._telemetry_state) sie live lesen koennen.
app._stats = _stats

# Lauf-Verdrahtung: registriert Stats-Hook + Counter-Hook + Start/Stop-Callbacks
# und reiht den ersten Tick ein (Tick-Kadenz/Logik vollstaendig in RunLoop).
_run = RunLoop(app)
_run.wire()

# In den CTk-Mainloop gehen. Das Schliessen des Fensters speichert die Config und
# loest die Log-Senke (von App._on_close behandelt) und beendet den Mainloop.
app.mainloop()

# Sicherheitsnetz: Sollte der Mainloop je auf einem Pfad enden, der App._on_close
# nicht durchlaeuft, hier final speichern (App._on_close/_hard_exit_for_update
# haben i.d.R. bereits via RunLoop.flush_stats_on_exit gesichert -- doppelt
# schadet nie, der atomare Replace ist idempotent). Wirft nie.
try:
    _run.flush_stats_on_exit()
except Exception:
    pass
