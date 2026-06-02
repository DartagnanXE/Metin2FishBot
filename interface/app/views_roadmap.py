# -*- coding: utf-8 -*-
"""RoadmapViewMixin -- extracted from interface/app (behaviour-preserving).

Mixin for :class:`interface.app.App`. Holds the read-only Roadmap view plus its
``ROADMAP_GROUPS`` class attribute. Inheriting the attribute on a mixin keeps
``App.ROADMAP_GROUPS`` resolvable exactly as before (class attribute via MRO).
"""

from interface.app._common import *  # noqa: F401,F403


class RoadmapViewMixin:
    # -- Roadmap (read-only, geplante Features; DARF scrollen) ------------

    # Gruppen + ihre Items (Uebersetzungs-Keys). Reine Anzeige -- keine Logik.
    ROADMAP_GROUPS = (
        ('ui.roadmap_group_recognition',
         ('ui.roadmap_rec_inv_pages', 'ui.roadmap_rec_inv_slots',
          'ui.roadmap_rec_key_items', 'ui.roadmap_rec_carbon_rod')),
        ('ui.roadmap_group_automation',
         ('ui.roadmap_auto_bait', 'ui.roadmap_auto_boxes',
          'ui.roadmap_auto_switch', 'ui.roadmap_auto_multiwin')),
        ('ui.roadmap_group_stats',
         ('ui.roadmap_stats_puzzle', 'ui.roadmap_stats_fishing',
          'ui.roadmap_stats_inventory')),
        ('ui.roadmap_group_info',
         ('ui.roadmap_info_tuna', 'ui.roadmap_info_event_end',
          'ui.roadmap_info_calc')),
    )

    def _build_roadmap_view(self, _parent):
        """Baut die Roadmap-Sicht: gruppierte, read-only Liste geplanter Features
        mit dezenten "geplant"-Chips. EINZIGE scrollbare Sicht (Info-Liste, keine
        Steuerung) -- ``CTkScrollableFrame`` faengt ueberlange Inhalte ab."""
        view = self._new_view('roadmap')
        view.grid_rowconfigure(1, weight=1)
        self._view_header(view, t('ui.view_roadmap'), t('ui.roadmap_sub'),
                          badge=t('ui.roadmap_chip'))

        scroller = ctk.CTkScrollableFrame(view, fg_color='transparent')
        scroller.grid(row=1, column=0, sticky='nsew')
        scroller.grid_columnconfigure(0, weight=1)

        for row, (group_key, item_keys) in enumerate(self.ROADMAP_GROUPS):
            card = Section(scroller, t(group_key))
            pad_bottom = 8 if row < len(self.ROADMAP_GROUPS) - 1 else 0
            card.grid(row=row, column=0, sticky='ew', pady=(0, pad_bottom))
            body = card.body
            for i, item_key in enumerate(item_keys):
                self._roadmap_item(body, i, t(item_key))

    def _roadmap_item(self, parent, row, text):
        """Eine Roadmap-Zeile: Item-Text (links, umbrechend) + "geplant"-Chip
        (rechts, kleine Pille). Read-only -- keine Buttons/Commands."""
        line = ctk.CTkFrame(parent, fg_color='transparent')
        line.grid(row=row, column=0, sticky='ew', pady=2)
        line.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(line, text=text, anchor='w', justify='left',
                     text_color=TEXT, font=ctk.CTkFont(size=12),
                     wraplength=300).grid(row=0, column=0, sticky='w')
        ctk.CTkLabel(line, text=' ' + t('ui.roadmap_chip') + ' ',
                     text_color=TEAL_BRIGHT, fg_color=TEAL_SOFT,
                     corner_radius=999,
                     font=ctk.CTkFont(size=9, weight='bold')).grid(
            row=0, column=1, sticky='e', padx=(6, 0))
