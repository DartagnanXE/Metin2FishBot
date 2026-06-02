# -*- coding: utf-8 -*-
"""DetectionMixin -- extracted from interface/app (behaviour-preserving).

Mixin for :class:`interface.app.App`. Holds only methods (no
``__init__``, no class-level mutable state) so MRO is unaffected and every
``self`` reference resolves exactly as in the original module.
"""

from interface.app._common import *  # noqa: F401,F403


class DetectionMixin:
    def _on_detection_change(self, label):
        """Detection-Modus gewaehlt: Wert sichern + passende Sicht-Hilfe zeigen.

        Nur bei echtem NUTZER-Klick aufgerufen (``Segmented._select``); ``set()``
        aus Config-Laden/Sprachwechsel/Startup loest den Command NICHT aus -> kein
        Overlay beim Laden (byte-stabiles Default-Verhalten bleibt erhalten).

          * Default        -> 5s-Vorschau an der FESTEN Standard-Brettlage (270,227),
          * Auto           -> Board automatisch erkennen, DANN 5s-Vorschau am Treffer,
          * Manuell ('mark')-> JEDES Mal das interaktive Mark-Overlay oeffnen.

        Waehrend eines Laufs werden keine Overlays gestartet (die Segmente sind
        dann ohnehin gesperrt). Jeder Vorschau-/Mark-Aufruf ist defensiv -- ein
        Overlay-Fehler darf das Umschalten nie unterbrechen.
        """
        mode = self._detect_l2v.get(label, cfgmod.DETECTION_MODES[0])
        self._cfg = self.controller.update_config('puzzle', 'detection_mode',
                                                  mode)
        if self.controller.running:
            return
        if mode == 'default':
            self._preview_default()
        elif mode == 'auto':
            self._preview_auto()
        elif mode == 'mark':
            self._open_mark_overlay()

    def _overlay_alpha(self):
        """Aktuelle Overlay-Deckkraft aus der Config (defensiv, mit Fallback)."""
        try:
            return float(self._cfg['puzzle']['overlay_opacity'])
        except Exception:
            return cfgmod.DEFAULTS['puzzle']['overlay_opacity']

    def _preview_default(self):
        """Zeigt ~5s die Vorschau an der FESTEN Standard-Brettlage (270,227).

        So prueft der Nutzer, ob sein 800x600-Spielfenster zur Default-Position
        passt. Strikt defensiv: ein Fehler wird geloggt, das Umschalten laeuft
        weiter."""
        try:
            import detection
            import overlay_preview
            overlay_preview.show_preview(
                detection.DEFAULT_OFFSET, board_size=detection.BOARD_SIZE,
                alpha=self._overlay_alpha())
            log.event('-', t('ui.preview_default_shown'))
        except Exception as exc:
            log.error(t('preview.unavailable'), exc=exc)

    def _preview_auto(self):
        """Erkennt das Board automatisch und zeigt dann die 5s-Vorschau am Treffer.

        Ohne echtes Spiel-Fenster (kein Screenshot) wird klar geloggt und
        uebersprungen. Findet die Erkennung nichts Eindeutiges (Fallback auf den
        Default), kommt zusaetzlich ein Hinweis, dass Auto ein echtes Brett am
        Bildschirm braucht -- die Vorschau wird trotzdem am gelieferten Offset
        gezeigt. Strikt defensiv."""
        try:
            import detection
            import overlay_preview
            try:
                from windowcapture import WindowCapture

                import constants
                shot = WindowCapture(constants.GAME_NAME).get_screenshot()
            except Exception:
                log.event('-', t('ui.preview_auto_no_window'))
                return
            offset = detection.resolve_offset(
                'auto', screenshot=shot,
                default_offset=detection.DEFAULT_OFFSET)
            if tuple(offset) == tuple(detection.DEFAULT_OFFSET):
                # Auto fiel auf den Default zurueck -> Erkennung war nicht
                # eindeutig. Vorschau trotzdem zeigen, aber Grund nennen.
                log.event('-', t('ui.preview_auto_failed'))
            overlay_preview.show_preview(
                offset, board_size=detection.BOARD_SIZE,
                alpha=self._overlay_alpha())
        except Exception as exc:
            log.error(t('preview.unavailable'), exc=exc)

    def _open_mark_overlay(self):
        """Oeffnet das interaktive Mark-Overlay (Item E -- jeder Manuell-Wechsel).

        Reine Wiederverwendung von :meth:`_on_mark` (dieselbe Persistenz).
        ``detection_seg.set(<Manuell-Label>)`` dort feuert den Command NICHT
        erneut -> keine Endlosschleife."""
        self._on_mark()

    def _on_mark(self):
        """Oeffnet das Mark-Overlay (Modul B) und speichert die Kalibrierung.

        Wird ueber die Detection-Auswahl 'Manuell'/'Manual' (Enum 'mark')
        ausgeloest. Das fruehere "kein markierter Bereich"-Statuslabel entfaellt
        (Item J) -- ist das Overlay nicht verfuegbar, geht der Hinweis nur ins
        Log (Fehlerpfad), nicht als Dauer-Hinweis ins UI."""
        try:
            from overlay_mark import pick_offset_interactive
        except Exception as exc:
            log.error(t('ui.mark_overlay_unavailable_log'), exc=exc)
            return
        try:
            result = pick_offset_interactive(alpha=self._overlay_alpha())
        except Exception as exc:
            log.error(t('ui.mark_overlay_failed'), exc=exc)
            result = None
        if result is not None:
            self._persist_mark_result(result)
            self._cfg = self.controller.update_config(
                'puzzle', 'detection_mode', 'mark')
            self.detection_seg.set(self._detect_label_for('mark'))

    def _persist_mark_result(self, result):
        offset = result.get('offset')
        if offset is not None:
            self._cfg = self.controller.update_config(
                'puzzle', 'mark_offset', [int(offset[0]), int(offset[1])])

        size = result.get('size')
        mark_size = None
        if size is not None:
            try:
                mark_size = [int(size[0]), int(size[1])]
            except (TypeError, ValueError, IndexError):
                mark_size = None
        self._cfg = self.controller.update_config(
            'puzzle', 'mark_size', mark_size)

        key_points = result.get('key_points') or {}
        mark_keypoints = {}
        try:
            for name, point in key_points.items():
                mark_keypoints[name] = [int(point[0]), int(point[1])]
        except (TypeError, ValueError, IndexError, AttributeError):
            mark_keypoints = {}
        self._cfg = self.controller.update_config(
            'puzzle', 'mark_keypoints', mark_keypoints)

    # -- Settings: Reset auf Standard (Item K) ---------------------------

    def _on_test_window(self):
        """Oeffnet das selbst-enthaltene Fake-"METIN2"-Testfenster (800x600).

        Damit findet ``FindWindow(None,'METIN2')`` ein Ziel und START laeuft
        trocken (Capture/Farb-/Board-Erkennung), ohne das echte Spiel. Strikt
        defensiv: ohne Display/bei Fehler nur ein Log-Hinweis, kein Crash."""
        try:
            from interface import testwindow
            self._test_window = testwindow.open_test_window(self)
            log.event('-', t('ui.test_window_opened'))
        except Exception as exc:
            log.error(t('ui.test_window_failed'), exc=exc)

    def _refresh_detect_note(self):
        """Erkennungsnote unten rechts -- 3 Zustaende (Item M):

          * Fenster nicht da        -> amber "Suche Metin2...".
          * da UND ~800x600 (gesund) -> leer + Resize-Knopf versteckt (wie bisher).
          * da, aber falsche Groesse -> amber Warnung mit IST-Groesse + Resize-Knopf.
        """
        self._saved_job = None
        note = getattr(self, 'detect_note', None)
        if note is None:
            return
        try:
            if not self._game_present:
                note.configure(text=t('ui.detect_searching'), text_color=AMBER)
                self._hide_resize_btn()
            elif self._game_healthy:
                note.configure(text='')
                self._hide_resize_btn()
            else:
                w, h = self._game_size
                note.configure(text=t('ui.detect_wrong_size', w=w, h=h),
                               text_color=AMBER)
                self._show_resize_btn()
        except Exception:
            pass

    def _show_resize_btn(self):
        try:
            if getattr(self, 'resize_btn', None) is not None:
                self.resize_btn.grid()
        except Exception:
            pass

    def _hide_resize_btn(self):
        try:
            if getattr(self, 'resize_btn', None) is not None:
                self.resize_btn.grid_remove()
        except Exception:
            pass

    def _poll_game(self):
        """Prueft ~1x/s passiv den Metin2-Fenster-Zustand (rein lesender
        Win32-Check -- kein Anti-Cheat-Trigger): vorhanden? richtige Groesse?
        wie viele? Spiegelt das in die Note/den Resize-Knopf/den Picker und
        beendet die App ggf. (close-on-Metin2)."""
        present, hwnd, w, h, healthy = _probe_game()
        self._game_present = present
        self._game_hwnd = hwnd
        self._game_size = (w, h)
        self._game_healthy = healthy
        self._refresh_window_picker()
        if self._saved_job is None:
            self._refresh_detect_note()
        self._maybe_close_on_metin2()
        try:
            self.after(1000, self._poll_game)
        except Exception:
            pass

    def _maybe_close_on_metin2(self):
        """Settings #3: beendet die App, wenn Metin2 (war da -> weg) schliesst.

        Der ``_game_was_present``-Latch verhindert ein Beenden beim Start, bevor
        Metin2 jemals offen war."""
        try:
            if not self._cfg['window']['close_on_metin2_close']:
                self._game_was_present = (self._game_present
                                          or self._game_was_present)
                return
            if self._game_was_present and not self._game_present:
                log.event('-', t('ui.closing_metin2_gone'))
                self._on_close()
                return
            self._game_was_present = (self._game_present
                                      or self._game_was_present)
        except Exception:
            pass

    def notify_stop(self, reason):
        """Meldet prominent, DASS + WARUM der Bot sich selbst gestoppt hat.

        Steht ~4 s in der Note (rot bei Fehler, sonst amber), danach zurueck auf
        den Ruhestatus. Wird vom Tick gerufen, wenn ein Bot sich selbst beendet
        (Zeitlimit, Fehler, Region-/Truhen-Problem)."""
        try:
            color = (DANGER if reason == t('run.reason_error_see_console')
                     else AMBER)
            self.detect_note.configure(
                text=t('ui.status_stopped', reason=reason), text_color=color)
            if self._saved_job is not None:
                self.after_cancel(self._saved_job)
            self._saved_job = self.after(4000, self._refresh_detect_note)
        except Exception:
            pass

    def notify_start_failed(self, no_window):
        """Meldet prominent (amber, ~5 s), dass der START nicht klappte -- meist
        weil das Metin2-Fenster nicht gefunden wurde (Spiel zuerst starten)."""
        try:
            reason = (t('ui.status_start_no_window') if no_window
                      else t('ui.status_start_failed'))
            self.detect_note.configure(text=reason, text_color=AMBER)
            if self._saved_job is not None:
                self.after_cancel(self._saved_job)
            self._saved_job = self.after(5000, self._refresh_detect_note)
        except Exception:
            pass

    # -- Metin2 auf 800x600 setzen (Item M) ------------------------------

    def _on_resize_game(self):
        """Setzt die CLIENT-Flaeche des gefundenen Metin2-Fensters auf 800x600.

        Nutzt ``windowcapture.set_client_size`` (gemessene Rahmen-Deltas, mit
        Rueckfall auf die festen 8/30-Masse). Strikt defensiv -- ohne gueltiges
        Handle oder bei Fehler nur ein Log-Eintrag, NIE ein Crash. Der naechste
        1s-Poll aktualisiert die Note ohnehin."""
        hwnd = getattr(self, '_game_hwnd', None)
        if not hwnd:
            return
        try:
            import windowcapture
            ok = windowcapture.set_client_size(
                hwnd, TARGET_CLIENT_W, TARGET_CLIENT_H)
        except Exception as exc:
            log.error(t('ui.resize_failed_log'), exc=exc)
            return
        if ok:
            log.event('-', t('ui.resize_done_log'))
            self._hide_resize_btn()
        else:
            log.error(t('ui.resize_failed_log'))

    # -- Mehrfenster-Picker + Ziel-HWND (Item N) -------------------------

    def flash_saved(self):
        """Zeigt kurz "saved" in der Detection-Note (nur im Ruhezustand)."""
        if self.controller.running:
            return
        try:
            self.detect_note.configure(text=t('ui.status_saved'),
                                       text_color=TEAL)
            if self._saved_job is not None:
                self.after_cancel(self._saved_job)
            self._saved_job = self.after(1200, self._refresh_detect_note)
        except Exception:
            pass
