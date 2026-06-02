"""Orchestration: classify a captured page, and drive a full I->IV scan.

:func:`recognize_page` is the headless unit entry -- it takes ONE already
captured page image (BGR) plus calibration, auto-aligns the grid, and returns
45 row-major :class:`SlotResult`. No game / win32 / GUI is touched.

:func:`scan_inventory` drives all four pages via two INJECTED callbacks so the
capture + input layer stays outside the engine: ``capture_fn() -> bgr_image``
and ``switch_page_fn(page) -> None``. In production these wrap
``WindowCapture.get_screenshot`` and ``pydirectinput`` tab clicks (built from
the calibration ``tabs`` + ``wincap.offset_x/y``, exactly like
:mod:`fishingbot` builds click coords). In tests they are trivial fakes -- so
the whole scanner is testable on static images.
"""

from .constants import (
    DEFAULT_CALIBRATION,
    DEFAULT_TOLERANCE,
    PAGES,
    slot_indices,
)
from .grid import extract_slot, auto_align, upper_region_is_empty
from .types import SlotResult, InventoryMap, STATE_UNKNOWN
from i18n import t

try:  # pragma: no cover - reiner Fallback
    from debuglog import log
except Exception:  # pragma: no cover
    log = None


def _log(key, **fmt):
    """Log a translated event line (State 0); swallows logger errors."""
    if log is None:
        return
    try:
        log.event(0, t(key, **fmt))
    except Exception:
        pass


def classify_slot(slot_rgb, db, row, col, page=None, tol=DEFAULT_TOLERANCE):
    """Classify one extracted RGB slot into a :class:`SlotResult`.

    Probes the number-free upper region for emptiness, then defers to the DB's
    threshold/margin decision (empty / item / unknown + signature).
    """
    empty = upper_region_is_empty(slot_rgb, tol)
    return db.best_slot_result(slot_rgb, row=row, col=col, page=page,
                               empty=empty, tol=tol)


def recognize_page(image_bgr, db, calib=DEFAULT_CALIBRATION, lattice=None,
                   page=None):
    """Classify all 45 slots of one captured page image (row-major).

    Auto-aligns the grid for this image unless an explicit ``lattice`` is given
    (the caller can reuse a locked lattice). Returns ``[SlotResult] * 45`` in
    row-major order. Degrades to all-unknown (logged) -- never raises -- if slot
    extraction is impossible (e.g. numpy missing).
    """
    tol = int((calib or {}).get('tolerance', DEFAULT_TOLERANCE))
    if lattice is None:
        lattice = auto_align(image_bgr, db, calib)

    results = []
    for row, col in slot_indices():
        slot = extract_slot(image_bgr, lattice.slot_box(row, col))
        if slot is None:
            # No image data for this slot -> unknown (defensive, never raise).
            results.append(SlotResult(state=STATE_UNKNOWN, name=None,
                                      distance=float('inf'), margin=0.0,
                                      signature=None, page=page,
                                      row=row, col=col))
            continue
        results.append(classify_slot(slot, db, row=row, col=col, page=page,
                                      tol=tol))
    return results


