# -*- coding: utf-8 -*-
"""Tests for the LIVE Lagerfeuer-Braten wrapper (inventory_campfire_runner).

All headless: the module's soft-imported live deps (``pydirectinput``,
``WindowCapture``) and ``inventory.grid.auto_align`` / ``scan_inventory`` are
MONKEYPATCHED, no game / win32 needed. These pin the THREE live-wiring fixes:

  * LOCK-ONCE -- ``run_campfire_grill`` runs ``auto_align`` exactly ONCE on a
    captured frame and threads the LOCKED lattice into ``run_campfire`` so the
    drag SOURCE + tool double-click hit the grid recognition uses (the user's
    bag sits ~1 slot above DEFAULT_CALIBRATION).
  * PARK -- the managed-scan tab switch parks the cursor OFF the tab/grid after
    the click (MOVE-only, restores PAUSE), exactly like
    ``inventory_runner._Runner.switch_page`` -- so the cursor never occludes the
    slot below the tab.
  * DEFENSIVE -- a failing auto-align lock degrades to ``None`` (run_campfire
    falls back to the calibration lattice); headless park / lock never raise.
"""

import types
import unittest

import interface.inventory_campfire_runner as cr
import inventory_campfire as campfire
from inventory.constants import DEFAULT_CALIBRATION
from inventory.grid import GridLattice
from inventory import hover

try:
    import numpy as np
except Exception:                       # pragma: no cover
    np = None


def _slot(name, row, col, state='item'):
    return types.SimpleNamespace(state=state, name=name, row=row, col=col)


def _inv(pages):
    return types.SimpleNamespace(pages=pages)


class _PDI:
    """Records pydirectinput calls; ``PAUSE`` round-trips. No real input."""

    def __init__(self):
        self.PAUSE = 0.0
        self.ev = []

    def keyDown(self, k):
        self.ev.append(('kd', k))

    def keyUp(self, k):
        self.ev.append(('ku', k))

    def click(self, x=None, y=None, **_):
        self.ev.append(('click', int(x), int(y)))

    def doubleClick(self, x=None, y=None, **_):
        self.ev.append(('dc', int(x), int(y)))

    def moveTo(self, x, y):
        self.ev.append(('mv', int(x), int(y)))

    def mouseDown(self):
        self.ev.append(('down',))

    def mouseUp(self):
        self.ev.append(('up',))


class _WinCap:
    offset_x = 1000
    offset_y = 500

    def __init__(self, _name):
        pass

    def get_screenshot(self):
        if np is None:                  # pragma: no cover
            return object()
        # The toggle-safe open guard (inventory.open_probe) probes this frame
        # BEFORE any click; stamp the real tab templates so it reads OPEN and
        # the wrapper proceeds (exercising the probe on the real wiring path).
        try:
            from tests._inv_synth import stamp_open_tabs
        except Exception:               # pragma: no cover - direct invocation
            from _inv_synth import stamp_open_tabs
        return stamp_open_tabs(np.zeros((632, 802, 3), dtype=np.uint8))


class _CampfireRunnerBase(unittest.TestCase):
    def setUp(self):
        self._orig = {}
        for name in ('pydirectinput', 'WindowCapture'):
            self._orig[name] = getattr(cr, name)
        self._orig['grid_auto_align'] = cr.grid_mod.auto_align
        self._orig['find_label'] = campfire.find_label
        self._orig['sleep'] = cr.time.sleep
        # Import-inside-function seam: scan_fn does `from inventory.scanner import
        # scan_inventory`, so patch it on the module.
        import inventory.scanner as sc
        self._sc = sc
        self._orig['scan_inventory'] = sc.scan_inventory
        cr.time.sleep = lambda *a, **k: None

    def tearDown(self):
        cr.pydirectinput = self._orig['pydirectinput']
        cr.WindowCapture = self._orig['WindowCapture']
        cr.grid_mod.auto_align = self._orig['grid_auto_align']
        campfire.find_label = self._orig['find_label']
        cr.time.sleep = self._orig['sleep']
        self._sc.scan_inventory = self._orig['scan_inventory']


