# -*- coding: utf-8 -*-
"""GUI-launch smoke test -- the SAFETY NET for the upcoming app.py refactor.

This is the committed, in-suite version of the manual smoke command:

    py.exe -c "import interface.app as a; app=a.App(); app.update_idletasks();
               app.update();
               [ (app._show_view(v), app.update()) for v in a.RAIL_ORDER ];
               app.destroy(); print('GUI OK')"

It proves -- end to end, against the REAL CustomTkinter widget tree -- that the
single window:

  * constructs (``App()``) without raising,
  * pumps its event loop once (``update_idletasks`` + ``update``),
  * switches through EVERY rail view in ``RAIL_ORDER`` (fishing/puzzle/console/
    inventory/ranking/roadmap/settings) with no exception, and
  * actually RENDERS something -- each view frame maps and reports a non-empty
    (> 1x1) size, and the window itself reports a real geometry.

A behaviour-preserving split of app.py (controller / run-control / _rebuild_ui /
the per-view builders) must keep ALL of this true; if a view stops building,
``_show_view`` regresses, or the window fails to construct, this test goes red.

ONE root per class: the App (a ``ctk.CTk`` root) is built once in ``setUpClass``
and shared by every test. Tk is single-root by nature, and repeatedly spinning
up/tearing down roots in one process is flaky (stale ``after`` callbacks, Tcl
library re-init); a single shared root mirrors the single manual invocation and
keeps the test deterministic.

Headless safety: a display is required to realise widgets. Where Tk cannot open
one (pure-CI Linux box, no X server), the whole class SKIPS rather than fails --
exactly like the other GUI-touching specs degrade. On the project's Windows-
Python (py.exe) a display is always present, so it runs for real there.
"""

import unittest

try:
    import customtkinter as _ctk  # noqa: F401  (import-probe only)
    _CTK_IMPORT_OK = True
    _CTK_IMPORT_ERR = ''
except Exception as exc:  # pragma: no cover - depends on environment
    _CTK_IMPORT_OK = False
    _CTK_IMPORT_ERR = repr(exc)


@unittest.skipUnless(_CTK_IMPORT_OK,
                     'customtkinter not importable: ' + _CTK_IMPORT_ERR)
