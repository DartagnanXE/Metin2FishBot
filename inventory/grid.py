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
    ACTIVE_TAB_SAMPLE,
    MATCH_THRESHOLD,
    DEFAULT_TOLERANCE,
    PAGES,
    slot_indices,
)
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


def auto_align(image_bgr, db, calib, radius=AUTO_ALIGN_RADIUS):
    """Re-lock the grid for THIS image by a dense origin-offset sweep.

    Starts from ``lattice_from_calibration`` and tries every integer origin
    offset ``dy,dx in [-radius..radius]^2`` (pitch held -- the documented
    failure was a pure origin drift). For each candidate lattice it scores how
    many slots hold a confident reference match, choosing the offset that

        maximises   the count of slots with best masked distance <= threshold,
        then minimises the mean of those matched distances,
        then minimises ``|dx| + |dy|`` (stay closest to the calibration guess).

    Rewarding the MATCH COUNT (rather than averaging an always-positive
    occupied distance) fixes the sparse-page failure where the old objective
    slid the grid until items fell into the dark inter-slot gaps and "won" by
    registering zero occupied cells. The ``|dx|+|dy|`` tie-break makes an all-
    empty page (every count 0) lock to the calibration origin, not a corner.

    To keep the dense sweep fast the scoring matches DOWNSAMPLED references
    (:meth:`ItemDB.alignment_distances`); localisation does not need full
    resolution. Returns the locked :class:`GridLattice` (the calibration lattice
    unchanged if numpy is missing or there is no usable DB).
    """
    base = lattice_from_calibration(calib)
    if np is None or image_bgr is None or db is None:
        return base
    if getattr(db, 'alignment_distances', None) is None:
        return base

    best_key = None
    best_lattice = base
    ox, oy = base.origin
    px, py = base.pitch
    boxes = slot_indices()
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            cand = GridLattice(origin=(ox + dx, oy + dy), pitch=(px, py))
            score = _lattice_score(image_bgr, db, cand, boxes)
            if score is None:
                continue
            matched, mean_dist = score
            # Lower key wins: most matches, then lowest mean, then nearest.
            key = (-matched, mean_dist, abs(dx) + abs(dy))
            if best_key is None or key < best_key:
                best_key = key
                best_lattice = cand

    _log('inventory.grid_locked',
         origin=best_lattice.origin, pitch=best_lattice.pitch,
         fit=None if best_key is None else -best_key[0])
    return best_lattice


def _lattice_score(image_bgr, db, lattice, boxes, thr=MATCH_THRESHOLD):
    """Score one candidate lattice: ``(matched_count, mean_matched_distance)``.

    A slot counts as matched when its best DOWNSAMPLED masked distance is
    ``<= thr``. The candidate-origin sweep IS the offset search, so the per-slot
    distance is taken at zero internal shift (cheap). Returns ``None`` if a slot
    cannot be extracted (off-image lattice) so that candidate is skipped.
    """
    from .itemdb import downsample_slot
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
