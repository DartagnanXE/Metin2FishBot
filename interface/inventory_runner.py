"""LIVE inventory-scan orchestration -- the ONLY win32 / pydirectinput shell.

This is the thin wrapper the UI calls (on a worker thread) to run a real scan.
It adds NO recognition logic: it only builds the four callbacks
:func:`inventory.scanner.scan_inventory` already expects, then renders + diffs
the resulting :class:`~inventory.types.InventoryMap`.

  * ``capture_fn``      -> ``WindowCapture.get_screenshot`` (BGR frame)
  * ``switch_page_fn``  -> a ``pydirectinput`` click on the tab centre
  * ``verify_page_fn``  -> :func:`inventory.grid.active_page` (open-tab check)
  * ``hover_fn``        -> :meth:`_Runner._hover_clear` (the cursor sweep that
    clears the lavender glow before the de-glowed re-capture)

The hard dependencies (``pydirectinput``, :class:`WindowCapture`, ``cv2``/PIL)
are SOFT-imported so this module is IMPORT-safe headless -- the same discipline
as :mod:`windowcapture` / :mod:`inventory.assets`. The pure core
(image -> page result -> map -> diff) is fully exercised in tests by
monkeypatching these module-level names and injecting synthetic page images, so
no game is needed to test the wiring.

Differential memory: the caller (the UI) holds the previous :class:`InventoryMap`
and passes it back in as ``previous_map``; :func:`run_inventory_scan` diffs the
new scan against it and emits EXACTLY ONE warning per NEWLY-appeared unrecognised
item (never for long-standing unknowns, recognised items, or vanished slots),
and best-effort saves that item's 32x32 crop so the user can add an icon.

KNOWN LIMITATION (documented; roadmap): the inventory hotkey is a TOGGLE in
Metin2. If the inventory was ALREADY open, our open-press CLOSES it and the scan
sees no grid. We detect that (no confident slot on ANY page) and warn
``inventory.scan_not_open`` instead of dumping an all-unknown map; we do NOT
auto-press twice (racey). A future open-state probe before pressing is the fix.

ROADMAP: item HANDLING (move / use / delete a tracked key item) is out of scope.
The seam is :meth:`InventoryMap.tracked` / :meth:`InventoryMap.locations` plus
the ``tracked`` parameter here; this round only LOCATES + reports.
"""

import os
import time

from inventory import grid as grid_mod
from inventory import scanner, report, hover
from inventory.diff import diff_maps
from inventory.constants import (
    DEFAULT_CALIBRATION,
    KEY_ITEMS,
    SLOT_PX,
    HOVER_SETTLE_S,
    TAB_SETTLE_S,
    OPEN_SETTLE_S,
    PAGES,
)
import constants
from i18n import t

# Modul-Helfer + Datei-/Console-I/O leben in inventory_io; HIER in den Namespace
# re-importiert, damit (a) der Runner/``run_inventory_scan`` sie als bare globale
# Namen aufloest und (b) Tests, die ``inventory_runner._save_bgr_png`` /
# ``inventory_runner._warn`` monkeypatchen, weiterhin greifen (der Patch
# rebindet exakt den Namen, den die Runner-Funktionen zur Laufzeit nachschlagen).
from .inventory_io import (
    _default_log_fn,
    _emit_line,
    _get_db,
    _is_all_unknown,
    _save_bgr_png,
    _slot_no,
    _unknown_crop_dir,  # noqa: F401  (re-export; vom Runner genutzt)
    _warn,
)

# -- soft imports (live deps; module stays importable headless) -------------
try:  # pragma: no cover - present only on the Windows build/runtime
    import pydirectinput
except Exception:  # pragma: no cover
    pydirectinput = None

try:  # pragma: no cover
    from windowcapture import WindowCapture
except Exception:  # pragma: no cover
    WindowCapture = None


