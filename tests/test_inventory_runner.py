"""Tests for the LIVE scan wrapper (:mod:`interface.inventory_runner`).

No game / win32: the module's soft-imported live deps (``pydirectinput``,
``WindowCapture``) and the active-page probe are MONKEYPATCHED, and synthetic
page images are injected. This proves the LIVE LOOP WIRING + the one-shot
new-unknown warning entirely headless:

  * the configurable hotkey is pressed exactly once,
  * all four tabs I->IV are clicked,
  * the hover sweep runs (45 moveTo per page),
  * the full 4-page map is assembled + report lines emitted,
  * a newly-appeared UNKNOWN warns EXACTLY once given a previous_map, and NOT for
    a long-standing one (and never on the first scan),
  * a toggled-shut inventory (all-unknown) warns scan_not_open instead of dumping
    an all-unknown map.
"""

import os
import unittest

from inventory.itemdb import ItemDB
from inventory.constants import PAGES, COLS, ROWS, DEFAULT_CALIBRATION
from inventory.types import (
    InventoryMap, SlotResult, STATE_EMPTY, STATE_ITEM, STATE_UNKNOWN,
)

from interface import inventory_runner as ir

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

try:
    from tests import _inv_synth as synth
except Exception:  # pragma: no cover
    synth = None


class _FakePDI:
    """Records pydirectinput calls; no real input. ``PAUSE`` round-trips."""

    def __init__(self):
        self.PAUSE = 0.0
        self.keys = []        # [(name, 'down'|'up')]
        self.clicks = []      # [(x, y)]
        self.moves = []       # [(x, y)]

    def keyDown(self, k):
        self.keys.append((k, 'down'))

    def keyUp(self, k):
        self.keys.append((k, 'up'))

    def click(self, x=None, y=None, button='left'):
        self.clicks.append((x, y))

    def moveTo(self, x, y):
        self.moves.append((x, y))


class _FakeWinCap:
    """Fake WindowCapture: fixed offset; per-tab synthetic page on capture.

    The page returned tracks the last-clicked tab so the engine's auto-align +
    classify run on the right synthetic image.
    """

    offset_x = 1000
    offset_y = 500

    def __init__(self, pages_by_tab, tab_state):
        self._pages = pages_by_tab
        self._tab_state = tab_state   # mutable [current_tab]

    def get_screenshot(self):
        return self._pages[self._tab_state[0]]


