# -*- coding: utf-8 -*-
"""SettingsViewMixin -- extracted from interface/app (behaviour-preserving).

Mixin for :class:`interface.app.App`. Holds only methods (no
``__init__``, no class-level mutable state) so MRO is unaffected and every
``self`` reference resolves exactly as in the original module.
"""

from interface.app._common import *  # noqa: F401,F403


class SettingsViewMixin:
    def _build_settings_view(self, _parent):
        view = self._new_view('settings')
        view.grid_rowconfigure(1, weight=1)
        self._view_header(view, t('ui.view_settings'), t('ui.settings_sub'))

        # Settings ist die inhaltsreichste Sicht. Mit den neuen Karten (Mount,
        # Fish-Events, Ranking) sprengt sie das fixe 470x608-Fenster -> die
        # Karten leben in einem scrollbaren Container (rein additiv; alle anderen
        # Sichten bleiben unscrollbar/byte-stabil). ``scroll`` ersetzt ``view``
        # als Karten-Parent.
        scroll = ctk.CTkScrollableFrame(view, fg_color='transparent')
        scroll.grid(row=1, column=0, sticky='nsew')
        scroll.grid_columnconfigure(0, weight=1)

        # -- Karte "Shutdown" (Settings #3 + #4) ------------------------
        shutdown = Section(scroll, t('ui.group_shutdown'))
        shutdown.grid(row=1, column=0, sticky='ew', pady=(0, 4))
        sbody = shutdown.body
        self._close_metin2_var = ctk.BooleanVar(
            value=self._cfg['window']['close_on_metin2_close'])
        self._switch_row(
            sbody, 0, t('ui.close_on_metin2'), None, t('ui.close_on_metin2_help'),
            self._close_metin2_var,
            lambda: self._on_window_toggle('close_on_metin2_close',
                                           self._close_metin2_var))
        self._close_timer_var = ctk.BooleanVar(
            value=self._cfg['window']['close_on_timer_expire'])
        self._switch_row(
            sbody, 1, t('ui.close_on_timer'), None, t('ui.close_on_timer_help'),
            self._close_timer_var,
            lambda: self._on_window_toggle('close_on_timer_expire',
                                           self._close_timer_var))

        # -- Karte "Fishing hotkeys" (Settings #5) ----------------------
        hotkeys = Section(scroll, t('ui.group_hotkeys'))
        hotkeys.grid(row=2, column=0, sticky='ew', pady=(0, 4))
        hbody = hotkeys.body
        hbody.grid_columnconfigure(0, weight=1)
        self.bait_key_btn = self._key_row(
            hbody, 0, t('ui.bait_key'), t('ui.bait_key_sub'),
            t('ui.hotkeys_help'), 'bait',
            self._cfg['fishing']['bait_key'])
        self.cast_key_btn = self._key_row(
            hbody, 1, t('ui.cast_key'), t('ui.cast_key_sub'),
            None, 'cast', self._cfg['fishing']['cast_key'])
        # Reittier-Taste gehoert thematisch zu den Angel-Tasten (kein eigener
        # "Mount"-Abschnitt mehr); der AN/AUS-Schalter sitzt in der Fishing-View.
        self.mount_key_btn = self._key_row(
            hbody, 2, t('ui.mount_key'), t('ui.mount_key_sub'),
            None, 'mount', self._cfg['fishing']['mount_key'])
        # Bot-Stop-Hotkey -- global (wirkt auch bei Spiel-Fokus), Default F6,
        # wird im laufenden Stop-Button angezeigt.
        self.stop_key_btn = self._key_row(
            hbody, 3, t('ui.stop_key'), t('ui.stop_key_sub'),
            None, 'stop', self._cfg.get('controls', {}).get('stop_hotkey', 'f6'))

        # (Der fruehere "Mount"-Abschnitt entfaellt: der AN/AUS-Schalter sitzt
        # jetzt als Option in der Fishing-View, die Reittier-TASTE oben unter
        # "Angel-Tasten".)

        # -- Karte "Fish events" (zwei Fenster + Warn-Minuten) ----------
        self._build_events_card(scroll, 4)

        # -- Karte "Ranking" (Telemetrie-Opt-in + Name) -----------------
        self._build_ranking_card(scroll, 5)

        # -- Karte "Inventory" (Hotkey + Auto-Scan-Toggle) --------------
        # Eigene Karte (sauberer als eine 3. Zeile in "Fishing hotkeys"). Der
        # Hotkey nutzt EXAKT den generischen Key-Capture-Fluss (which='inventory');
        # der Auto-Scan-Schalter persistiert die Einstellung schon (volle Automatik
        # ist eine Roadmap-Zeile -- der Runner stellt die Naht bereit).
        inv = Section(scroll, t('ui.group_inventory'))
        inv.grid(row=6, column=0, sticky='ew', pady=(0, 4))
        ibody = inv.body
        ibody.grid_columnconfigure(0, weight=1)
        self.inventory_key_btn = self._key_row(
            ibody, 0, t('ui.inventory_hotkey'), t('ui.inventory_hotkey_sub'),
            t('ui.inventory_scan_help'), 'inventory',
            self._cfg['inventory']['hotkey'])
        self._auto_scan_var = ctk.BooleanVar(
            value=self._cfg['inventory']['auto_scan_after_fishing'])
        self._switch_row(
            ibody, 1, t('ui.auto_scan_after_fishing'), None,
            t('ui.auto_scan_after_fishing_help'), self._auto_scan_var,
            self._on_auto_scan_toggle)
        # (Der "Schnelle Erkennung"-Schalter entfaellt: der Scan laeuft jetzt
        # IMMER vektorisiert/bit-identisch -- der Schalter waere ohne Wirkung. Die
        # Einstellung bleibt als interner Debug-Default True in der Config, ohne
        # eigene UI-Zeile.)

        # -- Karte "Window" (Settings #2 + #1) --------------------------
        window = Section(scroll, t('ui.group_window'))
        window.grid(row=7, column=0, sticky='ew', pady=(0, 2))
        wbody = window.body
        self._always_top_var = ctk.BooleanVar(
            value=self._cfg['window']['always_on_top'])
        self._switch_row(
            wbody, 0, t('ui.always_on_top'), None, t('ui.always_on_top_help'),
            self._always_top_var, self._on_always_top_toggle)
        self._tray_var = ctk.BooleanVar(
            value=self._cfg['window']['minimize_to_tray'])
        tray_ok = tray.available()
        tray_sub = None if tray_ok else t('ui.tray_unavailable')
        self._tray_switch = self._switch_row(
            wbody, 1, t('ui.minimize_to_tray'), tray_sub,
            t('ui.minimize_to_tray_help'), self._tray_var,
            self._on_tray_toggle, return_switch=True)
        if not tray_ok:
            try:
                self._tray_switch.configure(state='disabled')
            except Exception:
                pass

        # Overlay-Deckkraft: kleiner Slider (0.4..1.0) + Live-%-Wert + ?-Hilfe,
        # in die Window-Karte gefaltet (kein eigener Kartenkopf -> balanciert die
        # Settings-Hoehe). Steuert die Transparenz von Mark-/Vorschau-Overlay.
        self._build_opacity_row(wbody, 2)

        # Puzzle-Schritt-Delay: Slider 0.01..1.0 s (schneller = fluessigeres
        # Puzzle). Neben der Deckkraft eingefaltet (beides Puzzle-Steuerung).
        self._build_delay_row(wbody, 3)

        # -- Reset-Zeile (Item K) ---------------------------------------
        # Bewusst SEKUNDAER (transparent + duenner Rand, gedaempfte Schrift, klein
        # + rechtsbuendig) -- kein teal/roter Hero-Knopf. "?"-Hilfe links daneben.
        # Setzt nach Bestaetigung ALLES auf die Auslieferungs-Standardwerte; nur
        # im Leerlauf (Idle-Guard im Handler + sync_controls-Sperre).
        reset_row = ctk.CTkFrame(scroll, fg_color='transparent')
        reset_row.grid(row=8, column=0, sticky='ew', pady=(4, 0))
        reset_row.grid_columnconfigure(0, weight=1)
        InfoBadge(reset_row, text=t('ui.reset_settings_help')).grid(
            row=0, column=1, sticky='e', padx=(0, 6))
        self.reset_btn = ctk.CTkButton(
            reset_row, text=t('ui.reset_settings'), height=28, width=180,
            corner_radius=8, fg_color='transparent', hover_color=DANGER_SOFT,
            text_color=TEXT_MUTED, border_width=1, border_color=TEAL_DARK,
            font=ctk.CTkFont(size=11), command=self._on_reset_settings)
        self.reset_btn.grid(row=0, column=2, sticky='e')

    # -- Settings: neue Karten (Fish-Events / Ranking) -----------

    def _build_events_card(self, parent, row):
        """Fish-Events: zwei Fenster (Wochentag-Dropdown + Start/Ende HH:MM) +
        'N Min vor Ende warnen' -> config 'events'."""
        card = Section(parent, t('ui.group_events'))
        card.grid(row=row, column=0, sticky='ew', pady=(0, 4))
        body = card.body
        body.grid_columnconfigure(0, weight=1)
        InfoBadge(body, text=t('ui.events_help')).grid(
            row=0, column=0, sticky='e')
        windows = self._cfg['events']['windows']
        self._event_window_widgets = []
        self._build_event_window_row(body, 1, 0, t('ui.events_window1'),
                                     windows[0])
        self._build_event_window_row(body, 2, 1, t('ui.events_window2'),
                                     windows[1])
        # Warn-Minuten-Zeile.
        warn_row = ctk.CTkFrame(body, fg_color='transparent')
        warn_row.grid(row=3, column=0, sticky='ew', pady=(4, 0))
        warn_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(warn_row, text=t('ui.events_warn_minutes'), anchor='w',
                     text_color=TEXT, font=ctk.CTkFont(size=12)).grid(
            row=0, column=0, sticky='w')
        self._event_warn_entry = ctk.CTkEntry(warn_row, width=64,
                                              justify='center')
        self._event_warn_entry.grid(row=0, column=1, sticky='e')
        self._event_warn_entry.insert(
            0, str(self._cfg['events']['warn_minutes']))
        self._event_warn_entry.bind('<KeyRelease>', self._on_event_warn_change)
        self._event_warn_entry.bind('<FocusOut>', self._on_event_warn_change,
                                    add='+')
        self._event_warn_entry.bind('<Return>', self._blur_on_return, add='+')

    def _weekday_pairs(self):
        """(value 0..6, localized label) for the weekday dropdowns (live)."""
        keys = ('ui.weekday_mon', 'ui.weekday_tue', 'ui.weekday_wed',
                'ui.weekday_thu', 'ui.weekday_fri', 'ui.weekday_sat',
                'ui.weekday_sun')
        return [(i, t(keys[i])) for i in range(7)]

    def _build_event_window_row(self, parent, row, index, label, window):
        """One event-window row: weekday dropdown + start/end HH:MM entries."""
        frame = ctk.CTkFrame(parent, fg_color='transparent')
        frame.grid(row=row, column=0, sticky='ew', pady=2)
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(frame, text=label, anchor='w', text_color=TEXT_MUTED,
                     font=ctk.CTkFont(size=11, weight='bold')).grid(
            row=0, column=0, sticky='w', columnspan=4)

        pairs = self._weekday_pairs()
        labels = [lbl for _v, lbl in pairs]
        v2l = {v: lbl for v, lbl in pairs}
        l2v = {lbl: v for v, lbl in pairs}
        day_menu = ctk.CTkOptionMenu(
            frame, values=labels, width=86,
            fg_color=PANEL_LIGHT, button_color=TEAL_DARK,
            button_hover_color=TEAL_HOVER,
            command=lambda lbl, idx=index, mp=l2v:
                self._on_event_weekday_change(idx, mp.get(lbl, 0)))
        day_menu.set(v2l.get(window['weekday'], labels[0]))
        day_menu.grid(row=1, column=0, sticky='w', pady=(2, 0))

        start_entry = ctk.CTkEntry(frame, width=58, justify='center')
        start_entry.grid(row=1, column=1, sticky='e', padx=(4, 2), pady=(2, 0))
        start_entry.insert(0, window['start'])
        start_entry.bind('<KeyRelease>',
                         lambda e, idx=index: self._on_event_time_change(idx))
        start_entry.bind('<FocusOut>',
                         lambda e, idx=index: self._on_event_time_change(idx),
                         add='+')
        start_entry.bind('<Return>', self._blur_on_return, add='+')

        ctk.CTkLabel(frame, text='-', text_color=TEXT_FAINT,
                     font=ctk.CTkFont(size=12)).grid(
            row=1, column=2, pady=(2, 0))

        end_entry = ctk.CTkEntry(frame, width=58, justify='center')
        end_entry.grid(row=1, column=3, sticky='e', padx=(2, 0), pady=(2, 0))
        end_entry.insert(0, window['end'])
        end_entry.bind('<KeyRelease>',
                       lambda e, idx=index: self._on_event_time_change(idx))
        end_entry.bind('<FocusOut>',
                       lambda e, idx=index: self._on_event_time_change(idx),
                       add='+')
        end_entry.bind('<Return>', self._blur_on_return, add='+')

        self._event_window_widgets.append(
            {'day': day_menu, 'l2v': l2v, 'v2l': v2l,
             'start': start_entry, 'end': end_entry})

    def _build_ranking_card(self, parent, row):
        """Ranking: ein-Zeilen-Transparenz-Hinweis + (optionaler) Anzeigename.

        Kein Opt-in/Opt-out-Schalter mehr -- der anonyme Zaehler laeuft immer.
        Der Name ist das EINZIGE, das Identitaet preisgibt: leer = anonymer
        Zufallsname; etwas eintragen = diesen Namen zeigen."""
        card = Section(parent, t('ui.group_ranking'))
        card.grid(row=row, column=0, sticky='ew', pady=(0, 4))
        body = card.body
        body.grid_columnconfigure(0, weight=1)
        # Ein-Zeilen-Transparenz-Hinweis (ersetzt den Opt-in-Schalter).
        ctk.CTkLabel(body, text=t('ui.ranking_transparency'), anchor='w',
                     justify='left', text_color=TEXT_MUTED, wraplength=380,
                     font=ctk.CTkFont(size=10)).grid(
            row=0, column=0, sticky='w', pady=(0, 4))
        # Ranglisten-Name (top-level username).
        name_row = ctk.CTkFrame(body, fg_color='transparent')
        name_row.grid(row=1, column=0, sticky='ew', pady=3)
        name_row.grid_columnconfigure(0, weight=1)
        text_col = ctk.CTkFrame(name_row, fg_color='transparent')
        text_col.grid(row=0, column=0, sticky='w')
        ctk.CTkLabel(text_col, text=t('ui.ranking_username'), anchor='w',
                     text_color=TEXT, font=ctk.CTkFont(size=12)).grid(
            row=0, column=0, sticky='w')
        ctk.CTkLabel(text_col, text=t('ui.ranking_username_sub'), anchor='w',
                     text_color=TEXT_FAINT, justify='left', wraplength=240,
                     font=ctk.CTkFont(size=10)).grid(
            row=1, column=0, sticky='w')
        self._username_entry = ctk.CTkEntry(name_row, width=140,
                                           justify='center')
        self._username_entry.grid(row=0, column=1, sticky='e')
        self._username_entry.insert(0, self._cfg.get('username', ''))
        self._username_entry.bind('<KeyRelease>', self._on_username_change)
        # Commit on leaving the field / pressing Enter: save -> push to the server
        # -> reload the ranking (Enter also drops focus). KeyRelease above keeps
        # the config live while typing; the network side fires once here, and only
        # when the name actually changed (see _on_username_commit).
        self._last_pushed_username = self._cfg.get('username', '')
        self._username_entry.bind('<FocusOut>', self._on_username_commit, add='+')
        self._username_entry.bind(
            '<Return>',
            lambda e: self._on_username_commit(e, release_focus=True), add='+')
