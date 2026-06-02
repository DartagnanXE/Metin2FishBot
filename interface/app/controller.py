# -*- coding: utf-8 -*-
"""BotController -- run-state + mode + the two bot instances.

Extracted verbatim from the old single-file ``interface/app.py`` (behaviour-
preserving). Re-exported by :mod:`interface.app` so ``from interface.app import
BotController`` is unchanged. ``hack.py`` wires against this surface.
"""

from interface.app._common import *  # noqa: F401,F403


class BotController:
    """Haelt Laufzustand, Modus und die beiden Bot-Instanzen.

    Schnittstelle, gegen die ``hack.py`` verdrahtet: ``mode``/``running`` lesen,
    ``fishbot``/``puzzlebot`` ansprechen, ``collect_values()`` /
    ``current_config()`` fuer die Optionen. Die UI ruft ``on_start_stop`` beim
    Button-Klick. Einstellungen werden bei jeder Aenderung (entprellt)
    gespeichert.
    """

    def __init__(self, app, fishbot, puzzlebot, cfg):
        self.app = app
        self.fishbot = fishbot
        self.puzzlebot = puzzlebot
        self._cfg = cfgmod.validate(cfg)
        self.mode = self._cfg['mode']
        self.running = False
        self.on_start = None
        self.on_stop = None
        self._save_job = None

    # -- Konfigurationszugriff -------------------------------------------

    def current_config(self):
        return cfgmod.validate(self._cfg)

    def update_config(self, section, key, value):
        """Setzt einen Wert (immutabel), loggt ihn und plant ein Auto-Speichern."""
        new_cfg = copy.deepcopy(self._cfg)
        new_cfg.setdefault(section, {})[key] = value
        self._cfg = cfgmod.validate(new_cfg)
        # Hinweis: ``key`` ist hier ALSO der positionelle 1. Parameter von t()
        # -- die Format-Felder daher als Dict uebergeben (sonst Namenskollision
        # ``t() got multiple values for argument 'key'``), damit JEDE
        # Einstellungsaenderung sauber durchlaeuft (statt im Tk-Callback zu
        # crashen und das Auto-Speichern zu ueberspringen).
        log.event('-', t('ui.setting_changed').format(
            section=section, key=key, value=value))
        self._schedule_save()
        return self._cfg

    def update_username(self, name):
        """Setzt den top-level Schluessel ``username`` (immutabel) + Auto-Save.

        ``username`` ist KEIN section-key (anders als update_config), daher ein
        eigener Pfad. Validierung (strip/cap) erledigt cfgmod.validate. Wirft nie."""
        new_cfg = copy.deepcopy(self._cfg)
        new_cfg['username'] = name
        self._cfg = cfgmod.validate(new_cfg)
        log.event('-', t('ui.setting_changed').format(
            section='username', key='username', value=self._cfg['username']))
        self._schedule_save()
        return self._cfg

    def set_mode(self, mode):
        if mode in cfgmod.APP_MODES and not self.running:
            self.mode = mode
            new_cfg = copy.deepcopy(self._cfg)
            new_cfg['mode'] = mode
            self._cfg = cfgmod.validate(new_cfg)
            log.event('-', t('ui.mode_switched', mode=mode))
            self._schedule_save()

    def collect_values(self):
        return cfgmod.to_values(self._cfg)

    def set_language(self, lang):
        """Speichert die gewaehlte UI-Sprache ('en'/'de') in der Config."""
        new_cfg = copy.deepcopy(self._cfg)
        new_cfg['language'] = lang
        self._cfg = cfgmod.validate(new_cfg)
        self._schedule_save()

    def reset_to_defaults(self):
        """Setzt ALLES auf die Auslieferungs-Standardwerte (Item K).

        Nur im Leerlauf erlaubt (laeuft der Bot -> ``False``, kein Effekt). Baut
        die Config frisch aus ``merge_defaults({})`` -> validiert -> speichert
        sofort. Immutabel (neues Dict). Der Aufrufer (UI) wendet die Defaults
        danach auf alle Widgets an (Neuaufbau). Gibt ``True`` bei Erfolg.
        """
        if self.running:
            return False
        self._cfg = cfgmod.validate(cfgmod.merge_defaults({}))
        self.mode = self._cfg['mode']
        cfgmod.save(self._cfg)
        log.event('-', t('ui.reset_done_log'))
        return True

    # -- Auto-Speichern (entprellt) --------------------------------------

    def _schedule_save(self):
        """Plant ein Speichern in ~0.7s; weitere Aenderungen verschieben es.

        Schuetzt vor Datenverlust bei Absturz (statt nur beim Schliessen). Der
        Aufruf laeuft im GUI-Thread (after); faellt auf Sofort-Speichern zurueck,
        falls kein Scheduler verfuegbar ist.
        """
        try:
            if self._save_job is not None:
                self.app.after_cancel(self._save_job)
            self._save_job = self.app.after(700, self._do_save)
        except Exception:
            self._do_save()

    def _do_save(self):
        self._save_job = None
        try:
            cfgmod.save(self._cfg)
            log.event('-', t('ui.settings_saved'))
            self.app.flash_saved()
        except Exception:
            pass

    # -- Start/Stop -------------------------------------------------------

    def on_start_stop(self):
        try:
            if self.running:
                log.section(t('ui.stop_pressed_manual'))
                self.set_running(False)
                # Mehrfenster-Wahl (Item N) nur fuer den aktiven Lauf gueltig ->
                # beim Stop die Praeferenz loeschen, damit Leerlauf-Captures
                # wieder byte-identisch FindWindow nutzen.
                self.app._clear_preferred_hwnd()
                if callable(self.on_stop):
                    self.on_stop()
            else:
                log.section(t('ui.start_pressed', mode=self.mode))
                # Vom Nutzer gewaehltes Ziel-HWND (Item N) VOR dem Start setzen,
                # damit WindowCapture(...) es trifft. Ohne Wahl -> None ->
                # FindWindow-Pfad (byte-identisch zu frueher).
                self.app._apply_preferred_hwnd()
                if callable(self.on_start):
                    self.on_start()
                else:
                    self._fallback_start()
                self.set_running(True)
        except Exception as exc:
            self.set_running(False)
            # Spielfenster-nicht-gefunden ist ein NORMALER Fall (Spiel nicht offen)
            # -> klar im UI melden, KEIN alarmierender Traceback (windowcapture +
            # fishingbot haben den Grund schon geloggt). Andere Fehler: voll loggen.
            msg = str(exc)
            no_window = ('nicht gefunden' in msg or 'not found' in msg.lower())
            if no_window:
                log.event('-', t('ui.start_aborted_no_window'))
            else:
                log.error(t('ui.start_stop_toggle_failed'), exc=exc)
            self.app.notify_start_failed(no_window)

    def _fallback_start(self):
        values = self.collect_values()
        if self.mode == 'fishing':
            self.fishbot.set_to_begin(values)
            self.fishbot.botting = True
            self.puzzlebot.botting = False
        else:
            self.puzzlebot.set_to_begin(values)
            self.puzzlebot.botting = True
            self.fishbot.botting = False

    def set_running(self, running):
        self.running = bool(running)
        if not self.running:
            self.fishbot.botting = False
            self.puzzlebot.botting = False
        self.app.sync_controls()
