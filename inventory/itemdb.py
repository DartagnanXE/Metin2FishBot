"""The recognition database and the matcher core.

:class:`ItemDB` holds the references (built once from the bundled icons) and
scores a captured 32x32 RGB slot against every reference. The references are
kept BOTH as the per-item :class:`ItemReference` list (build order, public) AND
as stacked numpy arrays so the matcher scores all of them in one vectorised
pass (numerically identical to a per-reference loop, ~order-of-magnitude
faster -- the per-scan hot path).

Matcher (implements the PROVEN findings exactly -- all three required):

* MASKED mean-abs-diff: only pixels where ``weight_mask > 0`` contribute, so
  the glowing / empty slot background and the stack-number band are ignored.
* ROUNDED-SHIFT search: the distance is the MIN over integer shifts
  ``dy,dx in [-SHIFT_RADIUS..SHIFT_RADIUS]^2`` -- absorbs sub-pixel / small
  session offset.
* MARGIN: confidence = (2nd-best distance - best distance). A confident item
  must clear MATCH_THRESHOLD AND beat the runner-up by >= MARGIN_MIN, so a
  near-tie between two close-family references (e.g. two hair dyes) is demoted
  to ``'unknown'`` rather than reported as a confident WRONG name.

The DB also exposes a DOWNSAMPLED-reference probe (:meth:`alignment_distances`)
used only by the auto-align origin sweep: matching 16x16 references is ~4x
cheaper per evaluation and is plenty precise for *locating* the lattice (final
classification always uses the full-resolution references).

numpy is SOFT-imported (mirrors :mod:`detection`). With numpy absent the DB
builds empty and every slot is reported ``'unknown'`` (logged) -- never raises.
Tests force the fallback with ``itemdb.np = None``.
"""

from .constants import (
    SLOT_PX,
    MATCH_THRESHOLD,
    MARGIN_MIN,
    MARGIN_PRIMARY_MIN,
    MARGIN_PRIMARY_MAX_DIST,
    SHIFT_RADIUS,
    DEFAULT_TOLERANCE,
    ALIGN_DOWNSCALE,
    EMPTY_FALLBACK_STD,
)
from .reference import build_reference, signature_of
from . import assets
from .types import SlotResult, STATE_EMPTY, STATE_ITEM, STATE_UNKNOWN
from i18n import t

try:  # pragma: no cover - exercised on machines with numpy
    import numpy as np
except Exception:  # pragma: no cover
    np = None

try:  # pragma: no cover - reiner Fallback
    from debuglog import log
except Exception:  # pragma: no cover
    log = None

# A distance that always loses (used when there is no usable DB / slot).
_INF = float('inf')


def _log(key, **fmt):
    """Log a translated event line (State 0); swallows logger errors."""
    if log is None:
        return
    try:
        log.event(0, t(key, **fmt))
    except Exception:
        pass


