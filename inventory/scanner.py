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

TWO-PHASE FAST PATH (:func:`capture_pages` + :func:`recognize_pages`):
:func:`scan_inventory` does capture and recognition INTERLEAVED per page (it
auto-aligns + classifies 45 slots before switching to the next tab), so the
game window is held for the full sequential CPU time. The fast path SPLITS that:

  * PHASE 1 -- :func:`capture_pages` only clicks I->II->III->IV and buffers ONE
    raw screenshot per tab (just switch + minimal settle + capture, NO
    recognition between tabs), then returns to tab I. The input device is busy
    for the few tab-settle pauses only.
  * PHASE 2 -- :func:`recognize_pages` then auto-aligns + classifies the 4
    buffered frames OFF the input device, running the 4x45 = 180 slot
    classifications in PARALLEL over a thread pool. The matcher is pure
    numpy/cv2 (releases the GIL), so threads give real parallelism with NO
    pickling overhead. A slot-granular ``progress_fn(done, total)`` fires as
    each slot completes (the caller marshals it onto its UI thread).

Both new functions REUSE the same recognition engine (:func:`classify_slot` /
the per-slot read in :func:`recognize_page`) -- only capture is separated from
recognition and the recognition is parallelised. They are defensive (never
raise) and importable headless; the parallel path degrades to a serial loop if
:mod:`concurrent.futures` is unavailable or one worker is requested.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

from .constants import (
    DEFAULT_CALIBRATION,
    DEFAULT_TOLERANCE,
    PAGES,
    SLOTS_PER_PAGE,
    slot_indices,
)
from dataclasses import replace

from .grid import (extract_slot, auto_align, upper_region_is_empty,
                   lattice_from_calibration, aligned_match_count)
from .types import SlotResult, InventoryMap, STATE_UNKNOWN, STATE_ITEM
from .digits import read_count
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


#: Module default for the page-vectorised matcher. The vectorised path is
#: BIT-EXACT to the per-slot loop (pinned by tests/test_inventory_vectorized.py
#: "BIT-for-bit") -- same masked MAD, same shift-min, same stable order -> same
#: SlotResults -- it merely drops the 45x Python per-slot dispatch and reuses one
#: GIL-free numpy reduction per page. There is therefore no reason to default to
#: the slower per-slot loop: ``True`` makes the fast path the default everywhere.
#: A caller can still force the legacy loop per-call via
#: ``recognize_page(..., vectorized=False)`` / ``recognize_pages(...,
#: vectorized=False)`` (used by the bit-exactness regression tests). The
#: vectorised path itself transparently falls back to the per-slot loop whenever
#: the batched matrix is unavailable (numpy missing / empty DB), so flipping the
#: default on is never less capable than the loop.
VECTORIZED_DEFAULT = True


def recognize_page(image_bgr, db, calib=DEFAULT_CALIBRATION, lattice=None,
                   page=None, vectorized=None):
    """Classify all 45 slots of one captured page image (row-major).

    Auto-aligns the grid for this image unless an explicit ``lattice`` is given
    (the caller can reuse a locked lattice). Returns ``[SlotResult] * 45`` in
    row-major order. Degrades to all-unknown (logged) -- never raises -- if slot
    extraction is impossible (e.g. numpy missing).

    With ``vectorized`` (default :data:`VECTORIZED_DEFAULT`, now ON) the 45 slots
    are scored against the DB in ONE batched numpy reduction
    (:meth:`ItemDB.scored_for_page`) instead of a per-slot loop -- numerically
    identical (same masked MAD, same per-slot adaptive mask, same shift min, same
    stable order -> same SlotResults), just without the 45x Python dispatch. The
    vectorised path falls back to the per-slot loop whenever the batched matrix is
    unavailable (numpy missing / empty DB), so it is never less capable. Pass
    ``vectorized=False`` to force the legacy per-slot loop (the bit-exactness
    regression tests do this to compare the two).
    """
    tol = int((calib or {}).get('tolerance', DEFAULT_TOLERANCE))
    if lattice is None:
        lattice = auto_align(image_bgr, db, calib)

    use_vec = VECTORIZED_DEFAULT if vectorized is None else bool(vectorized)
    if use_vec:
        vec = _recognize_page_vectorized(image_bgr, db, lattice, page, tol)
        if vec is not None:
            return vec
        # else: batched path unavailable -> fall through to the per-slot loop.

    results = []
    for row, col in slot_indices():
        results.append(_classify_one_slot(image_bgr, db, lattice, page,
                                           row, col, tol))
    return results