class _Runner:
    """Holds the per-scan live context (window capture, calibration, db).

    All win32 / pydirectinput / sleep happens here; the engine stays headless.
    Constructed once per :func:`run_inventory_scan` call.
    """

    def __init__(self, cfg, db, calib=DEFAULT_CALIBRATION):
        self.cfg = cfg or {}
        self.db = db
        self.calib = calib
        self.wincap = None
        self.offset = (0, 0)
        # The most recent de-glowed page image + its locked lattice, kept so a
        # flagged unknown can be cropped from exactly what was classified.
        self._last_image = None
        self._last_lattice = None
        # PER-PAGE de-glowed frame + locked lattice, keyed by page label. A
        # flagged unknown on page I/II/III must be cropped from THAT page, not
        # from whatever page happened to be captured last (page IV). Filled at
        # classify time by :meth:`note_page_frame` (driven from the wrapped
        # capture right after that page's hover sweep).
        self._page_frames = {}        # page label -> (image, lattice)
        # The page currently being hovered/recaptured; set by hover_clear so the
        # very next capture is filed against the correct page.
        self._cur_page = None

    # -- live primitives --------------------------------------------------

    def open_window(self):
        """Open the capture path (raises the SAME 'not found' the UI handles)."""
        if WindowCapture is None:
            raise RuntimeError('WindowCapture unavailable (headless)')
        self.wincap = WindowCapture(constants.GAME_NAME)
        self.offset = (self.wincap.offset_x, self.wincap.offset_y)
        return self.wincap

    def open_inventory(self, hotkey):
        """Press the configurable inventory hotkey (a key tap), then settle.

        NOTE: this hotkey is a TOGGLE; we open + scan but deliberately do NOT
        auto-close (a second press would race the scan). See module docstring.
        """
        if pydirectinput is None:
            return
        try:
            pydirectinput.keyDown(hotkey)
            pydirectinput.keyUp(hotkey)
        except Exception as exc:
            _warn('inventory.scan_page_failed', page='open',
                  detail=str(exc)[:120])
        time.sleep(OPEN_SETTLE_S)

    def capture(self):
        """Capture one BGR frame via the open window."""
        if self.wincap is None:
            return None
        return self.wincap.get_screenshot()

    def switch_page(self, page):
        """Click the tab for ``page`` (offset + calib tab centre), then settle.

        Mirrors fishingbot's offset_x/offset_y click math exactly.
        """
        if pydirectinput is None:
            return
        # New page underway: clear the "current hovered page" marker so the next
        # pre-hover verify capture is NOT mis-filed against the previous page.
        self._cur_page = None
        tabs = (self.calib or {}).get('tabs', {})
        center = tabs.get(page)
        if not center:
            return
        x = int(self.offset[0]) + int(center[0])
        y = int(self.offset[1]) + int(center[1])
        try:
            pydirectinput.click(x=x, y=y)
        except Exception as exc:
            _warn('inventory.scan_page_failed', page=page, detail=str(exc)[:120])
        time.sleep(TAB_SETTLE_S)

    def verify(self, image):
        """Return the open-tab label for ``image`` (wraps ``active_page``)."""
        return grid_mod.active_page(image, self.calib)

    def hover_clear(self, page, lattice):
        """Sweep the cursor over all 45 slot centres to clear the glow.

        MOVE ONLY (never click) so we can never pick up or drag an item. Runs at
        ``pydirectinput.PAUSE = 0`` (45 moves cost a few ms), restored in a
        ``finally``. A failure is non-fatal: we classify what we have (margin-
        primary partly covers a lingering glow). Also records the locked lattice
        (per page) so a flagged unknown can be cropped from the de-glowed
        re-capture of EXACTLY that page.

        After the sweep the cursor is parked BELOW the grid (``hover.park_point``)
        so the de-glowed re-capture is never taken with the cursor resting on a
        slot -- otherwise a hardware-cursor-in-screenshot (or its tooltip) could
        occlude that one slot and demote it to unknown. Still MOVE-only.
        """
        self._last_lattice = lattice
        # File this page's lattice now; the matching de-glowed image is joined by
        # the wrapped capture that runs immediately after this hover sweep.
        self._cur_page = page
        self._page_frames[page] = (None, lattice)
        if pydirectinput is None:
            return
        centres = hover.slot_centres(lattice)
        screen = hover.to_screen(centres, self.offset)
        old_pause = getattr(pydirectinput, 'PAUSE', None)
        park = hover.to_screen([hover.park_point(lattice)], self.offset)[0]
        try:
            pydirectinput.PAUSE = 0
            for (x, y) in screen:
                pydirectinput.moveTo(x, y)
            # Park off-grid so the de-glowed re-capture has no cursor on any slot.
            pydirectinput.moveTo(park[0], park[1])
        except Exception as exc:
            _warn('inventory.scan_page_failed', page=page, detail=str(exc)[:120])
        finally:
            try:
                pydirectinput.PAUSE = old_pause
            except Exception:
                pass
        time.sleep(HOVER_SETTLE_S)

    def note_page_frame(self, image):
        """Join ``image`` to the page that was just hovered (its de-glowed frame).

        Called by the wrapped ``capture_fn`` right after a hover sweep so the
        per-page ``(image, lattice)`` pair is complete and a later unknown crop
        comes from the CORRECT page (not the last-captured one). No-op until a
        page has been hovered (``_cur_page`` is ``None`` during the pre-hover
        verify capture, which must not overwrite a page frame).
        """
        page = self._cur_page
        if page is None:
            return
        existing = self._page_frames.get(page)
        lattice = existing[1] if existing else self._last_lattice
        self._page_frames[page] = (image, lattice)

    # -- unknown-crop save (best-effort) ----------------------------------

    def save_unknown_crop(self, change):
        """Best-effort: write the 32x32 crop of a newly-appeared unknown slot.

        Crops from the de-glowed image of the FLAGGED ITEM'S OWN PAGE
        (``change.page``) at the slot box from that page's locked lattice, writing
        ``<exe-dir>/inventory_unknowns/unknown_<page>_<row>_<col>_<ts>.png`` (see
        :func:`_unknown_crop_dir`). Falls back to the last de-glowed page only if
        the per-page frame is missing. Soft (PIL/cv2): swallows every error -- a
        missing crop must never break a scan. Returns the written path or ``None``.
        """
        frame = self._page_frames.get(change.page)
        if frame is not None and frame[0] is not None:
            image, lattice = frame
        else:
            image, lattice = self._last_image, self._last_lattice
        if image is None or lattice is None:
            return None
        try:
            box = lattice.slot_box(change.row, change.col)
            x, y = int(box[0]), int(box[1])
            crop_bgr = image[y:y + SLOT_PX, x:x + SLOT_PX, :3]
            if crop_bgr.shape[0] != SLOT_PX or crop_bgr.shape[1] != SLOT_PX:
                return None
            ts = int(time.time())
            fname = 'unknown_{}_{}_{}_{}.png'.format(
                change.page, change.row, change.col, ts)
            path = os.path.join(_unknown_crop_dir(), fname)
            if _save_bgr_png(crop_bgr, path):
                return path
        except Exception:
            return None
        return None


