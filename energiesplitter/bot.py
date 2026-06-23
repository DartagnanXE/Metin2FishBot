"""EnergiesplitterBot -- Bot-Kern + Phase-0-GATE + State-Maschinen (Eigentuemer D).

EINE Klasse, ZWEI Aktionen (Modus-Schalter ``self.mode``):

* ``MODE_HAMMER``  -- Aktion 1: ``stack_count`` (X) mal einen **200er-Hammer-
  Stack** am Alchemisten kaufen (template-verifiziert, Re-Read-belegt), dann
  Auto-Stop.
* ``MODE_DAGGER``  -- Aktion 2: Schleife bis keine Haemmer mehr im Inventar:
  ``daggers_per_round`` Dolche kaufen, dann EINZELN NACHEINANDER verarbeiten
  (je 1 Drag eines Hammer-STACKS auf einen Dolch verbraucht 1 Hammer + 1 Dolch).

Integration ueber den ``run_loop``-Bot-Tick (wie ``fishbot``/``puzzlebot``):
``set_to_begin(values)`` friert die Config ein und ruft den Phase-0-GATE,
``runHack()`` fuehrt GENAU EINEN blockierenden Tick aus und stoppt sich bei
jeder Stop-Bedingung selbst (``self.botting = False``).

PHASE-0-GATE (harter Blocker, §2 CONTRACT): solange ``self.dry_run`` ODER
``not self.armed``, ruft der Bot NIE ``rightClick``/``click``/``drag``/
``keyDown`` -- er liest, loggt und stoppt. ``armed`` setzt ALLEIN
``phase0_gate()`` = ``detect.assets_ready(mode).ready AND
geometry.is_calibrated(wincap) AND detect.grid_present()`` (Templates + Shop-
Anker bereit, Fenster-Groesse 800x600 UND aufloesbares Inventar-Raster). YANG
spielt seit dem Umbau 2026-06-16 KEINE Rolle mehr -- kein Preis, kein Kontostand,
keine Ausgabe-Verfolgung. Als OCR-unabhaengige Backstops bleiben ``max_actions``
(``_action_cap_hit``) und ``consecutive_unverified_stop`` in JEDER Kauf-/
Verarbeitungs-Entscheidung wirksam, plus die Erkennung-vor-Aktion (Kauf/Drag nur
auf template-verifizierte Ziele).

Headless-Sicherheit: ``pydirectinput`` und die Schwester-Module von Agent A
(``detect``/``geometry``) werden WEICH importiert. Fehlt etwas, landet es als
``missing``-Eintrag im GATE -- kein ImportError, kein Klick.
"""

import time

import constants
from debuglog import log
from i18n import t

# -- weiche Imports (Build-Reihenfolge A/B/D parallel; headless-sicher) -------
# Fehlt ein Modul, bleibt der Bot importierbar; der Phase-0-GATE meldet die
# Luecke als 'missing' und blockt -- nie ein harter ImportError, nie ein Klick.

try:  # Eingabe-Treiber (Windows-only; in Tests gestubbt)
    import pydirectinput as _input
except Exception:  # pragma: no cover - nur ohne Windows-Treiber
    _input = None


def set_input_backend(backend):
    """Tauscht den modulweiten Eingabe-Treiber ``_input`` (Multiclient).

    Default = ``pydirectinput`` (Single-Client byte-identisch). Der Worker
    injiziert hier ein ``cursor_client.LeasedPydirectinput`` -> jede Eingabe
    laeuft als EIN Lease-Burst ueber die geteilte Maus. ``None`` -> der
    Phase-0/_guarded-Gate blockt jede Aktion (``_input is None``). Wirkt auf alle
    ``_input.*``-Aufrufe inkl. ``_discard_drag(_input, ...)``."""
    global _input
    _input = backend

try:  # Fenster-Capture (Windows-only; in Tests gestubbt)
    from windowcapture import WindowCapture as _WindowCapture
except Exception:  # pragma: no cover
    _WindowCapture = None

try:  # Fenster-Fokus (Vordergrund holen; Tasten brauchen Fokus). Soft.
    from windowcapture import focus_window as _focus_window
except Exception:  # pragma: no cover
    _focus_window = None

try:  # Vision/Asset-Pruefung (Agent A)
    from energiesplitter import detect as _detect
except Exception:
    _detect = None

try:  # Geometrie/Kalibrierung (Agent A)
    from energiesplitter import geometry as _geometry
except Exception:
    _geometry = None

# Drag-Primitiv WIEDERVERWENDEN (A2) -- nie neu bauen. mouseUp im finally.
try:
    from inventory_discard import drag as _discard_drag
except Exception:  # pragma: no cover
    _discard_drag = None

# Inventar-Offen-Erkennung laeuft jetzt ueber den eigenen, OFFSET-TOLERANTEN
# Detektor ``detect.inventory_open`` (periodische Slot-Struktur) -- die fruehere
# Angel-Tab-Template-Probe war am Live-Capture zu pixel-genau (Live-Bug
# 2026-06-20). Kein Inventar-Paket-Import mehr noetig.


MODE_HAMMER = 'hammer'
MODE_DAGGER = 'dagger'

# State-Maschinen + Bruecken als Mixins (NACH den weichen Globals importiert,
# damit deren Lauf-Lesen von ``_detect``/``_geometry`` ueber dieses Modul greift
# -- inkl. Test-Patching ``mock.patch.object(esbot_mod, ...)``).
from energiesplitter.bridges import BridgesMixin
from energiesplitter.flow_hammer import HammerFlowMixin
from energiesplitter.flow_dagger import DaggerFlowMixin