def _recognize_page_vectorized(image_bgr, db, lattice, page, tol):
    """Vectorised twin of the :func:`recognize_page` loop (or ``None``).

    Extracts all 45 slots into one ``(45, 32, 32, 3)`` stack, scores the whole
    page against the DB in a single batched reduction
    (:meth:`ItemDB.scored_for_page`), then per slot runs the SAME decision
    (:meth:`ItemDB._decide_from_scored`) + the SAME stack-number read as
    :func:`_classify_one_slot`. Returns the 45 row-major :class:`SlotResult`, or
    ``None`` when the batched matrix is not available (no numpy / empty DB / an
    unextractable slot) so the caller cleanly degrades to the per-slot loop.
    Never raises; never mutates ``image_bgr`` / ``db``.
    """
    if getattr(db, 'scored_for_page', None) is None:
        return None
    indices = slot_indices()
    slots = []
    for row, col in indices:
        slot = extract_slot(image_bgr, lattice.slot_box(row, col))
        if slot is None:
            return None  # cannot build a full stack -> let the loop handle it
        slots.append(slot)
    try:
        import numpy as _np
        stack = _np.stack(slots).astype(_np.float32)
    except Exception:
        return None
    scored_lists = db.scored_for_page(stack)
    if scored_lists is None or len(scored_lists) != len(indices):
        return None

    results = []
    for (row, col), slot, scored in zip(indices, slots, scored_lists):
        empty = upper_region_is_empty(slot, tol)
        try:
            res = db._decide_from_scored(scored, slot, row=row, col=col,
                                         page=page, empty=empty)
        except Exception:
            res = SlotResult(state=STATE_UNKNOWN, name=None,
                             distance=float('inf'), margin=0.0,
                             signature=None, page=page, row=row, col=col)
        res = _read_count_if_item(res, slot)
        results.append(res)
    return results


def _classify_one_slot(image_bgr, db, lattice, page, row, col, tol):
    """Recognise ONE slot of a captured page -> :class:`SlotResult`.

    The single per-slot unit shared by the serial :func:`recognize_page` loop
    and the PARALLEL :func:`recognize_pages` workers, so both go through the
    EXACT same recognition path: extract the slot from ``lattice.slot_box`` ->
    :func:`classify_slot` -> read the printed stack number on a recognised item.
    Pure (only reads ``image_bgr`` / ``db`` -- never mutates either) so it is
    thread-safe to call concurrently for different ``(row, col)``. Never raises:
    an unextractable slot degrades to UNKNOWN, a failed digit read to
    ``count=None``.
    """
    slot = extract_slot(image_bgr, lattice.slot_box(row, col))
    if slot is None:
        # No image data for this slot -> unknown (defensive, never raise).
        return SlotResult(state=STATE_UNKNOWN, name=None,
                          distance=float('inf'), margin=0.0,
                          signature=None, page=page, row=row, col=col)
    res = classify_slot(slot, db, row=row, col=col, page=page, tol=tol)
    return _read_count_if_item(res, slot)


def _read_count_if_item(res, slot):
    """Read + attach the printed stack number when ``res`` is a recognised item.

    Shared tail of the per-slot and page-vectorised paths so BOTH read the stack
    number identically. Reads the font-independent stack-count OCR on every
    ITEM slot so stackables (baits, boxes, dyes, bleach, keys) sum by quantity,
    not by slot. Never raises -> a failed read degrades to ``count=None``;
    a non-item ``res`` is returned unchanged.
    """
    if res.state != STATE_ITEM:
        return res
    try:
        cr = read_count(slot)
        return replace(res, count=cr.value, count_confident=cr.confident)
    except Exception:
        return res


# -- ALIGN-ONCE: lock the grid once, reuse across the fixed-window tabs ------

