# -*- coding: utf-8 -*-
"""LIVE shell for the Wegwerfen / fallen lassen -- the ONLY win32 part of it.

Thin wrapper the UI calls (on a worker thread) to actually drop the
REMOVE-marked items into the world. It adds NO logic: it opens the capture
window, locks the inventory grid ONCE via :func:`inventory.grid.auto_align`,
builds the capture + inventory-scan callbacks :func:`inventory_discard.run_discard`
expects, and hands ``pydirectinput`` in as the input api.

Same discipline as :mod:`interface.inventory_campfire_runner` /
:mod:`interface.inventory_runner`: the hard deps (``pydirectinput``,
:class:`WindowCapture`, ``cv2``) are SOFT-imported so this module stays importable
headless, and the whole flow is unit-tested by monkeypatching these module-level
names + injecting synthetic frames (no game needed). The PURE brain lives in
:mod:`inventory_discard`.

WHY lock the grid here (and pass it in): the raw ``DEFAULT_CALIBRATION`` sits ~1
slot too LOW relative to the user's actual inventory window, so a drag off the raw
calibration grabs the slot below the target. :func:`inventory.grid.auto_align`
re-locks the grid to the live frame ONCE (the grid position is identical across
all four tabs of the same fixed window), and that locked lattice is handed to
``run_discard`` so each drag SOURCE hits the real slot centre.

The inventory must be OPEN for the scan (the removed items live there). This
wrapper presses the configured inventory hotkey first -- exactly like the
inventory scan / the grill -- and the same TOGGLE caveat applies (documented in
:mod:`interface.inventory_runner`).
"""

import time

import constants
from inventory.constants import (
    DEFAULT_CALIBRATION, PAGES, OPEN_SETTLE_S, TAB_SETTLE_S,
)
from inventory import hover
from inventory import open_probe
from i18n import t

import inventory_discard as discard

# -- soft imports (live deps; module stays importable headless) -------------
try:  # pragma: no cover - present only on the Windows build/runtime
    import pydirectinput
    pydirectinput.PAUSE = 0.05  # down->up needs a hold (~3 frames) or the game ignores the click; 0 = not registered
except Exception:  # pragma: no cover
    pydirectinput = None

try:  # pragma: no cover
    import cv2 as _cv  # noqa: F401  (kept for symmetry / future dialog-verify)
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


