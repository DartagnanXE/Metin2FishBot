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

TOGGLE-SAFE OPEN (the fix for the old "hotkey toggled it shut" limitation):
the inventory hotkey is a TOGGLE in Metin2, so before any press the runner now
PROBES the open state via :func:`inventory.open_probe.ensure_inventory_open`
(template match on the four page tabs) and presses only when the bag is
actually closed, re-verifying after every press. If the bag cannot be verified
open the scan ABORTS with ``inventory.scan_not_open`` BEFORE any tab click --
a tab click on a closed bag lands in the 3D world and walks the character off.
The post-scan all-unknown check stays as a second line of defence.

ROADMAP: item HANDLING (move / use / delete a tracked key item) is out of scope.
The seam is :meth:`InventoryMap.tracked` / :meth:`InventoryMap.locations` plus
the ``tracked`` parameter here; this round only LOCATES + reports.
"""

import os
import time

from inventory import grid as grid_mod
from inventory import scanner, report, hover
from inventory import open_probe
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
    pydirectinput.PAUSE = 0.05  # down->up needs a hold (~3 frames) or the game ignores tab clicks; 0 made the scan stick on page I
except Exception:  # pragma: no cover
    pydirectinput = None

try:  # pragma: no cover
    from windowcapture import WindowCapture
except Exception:  # pragma: no cover
    WindowCapture = None

try:  # pragma: no cover - present only on the Windows build/runtime
    import win32gui
except Exception:  # pragma: no cover
    win32gui = None


def _window_present():
    """Cheap, prompt check that a target Metin2 window EXISTS (CS3 anti-hang).

    Belt-and-suspenders guard so :func:`run_inventory_scan` NEVER enters the long
    pydirectinput tab-click + 45-slot hover loop (with its ``time.sleep`` settles)
    when there is no window to scan -- the bug where "Scan inventory" with no game
    open hung forever on "scanning...".

    Honours a user-picked target first: if the multi-window picker set a preferred
    HWND (Item N) and it is still valid + visible, that counts as present. Otherwise
    falls back to ``FindWindow(None, GAME_NAME)`` -- the SAME lookup
    :class:`WindowCapture` performs. Purely passive win32 reads (no process memory).

    Returns ``True`` only when a window is genuinely there. Headless / missing
    win32 -> ``False`` (so a direct headless call early-returns instead of spinning;
    the real runtime has win32). Never raises.
    """
    if win32gui is None:
        return False
    try:
        import windowcapture as _wc
        pref = _wc.get_preferred_hwnd()
        if pref and win32gui.IsWindow(pref) and win32gui.IsWindowVisible(pref):
            return True
    except Exception:
        pass
    try:
        hwnd = win32gui.FindWindow(None, constants.GAME_NAME)
        return bool(hwnd) and bool(win32gui.IsWindowVisible(hwnd))
    except Exception:
        return False


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
        # PHASE-1 capture buffer (page label -> raw frame); set by the two-phase
        # runner so PHASE-2's align_fn can map a frame back to its page for the
        # per-page unknown crop. Empty until capture_pages has run.
        self._capture_buffer = {}

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

        NOTE: this hotkey is a TOGGLE; the caller decides WHETHER to press (see
        :func:`_ensure_inventory_open`) -- this method only performs the tap.

        PER-OPERATION PAUSE (the v1.1.3 lesson): the scan flow forces the
        module PAUSE to 0.05 for its mouse work, but a KEYBOARD tap needs the
        0.1s down->up hold or the game's per-frame DirectInput poll ignores it
        entirely (exactly the v1.1.1/v1.1.2 fishing-key regression). Force 0.1
        around this one tap and restore afterwards.
        """
        if pydirectinput is None:
            return
        old_pause = getattr(pydirectinput, 'PAUSE', None)
        try:
            pydirectinput.PAUSE = 0.1   # keyboard hold; mouse stays 0.05
            pydirectinput.keyDown(hotkey)
            pydirectinput.keyUp(hotkey)
        except Exception as exc:
            _warn('inventory.scan_page_failed', page='open',
                  detail=str(exc)[:120])
        finally:
            try:
                pydirectinput.PAUSE = old_pause
            except Exception:
                pass
        time.sleep(OPEN_SETTLE_S)

    def park_cursor(self):
        """MOVE the cursor to the neutral off-tab park point (never a click).

        Used before every open-probe capture so the hardware cursor / a tab
        tooltip cannot sit on the tab row and distort the probe. Same park
        point + PAUSE=0 discipline as :meth:`switch_page`. Non-fatal on error.
        """
        if pydirectinput is None:
            return
        try:
            park = hover.to_screen([hover.tab_park_point(self.calib)],
                                   self.offset)[0]
        except Exception:
            return
        old_pause = getattr(pydirectinput, 'PAUSE', None)
        try:
            pydirectinput.PAUSE = 0
            pydirectinput.moveTo(park[0], park[1])
        except Exception:
            pass
        finally:
            try:
                pydirectinput.PAUSE = old_pause
            except Exception:
                pass

    def capture(self):
        """Capture one BGR frame via the open window."""
        if self.wincap is None:
            return None
        return self.wincap.get_screenshot()

    def switch_page(self, page):
        """Click the tab for ``page`` (offset + calib tab centre), PARK the cursor
        off the inventory, then settle.

        Mirrors fishingbot's offset_x/offset_y click math exactly for the click.
        After the click the cursor would otherwise rest ON the tab button (which
        sits just above the grid) and its tooltip/hardware-cursor could occlude
        the top slot row on the captured page. So we MOVE the cursor to a neutral
        park point clear of every tab + slot (:func:`hover.tab_park_point`) BEFORE
        the page is captured. MOVE-only (never a click) at ``PAUSE=0`` (restored in
        a ``finally``); a failed park is non-fatal (we still settle + capture).
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
        park = hover.to_screen([hover.tab_park_point(self.calib)], self.offset)[0]
        old_pause = getattr(pydirectinput, 'PAUSE', None)
        try:
            pydirectinput.click(x=x, y=y)
            # Park the cursor OFF the tab/grid before the capture so neither the
            # cursor nor a tab tooltip occludes a slot (esp. the top row).
            pydirectinput.PAUSE = 0
            pydirectinput.moveTo(park[0], park[1])
        except Exception as exc:
            _warn('inventory.scan_page_failed', page=page, detail=str(exc)[:120])
        finally:
            try:
                pydirectinput.PAUSE = old_pause
            except Exception:
                pass
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

    def note_page_recognised(self, page, image, lattice):
        """File a page's ``(image, lattice)`` by EXPLICIT label (align-once seam).

        The scanner now locks the grid once and reuses it across tabs, so it can
        no longer hand each page through the aligner; instead it calls this once
        per page with the page LABEL, image, and the (shared) locked lattice. We
        file ``(image, lattice)`` under ``page`` for that page's unknown crop and
        keep ``_last_lattice`` as the crop fallback. Pure bookkeeping; never
        raises. Supersedes the object-identity :meth:`note_recognised_page` (kept
        for back-compat with any direct align_fn caller).
        """
        self._last_lattice = lattice
        if page is not None:
            self._page_frames[page] = (image, lattice)

    def note_recognised_page(self, image, lattice):
        """File a page's ``(image, lattice)`` as it is auto-aligned in PHASE 2.

        The two-phase fast path classifies the buffered raw frames after capture,
        so the per-page crop source is recorded HERE (from the recognise-phase
        ``align_fn`` wrapper). The aligner gets only the image + lattice, so we
        map the frame back to its page label by OBJECT IDENTITY against the
        capture buffer (the same ndarray is passed straight through). Also keeps
        ``_last_lattice`` as the crop fallback. Pure bookkeeping; never raises.
        """
        self._last_lattice = lattice
        page = self._page_of_image(image)
        if page is not None:
            self._page_frames[page] = (image, lattice)

    def _page_of_image(self, image):
        """Map a buffered frame back to its page label by object identity.

        :meth:`note_recognised_page` gets only the image + lattice; the page
        label lives in the capture buffer the runner stashed. Identity match is
        exact (the same ndarray object is passed straight through), so there is
        no ambiguity even if two pages happened to be pixel-equal.
        """
        for label, img in self._capture_buffer.items():
            if img is image:
                return label
        return None

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


def _ensure_inventory_open(runner, hotkey):
    """Toggle-safe open for the scan flow (module-level so tests can patch it).

    Wraps :func:`inventory.open_probe.ensure_inventory_open` with the runner's
    capture / key-tap / cursor-park primitives. Returns ``True`` (verified
    open), ``False`` (caller must abort -- a tab click on a closed bag walks
    the character into the world), or falls back to the historical single
    blind press and returns ``True`` when the probe is unavailable (headless;
    the live EXE always bundles numpy/PIL + the templates).

    With NO input device at all (``pydirectinput`` is None: headless tests /
    the fake test window, which is drawn already-open) there is nothing that
    could click into the world, so the guard passes -- the historical
    behaviour for that path.
    """
    if pydirectinput is None:
        return True
    ok = open_probe.ensure_inventory_open(
        runner.capture,
        lambda: runner.open_inventory(hotkey),
        runner.calib,
        park_fn=runner.park_cursor)
    if ok is None:
        runner.open_inventory(hotkey)
        return True
    return ok


# -- cross-session grid-lock persistence ------------------------------------
# The inventory window is FIXED per install, so the auto_align lock found by the
# first (cold, ~seconds) sweep is reusable next session. We persist it to a tiny
# sidecar next to config.json and re-seed inventory.grid's session cache on the
# FIRST scan of a process -- that scan then skips the cold sweep too. The grid
# module re-validates the seeded lock with its refine-probe (a MOVED window
# collapses the count -> cold fallback), so a stale sidecar can never mislock.
_GRID_LOCK_FILE = 'grid_lock.json'
_grid_lock_loaded = False


def _grid_lock_path():
    """Sidecar path next to config.json (frozen: %APPDATA%). None on failure."""
    try:
        from .config.paths import sibling_path
        return sibling_path(_GRID_LOCK_FILE)
    except Exception:
        return None


def _seed_grid_lock_once():
    """Re-seed grid's session cache from the sidecar ONCE per process. Never raises."""
    global _grid_lock_loaded
    if _grid_lock_loaded:
        return
    _grid_lock_loaded = True
    try:
        import json
        path = _grid_lock_path()
        if path and os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as fh:
                grid_mod.import_align_cache(json.load(fh))
    except Exception:
        pass