class ItemDB:
    """Recognition database over a fixed set of :class:`ItemReference`.

    The references are precomputed into stacked arrays once in ``__init__`` so
    the matcher scores all of them at once:

    * ``_ref_rgb``   -- ``(N, 32, 32, 3)`` float32
    * ``_mask``      -- ``(N, 32, 32, 1)`` float32 (per-pixel weight)
    * ``_mask_sum3`` -- ``(N,)`` float32 == ``mask.sum()*3`` (the normaliser)

    and a DOWNSAMPLED, flattened copy (``_ds_ref`` / ``_ds_mask`` /
    ``_ds_sum``) used only by the cheap auto-align sweep.
    """

    def __init__(self, refs):
        self._refs = list(refs or [])
        self._ref_rgb = None
        self._mask = None
        self._mask_sum3 = None
        self._ds_ref = None
        self._ds_mask = None
        self._ds_sum = None
        if np is not None and self._refs:
            self._build_stacks()

    def _build_stacks(self):
        """Stack the references into the full-res and downsampled match arrays."""
        self._ref_rgb = np.stack(
            [r.ref_rgb for r in self._refs]).astype(np.float32)
        mask = np.stack(
            [r.weight_mask for r in self._refs]).astype(np.float32)
        self._mask = mask[:, :, :, None]                       # (N,32,32,1)
        self._mask_sum3 = np.array(
            [r.mask_sum for r in self._refs], dtype=np.float32) * 3.0

        # Downsampled (block-mean) + flattened references for alignment.
        ds_rgb = _block_mean(self._ref_rgb, ALIGN_DOWNSCALE)   # (N,h,w,3)
        ds_mask = _block_mean(mask, ALIGN_DOWNSCALE)           # (N,h,w)
        n = ds_rgb.shape[0]
        self._ds_ref = ds_rgb.reshape(n, -1)                   # (N, h*w*3)
        ds_mask3 = np.repeat(ds_mask[:, :, :, None], 3, axis=3)
        self._ds_mask = ds_mask3.reshape(n, -1)                # (N, h*w*3)
        self._ds_sum = self._ds_mask.sum(axis=1)               # (N,)
        # Guard a degenerate all-transparent downsample (cannot happen for a
        # real icon, but keep the divide safe).
        self._ds_sum = np.where(self._ds_sum > 0.0, self._ds_sum, 1.0)

    @classmethod
    def from_bundled(cls):
        """Build the DB from every bundled icon (``inventory_icons/``).

        Soft path: with numpy/PIL missing or the icon dir absent, returns an
        EMPTY DB (logged) -> the engine reports every slot ``'unknown'`` rather
        than crashing.
        """
        refs = []
        if np is None:
            _log('inventory.db_no_numpy')
            return cls(refs)
        for path in assets.icon_paths():
            rgba = assets.load_icon_rgba(path)
            if rgba is None:
                continue
            rgba = assets.normalize_to_slot(rgba)
            if rgba is None:
                continue
            ref = build_reference(assets.name_from_path(path), rgba)
            if ref is not None:
                refs.append(ref)
        if not refs:
            _log('inventory.db_empty')
        else:
            _log('inventory.db_built', count=len(refs))
        return cls(refs)

    def references(self):
        """The list of :class:`ItemReference` in the DB (build order)."""
        return list(self._refs)

    # -- matcher core -----------------------------------------------------

    def match(self, slot_rgb, shift_radius=SHIFT_RADIUS):
        """``[(name, distance), ...]`` sorted ascending by masked distance.

        Empty list if numpy is missing, the DB is empty, or the slot is not a
        valid 32x32x3 array. ``shift_radius`` overrides the per-match shift
        search; callers that already sweep the offset externally pass ``0``.
        """
        if np is None or not self._refs or not _is_slot(slot_rgb):
            return []
        slot = np.asarray(slot_rgb, dtype=np.float32)
        dists = self._distances_all(slot, shift_radius)
        order = np.argsort(dists, kind='stable')
        return [(self._refs[i].name, float(dists[i])) for i in order]

    def best_distance(self, slot_rgb, shift_radius=SHIFT_RADIUS):
        """Lowest masked distance over the DB (``inf`` if none). Cheap probe."""
        if np is None or not self._refs or not _is_slot(slot_rgb):
            return _INF
        slot = np.asarray(slot_rgb, dtype=np.float32)
        return float(self._distances_all(slot, shift_radius).min())

    def alignment_distances(self, slot_ds_flat):
        """Vectorised masked MAD of one DOWNSAMPLED, flattened slot vs all refs.

        ``slot_ds_flat`` is a 1-D float32 vector of the slot block-mean-pooled
        by :data:`ALIGN_DOWNSCALE` and flattened (see :func:`downsample_slot`).
        Returns the ``(N,)`` per-reference distance (same 0..255 units as the
        full-res matcher, just on the coarse grid), or ``None`` if there is no
        usable DB. Used ONLY by the auto-align origin sweep.
        """
        if np is None or self._ds_ref is None:
            return None
        v = np.asarray(slot_ds_flat, dtype=np.float32)
        if v.ndim != 1 or v.shape[0] != self._ds_ref.shape[1]:
            return None
        diff = np.abs(v[None, :] - self._ds_ref) * self._ds_mask
        return diff.sum(axis=1) / self._ds_sum

    def best_slot_result(self, slot_rgb, row, col, page=None, empty=None,
                         tol=DEFAULT_TOLERANCE):
        """Classify one slot into a :class:`SlotResult`.

        Decision order (cheap first):

        1. EMPTY: ``empty`` is True (caller probed the number-free upper region
           against EMPTY_REF) AND there is no confident item match; OR the
           glow-aware fallback fires (no confident match AND the slot is
           near-uniform -- a glowing-but-empty slot, see below).
        2. ITEM: a confident match. EITHER the primary rule -- best masked
           distance <= MATCH_THRESHOLD AND the confidence margin (2nd-best -
           best) >= MARGIN_MIN -- OR the margin-primary rule -- best distance
           <= MARGIN_PRIMARY_MAX_DIST (slightly over threshold) AND margin >=
           MARGIN_PRIMARY_MIN (the runner-up is VERY far). The margin gate (both
           rules) keeps a near-tie between two close-family references from being
           reported as a confident WRONG name; margin-primary recovers an easy
           lingering-glow item whose icon survived but whose masked distance
           crept just over the no-glow threshold. See the constants for why the
           two margin-primary bounds cannot admit a false positive.
        3. UNKNOWN: occupied but no confident reference -> store a signature so
           the same unknown is trackable across scans.

        ``empty`` may be passed by the caller (it already extracted the slot);
        if ``None`` we treat the slot as occupied and rely on the threshold.
        """
        scored = self.match(slot_rgb)
        if not scored:
            # No usable DB / slot -> unknown if occupied, else empty.
            state = STATE_EMPTY if empty else STATE_UNKNOWN
            sig = None
            if state == STATE_UNKNOWN:
                sig = self._signature(slot_rgb)
            return SlotResult(state=state, name=None, distance=_INF,
                              margin=0.0, signature=sig, page=page,
                              row=row, col=col)

        best_name, best_dist = scored[0]
        margin = (scored[1][1] - best_dist) if len(scored) > 1 else _INF
        # A confident item must clear the threshold AND beat the runner-up by
        # the minimum margin (close-family guard -- see MARGIN_MIN). Margin-
        # primary additionally accepts an item slightly OVER the threshold when
        # the runner-up is VERY far (large margin) -- recovers easy lingering-
        # glow cases without changing the no-glow result (the bounds are chosen
        # so a truly-unmatched slot or a close-family near-tie can never fire it;
        # see MARGIN_PRIMARY_MIN / MARGIN_PRIMARY_MAX_DIST).
        primary = best_dist <= MATCH_THRESHOLD and margin >= MARGIN_MIN
        margin_primary = (best_dist <= MARGIN_PRIMARY_MAX_DIST
                          and margin >= MARGIN_PRIMARY_MIN)
        confident_item = primary or margin_primary

        # Empty wins when there is NO confident item on top of it. This covers
        # both a plain dark empty slot (empty=True) AND a glowing-but-empty slot
        # (empty=False because the lavender upper region is not ~EMPTY_REF, yet
        # there is no item and the whole slot is near-uniform). The latter would
        # otherwise fall through to UNKNOWN and churn signatures during glow
        # fade-out / when an item leaves a still-glowing slot.
        if not confident_item and (empty or self._is_uniform(slot_rgb)):
            return SlotResult(state=STATE_EMPTY, name=None, distance=best_dist,
                              margin=margin, signature=None, page=page,
                              row=row, col=col)

        if confident_item:
            return SlotResult(state=STATE_ITEM, name=best_name,
                              distance=best_dist, margin=margin,
                              signature=None, page=page, row=row, col=col)

        # Occupied but nothing confident -> unknown, with a signature.
        return SlotResult(state=STATE_UNKNOWN, name=None, distance=best_dist,
                          margin=margin, signature=self._signature(slot_rgb),
                          page=page, row=row, col=col)

    # -- internals --------------------------------------------------------

    def _distances_all(self, slot, shift_radius=SHIFT_RADIUS):
        """Vectorised best (min) masked MAD per reference over the shift search.

        For each integer shift ``dy,dx in [-S..S]^2`` it shifts the CAPTURED
        slot (edge-replicated), computes
        ``sum(mask * |slot_shifted - ref|) / (mask_sum*3)`` for ALL references at
        once, and keeps the elementwise minimum over shifts. Returns ``(N,)``
        float32 (per-channel mean in 0..255 units). Numerically identical to a
        per-reference loop. ``shift_radius == 0`` evaluates the single shift.
        """
        best = np.full(len(self._refs), _INF, dtype=np.float32)
        for dy in range(-shift_radius, shift_radius + 1):
            for dx in range(-shift_radius, shift_radius + 1):
                shifted = _shift_edge(slot, dy, dx)
                diff = np.abs(shifted[None, ...] - self._ref_rgb) * self._mask
                dist = diff.sum(axis=(1, 2, 3)) / self._mask_sum3
                best = np.minimum(best, dist)
        return best

    def _signature(self, slot_rgb):
        """Signature for an unknown slot using a generic upper-opaque mask.

        Unknown items have no stored alpha, so we weight every upper-region
        pixel equally (mask of ones) -- the descriptor is still deterministic
        and stable for the SAME unknown across scans.
        """
        if np is None or not _is_slot(slot_rgb):
            return None
        mask = np.ones((SLOT_PX, SLOT_PX), dtype=np.float32)
        return signature_of(np.asarray(slot_rgb, dtype=np.float32), mask)

    def _is_uniform(self, slot_rgb):
        """True iff the slot is near-uniform (tiny per-channel std).

        A glowing-but-empty slot is a flat lavender field; a real item (even on
        a glow background) has a high-contrast silhouette. Used by the
        glow-aware EMPTY fallback in :meth:`best_slot_result`.
        """
        if np is None or not _is_slot(slot_rgb):
            return False
        arr = np.asarray(slot_rgb, dtype=np.float32)
        return float(arr.reshape(-1, 3).std(axis=0).max()) <= EMPTY_FALLBACK_STD