def _lock_lattices(captured, db, calib, aligner, record_fn=None):
    """Lock a grid lattice per page, but auto-align AT MOST ONCE on a stable bag.

    The inventory window is FIXED, so its grid is geometrically IDENTICAL on all
    four tabs -- yet the old path ran the (expensive, ~seconds) ``auto_align``
    once PER buffered page (4x). This locks the grid ONCE on an anchor page and
    REUSES that single lattice for every page:

      * ANCHOR  -- the buffered page with the MOST confident items at the
        calibration lattice (:func:`inventory.grid.aligned_match_count`, a cheap
        downsampled probe). auto_align recovers the documented row-drift only
        when it has items to lock onto, so the richest page is the robust anchor;
        an all-empty bag has no signal anywhere and any page (-> calibration
        origin) is equivalent.
      * REUSE   -- every page is assigned that one locked lattice; ``aligner`` is
        invoked EXACTLY ONCE (on the anchor) for a stable bag (~4x less align
        time). With 0/1 buffered pages it is also at most once.

    ``record_fn(page, image, lattice)`` (optional) is called for EVERY page so a
    caller that needs the per-page (image, lattice) pair -- e.g. the live runner's
    per-page unknown crop -- still records all pages even though only one was
    aligned. Returns ``{page: GridLattice}``. Defensive: an aligner that raises
    falls back to the calibration lattice; never raises.

    NOTE: the per-page 0-item FALLBACK (re-align a page the shared grid could not
    place) lives in the recognisers, which re-align + re-classify only such a page
    -- so a genuinely mis-fitting tab still self-corrects, while the common stable
    bag pays a single align. Bit-identical to per-page aligning whenever
    ``aligner`` is position-independent (it returns the same lattice for every
    page), which is exactly the stable-window invariant + the test stubs.
    """
    pages = list(captured.keys())
    base = lattice_from_calibration(calib)

    def _align_one(page):
        try:
            return aligner(captured[page], db, calib)
        except Exception as exc:
            _log('inventory.scan_page_failed', page=page, detail=str(exc)[:120])
            return base

    if not pages:
        return {}

    if len(pages) == 1:
        only = pages[0]
        lat = _align_one(only)
        if record_fn is not None:
            _safe_record(record_fn, only, captured[only], lat)
        return {only: lat}

    # Pick the anchor: the page richest in confidently-matched slots (most signal
    # for auto_align's drift recovery). Cheap downsampled probe at the calibration
    # lattice; ties resolve to the FIRST page (deterministic, capture order).
    anchor = pages[0]
    best = -1
    for page in pages:
        try:
            cnt = aligned_match_count(captured[page], db, base)
        except Exception:
            cnt = 0
        if cnt > best:
            best = cnt
            anchor = page

    shared = _align_one(anchor)            # the ONE expensive align of the scan
    lattices = {}
    for page in pages:
        lattices[page] = shared
        if record_fn is not None:
            _safe_record(record_fn, page, captured[page], shared)
    return lattices


def _safe_record(record_fn, page, image, lattice):
    """Call ``record_fn(page, image, lattice)`` best-effort (never raises)."""
    try:
        record_fn(page, image, lattice)
    except Exception:
        pass


def _page_has_item(slots):
    """True iff any slot in ``slots`` is a recognised ITEM (fallback trigger)."""
    try:
        return any(getattr(s, 'state', None) == STATE_ITEM for s in slots)
    except Exception:
        return True  # unsure -> do NOT trigger a re-align


# -- TWO-PHASE FAST PATH: capture (fast) then parallel recognise -------------

