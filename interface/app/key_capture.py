# -*- coding: utf-8 -*-
"""KeyCaptureMixin -- extracted from interface/app (behaviour-preserving).

Mixin for :class:`interface.app.App`. Holds only methods (no
``__init__``, no class-level mutable state) so MRO is unaffected and every
``self`` reference resolves exactly as in the original module.
"""

from interface.app._common import *  # noqa: F401,F403


class KeyCaptureMixin:
    def _key_btn(self, which):
        """Der Key-Capture-Button zu ``which`` (bait/cast/inventory).

        Registry statt if/else, damit der Fluss generisch bleibt -- bait/cast
        treffen exakt dieselben Buttons wie zuvor."""
        return {
            'bait': getattr(self, 'bait_key_btn', None),
            'cast': getattr(self, 'cast_key_btn', None),
            'inventory': getattr(self, 'inventory_key_btn', None),
        }.get(which)

    def _start_key_capture(self, which):
        """Startet die Tasten-Aufnahme fuer bait/cast/inventory: Feld -> '...Taste'.

        Generisch ueber WHICH_TO_CFG + ein {which: btn}-Registry; bait/cast
        verhalten sich byte-identisch wie zuvor."""
        try:
            btn = self._key_btn(which)
            if btn is None:
                self._capturing = None
                return
            self._capturing = (which, btn)
            btn.configure(text=t('ui.key_capture_prompt'), fg_color=TEAL_SOFT,
                          text_color=TEAL_BRIGHT)
            self.bind('<Key>', self._on_key_capture, add='+')
        except Exception:
            self._capturing = None

    def _on_key_capture(self, event):
        """Nimmt einen Tastendruck als Hotkey ab. Esc bricht ab; ungueltige
        Eingaben fallen via _validate_key auf den bisherigen Wert zurueck.

        Die Ziel-(section, key) kommt aus WHICH_TO_CFG -- so persistiert der
        Inventar-Hotkey in ``inventory.hotkey``, bait/cast wie gehabt in
        ``fishing.*_key`` (byte-identisch)."""
        if self._capturing is None:
            return
        which, btn = self._capturing
        section, cfg_key = WHICH_TO_CFG.get(which, ('fishing', which + '_key'))
        try:
            keysym = (event.keysym or '').lower()
            if keysym in ('escape',):
                self._end_key_capture(which, btn)
                return
            if keysym == 'space':
                token = 'space'
            elif len(event.char) == 1 and event.char.strip():
                token = event.char.lower()
            elif len(keysym) == 1:
                token = keysym
            else:
                token = keysym
            current = self._cfg[section][cfg_key]
            key = cfgmod._validate_key(token, current)
            self._cfg = self.controller.update_config(section, cfg_key, key)
        except Exception:
            pass
        self._end_key_capture(which, btn)

    def _end_key_capture(self, which, btn):
        """Beendet die Aufnahme: Anzeige zuruecksetzen, Binding loesen."""
        section, cfg_key = WHICH_TO_CFG.get(which, ('fishing', which + '_key'))
        try:
            self.unbind('<Key>')
        except Exception:
            pass
        self._capturing = None
        try:
            btn.configure(text=str(self._cfg[section][cfg_key]).upper(),
                          fg_color=PANEL_LIGHT, text_color=TEXT)
        except Exception:
            pass

    # -- Schliessen -------------------------------------------------------
