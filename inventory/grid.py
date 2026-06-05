"""Grid geometry, slot extraction, auto-alignment, and active-page detection.

The capture boundary lives here: :func:`extract_slot` converts the captured
BGR image (``WindowCapture.get_screenshot`` order) to the engine-internal RGB
float32 once. :func:`auto_align` re-locks the grid per scan (recovers the
documented session drift) by a dense origin-offset sweep that picks the lattice
maximising the NUMBER of confidently matched slots (see :func:`auto_align`).

numpy is SOFT-imported (mirrors :mod:`detection`). Without it the geometry
helpers still work on Python lists where feasible, and :func:`auto_align` /
:func:`extract_slot` return the calibration lattice / ``None`` rather than
raising. Tests force the fallback with ``grid.np = None``.
"""

from dataclasses import dataclass
from typing import Tuple

from .constants import (
    SLOT_PX,
    COLS,
    ROWS,
    EMPTY_REF,
    UPPER_REGION_END,
    AUTO_ALIGN_RADIUS,
    AUTO_ALIGN_ROW_REACH,
    AUTO_ALIGN_CACHE_REFINE,
    ACTIVE_TAB_SAMPLE,
    MATCH_THRESHOLD,
    DEFAULT_TOLERANCE,
    PAGES,
    slot_indices,
)
import threading
from i18n import t

try:  # pragma: no cover - exercised on machines with numpy
    import numpy as np
except Exception:  # pragma: no cover
    np = None

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


@dataclass(frozen=True)
class GridLattice:
    """A locked inventory lattice: top-left origin + per-axis pitch (px)."""

    origin: Tuple[int, int]
    pitch: Tuple[int, int]

    def slot_box(self, row, col):
        """``(x, y, w, h)`` of slot ``(row, col)`` (always SLOT_PX x SLOT_PX)."""
        ox, oy = self.origin
        px, py = self.pitch
        x = int(ox + col * px)
        y = int(oy + row * py)
        return (x, y, SLOT_PX, SLOT_PX)


def lattice_from_calibration(calib):
    """Build the initial :class:`GridLattice` from a calibration dict.

    Origin = ``grid.tl``; per-axis pitch derived from ``(br - tl)`` over
    ``cols-1`` / ``rows-1`` (so the slots span tl..br), rounded to int. Falls
    back to SLOT_PX pitch if the span is degenerate.
    """
    grid = (calib or {}).get('grid', {})
    tl = grid.get('tl', [0, 0])
    br = grid.get('br', [tl[0] + SLOT_PX * COLS, tl[1] + SLOT_PX * ROWS])
    cols = int(grid.get('cols', COLS))
    rows = int(grid.get('rows', ROWS))
    span_x = int(br[0]) - int(tl[0])
    span_y = int(br[1]) - int(tl[1])
    pitch_x = int(round(span_x / (cols - 1))) if cols > 1 else SLOT_PX
    pitch_y = int(round(span_y / (rows - 1))) if rows > 1 else SLOT_PX
    if pitch_x <= 0:
        pitch_x = SLOT_PX
    if pitch_y <= 0:
        pitch_y = SLOT_PX
    return GridLattice(origin=(int(tl[0]), int(tl[1])),
                       pitch=(pitch_x, pitch_y))


def extract_slot(image_bgr, box):
    """Extract a slot as a ``(SLOT_PX, SLOT_PX, 3)`` float32 RGB array.

    ``image_bgr`` is the captured image in BGR (``img[y, x]``); this is the
    single BGR->RGB conversion boundary. ``box`` is ``(x, y, w, h)``. If the box
    runs past the image it is clamped and the missing border is edge-replicated,
    so a slightly off-image lattice still yields a full 32x32 slot. Returns
    ``None`` if numpy is missing or the image is unusable.
    """
    if np is None or image_bgr is None:
        return None
    img = np.asarray(image_bgr)
    if img.ndim != 3 or img.shape[2] < 3:
        return None
    h, w = img.shape[0], img.shape[1]
    x, y, bw, bh = int(box[0]), int(box[1]), int(box[2]), int(box[3])

    # Clamp the read window to the image, remember the in-frame sub-rectangle.
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(w, x + bw), min(h, y + bh)
    out = np.zeros((bh, bw, 3), dtype=np.float32)
    if x1 > x0 and y1 > y0:
        sub = img[y0:y1, x0:x1, :3].astype(np.float32)
        # BGR -> RGB (single conversion point for the whole engine).
        sub_rgb = sub[:, :, ::-1]
        dy0, dx0 = y0 - y, x0 - x
        out[dy0:dy0 + sub_rgb.shape[0], dx0:dx0 + sub_rgb.shape[1], :] = sub_rgb
        _fill_edges(out, dy0, dx0, sub_rgb.shape[0], sub_rgb.shape[1])
    return out


