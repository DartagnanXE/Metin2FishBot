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
      self.state = self.ST_APPROACH_NPC
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
      # Neue Runde: Dolch-Kauf-Zaehler dieser Runde + Warteschlange ruecksetzen.
      self._round_to_buy = max(1, int(self.daggers_per_round))
      self._dagger_queue = []
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
      self.hammer_remaining = self._count_hammers()
      if self.hammer_remaining > 0:
        self.state = self.ST_APPROACH_NPC
      else:
        self._stop('done')
      return

    self._stop('unknown_state')

  def _dagger_buy_one(self):
    """Kauft GENAU 1 Dolch (Rechtsklick), bestimmt den realen Lande-Slot per Diff
    und legt ihn in die Verarbeitungs-Warteschlange. Sind ``daggers_per_round``
    Dolche gekauft, geht es in die sequenzielle Verarbeitung."""
    if self._action_cap_hit():
      return
    if self._round_to_buy <= 0:
      # Runde fertig gekauft -> sequenziell verarbeiten (erster Dolch aus der Queue).
      self._start_processing_queue()
      return

    # TASCHE-VOLL-SCHUTZ (2026-06-20): ohne freien Slot hat der gekaufte Dolch
    # KEINEN Lande-Slot -> _diff_landing_slot=None -> frueher faelschlich
    # 'buy_unverified'-Stop (User-Log: stoppte bei 11/20). Stattdessen die bereits
    # gekauften Dolche JETZT verarbeiten (Zerlegen schafft Platz) und in den
    # naechsten Runden weiterkaufen. Ist noch NICHTS gekauft -> ehrlicher
    # no_space-Stop (Tasche von Anfang an voll).
    if not self._has_free_slot():
      if self._dagger_queue:
        log.event(self.state, 'ZUSTAND: Tasche voll -> Runde vorzeitig verarbeiten',
                  gekauft_runde=len(self._dagger_queue), rest_runde=self._round_to_buy)
        self._round_to_buy = 0
        self._start_processing_queue()
      else:
        log.event(self.state, t('energiesplitter.no_space'))
        self._stop('no_space')
      return

    try:
      verb = ('[SIM] wuerde' if not self.scharf else 'SCHARF:')
      log.event(self.state, verb + ' GENAU 1 Dolch kaufen',
                rest_runde=self._round_to_buy,
                hammer_rest=self.hammer_remaining,
                dolche_gekauft=self._dolche_gekauft)
    except Exception:  # pragma: no cover
      pass

    # ERKENNUNG VOR AKTION (pro Kauf): den Shop-Dolch JEDESMAL per TEMPLATE neu
    # lokalisieren -- nie eine stale Koordinate rechtsklicken. Re-Lokalisierung
    # fehlgeschlagen -> Rueckfall auf den verifizierten Slot; auch der unbekannt
    # -> sauberer Stop (kein Blind-Kauf eines Fremd-Items).
    slot = self._locate_shop_item('dolch')
    if slot is None:
      slot = getattr(self, '_dolch_shop_slot', None)
    if slot is None:
      log.event(self.state, t('energiesplitter.item_not_in_shop', item='dolch'))
      self._stop('item_not_in_shop')
      return
    self._dolch_shop_slot = slot

    before = self._inventory_signature()
    try:
      verb = ('[SIM] wuerde' if self._guarded() else 'SCHARF:')
      log.event(self.state, verb + ' Dolch rechtsklicken (Kauf)', ziel=tuple(slot))
    except Exception:  # pragma: no cover
      pass
    self._right_click(*slot)
    self.actions_done += 1
    # Kauf-Bestaetigung ('Moechtest du ... kaufen?') -> 'Ja' klicken.
    self._settle(self.BUY_CONFIRM_SETTLE_S)
    self._confirm_buy_if_present()
    self._settle(self.BUY_CONFIRM_SETTLE_S)

    after = self._inventory_signature()
    land = self._diff_landing_slot(before, after)
    if land is None:
      # Kein neues Item gelandet, obwohl der Tasche-voll-Schutz oben einen freien
      # Slot bestaetigt + der Shop-Dolch lokalisiert wurde -> der Rechtsklick blieb
      # WIRKUNGSLOS. Haeufigste Ursache auf langen Laeufen: KEIN Yang/Geld mehr
      # (Kauf nicht moeglich). Ehrlicher Hinweis (User-Vorgabe "bis Geld weg");
      # der Stop laeuft weiter ueber den OCR-unabhaengigen buy_unverified-Backstop
      # -- eine sichere "kein Yang"-Erkennung braeuchte ein kalibriertes
      # Fehlermeldungs-Template, das es (noch) nicht gibt.
      try:
        log.event(self.state, 'HINWEIS: Kauf ohne Wirkung trotz freiem Slot '
                  '-> evtl. kein Yang/Geld mehr (sonst Render-Aussetzer)')
      except Exception:  # pragma: no cover
        pass
      # Lande-Slot des gekauften Dolchs unklar -> nicht verifiziert.
      self._buy_retries += 1
      if self._buy_retries > 2 or self._note_unverified():
        if self.botting:
          self._snapshot('dolch_slot_unknown')
          log.event(self.state, t('energiesplitter.buy_unverified',
                                  retries=self._buy_retries))
          self._stop('buy_unverified')
      return

    self._dagger_queue.append(land)
    self._dolche_gekauft += 1
    self._round_to_buy -= 1
    self.consecutive_unverified = 0
    self._buy_retries = 0
    try:
      log.event(self.state, 'ZUSTAND: Dolch gekauft + Lande-Slot bestimmt',
                lande_slot=(tuple(land) if isinstance(land, (tuple, list)) else land),
                rest_runde=self._round_to_buy,
                dolche_gekauft=self._dolche_gekauft)
    except Exception:  # pragma: no cover
      pass
    if self._round_to_buy <= 0:
      self._start_processing_queue()
    # sonst: noch im selben State, naechster Dolch wird im naechsten Tick gekauft.

  def _start_processing_queue(self):
    """Beginnt die sequenzielle Verarbeitung der gekauften Dolche (EINZELN).

    WICHTIG (User-Grundwahrheit): ein Hammer laesst sich nur auf einen Dolch
    ziehen, wenn der Waffenhaendler-LADEN GESCHLOSSEN ist -> vor dem ersten Drag
    den Laden schliessen (ESC)."""
    if not self._dagger_queue:
      # Nichts gekauft -> Runde leer; Hammer-Bestand neu pruefen.
      self.state = self.ST_RESCAN
      return
    self._close_shop()                       # Laden zu -> Drag erlaubt
    self._settle(self.SHOP_OPEN_SETTLE_S)     # Schliessen rendern lassen
    # ALLE Dolche im Inventar verarbeiten (gerade gekaufte + bereits vorhandene)
    # -- NUR sicher als Dolch erkannte Slots (User-Vorgabe: nie ein Fremd-Item).
    # Faellt der Scan aus, bleiben die gekauften Lande-Slots als Fallback.
    all_dolch = self._all_dolch_slots()
    if all_dolch:
      self._dagger_queue = list(all_dolch)
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
    # wirklich zerlegen?') -> 'Ja' klicken (sonst bleibt der Dolch unverarbeitet).
    # Gleiche Mechanik wie die Kauf-Bestaetigung: Render-Pause, Confirm, Render-
    # Pause, dann verifizieren.
    self._settle(self.BUY_CONFIRM_SETTLE_S)
    self._confirm_dismantle_if_present()
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
