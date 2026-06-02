# -*- coding: utf-8 -*-
"""RowBuildersMixin -- extracted from interface/app (behaviour-preserving).

Mixin for :class:`interface.app.App`. Holds only methods (no
``__init__``, no class-level mutable state) so MRO is unaffected and every
``self`` reference resolves exactly as in the original module.
"""

from interface.app._common import *  # noqa: F401,F403


class RowBuildersMixin:
    def _switch_row(self, parent, row, label, sub, help_text, variable,
                    command, return_switch=False):
        """Eine Settings-Zeile: Label(+Untertitel) + ?-Hilfe + CTkSwitch.

        Gibt standardmaessig den Zeilen-Frame zurueck (oder den Switch, wenn
        ``return_switch``)."""
        frame = ctk.CTkFrame(parent, fg_color='transparent')
        frame.grid(row=row, column=0, sticky='ew', pady=3)
        frame.grid_columnconfigure(0, weight=1)
        text_col = ctk.CTkFrame(frame, fg_color='transparent')
        text_col.grid(row=0, column=0, sticky='w')
        ctk.CTkLabel(text_col, text=label, anchor='w', text_color=TEXT,
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, sticky='w')
        if sub:
            ctk.CTkLabel(text_col, text=sub, anchor='w', text_color=TEXT_FAINT,
                         font=ctk.CTkFont(size=10)).grid(
                row=1, column=0, sticky='w')
        if help_text:
            InfoBadge(frame, text=help_text).grid(row=0, column=1, padx=(4, 4))
        switch = ctk.CTkSwitch(
            frame, text='', variable=variable, command=command,
            progress_color=TEAL, button_color=TEXT_FAINT,
            button_hover_color=TEAL_HOVER, width=40)
        switch.grid(row=0, column=2, sticky='e')
        return switch if return_switch else frame

    def _key_row(self, parent, row, label, sub, help_text, which, current):
        """Eine Hotkey-Zeile: Label(+Untertitel) + ?-Hilfe + Key-Capture-Button."""
        frame = ctk.CTkFrame(parent, fg_color='transparent')
        frame.grid(row=row, column=0, sticky='ew', pady=3)
        frame.grid_columnconfigure(0, weight=1)
        text_col = ctk.CTkFrame(frame, fg_color='transparent')
        text_col.grid(row=0, column=0, sticky='w')
        ctk.CTkLabel(text_col, text=label, anchor='w', text_color=TEXT,
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, sticky='w')
        if sub:
            ctk.CTkLabel(text_col, text=sub, anchor='w', text_color=TEXT_FAINT,
                         font=ctk.CTkFont(size=10)).grid(
                row=1, column=0, sticky='w')
        if help_text:
            InfoBadge(frame, text=help_text).grid(row=0, column=1, padx=(4, 4))
        btn = ctk.CTkButton(
            frame, text=str(current).upper(), width=54, height=30,
            corner_radius=8, fg_color=PANEL_LIGHT, hover_color=PANEL_HOVER,
            text_color=TEXT, font=ctk.CTkFont(family='Consolas', size=13,
                                              weight='bold'),
            command=lambda: self._start_key_capture(which))
        btn.grid(row=0, column=2, sticky='e')
        return btn

    # -- View-Umschaltung ------------------------------------------------

    def _build_opacity_row(self, parent, row):
        """Baut die Overlay-Deckkraft-Zeile (Label + ?-Hilfe + Slider + %-Wert).

        Eigener ``CTkSlider`` statt ``LabeledSlider`` (das ist auf 0.1..20.0/'s'
        festverdrahtet). Bereich 0.4..1.0 in 0.05-Schritten; der Wert wird live
        als Prozent gezeigt und ueber ``_on_opacity_change`` in der Config
        gesichert."""
        frame = ctk.CTkFrame(parent, fg_color='transparent')
        frame.grid(row=row, column=0, sticky='ew', pady=3)
        frame.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(frame, fg_color='transparent')
        head.grid(row=0, column=0, sticky='ew')
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(head, text=t('ui.overlay_opacity'), anchor='w',
                     text_color=TEXT, font=ctk.CTkFont(size=12)).grid(
            row=0, column=0, sticky='w')
        InfoBadge(head, text=t('ui.overlay_opacity_help')).grid(
            row=0, column=1, sticky='e', padx=(4, 4))
        self._opacity_value = ctk.CTkLabel(
            head, text='', anchor='e', text_color=TEAL,
            font=ctk.CTkFont(size=13, weight='bold'))
        self._opacity_value.grid(row=0, column=2, sticky='e')

        lo = cfgmod.OVERLAY_OPACITY_MIN
        hi = cfgmod.OVERLAY_OPACITY_MAX
        steps = max(1, int(round((hi - lo) / 0.05)))
        self._opacity_slider = ctk.CTkSlider(
            frame, from_=lo, to=hi, number_of_steps=steps,
            progress_color=TEAL, button_color=TEAL,
            button_hover_color=TEAL_HOVER, command=self._on_opacity_change)
        self._opacity_slider.grid(row=1, column=0, sticky='ew', pady=(2, 0))
        self._opacity_slider.set(self._overlay_alpha())
        self._refresh_opacity_value()

    def _refresh_opacity_value(self):
        """Schreibt den aktuellen Slider-Wert als Prozent neben das Label."""
        try:
            pct = int(round(float(self._opacity_slider.get()) * 100))
            self._opacity_value.configure(text='{}%'.format(pct))
        except Exception:
            pass

    def _on_opacity_change(self, value):
        """Slider bewegt: Deckkraft (gerundet) in der Config sichern + %-Anzeige."""
        try:
            self._cfg = self.controller.update_config(
                'puzzle', 'overlay_opacity', round(float(value), 2))
        except Exception:
            pass
        self._refresh_opacity_value()
