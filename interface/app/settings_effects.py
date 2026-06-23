# -*- coding: utf-8 -*-
"""SettingsEffectsMixin -- extracted from interface/app (behaviour-preserving).

Mixin for :class:`interface.app.App`. Holds only methods (no
``__init__``, no class-level mutable state) so MRO is unaffected and every
``self`` reference resolves exactly as in the original module.
"""

from interface.app._common import *  # noqa: F401,F403


class SettingsEffectsMixin:
    def _on_window_toggle(self, key, variable):
        """Schreibt eine reine window-Bool-Option (close-on-*) in die Config."""
        self._cfg = self.controller.update_config(
            'window', key, bool(variable.get()))

    def _on_always_top_toggle(self):
        on = bool(self._always_top_var.get())
        self._cfg = self.controller.update_config('window', 'always_on_top', on)
        self._apply_always_on_top(on)

    def _on_tray_toggle(self):
        on = bool(self._tray_var.get())
        self._cfg = self.controller.update_config(
            'window', 'minimize_to_tray', on)
        self._tray_enabled = on and tray.available()

    def _on_auto_scan_toggle(self):
        """Persistiert den (gestubbten) Auto-Scan-nach-dem-Angeln-Schalter.

        Speichert die Einstellung schon heute; die volle Automatik (Scan-Trigger
        beim Angel-Stopp) ist eine Roadmap-Zeile -- der Runner stellt die Naht
        (``run_inventory_scan``) bereit."""
        self._cfg = self.controller.update_config(
            'inventory', 'auto_scan_after_fishing',
            bool(self._auto_scan_var.get()))

    def _on_fast_recognition_toggle(self):
        """Persistiert den Opt-in 'schnelle (vektorisierte) Erkennung'-Schalter.

        Der zugehoerige Schalter wurde aus dem UI entfernt: der vektorisierte,
        BIT-IDENTISCHE Erkennungspfad ist jetzt fest aktiv (siehe ``validate``,
        das ``inventory.fast_recognition`` unbedingt auf True setzt). Dieser
        Handler ist damit ohne gebundenes Widget unerreichbar; der Guard haelt
        ihn als no-op, falls er je doch aufgerufen wird (kein Wurf im UI)."""
        if not hasattr(self, '_fast_recognition_var'):
            return
        self._cfg = self.controller.update_config(
            'inventory', 'fast_recognition',
            bool(self._fast_recognition_var.get()))

    # -- Mount / Fish-Events / Ranking-Handler (Run 1) -------------------

    def _on_mount_toggle(self):
        """Persistiert den Mount-Animation-Cancel-Schalter (fishing)."""
        self._cfg = self.controller.update_config(
            'fishing', 'mount_enabled', bool(self._mount_var.get()))

    def _on_whitelist_toggle(self):
        """Persistiert den Angel-Whitelist-an/aus-Schalter (fishing).

        Reines bool (Default AUS -> es wird alles geangelt). Die konkreten
        Fisch-Entscheidungen injiziert der RunLoop beim Start separat aus dem
        Inventar-Tab; dieser Schalter ist nur der Master-an/aus."""
        self._cfg = self.controller.update_config(
            'fishing', 'whitelist_enabled', bool(self._whitelist_var.get()))

    def _on_bait_refill_toggle(self):
        """Persistiert den Koeder-Nachlegen-an/aus-Schalter (fishing).

        Reines bool (Default AUS -> der Bot prueft den Koeder-Slot nie). Die
        noetige Live-Infrastruktur (Inventar-DB/Kalibrierung) injiziert der RunLoop
        beim Start separat auf die Bot-Instanz; dieser Schalter ist nur der
        Master-an/aus."""
        self._cfg = self.controller.update_config(
            'fishing', 'bait_refill_enabled',
            bool(self._bait_refill_var.get()))

    def _on_event_weekday_change(self, index, weekday):
        """Wochentag eines Event-Fensters geaendert -> 'events' aktualisieren."""
        self._save_event_windows()

    def _on_event_time_change(self, _index):
        """Start/Ende eines Event-Fensters geaendert -> 'events' aktualisieren."""
        self._save_event_windows()

    def _save_event_windows(self):
        """Liest beide Event-Fenster-Zeilen + Warn-Minuten aus den Widgets und
        schreibt sie (validiert) in die Config. Defensiv -- ein leeres/kaputtes
        Feld faellt bei der Validierung auf den Default zurueck."""
        try:
            windows = []
            for w in self._event_window_widgets:
                weekday = w['l2v'].get(w['day'].get(), 0)
                windows.append({
                    'weekday': weekday,
                    'start': w['start'].get().strip(),
                    'end': w['end'].get().strip(),
                })
            self._cfg = self.controller.update_config(
                'events', 'windows', windows)
        except Exception:
            pass

    def _on_event_warn_change(self, _event=None):
        """Warn-Minuten-Feld geaendert -> 'events.warn_minutes' speichern."""
        raw = self._event_warn_entry.get().strip()
        try:
            minutes = int(raw) if raw else 0
        except ValueError:
            minutes = 0
        self._cfg = self.controller.update_config(
            'events', 'warn_minutes', minutes)

    def _on_username_change(self, _event=None):
        """Ranglisten-Name geaendert -> top-level 'username' speichern."""
        try:
            self._set_username(self._username_entry.get().strip())
        except Exception:
            pass

    def _set_username(self, name):
        """Schreibt den top-level Schluessel 'username' (kein section-key) in die
        Config. Geht ueber den Controller, damit Validierung + Auto-Save greifen.
        Wirft nie."""
        try:
            self._cfg = self.controller.update_username(name)
        except Exception:
            pass

    def _on_username_commit(self, _event=None, release_focus=False):
        """Ranglisten-Name committed (FocusOut/Enter): speichern -> SOFORT an den
        Server pushen + Ranking neu laden -> bei Enter den Fokus vom Feld nehmen.

        Der Netzwerk-Teil (submit-then-fetch via ``ranking_view``, Worker-Thread,
        blockiert Tk nie + zeigt sofort die frischen Daten) feuert NUR, wenn sich
        der Name wirklich GEAENDERT hat -- so loest ein Blur ohne Aenderung (oder
        das FocusOut, das Enter selbst ausloest) keinen erneuten Submit aus.
        Strikt defensiv; jeder Schritt unabhaengig gekapselt."""
        try:
            name = self._username_entry.get().strip()
        except Exception:
            name = None
        if name is not None:
            self._set_username(name)
            if name != getattr(self, '_last_pushed_username', None):
                self._last_pushed_username = name
                try:
                    from interface import ranking_view
                    ranking_view.refresh_leaderboard(self, force=True)
                except Exception:
                    pass
        if release_focus:
            self._blur_on_return()
        return 'break'

    def _blur_on_return(self, _event=None):
        """Enter in einem Settings-Feld -> Fokus aufs Hauptfenster, damit man das
        Feld sichtbar 'verlaesst'. Der Wert ist da bereits gespeichert (die Felder
        speichern live via ``<KeyRelease>``). Nie kritisch."""
        try:
            self.focus_set()
        except Exception:
            pass
        return 'break'

    def _apply_always_on_top(self, on):
        try:
            self.attributes('-topmost', bool(on))
        except Exception:
            pass

    def _apply_window_prefs(self):
        """Wendet die gespeicherten Fenster-Optionen an (Startup + Neuaufbau)."""
        try:
            window = self._cfg['window']
            self._apply_always_on_top(window['always_on_top'])
            self._tray_enabled = (window['minimize_to_tray']
                                  and tray.available())
        except Exception:
            pass

    def _on_unmap(self, _event=None):
        """Beim Minimieren ggf. in den Tray statt in die Taskleiste."""
        try:
            if self._tray_enabled and self.state() == 'iconic':
                self._hide_to_tray()
        except Exception:
            pass

    def _hide_to_tray(self):
        """Versteckt das Fenster und zeigt ein Tray-Icon. Strikt defensiv:
        schlaegt etwas fehl, bleibt es ein normales Minimieren (kein Crash)."""
        try:
            if self._tray_icon is not None:
                return
            icon = tray.make_icon(
                ICON_FILE, t('ui.window_title'),
                on_show=lambda: self.after(0, self._restore_from_tray),
                on_quit=lambda: self.after(0, self._on_close),
                show_text=t('ui.tray_show'), quit_text=t('ui.tray_quit'))
            if icon is None:
                return
            self._tray_icon = icon
            self.withdraw()
            icon.run_detached()
        except Exception:
            # Tray-Aufbau gescheitert -> normales Minimieren beibehalten.
            try:
                self.deiconify()
            except Exception:
                pass

    def _restore_from_tray(self):
        """Holt das Fenster aus dem Tray zurueck und stoppt das Icon."""
        try:
            self.deiconify()
            self.lift()
        except Exception:
            pass
        try:
            if self._tray_icon is not None:
                self._tray_icon.stop()
        except Exception:
            pass
        self._tray_icon = None

    # -- Key-Capture (Fishing-Hotkeys) -----------------------------------

    def _on_reset_settings(self):
        """Setzt nach Bestaetigung ALLE Einstellungen auf die Standardwerte.

        Idle-only: laeuft der Bot, kommt nur ein kurzer Hinweis (der Laufzustand
        wird NICHT angetastet). Sonst oeffnet sich ein dunkler Bestaetigungs-
        Dialog (eigenes CTkToplevel, passt zum Theme -- KEIN tkinter.messagebox);
        bestaetigt der Nutzer, baut ``reset_to_defaults`` die Config frisch,
        speichert sie, und das UI wird (mit ggf. gewechselter Sprache) neu
        aufgebaut, sodass alle Widgets sofort die Defaults zeigen. Strikt
        defensiv: scheitert der Dialog-Aufbau, passiert nichts (kein Reset)."""
        if self.controller.running:
            self._flash_note(t('ui.reset_blocked_running'), AMBER)
            return
        self._confirm_dialog(
            title=t('ui.reset_confirm_title'), body=t('ui.reset_confirm_body'),
            ok_text=t('ui.reset_confirm_yes'),
            cancel_text=t('ui.reset_confirm_cancel'),
            on_ok=self._do_reset_settings, danger=True)

    def _do_reset_settings(self):
        """Fuehrt den eigentlichen Reset aus (nach Bestaetigung)."""
        if not self.controller.reset_to_defaults():
            return
        self._cfg = self.controller.current_config()
        # Sprache (kann sich auf Default 'en' geaendert haben) live anwenden +
        # komplettes UI neu aufbauen -> alle Widgets zeigen sofort die Defaults.
        set_lang(self._cfg['language'])
        self.after(10, self._rebuild_ui)
        self.flash_saved()

    def _flash_note(self, text, color):
        """Zeigt kurz (~3 s) eine Meldung in der Detection-Note (Feedback-Slot)."""
        try:
            self.detect_note.configure(text=text, text_color=color)
            if self._saved_job is not None:
                self.after_cancel(self._saved_job)
            self._saved_job = self.after(3000, self._refresh_detect_note)
        except Exception:
            pass

    def _maybe_show_rating_prompt(self):
        """ONCE, after the 10th solved puzzle, offer to rate the project on
        GitHub. 'Rate' opens the repo + closes the popup; 'Later' just closes.
        Persisted via ``telemetry.rating_prompted`` so it never re-appears.
        Runs on the GUI thread (scheduled via ``after``). Never raises."""
        try:
            cfg = self.controller.current_config()
            if cfg.get('telemetry', {}).get('rating_prompted', False):
                return
            solved = int((getattr(self, '_stats', {}) or {}).get(
                'puzzles_solved', 0))
            if solved < 10:
                return
            self.controller.update_config('telemetry', 'rating_prompted', True)
            # Sofort auf Platte -> das Popup kommt nie erneut, auch nach hartem
            # Schliessen direkt nach dem 10. Puzzle.
            self.controller.persist_now()
        except Exception:
            return

        def _open():
            try:
                import webbrowser
                webbrowser.open('https://github.com/DartagnanXE/Metin2MultiTool')
            except Exception:
                pass
        try:
            self._confirm_dialog(
                t('ui.rating_title'), t('ui.rating_body'),
                t('ui.rating_ok'), t('ui.rating_later'), _open)
        except Exception:
            pass

    def _confirm_dialog(self, title, body, ok_text, cancel_text, on_ok,
                        danger=False):
        """Kleiner, dunkler Ja/Nein-Bestaetigungsdialog (eigenes CTkToplevel).

        Passt zum Teal/Dark-Theme (kein graues ``tkinter.messagebox``). Modal
        ueber ``transient`` + ``grab_set``. ``on_ok`` wird nur bei Bestaetigung
        gerufen. Strikt defensiv -- schlaegt der Aufbau fehl, passiert nichts."""
        try:
            dlg = ctk.CTkToplevel(self)
            dlg.title(title)
            dlg.configure(fg_color=BG)
            dlg.resizable(False, False)
            dlg.geometry('400x176')  # mitgewachsen mit widget_scaling 0.85->1.0
            try:
                dlg.transient(self)
            except Exception:
                pass
            dlg.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(dlg, text=title, text_color=TEXT,
                         font=ctk.CTkFont(size=14, weight='bold')).grid(
                row=0, column=0, sticky='w', padx=16, pady=(16, 4))
            ctk.CTkLabel(dlg, text=body, text_color=TEXT_MUTED, justify='left',
                         wraplength=300, font=ctk.CTkFont(size=12)).grid(
                row=1, column=0, sticky='w', padx=16, pady=(0, 12))

            btns = ctk.CTkFrame(dlg, fg_color='transparent')
            btns.grid(row=2, column=0, sticky='e', padx=16, pady=(0, 14))

            def _close():
                try:
                    dlg.grab_release()
                except Exception:
                    pass
                try:
                    dlg.destroy()
                except Exception:
                    pass

            def _confirm():
                _close()
                try:
                    on_ok()
                except Exception:
                    pass

            ctk.CTkButton(
                btns, text=cancel_text, width=90, height=30, corner_radius=8,
                fg_color='transparent', hover_color=PANEL_HOVER,
                text_color=TEXT_MUTED, border_width=1, border_color=PANEL_LIGHT,
                command=_close).grid(row=0, column=0, padx=(0, 8))
            ctk.CTkButton(
                btns, text=ok_text, width=110, height=30, corner_radius=8,
                fg_color=(DANGER if danger else TEAL),
                hover_color=(DANGER_HOVER if danger else TEAL_HOVER),
                text_color=('#fff' if danger else INK),
                command=_confirm).grid(row=0, column=1)

            dlg.protocol('WM_DELETE_WINDOW', _close)
            try:
                dlg.after(60, dlg.grab_set)   # nach dem Mappen modal greifen
                dlg.lift()
            except Exception:
                pass
        except Exception:
            pass

    # -- Settings: Laufzeit-Effekte + Tray-Lifecycle ---------------------
