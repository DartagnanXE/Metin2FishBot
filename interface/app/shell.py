# -*- coding: utf-8 -*-
"""ShellMixin -- extracted from interface/app (behaviour-preserving).

Mixin for :class:`interface.app.App`. Holds only methods (no
``__init__``, no class-level mutable state) so MRO is unaffected and every
``self`` reference resolves exactly as in the original module.
"""

from interface.app._common import *  # noqa: F401,F403


class ShellMixin:
    def _build_titlebar(self):
        """Schmale Titelleiste: Logo + Titel (links), EN|DE + Schliessen (rechts).

        ``self.topbar`` bleibt der Name (``_rebuild_ui`` zerstoert ihn beim
        Sprachwechsel und baut ihn neu).
        """
        bar = ctk.CTkFrame(self, fg_color=PANEL_DARK, corner_radius=0)
        bar.grid(row=0, column=0, sticky='ew')
        bar.grid_columnconfigure(1, weight=1)   # Spacer-Spalte waechst
        self.topbar = bar

        # col 0 -- Logo + Titel.
        ident = ctk.CTkFrame(bar, fg_color='transparent')
        ident.grid(row=0, column=0, sticky='w', padx=(12, 0), pady=7)
        self._place_logo(ident)
        ctk.CTkLabel(ident, text='Metin2 ', text_color=TEXT_MUTED,
                     font=ctk.CTkFont(size=12)).grid(row=0, column=1, sticky='w')
        ctk.CTkLabel(ident, text='Fishing Bot', text_color=TEXT,
                     font=ctk.CTkFont(size=12, weight='bold')).grid(
            row=0, column=2, sticky='w')

        # col 2 -- EN|DE-Umschalter (oben rechts, dezent).
        self._build_lang_toggle(bar).grid(row=0, column=2, sticky='e', padx=4)

        # col 3 -- Schliessen "X" (ASCII-sicher).
        ctk.CTkButton(bar, width=24, height=24, text='X',
                      fg_color='transparent', hover_color=DANGER_SOFT,
                      text_color=TEXT_MUTED, corner_radius=7,
                      font=ctk.CTkFont(size=12, weight='bold'),
                      command=self._on_close).grid(
            row=0, column=3, sticky='e', padx=(0, 10))

    def _place_logo(self, parent):
        """Laedt das musketier.ico als kleines Logo (PIL->CTkImage). Faellt das
        aus, bleibt es text-only -- NIE crashen, KEIN neues Logo erfinden."""
        try:
            from PIL import Image
            path = resource_path(ICON_FILE)
            if os.path.exists(path):
                img = Image.open(path).convert('RGBA')
                self._logo_img = ctk.CTkImage(light_image=img, dark_image=img,
                                              size=(20, 20))
                ctk.CTkLabel(parent, image=self._logo_img, text='').grid(
                    row=0, column=0, sticky='w', padx=(0, 6))
                return
        except Exception:
            pass
        # Fallback: kein Bild -> nur eine schmale Luecke.
        ctk.CTkLabel(parent, text='', width=4).grid(row=0, column=0)

    def _build_lang_toggle(self, parent):
        """Kleiner, dezenter EN/DE-Umschalter: klickbare Mini-Labels (aktiv teal,
        inaktiv grau)."""
        frame = ctk.CTkFrame(parent, fg_color='transparent')
        self._lang_labels = {}
        for col, lang in ((0, 'en'), (2, 'de')):
            lbl = ctk.CTkLabel(frame, text=lang.upper(), width=18,
                               font=ctk.CTkFont(size=11, weight='bold'),
                               cursor='hand2')
            lbl.grid(row=0, column=col)
            lbl.bind('<Button-1>',
                     lambda _e, lng=lang: self._on_lang_change(lng))
            self._lang_labels[lang] = lbl
        ctk.CTkLabel(frame, text='|', text_color=TEXT_MUTED,
                     font=ctk.CTkFont(size=10)).grid(row=0, column=1, padx=1)
        self._refresh_lang_toggle()
        return frame

    def _refresh_lang_toggle(self):
        cur = get_lang()
        for lang, lbl in getattr(self, '_lang_labels', {}).items():
            lbl.configure(text_color=(TEAL if lang == cur else TEXT_MUTED))

    def _on_lang_change(self, lang):
        """Schaltet die Sprache um, speichert sie und rendert das UI neu."""
        if lang == get_lang():
            return
        set_lang(lang)
        self.controller.set_language(lang)
        log.event('-', t('ui.language_changed', lang=lang))
        # Erst NACH dem Callback neu bauen (nicht das klickende Widget zerstoeren).
        self.after(10, self._rebuild_ui)

    def _rebuild_ui(self):
        """Baut Titelleiste + Shell in der aktuellen Sprache neu (Sprachwechsel).

        Der Laufzustand bleibt erhalten (steckt im BotController, nicht in den
        Widgets); die Log-Senke wird sauber ab- und wieder angehaengt. Footer
        (row 3) und Update-Banner (row 2) liegen auf eigenen Zeilen und werden
        NICHT zerstoert -- nur ihre Texte werden aufgefrischt.
        """
        try:
            self.log_panel.detach()
        except Exception:
            pass
        for widget in (getattr(self, 'topbar', None),
                       getattr(self, 'content', None)):
            if widget is not None:
                try:
                    widget.destroy()
                except Exception:
                    pass
        self._build_titlebar()
        self._build_content()
        self._show_view(self._active_view)
        self._apply_config_to_widgets()
        self._apply_window_prefs()
        self.sync_controls()
        if self._cfg['log']['show_in_ui']:
            self.log_panel.attach()
        # Update-Banner liegt auf einer eigenen Grid-Zeile -> NICHT zerstoert;
        # nur seine Texte neu setzen.
        if (getattr(self, '_update_info', None) is not None
                and getattr(self, '_update_banner', None) is not None):
            try:
                self._refresh_update_banner_text()
                self._update_btn.configure(text=t('ui.update_now'))
            except Exception:
                pass
        try:
            self.update_idletasks()
        except Exception:
            pass

    # -- Shell: Rail + Body ----------------------------------------------

    def _build_content(self):
        """Shell (row 1): Icon-Rail (col 0) + Body (col 1).

        ``self.content`` bleibt der Name (``_rebuild_ui`` zerstoert ihn).
        """
        self.content = ctk.CTkFrame(self, fg_color='transparent')
        self.content.grid(row=1, column=0, sticky='nsew')
        self.content.grid_columnconfigure(1, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self._build_rail(self.content)
        self._build_body(self.content)

    def _build_rail(self, parent):
        """Schmale Icon-Rail: Fishing/Puzzle/Console oben, Settings unten."""
        rail = ctk.CTkFrame(parent, width=60, corner_radius=0, fg_color=RAIL_BG)
        rail.grid(row=0, column=0, sticky='ns')
        rail.grid_propagate(False)
        rail.grid_columnconfigure(0, weight=1)
        # Top-Gruppe Fishing/Puzzle/Console/Inventory/Ranking/Roadmap (rows 0-5);
        # die Spacer-Zeile (row 6) waechst und drueckt Settings (row 7) nach unten.
        rail.grid_rowconfigure(6, weight=1)

        self._rail_items = {}
        self._rail_dots = {}
        rows = {'fishing': 0, 'puzzle': 1, 'console': 2, 'inventory': 3,
                'ranking': 4, 'roadmap': 5, 'settings': 7}
        tip_keys = {'fishing': 'ui.view_fishing', 'puzzle': 'ui.view_puzzle',
                    'console': 'ui.view_console',
                    'inventory': 'ui.view_inventory',
                    'ranking': 'ui.view_ranking',
                    'roadmap': 'ui.view_roadmap',
                    'settings': 'ui.view_settings'}
        for view in RAIL_ORDER:
            btn = ctk.CTkButton(
                rail, text=RAIL_GLYPHS[view], width=42, height=42,
                corner_radius=12, font=ctk.CTkFont(size=18),
                fg_color='transparent', text_color=TEXT_FAINT,
                hover_color=RAIL_HOVER,
                command=lambda v=view: self._show_view(v))
            pad_top = 12 if rows[view] == 0 else 3
            pad_bottom = 10 if view == 'settings' else 3
            btn.grid(row=rows[view], column=0, pady=(pad_top, pad_bottom))
            self._rail_items[view] = btn
            try:
                Tooltip(btn, text=t(tip_keys[view]))
            except Exception:
                pass
            # Kleiner Lauf-Punkt, oben rechts auf dem Button (anfangs versteckt).
            dot = ctk.CTkLabel(btn, text='●', text_color=TEAL_BRIGHT,
                               fg_color='transparent',
                               font=ctk.CTkFont(size=9))
            self._rail_dots[view] = dot

    def _set_rail_active(self, view):
        """Hebt das aktive Rail-Item hervor (teal-Fill), die anderen neutral."""
        for name, btn in self._rail_items.items():
            try:
                if name == view:
                    btn.configure(fg_color=TEAL_SOFT, text_color=TEAL_BRIGHT)
                else:
                    btn.configure(fg_color='transparent',
                                  text_color=TEXT_FAINT)
            except Exception:
                pass

    def _update_running_dots(self, running, mode):
        """Zeigt den Lauf-Punkt auf dem aktiven Modus + Console, sonst versteckt."""
        show = {mode, 'console'} if running else set()
        for name, dot in self._rail_dots.items():
            try:
                if name in show:
                    dot.place(relx=0.72, y=4)
                else:
                    dot.place_forget()
            except Exception:
                pass

    def _build_body(self, parent):
        """Body (col 1): Command-Strip oben, getauschte Ansicht darunter."""
        body = ctk.CTkFrame(parent, fg_color='transparent')
        body.grid(row=0, column=1, sticky='nsew')
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)

        self._build_command_strip(body)

        self.panel_wrap = ctk.CTkFrame(body, fg_color=PANEL, corner_radius=0)
        self.panel_wrap.grid(row=1, column=0, sticky='nsew')
        self.panel_wrap.grid_columnconfigure(0, weight=1)
        self.panel_wrap.grid_rowconfigure(0, weight=1)

        self._views = {}
        self._build_fishing_view(self.panel_wrap)
        self._build_puzzle_view(self.panel_wrap)
        self._build_console_view(self.panel_wrap)
        self._build_inventory_view(self.panel_wrap)
        self._build_ranking_view(self.panel_wrap)
        self._build_roadmap_view(self.panel_wrap)
        self._build_settings_view(self.panel_wrap)

    # -- Command-Strip (Timer + START/STOP-Hero) -------------------------

    def _build_command_strip(self, parent):
        """Oberer Streifen: Lauf-Timer (links) + grosser START/STOP-Hero."""
        strip = ctk.CTkFrame(parent, fg_color=STRIP_BG, corner_radius=0)
        strip.grid(row=0, column=0, sticky='ew')
        strip.grid_columnconfigure(1, weight=1)

        # col 0 -- Timer-Block (Wert + Label).
        timer = ctk.CTkFrame(strip, fg_color='transparent', width=70)
        timer.grid(row=0, column=0, sticky='w', padx=(12, 6), pady=11)
        self.timer_val = ctk.CTkLabel(
            timer, text='00:00:00', text_color=TEXT,
            font=ctk.CTkFont(family='Consolas', size=14, weight='bold'))
        self.timer_val.grid(row=0, column=0)
        self.timer_lbl = ctk.CTkLabel(
            timer, text=t('ui.timer_idle'), text_color=TEXT_FAINT,
            font=ctk.CTkFont(size=9, weight='bold'))
        self.timer_lbl.grid(row=1, column=0)
        try:
            self._timer_tooltip = Tooltip(timer, text=t('ui.timer_tip_idle'))
        except Exception:
            self._timer_tooltip = None

        # col 1 -- Hero (gross, teal -> rot beim Laufen).
        self.hero_btn = ctk.CTkButton(
            strip, height=48, corner_radius=14,
            font=ctk.CTkFont(size=17, weight='bold'),
            fg_color=TEAL, hover_color=TEAL_HOVER, text_color=INK,
            text='▶  ' + t('ui.hero_start'),
            command=self._on_start_stop)
        self.hero_btn.grid(row=0, column=1, sticky='ew', padx=(6, 12), pady=11)

    # -- Ansichts-Kopf + die 4 Ansichten ---------------------------------