def _park_cursor(offset, calib):
    """MOVE the cursor OFF the tab/grid after a tab click (never a click).

    Mirrors :func:`interface.inventory_campfire_runner._park_cursor` /
    :meth:`interface.inventory_runner._Runner.switch_page`: after clicking a page
    tab the cursor would otherwise rest ON the tab (just above the grid) and its
    glow/tooltip can occlude the slot below, so the pre-drop scan would misread the
    top slot row(s) as ``unknown`` and silently skip REMOVE-marked items there. We
    move it to the neutral :func:`inventory.hover.tab_park_point` (left of the grid,
    clear of all tabs) at ``pydirectinput.PAUSE = 0`` (restored in a ``finally``).
    MOVE-only; a failed park is non-fatal. No-op headless (``pydirectinput`` absent).
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

    Mirrors :func:`interface.inventory_runner._ensure_inventory_open` (same
    duplication discipline as :func:`_park_cursor`). Returns ``True`` when the
    bag is verifiably open, ``False`` when it stays closed (caller ABORTS its
    drag flow), and falls back to the historical blind single press (returning
    ``True``) when the probe is unavailable -- headless only, the live EXE
    bundles numpy/PIL + the tab templates.
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


def _client_size(frame, wincap):
    """``(client_w, client_h)`` of the captured client.

    Prefers the captured frame's own shape (``(H, W, ...)``); falls back to the
    WindowCapture width/height attributes, then to the calibration ``client``.
    Defensive: any hiccup -> the calibration client size. Never raises.
    """
    try:
        if frame is not None:
            h, w = int(frame.shape[0]), int(frame.shape[1])
            if w > 0 and h > 0:
                return (w, h)
    except Exception:
        pass
    try:
        w = int(getattr(wincap, 'w', 0) or 0)
        h = int(getattr(wincap, 'h', 0) or 0)
        if w > 0 and h > 0:
            return (w, h)
    except Exception:
        pass
    cl = (DEFAULT_CALIBRATION or {}).get('client', [0, 0])
    return (int(cl[0]), int(cl[1]))


def run_discard_items(cfg, states, *, log_fn=None, db=None,
                      calib=DEFAULT_CALIBRATION):
    """Open the window + inventory and drop every REMOVE-marked item.

    :param cfg: current config dict (reads ``inventory.hotkey`` to open the bag).
    :param states: the inventory-manage ``{name: KEEP|REMOVE|CAMPFIRE}`` map from
        the GUI (which items the user marked for removal).
    :param db: an :class:`~inventory.itemdb.ItemDB` to reuse (default: the cached
        bundled DB via :func:`interface.inventory_io._get_db`) -- also used to
        lock the grid via ``auto_align``.
    :return: the :class:`inventory_discard.DiscardResult`.

    Defensive: with no marked items / no window it returns a clear status and
    never raises. The caller (UI) is idle-only-gated exactly like the inventory
    scan, so no concurrent bot run can race the cursor.
    """
    # Nothing marked -> skip everything (no window work at all).
    if not discard.discard_item_names(states):
        _emit('-', 'discard.no_items')
        return discard.DiscardResult('no_items')

    if WindowCapture is None or pydirectinput is None:
        _emit('-', 'discard.live_unavailable')
        return discard.DiscardResult('error')

    if db is None:
        try:
            from interface.inventory_io import _get_db
            db = _get_db()
        except Exception:
            db = None

    try:
        wincap = WindowCapture(constants.GAME_NAME)
    except Exception as exc:
        _emit('-', 'discard.no_window', detail=str(exc)[:120])
        return discard.DiscardResult('error')

    offset = (int(getattr(wincap, 'offset_x', 0) or 0),
              int(getattr(wincap, 'offset_y', 0) or 0))

    # TOGGLE-SAFE open (the "Bot laeuft los" fix): probe the open state via the
    # tab templates and press the (toggle!) hotkey only when the bag is actually
    # closed. If it cannot be verified open we ABORT -- the drag mouseDown on a
    # slot position of a CLOSED bag is a left-click into the 3D world and walks
    # the character off. ``None`` (probe unavailable, headless only) falls back
    # to the historical blind press.
    hotkey = (cfg or {}).get('inventory', {}).get('hotkey', 'i')
    if not _ensure_open(wincap, offset, hotkey, calib):
        _emit('-', 'discard.status_not_open')
        return discard.DiscardResult('not_open')

    # Lock the grid ONCE on a fresh frame (identical across all 4 tabs of the same
    # fixed window). auto_align degrades to the calibration lattice if numpy/DB is
    # missing, so this is always safe.
    try:
        frame0 = wincap.get_screenshot()
    except Exception:
        frame0 = None
    try:
        from inventory.grid import auto_align
        lattice = auto_align(frame0, db, calib)
    except Exception:
        lattice = None

    client_size = _client_size(frame0, wincap)

    def capture_fn():
        try:
            return wincap.get_screenshot()
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
                    # hardware cursor / tab glow never occludes the top slot row
                    # (same fix as inventory_campfire_runner / inventory_runner).
                    # Without this the pre-drop scan can read top-row slots as
                    # unknown and silently skip REMOVE-marked items there.
                    _park_cursor(offset, calib)
                    time.sleep(TAB_SETTLE_S)

            return scan_inventory(
                capture_fn=wincap.get_screenshot,
                switch_page_fn=_switch,
                db=db, calib=calib, pages=PAGES)
        except Exception:
            return None

    _emit('0', 'discard.started')
    result = discard.run_discard(
        states,
        inp=pydirectinput,
        capture_fn=capture_fn,
        scan_fn=scan_fn,
        client_size=client_size,
        offset=offset,
        calib=calib,
        lattice=lattice)
    return result
