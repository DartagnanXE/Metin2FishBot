# -*- coding: utf-8 -*-
"""ConfigWidgetsMixin -- extracted from interface/app (behaviour-preserving).

Mixin for :class:`interface.app.App`. Holds only methods (no
``__init__``, no class-level mutable state) so MRO is unaffected and every
``self`` reference resolves exactly as in the original module.
"""

from interface.app._common import *  # noqa: F401,F403


class ConfigWidgetsMixin:
    def _apply_config_to_widgets(self):
        fishing = self._cfg['fishing']
        self.bait_slider.set(fishing['bait_time'])
        self.throw_slider.set(fishing['throw_time'])
        self.start_slider.set(fishing['start_game_time'])
        self.stop_after_var.set(fishing['stop_after_enabled'])
        self.stop_after_entry.delete(0, 'end')
        self.stop_after_entry.insert(0, str(fishing['stop_after_minutes']))
        self.golden_tuna_seg.set(str(fishing['golden_tuna_action']))

        puzzle = self._cfg['puzzle']
        self.detection_seg.set(self._detect_label_for(puzzle['detection_mode']))
        self.color_seg.set(puzzle['color_mode'].capitalize())
        self.solver_seg.set(self._solver_label_for(puzzle['solver_mode']))
        try:
            self._opacity_slider.set(puzzle['overlay_opacity'])
            self._refresh_opacity_value()
        except Exception:
            pass

        window = self._cfg['window']
        self._close_metin2_var.set(window['close_on_metin2_close'])
        self._close_timer_var.set(window['close_on_timer_expire'])
        self._always_top_var.set(window['always_on_top'])
        self._tray_var.set(window['minimize_to_tray'])
        try:
            self.bait_key_btn.configure(text=str(fishing['bait_key']).upper())
            self.cast_key_btn.configure(text=str(fishing['cast_key']).upper())
        except Exception:
            pass

        inventory = self._cfg.get('inventory', {})
        try:
            self.inventory_key_btn.configure(
                text=str(inventory.get('hotkey', 'i')).upper())
            self._auto_scan_var.set(
                bool(inventory.get('auto_scan_after_fishing', False)))
        except Exception:
            pass

        # Mount (Animation-Cancel): Schalter + Tasten-Knopf.
        try:
            self._mount_var.set(bool(fishing.get('mount_enabled', False)))
            self.mount_key_btn.configure(
                text=str(fishing.get('mount_key', '3')).upper())
        except Exception:
            pass

        # Fish-Events: zwei Fenster (Wochentag + Start/Ende) + Warn-Minuten.
        try:
            events = self._cfg.get('events', {})
            ev_windows = events.get('windows', [])
            for i, widgets in enumerate(getattr(self, '_event_window_widgets',
                                                [])):
                if i >= len(ev_windows):
                    break
                w = ev_windows[i]
                widgets['day'].set(widgets['v2l'].get(w['weekday']))
                widgets['start'].delete(0, 'end')
                widgets['start'].insert(0, w['start'])
                widgets['end'].delete(0, 'end')
                widgets['end'].insert(0, w['end'])
            self._event_warn_entry.delete(0, 'end')
            self._event_warn_entry.insert(0, str(events.get('warn_minutes', 0)))
        except Exception:
            pass

        # Ranking: Opt-in-Schalter + Name.
        try:
            self._ranking_var.set(
                bool(self._cfg.get('telemetry', {}).get('enabled', False)))
            self._username_entry.delete(0, 'end')
            self._username_entry.insert(0, self._cfg.get('username', ''))
        except Exception:
            pass

    # -- kleine Helfer ----------------------------------------------------