class EnergiesplitterBot(HammerFlowMixin, DaggerFlowMixin, BridgesMixin):
  """Energiesplitter-Bot mit Modus-Schalter (siehe Modul-Docstring, CONTRACT §1).

  Die zwei State-Maschinen (Hammer/Dolch) und die Detect-/Geometry-Bruecken sind
  in :mod:`energiesplitter.flow_hammer` / :mod:`energiesplitter.flow_dagger` /
  :mod:`energiesplitter.bridges` als Mixins ausgelagert -- die oeffentliche API
  (Attribute/Methoden) bleibt unveraendert auf DIESER Klasse."""

  # -- State-Konstanten (Klassen-Attribute, int) --------------------------
  ST_INIT = 0
  ST_INVENTORY_BASE = 1
  ST_APPROACH_NPC = 2
  ST_SELECT_NPC = 3
  ST_OPEN_DIALOG = 4
  ST_UNLOCK_DECIDE = 5
  ST_OPEN_SHOP = 6
  ST_UNLOCK_STORY = 7
  ST_LOCATE_HAMMER = 8
  ST_BUY_LOOP = 9
  ST_CHECK_DONE = 10
  ST_LOCATE_DOLCH = 11
  ST_BUY_ONE_DOLCH = 12
  ST_PROCESS_DRAG = 13
  ST_VERIFY_PROCESS = 14
  ST_RESCAN = 15
  ST_PREPROCESS = 16
  ST_STOP = 99

  # -- Modus-Konstanten ---------------------------------------------------
  MODE_HAMMER = MODE_HAMMER
  MODE_DAGGER = MODE_DAGGER

  # -- run_loop-/Lebenszyklus-Defaults (von run_loop ueberschrieben) ------
  botting = False
  mode = MODE_HAMMER
  state = ST_INIT
  wincap = None
  stop_signal = None

  # -- sichere Erststart-Defaults (CONTRACT §2) ---------------------------
  # dry_run=True bis Phase-0 + Nutzer-Bestaetigung; armed wird ALLEIN von
  # phase0_gate() gesetzt. So bleibt ein frisch konstruierter Bot harmlos.
  dry_run = True
  armed = False
  max_actions = 2
  consecutive_unverified_stop = 3

  # Fixe Mechanik-Konstante: ein Hammer-Kauf ist IMMER ein 200er-Stack.
  HAMMER_STACK_SIZE = 200

  # NPC-Suche: der Bot faehrt EINMAL pro Lauf die volle VOGELPERSPEKTIVE per
  # Rechtsklick-Drag (Maus 25% der Hoehe runterziehen -> Kamera top-down; erst so
  # ist der NPC-Klick zuverlaessig). Danach Settle, dann Namens-Suche; bei Miss
  # bounded Retries (Kamera nachziehen). NPC_MAX_TRIES = Such-Versuche,
  # NPC_SETTLE_S = Kamera-Renderzeit (Tests setzen 0). Instanz-ueberschreibbar.
  NPC_MAX_TRIES = 4
  NPC_SETTLE_S = 0.8
  # Volle Vogelperspektive = Rechtsklick gedrueckt halten + Maus diesen Anteil der
  # Client-Hoehe (600) nach unten ziehen (User-Grundwahrheit: 25%).
  BIRDSEYE_DRAG_FRACTION = 0.25
  # Wartezeit, damit der Kauf-Bestaetigungsdialog ('Ja'/'Nein') erscheint bzw.
  # der Kauf verarbeitet wird (Tests setzen 0).
  BUY_CONFIRM_SETTLE_S = 0.4
  # Chat-Modus: max. Wartezeit, bis ein gekaufter Dolch im Inventar LANDET (freie
  # Slots sinken), bevor der Versuch als blockiert (-> Backoff/Retry) gilt. Der
  # Dolch rendert i.d.R. < 0.5s -> 0.7s deckt das mit Polster, haelt aber den Kauf
  # schnell (kein sekundenlanges Chat-Warten mehr). Tests setzen 0.
  BUY_VERIFY_TIMEOUT_S = 0.7
  # Poll-Intervall fuer die Chat-Verifikation (Frame-Takt). Tests setzen 0.
  DETECT_POLL_INTERVAL_S = 0.03
  # Erkennung-vor-Aktion (zeitlich): statt fix BUY_CONFIRM_SETTLE_S zu warten, wird
  # auf den Bestaetigungsdialog GEPOLLT und 'Ja' SOFORT geklickt, sobald er erkannt
  # ist -> kein verschenktes Blind-Warten, kein Klick vor dem Rendern. Max. so lange
  # pollen, bevor (best-effort) weitergemacht wird. Tests setzen 0.
  CONFIRM_POLL_TIMEOUT_S = 1.0
  # Max. aufeinanderfolgende rate-limitierte/unklare Kaeufe DESSELBEN Dolchs, bevor
  # der Kauf-Loop (defensiv) aufgibt -> der Lauf stoppt NICHT hart, sondern geht in
  # die Verarbeitung des bisher Gekauften (Rate-Limit ist transient).
  BUY_RATELIMIT_MAX = 12
  # So viele Runden IN FOLGE ohne jede Verarbeitung (splitter_summe waechst nicht)
  # -> sauberer Stop (evtl. kein Geld/Yang mehr ODER nichts mehr kaufbar). Faengt
  # die Endlosschleife "kaufen scheitert -> nichts verarbeitet -> erneut" ab.
  NO_PROGRESS_ROUNDS_MAX = 3
  # Pause zwischen den beiden Klicks der Zwei-Klick-Verarbeitung (Hammer aufnehmen
  # -> auf Dolch setzen). User-Grundwahrheit: Hammer ist KEIN Drag, sondern
  # Linksklick (aufnehmen) + Linksklick (setzen). Kurze Pause, damit der erste
  # Klick (Aufnahme) registriert ist, bevor der zweite (Setzen) kommt. Tests = 0.
  PICKUP_SETTLE_S = 0.15
  # Der Shop blendet nach 'Laden oeffnen' ein -> das Item-Suchen mehrfach mit
  # Renderpause wiederholen, bevor 'nicht im Shop' gemeldet wird (fing den Fall
  # ab: ein Tester sah ncc=0.547, weil der Shop noch nicht fertig gerendert war).
  SHOP_LOCATE_MAX_TRIES = 6
  # Wartezeit, damit der Shop nach 'Laden oeffnen' rendert, bevor das Item
  # gesucht wird (Tests setzen 0).
  SHOP_OPEN_SETTLE_S = 0.5
  # Wartezeit, damit der NPC-DIALOG nach dem Ansprechen (Linksklick) erscheint,
  # bevor nach 'Laden oeffnen' gesucht wird. FEHLTE -> die Suche lief ~30ms nach
  # dem Klick, der Dialog war noch nicht offen (Tester: ncc 0.274). Tests = 0.
  DIALOG_SETTLE_S = 0.7
  # Wie oft 'Laden oeffnen' (Dialog) mit Renderpause erneut gesucht wird, bevor
  # 'Laden oeffnete nicht' gemeldet wird.
  DIALOG_OPEN_MAX_TRIES = 5

  def __init__(self):
    # Konstruktor haelt das Objekt headless-konstruierbar; die echte Config
    # friert set_to_begin ein. Defensive Defaults setzen, damit Read-Only-
    # Zugriffe vor set_to_begin nie crashen.
    self.mode = MODE_HAMMER
    self.state = self.ST_INIT
    self.wincap = None
    self.stop_signal = None
    self._stop_reason = None
    self._missing = []
    self._reset_config_defaults()
    self._reset_counters()

  # -- Config-Defaults (vor set_to_begin; werden dann eingefroren) --------
  def _reset_config_defaults(self):
    self.stack_count = 1
    self.energie_freischalten = True
    self.daggers_per_round = 20
    self.mouse_pause = 0.05
    self.keyboard_pause = 0.10
    self.speed_profile = 'fast'
    self.jitter_pct = 0.15
    # Dolch-Kauf-Verifikation (umschaltbar): 'chat' = Chat-Quittung lesen
    # (Vorher/Nachher, Erfolg vs. 'Bitte spaeter erneut'); 'click' = rein
    # klickbasiert mit fixem Delay, KEINE Erkennung (robust bei mehreren
    # Inventarseiten). buy_delay_s = Pause zwischen Kaufklicks bzw. Backoff vor
    # Wiederholung im Chat-Modus.
    self.buy_mode = 'chat'
    self.buy_delay_s = 0.35
    # "Erst verarbeiten": vor dem Kauf erst die schon auf Seite 1 liegenden
    # Dolche einzeln verarbeiten (nur Dolche). Einmal pro Lauf.
    self.process_first = False
    self.inventory_hotkey = 'i'   # Toggle-Taste Tasche (run_loop injiziert Config)
    self.max_actions = 2
    self.consecutive_unverified_stop = 3
    self.dry_run = True
    self.armed = False

  def _reset_counters(self):
    # gekauft = bisher gekaufte 200er-Stacks (Aktion 1).
    self.gekauft = 0
    self.hammer_remaining = 0
    self.splitter_summe = 0
    self.actions_done = 0
    self.consecutive_unverified = 0
    self._dolche_gekauft = 0
    self._buy_retries = 0
    self._npc_tries = 0
    # Render-Retry-Zaehler fuers Shop-Item-Suchen (Shop blendet ein).
    self._shop_locate_tries = 0
    # Render-Retry-Zaehler fuers Dialog-Oeffnen ('Laden oeffnen' erscheint).
    self._dialog_open_tries = 0
    # Wurde fuer DIESEN Lauf schon die volle Vogelperspektive gefahren
    # (Rechtsklick-Drag)? Einmal pro Lauf -- danach bleibt die Kamera top-down,
    # der Bot kann den Shop beliebig oft neu oeffnen ohne erneut zu kippen.
    self._did_birdseye = False
    # Wurde das Spiel-Fenster fuer diesen Lauf schon EINMAL in den Vordergrund
    # geholt? (Tasten brauchen Fokus -- sonst landet ein Tastendruck im Bot.)
    self._did_focus = False
    # Deadline (time.monotonic), bis zu der die Kamera nach einem
    # Vogelperspektive-Umschalten rendern darf -- bis dahin tut approach_npc
    # nichts (kein Screenshot/Klick), der naechste Tick prueft erneut. 0 = keine
    # Wartephase aktiv.
    self._npc_wait_until = 0.0
    # Dolch-Verarbeitung: Warteschlange der gekauften, noch nicht verarbeiteten
    # Dolch-Slots der aktuellen Runde (EINZELN nacheinander abgearbeitet).
    self._dagger_queue = []
    self._round_to_buy = 0
    # In DIESER Runde bestaetigt gekaufte Dolche (Modus-unabhaengig).
    self._round_bought = 0
    # Aufeinanderfolgende rate-limitierte/unklare Kaeufe DESSELBEN Dolchs.
    self._buy_rl_streak = 0
    # Fortschritts-Wache: splitter_summe zu Rundenbeginn + Zaehler der Runden ohne
    # jede Verarbeitung (-> evtl. kein Geld / leer) bis zum sauberen Stop.
    self._splitter_round_start = 0
    self._no_progress_rounds = 0
    # "Erst verarbeiten" wurde fuer DIESEN Lauf bereits abgearbeitet (einmalig,
    # bevor der Kauf-Ablauf startet).
    self._preprocess_done = False

  # -- 'scharf'-Schalter (bewusste Tester-Aktion, CONTRACT §2/§7) ----------
  # KANONISCHER Name fuer den bewussten Live-/scharf-Schalter. Default NICHT
  # scharf = Simulation/dry: alles erkennen + loggen, KEINE Maus. ``scharf`` ist
  # exakt die Umkehrung von ``dry_run`` (EINE Wahrheit, kein zweiter Riegel, der
  # auseinanderlaufen koennte): das erste echte Yang-Ausgeben verlangt ``dry_run
  # = False`` (UI-Entsicherung) UND ``armed`` (Phase-0-GATE) UND alle Backstops.
  @property
  def scharf(self):
    """``True`` nur, wenn der Bot bewusst entsichert ist (``not dry_run``)."""
    return not bool(self.dry_run)

  @scharf.setter
  def scharf(self, value):
    self.dry_run = not bool(value)

  # -- abort_fn-Seam (wie Manage v1.1.6) ----------------------------------
  def abort_fn(self):
    """``True`` wenn das injizierte Stop-Signal gesetzt ist.

    Seam, nicht Polling: run_loop ruft ``stop_signal.add_callback`` -- dieser
    Lesepfad spiegelt nur das Flag. Defensiv: ohne Signal -> nie abbrechen.
    """
    sig = self.stop_signal
    if sig is None:
      return False
    try:
      return bool(sig.stopped)
    except Exception:  # pragma: no cover - defensiv
      return False

  # -- set_to_begin (idempotent; friert Config ein; ruft phase0_gate) -----
  def set_to_begin(self, values):
    """Friert ALLE Config-Attribute aus ``values`` ein, RESETtet State +
    Zaehler, leitet ``max_actions`` ab und ruft den Phase-0-GATE (setzt
    ``self.armed``). Erzeugt ``wincap``. KEIN Klick.

    Idempotent re-aufrufbar (run_loop setzt ``self.mode`` vor dem Aufruf).
    Fehlt das Spiel-Fenster, wird ``self._stop_reason`` gesetzt; das Laufflag
    bleibt run_loop-gesteuert (botting setzt der RunLoop).
    """
    self._reset_counters()
    self.state = self.ST_INIT
    self._stop_reason = None
    self._missing = []

    self._freeze_config(values or {})

    # max_actions: 0 = UNBEGRENZT (Default). Der Dolch-Lauf ist bewusst
    # open-ended -- er laeuft Runde fuer Runde, bis die Hammer-Stacks im Beutel
    # aufgebraucht sind (flow_dagger: _count_hammers() <= 0 -> _stop('done')).
    # FRUEHER wurde 0 auf max(50, 3*stack_count) "auto-abgeleitet" -> das schnitt
    # den Lauf nach ~50 Aktionen ab (Bug: stack_count ist NICHT der Workload, und
    # bei daggers_per_round-Batches ist die Gesamtzahl ohnehin open-ended). Die
    # echten Backstops bleiben aktiv: Hammer-Erschoepfung ('done') +
    # consecutive_unverified_stop (Stuck-Schutz). Ein POSITIVER Wert bleibt als
    # harter Opt-in-Cap erhalten; Negatives -> 0 (unbegrenzt).
    if int(self.max_actions) < 0:
      self.max_actions = 0

    # wincap erzeugen -- Fenster fehlt -> Stop-Grund merken (kein Raise nach
    # aussen; run_loop steuert botting). WindowCapture wirft bei fehlendem HWND.
    self.wincap = None
    if _WindowCapture is not None:
      try:
        self.wincap = _WindowCapture(constants.GAME_NAME)
      except Exception:
        self.wincap = None
        self._stop_reason = 'no_window'

    self.phase0_gate()

  def _freeze_config(self, v):
    """Liest die -ES_*--Keys aus ``values`` (vom run_loop via
    apply_energiesplitter_config gelegt). Fehlt ein Key -> dokumentierter
    Default. Reine Wert-Uebernahme; Clamps macht validate.py (Eigentuemer C)."""
    def _get(key, default):
      val = v.get(key, default)
      return default if val is None else val

    self.stack_count = int(_get('-ES_STACK_COUNT-', 1))
    self.energie_freischalten = bool(_get('-ES_FREISCHALTEN-', True))
    self.daggers_per_round = int(_get('-ES_DAGGERS_PER_ROUND-', 20))
    self.mouse_pause = float(_get('-ES_MOUSE_PAUSE-', 0.05))
    self.keyboard_pause = float(_get('-ES_KB_PAUSE-', 0.10))
    self.speed_profile = str(_get('-ES_SPEED-', 'fast'))
    self.jitter_pct = float(_get('-ES_JITTER-', 0.15))
    mode = str(_get('-ES_BUY_MODE-', 'chat')).lower()
    self.buy_mode = mode if mode in ('chat', 'click') else 'chat'
    self.buy_delay_s = max(0.0, float(_get('-ES_BUY_DELAY_S-', 0.35)))
    self.process_first = bool(_get('-ES_PROCESS_FIRST-', False))
    # Verarbeiten-Tempo (Sek.) als Instanz-Override der Klassen-Defaults: Pause
    # zwischen Aufnehmen & Setzen (PICKUP_SETTLE_S) bzw. nach 'Ja' bis Re-Read
    # (BUY_CONFIRM_SETTLE_S). Default = aktueller Klassenwert -> Verhalten
    # unveraendert, wenn die Keys fehlen (Tests duerfen weiter direkt setzen).
    self.PICKUP_SETTLE_S = max(0.0, float(
        _get('-ES_PROC_PICKUP_S-', self.PICKUP_SETTLE_S)))
    self.BUY_CONFIRM_SETTLE_S = max(0.0, float(
        _get('-ES_PROC_CONFIRM_S-', self.BUY_CONFIRM_SETTLE_S)))
    self.max_actions = int(_get('-ES_MAX_ACTIONS-', 0))
    self.consecutive_unverified_stop = int(_get('-ES_UNVERIF_STOP-', 3))
    self.dry_run = bool(_get('-ES_DRY_RUN-', True))

  # -- Phase-0-GATE (harter Blocker, CONTRACT §2) -------------------------
  def phase0_gate(self):
    """Setzt ``self.armed`` = (Assets bereit AND 800x600-kalibriert AND
    Inventar-Raster aufloesbar). YANG spielt KEINE Rolle mehr.

    Delegiert die reine Pruefung an Agent A:
      1. ``detect.assets_ready(mode)`` -- Item-/NPC-Templates + Shop-Anker bereit.
      2. ``geometry.is_calibrated(wincap)`` -- Fenster ~800x600.
      3. ``detect.grid_present()`` -- Inventar-Raster (Slot 1 -> Pixel) aufloesbar
         (sichere Drag-/Slot-Ziele).
    Fehlt ein Modul (Build-Reihenfolge) ODER das Fenster ODER das Raster, bleibt
    ``armed=False`` und die Luecke landet in ``missing`` (sicher = rot). Liefert
    ``(armed, missing)`` und speichert ``self._missing``.

    Erkennung-vor-Aktion bleibt unveraendert (Kauf/Drag weiter nur auf Template-
    verifizierte Ziele); die OCR-unabhaengigen Backstops sind ``max_actions`` +
    ``consecutive_unverified_stop``.
    """
    missing = []

    mode = self.mode if self.mode in (MODE_HAMMER, MODE_DAGGER) else MODE_HAMMER

    # 1) Assets (Item-/NPC-Templates / Shop-Anker) -- via Agent A.
    if _detect is None or not hasattr(_detect, 'assets_ready'):
      missing.append('detect_module')
    else:
      try:
        _ready, miss = _detect.assets_ready(mode)
        if miss:
          missing.extend(list(miss))
      except Exception:
        missing.append('detect_error')

    # 2) Kalibrierung 800x600 -- via Agent A (IMMER gefordert, beide Modi).
    if _geometry is None or not hasattr(_geometry, 'is_calibrated'):
      missing.append('geometry_module')
    elif self.wincap is None:
      missing.append('calibration:800x600')
    else:
      try:
        if not _geometry.is_calibrated(self.wincap):
          missing.append('calibration:800x600')
      except Exception:
        missing.append('calibration:800x600')

    # 3) Inventar-Raster aufloesbar (sichere Drag-/Slot-Ziele).
    if not self._grid_calibrated():
      missing.append('grid_calibration')

    self._missing = missing
    self.armed = (len(missing) == 0)
    # GATE-Entscheidung strukturiert protokollieren (Wahrnehmung/Fehler): bei rot
    # die EXAKTE Liste der fehlenden Assets/Kalibrierungen -- der Tester sieht
    # sofort, WORAN es haengt. Absturzsicher.
    try:
      if self.armed:
        log.event(self.state, 'Phase-0-GATE: gruen (scharf erlaubt)', modus=mode)
      else:
        log.event(self.state, 'Phase-0-GATE: rot (kein Kauf/Drag)',
                  modus=mode, fehlend=', '.join(missing))
    except Exception:  # pragma: no cover - Logging darf das Gate nie kippen
      pass
    return self.armed, missing

  def _grid_calibrated(self):
    """``True``, wenn das Inventar-Raster aufloesbar ist (Slot 1 -> Pixel).

    Nutzt ``detect.grid_present`` (reiner Kalibrier-Check ueber
    ``calibration.slot_center``) -- garantiert sichere Drag-/Slot-Ziele.
    Defensiv ``False`` bei fehlendem Modul. Read-only, wirft nie."""
    if _detect is None or not hasattr(_detect, 'grid_present'):
      return False
    try:
      return bool(_detect.grid_present())
    except Exception:  # pragma: no cover - defensiv
      return False

  # -- Klartext-Diagnose der fehlenden Artefakte (Laien-Debug) ------------
  # Labels fuer die internen Tokens aus assets_ready ('item:hammer',
  # 'npc:alchemist', ...). So liest der Nutzer im Log "Alchemist nicht
  # erkennbar" statt "npc:alchemist".
  _MISSING_ITEM_LABELS = {'hammer': 'Hammer', 'dolch': 'Dolch'}
  _MISSING_NPC_LABELS = {'alchemist': 'Alchemist',
                         'waffenhaendler': 'Waffenhändler'}

  def _humanize_missing(self, missing):
    """Uebersetzt die internen ``missing``-Tokens in KLARE deutsche Saetze
    (welcher NPC/Item/Kalibrierung fehlt). Wirft nie -- ein unbekanntes Token
    wird als internes Artefakt gemeldet, nie verschluckt."""
    lines = []
    for tok in (missing or []):
      try:
        lines.append(self._humanize_token(str(tok)))
      except Exception:  # pragma: no cover - defensiv
        lines.append(str(tok))
    return lines

  def _humanize_token(self, tok):
    """Ein einzelnes missing-Token -> Klartext-Satz (i18n). Wirft nie."""
    if tok.startswith('item:'):
      name = tok.split(':', 1)[1]
      return t('energiesplitter.miss_item',
               item=self._MISSING_ITEM_LABELS.get(name, name))
    if tok.startswith('npc:'):
      name = tok.split(':', 1)[1]
      return t('energiesplitter.miss_npc',
               npc=self._MISSING_NPC_LABELS.get(name, name))
    if tok.startswith('calibration'):
      return t('energiesplitter.miss_calibration')
    if tok == 'grid_calibration':
      return t('energiesplitter.miss_grid')
    return t('energiesplitter.miss_internal', token=tok)

  # -- runHack: EIN blockierender Tick ------------------------------------
  def runHack(self):
    """Ein Tick: verzweigt nach ``self.mode``. Bei ``dry_run or not armed``
    nur Read-Only-Erkennung + Log + Selbst-Stop ("Phase-0 nicht bereit").
    Stoppt sich bei jeder Stop-Bedingung selbst (``self.botting=False``)."""
    if not self.botting:
      return

    # Abbruch-Seam (F6): hat Vorrang vor jeder teuren Aktion.
    if self.abort_fn():
      try:
        log.event(self.state, 'Abbruch-Signal (F6) erkannt -- stoppe vor jeder Aktion')
      except Exception:  # pragma: no cover
        pass
      self._stop('aborted')
      return

    # Fenster fehlte schon beim set_to_begin -> sauberer Stop, kein Klick.
    if self._stop_reason == 'no_window' or self.wincap is None:
      self._log_section()
      log.event('-', t('energiesplitter.no_window'))
      self._stop('no_window')
      return

    # PHASE-0-GATE: blockt VOR jeder Maus-/Tasten-Aktion (CONTRACT §2/§7).
    # (a) ECHTE Luecke (Asset/NPC/Fenster/Raster fehlt) -> harter Stop mit
    #     KLAREN Klartext-Gruenden (welcher NPC/Item/Kalibrierung) -- wie jede
    #     andere Bot-Methode: bei Fehler automatisch stoppen; F6 stoppt ebenso.
    if not self.armed:
      self._log_section()
      for line in self._humanize_missing(self._missing):
        log.event('-', line)
      log.event('-', t('energiesplitter.gate_red_hint'))
      self._stop('phase0_not_ready')
      return
    # (b) GATE gruen, aber SIMULATION (Schalter 'Scharf/Live' aus): NICHTS real
    #     tun -- klar melden, DASS + WIE man scharf schaltet, dann sauber stoppen
    #     (kein endloser Restart, kein verwirrendes "phase0_not_ready").
    if self.dry_run:
      self._log_section()
      log.event('-', t('energiesplitter.simulation_idle'))
      self._stop('simulation_idle')
      return

    # Scharfer Lauf: das Spiel-Fenster EINMAL pro Lauf in den Vordergrund holen,
    # damit Tasten (Vogelperspektive) sicher ankommen und der Lauf das Fenster
    # besitzt. Klicks aktivieren es ohnehin; Tasten NICHT (genau hier hakte es).
    if not self._did_focus:
      self._did_focus = True
      self._focus_game()

    # AFK-Dialog ("Du bist im AFK-Modus") blockiert alle Klicks/Tasten -> zuerst
    # wegklicken; dann erst (naechster Tick) normal weiter.
    if self._dismiss_afk_if_present():
      return

    # 'ZUSTAND: Tick' NUR loggen, wenn sich Zustand/Fortschritt aendert -- sonst
    # spammt der 10ms-Tick waehrend Wartephasen (z.B. Kamera-Settle) ~80 gleiche
    # Zeilen und das Log SIEHT eingefroren aus (Tester stoppte deshalb). Keine
    # Verhaltensaenderung, nur weniger Rauschen.
    _tick_sig = (self.state, self.actions_done, self.gekauft,
                 self.hammer_remaining)
    if _tick_sig != getattr(self, '_last_tick_sig', None):
      self._last_tick_sig = _tick_sig
      try:
        log.event(self.state, 'ZUSTAND: Tick', modus=self.mode,
                  actions_done=self.actions_done, gekauft=self.gekauft,
                  rest=self.hammer_remaining)
      except Exception:  # pragma: no cover
        pass
    # Verhalten UNVERAENDERT: ein unerwarteter Tick-Fehler wird protokolliert
    # (mit Traceback fuer den Tester) und dann RE-RAISED -- das Logging darf den
    # Fehler nicht verschlucken (das waere eine Verhaltensaenderung).
    try:
      if self.mode == MODE_HAMMER:
        self._tick_hammer()
      else:
        self._tick_dagger()
    except Exception as exc:
      try:
        log.error('FEHLER: unerwartete Ausnahme im Tick (Modus {}, State {})'.format(
            self.mode, self.state), exc=exc)
      except Exception:  # pragma: no cover - Logging selbst darf nie werfen
        pass
      raise

  # -- Selbst-Stop --------------------------------------------------------
  def _stop(self, reason):
    """Bilanz loggen, Cursor NICHT bewegen (kein Klick), botting=False."""
    self._stop_reason = reason
    try:
      log.event(self.state, t(
          'energiesplitter.done',
          hammers=self.gekauft, daggers=self._dolche_gekauft,
          splitters=self.splitter_summe, reason=reason))
    except Exception:  # pragma: no cover - Logging darf nie den Stop kippen
      pass
    self.state = self.ST_STOP
    self.botting = False

  def _log_section(self):
    key = ('energiesplitter.section_hammer' if self.mode == MODE_HAMMER
           else 'energiesplitter.section_dagger')
    try:
      log.section(t(key))
    except Exception:  # pragma: no cover
      pass
    # Volle aktive Konfiguration + Kalibrier-/Asset-Status EINMAL pro Lauf-Start
    # protokollieren (Zustand/Fortschritt D): der Tester sieht sofort, womit der
    # Bot startet -- Modus, Mengen, alle Safety-Backstops, scharf vs Simulation
    # UND ob der Phase-0-GATE gruen ist (sonst die fehlenden Artefakte). Reines
    # Logging, absturzsicher.
    self._log_config_state()

  def _log_config_state(self):
    """Loggt die eingefrorene Konfiguration + GATE-/Asset-Status. Wirft nie."""
    try:
      log.event(self.state, 'Konfiguration',
                modus=self.mode,
                betrieb=('SCHARF' if self.scharf else 'SIMULATION'),
                dry_run=self.dry_run,
                armed=self.armed,
                stack_count=self.stack_count,
                daggers_per_round=self.daggers_per_round,
                max_actions=(self.max_actions
                             if int(self.max_actions) > 0 else 'unbegrenzt'),
                unverif_stop=self.consecutive_unverified_stop,
                freischalten=self.energie_freischalten)
    except Exception:  # pragma: no cover - Logging darf nie den Lauf kippen
      pass
    try:
      if self.armed and not self._missing:
        log.event(self.state, 'GATE gruen -- alle Assets/Kalibrierung bereit')
      else:
        log.event(self.state, 'GATE rot -- es wird NICHT gekauft/gedraggt',
                  fehlend=(', '.join(self._missing) or 'dry_run'))
    except Exception:  # pragma: no cover
      pass

  # -- Backstops (OCR-unabhaengig, IMMER aktiv) ---------------------------
  def _action_cap_hit(self):
    """``True`` + Stop, wenn eine POSITIVE Aktions-Obergrenze erreicht ist.

    ``max_actions <= 0`` = UNBEGRENZT -> dieser Backstop stoppt NIE (der Lauf
    endet natuerlich bei Hammer-Erschoepfung; Stuck-Schutz via
    ``consecutive_unverified_stop``). Nur ein vom Nutzer gesetzter positiver
    Wert ist ein harter Cap."""
    if int(self.max_actions) > 0 and self.actions_done >= int(self.max_actions):
      log.event(self.state, t('energiesplitter.max_actions', n=self.max_actions))
      self._stop('max_actions')
      return True
    return False

  def _note_unverified(self):
    """Zaehlt eine nicht-verifizierte Aktion; stoppt bei N in Folge."""
    self.consecutive_unverified += 1
    if self.consecutive_unverified >= int(self.consecutive_unverified_stop):
      log.event(self.state, t('energiesplitter.buy_unverified',
                              retries=self.consecutive_unverified))
      self._stop('consecutive_unverified')
      return True
    return False

  # -- Read-Only-Helfer (defensiv; nie Raise) -----------------------------
  def _shot(self):
    try:
      return self.wincap.get_screenshot()
    except Exception:  # pragma: no cover - defensiv
      return None

  def _snapshot(self, name):
    bgr = self._shot()
    try:
      log.snapshot('energiesplitter_' + name, bgr=bgr)
    except Exception:  # pragma: no cover
      pass

  # -- Maus/Tasten (NUR erreichbar, wenn GATE gruen; jeder Pfad re-prueft) -
  def _guarded(self):
    """``True`` solange KEINE teure Aktion erlaubt ist (Gate/abort)."""
    return self.dry_run or not self.armed or self.abort_fn() or _input is None

  def _to_screen(self, x, y):
    ox = getattr(self.wincap, 'offset_x', 0) or 0
    oy = getattr(self.wincap, 'offset_y', 0) or 0
    return int(x + ox), int(y + oy)

  def _focus_game(self):
    """Holt das Spiel-Fenster in den VORDERGRUND (Tastatur-Fokus).

    NOETIG: ``pydirectinput``-TASTEN gehen ans fokussierte Fenster -- ohne Fokus
    landet z.B. die Vogelperspektive 'g' im Bot-Fenster und bewirkt im Spiel
    nichts. (Maus-Klicks aktivieren das Fenster ohnehin selbst.) Defensiv: ohne
    Modul/HWND ein No-op. Wirft NIE. Liefert ``True`` bei Erfolg."""
    if _focus_window is None:
      return False
    hwnd = getattr(self.wincap, 'hwnd', None)
    if not hwnd:
      return False
    try:
      ok = bool(_focus_window(hwnd))
      try:
        log.event(self.state,
                  'AKTION: Spiel-Fenster in den Vordergrund geholt (Fokus)',
                  erfolg=ok)
      except Exception:  # pragma: no cover
        pass
      return ok
    except Exception:  # pragma: no cover - defensiv
      return False

  def _ensure_inventory_open(self):
    """Stellt sicher, dass die TASCHE offen ist -- TEMPLATE-FREI ueber die
    periodische 32px-Slot-Struktur (``detect.inventory_open``), die OFFSET-
    TOLERANT ist und dieselbe live-bewaehrte Raster-Geometrie nutzt wie die
    Slot-Detektoren.

    Ersetzt die fruehere Angel-Tab-Template-Probe: die war am Live-Capture zu
    pixel-genau (schon wenige px DWM-/Fokus-Versatz schoben die Tab-Reihe aus der
    +-3px-Toleranz -> 0/4 -> faelschlich 'inventory_not_open', Live-Bug
    2026-06-20). Ist die Tasche zu, wird die Toggle-Taste gedrueckt und erneut
    geprueft (bis 3 Versuche).

    Rueckgabe: ``True`` weiter (offen verifiziert ODER Detektor headless nicht
    verfuegbar -> nicht blockieren), ``False`` = konnte nicht geoeffnet werden ->
    der Aufrufer bricht ab (der Bot hat sich bereits gestoppt). Wirft NIE."""
    if _detect is None or not hasattr(_detect, 'inventory_open'):
      return True  # headless/ohne Detektor: nicht blockieren (GATE deckt ab)
    tries = 3
    for attempt in range(tries):
      bgr = self._shot()
      try:
        is_open, score = _detect.inventory_open(bgr)
      except Exception:  # pragma: no cover - Probe-Fehler nie zum Stop eskalieren
        return True
      try:
        log.event(self.state, 'WAHRNEHMUNG: Inventar-Offen-Check (Slot-Periodik)',
                  offen=bool(is_open), score=round(float(score), 1),
                  schwelle=getattr(_detect, 'INVENTORY_OPEN_MIN', None),
                  hotkey=self.inventory_hotkey, versuch=attempt + 1)
      except Exception:  # pragma: no cover
        pass
      if is_open:
        return True
      if attempt < tries - 1:
        self._press_key(self.inventory_hotkey)   # Toggle-Taste -> erneut pruefen
        self._settle(self.SHOP_OPEN_SETTLE_S)    # Toggle rendern lassen
    try:
      log.event(self.state, t('energiesplitter.inventory_not_open'))
    except Exception:  # pragma: no cover
      pass
    self._stop('inventory_not_open')
    return False

  def _dismiss_afk_if_present(self):
    """Erkennt den zentrierten 'Du bist im AFK-Modus'-Dialog und klickt OK weg.

    Der AFK-Dialog blockiert ALLE Klicks/Tasten -- ohne Wegklicken kommt der Bot
    nie zum NPC/Inventar. Wird zu Beginn JEDES scharfen Ticks geprueft (er kann
    jederzeit auftauchen). Liefert ``True``, wenn ein Dialog erkannt + ein OK-
    Klick abgesetzt wurde (der Aufrufer ueberspringt dann den Rest dieses Ticks).
    Wirft NIE."""
    if _detect is None or not hasattr(_detect, 'afk_dialog_present'):
      return False
    bgr = self._shot()
    if bgr is None:
      return False
    try:
      present, center = _detect.afk_dialog_present(bgr)
    except Exception:  # pragma: no cover - defensiv
      return False
    if not present or center is None:
      return False
    try:
      log.event(self.state, 'AKTION: AFK-Dialog erkannt -> OK klicken', ziel=tuple(center))
    except Exception:  # pragma: no cover
      pass
    self._left_click(int(center[0]), int(center[1]))
    return True

  def _settle(self, seconds):
    """Kurze Renderpause (z.B. nach 'Laden oeffnen'/Seitenwechsel). Blockiert den
    Tick bewusst (wie jede Aktion); F6 wird am Tick-Kopf geprueft. Wirft NIE."""
    try:
      s = max(0.0, float(seconds))
      if s > 0:
        time.sleep(s)
    except Exception:  # pragma: no cover
      pass

  def _confirm_buy_if_present(self):
    """Klickt 'Ja' im Kauf-Bestaetigungsdialog ('Moechtest du ... kaufen?'),
    falls er erscheint (jeder Shop-Kauf in Metin2 fragt nach). Liefert ``True``,
    wenn bestaetigt wurde. KONTEXT-gegated: nur direkt nach einem Kauf-Klick
    aufgerufen. Wirft NIE."""
    if _detect is None or not hasattr(_detect, 'buy_confirm_present'):
      return False
    bgr = self._shot()
    if bgr is None:
      return False
    try:
      present, ja = _detect.buy_confirm_present(bgr)
    except Exception:  # pragma: no cover - defensiv
      return False
    if not present or ja is None:
      return False
    try:
      log.event(self.state, "AKTION: Kauf-Bestaetigung -> 'Ja' klicken", ziel=tuple(ja))
    except Exception:  # pragma: no cover
      pass
    self._left_click(int(ja[0]), int(ja[1]))
    return True

  def _confirm_dismantle_if_present(self):
    """Klickt 'Ja' im Zerlege-Bestaetigungsdialog ('Moechtest du das wirklich
    zerlegen?'), falls er nach dem Hammer->Dolch-Drag erscheint. Ohne dieses 'Ja'
    bleibt der Dolch unverarbeitet (-> faelschlich 'process_unverified'). Liefert
    ``True``, wenn bestaetigt wurde. KONTEXT-gegated: nur direkt nach dem
    Verarbeitungs-Drag aufgerufen. Wirft NIE."""
    if _detect is None or not hasattr(_detect, 'dismantle_confirm_present'):
      return False
    bgr = self._shot()
    if bgr is None:
      return False
    try:
      present, ja = _detect.dismantle_confirm_present(bgr)
    except Exception:  # pragma: no cover - defensiv
      return False
    if not present or ja is None:
      return False
    try:
      log.event(self.state, "AKTION: Zerlege-Bestaetigung -> 'Ja' klicken", ziel=tuple(ja))
    except Exception:  # pragma: no cover
      pass
    self._left_click(int(ja[0]), int(ja[1]))
    return True

  def _poll_confirm(self, check_fn, timeout_s=None):
    """Pollt bis ``check_fn()`` (Einzel-Check, der bei Erkennung 'Ja' klickt + True
    liefert) anschlaegt und gibt dann SOFORT True zurueck. Kein fixes Blind-Warten
    davor. False bei Timeout. ``check_fn`` liest pro Frame ein frisches Capture und
    klickt selbst -> hier nur die Schleife. Wirft NIE."""
    timeout = self.CONFIRM_POLL_TIMEOUT_S if timeout_s is None else timeout_s
    deadline = time.monotonic() + max(0.0, float(timeout))
    while True:
      try:
        if check_fn():
          return True
      except Exception:  # pragma: no cover - defensiv
        pass
      if time.monotonic() >= deadline:
        return False
      time.sleep(max(0.0, float(self.DETECT_POLL_INTERVAL_S)))

  def _confirm_buy_polled(self, timeout_s=None):
    """Kauf-Bestaetigung: pollt -> klickt 'Ja' SOFORT bei Erkennung (ersetzt das
    fixe BUY_CONFIRM_SETTLE_S-Blind-Warten). Wirft NIE."""
    return self._poll_confirm(self._confirm_buy_if_present, timeout_s)

  def _confirm_dismantle_polled(self, timeout_s=None):
    """Zerlege-Bestaetigung: pollt -> klickt 'Ja' SOFORT bei Erkennung. Wirft NIE."""
    return self._poll_confirm(self._confirm_dismantle_if_present, timeout_s)

  def _verify_buy(self, free_before):
    """Verifiziert EINEN Dolch-Kauf je nach Modus. Liefert:
      * ``'ok'``           -- Kauf erfolgreich (zaehlen, naechster Dolch),
      * ``'rate_limited'`` -- zu schnell gekauft (Backoff + denselben Dolch erneut),
      * ``'unknown'``      -- nicht gelandet, kein Rate-Limit erkannt (Backoff).

    ``click``-Modus: KEINE Erkennung -> immer ``'ok'`` (rein klickbasiert, Tempo
    haelt unter dem Limit; robust bei mehreren Inventarseiten).

    ``chat``-Modus: ERFOLG = ein Dolch ist GELANDET -> freie Slots auf Seite 1
    GESUNKEN ggue. ``free_before``. Das ist der robuste + schnelle Beleg (gekauft
    wird nur mit freiem Seite-1-Slot -> die Landung ist auf Seite 1 sichtbar),
    UNABHAENGIG vom fortlaufenden/identischen Chat. Landet binnen
    ``BUY_VERIFY_TIMEOUT_S`` nichts -> war der Kauf blockiert; der Chat wird dann
    nur noch gelesen, um 'rate_limited' (zu schnell) sauber zu loggen. Wirft NIE."""
    if self.buy_mode != 'chat':
      return 'ok'
    deadline = time.monotonic() + max(0.0, float(self.BUY_VERIFY_TIMEOUT_S))
    while True:
      try:
        if self._free_slot_count(quiet=True) < int(free_before):
          return 'ok'   # ein Dolch ist gelandet -> Kauf erfolgreich
      except Exception:  # pragma: no cover - defensiv
        pass
      if time.monotonic() >= deadline:
        break
      time.sleep(max(0.0, float(self.DETECT_POLL_INTERVAL_S)))
    # Nichts gelandet -> blockiert. Chat lesen, um Rate-Limit vs. unklar zu trennen
    # (Aktion ist in beiden Faellen Backoff+Retry; nur fuers Log getrennt).
    try:
      if _detect is not None and hasattr(_detect, 'chat_buy_result') \
          and _detect.chat_buy_result(self._shot()) == 'rate_limited':
        return 'rate_limited'
    except Exception:  # pragma: no cover - defensiv
      pass
    return 'unknown'

  def _close_shop(self):
    """Schliesst ein offenes Shop-/Dialogfenster (Taste ESC). NOETIG vor dem
    Dolch-Verarbeiten: nur bei GESCHLOSSENEM Waffenhaendler-Laden laesst sich ein
    Hammer auf einen Dolch ziehen (User-Grundwahrheit). Wirft NIE."""
    try:
      log.event(self.state, 'AKTION: Laden schliessen (ESC) vor Drag')
    except Exception:  # pragma: no cover
      pass
    self._press_key('esc')

  def _right_click(self, x, y):
    if self._guarded():
      return False
    sx, sy = self._to_screen(x, y)
    try:
      _input.PAUSE = self.mouse_pause
      _input.click(x=sx, y=sy, button='right')
      return True
    except Exception:  # pragma: no cover - defensiv
      return False

  def _left_click(self, x, y):
    if self._guarded():
      return False
    sx, sy = self._to_screen(x, y)
    try:
      _input.PAUSE = self.mouse_pause
      _input.click(x=sx, y=sy)
      return True
    except Exception:  # pragma: no cover
      return False

  def _press_key(self, key):
    if self._guarded():
      return False
    # Taste braucht FOKUS: erst das Spiel in den Vordergrund holen, sonst geht
    # der Tastendruck (z.B. Vogelperspektive 'g') ins Bot-Fenster ins Leere.
    self._focus_game()
    try:
      _input.PAUSE = self.keyboard_pause
      _input.keyDown(key)
      _input.keyUp(key)
      return True
    except Exception:  # pragma: no cover
      return False

  def _drag(self, x1, y1, x2, y2):
    """Drag NUR via wiederverwendetem inventory_discard.drag (A2, mouseUp im
    finally). Vor dem Aufruf Gate-Re-Check; abort wird NICHT mitten im Drag
    geprueft (erst danach), damit kein Button haengen bleibt."""
    if self._guarded() or _discard_drag is None:
      return False
    sx1, sy1 = self._to_screen(x1, y1)
    sx2, sy2 = self._to_screen(x2, y2)
    try:
      _discard_drag(_input, sx1, sy1, sx2, sy2)
      return True
    except Exception:  # pragma: no cover - drag garantiert mouseUp im finally
      return False

  def _two_click_move(self, x1, y1, x2, y2):
    """Verschiebt/wendet ein Item per ZWEI-KLICK an: Linksklick auf die Quelle
    (Item aufnehmen) -> kurze Pause -> Linksklick auf das Ziel (setzen/anwenden).

    User-Grundwahrheit: der Hammer ist KEIN Drag&Drop, sondern genau dieses
    Aufnehmen+Setzen; funktioniert auch ueber einen Seitenwechsel hinweg (Basis
    fuer Cross-Page-Verarbeitung). Ersetzt den frueheren ``_drag`` fuer den
    Hammer->Dolch-SLOT->SLOT-Move (sauberer, kein haengender Mausknopf). NUR fuer
    UI-Slot->UI-Slot -- NICHT fuer Slot->Welt-Wuerfe (dort bleibt Drag sicherer,
    weil ein Welt-Klick sonst die Figur laufen liesse). ``_left_click`` ist
    gate-/abort-geschuetzt. Liefert ``False`` bei gesperrtem Gate. Wirft NIE."""
    if self._guarded():
      return False
    self._left_click(int(x1), int(y1))     # Hammer aufnehmen
    self._settle(self.PICKUP_SETTLE_S)
    self._left_click(int(x2), int(y2))     # auf den Dolch setzen
    return True

  # -- gemeinsame Flow-Helfer (Detection von A) ---------------------------
  def _birdseye_drag(self):
    """Volle VOGELPERSPEKTIVE: Rechtsklick gedrueckt halten und die Maus IN EINEM
    RUTSCH ~25% der Client-Hoehe nach unten ziehen -> die Kamera kippt top-down.
    Erst dann ist der NPC-Klick zuverlaessig (User-Grundwahrheit). Garantiert
    ``mouseUp(right)`` im finally (nie Maustaste haengen lassen). Wirft NIE.

    Reine Mausgeste (kein Tastendruck mehr) -- ersetzt das fruehere 'g'-Toggle.
    """
    if self._guarded() or _input is None:
      return False
    self._focus_game()
    cx, cy = 400, 250                              # Bildmitte (links vom HUD ~625)
    dy = max(1, int(self.BIRDSEYE_DRAG_FRACTION * 600))   # 25% von 600 = 150 px
    sx, sy = self._to_screen(cx, cy)
    try:
      _input.PAUSE = self.mouse_pause
      _input.moveTo(sx, sy)
      _input.mouseDown(button='right')
      steps = 10                                   # sanft in einem Rutsch ziehen
      for i in range(1, steps + 1):
        _input.moveTo(sx, sy + (dy * i) // steps)
      return True
    except Exception:  # pragma: no cover - defensiv
      return False
    finally:
      try:
        _input.mouseUp(button='right')             # Maustaste IMMER loesen
      except Exception:  # pragma: no cover
        pass

  def approach_npc(self, npc_template_key):
    """Faehrt EINMAL pro Lauf die volle VOGELPERSPEKTIVE (Rechtsklick-Drag 25%
    runter) und sucht dann den gruenen NPC-Namen. Treffer -> Namens-Mitte (der
    Caller LINKSklickt sie -- erst top-down klappt das). Kein Treffer -> bounded
    Retries (Kamera nachziehen), dann sauberer Stop. Tick-getrieben (Rueckgabe
    ``None`` haelt ST_APPROACH_NPC; F6 am runHack-Kopf bleibt responsiv).
    """
    now = time.monotonic()
    if self._npc_wait_until and now < self._npc_wait_until:
      return None
    self._npc_wait_until = 0.0

    # (1) Vogelperspektive ZUERST (einmal pro Lauf), dann Kamera-Settle.
    if not self._did_birdseye:
      self._did_birdseye = True
      try:
        log.event(self.state, 'ABSICHT: Vogelperspektive -- Rechtsklick-Drag 25% nach unten')
      except Exception:  # pragma: no cover
        pass
      self._birdseye_drag()
      self._npc_wait_until = time.monotonic() + max(0.0, float(self.NPC_SETTLE_S))
      return None

    try:
      log.event(self.state, 'ABSICHT: NPC ansprechen', npc=npc_template_key,
                versuch=self._npc_tries, von=self.NPC_MAX_TRIES)
    except Exception:  # pragma: no cover
      pass
    bgr = self._shot()
    if bgr is None or _detect is None:
      log.event(self.state, t('energiesplitter.npc_not_found', npc=npc_template_key))
      self._stop('npc_not_found')
      return None
    tpl = self._template(npc_template_key)
    ok, pt, _ncc = (False, None, 0.0)
    try:
      ok, pt, _ncc = _detect.find_npc_name(bgr, tpl)
    except Exception:  # pragma: no cover - defensiv
      ok, pt = False, None
    try:
      log.event(self.state, 'WAHRNEHMUNG: NPC-Suche', npc=npc_template_key,
                gefunden=bool(ok and pt is not None), versuch=self._npc_tries,
                ncc=round(float(_ncc), 3), pos=(tuple(pt) if pt is not None else None))
    except Exception:  # pragma: no cover
      pass
    if ok and pt is not None:
      self._npc_tries = 0
      self._npc_wait_until = 0.0
      return pt
    # Miss: Kamera nochmal nachziehen + erneut suchen (bounded).
    if self._npc_tries < int(self.NPC_MAX_TRIES):
      self._npc_tries += 1
      try:
        log.event(self.state, 'WAHRNEHMUNG: NPC nicht gesehen -- Vogelperspektive nachziehen',
                  versuch=self._npc_tries, von=self.NPC_MAX_TRIES)
      except Exception:  # pragma: no cover
        pass
      self._birdseye_drag()
      self._npc_wait_until = time.monotonic() + max(0.0, float(self.NPC_SETTLE_S))
      return None
    log.event(self.state, t('energiesplitter.npc_not_found', npc=npc_template_key))
    self._stop('npc_not_found')
    return None

  def open_shop_via_dialog(self):
    """Findet die Dialogzeile 'Laden oeffnen' (Farb-NCC im Dialog-Optionen-Band,
    gegen alle Dialog-Bilder kalibriert: vorhanden >= 0.985, abwesend <= 0.36)
    und KLICKT sie. Danach kurze Settle-Zeit, damit der Shop rendert -- die
    eigentliche Shop-offen-Verifikation macht der naechste Zustand
    (``_locate_shop_item`` findet das Item NUR bei offenem Shop; sonst sauberer
    Stop ``item_not_in_shop``). KEIN fragiles fixes Header-Template (das Shop-
    Panel ist frei verschiebbar). Liefert ``True``, wenn geklickt wurde."""
    bgr = self._shot()
    if bgr is None or _detect is None or not hasattr(_detect, 'find_dialog_line'):
      self._snapshot('shop_not_open')
      log.event(self.state, t('energiesplitter.shop_not_open'))
      self._stop('shop_not_open')
      return False
    tpl = self._template('laden_oeffnen')
    ok, pt, ncc = (False, None, 0.0)
    try:
      ok, pt, ncc = _detect.find_dialog_line(bgr, tpl)
    except Exception:  # pragma: no cover
      ok, pt = False, None
    try:
      log.event(self.state, "WAHRNEHMUNG: Dialogzeile 'Laden oeffnen'",
                gefunden=bool(ok and pt is not None), ncc=round(float(ncc), 3),
                pos=(tuple(pt) if pt is not None else None))
    except Exception:  # pragma: no cover
      pass
    if not ok or pt is None:
      # 'Laden oeffnen' (noch) nicht da -> Dialog evtl. noch am Erscheinen:
      # mit Renderpause erneut versuchen, bevor aufgegeben wird.
      self._dialog_open_tries += 1
      if self._dialog_open_tries < int(self.DIALOG_OPEN_MAX_TRIES):
        log.event(self.state, "WAHRNEHMUNG: 'Laden oeffnen' noch nicht da -- warte + erneut",
                  versuch=self._dialog_open_tries, von=self.DIALOG_OPEN_MAX_TRIES,
                  ncc=round(float(ncc), 3))
        self._settle(self.DIALOG_SETTLE_S)
        return False   # bleibt in ST_OPEN_SHOP, naechster Tick sucht erneut
      self._snapshot('shop_not_open')
      log.event(self.state, t('energiesplitter.shop_not_open'))
      self._stop('shop_not_open')
      return False
    self._dialog_open_tries = 0
    try:
      log.event(self.state, "ABSICHT: 'Laden oeffnen' anklicken", ziel=tuple(pt))
    except Exception:  # pragma: no cover
      pass
    self._left_click(int(pt[0]), int(pt[1]))
    self._settle(self.SHOP_OPEN_SETTLE_S)   # Shop rendern lassen
    return True

  def verify_hammer_purchase(self, bag_before):
    """Verifiziert einen Hammer-Stack-Kauf per Re-Read: der Hammer-Bestand im
    Beutel ist nach dem Kauf gewachsen. YANG wird NICHT gelesen.

    ``bag_before`` = gemessener Hammer-Bestand VOR dem Kauf (oder ``None``, wenn
    nicht messbar). Liefert ``True``, wenn der Bestand nachweislich gewachsen ist
    (``_verify_bag_growth`` erwartet >= 1 Slot Zuwachs durch den 200er-Stack);
    ist der Bag-Stack NICHT messbar (Phase-0-Stub), gilt der Kauf als belegt
    (``True``) -- der GATE haelt scharfe Laeufe ohne Live-Asset ohnehin zurueck.
    Reine Lese-Pruefung -- kein Klick. Wirft nie."""
    ok = bool(self._verify_bag_growth(bag_before, 1))
    try:
      log.event(self.state, 'WAHRNEHMUNG: Hammer-Kauf-Verifikation (Re-Read)',
                bag_vorher=bag_before, bag_messbar=self._bag_count_measurable(),
                verifiziert=bool(ok))
    except Exception:  # pragma: no cover
      pass
    return ok

  def verify_process(self, before_bgr, after_bgr):
    """Verifiziert die 1:1-Verarbeitung NACH der neuen Grundwahrheit (User
    2026-06-15): es gibt **KEIN Bestaetigungsfenster** -- der Erfolg wird NICHT
    am Splitter-Aussehen festgemacht (das ist unbeobachtbar), sondern an zwei
    re-gelesenen Inventar-Tatsachen:

      1. der gerade gefuellte **Dolch-Slot ist jetzt LEER** (Dolch verbraucht), UND
      2. der **Hammer-Bestand ist um genau 1 gesunken** (Hammer verbraucht).

    Liefert ``1`` bei verifizierter Verarbeitung, sonst ``0`` (der Caller
    dekrementiert NUR bei ``> 0`` -- R5). Read-only, kein Klick, wirft nie.

    Rueckwaerts-kompatibel: ist eine ``read_splitter_growth``-Messung verfuegbar
    und positiv (Live-Asset P0.5 spaeter), zaehlt auch das als Beleg.
    """
    if _detect is None:
      return 0
    after = after_bgr if after_bgr is not None else self._shot()

    # (1) Ziel-Dolch-Slot jetzt leer? (Dolch verbraucht.)
    slot = getattr(self, '_dolch_inv_slot', None)
    slot_emptied = self._slot_is_empty(slot, after) if slot is not None else False

    # (2) Hammer-Bestand um 1 gesunken? (Hammer verbraucht.) NUR erzwungen,
    # wenn der Bag-Stack real messbar ist (sonst traegt der Dolch-Slot-Beleg
    # allein -- der GATE haelt scharfe Laeufe ohne Live-Assets ohnehin zurueck).
    before_n = getattr(self, '_hammer_count_before_proc', None)
    if self._bag_count_measurable() and before_n is not None:
      now_n = self._count_hammers()
      hammer_dropped = (now_n is not None and now_n == before_n - 1)
    else:
      hammer_dropped = True  # nicht messbar -> kein blockierender Zusatz-Riegel

    try:
      log.event(self.state, 'WAHRNEHMUNG: Verarbeitungs-Verifikation (Re-Read)',
                dolch_slot_leer=bool(slot_emptied),
                hammer_dekrementiert=bool(hammer_dropped),
                bag_messbar=self._bag_count_measurable(),
                hammer_vorher=before_n)
    except Exception:  # pragma: no cover
      pass
    if slot_emptied and hammer_dropped:
      return 1

    # Optionaler Zusatz-Beleg (P0.5): echter Splitter-Zuwachs, falls messbar.
    try:
      if before_bgr is not None and after is not None:
        growth = int(_detect.read_splitter_growth(before_bgr, after))
        if growth > 0 and (slot_emptied or hammer_dropped):
          try:
            log.event(self.state, 'WAHRNEHMUNG: Splitter-Zuwachs als Zusatz-Beleg',
                      zuwachs=growth)
          except Exception:  # pragma: no cover
            pass
          return 1
    except Exception:  # pragma: no cover
      pass
    return 0

  # -- NPC-Selektion / Dialog (gemeinsam) ---------------------------------
  def _select_npc(self, pt):
    """NPC ANSPRECHEN: LINKSklick MITTIG auf den gefundenen gruenen Namen.

    Das ist der sichere Weg, einen NPC anzusprechen (User-Grundwahrheit): ein
    LINKSklick auf den Namen oeffnet den Dialog. Rechtsklick = anvisieren/
    angreifen -- NICHT ansprechen (darum hier bewusst NICHT mehr). ``pt`` ist die
    Namens-Mitte aus ``find_npc_name`` (die Vogelperspektive in ``approach_npc``
    laeuft davor, falls der Name sonst nicht sichtbar ist). Liefert ``True``
    (Klick abgesetzt) oder ``False`` (kein Punkt -> Stop)."""
    if pt is None:
      self._stop('select_failed')
      return False
    try:
      log.event(self.state, 'ABSICHT: NPC ansprechen -- LINKSklick MITTIG auf den Namen',
                ziel=tuple(pt))
    except Exception:  # pragma: no cover
      pass
    self._left_click(int(pt[0]), int(pt[1]))
    # Dem NPC-Dialog ZEIT zum Erscheinen geben, BEVOR nach 'Laden oeffnen'
    # gesucht wird (sonst lief die Suche ~30ms nach dem Klick ins Leere).
    self._settle(self.DIALOG_SETTLE_S)
    return True

  def _open_dialog(self, pt):
    """Beobachtet NACH dem Ansprechen den Dialog-Zustand. KEIN weiterer Klick
    (der Linksklick auf den Namen in ``_select_npc`` oeffnet den Dialog bereits).

    Ist die Dialog-Erkennung (noch) nicht kalibriert (kein Template -> ``None``),
    wird NICHT blind gestoppt, sondern mit klarem Log fortgefahren -- der Shop-
    Schritt verifiziert anschliessend hart. Liefert ``True`` (weiter)."""
    bgr = self._shot()
    ds = self._dialog_state_of(bgr) if bgr is not None else None
    try:
      log.event(self.state, 'WAHRNEHMUNG: Dialog-Zustand', zustand=ds,
                energie_freischalt_option=(ds == 'locked'))
    except Exception:  # pragma: no cover
      pass
    if ds is None:
      try:
        log.event(self.state, 'HINWEIS: Dialog-Erkennung noch nicht kalibriert '
                  '(kein Template) -- fahre fort, Shop-Schritt verifiziert')
      except Exception:  # pragma: no cover
        pass
    return True

  def _dialog_state(self):
    bgr = self._shot()
    return self._dialog_state_of(bgr) if bgr is not None else None

  def _dialog_state_of(self, bgr):
    if _detect is None or bgr is None:
      return None
    try:
      return _detect.dialog_state(bgr)
    except Exception:  # pragma: no cover
      return None

  def _click_story_buttons(self):
    """Klickt die freigegebenen Story-Buttons (Weiter/Weiter/OK) sofern A sie
    findet. Negativliste wird von A nie als klickbar geliefert."""
    for key in ('weiter', 'weiter', 'ok'):
      bgr = self._shot()
      if bgr is None or _detect is None:
        return
      tpl = self._template(key)
      try:
        ok, pt, _ncc = _detect.find_shop_item(bgr, tpl)
      except Exception:  # pragma: no cover
        ok, pt = False, None
      try:
        log.event(self.state, 'WAHRNEHMUNG: Story-Button', button=key,
                  gefunden=bool(ok and pt is not None),
                  pos=(tuple(pt) if pt is not None else None))
      except Exception:  # pragma: no cover
        pass
      if ok and pt is not None:
        try:
          log.event(self.state, 'ABSICHT: Story-Button klicken', button=key,
                    ziel=tuple(pt))
        except Exception:  # pragma: no cover
          pass
        self._left_click(pt[0], pt[1])