def capture_pages(capture_fn, switch_page_fn, pages=PAGES,
                  verify_page_fn=None, settle_fn=None, return_to_first=True):
    """PHASE 1 -- click each tab and BUFFER one raw screenshot per page (fast).

    Switches I->II->III->IV (``switch_page_fn(page)``), grabs ONE frame per tab
    (``capture_fn()``) and buffers it -- with NO recognition / auto-align /
    hover between tabs, so the input device is held only for the tab-switch
    settles. Returns an ORDERED ``{page: bgr_image}`` dict of the pages that
    yielded a usable frame (a page whose switch/capture failed is simply
    omitted, logged -- one bad tab never aborts the rest).

    ``switch_page_fn`` itself owns its post-click settle in the live runner (it
    sleeps ``TAB_SETTLE_S`` after the click); the optional ``settle_fn(page)``
    is an extra hook for callers that want to settle separately (tests pass it
    to assert ordering; the live runner leaves it ``None``). ``verify_page_fn``
    (optional) confirms the expected tab actually opened and retries the switch
    once, exactly like :func:`_scan_one_page`, so a missed click does not buffer
    the wrong page. With ``return_to_first`` the cursor/tab is returned to the
    first page at the end (cosmetic: leaves the inventory as the user expects).

    Defensive: never raises. ``capture_fn``/``switch_page_fn`` may be ``None``
    (then nothing is captured / switched). Pure of recognition, so it is fully
    testable with fake capture/switch callbacks.
    """
    captured = {}
    for page in pages:
        try:
            if switch_page_fn is not None:
                switch_page_fn(page)
            if settle_fn is not None:
                settle_fn(page)
            image = capture_fn() if capture_fn is not None else None
        except Exception as exc:
            _log('inventory.scan_page_failed', page=page, detail=str(exc)[:120])
            continue
        if image is None:
            _log('inventory.scan_page_no_image', page=page)
            continue
        # Confirm the right tab opened; retry the switch once (do not buffer the
        # wrong page). Verification failure is non-fatal -> keep the frame.
        if verify_page_fn is not None:
            image = _verified_capture(page, image, capture_fn, switch_page_fn,
                                      verify_page_fn)
            if image is None:
                continue
        captured[page] = image
    # Leave the panel on the first tab (the click loop ended on the last one).
    if return_to_first and switch_page_fn is not None and pages:
        try:
            switch_page_fn(pages[0])
        except Exception:
            pass
    return captured


def _verified_capture(page, image, capture_fn, switch_page_fn, verify_page_fn):
    """Confirm ``image`` shows ``page``; retry the switch once; else drop it.

    Returns the (possibly re-captured) image of the correct page, or ``None`` if
    after one retry the wrong tab is still open (caller skips the page). Mirrors
    the verify/retry branch of :func:`_scan_one_page`; never raises.
    """
    try:
        opened = verify_page_fn(image)
    except Exception:
        return image  # never let verification drop a page
    if opened == page:
        return image
    _log('inventory.scan_page_wrong_tab', page=page, got=opened)
    try:
        if switch_page_fn is not None:
            switch_page_fn(page)
        retry = capture_fn() if capture_fn is not None else None
        if retry is not None and verify_page_fn(retry) == page:
            return retry
    except Exception as exc:
        _log('inventory.scan_page_failed', page=page, detail=str(exc)[:120])
        return None
    return None


