# -*- coding: utf-8 -*-
"""InventoryViewMixin -- extracted from interface/app (behaviour-preserving).

Mixin for :class:`interface.app.App`. Holds only methods (no
``__init__``, no class-level mutable state) so MRO is unaffected and every
``self`` reference resolves exactly as in the original module.
"""

from interface.app._common import *  # noqa: F401,F403


class InventoryViewMixin:
    def _build_inventory_view(self, _parent):
        """Baut die Inventar-Sicht: ein grosser "Inventar scannen"-Knopf, der den
        Scan auf einem Hintergrund-Thread startet (UI nie blockieren), plus ?-Hilfe
        und eine dezente Status-Zeile (letztes Scan-Ergebnis). Die ausfuehrliche
        4-Seiten-Karte wird in die Console gedruckt (die rendert Log-Zeilen)."""
        view = self._new_view('inventory')
        self._view_header(view, t('ui.view_inventory'), t('ui.inventory_sub'))

        # Karte: der primaere Scan-Knopf (teal-Hero-Stil) + ?-Hilfe daneben.
        card = Section(view, t('ui.group_inventory'))
        card.grid(row=1, column=0, sticky='ew', pady=(0, 8))
        body = card.body
        body.grid_columnconfigure(0, weight=1)

        self._inv_scan_btn = ctk.CTkButton(
            body, text=t('ui.inventory_scan_btn'), height=44, corner_radius=12,
            font=ctk.CTkFont(size=15, weight='bold'),
            fg_color=TEAL, hover_color=TEAL_HOVER, text_color=INK,
            command=self._on_scan_inventory)
        self._inv_scan_btn.grid(row=0, column=0, sticky='ew', pady=(0, 2))
        InfoBadge(body, text=t('ui.inventory_scan_help')).grid(
            row=0, column=1, sticky='ne', padx=(6, 0))

        # Dezente Status-Zeile: letzte Scan-Zusammenfassung (vom Worker via
        # ``after`` zurueckgespiegelt). Anfangs "noch nicht gescannt".
        self._inv_status = ctk.CTkLabel(
            body, text=t('ui.inventory_never_scanned'), anchor='w',
            text_color=TEXT_FAINT, font=ctk.CTkFont(size=11), wraplength=300)
        self._inv_status.grid(row=1, column=0, columnspan=2, sticky='w',
                              pady=(6, 0))

        # Lebenden Zustand spiegeln: wird das UI WAEHREND eines Scans oder eines
        # laufenden Bots neu gebaut (z.B. EN/DE-Sprachwechsel), zeigt der frische
        # Knopf sonst faelschlich "klickbar". Der Scan-Worker heilt das ohnehin per
        # after(0,...), und die Re-Entrancy-Sperre verhindert Doppel-Scans -- das
        # hier ist die kosmetische Korrektur, damit der Knopf sofort stimmt.
        try:
            if getattr(self, '_inv_scanning', False):
                self._inv_scan_btn.configure(
                    state='disabled', text=t('ui.inventory_scanning'))
            elif self.controller.running:
                self._inv_scan_btn.configure(state='disabled')
        except Exception:
            pass

    # -- Ranking (Stats + Event-Status + Leaderboard) --------------------

    def _on_scan_inventory(self):
        """Startet einen Inventar-Scan auf einem Daemon-Thread und spiegelt das
        Ergebnis via ``after(0, ...)`` zurueck auf den GUI-Thread (Tk ist
        single-threaded: der Worker fasst NULL Widgets an). Eine Re-Entrancy-Sperre
        verhindert ueberlappende Scans. Spiegelt exakt das _start_update_download-
        Muster (bewaehrt).

        IDLE-ONLY (ship-blocker): ein Scan presst den Hotkey, klickt 4 Reiter und
        faehrt mit der Maus ueber 45 Slots (pydirectinput, globaler PAUSE=0). Liefe
        der Bot, kaempften beide Threads um denselben Cursor -> Fehlklicks im Spiel.
        Darum: laeuft der Bot, nur ein kurzer Hinweis (Laufzustand unangetastet),
        KEIN Scan -- exakt der Idle-Guard von _on_reset_settings. ``sync_controls``
        graut den Knopf zusaetzlich aus (belt-and-suspenders).

        Vor-Pruefung (Klarheit der Meldung): ist das Fenster DA, aber NICHT ~800x600,
        wuerde der Scan mangels passender Grid-Geometrie fast nur Unbekanntes lesen
        und faelschlich als "Inventar nicht offen" enden. Darum hier vorab denselben
        Groessen-Check wie die Detection (``_probe_game``) -> bei falscher Groesse die
        bestehende 800x600-Hilfe zeigen, statt in die irrefuehrende Meldung zu laufen.
        Der Check ist ein passiver Win32-Read (kein Prozessspeicher); fehlt win32
        (headless), liefert ``_probe_game`` 'nicht da' und wir scannen normal weiter
        (der Runner faengt das fehlende Fenster sauber ab)."""
        if self.controller.running:
            self._set_inv_status(t('ui.inventory_blocked_running'), AMBER)
            return
        present, _hwnd, gw, gh, healthy = _probe_game()
        if present and not healthy:
            self._set_inv_status(t('ui.detect_wrong_size', w=gw, h=gh), AMBER)
            return
        if self._inv_scanning:
            return
        self._inv_scanning = True
        try:
            self._inv_scan_btn.configure(state='disabled',
                                         text=t('ui.inventory_scanning'))
        except Exception:
            pass
        cfg = self.controller.current_config()
        prev = self._inv_last_map

        def _worker():
            try:
                from interface import inventory_runner
                inv = inventory_runner.run_inventory_scan(
                    cfg, previous_map=prev)   # loggt selbst in die Console
                self.after(0, lambda: self._inv_scan_done(inv))
            except Exception as exc:
                self.after(0, lambda: self._inv_scan_failed(exc))

        threading.Thread(target=_worker, name='inv-scan', daemon=True).start()

    def _inv_scan_done(self, inv):
        """Scan fertig (GUI-Thread): merkt die neue Map als Diff-Basis, gibt den
        Knopf frei und schreibt eine 1-Zeilen-Zusammenfassung in die Status-Zeile."""
        self._inv_last_map = inv
        self._inv_scanning = False
        try:
            self._inv_scan_btn.configure(state='normal',
                                         text=t('ui.inventory_scan_btn'))
        except Exception:
            pass
        try:
            items = len(inv.items()) if inv is not None else 0
            unknown = len(inv.unknowns()) if inv is not None else 0
            tracked = len(inv.tracked()) if inv is not None else 0
            self._set_inv_status(
                t('ui.inventory_scan_done', items=items, unknown=unknown,
                  tracked=tracked), TEAL)
        except Exception:
            pass
        self.flash_saved()

    def _inv_scan_failed(self, exc):
        """Scan fehlgeschlagen (GUI-Thread): Knopf freigeben, loggen, Status setzen.

        Fehlt das Metin2-Fenster, wirft ``WindowCapture`` denselben 'not found'-
        Text wie beim Start -- dieselbe Erkennung wie notify_start_failed."""
        self._inv_scanning = False
        try:
            self._inv_scan_btn.configure(state='normal',
                                         text=t('ui.inventory_scan_btn'))
        except Exception:
            pass
        no_window = _is_no_window_error(exc)
        try:
            log.error(t('ui.inventory_scan_failed'), exc=exc)
        except Exception:
            pass
        msg = (t('ui.inventory_no_window') if no_window
               else t('ui.inventory_scan_failed'))
        self._set_inv_status(msg, AMBER)

    def _set_inv_status(self, text, color):
        """Setzt die Inventar-Status-Zeile (defensiv; existiert das Label nicht,
        passiert nichts)."""
        try:
            self._inv_status.configure(text=text, text_color=color)
        except Exception:
            pass

    # -- Config -> Widgets -----------------------------------------------
