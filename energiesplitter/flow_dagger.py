# -*- coding: utf-8 -*-
"""Dolch-Modus-State-Maschine (Aktion 2 @ Waffenhaendler) als Mixin.

Mechanik (User-Grundwahrheit 2026-06-16): EIN Drag eines Hammer-STACKS auf einen
Dolch verbraucht 1 Hammer + 1 Dolch (NICHT den ganzen Stack). Ablauf:

  Schleife bis keine Haemmer mehr im Inventar:
    1. ``daggers_per_round`` Dolche am Waffenhaendler kaufen (template-verifiziert,
       Rechtsklick je Dolch) -> Lande-Slots sammeln.
    2. Die gekauften Dolche EINZELN NACHEINANDER verarbeiten: fuer JEDEN Dolch den
       Hammer-STACK-Slot (Template=Hammer) auf den Dolch-Slot (Template=Dolch)
       ziehen. Der Drag oeffnet ein ZERLEGE-Bestaetigungsfenster ('Moechtest du
       das wirklich zerlegen?') -> 'Ja' klicken (wie der Kauf-Confirm), danach
       Re-Read-Verifikation (Dolch weg + Hammer dekrementiert). Erkennung-vor-
       Aktion (src=Hammer, dst=Dolch live verifiziert) bleibt zwingend.

YANG spielt keine Rolle. Diese Methoden werden per Mehrfachvererbung Teil von
:class:`energiesplitter.bot.EnergiesplitterBot`; sie operieren auf der Bot-
Instanz (``self``).
"""

from debuglog import log
from i18n import t