@unittest.skipUnless(np is not None, 'numpy required for the captured frame')
class TestLockOnceAndThread(_CampfireRunnerBase):
    def test_locks_grid_once_and_drag_uses_locked_grid(self):
        pdi = _PDI()
        cr.pydirectinput = pdi
        cr.WindowCapture = _WinCap

        locked = GridLattice(origin=(632, 245), pitch=(32, 32))
        align_calls = [0]

        def fake_align(frame, db, calib):
            align_calls[0] += 1
            return locked

        cr.grid_mod.auto_align = fake_align
        campfire.find_label = lambda *a, **k: (True, 0.99, (300, 400))

        inv = _inv({'I': [_slot('Lagerfeuer', 0, 0), _slot('Carp', 1, 2)]})
        # scan_fn calls switch_page_fn per page then returns the map.
        self._sc.scan_inventory = lambda **kw: inv

        res = cr.run_campfire_grill({'inventory': {'hotkey': 'i'}},
                                    {'Carp': 2}, db=object())

        self.assertEqual(res.status, 'done')
        # The grid was locked EXACTLY once (one fixed window -> one lock).
        self.assertEqual(align_calls[0], 1)
        # The Carp drag SOURCE uses the LOCKED grid: slot (1,2) on (632,245) +
        # offset (1000,500) = (1712, 793).
        ev = pdi.ev
        down_idx = next(i for i, e in enumerate(ev) if e[0] == 'down')
        self.assertEqual(ev[down_idx - 1], ('mv', 1712, 793))

    def test_failing_lock_degrades_to_calibration_fallback(self):
        # auto_align raising -> _lock_lattice returns None -> run_campfire uses the
        # calibration lattice (slot grabbed at the raw calib, the old behaviour),
        # and the grill still completes without raising.
        pdi = _PDI()
        cr.pydirectinput = pdi
        cr.WindowCapture = _WinCap

        def boom_align(frame, db, calib):
            raise RuntimeError('align down')

        cr.grid_mod.auto_align = boom_align
        campfire.find_label = lambda *a, **k: (True, 0.99, (300, 400))
        inv = _inv({'I': [_slot('Lagerfeuer', 0, 0), _slot('Carp', 1, 2)]})
        self._sc.scan_inventory = lambda **kw: inv

        res = cr.run_campfire_grill({'inventory': {'hotkey': 'i'}},
                                    {'Carp': 2}, db=object())
        self.assertEqual(res.status, 'done')
        # Drag SOURCE = calibration-lattice slot (1,2) + offset (NOT the 245 lock).
        from inventory.grid import lattice_from_calibration
        cl = lattice_from_calibration(DEFAULT_CALIBRATION)
        ox, oy = cl.origin
        px, py = cl.pitch
        exp = (1000 + ox + 2 * px + px // 2, 500 + oy + 1 * py + py // 2)
        ev = pdi.ev
        down_idx = next(i for i, e in enumerate(ev) if e[0] == 'down')
        self.assertEqual(ev[down_idx - 1], ('mv',) + exp)


@unittest.skipUnless(np is not None, 'numpy required for the captured frame')
class TestManagedScanParksCursor(_CampfireRunnerBase):
    def test_tab_switch_parks_off_grid(self):
        # The scan_fn._switch must park the cursor at hover.tab_park_point AFTER
        # each tab click (MOVE-only) so it never occludes the slot below the tab.
        pdi = _PDI()
        cr.pydirectinput = pdi
        cr.WindowCapture = _WinCap
        cr.grid_mod.auto_align = lambda f, d, c: GridLattice(origin=(632, 245),
                                                             pitch=(32, 32))
        campfire.find_label = lambda *a, **k: (True, 0.99, (300, 400))

        inv = _inv({'I': [_slot('Lagerfeuer', 0, 0), _slot('Carp', 1, 2)]})

        # A scan_inventory that DRIVES switch_page_fn for every page, so _switch
        # (and its park) actually runs -- then returns the map.
        def fake_scan(capture_fn=None, switch_page_fn=None, db=None, calib=None,
                      pages=()):
            for p in pages:
                if switch_page_fn is not None:
                    switch_page_fn(p)
            return inv

        self._sc.scan_inventory = fake_scan

        cr.run_campfire_grill({'inventory': {'hotkey': 'i'}},
                              {'Carp': 2}, db=object())

        park = hover.to_screen(
            [hover.tab_park_point(DEFAULT_CALIBRATION)],
            (1000, 500))[0]
        # A park MOVE to the off-grid point fired after a tab click.
        self.assertIn(('mv',) + park, pdi.ev)
        # PAUSE was restored to its original value after each parked move.
        self.assertEqual(pdi.PAUSE, 0.0)
        # The park x sits LEFT of the grid's left edge (clear of every slot).
        grid_left = int(DEFAULT_CALIBRATION['grid']['tl'][0]) + 1000
        self.assertLess(park[0], grid_left)


class TestParkAndLockHelpersDefensive(unittest.TestCase):
    def test_park_headless_is_noop(self):
        orig = cr.pydirectinput
        cr.pydirectinput = None
        try:
            cr._park_cursor((0, 0), DEFAULT_CALIBRATION)   # must not raise
        finally:
            cr.pydirectinput = orig

    def test_park_restores_pause_and_moves_once(self):
        orig = cr.pydirectinput
        pdi = _PDI()
        pdi.PAUSE = 0.123
        cr.pydirectinput = pdi
        try:
            cr._park_cursor((1000, 500), DEFAULT_CALIBRATION)
        finally:
            cr.pydirectinput = orig
        moves = [e for e in pdi.ev if e[0] == 'mv']
        self.assertEqual(len(moves), 1)            # MOVE-only, exactly one
        self.assertEqual(pdi.PAUSE, 0.123)         # restored in finally

    def test_lock_returns_none_without_window_or_db(self):
        self.assertIsNone(cr._lock_lattice(None, object(), DEFAULT_CALIBRATION))

        class _WC:
            def get_screenshot(self):
                return None
        self.assertIsNone(cr._lock_lattice(_WC(), object(), DEFAULT_CALIBRATION))

    def test_lock_returns_none_on_align_error(self):
        orig = cr.grid_mod.auto_align

        class _WC:
            def get_screenshot(self):
                return 'frame'

        def boom(*a, **k):
            raise RuntimeError('down')

        cr.grid_mod.auto_align = boom
        try:
            self.assertIsNone(
                cr._lock_lattice(_WC(), object(), DEFAULT_CALIBRATION))
        finally:
            cr.grid_mod.auto_align = orig


if __name__ == '__main__':
    unittest.main()
