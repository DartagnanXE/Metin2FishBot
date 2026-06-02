# -*- coding: utf-8 -*-
"""FishingPuzzleConsoleViewsMixin -- extracted from interface/app (behaviour-preserving).

Mixin for :class:`interface.app.App`. Holds only methods (no
``__init__``, no class-level mutable state) so MRO is unaffected and every
``self`` reference resolves exactly as in the original module.
"""

from interface.app._common import *  # noqa: F401,F403


class FishingPuzzleConsoleViewsMixin:
    def _build_fishing_view(self, _parent):
        view = self._new_view('fishing')
        # Inhalt OBEN gruppiert: KEIN verteilender Zwischenraum -- alle Regler sitzen
        # kompakt am oberen Rand, der Rest-Leerraum sammelt sich ruhig UNTEN (row 2
        # bleibt leer -> kollabiert auf 0). Fenster bleibt fix auf der hoechsten View
        # (Settings) -- kein Springen beim Tab-Wechsel, keine Mittel-Luecke.
        self._view_header(view, t('ui.view_fishing'), t('ui.fishing_sub'),
                          badge=t('ui.badge_primary'))

        # Karte "Timing": die drei Delay-Slider mit ?-Hilfe.
        timing = Section(view, t('ui.delays_seconds'))
        timing.grid(row=1, column=0, sticky='ew', pady=(0, 10))
        tbody = timing.body

        self.bait_slider = LabeledSlider(
            tbody, t('ui.wait_to_put_bait'),
            default=self._cfg['fishing']['bait_time'],
            command=lambda v: self.controller.update_config(
                'fishing', 'bait_time', v))
        self.bait_slider.grid(row=0, column=0, sticky='ew', pady=4)
        InfoBadge(tbody, text=t('ui.bait_delay_help')).grid(
            row=0, column=1, sticky='ne', padx=(4, 0))

        self.throw_slider = LabeledSlider(
            tbody, t('ui.wait_to_throw'),
            default=self._cfg['fishing']['throw_time'],
            command=lambda v: self.controller.update_config(
                'fishing', 'throw_time', v))
        self.throw_slider.grid(row=1, column=0, sticky='ew', pady=4)
        InfoBadge(tbody, text=t('ui.throw_delay_help')).grid(
            row=1, column=1, sticky='ne', padx=(4, 0))

        self.start_slider = LabeledSlider(
            tbody, t('ui.wait_to_start_game'),
            default=self._cfg['fishing']['start_game_time'],
            command=lambda v: self.controller.update_config(
                'fishing', 'start_game_time', v))
        self.start_slider.grid(row=2, column=0, sticky='ew', pady=4)
        InfoBadge(tbody, text=t('ui.start_delay_help')).grid(
            row=2, column=1, sticky='ne', padx=(4, 0))

        # Stop-after-Zeile (Checkbox + Minuten + ?-Hilfe). Sitzt unter dem
        # flexiblen Zwischenraum (row 3).
        stop_row = ctk.CTkFrame(view, fg_color='transparent')
        stop_row.grid(row=3, column=0, sticky='ew', pady=(2, 8))
        stop_row.grid_columnconfigure(0, weight=1)
        self.stop_after_var = ctk.BooleanVar(
            value=self._cfg['fishing']['stop_after_enabled'])
        self.stop_after_chk = ctk.CTkCheckBox(
            stop_row, text=t('ui.stop_after_time_min'),
            variable=self.stop_after_var, text_color=TEXT, fg_color=TEAL,
            hover_color=TEAL_HOVER, command=self._on_stop_after_toggle)
        self.stop_after_chk.grid(row=0, column=0, sticky='w')
        InfoBadge(stop_row, text=t('ui.stop_after_help')).grid(
            row=0, column=1, sticky='e', padx=(4, 4))
        self.stop_after_entry = ctk.CTkEntry(
            stop_row, width=64, justify='center')
        self.stop_after_entry.grid(row=0, column=2, sticky='e')
        self.stop_after_entry.insert(
            0, str(self._cfg['fishing']['stop_after_minutes']))
        self.stop_after_entry.bind('<KeyRelease>', self._on_stop_minutes)

        # Golden-Tuna-Aktion: Labels '1'/'2'/'3' -> int-Werte (byte-stabil).
        # Golden-Tuna-Hilfe = VERIFIZIERTE Wiki-Fakten (keine erfundenen Zahlen);
        # ersetzt den alten knappen Hilfetext. Default bleibt 3 (Nutzer entscheidet).
        self.golden_tuna_seg = SegmentedRow(
            view, label=t('ui.golden_tuna_action'), values=['1', '2', '3'],
            default=str(self._cfg['fishing']['golden_tuna_action']),
            command=self._on_golden_tuna_change,
            info=t('ui.golden_tuna_verified'))
        self.golden_tuna_seg.grid(row=4, column=0, sticky='ew', pady=(0, 4))

    def _build_puzzle_view(self, _parent):
        view = self._new_view('puzzle')
        # Inhalt OBEN gruppiert: KEIN verteilender Zwischenraum (row 3 bleibt leer ->
        # kollabiert auf 0). Detection + Solver sitzen kompakt oben, Rest-Leerraum
        # sammelt sich ruhig unten. Fenster bleibt fix (keine Mittel-Luecke).
        self._view_header(view, t('ui.view_puzzle'), t('ui.puzzle_sub'),
                          badge=t('ui.badge_secondary'))

        # Karte "Detection": Detection-Modus + Color-Sampling. Die Modus-Labels
        # ('Default'/'Auto'/'Manual'|'Manuell') sind sprachabhaengig -> ueber
        # value<->label-Dicts gefuehrt (interner Enum bleibt 'mark'). Manuell
        # oeffnet bei Auswahl weiterhin das interaktive Mark-Overlay.
        detect = Section(view, t('ui.board_detection'))
        detect.grid(row=1, column=0, sticky='ew', pady=(0, 8))
        dbody = detect.body
        detection_pairs = _detection_pairs()
        self._detect_v2l = {value: label for value, label in detection_pairs}
        self._detect_l2v = {label: value for value, label in detection_pairs}
        self.detection_seg = SegmentedRow(
            dbody, label='',
            values=[label for _value, label in detection_pairs],
            default=self._detect_label_for(self._cfg['puzzle']['detection_mode']),
            command=self._on_detection_change,
            info=t('ui.detection_help'), info_image=REFERENCE_IMAGE,
            info_image_size=REFERENCE_IMAGE_SIZE)
        self.detection_seg.grid(row=0, column=0, sticky='ew', pady=(0, 6))
        self.color_seg = SegmentedRow(
            dbody, label=t('ui.color_sampling'), values=['Single', 'Multi'],
            default=self._cfg['puzzle']['color_mode'].capitalize(),
            command=self._on_color_change, info=t('ui.color_sampling_help'))
        self.color_seg.grid(row=1, column=0, sticky='ew')

        # Karte "Solver": Puzzle-Methode. (Der frueher hier sitzende "Brettbereich
        # markieren"-Knopf entfaellt -- Manuell oeffnet das Overlay direkt; die
        # "kein markierter Bereich"-Statuszeile entfaellt ebenfalls.)
        solver = Section(view, t('ui.puzzle_method'))
        solver.grid(row=2, column=0, sticky='ew', pady=(0, 8))
        sbody = solver.body
        solver_pairs = _solver_pairs()
        self._solver_v2l = {value: label for value, label in solver_pairs}
        self._solver_l2v = {label: value for value, label in solver_pairs}
        self.solver_seg = SegmentedRow(
            sbody, label='',
            values=[label for _value, label in solver_pairs],
            default=self._solver_label_for(self._cfg['puzzle']['solver_mode']),
            command=self._on_solver_change, info=t('ui.puzzle_method_help'))
        self.solver_seg.grid(row=0, column=0, sticky='ew')

    def _build_console_view(self, _parent):
        view = self._new_view('console')
        view.grid_rowconfigure(1, weight=1)
        self._view_header(view, t('ui.view_console'), t('ui.console_sub'))
        self.log_panel = LogPanel(view)
        self.log_panel.grid(row=1, column=0, sticky='nsew')
        # Winziger, BEWUSST unscheinbarer "Test Window"-Knopf unter dem Log:
        # spawnt das Fake-"METIN2"-Fenster, damit START auch ohne echtes Spiel
        # laeuft. Deutlich kleiner/schlichter als die echten Knoepfe (kein
        # Fill, kleine Schrift, gedaempfte Farben) -- reines Test-Hilfsmittel.
        self.test_window_btn = ctk.CTkButton(
            view, text=t('ui.test_window'), height=22, width=92,
            corner_radius=6, fg_color='transparent', hover_color=PANEL_HOVER,
            text_color=TEXT_FAINT, border_width=1, border_color=PANEL_LIGHT,
            font=ctk.CTkFont(size=10), command=self._on_test_window)
        self.test_window_btn.grid(row=2, column=0, sticky='e', pady=(6, 0))

    # -- Inventory (manueller Scan; Ausgabe geht in die Console) ----------