def run_inventory_scan(cfg, previous_map=None, *, log_fn=None, db=None,
                       tracked=KEY_ITEMS):
    """Run ONE live I->IV inventory scan; render + diff it; return the new map.

    Steps: build/reuse the DB -> open the capture window -> press the configured
    hotkey -> drive the four callbacks through
    :func:`inventory.scanner.scan_inventory` (tab click + active-page verify +
    hover-clear + auto-align + classify) -> push ``format_full`` lines to the
    Console -> diff vs ``previous_map`` -> emit exactly one warning per newly
    appeared unknown (+ best-effort crop save) -> return the new
    :class:`InventoryMap` (the caller stores it as the next ``previous_map``).

    :param cfg: the current config dict (reads ``cfg['inventory']['hotkey']``).
    :param previous_map: the last scan's map (``None`` on the first scan of a
        session -- then the new-unknown warning is SUPPRESSED, since with no
        baseline nothing is genuinely "newly appeared").
    :param log_fn: Console sink ``(line) -> None`` (default: a debuglog event).
    :param db: an :class:`ItemDB` to reuse (default: the module-cached bundled
        DB, built once).
    :param tracked: tracked-item names for the report summary (default
        KEY_ITEMS); the seam a future handler narrows.
    :return: the new :class:`InventoryMap`.
    """
    sink = log_fn or _default_log_fn
    db = db if db is not None else _get_db()
    runner = _Runner(cfg, db, calib=DEFAULT_CALIBRATION)

    _emit_line(sink, t('inventory.scan_started'))
    runner.open_window()                       # may raise 'not found' (UI handles)
    hotkey = (cfg or {}).get('inventory', {}).get('hotkey', 'i')
    runner.open_inventory(hotkey)

    # Keep the LAST de-glowed page image (fallback) AND file each page's de-glowed
    # re-capture against its own page label, so a flagged unknown is cropped from
    # the page it actually lives on (not whatever page was captured last). The
    # capture right after a hover sweep carries _cur_page set by hover_clear.
    def capture_fn():
        img = runner.capture()
        runner._last_image = img
        runner.note_page_frame(img)
        return img

    inv = scanner.scan_inventory(
        capture_fn,
        runner.switch_page,
        db,
        calib=DEFAULT_CALIBRATION,
        pages=PAGES,
        hover_fn=runner.hover_clear,
        verify_page_fn=runner.verify,
    )

    # Toggled-shut detection: a hotkey that CLOSED the inventory yields no items
    # and only unknowns (or nothing). Warn clearly instead of dumping garbage.
    if _is_all_unknown(inv):
        _warn('inventory.scan_not_open')
        _emit_line(sink, t('inventory.scan_not_open'))
        return inv

    # Render the full readout to the Console.
    for line in report.format_full(inv, names=tracked):
        _emit_line(sink, line)

    # Diff vs the previous scan; warn ONCE per newly-appeared unknown.
    diff = diff_maps(previous_map, inv)
    if previous_map is not None:
        for change in diff.new_unknown:
            _warn('inventory.new_unknown_item',
                  page=change.page, slot=_slot_no(change.row, change.col))
            path = runner.save_unknown_crop(change)
            if path:
                _warn('inventory.unknown_crop_saved', path=path)

    return inv
