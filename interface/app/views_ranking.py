# -*- coding: utf-8 -*-
"""RankingViewMixin -- extracted from interface/app (behaviour-preserving).

Mixin for :class:`interface.app.App`. Holds only methods (no
``__init__``, no class-level mutable state) so MRO is unaffected and every
``self`` reference resolves exactly as in the original module.
"""

from interface.app._common import *  # noqa: F401,F403


class RankingViewMixin:
    def _build_ranking_view(self, _parent):
        """Baut die Ranking-Sicht -- delegiert an interface.ranking_view, damit
        app.py nicht weiter waechst. Streng defensiv: schlaegt der Aufbau fehl,
        zeigt die Sicht nur den Kopf."""
        view = self._new_view('ranking')
        self._view_header(view, t('ui.view_ranking'), t('ui.ranking_sub'))
        try:
            from interface import ranking_view
            ranking_view.build_ranking_view(self, view)
        except Exception:
            pass