def recognize_pages(captured, db, calib=DEFAULT_CALIBRATION,
                    progress_fn=None, max_workers=None,
                    align_fn=None, vectorized=None, record_fn=None):
    """PHASE 2 -- auto-align + classify the buffered pages, slots in PARALLEL.

    Takes the ``{page: bgr_image}`` buffer from :func:`capture_pages`, locks the
    grid ONCE on the richest buffered page and reuses it across the fixed-window
    tabs (:func:`_lock_lattices`; ``align_fn`` overrides the aligner for tests),
    then classifies all of each page's slots. The 45-per-page slot
    classifications across ALL buffered pages are run on a
    :class:`~concurrent.futures.ThreadPoolExecutor`: each task is one
    :func:`_classify_one_slot` call, which is pure numpy/cv2 (the heavy matcher
    releases the GIL) so the threads run in genuine parallel with NO pickling
    overhead. Returns an assembled :class:`InventoryMap`.

    ALIGN-ONCE: ``auto_align`` (the expensive per-scan cost) runs at most ONCE for
    a stable bag instead of once per tab (~4x less align time) -- the grid is
    identical on every tab of the one fixed window. A page the shared grid places
    with ZERO items is re-aligned + re-classified on its OWN (the only case that
    pays a second align), so a genuinely mis-fitting tab still self-corrects. The
    result map is bit-identical to per-page aligning whenever the aligner is
    position-independent (the stable-window invariant + the test stubs).

    ``record_fn(page, image, lattice)`` (optional) fires once per page with the
    locked lattice, so the live runner can file each page's (image, lattice) for
    its per-page unknown crop even though only one page was aligned.

    Progress: ``progress_fn(done, total)`` (best-effort, wrapped) fires after
    each slot completes, with ``total = len(captured) * 45`` and ``done``
    MONOTONICALLY increasing 1..total -- the caller marshals it onto its UI
    thread for a smooth 0..100%. ``max_workers`` defaults to a small CPU-bound
    pool; ``max_workers <= 1`` (or a missing pool) runs a serial fallback that
    fires the same progress sequence.

    VECTORISED PATH (``vectorized``, default :data:`VECTORIZED_DEFAULT`, now ON):
    each PAGE is recognised as ONE batched numpy reduction over its 45 slots
    (:func:`_recognize_page_vectorized`) instead of fanning 45 individual slot
    tasks; the pages then fan across the pool (the heavy reduction is GIL-free, so
    pages overlap). The result map is IDENTICAL to the per-slot path (same engine,
    same per-slot adaptive mask, same numbers); progress still advances 1..total
    in slot units (a page contributes its 45 ticks when it completes) so the
    monotonic-1..total contract holds on both paths. Pass ``vectorized=False`` to
    force the original slot-fanout path (byte-for-byte unchanged).

    Defensive: never raises. A page whose auto-align fails still classifies
    against the calibration lattice; a slot whose worker raises degrades to an
    UNKNOWN result rather than aborting the scan.
    """
    if not captured:
        _log('inventory.scan_done', pages=0)
        return InventoryMap(pages={})

    tol = int((calib or {}).get('tolerance', DEFAULT_TOLERANCE))
    aligner = align_fn if align_fn is not None else auto_align

    use_vec = VECTORIZED_DEFAULT if vectorized is None else bool(vectorized)
    if use_vec:
        return _recognize_pages_vectorized(captured, db, calib, aligner,
                                           progress_fn, max_workers, tol,
                                           record_fn)

    # ALIGN-ONCE: lock the grid once on the richest page, reuse for all tabs.
    # Then fan the slots out. Pre-size each page's result list so workers can drop
    # their SlotResult into a fixed row-major index with no shared mutation race
    # (each (page, row, col) writes a distinct cell).
    lattices = _lock_lattices(captured, db, calib, aligner, record_fn)
    page_results = {}
    jobs = []  # (page, row, col, flat_index)
    for page in captured:
        page_results[page] = [None] * SLOTS_PER_PAGE
        for flat, (row, col) in enumerate(slot_indices()):
            jobs.append((page, row, col, flat))

    total = len(jobs)

    def _emit_progress(done):
        if progress_fn is None:
            return
        try:
            progress_fn(done, total)
        except Exception:
            pass  # progress is cosmetic; never let it abort the scan

    def _work(job):
        page, row, col, flat = job
        try:
            res = _classify_one_slot(captured[page], db, lattices[page],
                                     page, row, col, tol)
        except Exception:
            res = SlotResult(state=STATE_UNKNOWN, name=None,
                             distance=float('inf'), margin=0.0,
                             signature=None, page=page, row=row, col=col)
        return page, flat, res

    workers = _resolve_workers(max_workers, total)
    done = 0
    if workers <= 1:
        # Serial fallback (single worker / no pool) -- same progress sequence.
        for job in jobs:
            page, flat, res = _work(job)
            page_results[page][flat] = res
            done += 1
            _emit_progress(done)
    else:
        try:
            with ThreadPoolExecutor(max_workers=workers,
                                    thread_name_prefix='inv-recognize') as ex:
                # as_completed (NICHT ex.map): map liefert in EINREICH-Reihenfolge,
                # d. h. ein langsamer fruehrer Slot blockiert den Fortschritt, bis
                # er fertig ist (Anzeige klebt, springt dann) -- as_completed feuert
                # _emit_progress genau dann, wenn IRGENDEIN Slot fertig ist, also
                # echt slot-granular + monoton (s. Docstring: "after each slot").
                futs = [ex.submit(_work, job) for job in jobs]
                for fut in as_completed(futs):
                    page, flat, res = fut.result()
                    page_results[page][flat] = res
                    done += 1
                    _emit_progress(done)
        except Exception as exc:
            # Pool blew up (extremely unlikely) -> finish serially so the scan
            # still returns a full map rather than raising.
            _log('inventory.scan_page_failed', page='recognize',
                 detail=str(exc)[:120])
            for job in jobs:
                page, flat, res = _work(job)
                if page_results[page][flat] is None:
                    page_results[page][flat] = res
                    done += 1
                    _emit_progress(done)

    # ALIGN-ONCE fallback: a page the SHARED grid placed with ZERO items might be
    # mis-fit (the one case worth a second align). Re-align it ALONE; if its own
    # lattice differs, re-classify that page with it. Only fires for a >1-page
    # scan where the shared lattice produced no item -- the stable bag never hits
    # this, so it stays bit-identical + single-align there.
    if len(captured) > 1:
        for page in list(page_results.keys()):
            if _page_has_item(page_results[page]):
                continue
            relat = _realign_page(captured[page], db, calib, aligner,
                                  lattices.get(page))
            if relat is None:
                continue
            lattices[page] = relat
            if record_fn is not None:
                _safe_record(record_fn, page, captured[page], relat)
            page_results[page] = [
                _classify_one_slot(captured[page], db, relat, page, row, col,
                                   tol)
                for (row, col) in slot_indices()]

    pages_out = {page: tuple(slots) for page, slots in page_results.items()}
    _log('inventory.scan_done', pages=len(pages_out))
    return InventoryMap(pages=pages_out)


