# -*- coding: utf-8 -*-
"""LifecycleMixin -- extracted from interface/app (behaviour-preserving).

Mixin for :class:`interface.app.App`. Holds only methods (no
``__init__``, no class-level mutable state) so MRO is unaffected and every
``self`` reference resolves exactly as in the original module.
"""

from interface.app._common import *  # noqa: F401,F403


class LifecycleMixin:
    def _flush_stats(self):
        """Run the registered final-stats-save hook (if any). Never raises.

        Called on every exit path so accrued runtime/counters reach stats.json
        even when no catch/solve triggered the debounced save before exit."""
        try:
            hook = getattr(self, '_stats_save_hook', None)
            if callable(hook):
                hook()
        except Exception:
            pass

    def _on_close(self):
        self._flush_stats()
        try:
            cfgmod.save(self.controller.current_config())
        except Exception:
            pass
        try:
            if self._tray_icon is not None:
                self._tray_icon.stop()
        except Exception:
            pass
        try:
            self.log_panel.detach()
        except Exception:
            pass
        self.destroy()

    # -- UI-Synchronisierung ---------------------------------------------

    def _maybe_onboard(self):
        """Zeigt beim ersten Start den Onboarding-Dialog (Name + GDPR-Opt-in).

        Nur wenn noch kein Name gewaehlt UND noch nie zugestimmt/abgelehnt wurde.
        Streng defensiv -- ein Fehler hier darf den Start nie kippen."""
        try:
            from interface import onboarding
            if onboarding.needs_onboarding(self.controller.current_config()):
                onboarding.open_onboarding(self, on_done=self._on_onboarded)
        except Exception:
            pass

    def _on_onboarded(self, result):
        """Nach dem Onboarding: Widgets/Tab aktualisieren + ggf. Sender starten."""
        try:
            self._cfg = self.controller.current_config()
            # Sender-Zustand neu bewerten (Opt-in koennte jetzt an sein).
            self._start_telemetry()
            from interface import ranking_view
            ranking_view.refresh_leaderboard(self)
        except Exception:
            pass

    def _telemetry_state(self):
        """Thread-sicherer Snapshot fuer den Telemetrie-Sender.

        Liefert genau die Felder, die telemetry.client.start_sender erwartet
        (enabled/username/submit_url/interval_s + fertiges payload). Liest NUR
        unveraenderliche Kopien (current_config + app._stats) -> sicher aus dem
        Daemon-Thread aufrufbar. Wirft nie."""
        try:
            cfg = self.controller.current_config()
            telemetry = cfg.get('telemetry', {})
            username = str(cfg.get('username', '') or '')
            from telemetry import hwid, payload
            from version import __version__
            import datetime as _dt
            stats = getattr(self, '_stats', None)
            hwid_value = getattr(self, '_hwid_cache', None)
            if hwid_value is None:
                hwid_value = hwid.get_hwid()
                self._hwid_cache = hwid_value
            built = payload.build_submit(
                username, hwid_value, stats, __version__, _dt.datetime.now())
            return {
                'enabled': bool(telemetry.get('enabled', False))
                           and not self._ranking_banned,
                'username': username,
                'hwid': hwid_value,
                'submit_url': telemetry.get('submit_url', ''),
                'interval_s': telemetry.get('interval_s', 120),
                'payload': built,
            }
        except Exception:
            return {'enabled': False, 'username': '', 'hwid': '',
                    'submit_url': '', 'interval_s': 120, 'payload': {}}

    def _start_telemetry(self):
        """Startet (oder ersetzt) den Telemetrie-Daemon-Sender. Gated durch das
        Opt-in im Snapshot -- laeuft also leer, solange Telemetrie aus ist.
        Streng defensiv; wirft nie."""
        try:
            interval = int(self._cfg.get('telemetry', {}).get('interval_s', 120))
        except Exception:
            interval = 120
        try:
            from telemetry import client
            self._telemetry_thread = client.start_sender(
                self._telemetry_state, on_status=self._on_telemetry_status,
                interval=interval)
        except Exception:
            self._telemetry_thread = None

    def _on_telemetry_status(self, status):
        """Sender-Status-Callback (laeuft auf dem WORKER-Thread -> via after(0,
        ...) ins UI marshallen). 'banned' -> Ranking-Tab versteckt das Board +
        zeigt den Bann-Hinweis. Wirft nie."""
        try:
            if status == 'banned':
                self.after(0, self._handle_banned)
            elif status == 'started':
                self.after(0, lambda: log.event('-', t(
                    'telemetry.sender_started',
                    interval=self._cfg.get('telemetry', {}).get(
                        'interval_s', 120))))
            elif status == 'stopped':
                self.after(0, lambda: log.event('-',
                                                t('telemetry.sender_stopped')))
        except Exception:
            pass

    def _handle_banned(self):
        """GUI-Thread: Bann verarbeiten -- Flag setzen, Ranking-Tab umschalten."""
        try:
            self._ranking_banned = True
            log.event('-', t('telemetry.sender_banned'))
            from interface import ranking_view
            ranking_view.refresh_leaderboard(self)
        except Exception:
            pass

    # -- Status-/Detection-Note (unten rechts) ---------------------------
