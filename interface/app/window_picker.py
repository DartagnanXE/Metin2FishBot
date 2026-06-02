# -*- coding: utf-8 -*-
"""WindowPickerMixin -- extracted from interface/app (behaviour-preserving).

Mixin for :class:`interface.app.App`. Holds only methods (no
``__init__``, no class-level mutable state) so MRO is unaffected and every
``self`` reference resolves exactly as in the original module.
"""

from interface.app._common import *  # noqa: F401,F403


class WindowPickerMixin:
    def _refresh_window_picker(self):
        """Aktualisiert die Liste sichtbarer METIN2-Fenster + die Picker-UI.

        <=1 Fenster: ``_chosen_hwnd`` loeschen, Picker-Knopf verstecken ->
        byte-identisch zu frueher (Single-Window). >1: Knopf zeigen. Die UI wird
        NUR bei geaenderter HWND-Signatur angefasst (kein Sekunden-Flackern)."""
        try:
            import constants
            import windowcapture
            windows = windowcapture.enumerate_game_windows(constants.GAME_NAME)
        except Exception:
            windows = []
        self._game_windows = windows
        sig = tuple(w['hwnd'] for w in windows)
        if sig == self._window_sig:
            return
        self._window_sig = sig
        # Gewaehltes Ziel verwerfen, wenn es nicht mehr existiert.
        if self._chosen_hwnd not in sig:
            self._chosen_hwnd = None
        try:
            btn = getattr(self, 'pick_btn', None)
            if btn is None:
                return
            if len(windows) > 1:
                btn.grid()
            else:
                btn.grid_remove()
        except Exception:
            pass

    def _open_window_picker(self):
        """Kleiner Auswahldialog (eigenes CTkToplevel) der gefundenen METIN2-
        Fenster -- je Fenster eine Zeile mit Groesse/Position. Auswahl setzt das
        Ziel-HWND (Item N). Strikt defensiv."""
        windows = list(self._game_windows)
        if len(windows) <= 1:
            return
        try:
            dlg = ctk.CTkToplevel(self)
            dlg.title(t('ui.pick_window_title'))
            dlg.configure(fg_color=BG)
            dlg.resizable(False, False)
            dlg.geometry('360x{}'.format(70 + 40 * len(windows)))
            try:
                dlg.transient(self)
            except Exception:
                pass
            dlg.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(dlg, text=t('ui.pick_window_title'), text_color=TEXT,
                         font=ctk.CTkFont(size=14, weight='bold')).grid(
                row=0, column=0, sticky='w', padx=16, pady=(14, 6))

            def _close():
                try:
                    dlg.grab_release()
                except Exception:
                    pass
                try:
                    dlg.destroy()
                except Exception:
                    pass

            for i, win in enumerate(windows):
                n = i + 1
                row_text = t('ui.pick_window_row', n=n, w=win['w'], h=win['h'],
                             x=win['x'], y=win['y'])

                def _pick(w=win, num=n, dialog_close=_close):
                    dialog_close()
                    self._on_pick_window(w['hwnd'], num, w['w'], w['h'])

                ctk.CTkButton(
                    dlg, text=row_text, height=30, corner_radius=8,
                    fg_color=PANEL_LIGHT, hover_color=PANEL_HOVER,
                    text_color=TEXT, font=ctk.CTkFont(size=12),
                    command=_pick).grid(row=1 + i, column=0, sticky='ew',
                                        padx=16, pady=3)

            dlg.protocol('WM_DELETE_WINDOW', _close)
            try:
                dlg.after(60, dlg.grab_set)
                dlg.lift()
            except Exception:
                pass
        except Exception:
            pass

    def _on_pick_window(self, hwnd, n, w, h):
        """Speichert das gewaehlte Ziel-HWND (runtime-only) + loggt die Wahl."""
        self._chosen_hwnd = hwnd
        log.event('-', t('ui.window_chosen', n=n, w=w, h=h))

    def _apply_preferred_hwnd(self):
        """Reicht das gewaehlte Ziel-HWND an WindowCapture durch (vor Start).

        Ohne Wahl (``None``) -> ``set_preferred_hwnd(None)`` -> FindWindow-Pfad
        (byte-identisch zu frueher). Strikt defensiv."""
        try:
            import windowcapture
            windowcapture.set_preferred_hwnd(self._chosen_hwnd)
        except Exception:
            pass

    def _clear_preferred_hwnd(self):
        """Loescht die WindowCapture-Praeferenz (beim Stop). Strikt defensiv."""
        try:
            import windowcapture
            windowcapture.clear_preferred_hwnd()
        except Exception:
            pass

    # -- Auto-Update (dezentes, schliessbares Banner) --------------------