def _scan_one_page(page, capture_fn, switch_page_fn, hover_fn, verify_page_fn,
                   db, calib):
    """Switch to, (optionally) verify, hover-clear, and classify ONE page.

    Step order (each step defensive; this helper NEVER raises -- it returns the
    45-slot result tuple, or ``None`` to mean "skip this page"):

      1. ``switch_page_fn(page)``      (live: click the tab; tests: record it)
      2. ``img = capture_fn()``        (first capture: used for verify + align)
      3. if ``verify_page_fn``: confirm the open tab == ``page``; on mismatch
         RETRY ``switch_page_fn`` once + re-capture; if still wrong, skip page
         (do not classify the wrong tab).
      4. ``lattice = auto_align(img, db, calib)``   (lock the grid on this page;
         auto_align is glow-robust, so locking on the still-glowing capture is
         fine -- the cursor sweep next does not move the grid)
      5. if ``hover_fn``: ``hover_fn(page, lattice)`` then RE-CAPTURE the now
         de-glowed page. With ``hover_fn=None`` (headless / tests) we keep the
         already-captured ``img`` -> byte-identical to the pre-hover behaviour.
      6. ``recognize_page(img, db, calib, lattice=lattice, page=page)``

    Pure-ish + testable on static images with fake callbacks: a test can pass a
    ``hover_fn`` that swaps the fake capture from a glow image to a no-glow image
    and assert recognition improves, or a ``verify_page_fn`` that reports the
    wrong tab and assert the retry/skip path.
    """
    try:
        if switch_page_fn is not None:
            switch_page_fn(page)
        image = capture_fn() if capture_fn is not None else None
    except Exception as exc:
        _log('inventory.scan_page_failed', page=page, detail=str(exc)[:120])
        return None
    if image is None:
        _log('inventory.scan_page_no_image', page=page)
        return None

    # 3. Verify the correct tab actually opened; retry the switch once.
    if verify_page_fn is not None:
        try:
            opened = verify_page_fn(image)
        except Exception:
            opened = page  # never let verification abort the page
        if opened != page:
            _log('inventory.scan_page_wrong_tab', page=page, got=opened)
            try:
                if switch_page_fn is not None:
                    switch_page_fn(page)
                retry = capture_fn() if capture_fn is not None else None
                if retry is not None:
                    image = retry
                    opened = verify_page_fn(image)
            except Exception as exc:
                _log('inventory.scan_page_failed', page=page,
                     detail=str(exc)[:120])
                return None
            if opened != page:
                # Still the wrong tab -> skip rather than classify it.
                return None

    # 4. Lock the grid for this page (glow-robust; on the first capture).
    lattice = auto_align(image, db, calib)

    # 5. Hover-clear the glow, then RE-CAPTURE the de-glowed page (same lattice).
    if hover_fn is not None:
        try:
            hover_fn(page, lattice)
            recaptured = capture_fn() if capture_fn is not None else None
            if recaptured is not None:
                image = recaptured
        except Exception as exc:
            # A failed hover just means some slots may still glow (margin-primary
            # partly covers that) -> classify the image we have, do not abort.
            _log('inventory.scan_page_failed', page=page, detail=str(exc)[:120])

    # 6. Classify all 45 slots with the locked lattice.
    results = recognize_page(image, db, calib, lattice=lattice, page=page)
    return tuple(results)


def scan_inventory(capture_fn, switch_page_fn, db,
                   calib=DEFAULT_CALIBRATION, pages=PAGES,
                   hover_fn=None, verify_page_fn=None):
    """Drive a full I->IV scan via injected callbacks; assemble an InventoryMap.

    For each page label the per-page steps (switch -> capture -> optional verify
    -> auto-align -> optional hover-clear + re-capture -> classify) run in
    :func:`_scan_one_page`. A page that fails or opens the wrong tab is skipped
    (logged) so one bad page cannot abort the whole scan.

    The two NEW callbacks are OPTIONAL and keyword-defaulted to ``None`` so every
    existing caller / test is unchanged: with both ``None`` the loop is
    byte-identical to the original (no verification, no hover, the first capture
    is classified directly).

    :param capture_fn: ``() -> bgr_image`` (e.g. ``wincap.get_screenshot``).
    :param switch_page_fn: ``(page) -> None`` (e.g. a pydirectinput tab click).
    :param db: the :class:`~inventory.itemdb.ItemDB`.
    :param hover_fn: optional ``(page, lattice) -> None`` cursor sweep that
        clears the lavender glow before the de-glowed re-capture (live only).
    :param verify_page_fn: optional ``(bgr_image) -> page_label`` that confirms
        the expected tab is open (wraps :func:`inventory.grid.active_page`).
    :return: :class:`InventoryMap` keyed by the pages successfully scanned.
    """
    page_results = {}
    for page in pages:
        results = _scan_one_page(page, capture_fn, switch_page_fn, hover_fn,
                                 verify_page_fn, db, calib)
        if results is None:
            continue
        page_results[page] = results
    _log('inventory.scan_done', pages=len(page_results))
    return InventoryMap(pages=page_results)