# -- module-level numeric helpers (numpy-only; importable, tested via DB) ---

def _is_slot(slot_rgb):
    """True iff ``slot_rgb`` is an ``(SLOT_PX, SLOT_PX, 3)`` array."""
    if np is None or slot_rgb is None:
        return False
    arr = np.asarray(slot_rgb)
    return arr.ndim == 3 and arr.shape == (SLOT_PX, SLOT_PX, 3)


def _block_mean(arr, factor):
    """Block-mean-pool the last two spatial axes of ``arr`` by ``factor``.

    ``arr`` is ``(N, H, W)`` or ``(N, H, W, C)`` with ``H``/``W`` divisible by
    ``factor``. Returns ``(N, H//f, W//f[, C])`` -- a cheap area downscale used
    to build the coarse alignment references and slots (same pooling on both
    sides, so the masked MAD stays comparable to the full-res score).
    """
    n, h, w = arr.shape[0], arr.shape[1], arr.shape[2]
    hh, ww = h // factor, w // factor
    if arr.ndim == 4:
        c = arr.shape[3]
        r = arr.reshape(n, hh, factor, ww, factor, c)
        return r.mean(axis=(2, 4))
    r = arr.reshape(n, hh, factor, ww, factor)
    return r.mean(axis=(2, 4))