def _fill_edges(out, dy0, dx0, ih, iw):
    """Replicate the placed sub-rectangle into vacated border rows/cols."""
    if ih <= 0 or iw <= 0:
        return
    top, bottom = dy0, dy0 + ih
    left, right = dx0, dx0 + iw
    if top > 0:
        out[:top, left:right, :] = out[top:top + 1, left:right, :]
    if bottom < out.shape[0]:
        out[bottom:, left:right, :] = out[bottom - 1:bottom, left:right, :]
    if left > 0:
        out[:, :left, :] = out[:, left:left + 1, :]
    if right < out.shape[1]:
        out[:, right:, :] = out[:, right - 1:right, :]


def upper_region_is_empty(slot_rgb, tol=DEFAULT_TOLERANCE):
    """True iff the number-free upper region is ~EMPTY_REF within ``tol``.

    Per-channel mean absolute deviation from EMPTY_REF over rows
    0..UPPER_REGION_END-1. Glow-aware: glow recolours the WHOLE slot uniformly,
    so a glowing-but-empty slot's upper region is uniform (not EMPTY_REF) --
    this probe returns False for it, and the classifier then relies on the
    (high) match distance to still call it empty/unknown correctly. Returns
    True for an exactly-empty dark slot.
    """
    if np is None or slot_rgb is None:
        return False
    arr = np.asarray(slot_rgb, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[2] != 3:
        return False
    end = min(UPPER_REGION_END, arr.shape[0])
    upper = arr[:end, :, :]
    ref = np.array(EMPTY_REF, dtype=np.float32).reshape(1, 1, 3)
    dev = float(np.abs(upper - ref).mean())
    return dev <= float(tol)


# -- SESSION CACHE: the inventory window is FIXED, so reuse the last lock -----
#
# A whole session scans the SAME fixed window, so after the first (~441-candidate)
# cold sweep the grid origin no longer changes. We cache the last lock and, on the
# next call, probe just the cached origin with a tiny DENSE +-AUTO_ALIGN_CACHE_REFINE
# full-res sweep; a reused lock costs <<1s instead of the full sweep. The cache is
# keyed on (calibration grid + image shape) so a different calibration / capture
# size never reuses a stale lock, and it transparently falls back to the cold
# sweep whenever the cheap probe cannot reproduce an adequately-fitting grid (the
# window genuinely moved). Module-level + lock-guarded; the align-once scanner
# calls the aligner serially, so there is no in-scan contention.
_align_cache_lock = threading.Lock()
_align_cache = None   # dict(key, lattice, count) or None


def _cache_key(calib, image_bgr):
    """Hashable identity of (calibration grid geometry, image shape).

    Two scans of the SAME fixed window with the SAME calibration share a key, so
    the cached lock is eligible for reuse; any change to the grid calibration or
    the captured frame size yields a different key (no stale reuse). ``None`` if
    the image has no usable shape (then caching is skipped)."""
    grid = (calib or {}).get('grid', {})
    try:
        tl = tuple(grid.get('tl', [0, 0]))
        br = tuple(grid.get('br', [0, 0]))
        cols = int(grid.get('cols', COLS))
        rows = int(grid.get('rows', ROWS))
        shape = tuple(np.asarray(image_bgr).shape) if np is not None else None
    except Exception:
        return None
    if shape is None:
        return None
    return (tl, br, cols, rows, shape)


def reset_align_cache():
    """Forget the cached lock (e.g. when the user re-calibrates). Never raises."""
    global _align_cache
    with _align_cache_lock:
        _align_cache = None


def _cached_lattice(key):
    """Return the cached ``(lattice, count)`` for ``key`` (or ``None``)."""
    with _align_cache_lock:
        c = _align_cache
    if c is not None and key is not None and c.get('key') == key:
        return c.get('lattice'), int(c.get('count', 0))
    return None


def _store_lattice(key, lattice, count):
    """Cache ``lattice`` (+ its match count) under ``key`` for the next scan."""
    global _align_cache
    if key is None or lattice is None:
        return
    with _align_cache_lock:
        _align_cache = {'key': key, 'lattice': lattice, 'count': int(count)}


def _cache_reuse_ok(refined_count, prev_count):
    """Decide whether a refined-around-cache lock may be REUSED (vs cold sweep).

    The session window is fixed, so an unmoved window keeps its item count (the
    refine reproduces >= the cached count); moderate bag churn only nudges it. A
    genuine window MOVE past the small refine window instead collapses the count
    to ~0 at the stale origin -- that must fall back to the full cold sweep.

      * cached bag was EMPTY (``prev_count`` <= 0): NEVER reuse. A zero count is
        no signal at all -- the stale origin reads ~0 whether the window is still
        there (empty) OR has moved away (items now sit elsewhere, off the refine
        window). Trusting refine==0 would silently LOCK the stale empty origin
        after a move and miss every item that re-appeared at the new position.
        Falling back to the cold sweep costs one extra sweep on an empty bag but
        always re-locks the real grid; an empty bag mislock is harmless (no item
        to misattribute), a moved-bag mislock loses real items.
      * cached bag had items: reuse iff the refine still finds at least HALF of
        them (floored at 2). Half tolerates real item removal between scans while
        still catching a move (which drops the count to ~0).
    """
    if prev_count <= 0:
        return False
    return refined_count >= max(2, prev_count // 2)


def _refine_around(image_bgr, db, calib, center,
                   refine=AUTO_ALIGN_CACHE_REFINE):
    """Best lattice in a dense +-``refine`` window around ``center`` (CHEAP).

    Uses the SAME cheap DOWNSAMPLED scorer as the cold sweep's per-band search
    (:func:`_lattice_score`), ranked exactly as a band is -- max matched count,
    then min mean distance -- plus an offset-from-``center`` final tie-break. So a
    tiny +-3 window costs ~49 downsampled candidates (a few ms), and -- centred on
    the previous lock -- it reproduces the cold sweep's downsampled peak EXACTLY
    when the window is unmoved (the true peak sits at offset 0, winning the
    tie-break). Returns ``(lattice, matched_count)`` (downsampled count, the same
    unit the cold sweep and :func:`aligned_match_count` use) or ``None`` if every
    candidate is off-image."""
    cx, cy = center
    px, py = lattice_from_calibration(calib).pitch
    boxes = slot_indices()
    best_key = None
    best_lat = None
    best_count = 0
    for dy in range(-refine, refine + 1):
        for dx in range(-refine, refine + 1):
            cand = GridLattice(origin=(cx + dx, cy + dy), pitch=(px, py))
            s = _lattice_score(image_bgr, db, cand, boxes)
            if s is None:
                continue
            off = abs(dx) + abs(dy)
            key = (-s[0], s[1], off)
            if best_key is None or key < best_key:
                best_key = key
                best_lat = cand
                best_count = int(s[0])
    if best_lat is None:
        return None
    return best_lat, best_count


def auto_align(image_bgr, db, calib, radius=AUTO_ALIGN_RADIUS,
               row_reach=AUTO_ALIGN_ROW_REACH):
    """Re-lock the grid for THIS image, REUSING the cached lock when possible.

    SESSION-CACHE fast path: the inventory window is fixed for a session, so after
    the first cold sweep the grid origin is stable. If a lock was cached for this
    (calibration, image-shape) key, probe ONLY the cached origin with a tiny dense
    +-``AUTO_ALIGN_CACHE_REFINE`` full-res sweep (:func:`_refine_around`). When that
    still locks an adequately-fitting grid (item count not collapsed vs the cached
    lock) it is reused in <<1s -- and, being centred on the previous origin, it
    reproduces the cold-sweep winner EXACTLY whenever the window is unmoved. If the
    probe's count collapsed (the window moved past the refine window) the full cold
    sweep below runs and re-seeds the cache. The cold sweep itself is unchanged, so
    the FIRST scan and any genuine re-lock are byte-identical to before.

    COLD SWEEP (:func:`_auto_align_cold`): start from ``lattice_from_calibration``
    and try integer origin offsets, choosing the offset that

        maximises   the count of slots with best masked distance <= threshold,
        then minimises the mean of those matched distances,
        then minimises ``|dx| + |dy|`` (stay closest to the calibration guess).

    Rewarding the MATCH COUNT (rather than averaging an always-positive
    occupied distance) fixes the sparse-page failure where the old objective
    slid the grid until items fell into the dark inter-slot gaps and "won" by
    registering zero occupied cells. On an ALL-empty page every candidate ties at
    (0 matches, inf mean), so the lock is geometry-arbitrary (it settles on a
    band corner near calibration) -- which is harmless: with no item in any slot,
    every origin extracts the same empty/unknown classification. The session
    cache must NOT trust that zero-count lock though (see :func:`_cache_reuse_ok`):
    a later window MOVE would otherwise be missed.

    The cold sweep (see :func:`_auto_align_cold`) has TWO stages (each can only
    pick a STRICTLY better key, so a calibration that is already correct stays
    put -- the nearer offset wins ties):

      1. PER-ROW-BAND dense sweep: for each whole-row shift
         ``k in [-row_reach..+row_reach]`` run a DENSE ``[-radius..radius]^2``
         search around ``(calib_x, calib_y + k*pitch_y)`` and keep that band's
         own best-fit representative (most matches, then lowest mean -- no
         calibration bias inside a band). The ``k != 0`` bands bridge a WHOLE-ROW
         calibration drift (an inventory sitting one slot-row off the bundled
         default), which the ``+-radius`` window alone cannot reach and which
         would otherwise drop the off-grid row + invent a phantom one. The sweep
         is dense (every integer offset) so the 1-px match-count well of a sparse
         page is never stepped over.
      2. FULL-RESOLUTION cross-band re-rank: re-score the (deduplicated) band
         representatives with the sharp full-32x32 classifier and pick the most
         confident items, then lowest mean distance, then NEAREST to the
         calibration origin (``|dx|+|dy|``). The proximity tie-break is decisive
         for a full bag, where a one-row shift is an EQUAL-quality alias -- ties
         fall back to the trusted calibration row, while a genuinely better band
         (strictly more matches) still wins on the count. There is no extra
         refine pass: each band representative is ALREADY its dense-sweep peak.

    To keep the sweep fast the scoring matches DOWNSAMPLED references
    (:meth:`ItemDB.alignment_distances`). Returns the locked
    :class:`GridLattice` (the calibration lattice unchanged if numpy is missing
    or there is no usable DB).
    """
    base = lattice_from_calibration(calib)
    if np is None or image_bgr is None or db is None:
        return base
    if getattr(db, 'alignment_distances', None) is None:
        return base

    tol = int((calib or {}).get('tolerance', DEFAULT_TOLERANCE))
    key = _cache_key(calib, image_bgr)

    # SESSION-CACHE fast path: confirm/adjust the previous lock with a tiny refine.
    cached = _cached_lattice(key)
    if cached is not None:
        prev_lat, prev_count = cached
        refined = _refine_around(image_bgr, db, calib, prev_lat.origin)
        if refined is not None and _cache_reuse_ok(refined[1], prev_count):
            lat, cnt = refined
            _store_lattice(key, lat, cnt)
            _log('inventory.grid_locked', origin=lat.origin,
                 pitch=lat.pitch, fit=cnt)
            return lat

    lat = _auto_align_cold(image_bgr, db, calib, base, tol, radius, row_reach)
    # Seed/refresh the cache with the cold lock + its DOWNSAMPLED match count (the
    # same unit _refine_around / _cache_reuse_ok compare against next scan).
    try:
        _store_lattice(key, lat, aligned_match_count(image_bgr, db, lat))
    except Exception:
        pass
    return lat


def _auto_align_cold(image_bgr, db, calib, base, tol,
                     radius=AUTO_ALIGN_RADIUS, row_reach=AUTO_ALIGN_ROW_REACH):
    """The full cold origin sweep (unchanged behaviour) -> locked GridLattice.

    Factored out of :func:`auto_align` so the session-cache fast path can wrap it;
    the search itself (dense +-radius per row-band, full-res cross-band re-rank) is
    byte-identical to the historic ``auto_align`` body, so the first scan and any
    genuine re-lock produce exactly the same origin as before. ``base`` is the
    calibration lattice, ``tol`` the empty/match tolerance."""
    ox, oy = base.origin
    px, py = base.pitch
    boxes = slot_indices()

    def band_rep(center_y):
        """Best-aligned FUZZY lattice in the dense +-radius window around
        ``(ox, center_y)``, localised PURELY by fit (max matches, then lowest
        mean) -- no calibration bias here, so each band reports its own true
        peak. The calibration-proximity tie-break lives in the cross-band step.
        """
        bk = None
        bl = None
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                cand = GridLattice(origin=(ox + dx, center_y + dy),
                                   pitch=(px, py))
                s = _lattice_score(image_bgr, db, cand, boxes)
                if s is None:
                    continue
                key = (-s[0], s[1])
                if bk is None or key < bk:
                    bk = key
                    bl = cand
        return bl

    # One representative per ROW-BAND: the calibration row (k=0) plus +-row_reach
    # whole-row shifts. A whole-row calibration drift puts the true origin in a
    # NEIGHBOURING band that the +-radius dense sweep alone cannot reach.
    reps = []
    seen = set()
    for k in range(-int(row_reach or 0), int(row_reach or 0) + 1):
        lat = band_rep(oy + k * py)
        if lat is not None and lat.origin not in seen:
            seen.add(lat.origin)
            reps.append(lat)

    if not reps:
        return base
    if len(reps) == 1:
        best_lat = reps[0]
        fit = None
    else:
        # Decide BETWEEN bands at FULL RESOLUTION: most confident items, then
        # lowest mean distance, then NEAREST to the calibration origin. The last
        # key is decisive for a full inventory, where a one-row shift is a real
        # alias of EQUAL quality (each row's slot just remaps to the next) -- so
        # ties must fall back to the trusted calibration row, while a genuinely
        # better band (e.g. a foreign client one row off, with strictly more
        # matches) still wins on the count.
        best_key = None
        best_lat = reps[0]
        fit = None
        for lat in reps:
            fm = _lattice_score_full(image_bgr, db, lat, boxes, tol)
            if fm is None:
                continue
            off = abs(lat.origin[0] - ox) + abs(lat.origin[1] - oy)
            key = (-fm[0], fm[1], off)
            if best_key is None or key < best_key:
                best_key = key
                best_lat = lat
                fit = fm[0]

    _log('inventory.grid_locked',
         origin=best_lat.origin, pitch=best_lat.pitch, fit=fit)
    return best_lat


def aligned_match_count(image_bgr, db, lattice, thr=MATCH_THRESHOLD):
    """Cheap count of confidently-matched slots for ``image_bgr`` at ``lattice``.

    A thin public wrapper over the downsampled alignment scorer
    (:func:`_lattice_score`) returning JUST the matched-slot count (0 when the
    image/db/numpy is unusable). Used by the scanner's ALIGN-ONCE optimisation to
    pick the buffered page with the MOST items as the single auto-align anchor
    (the grid is identical across all four fixed-window tabs, so one lock serves
    every page -- but locking on the page richest in items gives auto_align the
    most signal to recover the documented row drift). Pure; never raises.
    """
    if np is None or image_bgr is None or db is None:
        return 0
    if getattr(db, 'alignment_distances', None) is None:
        return 0
    score = _lattice_score(image_bgr, db, lattice, slot_indices(), thr)
    if score is None:
        return 0
    return int(score[0])


#: Lazily-resolved ``itemdb.downsample_slot`` (imported on first use to avoid the
#: grid<->itemdb import cycle). Cached at module level so the alignment sweep --
#: which calls :func:`_lattice_score` ~1300x per scan -- does NOT repeat a
#: ``from .itemdb import`` (sys.modules dict lookup + getattr) on every call.
_downsample_slot = None


def _get_downsample_slot():
    """Return ``itemdb.downsample_slot``, importing+caching it once. Lazy import
    keeps the grid<->itemdb cycle from forming at module load."""
    global _downsample_slot
    if _downsample_slot is None:
        from .itemdb import downsample_slot as _ds
        _downsample_slot = _ds
    return _downsample_slot


def _lattice_score(image_bgr, db, lattice, boxes, thr=MATCH_THRESHOLD):
    """Score one candidate lattice: ``(matched_count, mean_matched_distance)``.

    A slot counts as matched when its best DOWNSAMPLED masked distance is
    ``<= thr``. The candidate-origin sweep IS the offset search, so the per-slot
    distance is taken at zero internal shift (cheap). Returns ``None`` if a slot
    cannot be extracted (off-image lattice) so that candidate is skipped.

    NOTE: this is the dense-sweep inner loop (called ~1300x per cold align), so it
    keeps the per-slot ``alignment_distances`` form -- measured FASTER than a
    batched ``(M, N, P)`` reduction here, because the downsampled reference axis is
    small and the per-slot call reuses the cached reference stack with a tiny
    intermediate, whereas the batch materialises a 45x-larger memory-bound tensor.
    The cold-sweep cost is instead amortised by the SESSION CACHE (see
    :func:`auto_align`): only the FIRST scan of a fixed window pays the full sweep.
    """
    downsample_slot = _get_downsample_slot()
    matched = 0
    sum_dist = 0.0
    for row, col in boxes:
        slot = extract_slot(image_bgr, lattice.slot_box(row, col))
        if slot is None:
            return None
        dists = db.alignment_distances(downsample_slot(slot))
        if dists is None:
            return None
        best = float(dists.min())
        if best <= thr:
            matched += 1
            sum_dist += best
    mean_dist = (sum_dist / matched) if matched else float('inf')
    return matched, mean_dist


def _lattice_score_full(image_bgr, db, lattice, boxes, tol):
    """Score a candidate at FULL resolution: ``(item_count, mean_distance)``.

    Uses the real per-slot classifier (:meth:`ItemDB.best_slot_result`, the
    same one :func:`inventory.scanner.classify_slot` calls) so a slot only
    counts when it is a CONFIDENT item on the full 32x32 pixels -- the sharp
    arbiter the fuzzy downsampled :func:`_lattice_score` cannot be. Returns
    ``None`` if a slot cannot be extracted (off-image candidate -> skip it).
    """
    from .types import STATE_ITEM
    matched = 0
    sum_dist = 0.0
    for row, col in boxes:
        slot = extract_slot(image_bgr, lattice.slot_box(row, col))
        if slot is None:
            return None
        empty = upper_region_is_empty(slot, tol)
        res = db.best_slot_result(slot, row=row, col=col, page=None,
                                  empty=empty, tol=tol)
        if res.state == STATE_ITEM:
            matched += 1
            sum_dist += res.distance
    mean_dist = (sum_dist / matched) if matched else float('inf')
    return matched, mean_dist


def active_page(image_bgr, calib):
    """Return the open page label by sampling the 4 tab points (brightest wins).

    Sample point = ``tab_center + tab_active.offset`` (per calibration). Around
    that point a small ``ACTIVE_TAB_SAMPLE``-radius window MEAN is taken (clamped
    to the image), not a single pixel: a lone pixel can land on tab text/border
    highlight and leave only ~20 brightness units between the open and a closed
    tab, which could flip on a different theme/resolution/glow; the window mean
    widens the active/inactive gap several-fold (measured ~90-120 units on the
    real shots) for the SAME brightest-of-4 decision. The brightest sample is the
    open tab. Returns the FIRST page label when numpy is missing or sampling
    fails (deterministic default).
    """
    pages = list(PAGES)
    if np is None or image_bgr is None:
        return pages[0]
    img = np.asarray(image_bgr)
    if img.ndim != 3 or img.shape[2] < 3:
        return pages[0]
    h, w = img.shape[0], img.shape[1]
    tabs = (calib or {}).get('tabs', {})
    offset = (calib or {}).get('tab_active', {}).get('offset', [0, 0])
    ox, oy = int(offset[0]), int(offset[1])
    rad = int(ACTIVE_TAB_SAMPLE)

    best_label = pages[0]
    best_bright = None
    for label in pages:
        center = tabs.get(label)
        if not center:
            continue
        sx = int(center[0]) + ox
        sy = int(center[1]) + oy
        if not (0 <= sx < w and 0 <= sy < h):
            continue
        # Clamped window mean around (sx, sy) -- far more discriminative than one
        # pixel, and the +-rad box always contains the centre so it is non-empty.
        x0 = max(0, sx - rad)
        x1 = min(w, sx + rad + 1)
        y0 = max(0, sy - rad)
        y1 = min(h, sy + rad + 1)
        patch = np.asarray(img[y0:y1, x0:x1, :3], dtype=np.float32)
        bright = float(patch.mean())
        if best_bright is None or bright > best_bright:
            best_bright = bright
            best_label = label
    return best_label
