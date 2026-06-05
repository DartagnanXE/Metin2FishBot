# -*- coding: utf-8 -*-
"""InventoryViewMixin -- extracted from interface/app (behaviour-preserving).

Mixin for :class:`interface.app.App`. Holds only methods (no
``__init__``, no class-level mutable state) so MRO is unaffected and every
``self`` reference resolves exactly as in the original module.
"""

from interface.app._common import *  # noqa: F401,F403


class InventoryViewMixin:
    def _build_inventory_view(self, _parent):
        """Baut die Inventar-Sicht: ein grosser "Inventar scannen"-Knopf, der den
        Scan auf einem Hintergrund-Thread startet (UI nie blockieren), plus ?-Hilfe
        und eine dezente Status-Zeile (letztes Scan-Ergebnis). Die ausfuehrliche
        4-Seiten-Karte wird in die Console gedruckt (die rendert Log-Zeilen)."""
        view = self._new_view('inventory')
        self._view_header(view, t('ui.view_inventory'), t('ui.inventory_sub'))

        # Karte: der primaere Scan-Knopf (teal-Hero-Stil) + ?-Hilfe daneben.
        card = Section(view, t('ui.group_inventory'))
        card.grid(row=1, column=0, sticky='ew', pady=(0, 8))
        body = card.body
        body.grid_columnconfigure(0, weight=1)

        self._inv_scan_btn = ctk.CTkButton(
            body, text=t('ui.inventory_scan_btn'), height=44, corner_radius=12,
            font=ctk.CTkFont(size=15, weight='bold'),
            fg_color=TEAL, hover_color=TEAL_HOVER, text_color=INK,
            command=self._on_scan_inventory)
        self._inv_scan_btn.grid(row=0, column=0, sticky='ew', pady=(0, 2))
        InfoBadge(body, text=t('ui.inventory_scan_help')).grid(
            row=0, column=1, sticky='ne', padx=(6, 0))

        # Dezente Status-Zeile: letzte Scan-Zusammenfassung (vom Worker via
        # ``after`` zurueckgespiegelt). Anfangs "noch nicht gescannt".
        self._inv_status = ctk.CTkLabel(
            body, text=t('ui.inventory_never_scanned'), anchor='w',
            text_color=TEXT_FAINT, font=ctk.CTkFont(size=11), wraplength=300)
        self._inv_status.grid(row=1, column=0, columnspan=2, sticky='w',
                              pady=(6, 0))

        # Inventar-Management-Grid (alle Angel-Items als 3-Status-Bild-Toggles).
        self._build_inventory_manage(view, 2)

        # Lebenden Zustand spiegeln: wird das UI WAEHREND eines Scans oder eines
        # laufenden Bots neu gebaut (z.B. EN/DE-Sprachwechsel), zeigt der frische
        # Knopf sonst faelschlich "klickbar". Der Scan-Worker heilt das ohnehin per
        # after(0,...), und die Re-Entrancy-Sperre verhindert Doppel-Scans -- das
        # hier ist die kosmetische Korrektur, damit der Knopf sofort stimmt.
        try:
            if getattr(self, '_inv_scanning', False):
                # Laeuft ein Scan, ist der frisch gebaute Knopf ein NEUES Widget
                # ohne Overlay -> die alte Overlay-Referenz verwerfen und auf dem
                # neuen Knopf den Fortschrittsbalken neu aufsetzen (der naechste
                # progress-Callback fuellt ihn weiter).
                self._inv_scan_btn.configure(state='disabled')
                self._inv_scan_fill = None
                self._inv_scan_fill_begin()
            elif self.controller.running:
                self._inv_scan_btn.configure(state='disabled')
        except Exception:
            pass

    # -- Inventar-Management-Grid (3-Status-Bild-Toggles) ----------------

    def _build_inventory_manage(self, parent, row):
        """Alle Angel-Items als kleine Bilder; jedes ein 3-Status-Toggle per Klick
        (behalten -> entfernen -> Lagerfeuer). Legende + 'Inventar managen'-Knopf.
        Fische zuerst, dann der Rest. Der Apply ist ein PLATZHALTER (loggt nur den
        Plan in die Console -- die echten Handler schreibt der Nutzer noch)."""
        from interface import inventory_manage as im
        card = Section(parent, t('ui.group_inventory_manage'))
        card.grid(row=row, column=0, sticky='ew', pady=(0, 6))
        body = card.body
        body.grid_columnconfigure(0, weight=1)

        # ?-Legende statt Textzeile: EIN Fisch in allen 3 Formen + Beschriftung,
        # versteckt hinter einem ?-Badge (oben rechts, wie die anderen Hilfen).
        try:
            legend = im.legend_image(px=40, lang=get_lang(),
                                     borders=(TEAL, '#6b7280', AMBER))
        except Exception:
            legend = None
        InfoBadge(body, text=t('ui.inv_manage_help'), image=legend).grid(
            row=0, column=0, sticky='e', pady=(0, 2))

        grid = ctk.CTkFrame(body, fg_color='transparent')
        grid.grid(row=1, column=0, sticky='ew')
        self._inv_manage_states = {}
        self._inv_manage_btns = {}
        self._inv_manage_imgs = {}
        self._inv_manage_base = {}
        self._inv_manage_px = 34
        items = im.available_items()
        if not items:
            ctk.CTkLabel(grid, text=t('ui.inv_manage_no_icons'),
                         text_color=AMBER, font=ctk.CTkFont(size=11)).grid(
                row=0, column=0, sticky='w')
            return
        PX, COLS = self._inv_manage_px, 9
        flame = im.make_flame(PX)
        for i, name in enumerate(items):
            keep, remove, fire = im.variants(name, PX, flame=flame)
            if keep is None:
                continue
            self._inv_manage_base[name] = (keep, remove, fire)
            imgs = tuple(
                ctk.CTkImage(light_image=v, dark_image=v, size=(PX, PX))
                for v in (keep, remove, fire))
            self._inv_manage_imgs[name] = imgs
            self._inv_manage_states[name] = im.KEEP
            btn = ctk.CTkButton(
                grid, text='', image=imgs[0], width=PX + 8, height=PX + 8,
                corner_radius=6, fg_color=PANEL_DARK, hover_color=PANEL_HOVER,
                border_width=2,
                border_color=self._inv_manage_border(name, im.KEEP),
                command=lambda n=name: self._on_inv_manage_click(n))
            btn.grid(row=i // COLS, column=i % COLS, padx=2, pady=2)
            self._inv_manage_btns[name] = btn
            try:
                Tooltip(btn, text=im.localized_name(name))
            except Exception:
                pass

        ctk.CTkButton(
            body, text=t('ui.inv_manage_apply'), height=34, corner_radius=10,
            font=ctk.CTkFont(size=13, weight='bold'),
            fg_color=TEAL, hover_color=TEAL_HOVER, text_color=INK,
            command=self._on_inv_manage_apply).grid(
            row=2, column=0, sticky='ew', pady=(6, 0))

    def _update_inv_manage_counts(self, inv):
        """Nach einem Scan: die erkannte Stack-Menge pro Item als Zahl in ALLE 3
        Bildvarianten zeichnen (0 = nichts) + die Buttons aktualisieren. Wirft
        nie -- existiert das Grid nicht (Tab nie geoeffnet), passiert nichts."""
        from interface import inventory_manage as im
        try:
            from inventory.types import STATE_ITEM
        except Exception:
            return
        counts = {}
        try:
            # SUMMED stack quantity per item (read stack numbers), not slot tally:
            # all catchable stackables (baits, boxes, dyes, bleach, keys) add up
            # by their printed number. A slot whose number could not be read
            # still counts as >=1 (its item is there).
            if hasattr(inv, 'stack_totals'):
                counts = dict(inv.stack_totals())
            else:
                pages = getattr(inv, 'pages', {}) or {}
                for page in pages:
                    for s in pages.get(page, ()):
                        if getattr(s, 'state', None) == STATE_ITEM and s.name:
                            n = getattr(s, 'count', None)
                            counts[s.name] = counts.get(s.name, 0) + (
                                n if n is not None else 1)
        except Exception:
            return
        px = getattr(self, '_inv_manage_px', 34)
        for name, base in getattr(self, '_inv_manage_base', {}).items():
            count = counts.get(name, 0)
            try:
                withc = [im.apply_count(v, count, px) for v in base]
                imgs = tuple(
                    ctk.CTkImage(light_image=w, dark_image=w, size=(px, px))
                    for w in withc)
                self._inv_manage_imgs[name] = imgs
                state = self._inv_manage_states.get(name, im.KEEP)
                self._inv_manage_btns[name].configure(image=imgs[state])
            except Exception:
                pass

    def _on_inv_manage_click(self, name):
        """Item angeklickt: in die NAECHSTE ERLAUBTE Stufe schalten (Fisch: voll
        keep->remove->campfire; andere Non-Fish: nur keep<->remove; FIXED-Items
        wie Lagerfeuer/Baits/Boxen bleiben keep) + Bild/Rahmen aktualisieren.
        Wirft nie."""
        from interface import inventory_manage as im
        state = im.next_state(name, self._inv_manage_states.get(name, im.KEEP))
        self._inv_manage_states[name] = state
        try:
            self._inv_manage_btns[name].configure(
                image=self._inv_manage_imgs[name][state],
                border_color=self._inv_manage_border(name, state))
        except Exception:
            pass

    def _inv_manage_border(self, name, state):
        """Rahmenfarbe je Item+Status: FIXED-Items (Lagerfeuer/Baits/Boxen) einen
        gedaempften neutralen Rahmen (signalisiert 'nicht aenderbar'); sonst die
        State-Farbe (behalten=teal / entfernen=grau / Lagerfeuer=amber)."""
        from interface import inventory_manage as im
        if name in im.FIXED_KEEP:
            return '#3f4753'
        return (TEAL, '#6b7280', AMBER)[state]

    def _on_inv_manage_apply(self):
        """'Inventar managen': wendet die per-Item-Entscheidungen an.

        Loggt zuerst den Plan in die Console (behalten / entfernen / Lagerfeuer).
        Die LAGERFEUER-Entscheidungen sind jetzt live: stehen Fische auf
        'Lagerfeuer', startet ein Hintergrund-Thread das Braten (Lagerfeuer
        platzieren -> Feuer per "Lagerfeuer"-Label finden -> jeden markierten
        Fisch per Drag aufs Feuer ziehen). Die REMOVE-Entscheidungen sind jetzt
        ebenfalls live: stehen Items auf 'Entfernen', werden sie -- NACH dem
        Braten -- per Drag aus dem Beutel in die Welt links neben dem Panel
        gezogen und der "fallen lassen?"-Dialog mit "Ja" bestaetigt.

        IDLE-ONLY (wie der Inventar-Scan): das Braten presst Tasten, klickt Reiter
        und zieht mit der Maus -- liefe der Bot, kaempften beide um den Cursor.
        Darum nur ein Hinweis, wenn der Bot laeuft. Wirft nie."""
        from interface import inventory_manage as im
        st = getattr(self, '_inv_manage_states', {})
        remove = sorted(n for n, s in st.items() if s == im.REMOVE)
        campfire = sorted(n for n, s in st.items() if s == im.CAMPFIRE)
        keep = len(st) - len(remove) - len(campfire)
        # NICHTS markiert (alles auf 'behalten'): die nackten Zahlen
        # ("45 behalten, 0 entfernen, 0 Lagerfeuer") sind missverstaendlich --
        # es sieht aus, als waere etwas passiert. Stattdessen eine klare
        # Handlungsanweisung loggen + in der Status-Zeile zeigen und SOFORT raus
        # (kein Grill-/Discard-Worker noetig). Wirft nie.
        if not remove and not campfire:
            try:
                log.event('-', t('ui.inv_manage_no_marks'))
            except Exception:
                pass
            try:
                self._set_inv_status(t('ui.inv_manage_no_marks'), AMBER)
            except Exception:
                pass
            return
        try:
            log.event('0', t('ui.inv_manage_applied', keep=keep,
                             remove=len(remove), campfire=len(campfire)))
            for n in remove:
                log.event('-', '  ' + t('ui.inv_manage_remove') + ': '
                          + im.localized_name(n))
            for n in campfire:
                log.event('-', '  ' + t('ui.inv_manage_campfire') + ': '
                          + im.localized_name(n))
        except Exception:
            pass
        try:
            self.flash_saved()
        except Exception:
            pass
        # Lagerfeuer-Braten anstossen (nur wenn Fische dafuer markiert sind).
        if campfire:
            self._start_campfire_grill(dict(st))
        # Wegwerfen anstossen (nur wenn Items dafuer markiert sind). REIHENFOLGE:
        # erst grillen, dann wegwerfen -- der Discard-Worker wartet, bis das
        # Braten fertig ist (beide nutzen denselben Cursor), sonst startet er
        # sofort. Beide idle-gated + defensiv.
        if remove:
            self._start_item_discard(dict(st))

    def _start_campfire_grill(self, states):
        """Startet das Lagerfeuer-Braten auf einem Daemon-Thread (UI nie blocken).

        Spiegelt exakt das _on_scan_inventory-Muster: Idle-Guard (laeuft der Bot,
        nur ein Hinweis), Fenster-Praefix binden, Worker startet den Live-Runner,
        Ergebnis via after(0, ...) zurueck auf den GUI-Thread. Eine Re-Entrancy-
        Sperre verhindert ueberlappende Grills. Wirft nie."""
        if getattr(self, '_campfire_running', False):
            return
        if self.controller.running:
            try:
                log.event('-', t('campfire.blocked_running'))
            except Exception:
                pass
            try:
                self._set_inv_status(t('ui.inventory_blocked_running'), AMBER)
            except Exception:
                pass
            return
        present, _hwnd, gw, gh, healthy = _probe_game()
        if not present:
            try:
                log.event('-', t('campfire.no_window', detail=''))
            except Exception:
                pass
            return
        self._campfire_running = True
        try:
            self._apply_preferred_hwnd()
        except Exception:
            pass
        cfg = self.controller.current_config()

        def _worker():
            try:
                from interface import inventory_campfire_runner as cr
                res = cr.run_campfire_grill(cfg, states)
                self.after(0, lambda r=res: self._campfire_grill_done(r))
            except Exception as exc:
                self.after(0, lambda e=exc: self._campfire_grill_failed(e))

        threading.Thread(target=_worker, name='campfire-grill',
                         daemon=True).start()

    def _campfire_grill_done(self, res):
        """Braten fertig (GUI-Thread): Praeferenz freigeben, Status setzen."""
        self._campfire_running = False
        try:
            self._clear_preferred_hwnd()
        except Exception:
            pass
        try:
            grilled = len(getattr(res, 'grilled', []) or [])
            status = getattr(res, 'status', 'error')
            if status == 'done':
                self._set_inv_status(
                    t('campfire.status_done', count=grilled), TEAL)
            else:
                self._set_inv_status(
                    t('campfire.status_' + status), AMBER)
        except Exception:
            pass

    def _campfire_grill_failed(self, exc):
        """Braten fehlgeschlagen (GUI-Thread): Praeferenz freigeben, loggen."""
        self._campfire_running = False
        try:
            self._clear_preferred_hwnd()
        except Exception:
            pass
        try:
            log.error(t('campfire.error', detail=str(exc)[:120]), exc=exc)
        except Exception:
            pass
        try:
            self._set_inv_status(t('campfire.status_error'), AMBER)
        except Exception:
            pass

    # -- Wegwerfen / fallen lassen (Discard) -----------------------------

    def _start_item_discard(self, states):
        """Startet das Wegwerfen auf einem Daemon-Thread (UI nie blocken).

        Spiegelt exakt das _start_campfire_grill-Muster: Idle-Guard (laeuft der
        Bot, nur ein Hinweis), Fenster-Praefix binden, Worker startet den Live-
        Runner, Ergebnis via after(0, ...) zurueck auf den GUI-Thread. Eine
        eigene Re-Entrancy-Sperre verhindert ueberlappende Wegwerf-Laeufe.

        REIHENFOLGE: laeuft gerade das Braten (``_campfire_running``), wartet der
        Worker, bis es fertig ist, BEVOR er den Cursor uebernimmt -- so greifen
        Grill und Wegwerfen nie gleichzeitig zur Maus. Wirft nie."""
        if getattr(self, '_discard_running', False):
            return
        if self.controller.running:
            try:
                log.event('-', t('discard.blocked_running'))
            except Exception:
                pass
            try:
                self._set_inv_status(t('ui.inventory_blocked_running'), AMBER)
            except Exception:
                pass
            return
        present, _hwnd, gw, gh, healthy = _probe_game()
        if not present:
            try:
                log.event('-', t('discard.no_window', detail=''))
            except Exception:
                pass
            return
        self._discard_running = True
        try:
            self._apply_preferred_hwnd()
        except Exception:
            pass
        cfg = self.controller.current_config()

        def _worker():
            try:
                # Erst grillen, dann wegwerfen: warte, bis ein evtl. laufendes
                # Braten den Cursor freigibt (beide nutzen dieselbe Maus).
                while getattr(self, '_campfire_running', False):
                    time.sleep(0.1)
                from interface import inventory_discard_runner as dr
                res = dr.run_discard_items(cfg, states)
                self.after(0, lambda r=res: self._item_discard_done(r))
            except Exception as exc:
                self.after(0, lambda e=exc: self._item_discard_failed(e))

        threading.Thread(target=_worker, name='item-discard',
                         daemon=True).start()

    def _item_discard_done(self, res):
        """Wegwerfen fertig (GUI-Thread): Praeferenz freigeben, Status setzen."""
        self._discard_running = False
        try:
            self._clear_preferred_hwnd()
        except Exception:
            pass
        try:
            dropped = len(getattr(res, 'dropped', []) or [])
            status = getattr(res, 'status', 'error')
            if status == 'done':
                self._set_inv_status(
                    t('discard.status_done', count=dropped), TEAL)
            else:
                self._set_inv_status(
                    t('discard.status_' + status), AMBER)
        except Exception:
            pass

    def _item_discard_failed(self, exc):
        """Wegwerfen fehlgeschlagen (GUI-Thread): Praeferenz freigeben, loggen."""
        self._discard_running = False
        try:
            self._clear_preferred_hwnd()
        except Exception:
            pass
        try:
            log.error(t('discard.error', detail=str(exc)[:120]), exc=exc)
        except Exception:
            pass
        try:
            self._set_inv_status(t('discard.status_error'), AMBER)
        except Exception:
            pass

    # -- Ranking (Stats + Event-Status + Leaderboard) --------------------

    def _on_scan_inventory(self):
        """Startet einen Inventar-Scan auf einem Daemon-Thread und spiegelt das
        Ergebnis via ``after(0, ...)`` zurueck auf den GUI-Thread (Tk ist
        single-threaded: der Worker fasst NULL Widgets an). Eine Re-Entrancy-Sperre
        verhindert ueberlappende Scans. Spiegelt exakt das _start_update_download-
        Muster (bewaehrt).

        IDLE-ONLY (ship-blocker): ein Scan presst den Hotkey, klickt 4 Reiter und
        faehrt mit der Maus ueber 45 Slots (pydirectinput, globaler PAUSE=0). Liefe
        der Bot, kaempften beide Threads um denselben Cursor -> Fehlklicks im Spiel.
        Darum: laeuft der Bot, nur ein kurzer Hinweis (Laufzustand unangetastet),
        KEIN Scan -- exakt der Idle-Guard von _on_reset_settings. ``sync_controls``
        graut den Knopf zusaetzlich aus (belt-and-suspenders).

        Vor-Pruefung (Klarheit der Meldung): ist das Fenster DA, aber NICHT ~800x600,
        wuerde der Scan mangels passender Grid-Geometrie fast nur Unbekanntes lesen
        und faelschlich als "Inventar nicht offen" enden. Darum hier vorab denselben
        Groessen-Check wie die Detection (``_probe_game``) -> bei falscher Groesse die
        bestehende 800x600-Hilfe zeigen, statt in die irrefuehrende Meldung zu laufen.
        Der Check ist ein passiver Win32-Read (kein Prozessspeicher); fehlt win32
        (headless), liefert ``_probe_game`` 'nicht da' und wir scannen normal weiter
        (der Runner faengt das fehlende Fenster sauber ab)."""
        if self.controller.running:
            self._set_inv_status(t('ui.inventory_blocked_running'), AMBER)
            return
        present, _hwnd, gw, gh, healthy = _probe_game()
        # CS3 (anti-hang): no Metin2 window -> abort PROMPTLY here, BEFORE the
        # worker spawns. The old path left the button stuck on "scanning..." until
        # the deep WindowCapture exception (or worse, spun against a stale/headless
        # target). Now we show a clear "Metin2 nicht gefunden / nicht offen", log
        # it to the Console, restore the button and return -- never starting the
        # worker. (The runner has the same guard as belt-and-suspenders.)
        if not present:
            self._set_inv_status(t('ui.inventory_not_open'), AMBER)
            try:
                log.event('-', t('ui.inventory_not_open'))
            except Exception:
                pass
            try:
                self._inv_scan_btn.configure(state='normal',
                                             text=t('ui.inventory_scan_btn'))
            except Exception:
                pass
            self._inv_scanning = False
            return
        if present and not healthy:
            self._set_inv_status(t('ui.detect_wrong_size', w=gw, h=gh), AMBER)
            return
        if self._inv_scanning:
            return
        self._inv_scanning = True
        try:
            # Knopf sperren UND in einen Fortschrittsbalken verwandeln (Fuellung
            # links->rechts + synchrone %-Zahl ab 0). Der Text wird vom Overlay
            # gestellt; scheitert das Overlay, faellt _inv_scan_fill_begin selbst
            # auf den 'Scanne ...'-Text zurueck.
            self._inv_scan_btn.configure(state='disabled')
            self._inv_scan_fill_begin()
        except Exception:
            pass
        # CS4: bind the SELECTED window for the scan's duration so capture+input
        # both derive from the picked hwnd (WindowCapture binds it). Honours the
        # window MODE ('last_focused' -> legacy FindWindow; 'specific' -> the
        # picked hwnd). Cleared again on completion in the done/failed handlers.
        # Scans are idle-only (guarded above), so no concurrent run can race the
        # module-global preferred hwnd.
        try:
            self._apply_preferred_hwnd()
        except Exception:
            pass
        cfg = self.controller.current_config()
        prev = self._inv_last_map

        def _on_progress(done, total):
            # Worker-THREADS (parallel recognise): slot-granularen Fortschritt
            # (done von total ueber die 180 Slots) auf den GUI-Thread spiegeln
            # (Tk single-threaded), damit die Status-Zeile 0-100% mitlaeuft statt
            # erst am Ende. Rein kosmetisch + defensiv.
            self.after(0, lambda d=done, n=total:
                       self._inv_scan_progress(d, n))

        def _worker():
            try:
                from interface import inventory_runner
                inv = inventory_runner.run_inventory_scan(
                    cfg, previous_map=prev,   # loggt selbst in die Console
                    progress_fn=_on_progress)
                self.after(0, lambda: self._inv_scan_done(inv))
            except Exception as exc:
                # exc MUSS am Lambda-Erzeugungszeitpunkt gebunden werden: Python 3
                # loescht ``exc`` am Ende des except-Blocks implizit (``del exc``),
                # das via after(0,...) verzoegerte Lambda liefe aber erst im
                # NAECHSTEN Tk-Tick -> NameError im Callback (von Tk verschluckt) ->
                # _inv_scan_failed liefe nie -> der Knopf haenge fuer immer auf
                # "Scanning...". Mit e=exc ueberlebt die Ausnahme den del.
                self.after(0, lambda e=exc: self._inv_scan_failed(e))

        threading.Thread(target=_worker, name='inv-scan', daemon=True).start()

    def _inv_scan_progress(self, done, total):
        """Slot-Fortschritt (GUI-Thread): aktualisiert die Status-Zeile auf
        'Erkenne Items ... P%' (P = done/total ueber die 180 Slots), damit der
        laufende Scan ein fluessiges 0-100% zeigt statt erst am Ende ein Ergebnis.
        Rein kosmetisch + defensiv -- wirft nie, faesst nur die Status-Zeile an
        (der Knopf bleibt deaktiviert wie in _on_scan_inventory gesetzt). Kommt
        der Callback verspaetet erst nach _inv_scan_done an (Scan schon fertig),
        wird er ignoriert, um die Endmeldung nicht zu ueberschreiben. Der
        Fortschritt ist MONOTON (done steigt 1..total), daher springt die Anzeige
        nie zurueck."""
        if not getattr(self, '_inv_scanning', False):
            return
        try:
            pct = int(done * 100 / total) if total else 100
            # Knopf-Fuellung + %-Zahl SYNCHRON hochziehen (links->rechts, 0..100)
            # und parallel die Status-Zeile mitlaufen lassen.
            self._inv_scan_fill_set(pct)
            self._set_inv_status(
                t('inventory.scan_progress_pct', pct=pct), TEAL)
        except Exception:
            pass

    def _inv_scan_done(self, inv):
        """Scan fertig (GUI-Thread): merkt die neue Map als Diff-Basis, gibt den
        Knopf frei und schreibt eine 1-Zeilen-Zusammenfassung in die Status-Zeile."""
        self._inv_last_map = inv
        self._inv_scanning = False
        # CS4: release the scan-scoped window preference (back to FindWindow).
        try:
            self._clear_preferred_hwnd()
        except Exception:
            pass
        try:
            # Fortschrittsbalken-Optik beenden (Overlay weg + Knopftext zurueck)
            # und den Knopf wieder freigeben (voll/leer -> normaler Knopf).
            self._inv_scan_fill_end()
            self._inv_scan_btn.configure(state='normal')
        except Exception:
            pass
        try:
            items = len(inv.items()) if inv is not None else 0
            unknown = len(inv.unknowns()) if inv is not None else 0
            tracked = len(inv.tracked()) if inv is not None else 0
            self._set_inv_status(
                t('ui.inventory_scan_done', items=items, unknown=unknown,
                  tracked=tracked), TEAL)
        except Exception:
            pass
        # Scan-Konfidenz: warne in der Debug-Console, wenn das Ergebnis unsicher
        # aussieht -- nichts erkannt (Fenster/Ausrichtung falsch), eine Stack-Zahl
        # nicht sicher gelesen, ODER deutlich mehr unerkannte als erkannte Slots.
        # Lieber 'nicht sicher ob der Scan geklappt hat' als still vertrauen.
        try:
            uncertain = len(inv.uncertain_counts()) if inv is not None else 0
            if inv is not None and (items == 0 or uncertain
                                    or (unknown > 4 and unknown > 2 * items)):
                self._set_inv_status(t('ui.inventory_scan_uncertain',
                                       unknown=unknown, uncertain=uncertain),
                                     AMBER)
                log.warning(t('ui.inventory_scan_uncertain',
                              unknown=unknown, uncertain=uncertain))
        except Exception:
            pass
        # Stack-Mengen auf die Management-Bilder schreiben (falls Grid existiert).
        try:
            self._update_inv_manage_counts(inv)
        except Exception:
            pass
        self.flash_saved()

    def _inv_scan_failed(self, exc):
        """Scan fehlgeschlagen (GUI-Thread): Knopf freigeben, loggen, Status setzen.

        Fehlt das Metin2-Fenster, wirft ``WindowCapture`` denselben 'not found'-
        Text wie beim Start -- dieselbe Erkennung wie notify_start_failed."""
        self._inv_scanning = False
        # CS4: release the scan-scoped window preference (back to FindWindow).
        try:
            self._clear_preferred_hwnd()
        except Exception:
            pass
        try:
            # Fortschrittsbalken-Optik beenden (Overlay weg + Knopftext zurueck)
            # und den Knopf wieder freigeben.
            self._inv_scan_fill_end()
            self._inv_scan_btn.configure(state='normal')
        except Exception:
            pass
        no_window = _is_no_window_error(exc)
        try:
            log.error(t('ui.inventory_scan_failed'), exc=exc)
        except Exception:
            pass
        msg = (t('ui.inventory_no_window') if no_window
               else t('ui.inventory_scan_failed'))
        self._set_inv_status(msg, AMBER)

    def _set_inv_status(self, text, color):
        """Setzt die Inventar-Status-Zeile (defensiv; existiert das Label nicht,
        passiert nichts)."""
        try:
            self._inv_status.configure(text=text, text_color=color)
        except Exception:
            pass

    # -- Scan-Knopf als Fortschrittsbalken (Fuellung links->rechts + %) --

    def _inv_scan_fill_begin(self):
        """Verwandelt den 'Inventar scannen'-Knopf fuer die Scan-Dauer in einen
        Fortschrittsbalken: ein randloser ``CTkProgressBar`` (Spur = dunkle
        Knopf-Flaeche, Fuellung = TEAL) liegt deckend IM Knopf, darueber zentriert
        ein %-Label. Beide sind KINDER des Knopfes und per ``place(relwidth=1,
        relheight=1)`` an dessen Groesse gekoppelt -- unabhaengig vom Grid. Start
        bei 0 %. Idempotent (ein zweiter Aufruf setzt nur zurueck) + defensiv:
        wirft nie (scheitert das Overlay, bleibt der Knopf einfach 'Scanne ...')."""
        btn = getattr(self, '_inv_scan_btn', None)
        if btn is None:
            return
        try:
            # Leerer Knopf-Text -- die Fuellung + das %-Label IM Knopf ersetzen ihn.
            btn.configure(text='')
        except Exception:
            pass
        fill = getattr(self, '_inv_scan_fill', None)
        if fill is not None:
            # Schon vorhanden (Re-Entry) -> hart auf 0 zuruecksetzen. NICHT ueber
            # _inv_scan_fill_set, dessen Monotonie-Sperre einen Ruecksprung
            # verhinderte (sie bliebe sonst auf dem alten Prozentwert haengen).
            try:
                fill['pct'] = 0
                fill['bar'].set(0.0)
                fill['label'].configure(
                    text=t('inventory.scan_progress_pct', pct=0))
            except Exception:
                pass
            return
        try:
            bar = ctk.CTkProgressBar(
                btn, corner_radius=12, border_width=0, height=44,
                fg_color=PANEL_DARK, progress_color=TEAL)
            bar.set(0.0)
            # Knapp innerhalb des Knopf-Radius platzieren, damit die runden Ecken
            # des Knopfes sichtbar bleiben (kein rechteckiger Balken-Rand).
            bar.place(relx=0.5, rely=0.5, anchor='center',
                      relwidth=0.965, relheight=0.80)
            label = ctk.CTkLabel(
                btn, text=t('inventory.scan_progress_pct', pct=0),
                fg_color='transparent', text_color=TEXT,
                font=ctk.CTkFont(size=14, weight='bold'))
            label.place(relx=0.5, rely=0.5, anchor='center')
            self._inv_scan_fill = {'bar': bar, 'label': label, 'pct': 0}
        except Exception:
            # Kein Overlay moeglich -> Fallback: der Knopf zeigt wieder den
            # klassischen 'Scanne ...'-Text (nie ein leerer Knopf).
            try:
                btn.configure(text=t('ui.inventory_scanning'))
            except Exception:
                pass
            self._inv_scan_fill = None

    def _inv_scan_fill_set(self, pct):
        """Setzt Fuellung UND %-Zahl SYNCHRON auf ``pct`` (0..100). Der Wert ist
        monoton (springt nie zurueck), die Fuellung waechst links->rechts. Rein
        kosmetisch + defensiv -- existiert kein Overlay, passiert nichts."""
        fill = getattr(self, '_inv_scan_fill', None)
        if not fill:
            return
        try:
            value = int(pct)
            if value < 0:
                value = 0
            elif value > 100:
                value = 100
            # Monoton: eine verspaetete kleinere Meldung darf den Balken nicht
            # zurueckspringen lassen.
            if value < fill.get('pct', 0):
                value = fill['pct']
            fill['pct'] = value
            fill['bar'].set(value / 100.0)          # Fuellung (0.0..1.0)
            fill['label'].configure(
                text=t('inventory.scan_progress_pct', pct=value))
        except Exception:
            pass

    def _inv_scan_fill_end(self):
        """Beendet die Fortschritts-Optik: Overlay (Balken + %-Label) entfernen und
        den Knopf auf seinen Ruhetext zuruecksetzen (voll/leer -> wieder ein
        normaler Knopf). Defensiv -- wirft nie."""
        fill = getattr(self, '_inv_scan_fill', None)
        self._inv_scan_fill = None
        if fill:
            for key in ('label', 'bar'):
                widget = fill.get(key)
                try:
                    if widget is not None:
                        widget.destroy()
                except Exception:
                    pass
        try:
            self._inv_scan_btn.configure(text=t('ui.inventory_scan_btn'))
        except Exception:
            pass

    # -- Config -> Widgets -----------------------------------------------