def downsample_slot(slot_rgb, factor=ALIGN_DOWNSCALE):
    """Block-mean-pool one ``(32, 32, 3)`` slot by ``factor`` and flatten it.

    Returns the 1-D float32 vector :meth:`ItemDB.alignment_distances` expects,
    or ``None`` if numpy is missing / the slot is malformed.
    """
    if np is None or slot_rgb is None:
        return None
    arr = np.asarray(slot_rgb, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[2] != 3:
        return None
    h, w = arr.shape[0], arr.shape[1]
    hh, ww = h // factor, w // factor
    pooled = arr[:hh * factor, :ww * factor, :].reshape(
        hh, factor, ww, factor, 3).mean(axis=(1, 3))
    return pooled.reshape(-1)


def _shift_edge(img, dy, dx):
    """Shift a 2-D-ish image by ``(dy, dx)`` with edge replication.

    Positive ``dy`` moves content DOWN, positive ``dx`` moves it RIGHT. Vacated
    border rows/cols are filled by replicating the edge (np.roll + edge fill),
    which keeps the silhouette intact at the borders. ``(0, 0)`` returns the
    input unchanged.
    """
    if dy == 0 and dx == 0:
        return img
    out = np.roll(img, shift=(dy, dx), axis=(0, 1))
    # Replace wrapped-around borders with the nearest valid edge.
    if dy > 0:
        out[:dy, :] = out[dy:dy + 1, :]
    elif dy < 0:
        out[dy:, :] = out[dy - 1:dy, :]
    if dx > 0:
        out[:, :dx] = out[:, dx:dx + 1]
    elif dx < 0:
        out[:, dx:] = out[:, dx - 1:dx]
    return out