class DaggerFlowMixin:
  """Dolch-Kauf + sequenzielle Verarbeitung (siehe Modul-Docstring, CONTRACT §1)."""

  def _tick_dagger(self):
    st = self.state
    if st == self.ST_INIT:
      self._log_section()
      log.event(st, t('energiesplitter.started', mode=self.mode))
      self.state = self.ST_INVENTORY_BASE
      return

    if st == self.ST_INVENTORY_BASE:
      # ZUERST Tasche offen sicherstellen (bewaehrte open_probe-Logik) -- sonst
      # liest der Hammer-Bestands-Scan auf geschlossener Tasche 0.
      if not self._ensure_inventory_open():
        return  # hat sich selbst gestoppt
      if not self._item_template_ready('hammer'):
        log.event(st, t('energiesplitter.item_template_missing', item='hammer'))
        self._stop('item_template_missing')
        return
      if not self._item_template_ready('dolch'):
        log.event(st, t('energiesplitter.item_template_missing', item='dolch'))
        self._stop('item_template_missing')
        return
      self.hammer_remaining = self._count_hammers()
      if self.hammer_remaining <= 0:
        self._stop('done')
        return
      # "Erst verarbeiten": vor dem Kauf zuerst die bereits auf Seite 1
      # liegenden Dolche abarbeiten (einmal pro Lauf). Sonst direkt zum Kauf.
      if self.process_first and not self._preprocess_done:
        self.state = self.ST_PREPROCESS
      else:
        self.state = self.ST_APPROACH_NPC
      return

    if st == self.ST_PREPROCESS:
      # Scannt Seite 1 (die offene Tasche) und verarbeitet ALLE dort sicher als
      # Dolch erkannten Slots EINZELN -- NUR Dolche (template-verifiziert), nie
      # ein Fremd-Item -> BEVOR der Kauf-Mechanismus startet. Die eigentliche
      # Verarbeitung laeuft ueber die bestehende ST_PROCESS_DRAG/ST_VERIFY_PROCESS-
      # Maschinerie; ist die Queue leer, fuehrt ST_RESCAN automatisch zum Kauf
      # (ST_APPROACH_NPC) bzw. zu 'done'. Einmal pro Lauf (_preprocess_done).
      self._preprocess_done = True
      if not self._ensure_inventory_open():
        return  # hat sich selbst gestoppt
      slots = self._all_dolch_slots()
      if not slots:
        log.event(st, 'ZUSTAND: keine vorhandenen Dolche auf Seite 1 '
                  '-> direkt zum Kauf')
        self.state = self.ST_APPROACH_NPC
        return
      self._dagger_queue = list(slots)
      self._dolch_inv_slot = self._dagger_queue.pop(0)
      self._splitter_round_start = self.splitter_summe
      log.event(st, 'ZUSTAND: erst vorhandene Dolche verarbeiten '
                '(Seite 1, KEIN Kauf)', anzahl=len(slots))
      self.state = self.ST_PROCESS_DRAG
      return

    if st == self.ST_APPROACH_NPC:
      pt = self.approach_npc('waffenhaendler')
      if pt is None:
        return
      self._npc_pt = pt
      self.state = self.ST_SELECT_NPC
      return

    if st == self.ST_SELECT_NPC:
      if not self._select_npc(self._npc_pt):
        return
      self.state = self.ST_OPEN_DIALOG
      return

    if st == self.ST_OPEN_DIALOG:
      if not self._open_dialog(self._npc_pt):
        return
      self.state = self.ST_OPEN_SHOP
      return

    if st == self.ST_OPEN_SHOP:
      if not self.open_shop_via_dialog():
        return
      # HINWEIS: der fruehere _ensure_bag_open()-Doppelcheck (panel_is_bag) ist
      # ENTFERNT -- sein Marker-Template ist nicht kalibriert -> lieferte IMMER
      # False -> Stop 'bag_not_open' (genau der Tester-Fall). Die Tasche ist
      # bereits am ST_INVENTORY_BASE ueber die bewaehrte open_probe verifiziert.
      self.state = self.ST_LOCATE_DOLCH
      return

    if st == self.ST_LOCATE_DOLCH:
      slot = self._locate_shop_item('dolch')
      if slot is None:
        # Shop blendet evtl. noch ein -> mit Renderpause erneut versuchen.
        self._shop_locate_tries += 1
        if self._shop_locate_tries < int(self.SHOP_LOCATE_MAX_TRIES):
          log.event(st, 'WAHRNEHMUNG: Dolch noch nicht im Shop -- warte (Render) + erneut',
                    versuch=self._shop_locate_tries, von=self.SHOP_LOCATE_MAX_TRIES)
          self._settle(self.SHOP_OPEN_SETTLE_S)
          return
        log.event(st, t('energiesplitter.item_not_in_shop', item='dolch'))
        self._stop('item_not_in_shop')
        return
      self._shop_locate_tries = 0
      self._dolch_shop_slot = slot
      # Neue Runde: Kauf-Zaehler + Warteschlange + Runden-Marker ruecksetzen.
      self._round_to_buy = max(1, int(self.daggers_per_round))
      self._dagger_queue = []
      self._round_bought = 0
      self._buy_rl_streak = 0
      self._splitter_round_start = self.splitter_summe
      self.state = self.ST_BUY_ONE_DOLCH
      return

    if st == self.ST_BUY_ONE_DOLCH:
      self._dagger_buy_one()
      return

    if st == self.ST_PROCESS_DRAG:
      self._dagger_process_drag()
      return

    if st == self.ST_VERIFY_PROCESS:
      self._dagger_verify_process()
      return

    if st == self.ST_RESCAN:
      # Eine Runde ist abgearbeitet (Laden ist nach dem Drag GESCHLOSSEN) ->
      # Hammer-Bestand neu lesen. Sind noch Haemmer da: NAECHSTE RUNDE -> NPC
      # erneut ansprechen + Laden NEU oeffnen (ST_APPROACH_NPC; die
      # Vogelperspektive bleibt, _did_birdseye verhindert ein erneutes Kippen),
      # sonst fertig.
      # Fortschritts-Wache: hat diese Runde ueberhaupt etwas verarbeitet
      # (splitter_summe gewachsen)? N Runden IN FOLGE ohne Fortschritt -> sauberer
      # Stop (evtl. kein Geld/Yang mehr ODER nichts mehr kaufbar) statt Endlos-
      # schleife "kaufen scheitert -> nichts verarbeitet -> erneut".
      if self.splitter_summe > self._splitter_round_start:
        self._no_progress_rounds = 0
      else:
        self._no_progress_rounds += 1
      if self._no_progress_rounds >= int(self.NO_PROGRESS_ROUNDS_MAX):
        log.event(self.state, 'WAHRNEHMUNG: mehrere Runden ohne Verarbeitung '
                  '-> Stop (evtl. kein Geld/Yang mehr oder nichts kaufbar)',
                  runden=self._no_progress_rounds)
        self._stop('no_progress')
        return
      self.hammer_remaining = self._count_hammers()
      if self.hammer_remaining > 0:
        self.state = self.ST_APPROACH_NPC
      else:
        self._stop('done')
      return

    self._stop('unknown_state')

  def _dagger_buy_one(self):
    """Kauft GENAU 1 Dolch (Rechtsklick) und verifiziert ihn je nach ``buy_mode``:

      * ``'chat'``  (Default): die Chat-Quittung lesen (Vorher/Nachher -> neueste
        Zeile). 'X Yang ausgegeben' = Erfolg; 'Bitte spaeter erneut' = Rate-Limit.
      * ``'click'``          : rein klickbasiert mit Tempo-Delay, KEINE Erkennung
        (robust bei mehreren Inventarseiten -- ein Inventar-Diff waere dort unzu-
        verlaessig).

    Ein rate-limitierter Kauf ist KEIN Fehler-Stop mehr: Backoff (``buy_delay_s``)
    + denselben Dolch erneut (das Limit ist transient). Die Verarbeitung holt sich
    die realen Dolch-Slots per SCAN -> kein per-Kauf-Lande-Slot noetig."""
    if self._action_cap_hit():
      return
    if self._round_to_buy <= 0:
      self._start_processing_queue()
      return

    # Tasche-voll-Schutz: kein freier Slot -> schon Gekauftes JETZT verarbeiten
    # (Zerlegen schafft Platz). Noch nichts gekauft -> ehrlicher no_space-Stop.
    if not self._has_free_slot():
      if self._round_bought > 0:
        log.event(self.state, 'ZUSTAND: Tasche voll -> Runde vorzeitig verarbeiten',
                  gekauft_runde=self._round_bought, rest_runde=self._round_to_buy)
        self._round_to_buy = 0
        self._start_processing_queue()
      else:
        log.event(self.state, t('energiesplitter.no_space'))
        self._stop('no_space')
      return

    try:
      verb = ('[SIM] wuerde' if not self.scharf else 'SCHARF:')
      log.event(self.state, verb + ' GENAU 1 Dolch kaufen',
                rest_runde=self._round_to_buy, hammer_rest=self.hammer_remaining,
                dolche_gekauft=self._dolche_gekauft, modus=self.buy_mode)
    except Exception:  # pragma: no cover
      pass

    # ERKENNUNG VOR AKTION (pro Kauf): Shop-Dolch JEDESMAL neu lokalisieren.
    slot = self._locate_shop_item('dolch')
    if slot is None:
      slot = getattr(self, '_dolch_shop_slot', None)
    if slot is None:
      log.event(self.state, t('energiesplitter.item_not_in_shop', item='dolch'))
      self._stop('item_not_in_shop')
      return
    self._dolch_shop_slot = slot

    # Chat-Modus: freie Slots VOR dem Kauf merken -> Erfolg = Dolch gelandet
    # (freie Slots gesunken). Schnell + robust, unabhaengig vom Chat-Wirrwarr.
    free_before = self._free_slot_count() if self.buy_mode == 'chat' else 0
    try:
      verb = ('[SIM] wuerde' if self._guarded() else 'SCHARF:')
      log.event(self.state, verb + ' Dolch rechtsklicken (Kauf)', ziel=tuple(slot))
    except Exception:  # pragma: no cover
      pass
    self._right_click(*slot)
    self.actions_done += 1
    # Kauf-Bestaetigung: EINMAL pruefen + 'Ja' falls vorhanden. Der Dolch-Kauf
    # zeigt KEIN Bestaetigungsfenster (nur das Zerlegen tut das) -> hier KEIN
    # Poll-Spin (der wuerde sonst pro Kauf bis zum Timeout ins Leere drehen).
    self._confirm_buy_if_present()

    result = self._verify_buy(free_before)
    if result in ('rate_limited', 'unknown'):
      # Zu schnell / keine Quittung -> Backoff, NICHT zaehlen, denselben Dolch
      # erneut (Rate-Limit ist transient -> KEIN harter Stop).
      self._buy_rl_streak += 1
      try:
        log.event(self.state, 'WAHRNEHMUNG: Kauf nicht bestaetigt -> Backoff + erneut',
                  grund=result, streak=self._buy_rl_streak, modus=self.buy_mode)
      except Exception:  # pragma: no cover
        pass
      self._settle(self.buy_delay_s)
      if self._buy_rl_streak >= int(self.BUY_RATELIMIT_MAX):
        # Dauer-Fehlschlag -> nicht ewig denselben Dolch klicken: das bisher
        # Gekaufte verarbeiten (die Fortschritts-Wache in ST_RESCAN stoppt sauber,
        # falls auch ueber Runden NICHTS verarbeitet wird = evtl. kein Geld).
        log.event(self.state, 'WAHRNEHMUNG: Kauf wiederholt nicht bestaetigt '
                  '-> verarbeite bisher Gekauftes', streak=self._buy_rl_streak)
        self._buy_rl_streak = 0
        self._round_to_buy = 0
        self._start_processing_queue()
      return

    # 'ok' (Chat-Quittung) ODER klick-Modus -> als gekauft zaehlen.
    self._buy_rl_streak = 0
    self.consecutive_unverified = 0
    self._round_bought += 1
    self._dolche_gekauft += 1
    self._round_to_buy -= 1
    # Kauf-Tempo: Pause vor dem naechsten Kaufklick -- in BEIDEN Modi wirksam,
    # damit das Feld auch im Chat-Modus den Klick-Takt steuert (0 = max. schnell;
    # gegen das Server-Rate-Limit ggf. leicht erhoehen).
    self._settle(self.buy_delay_s)
    try:
      log.event(self.state, 'ZUSTAND: Dolch gekauft', rest_runde=self._round_to_buy,
                dolche_gekauft=self._dolche_gekauft, modus=self.buy_mode)
    except Exception:  # pragma: no cover
      pass
    if self._round_to_buy <= 0:
      self._start_processing_queue()
    # sonst: naechster Dolch wird im naechsten Tick gekauft.

  def _start_processing_queue(self):
    """Beginnt die Verarbeitung: schliesst den Laden (ein Hammer laesst sich nur
    bei GESCHLOSSENEM Laden auf einen Dolch ziehen) und holt die real vorhandenen
    Dolch-Slots per SCAN (Ground-Truth -- unabhaengig vom Kauf-Zaehler/Inventar-
    seite). Nichts zu verarbeiten -> Hammer-Recheck (ST_RESCAN)."""
    self._close_shop()                       # Laden zu -> Drag erlaubt
    self._settle(self.SHOP_OPEN_SETTLE_S)     # Schliessen rendern lassen
    # NUR sicher als Dolch erkannte Slots (nie ein Fremd-Item). Scan = Wahrheit.
    all_dolch = self._all_dolch_slots()
    if all_dolch:
      self._dagger_queue = list(all_dolch)
    if not self._dagger_queue:
      self.state = self.ST_RESCAN
      return
    self._dolch_inv_slot = self._dagger_queue.pop(0)
    self.state = self.ST_PROCESS_DRAG

  def _dagger_process_drag(self):
    """Drag 1 Hammer-STACK -> verifizierter Dolch-Slot (verbraucht 1 Hammer + 1
    Dolch). NUR wenn Quelle=Hammer UND Ziel=Dolch (beide Template-positiv). Sonst
    Stop, KEIN Drag (R11)."""
    if self._action_cap_hit():
      return
    src = self._classified_hammer_slot()
    dst_ok = self._slot_is('dolch', self._dolch_inv_slot)
    try:
      log.event(self.state, 'WAHRNEHMUNG: Slot-Klassifikation vor Drag',
                src_hammer=(src is not None),
                src_slot=(tuple(src) if isinstance(src, (tuple, list)) else src),
                dst_dolch=bool(dst_ok),
                dst_slot=(tuple(self._dolch_inv_slot)
                          if isinstance(self._dolch_inv_slot, (tuple, list))
                          else self._dolch_inv_slot))
    except Exception:  # pragma: no cover
      pass
    if src is None or not dst_ok:
      try:
        log.event(self.state, 'FEHLER: Drag unsicher -- '
                  + ('Quelle NICHT Hammer ' if src is None else '')
                  + ('Ziel NICHT Dolch' if not dst_ok else ''))
      except Exception:  # pragma: no cover
        pass
      log.event(self.state, t('energiesplitter.drag_unsafe'))
      self._stop('drag_unsafe')
      return

    # Re-Read-Anker fuer die Verifikation: Hammer-Bestand VOR dem Drag merken ->
    # nach Drag + Zerlege-Bestaetigung muss er um genau 1 gesunken sein (Hammer
    # verbraucht), zusaetzlich zum jetzt-leeren Dolch-Slot.
    self._before_proc = self._shot()
    self._hammer_count_before_proc = self._count_hammers()
    sx, sy = self._slot_center(src)
    dx, dy = self._slot_center(self._dolch_inv_slot)
    try:
      verb = ('[SIM] wuerde' if self._guarded() else 'SCHARF:')
      log.event(self.state, verb + ' Dolch verarbeiten -- Hammer aufnehmen + auf Dolch setzen (Zwei-Klick)',
                von=(sx, sy), nach=(dx, dy),
                hammer_vor_aktion=self._hammer_count_before_proc)
    except Exception:  # pragma: no cover
      pass
    # ZWEI-KLICK statt Drag (User-Grundwahrheit): Linksklick Hammer (aufnehmen) +
    # Linksklick Dolch (setzen). Slot->Slot in der Tasche -> sicher (kein Welt-
    # Klick). Basis fuer die geplante Cross-Page-Verarbeitung.
    self._two_click_move(sx, sy, dx, dy)
    self.actions_done += 1
    # Das Setzen oeffnet das Zerlege-Bestaetigungsfenster ('Moechtest du das
    # wirklich zerlegen?') -> 'Ja'. POLL-INSTANT (Erkennung -> sofort klicken;
    # kein fixes Vor-Warten). Danach KURZ rendern lassen, damit der Verify-Re-Read
    # den jetzt geleerten Dolch-Slot sieht.
    self._confirm_dismantle_polled()
    self._settle(self.BUY_CONFIRM_SETTLE_S)
    self.state = self.ST_VERIFY_PROCESS

  def _dagger_verify_process(self):
    """Verifiziert die Verarbeitung per Re-Read (nach Drag + Zerlege-'Ja'):
    ``verify_process`` belegt den Erfolg (Dolch-Slot jetzt LEER UND Hammer-Bestand
    um 1 gesunken) und liefert ``> 0`` nur dann. NUR bei positivem Beleg wird
    dekrementiert (R5). Danach den NAECHSTEN Dolch der Runde verarbeiten (Queue),
    sonst zurueck zum Hammer-Re-Scan."""
    after = self._shot()
    processed = self.verify_process(self._before_proc, after)
    if processed > 0:
      self.splitter_summe += processed
      self.hammer_remaining -= 1
      self.consecutive_unverified = 0
      log.event(self.state, t(
          'energiesplitter.processed', value=processed,
          sum=self.splitter_summe, rest=self.hammer_remaining))
      # HINWEIS: Frueher stand hier ein Anti-Drift-Riegel
      # ``if self._dolche_gekauft - self.splitter_summe > PROCESS_DRIFT_MAX: stop``.
      # Der war FALSCH fuer Batch-Kauf: bei daggers_per_round=20 ist nach dem 1.
      # Verarbeiten gekauft=20, summe=1 -> 19 > 2 -> sofortiger Fehl-Stop
      # ('kauft 20, verarbeitet 1, stoppt'). Entfernt. Echte Drift (Verarbeitung
      # schlaegt wirklich fehl) faengt der else-Zweig unten ueber
      # ``_note_unverified`` (Stop nach ``consecutive_unverified_stop`` Fehlern IN
      # FOLGE; ein Erfolg setzt den Zaehler zurueck) -- korrekt fuer jede Runden-
      # groesse.
      # Naechsten Dolch der Runde verarbeiten, falls die Queue noch welche hat.
      if self._dagger_queue:
        self._dolch_inv_slot = self._dagger_queue.pop(0)
        self.state = self.ST_PROCESS_DRAG
      else:
        self.state = self.ST_RESCAN
    else:
      if not self._note_unverified():
        log.event(self.state, t('energiesplitter.process_unverified'))
        self._stop('process_unverified')
