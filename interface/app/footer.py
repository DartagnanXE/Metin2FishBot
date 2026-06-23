# -*- coding: utf-8 -*-
"""FooterMixin -- extracted from interface/app (behaviour-preserving).

Mixin for :class:`interface.app.App`. Holds only methods (no
``__init__``, no class-level mutable state) so MRO is unaffected and every
``self`` reference resolves exactly as in the original module.
"""

from interface.app._common import *  # noqa: F401,F403


class FooterMixin:
    def _build_footer(self):
        """Dezente, dauerhaft sichtbare Versionsanzeige unten links (eigene
        Grid-Zeile row 2, unter dem optionalen Update-Banner) + der EN|DE-
        Umschalter und die Detection-Note unten rechts (gegenueber). Zeigt normal
        nur ``vX.Y.Z`` gedaempft; liegt ein Update vor, leuchtet die Version teal
        auf. Klick oeffnet das GitHub-Repo (bzw. startet das Update). Einmalig
        gebaut, vom Sprachwechsel-Neuaufbau NICHT zerstoert (daher ueberleben auch
        EN|DE-Umschalter + Detection-Note -- ihre Texte/Farben werden im
        ``_rebuild_ui`` nur aufgefrischt)."""
        try:
            from version import __version__
            ver = __version__
        except Exception:
            ver = '?'
        self._version_base = 'v' + ver
        self._repo_url = 'https://github.com/DartagnanXE/Metin2MultiTool'

        footer = ctk.CTkFrame(self, fg_color=PANEL_DARK, corner_radius=0)
        footer.grid(row=2, column=0, sticky='ew')
        # Spacer-Spalte (col 2, weight=1) absorbiert die freie Breite -> der
        # EN|DE-Umschalter (col 1, fest links neben der Version) bleibt FEST
        # verankert und rutscht NICHT mehr, wenn der Status-Text (detect_note,
        # rechts) seine Laenge aendert. Layout: Version(0) EN|DE(1) Spacer(2)
        # mode(3) pick(4) resize(5) status(6, rechtsbuendig).
        footer.grid_columnconfigure(2, weight=1)
        self.footer = footer

        self._version_label = ctk.CTkLabel(
            footer, text=self._version_base, anchor='w', cursor='hand2',
            text_color=TEXT_MUTED, font=ctk.CTkFont(size=10))
        self._version_label.grid(row=0, column=0, sticky='w', padx=10,
                                 pady=(3, 4))
        self._version_label.bind('<Button-1>', self._on_version_click, add='+')

        # EN|DE-Umschalter (vom frueheren In-Window-Header hierher verschoben):
        # FEST links neben dem Versionschip (col 1), VOR der weight=1-Spacer-
        # Spalte -> bleibt unbeweglich, egal wie lang der Status-Text rechts wird;
        # die ganze rechte Seite bleibt damit frei fuer die Status-Meldungen. Lebt
        # auf dem Footer und ueberlebt so ``_rebuild_ui`` (das ihn nur via
        # ``_refresh_lang_toggle`` neu einfaerbt). Der LIVE-Wechsel bleibt aktiv.
        self._build_lang_toggle(footer).grid(row=0, column=1, sticky='w',
                                             padx=(8, 6), pady=(3, 4))

        # Fenster-MODUS-Umschalter (Item N / CS4): "Zuletzt fokussiert" <->
        # "Bestimmtes Fenster". Nur sichtbar, wenn >1 METIN2-Fenster offen ist
        # (dann besteht ueberhaupt eine Wahl); sonst versteckt. Lebt auf dem
        # Footer und ueberlebt so ``_rebuild_ui`` (Label via
        # ``_refresh_window_mode_label`` aufgefrischt). Stil wie ``pick_btn``.
        self.mode_btn = ctk.CTkButton(
            footer, text=t('ui.window_mode_last_focused'), height=22, width=120,
            corner_radius=6, fg_color='transparent', hover_color=PANEL_HOVER,
            text_color=TEXT_FAINT, border_width=1, border_color=PANEL_LIGHT,
            font=ctk.CTkFont(size=10), command=self._on_toggle_window_mode)
        self.mode_btn.grid(row=0, column=3, sticky='e', padx=(0, 6),
                          pady=(3, 4))
        self.mode_btn.grid_remove()
        try:
            Tooltip(self.mode_btn, text=t('ui.window_mode_toggle_tip'))
        except Exception:
            pass

        # Mehrfenster-Picker-Knopf (Item N): nur sichtbar, wenn >1 METIN2-Fenster
        # offen ist; sonst versteckt (Single-Window = byte-identisch zu frueher).
        self.pick_btn = ctk.CTkButton(
            footer, text=t('ui.pick_window_btn'), height=22, width=110,
            corner_radius=6, fg_color='transparent', hover_color=PANEL_HOVER,
            text_color=TEXT_FAINT, border_width=1, border_color=PANEL_LIGHT,
            font=ctk.CTkFont(size=10), command=self._open_window_picker)
        self.pick_btn.grid(row=0, column=4, sticky='e', padx=(0, 6),
                           pady=(3, 4))
        self.pick_btn.grid_remove()

        # "Auf 800x600 setzen"-Knopf (Item M): nur sichtbar, wenn Metin2 in
        # falscher Groesse gefunden wurde; setzt die Client-Flaeche auf 800x600.
        self.resize_btn = ctk.CTkButton(
            footer, text=t('ui.detect_resize_btn'), height=22, width=120,
            corner_radius=6, fg_color='transparent', hover_color=PANEL_HOVER,
            text_color=AMBER, border_width=1, border_color=TEAL_DARK,
            font=ctk.CTkFont(size=10), command=self._on_resize_game)
        self.resize_btn.grid(row=0, column=5, sticky='e', padx=(0, 6),
                            pady=(3, 4))
        self.resize_btn.grid_remove()

        # Detection-Note (rechts, gegenueber der Versionsanzeige). Doppelt als
        # transienter Feedback-Slot (flash_saved/notify_*). Leer = gesund.
        self.detect_note = ctk.CTkLabel(
            footer, text='', text_color=AMBER, font=ctk.CTkFont(size=11),
            anchor='e')
        self.detect_note.grid(row=0, column=6, sticky='e', padx=8, pady=(3, 4))

        # Hover-Attribution. Bewusst sprachneutral (Eigennamen + URL).
        try:
            Tooltip(self._version_label,
                    text=('Metin2 MultiTool · ' + self._version_base
                          + '\nMusketier Software - DartagnanXE'
                          + '\n' + self._repo_url))
        except Exception:
            pass

    def _on_version_click(self, _event=None):
        """Klick auf die Versionsanzeige: liegt ein Update vor -> Update-Flow;
        sonst -> GitHub-Repo (Herkunft/Quellcode) im Browser oeffnen."""
        if getattr(self, '_update_info', None) is not None:
            self._on_update_click()
            return
        try:
            import webbrowser
            webbrowser.open(getattr(self, '_repo_url',
                                    'https://github.com/DartagnanXE/Metin2MultiTool'))
        except Exception:
            pass

    # -- EN|DE-Umschalter (vom fruehern In-Window-Header hierher verschoben) --

    def _build_lang_toggle(self, parent):
        """Kleiner, dezenter EN/DE-Umschalter: klickbare Mini-Labels (aktiv teal,
        inaktiv grau). Lebt nun im Footer (``parent``); ``_lang_labels`` wird
        gehalten, damit ``_refresh_lang_toggle`` die aktive Sprache nach einem
        ``_rebuild_ui`` neu einfaerben kann."""
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