def _save_grid_lock():
    """Persist grid's current session lock to the sidecar (best-effort). Never raises."""
    try:
        import json
        data = grid_mod.export_align_cache()
        if not data:
            return
        path = _grid_lock_path()
        if path:
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(data, fh)
    except Exception:
        pass


def run_inventory_scan(cfg, previous_map=None, *, log_fn=None, db=None,
                       tracked=KEY_ITEMS, progress_fn=None):
    """Run ONE live I->IV inventory scan; render + diff it; return the new map.

    TWO-PHASE (fast): build/reuse the DB -> open the capture window -> press the
    configured hotkey -> PHASE 1 click I->II->III->IV and buffer one raw frame
    per tab (:func:`inventory.scanner.capture_pages`; just switch + settle +
    capture, NO recognition between tabs, so the cursor is released quickly) ->
    PHASE 2 auto-align + classify the 4 buffered frames OFF the input device with
    the 180 slots fanned across a thread pool
    (:func:`inventory.scanner.recognize_pages`) -> push the found-items list to
    the Console -> diff vs ``previous_map`` -> emit exactly one warning per newly
    appeared unknown (+ best-effort crop save) -> return the new
    :class:`InventoryMap` (the caller stores it as the next ``previous_map``).

    The cursor-sweep HOVER glow-clear of the old interleaved path is dropped here
    (it needed a per-page auto-align mid-capture, which is exactly the recognition
    work Phase 1 defers): freshly-caught lavender glow on the few just-caught
    slots is covered by the matcher's margin-primary safety net, and the win is
    that the input device is busy only for the four tab settles instead of for the
    whole 4x45-slot recognise. Each buffered raw frame doubles as that page's crop
    source, so a flagged unknown is still cropped from its OWN page.

    :param cfg: the current config dict (reads ``cfg['inventory']['hotkey']``).
    :param previous_map: the last scan's map (``None`` on the first scan of a
        session -- then the new-unknown warning is SUPPRESSED, since with no
        baseline nothing is genuinely "newly appeared").
    :param log_fn: Console sink ``(line) -> None`` (default: a debuglog event).
    :param db: an :class:`ItemDB` to reuse (default: the module-cached bundled
        DB, built once).
    :param tracked: tracked-item names for the report summary (default
        KEY_ITEMS); the seam a future handler narrows.
    :param progress_fn: optional ``(done, total) -> None`` for LIVE slot-granular
        UI feedback over the 180 slots (the worker threads call it as each slot
        completes, so a Tk caller must marshal via ``after``). ``done`` rises
        monotonically 1..total. Purely cosmetic and wrapped defensively.
    :return: the new :class:`InventoryMap`.
    """
    sink = log_fn or _default_log_fn
    db = db or _get_db()
    runner = _Runner(cfg, db, calib=DEFAULT_CALIBRATION)

    _emit_line(sink, t('inventory.scan_started'))

    # CS3 (anti-hang): prompt window-presence guard BEFORE any pydirectinput
    # tab-click loop (those accumulate time.sleep settles). With no Metin2 window
    # open the old path could spin forever on "scanning...". Here we abort
    # cleanly, emit a clear not-open line, warn the Console and return an EMPTY
    # map -- the engine never hangs, even when called directly (tests monkeypatch
    # _window_present). Tests assert ZERO clicks/moves.
    if not _window_present():
        _warn('inventory.scan_no_window')
        _emit_line(sink, t('inventory.scan_no_window'))
        from inventory.types import InventoryMap
        return InventoryMap(pages={})

    # Mouse clicks register fine at 0.05 (proven by the live tab-switch); a prior
    # fishing run raises PAUSE to 0.1 for the keyboard, so force 0.05 back here so
    # the (mouse-only) scan stays fast.
    if pydirectinput is not None:
        pydirectinput.PAUSE = 0.05
    # Re-seed the grid lock from last session so THIS scan can skip the cold sweep
    # when the window has not moved (grid re-validates the seed -> safe on a move).
    _seed_grid_lock_once()

    runner.open_window()                       # may raise 'not found' (UI handles)
    hotkey = (cfg or {}).get('inventory', {}).get('hotkey', 'i')
    # TOGGLE-SAFE: probe the open state and press only when actually closed
    # (see module docstring). On a verified-closed bag we ABORT before any tab
    # click -- clicking a tab position on a closed bag is a left-click into the
    # 3D world and walks the character off.
    if not _ensure_inventory_open(runner, hotkey):
        _warn('inventory.scan_not_open')
        _emit_line(sink, t('inventory.scan_not_open'))
        from inventory.types import InventoryMap
        return InventoryMap(pages={})

    # PHASE 1 (fast capture): buffer each page's raw frame; remember the last as
    # the crop fallback. No hover, no recognition -- just switch + capture.
    _emit_line(sink, t('inventory.scan_capturing'))

    def capture_fn():
        img = runner.capture()
        runner._last_image = img
        return img

    captured = scanner.capture_pages(
        capture_fn,
        runner.switch_page,
        pages=PAGES,
        verify_page_fn=runner.verify,
    )
    # Hand the buffer to the runner so PHASE-2 can map an aligned frame back to
    # its page label for the per-page unknown crop.
    runner._capture_buffer = captured

    # PHASE 2 (parallel recognise): record each page's locked lattice + frame so a
    # flagged unknown crops from its OWN page, then classify all 180 slots across
    # the thread pool. ALIGN-ONCE: the engine now locks the grid only on the
    # richest page (the bag is one fixed window -> the grid is identical on every
    # tab), so the per-page (image, lattice) bookkeeping moves to a dedicated
    # record_fn (fired for EVERY page) -- the align_fn is just the aligner. Both
    # keep _last_lattice as the crop fallback. Progress is slot-granular: push a
    # coarse per-quarter Console line + forward the (done,total) tick to the
    # optional UI callback (which marshals onto the GUI thread). Best-effort -- a
    # raising sink/callback must never abort the scan.
    def _align_only(image, db_, calib):
        return scanner.auto_align(image, db_, calib)

    def _record_page(page, image, lattice):
        runner.note_page_recognised(page, image, lattice)

    last_console_step = [0]   # tracks last 'done' at which a Console line fired

    def _progress(done, total):
        if progress_fn is not None:
            try:
                progress_fn(done, total)
            except Exception:
                pass
        # Coarse Console line: one update per ~quarter so the Console is not
        # flooded with 180 lines (the UI status shows the smooth percentage).
        try:
            step = max(1, total // 4)
            if done >= last_console_step[0] + step or done == total:
                last_console_step[0] = done
                pct = int(done * 100 / total) if total else 100
                _emit_line(sink, t('inventory.scan_progress_pct', pct=pct))
        except Exception:
            pass

    # ALWAYS vectorised: the page-vectorised matcher is BIT-IDENTICAL to the
    # per-slot loop (pinned by tests/test_inventory_vectorized.py) and strictly
    # faster (one GIL-free numpy reduction per page instead of 45 Python slot
    # dispatches), so the live scan always takes it -- there is no quality reason
    # to keep the slow loop as a runtime switch. The old
    # ``cfg['inventory']['fast_recognition']`` gate is thus vestigial here (the UI
    # agent removes the settings checkbox); we pin ``vectorized=True`` so the live
    # path is fast regardless of any stale config value.
    inv = scanner.recognize_pages(
        captured, db,
        calib=DEFAULT_CALIBRATION,
        progress_fn=_progress,
        align_fn=_align_only,
        record_fn=_record_page,
        vectorized=True,
    )
    # Persist the (now warm) grid lock so next session's first scan is warm too.
    _save_grid_lock()

    # Toggled-shut detection: a hotkey that CLOSED the inventory yields no items
    # and only unknowns (or nothing). Warn clearly instead of dumping garbage.
    if _is_all_unknown(inv):
        _warn('inventory.scan_not_open')
        _emit_line(sink, t('inventory.scan_not_open'))
        return inv

    # Render a SIMPLE found-items list (+ the tracked summary) to the Console.
    # The per-page grids are intentionally dropped here -- too noisy, and the
    # inventory view itself has no room (hence routing the readout to the
    # Console). ``format_item_list`` = the plain "what did the scan find?" view.
    for line in report.format_item_list(inv):
        _emit_line(sink, line)
    for line in report.format_tracked(inv, names=tracked):
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
