# -*- coding: utf-8 -*-
"""LIVE shell for the Lagerfeuer-Braten -- the ONLY win32 / pydirectinput part.

Thin wrapper the UI calls (on a worker thread) to actually grill the
CAMPFIRE-marked fish. It adds NO logic: it opens the capture window, builds the
RGB-capture + inventory-scan callbacks :func:`inventory_campfire.run_campfire`
expects, and hands ``pydirectinput`` in as the input api.

Same discipline as :mod:`interface.inventory_runner` / :mod:`windowcapture`: the
hard deps (``pydirectinput``, :class:`WindowCapture`, ``cv2``) are SOFT-imported
so this module stays importable headless, and the whole flow is unit-tested by
monkeypatching these module-level names + injecting synthetic frames (no game
needed). The PURE brain lives in :mod:`inventory_campfire`.

The inventory must be OPEN for the scan (the campfire tool + the fish live there).
This wrapper presses the configured inventory hotkey first -- exactly like the
inventory scan -- and the same TOGGLE caveat applies (documented there).
"""

import time

import constants
from inventory.constants import DEFAULT_CALIBRATION, PAGES, OPEN_SETTLE_S, TAB_SETTLE_S
from inventory import grid as grid_mod
from inventory import hover
from inventory import open_probe
from i18n import t

import inventory_campfire as campfire

# -- soft imports (live deps; module stays importable headless) -------------
try:  # pragma: no cover - present only on the Windows build/runtime
    import pydirectinput
    pydirectinput.PAUSE = 0.05  # down->up needs a hold (~3 frames) or the game ignores the click; 0 = not registered
except Exception:  # pragma: no cover
    pydirectinput = None

try:  # pragma: no cover
    import cv2 as _cv
except Exception:  # pragma: no cover
    _cv = None

try:  # pragma: no cover
    from windowcapture import WindowCapture
except Exception:  # pragma: no cover
    WindowCapture = None

try:  # pragma: no cover - reiner Fallback
    from debuglog import log
except Exception:  # pragma: no cover
    log = None


def _emit(state, key, **fmt):
    """Console/log line (best-effort)."""
    if log is None:
        return
    try:
        log.event(state, t(key, **fmt))
    except Exception:
        pass


def _bgr_to_rgb(bgr):
    """Convert a captured BGR frame to RGB (what the matcher expects). Soft.

    Uses cv2 when present, else a numpy channel-flip, else returns the input
    unchanged (the matcher degrades to a low score rather than crashing).
    """
    if bgr is None:
        return None
    try:
        if _cv is not None:
            return _cv.cvtColor(bgr, _cv.COLOR_BGR2RGB)
    except Exception:
        pass
    try:
        return bgr[:, :, ::-1]
    except Exception:
        return bgr


def _lock_lattice(wincap, db, calib):
    """Lock the inventory grid ONCE on the live window (or ``None`` on failure).

    Captures a single BGR frame and runs :func:`inventory.grid.auto_align`, so the
    campfire drag SOURCE + the tool double-click hit the SAME grid recognition
    uses (the user's bag sits ~1 slot above the bundled DEFAULT_CALIBRATION). The
    grid is identical across all four tabs (one fixed window), so this single lock
    serves every page. Strictly defensive -> any hiccup returns ``None`` and the
    caller falls back to the calibration lattice (the un-aligned, historical
    behaviour) rather than aborting the grill.
    """
    if wincap is None or db is None:
        return None
    try:
        frame = wincap.get_screenshot()
        if frame is None:
            return None
        return grid_mod.auto_align(frame, db, calib)
    except Exception:
        return None


def _park_cursor(offset, calib):
    """MOVE the cursor OFF the tab/grid after a tab click (never a click).

    Mirrors :meth:`interface.inventory_runner._Runner.switch_page`: after clicking
    a page tab the cursor would otherwise rest ON the tab (just above the grid) and
    its glow/tooltip can occlude the slot below. We move it to the neutral
    :func:`inventory.hover.tab_park_point` (left of the grid, clear of all tabs)
    at ``pydirectinput.PAUSE = 0`` (restored in a ``finally``). MOVE-only; a failed
    park is non-fatal. No-op headless (``pydirectinput`` absent).
    """
    if pydirectinput is None:
        return
    try:
        park = hover.to_screen([hover.tab_park_point(calib)], offset)[0]
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