def _realign_page(image, db, calib, aligner, shared_lattice):
    """Re-align ONE page on its own (or ``None`` to skip the re-classify).

    The align-once fallback: when the shared grid placed a page with no item, try
    aligning THAT page independently. Returns the page's own lattice ONLY when it
    is BOTH usable AND actually different from the shared one (otherwise there is
    nothing to gain -- return ``None`` so the caller keeps the shared result and
    pays no re-classify). Defensive: an aligner that raises -> ``None``.
    """
    try:
        relat = aligner(image, db, calib)
    except Exception as exc:
        _log('inventory.scan_page_failed', page='realign', detail=str(exc)[:120])
        return None
    if relat is None or relat == shared_lattice:
        return None
    return relat


def _recognize_pages_vectorized(captured, db, calib, aligner, progress_fn,
                                max_workers, tol, record_fn=None):
    """Vectorised twin of :func:`recognize_pages`: PAGE-fanout, batched matcher.

    Locks the grid with the SAME align-once policy as the slot path
    (:func:`_lock_lattices`: one auto-align on the richest page, reused across the
    fixed-window tabs), then runs ONE :func:`_recognize_page_vectorized` per page
    -- each page is a single batched numpy reduction over its 45 slots -- and fans
    the PAGES across the thread pool (the heavy reduction is GIL-free, so pages
    overlap). The result map is identical to the per-slot path.

    Progress stays in SLOT units for an unchanged 0..100%% UI contract: a page
    contributes its :data:`SLOTS_PER_PAGE` ticks (``done`` += 1 each) when it
    completes, collected single-threaded via :func:`as_completed`, so ``done``
    rises monotonically 1..``total`` with ``total = pages * 45`` and the last
    tick equals ``total``. Never raises: a page whose vectorised recognition
    fails degrades to the per-slot loop (inside :func:`recognize_page`) or, in
    the extreme, to 45 UNKNOWN slots, but the scan always returns a full map.
    """
    lattices = _lock_lattices(captured, db, calib, aligner, record_fn)
    page_results = {page: None for page in captured}

    pages = list(captured.keys())
    total = len(pages) * SLOTS_PER_PAGE
    done = 0

    def _emit_progress(d):
        if progress_fn is None:
            return
        try:
            progress_fn(d, total)
        except Exception:
            pass  # progress is cosmetic; never let it abort the scan

    def _work(page):
        # One whole page through the batched matcher. recognize_page already
        # degrades to the per-slot loop if the batch is unavailable; wrap once
        # more so a page NEVER aborts the scan (worst case: 45 UNKNOWN).
        try:
            slots = recognize_page(captured[page], db, calib,
                                   lattice=lattices[page], page=page,
                                   vectorized=True)
        except Exception as exc:
            _log('inventory.scan_page_failed', page=page, detail=str(exc)[:120])
            slots = [SlotResult(state=STATE_UNKNOWN, name=None,
                                distance=float('inf'), margin=0.0,
                                signature=None, page=page, row=row, col=col)
                     for (row, col) in slot_indices()]
        return page, slots

    def _collect(page, slots):
        nonlocal done
        page_results[page] = tuple(slots)
        # Emit this page's 45 slot ticks so the bar advances in slot units.
        for _ in range(SLOTS_PER_PAGE):
            done += 1
            _emit_progress(done)

    workers = _resolve_workers(max_workers, len(pages))
    if workers <= 1:
        for page in pages:
            _collect(*_work(page))
    else:
        try:
            with ThreadPoolExecutor(max_workers=workers,
                                    thread_name_prefix='inv-recognize') as ex:
                futs = [ex.submit(_work, page) for page in pages]
                for fut in as_completed(futs):
                    page, slots = fut.result()
                    _collect(page, slots)
        except Exception as exc:
            # Pool blew up -> finish serially so a full map still returns.
            _log('inventory.scan_page_failed', page='recognize',
                 detail=str(exc)[:120])
            for page in pages:
                if page_results[page] is None:
                    _collect(*_work(page))

    # ALIGN-ONCE fallback (mirrors the slot path): re-align + re-recognise ONLY a
    # >1-page scan's page the shared grid placed with no item. Stable bag: no-op.
    if len(pages) > 1:
        for page in pages:
            slots = page_results.get(page)
            if slots is None or _page_has_item(slots):
                continue
            relat = _realign_page(captured[page], db, calib, aligner,
                                  lattices.get(page))
            if relat is None:
                continue
            lattices[page] = relat
            if record_fn is not None:
                _safe_record(record_fn, page, captured[page], relat)
            try:
                page_results[page] = tuple(recognize_page(
                    captured[page], db, calib, lattice=relat, page=page,
                    vectorized=True))
            except Exception as exc:
                _log('inventory.scan_page_failed', page=page,
                     detail=str(exc)[:120])

    pages_out = {page: page_results[page] for page in pages
                 if page_results[page] is not None}
    _log('inventory.scan_done', pages=len(pages_out))
    return InventoryMap(pages=pages_out)