@unittest.skipUnless(np is not None and synth is not None, 'numpy required')
class TestRunInventoryScan(unittest.TestCase):
    def setUp(self):
        self.db = ItemDB.from_bundled()
        if not self.db.references():
            self.skipTest('bundled icons / numpy unavailable')
        self.refs = self.db.references()
        self._orig = {}            # ir attribute name -> original value
        self._grid_orig = None     # saved grid_mod.active_page (or None)
        self._scan_align_orig = None  # saved scanner.auto_align (or None)
        # Neutralise the best-effort crop WRITE for the whole class so no test
        # ever leaves a PNG on disk (the new-unknown path calls save_unknown_crop).
        # Tests that need to INSPECT the crop install their own recorder over this
        # (also via self._orig, so teardown restores the REAL writer either way).
        self._orig['_save_bgr_png'] = ir._save_bgr_png
        ir._save_bgr_png = lambda crop_bgr, path: True

    def tearDown(self):
        # Restore patched interface.inventory_runner attributes.
        for name, val in self._orig.items():
            setattr(ir, name, val)
        # Restore the grid.active_page shim if installed.
        if self._grid_orig is not None:
            import inventory.grid as grid_mod
            grid_mod.active_page = self._grid_orig
        # Restore the scanner.auto_align shim if installed.
        if self._scan_align_orig is not None:
            ir.scanner.auto_align = self._scan_align_orig

    def _patch(self, name, val):
        if name not in self._orig:
            self._orig[name] = getattr(ir, name)
        setattr(ir, name, val)

    def _wire(self, pages_by_tab):
        """Install fakes + a tab-aware active_page; return (pdi, captured_lines).

        ``pages_by_tab`` maps each label in PAGES -> a synthetic BGR page image.
        """
        tab_state = ['I']
        pdi = _FakePDI()
        wincap = _FakeWinCap(pages_by_tab, tab_state)

        self._patch('pydirectinput', pdi)
        self._patch('WindowCapture', lambda name: wincap)

        # The runner switches tabs via pydirectinput.click; make active_page
        # report the tab whose calibrated centre matches the last click so verify
        # passes and every page is scanned. We shim switch by tracking clicks.
        tabs = DEFAULT_CALIBRATION['tabs']

        def fake_click(x=None, y=None, button='left'):
            pdi.clicks.append((x, y))
            # Map the click back to a tab label via offset + calib centre.
            for label, c in tabs.items():
                if (x == wincap.offset_x + c[0]
                        and y == wincap.offset_y + c[1]):
                    tab_state[0] = label
                    break

        pdi.click = fake_click

        # active_page on the small synth canvas can't read off-image tab pixels,
        # so report the currently-selected tab directly.
        import inventory.grid as grid_mod
        if self._grid_orig is None:
            self._grid_orig = grid_mod.active_page
        grid_mod.active_page = lambda img, calib: tab_state[0]

        # The scanner auto-aligns each captured page; on the SMALL synth canvas
        # the calibration origin (633,275) is off-image, so pin the lattice to the
        # synth origin (2,2) -- the same fixed lattice the scanner tests use --
        # so the synthesised items/unknowns land where they were stamped.
        from inventory.grid import GridLattice
        if self._scan_align_orig is None:
            self._scan_align_orig = ir.scanner.auto_align
        ir.scanner.auto_align = (
            lambda img, db, calib, **kw: GridLattice(origin=(2, 2),
                                                     pitch=(32, 32)))

        lines = []
        return pdi, lines, (grid_mod, tab_state)

    def _restore_grid(self, ctx):
        grid_mod, _ = ctx
        if self._grid_orig is not None:
            grid_mod.active_page = self._grid_orig
            self._grid_orig = None
        if self._scan_align_orig is not None:
            ir.scanner.auto_align = self._scan_align_orig
            self._scan_align_orig = None

    def _page_with(self, specs):
        """A synth page; ``specs`` maps slot index -> a layout cell dict."""
        layout = [None] * (COLS * ROWS)
        for idx, cell in specs.items():
            layout[idx] = cell
        page, _ = synth.synth_page(layout, origin=(2, 2))
        return page

    def test_full_loop_wiring(self):
        # One distinct known item per page so each page is a real grid.
        pages = {}
        for i, label in enumerate(PAGES):
            pages[label] = self._page_with({0: {'ref': self.refs[i]}})
        pdi, lines, ctx = self._wire(pages)
        try:
            cfg = {'inventory': {'hotkey': 'i'}}
            inv = ir.run_inventory_scan(cfg, previous_map=None,
                                        log_fn=lines.append, db=self.db)
        finally:
            self._restore_grid(ctx)

        self.assertIsInstance(inv, InventoryMap)
        # Hotkey pressed exactly once (down+up of 'i').
        self.assertEqual(pdi.keys, [('i', 'down'), ('i', 'up')])
        # All four tabs clicked, in order.
        self.assertEqual(len(pdi.clicks), 4)
        # Hover sweep ran: 45 slot-centre moves + 1 off-grid park move per page,
        # x 4 pages (the park keeps the cursor off any slot for the re-capture).
        self.assertEqual(len(pdi.moves), 46 * len(PAGES))
        # And NO clicks happened during the sweep (only the 4 tab clicks total) --
        # the hover sweep + park are strictly MOVE-only (can never grab an item).
        self.assertEqual(len(pdi.clicks), 4)
        # Full map assembled.
        self.assertEqual(set(inv.pages), set(PAGES))
        # Report lines emitted (a header line at least).
        self.assertTrue(any('Page I' in ln for ln in lines))
        self.assertTrue(any('Tracked found at:' in ln for ln in lines))

    def test_configurable_hotkey_used(self):
        pages = {label: self._page_with({0: {'ref': self.refs[0]}})
                 for label in PAGES}
        pdi, lines, ctx = self._wire(pages)
        try:
            cfg = {'inventory': {'hotkey': 'b'}}
            ir.run_inventory_scan(cfg, previous_map=None,
                                  log_fn=lines.append, db=self.db)
        finally:
            self._restore_grid(ctx)
        self.assertEqual(pdi.keys, [('b', 'down'), ('b', 'up')])

    def test_new_unknown_warns_once_with_previous_map(self):
        # Build a baseline scan, then a new scan where a fresh UNKNOWN appears in
        # a slot that was EMPTY before. Exactly one new-unknown warning must fire.
        warnings = []
        self._orig.setdefault('_warn', ir._warn)
        ir._warn = lambda key, **fmt: warnings.append((key, fmt))

        # An unknown blob the DB cannot recognise (bright magenta square).
        def unknown_page():
            layout = [None] * (COLS * ROWS)
            page, _ = synth.synth_page(layout, origin=(2, 2))
            # Slot (0,0) box top-left is at origin (2,2); stamp an unknown there.
            # A high-contrast magenta blob with a dark margin (a silhouette,
            # not a flat field) at slot (0,0); the flat-field guard would
            # otherwise read a uniform slot as EMPTY.
            page[2 + 6:2 + 26, 2 + 6:2 + 26, :] = np.array(
                [160, 20, 180], dtype=np.uint8)
            return page

        # Baseline: slot (0,0) EMPTY everywhere.
        base_pages = {label: self._page_with({}) for label in PAGES}
        # New: page I slot (0,0) holds an unknown.
        new_pages = {label: self._page_with({}) for label in PAGES}
        new_pages['I'] = unknown_page()

        try:
            cfg = {'inventory': {'hotkey': 'i'}}
            # First scan (previous=None): NO new-unknown warning even though the
            # baseline is all empty.
            pdi, lines, ctx = self._wire(base_pages)
            base_map = ir.run_inventory_scan(cfg, previous_map=None,
                                             log_fn=lines.append, db=self.db)
            self._restore_grid(ctx)
            base_unknown_warns = [w for w in warnings
                                  if w[0] == 'inventory.new_unknown_item']
            self.assertEqual(base_unknown_warns, [],
                             'first scan must not warn new-unknown')

            # Second scan with the baseline as previous_map -> the appeared
            # unknown on page I must warn EXACTLY once.
            warnings.clear()
            pdi2, lines2, ctx2 = self._wire(new_pages)
            ir.run_inventory_scan(cfg, previous_map=base_map,
                                  log_fn=lines2.append, db=self.db)
            self._restore_grid(ctx2)
            unknown_warns = [w for w in warnings
                             if w[0] == 'inventory.new_unknown_item']
            self.assertEqual(len(unknown_warns), 1,
                             'exactly one new-unknown warning expected')
            self.assertEqual(unknown_warns[0][1].get('page'), 'I')
        finally:
            if '_warn' in self._orig:
                ir._warn = self._orig['_warn']

    def test_long_standing_unknown_does_not_warn(self):
        # Same unknown present in BOTH the previous and the new scan -> no warning
        # (the silence rule end-to-end through the runner).
        warnings = []
        self._orig.setdefault('_warn', ir._warn)
        ir._warn = lambda key, **fmt: warnings.append((key, fmt))

        def unknown_page():
            layout = [None] * (COLS * ROWS)
            page, _ = synth.synth_page(layout, origin=(2, 2))
            # A high-contrast magenta blob with a dark margin (a silhouette,
            # not a flat field) at slot (0,0); the flat-field guard would
            # otherwise read a uniform slot as EMPTY.
            page[2 + 6:2 + 26, 2 + 6:2 + 26, :] = np.array(
                [160, 20, 180], dtype=np.uint8)
            return page

        pages_prev = {label: self._page_with({}) for label in PAGES}
        pages_prev['I'] = unknown_page()
        pages_new = {label: self._page_with({}) for label in PAGES}
        pages_new['I'] = unknown_page()

        try:
            cfg = {'inventory': {'hotkey': 'i'}}
            pdi, lines, ctx = self._wire(pages_prev)
            prev_map = ir.run_inventory_scan(cfg, previous_map=None,
                                             log_fn=lines.append, db=self.db)
            self._restore_grid(ctx)

            warnings.clear()
            pdi2, lines2, ctx2 = self._wire(pages_new)
            ir.run_inventory_scan(cfg, previous_map=prev_map,
                                  log_fn=lines2.append, db=self.db)
            self._restore_grid(ctx2)
            unknown_warns = [w for w in warnings
                             if w[0] == 'inventory.new_unknown_item']
            self.assertEqual(unknown_warns, [],
                             'a long-standing unknown must not warn')
        finally:
            if '_warn' in self._orig:
                ir._warn = self._orig['_warn']

    def test_not_open_warns_instead_of_dump(self):
        # Simulate a TOGGLED-SHUT inventory: the game world behind the panel reads
        # as a DENSE field of un-recognisable noise (most slots unknown, none a
        # confident item). The runner must warn scan_not_open and NOT push a full
        # grid dump.
        warnings = []
        self._orig.setdefault('_warn', ir._warn)
        ir._warn = lambda key, **fmt: warnings.append((key, fmt))

        def noise_page():
            layout = [None] * (COLS * ROWS)
            page, _ = synth.synth_page(layout, origin=(2, 2))
            # Stamp a high-contrast blob (silhouette, not a flat field, so it
            # reads UNKNOWN not EMPTY) into EVERY slot -> ~100% unknown fraction.
            for r in range(ROWS):
                for c in range(COLS):
                    x = 2 + c * 32
                    y = 2 + r * 32
                    page[y + 6:y + 26, x + 6:x + 26, :] = np.array(
                        [160, 20, 180], dtype=np.uint8)
            return page

        pages = {label: noise_page() for label in PAGES}
        try:
            cfg = {'inventory': {'hotkey': 'i'}}
            pdi, lines, ctx = self._wire(pages)
            inv = ir.run_inventory_scan(cfg, previous_map=None,
                                        log_fn=lines.append, db=self.db)
            self._restore_grid(ctx)
            keys = [w[0] for w in warnings]
            self.assertIn('inventory.scan_not_open', keys)
            # No full per-page grid dump on the not-open path.
            self.assertFalse(any('Tracked found at:' in ln for ln in lines))
        finally:
            if '_warn' in self._orig:
                ir._warn = self._orig['_warn']

    def test_unknown_crop_taken_from_its_own_page_not_the_last(self):
        # REGRESSION (per-page crop): a newly-appeared unknown on a NON-final page
        # (II) must be cropped from PAGE II's de-glowed image, not from the last
        # captured page (IV). We give every page a DISTINCT marker colour at slot
        # (0,0) and assert the saved crop carries PAGE II's colour.
        warnings = []
        self._orig.setdefault('_warn', ir._warn)
        ir._warn = lambda key, **fmt: warnings.append((key, fmt))

        # Distinct BGR fill per page at slot (0,0) -> a silhouette (reads UNKNOWN).
        colours = {'I': (10, 200, 20), 'II': (200, 30, 40),
                   'III': (20, 30, 210), 'IV': (210, 200, 30)}

        def unknown_page(colour):
            layout = [None] * (COLS * ROWS)
            page, _ = synth.synth_page(layout, origin=(2, 2))
            page[2 + 6:2 + 26, 2 + 6:2 + 26, :] = np.array(
                colour, dtype=np.uint8)
            return page

        # Baseline: slot (0,0) EMPTY on every page (no unknown anywhere).
        base_pages = {label: self._page_with({}) for label in PAGES}
        # New scan: a distinctly-coloured unknown at slot (0,0) on EVERY page so
        # ALL four newly appear; the crop for the page II change must come from
        # page II's image specifically.
        new_pages = {label: unknown_page(colours[label]) for label in PAGES}

        # Capture the BGR crop(s) passed to the PNG writer instead of writing
        # (setUp already redirected _save_bgr_png to a no-op; teardown restores
        # the real writer -- this just records what would have been written).
        saved = []   # [(path, bgr_copy)]
        ir._save_bgr_png = lambda crop_bgr, path: (
            saved.append((path, crop_bgr.copy())) or True)

        try:
            cfg = {'inventory': {'hotkey': 'i'}}
            pdi, lines, ctx = self._wire(base_pages)
            base_map = ir.run_inventory_scan(cfg, previous_map=None,
                                             log_fn=lines.append, db=self.db)
            self._restore_grid(ctx)

            warnings.clear()
            saved.clear()
            pdi2, lines2, ctx2 = self._wire(new_pages)
            ir.run_inventory_scan(cfg, previous_map=base_map,
                                  log_fn=lines2.append, db=self.db)
            self._restore_grid(ctx2)

            # A crop was saved whose filename names page II, and its centre pixel
            # equals PAGE II's marker colour (BGR) -- proving it came from page II,
            # not from page IV (the last captured page).
            page2_crops = [(p, c) for (p, c) in saved
                           if 'unknown_II_' in os.path.basename(p)]
            self.assertTrue(page2_crops, 'no crop saved for the page II unknown')
            _path, crop = page2_crops[0]
            # The marker fills the interior; sample a pixel well inside it.
            centre_bgr = tuple(int(v) for v in crop[16, 16, :3])
            self.assertEqual(centre_bgr, colours['II'],
                             'page II crop must carry page II colour, not IV')
            # And it must NOT be page IV's colour (the old wrong-page bug).
            self.assertNotEqual(centre_bgr, colours['IV'])
        finally:
            if '_warn' in self._orig:
                ir._warn = self._orig['_warn']


if __name__ == '__main__':
    unittest.main()