def _ensure_open(wincap, offset, hotkey, calib):
    """Toggle-safe inventory open: probe -> press only when closed -> verify.

    Mirrors :func:`interface.inventory_discard_runner._ensure_open` (same
    duplication discipline as :func:`_park_cursor`). Returns ``True`` when the
    bag is verifiably open, ``False`` when it stays closed (caller ABORTS the
    grill -- the tool double-click / fish drag on a CLOSED bag is a click into
    the 3D world and walks the character off), and falls back to the historical
    blind single press (returning ``True``) when the probe is unavailable --
    headless only, the live EXE bundles numpy/PIL + the tab templates.
    """
    def _press():
        # KEYBOARD tap needs the 0.1s down->up hold (v1.1.3 lesson) -- the
        # module PAUSE here is the 0.05 mouse default, so force 0.1 around it.
        old_pause = getattr(pydirectinput, 'PAUSE', None)
        try:
            pydirectinput.PAUSE = 0.1
            pydirectinput.keyDown(hotkey)
            pydirectinput.keyUp(hotkey)
        except Exception:
            pass
        finally:
            try:
                pydirectinput.PAUSE = old_pause
            except Exception:
                pass

    def _capture():
        try:
            return wincap.get_screenshot()
        except Exception:
            return None

    ok = open_probe.ensure_inventory_open(
        _capture, _press, calib,
        park_fn=lambda: _park_cursor(offset, calib))
    if ok is None:
        _press()
        time.sleep(OPEN_SETTLE_S)
        return True
    return ok


def run_campfire_grill(cfg, states, *, log_fn=None, db=None,
                       calib=DEFAULT_CALIBRATION):
    """Open the window + inventory and grill every CAMPFIRE-marked fish.

    :param cfg: current config dict (reads ``inventory.hotkey`` to open the bag,
        and ``fishing.bait_key`` only to know what NOT to grill is already handled
        by the name exclusion -- no key needed here).
    :param states: the inventory-manage ``{name: KEEP|REMOVE|CAMPFIRE}`` map from
        the GUI (which fish the user marked for the fire).
    :param db: an :class:`~inventory.itemdb.ItemDB` to reuse (default: the cached
        bundled DB via :func:`interface.inventory_io._get_db`).
    :return: the :class:`inventory_campfire.CampfireResult`.

    Defensive: with no marked fish / no window it returns a clear status and never
    raises. The caller (UI) is idle-only-gated exactly like the inventory scan, so
    no concurrent bot run can race the cursor.
    """
    # Nothing marked -> skip everything (no window work at all).
    if not campfire.campfire_fish_names(states):
        _emit('-', 'campfire.no_fish_marked')
        return campfire.CampfireResult('no_fish')

    if WindowCapture is None or pydirectinput is None:
        _emit('-', 'campfire.live_unavailable')
        return campfire.CampfireResult('error')

    if db is None:
        try:
            from interface.inventory_io import _get_db
            db = _get_db()
        except Exception:
            db = None

    try:
        wincap = WindowCapture(constants.GAME_NAME)
    except Exception as exc:
        _emit('-', 'campfire.no_window', detail=str(exc)[:120])
        return campfire.CampfireResult('error')

    offset = (int(getattr(wincap, 'offset_x', 0) or 0),
              int(getattr(wincap, 'offset_y', 0) or 0))

    # TOGGLE-SAFE open (the "Bot laeuft los" fix): probe the open state via the
    # tab templates and press the (toggle!) hotkey only when the bag is actually
    # closed -- the common trigger was Scan (leaves the bag open) -> Manage
    # (blind press CLOSED it) -> tool double-click / drag into the 3D world.
    hotkey = (cfg or {}).get('inventory', {}).get('hotkey', 'i')
    if not _ensure_open(wincap, offset, hotkey, calib):
        _emit('-', 'campfire.status_not_open')
        return campfire.CampfireResult('not_open')

    def capture_rgb_fn():
        try:
            return _bgr_to_rgb(wincap.get_screenshot())
        except Exception:
            return None

    def scan_fn():
        """One headless I->IV inventory scan (tab-click page switch + offset)."""
        try:
            from inventory.scanner import scan_inventory
            ox, oy = offset

            def _switch(page):
                pt = ((calib or {}).get('tabs', {}) or {}).get(page)
                if pt:
                    try:
                        pydirectinput.click(x=int(ox + pt[0]), y=int(oy + pt[1]))
                    except Exception:
                        pass
                    # Park the cursor OFF the tab/grid before the capture so the
                    # hardware cursor / tab glow never occludes the slot below
                    # (same fix as inventory_runner._Runner.switch_page).
                    _park_cursor(offset, calib)
                    time.sleep(TAB_SETTLE_S)

            return scan_inventory(
                capture_fn=wincap.get_screenshot,
                switch_page_fn=_switch,
                db=db, calib=calib, pages=PAGES)
        except Exception:
            return None

    # Lock the inventory grid ONCE on the live window (identical across all four
    # tabs -> one lock serves every page). Threaded into run_campfire so the tool
    # double-click + every fish drag SOURCE hit the SAME grid recognition uses,
    # not the raw (un-aligned) DEFAULT_CALIBRATION that grabs ~1 slot too low.
    # Defensive: None -> run_campfire falls back to the calibration lattice.
    locked = _lock_lattice(wincap, db, calib)

    _emit('0', 'campfire.started')
    result = campfire.run_campfire(
        states,
        inp=pydirectinput,
        capture_rgb_fn=capture_rgb_fn,
        scan_fn=scan_fn,
        offset=offset,
        calib=calib,
        lattice=locked)
    return result