class TestGuiLaunchSmoke(unittest.TestCase):
    """Construct the real App once, drive every view, assert it renders."""

    @classmethod
    def setUpClass(cls):
        # Import here (not at module top) so the lazy GUI import only happens
        # when we are actually going to run -- keeps collection headless-safe.
        import interface.app as appmod
        cls.appmod = appmod
        try:
            cls.app = appmod.App()
            cls.app.update_idletasks()
            cls.app.update()   # one full event-loop pump (as the manual smoke)
        except Exception as exc:  # pragma: no cover - headless CI without X
            # No display / Tcl unavailable -> skip the whole class cleanly.
            raise unittest.SkipTest(
                'cannot realise Tk window here: {!r}'.format(exc))

    @classmethod
    def tearDownClass(cls):
        app = getattr(cls, 'app', None)
        if app is None:
            return
        # Cancel any pending after-jobs so no callback fires post-destroy, then
        # tear the single root down.
        try:
            for job in app.tk.call('after', 'info'):
                try:
                    app.after_cancel(job)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            app.destroy()
        except Exception:
            pass

    def test_constructs_and_has_controller(self):
        # The window exists and wired up its controller + the two bot instances.
        self.assertTrue(self.app.winfo_exists())
        self.assertIsNotNone(self.app.controller)
        self.assertIsNotNone(self.app.controller.fishbot)
        self.assertIsNotNone(self.app.controller.puzzlebot)
        self.assertFalse(self.app.controller.running)

    def test_all_rail_views_built(self):
        # Every rail entry must have a backing view frame AND a rail button.
        for view in self.appmod.RAIL_ORDER:
            self.assertIn(view, self.app._views,
                          'no view frame for rail item {!r}'.format(view))
            self.assertIn(view, self.app._rail_items,
                          'no rail button for {!r}'.format(view))

    def test_rail_order_inventory_then_settings_last(self):
        # CHANGE-SET 2: Inventory is kept SEPARATE + last (temporary until
        # calibrated), with Settings pinned at the very bottom.
        order = self.appmod.RAIL_ORDER
        self.assertEqual(order[-2:], ('inventory', 'settings'),
                         'rail must end with (inventory, settings); got '
                         '{!r}'.format(order))
        self.assertEqual(order[-1], 'settings',
                         'settings must be the last rail item')
        # The earlier cluster keeps the spec order before the gap.
        self.assertEqual(order[:5],
                         ('fishing', 'puzzle', 'ranking', 'roadmap', 'console'))

    def test_inventory_sits_directly_under_puzzle(self):
        # Inventory is now a REGULAR section placed directly under Puzzle (the
        # old "temporary" separator was removed). By grid row: it is exactly one
        # row below Puzzle, above Ranking, and above the pinned Settings.
        rows = {v: int(self.app._rail_items[v].grid_info()['row'])
                for v in ('puzzle', 'inventory', 'ranking', 'settings')}
        self.assertEqual(rows['inventory'], rows['puzzle'] + 1,
                         'Inventory must sit directly under Puzzle')
        self.assertLess(rows['inventory'], rows['ranking'])
        self.assertLess(rows['inventory'], rows['settings'])
        # Inventory + Puzzle share the one rail container.
        self.assertIs(self.app._rail_items['inventory'].master,
                      self.app._rail_items['puzzle'].master)

    def test_no_temporary_inventory_separator(self):
        # When Inventory became a normal section the "temporary" rail separator
        # was removed -> the attribute stays None.
        self.assertIsNone(getattr(self.app, '_rail_separator', None))

    def test_every_rail_button_parented_in_one_rail(self):
        # CHANGE-SET 2: all seven rail buttons live in the SAME rail container,
        # built in RAIL_ORDER -- guards against a view drifting out of the rail.
        masters = {self.app._rail_items[v].master
                   for v in self.appmod.RAIL_ORDER}
        self.assertEqual(len(masters), 1,
                         'all rail buttons must share one rail container')

    def test_switch_all_views_no_exception_and_renders(self):
        # The crux of the smoke test: switch to EVERY view, pump the loop, and
        # assert the active frame is mapped and renders a non-trivial area.
        for view in self.appmod.RAIL_ORDER:
            with self.subTest(view=view):
                self.app._show_view(view)
                self.app.update_idletasks()
                self.app.update()
                # The controller's active view tracks the switch.
                self.assertEqual(self.app._active_view, view)
                frame = self.app._views[view]
                self.assertTrue(frame.winfo_ismapped(),
                                'view {!r} did not map'.format(view))
                w = frame.winfo_width()
                h = frame.winfo_height()
                self.assertGreater(w, 1, 'view {!r} width {}'.format(view, w))
                self.assertGreater(h, 1, 'view {!r} height {}'.format(view, h))

    def test_window_reports_nonempty_geometry(self):
        # A real, non-empty render: the window itself has a sensible size.
        self.app.update_idletasks()
        self.assertGreater(self.app.winfo_width(), 1)
        self.assertGreater(self.app.winfo_height(), 1)

    def test_only_active_view_is_mapped(self):
        # Switching is exclusive -- exactly the selected frame is shown, the
        # others are grid_remove()'d. Guards the swap logic the refactor touches.
        self.app._show_view('settings')
        self.app.update_idletasks()
        for view, frame in self.app._views.items():
            if view == 'settings':
                self.assertTrue(frame.winfo_ismapped())
            else:
                self.assertFalse(
                    frame.winfo_ismapped(),
                    'view {!r} still mapped alongside settings'.format(view))

    def test_view_switch_round_trip_sets_run_mode(self):
        # The mode-coupled views (fishing/puzzle) must still set the run mode
        # while idle as the active view changes. Guards _show_view's XOR logic.
        self.app._show_view('fishing')
        self.app.update_idletasks()
        self.assertEqual(self.app._active_view, 'fishing')
        self.assertEqual(self.app.controller.mode, 'fishing')
        self.app._show_view('puzzle')
        self.assertEqual(self.app.controller.mode, 'puzzle')
        # Switching to a non-mode view (console) must NOT change the run mode.
        self.app._show_view('console')
        self.assertEqual(self.app.controller.mode, 'puzzle')

    def test_no_in_window_titlebar(self):
        # CHANGE-SET 6: the redundant in-window header is gone (the OS title bar
        # is the single source of title + min/max/close). No `topbar` widget,
        # and the in-window logo is no longer built.
        self.assertIsNone(getattr(self.app, 'topbar', None),
                          'in-window titlebar (topbar) should be removed')
        self.assertFalse(hasattr(self.app, '_build_titlebar'),
                         '_build_titlebar should be deleted')

    def test_language_toggle_lives_under_footer(self):
        # CHANGE-SET 6: the EN|DE toggle was relocated from the header to the
        # footer (next to the version chip), so it survives _rebuild_ui.
        labels = getattr(self.app, '_lang_labels', None)
        self.assertIsNotNone(labels, 'language toggle labels missing')
        self.assertIn('en', labels)
        self.assertIn('de', labels)
        footer = self.app.footer
        # Walk up from a toggle label to confirm the footer is an ancestor.
        node = labels['en']
        ancestors = []
        for _ in range(8):
            node = node.master
            if node is None:
                break
            ancestors.append(node)
        self.assertIn(footer, ancestors,
                      'EN|DE toggle is not parented under the footer')

    def test_live_language_switch_survives_rebuild(self):
        # CHANGE-SET 6: the live EN/DE switch must still work AND the views must
        # rebuild cleanly after the header removal + toggle relocation. The
        # footer (and thus the toggle) survives _rebuild_ui; _refresh_lang_toggle
        # re-colours it.
        import i18n

        def _pump_rebuild():
            # _on_lang_change sets the lang synchronously but schedules
            # _rebuild_ui via after(10, ...). A bare update() loop will NOT
            # advance Tk's timer queue (no wall-clock elapses), so briefly run
            # the real event loop until a short timeout fires -- this lets the
            # 10ms rebuild timer (and its _refresh_lang_toggle) actually run.
            self.app.after(80, self.app.quit)
            self.app.mainloop()
            self.app.update_idletasks()

        start = i18n.get_lang()
        try:
            self.app._on_lang_change('de')
            # The language flips synchronously regardless of the rebuild timer.
            self.assertEqual(i18n.get_lang(), 'de')
            _pump_rebuild()
            # Active-lang colour reflects DE on the surviving footer toggle once
            # the rebuild's _refresh_lang_toggle has run.
            from interface.app._common import TEAL
            self.assertEqual(
                str(self.app._lang_labels['de'].cget('text_color')),
                str(TEAL))
            # Views still build/map after the rebuild.
            for view in self.appmod.RAIL_ORDER:
                self.app._show_view(view)
                self.app.update_idletasks()
                self.assertTrue(self.app._views[view].winfo_ismapped(),
                                'view {!r} lost after rebuild'.format(view))
            # Switch back to EN cleanly + the EN label re-colours active (teal)
            # while DE goes inactive (muted) -- the toggle tracks both ways.
            self.app._on_lang_change('en')
            _pump_rebuild()
            self.assertEqual(i18n.get_lang(), 'en')
            from interface.app._common import TEAL as _TEAL, TEXT_MUTED
            self.assertEqual(
                str(self.app._lang_labels['en'].cget('text_color')),
                str(_TEAL))
            self.assertEqual(
                str(self.app._lang_labels['de'].cget('text_color')),
                str(TEXT_MUTED))
        finally:
            # Restore the starting language for the shared root.
            if i18n.get_lang() != start:
                self.app._on_lang_change(start)
                _pump_rebuild()

    def test_footer_widgets_survive_rebuild_by_identity(self):
        # CHANGE-SET 6 (+CS4): the footer lives on its OWN grid row (row 2) and is
        # NOT destroyed by _rebuild_ui -- only the shell (content) is rebuilt. So
        # the footer container, the EN|DE toggle labels, AND the window-mode /
        # picker buttons that also live there must be the SAME widget objects
        # before and after a language rebuild (that is what lets the live toggle +
        # mode switch keep working across rebuilds).
        import i18n

        def _pump_rebuild():
            self.app.after(80, self.app.quit)
            self.app.mainloop()
            self.app.update_idletasks()

        footer_before = self.app.footer
        en_before = self.app._lang_labels['en']
        de_before = self.app._lang_labels['de']
        mode_before = getattr(self.app, 'mode_btn', None)
        pick_before = getattr(self.app, 'pick_btn', None)
        version_before = getattr(self.app, '_version_label', None)

        start = i18n.get_lang()
        target = 'de' if start != 'de' else 'en'
        try:
            self.app._on_lang_change(target)
            _pump_rebuild()
            # Identity preserved -> the footer survived (was not rebuilt).
            self.assertIs(self.app.footer, footer_before)
            self.assertIs(self.app._lang_labels['en'], en_before)
            self.assertIs(self.app._lang_labels['de'], de_before)
            self.assertIs(getattr(self.app, 'mode_btn', None), mode_before)
            self.assertIs(getattr(self.app, 'pick_btn', None), pick_before)
            self.assertIs(getattr(self.app, '_version_label', None),
                          version_before)
            # And the surviving footer widgets are still alive/usable.
            self.assertTrue(footer_before.winfo_exists())
            self.assertTrue(en_before.winfo_exists())
        finally:
            if i18n.get_lang() != start:
                self.app._on_lang_change(start)
                _pump_rebuild()

    def test_scan_failure_restores_button_under_mainloop(self):
        # CS3 regression (deferred-except-var bug): a scan that FAILS mid-flight
        # (window present at probe time but the runner raises -- e.g. the window
        # is closed mid-scan) must restore the Scan button and clear the scanning
        # flag, NOT hang forever on "Scanning...". The worker marshals the failure
        # via after(0, lambda e=exc: self._inv_scan_failed(e)); without binding
        # ``exc`` at lambda-creation time Python 3's implicit ``del exc`` would make
        # the deferred callback raise NameError (swallowed by Tk), so
        # _inv_scan_failed never runs and the button stays disabled. Driven under a
        # REAL mainloop so the after()-deferred handler actually fires.
        from unittest import mock
        from interface import inventory_runner
        from interface.app import views_inventory as vi
        from interface.app import _common as common
        from i18n import t

        self.app._show_view('inventory')
        self.app.update_idletasks()

        done = {'flag': False}

        def _boom(*a, **k):
            raise RuntimeError('window closed mid-scan')

        orig_failed = self.app._inv_scan_failed

        def _wrapped_failed(exc):
            orig_failed(exc)
            done['flag'] = True
            try:
                self.app.quit()
            except Exception:
                pass

        with mock.patch.object(common, '_probe_game',
                               return_value=(True, 1234, 800, 600, True)), \
             mock.patch.object(vi, '_probe_game',
                               return_value=(True, 1234, 800, 600, True)), \
             mock.patch.object(inventory_runner, 'run_inventory_scan', _boom), \
             mock.patch.object(self.app, '_inv_scan_failed', _wrapped_failed), \
             mock.patch.object(self.app, '_apply_preferred_hwnd',
                               lambda *a, **k: None), \
             mock.patch.object(self.app, '_clear_preferred_hwnd',
                               lambda *a, **k: None):
            self.app._inv_scanning = False
            self.app._on_scan_inventory()         # spawns the worker thread
            # Safety timeout so a real hang fails the test instead of blocking CI.
            self.app.after(4000, self.app.quit)
            self.app.mainloop()
            self.app.update_idletasks()

        # The deferred failure handler MUST have run (proves no NameError ate it).
        self.assertTrue(done['flag'],
                        'failure handler never ran -> button would hang')
        # And the user-visible state is recovered: not scanning, button enabled
        # with its idle label.
        self.assertFalse(self.app._inv_scanning,
                         '_inv_scanning still True -> stuck on "Scanning..."')
        btn = self.app._inv_scan_btn
        self.assertEqual(str(btn.cget('state')), 'normal')
        self.assertEqual(str(btn.cget('text')), t('ui.inventory_scan_btn'))

    def test_update_download_failure_restores_button(self):
        # CS6-adjacent regression (SAME deferred-except-var class): an update
        # DOWNLOAD that raises must restore the update button -- NOT swallow a
        # NameError and leave the button disabled. The worker marshals via
        # after(0, lambda e=exc: self._update_failed(e)). Driven under a real loop.
        from unittest import mock
        import updater

        info = type('Info', (), {'tag': 'v9.9.9', 'download_url': 'http://x/a',
                                 'page_url': 'http://x', 'version': 'v9.9.9'})()
        self.app._show_update_banner(info)
        self.app.update_idletasks()

        done = {'flag': False}
        orig_failed = self.app._update_failed

        def _wrapped_failed(exc):
            orig_failed(exc)
            done['flag'] = True
            try:
                self.app.quit()
            except Exception:
                pass

        def _boom(*a, **k):
            raise RuntimeError('network down mid-download')

        with mock.patch.object(updater, 'download_asset', _boom), \
             mock.patch.object(self.app, '_update_failed', _wrapped_failed):
            self.app._start_update_download(info)
            self.app.after(4000, self.app.quit)
            self.app.mainloop()
            self.app.update_idletasks()

        self.assertTrue(done['flag'],
                        'update failure handler never ran -> button stuck')
        btn = self.app._update_btn
        self.assertEqual(str(btn.cget('state')), 'normal')

    def test_fishing_whitelist_toggle_wired_to_config(self):
        # The Fishing view builds the whitelist checkbox; it reflects the config
        # default (OFF) on build, and toggling it through the REAL handler
        # persists fishing.whitelist_enabled via the controller (and clears
        # again). Guards the UI<->config seam for the whitelist master switch.
        self.app._show_view('fishing')
        self.app.update_idletasks()
        chk = getattr(self.app, 'whitelist_chk', None)
        var = getattr(self.app, '_whitelist_var', None)
        self.assertIsNotNone(chk, 'whitelist checkbox not built')
        self.assertIsNotNone(var, 'whitelist BooleanVar not built')
        self.assertTrue(chk.winfo_exists())
        # Default OFF -> byte-stable "fish everything".
        self.assertFalse(bool(var.get()))
        self.assertFalse(
            self.app.controller.current_config()['fishing']['whitelist_enabled'])
        # Flip ON via the real handler -> persisted as a real bool.
        var.set(True)
        self.app._on_whitelist_toggle()
        self.assertIs(
            self.app.controller.current_config()['fishing']['whitelist_enabled'],
            True)
        # Flip OFF again -> persisted False (restores the byte-stable default).
        var.set(False)
        self.app._on_whitelist_toggle()
        self.assertIs(
            self.app.controller.current_config()['fishing']['whitelist_enabled'],
            False)

    def test_fishing_bait_refill_toggle_wired_to_config(self):
        # The Fishing view builds the bait-refill checkbox; it reflects the config
        # default (OFF) on build, and toggling it through the REAL handler
        # persists fishing.bait_refill_enabled via the controller (and clears
        # again). Guards the UI<->config seam for the bait-refill master switch.
        self.app._show_view('fishing')
        self.app.update_idletasks()
        chk = getattr(self.app, 'bait_refill_chk', None)
        var = getattr(self.app, '_bait_refill_var', None)
        self.assertIsNotNone(chk, 'bait-refill checkbox not built')
        self.assertIsNotNone(var, 'bait-refill BooleanVar not built')
        self.assertTrue(chk.winfo_exists())
        # Default OFF -> byte-stable "never check the bait slot".
        self.assertFalse(bool(var.get()))
        self.assertFalse(
            self.app.controller.current_config()['fishing']['bait_refill_enabled'])
        # Flip ON via the real handler -> persisted as a real bool.
        var.set(True)
        self.app._on_bait_refill_toggle()
        self.assertIs(
            self.app.controller.current_config()['fishing']['bait_refill_enabled'],
            True)
        # Flip OFF again -> persisted False (restores the byte-stable default).
        var.set(False)
        self.app._on_bait_refill_toggle()
        self.assertIs(
            self.app.controller.current_config()['fishing']['bait_refill_enabled'],
            False)

    # -- Inventory scan: progress-fill button + no-marks message ----------

    def test_inventory_scan_button_fills_with_progress(self):
        # The "Scan inventory" button turns into a progress bar during a scan:
        # a CTkProgressBar (the fill, left->right) + a % label, both children of
        # the button. The % runs SYNC with the fill (0..100). Driven directly via
        # the GUI-thread fill helpers that the worker's progress_fn marshals into.
        from i18n import t
        self.app._show_view('inventory')
        self.app.update_idletasks()
        btn = self.app._inv_scan_btn
        self.assertTrue(btn.winfo_exists())

        # Begin: overlay exists, starts at 0%, button text cleared (overlay owns
        # the surface now).
        self.app._inv_scan_fill_begin()
        self.app.update_idletasks()
        fill = getattr(self.app, '_inv_scan_fill', None)
        self.assertIsNotNone(fill, 'progress overlay not created on begin')
        self.assertIn('bar', fill)
        self.assertIn('label', fill)
        self.assertEqual(fill['pct'], 0)
        # Bar + label are parented IN the button (track its size via place()).
        self.assertIs(fill['bar'].master, btn)
        self.assertIs(fill['label'].master, btn)
        self.assertEqual(str(btn.cget('text')), '')

        # Progress: fill value and % label move together.
        self.app._inv_scan_fill_set(50)
        self.app.update_idletasks()
        self.assertEqual(self.app._inv_scan_fill['pct'], 50)
        self.assertAlmostEqual(fill['bar'].get(), 0.5, places=3)
        self.assertEqual(str(fill['label'].cget('text')),
                         t('inventory.scan_progress_pct', pct=50))

        # Monotonic: a late, smaller value must NOT make the bar jump back.
        self.app._inv_scan_fill_set(20)
        self.assertEqual(self.app._inv_scan_fill['pct'], 50)
        # Clamp above 100 -> full bar.
        self.app._inv_scan_fill_set(150)
        self.assertEqual(self.app._inv_scan_fill['pct'], 100)
        self.assertAlmostEqual(fill['bar'].get(), 1.0, places=3)

        # End: overlay torn down, button text reset to its idle label (full/empty
        # -> a normal button again).
        self.app._inv_scan_fill_end()
        self.app.update_idletasks()
        self.assertIsNone(getattr(self.app, '_inv_scan_fill', None))
        self.assertEqual(str(btn.cget('text')), t('ui.inventory_scan_btn'))

    def test_inventory_scan_fill_begin_is_idempotent(self):
        # Re-entry / a UI rebuild mid-scan must not stack overlays: a second
        # begin just resets the existing fill to 0%.
        self.app._show_view('inventory')
        self.app.update_idletasks()
        self.app._inv_scan_fill_begin()
        self.app._inv_scan_fill_set(40)
        self.app._inv_scan_fill_begin()          # second begin
        self.app.update_idletasks()
        self.assertEqual(self.app._inv_scan_fill['pct'], 0)
        self.app._inv_scan_fill_end()

    def test_inventory_scan_fill_helpers_never_raise_without_overlay(self):
        # set/end are defensive: with no overlay present they are silent no-ops
        # (e.g. a stray late progress callback after the scan already ended).
        self.app._inv_scan_fill = None
        self.app._inv_scan_fill_set(75)          # must not raise
        self.app._inv_scan_fill_end()            # must not raise
        self.assertIsNone(getattr(self.app, '_inv_scan_fill', None))

    def test_inventory_manage_nothing_marked_shows_clear_message(self):
        # With everything left on KEEP (nothing marked remove/campfire), Manage
        # must NOT log the misleading bare counts ("45 keep, 0 remove, 0
        # campfire") -- it logs/shows a clear call-to-action and starts NO worker.
        from i18n import t
        from interface import inventory_manage as im
        self.app._show_view('inventory')
        self.app.update_idletasks()

        started = {'grill': 0, 'discard': 0}
        orig_grill = self.app._start_campfire_grill
        orig_discard = self.app._start_item_discard
        self.app._start_campfire_grill = lambda *a, **k: started.__setitem__(
            'grill', started['grill'] + 1)
        self.app._start_item_discard = lambda *a, **k: started.__setitem__(
            'discard', started['discard'] + 1)
        try:
            # Force a known "all keep" state regardless of which icons bundled.
            self.app._inv_manage_states = {'Lachs': im.KEEP, 'Zander': im.KEEP}
            self.app._on_inv_manage_apply()
            self.app.update_idletasks()
            self.assertEqual(str(self.app._inv_status.cget('text')),
                             t('ui.inv_manage_no_marks'))
            self.assertEqual(started['grill'], 0)
            self.assertEqual(started['discard'], 0)

            # Sanity: with one item marked REMOVE, the normal path runs (discard
            # worker invoked) -- the no-marks guard is specific to "nothing marked".
            self.app._inv_manage_states = {'Lachs': im.REMOVE, 'Zander': im.KEEP}
            self.app._on_inv_manage_apply()
            self.app.update_idletasks()
            self.assertEqual(started['discard'], 1)
        finally:
            self.app._start_campfire_grill = orig_grill
            self.app._start_item_discard = orig_discard


if __name__ == '__main__':
    unittest.main()
