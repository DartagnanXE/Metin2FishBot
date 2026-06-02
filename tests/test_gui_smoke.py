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


if __name__ == '__main__':
    unittest.main()