def _resolve_workers(max_workers, total):
    """Clamp the worker count to a sane pool size for ``total`` tasks.

    ``None`` -> a pool sized to the CPU count, capped at :data:`_WORKER_CAP`,
    never exceeding the number of jobs, floored at 2 (so a single-core box still
    overlaps the matcher's GIL-free numpy with Python). A caller forces serial
    with ``max_workers=1``.

    On the DEFAULT path (page-vectorised) ``total`` == number of buffered pages
    (<= 4), so the pool is 4 regardless of the cap -- that is already the most
    overlap available there. MEASURED REALITY (32-core build box): beyond ~4 the
    wall time barely moves, because the recognition's dominant cost is the printed
    stack-count OCR (PIL, which holds the GIL) -- only the numpy MATCHER releases
    the GIL and overlaps. So the cap is generous enough not to throttle the
    GIL-free matcher in any larger fan-out (e.g. the per-slot fallback's 180
    tasks) yet not so large that scheduling a huge GIL-contended pool wastes time.
    """
    if total <= 1:
        return 1
    if max_workers is not None:
        try:
            return max(1, min(int(max_workers), total))
        except Exception:
            return 1
    try:
        import os
        cpu = os.cpu_count() or 1
    except Exception:
        cpu = 1
    return max(2, min(cpu, _WORKER_CAP, total))


#: Upper bound on the auto-sized recognise pool. The page-vectorised default fans
#: only <= 4 page tasks, so this mainly bounds the per-slot fallback (180 tasks);
#: raised from the old 8 so the GIL-free numpy matcher can overlap freely on a
#: many-core box, while staying modest because the GIL-bound OCR (the dominant
#: cost) does not scale with more threads (see :func:`_resolve_workers`).
_WORKER_CAP = 16


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
                   hover_fn=None, verify_page_fn=None, progress_fn=None):
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
    :param progress_fn: optional ``(page, index, total) -> None`` called ONCE
        just before each page's work starts (``index`` is 1-based) so the UI can
        show live per-page feedback instead of only a final summary. Defaults to
        ``None`` (no progress) and is wrapped defensively -- a raising callback
        never aborts the scan.
    :return: :class:`InventoryMap` keyed by the pages successfully scanned.
    """
    page_results = {}
    total = len(pages)
    for index, page in enumerate(pages, start=1):
        if progress_fn is not None:
            try:
                progress_fn(page, index, total)
            except Exception:
                pass  # progress is cosmetic; never let it abort the scan
        results = _scan_one_page(page, capture_fn, switch_page_fn, hover_fn,
                                 verify_page_fn, db, calib)
        if results is None:
            continue
        page_results[page] = results
    _log('inventory.scan_done', pages=len(page_results))
    return InventoryMap(pages=page_results)
