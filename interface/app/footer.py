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
        Grid-Zeile row 3, unter dem optionalen Update-Banner) + die Detection-
        Note unten rechts (gegenueber). Zeigt normal nur ``vX.Y.Z`` gedaempft;
        liegt ein Update vor, leuchtet die Version teal auf. Klick oeffnet das
        GitHub-Repo (bzw. startet das Update). Einmalig gebaut, vom Sprachwechsel-
        Neuaufbau NICHT zerstoert (daher ueberlebt auch die Detection-Note)."""
        try:
            from version import __version__
            ver = __version__
        except Exception:
            ver = '?'
        self._version_base = 'v' + ver
        self._repo_url = 'https://github.com/DartagnanXE/Metin2FishBot'

        footer = ctk.CTkFrame(self, fg_color=PANEL_DARK, corner_radius=0)
        footer.grid(row=3, column=0, sticky='ew')
        footer.grid_columnconfigure(0, weight=1)
        self.footer = footer

        self._version_label = ctk.CTkLabel(
            footer, text=self._version_base, anchor='w', cursor='hand2',
            text_color=TEXT_MUTED, font=ctk.CTkFont(size=10))
        self._version_label.grid(row=0, column=0, sticky='w', padx=10,
                                 pady=(3, 4))
        self._version_label.bind('<Button-1>', self._on_version_click, add='+')

        # Mehrfenster-Picker-Knopf (Item N): nur sichtbar, wenn >1 METIN2-Fenster
        # offen ist; sonst versteckt (Single-Window = byte-identisch zu frueher).
        self.pick_btn = ctk.CTkButton(
            footer, text=t('ui.pick_window_btn'), height=22, width=110,
            corner_radius=6, fg_color='transparent', hover_color=PANEL_HOVER,
            text_color=TEXT_FAINT, border_width=1, border_color=PANEL_LIGHT,
            font=ctk.CTkFont(size=10), command=self._open_window_picker)
        self.pick_btn.grid(row=0, column=1, sticky='e', padx=(0, 6),
                           pady=(3, 4))
        self.pick_btn.grid_remove()

        # "Auf 800x600 setzen"-Knopf (Item M): nur sichtbar, wenn Metin2 in
        # falscher Groesse gefunden wurde; setzt die Client-Flaeche auf 800x600.
        self.resize_btn = ctk.CTkButton(
            footer, text=t('ui.detect_resize_btn'), height=22, width=120,
            corner_radius=6, fg_color='transparent', hover_color=PANEL_HOVER,
            text_color=AMBER, border_width=1, border_color=TEAL_DARK,
            font=ctk.CTkFont(size=10), command=self._on_resize_game)
        self.resize_btn.grid(row=0, column=2, sticky='e', padx=(0, 6),
                            pady=(3, 4))
        self.resize_btn.grid_remove()

        # Detection-Note (rechts, gegenueber der Versionsanzeige). Doppelt als
        # transienter Feedback-Slot (flash_saved/notify_*). Leer = gesund.
        self.detect_note = ctk.CTkLabel(
            footer, text='', text_color=AMBER, font=ctk.CTkFont(size=11),
            anchor='e')
        self.detect_note.grid(row=0, column=3, sticky='e', padx=8, pady=(3, 4))

        # Hover-Attribution. Bewusst sprachneutral (Eigennamen + URL).
        try:
            Tooltip(self._version_label,
                    text=('Metin2 Fishing Bot · ' + self._version_base
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
                                    'https://github.com/DartagnanXE/Metin2FishBot'))
        except Exception:
            pass
