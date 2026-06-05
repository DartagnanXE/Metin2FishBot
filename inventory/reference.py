"""Turn a raw RGBA icon into a glow-/number-proof :class:`ItemReference`.

The PROVEN recognition recipe (do not re-derive):

1. Composite the icon over the DARK empty-slot background ``EMPTY_REF`` using
   the icon's alpha -> ``ref_rgb`` (float32, RGB, 32x32). We composite over the
   *empty* background (not glow) because the matcher only ever scores masked
   (opaque) pixels, and over those the background contribution is multiplied by
   ``1 - alpha`` ~ 0, so the exact background colour is irrelevant there.
2. ``full_mask`` = the icon's alpha (0..1) ERODED to SOLIDLY-opaque pixels
   (alpha >= ``ALPHA_OPAQUE_MIN``): the whole item silhouette, glow-proof
   (partial-alpha edges, where glow bleeds, are dropped). ``weight_mask`` (the
   BAND mask) is ``full_mask`` with the stack-number rows (``NUMBER_BAND_ROWS``,
   14..24) additionally ZEROED, so it ALSO ignores the stack digits.

ADAPTIVE MASK (per slot, chosen at classify time): a slot that carries a printed
stack number is matched with the BAND mask (digits excluded -- today's
behaviour, unchanged); a slot with NO number is matched with the FULL mask,
which scores the extra central rows too and so widens the confidence margin (the
number band of a number-free item is just more icon/background that legitimately
matches the reference). Every reference therefore carries BOTH masks; the matcher
picks per slot from a cheap near-white-pixel number detector
(:func:`slot_has_number`). The numbered case stays bit-identical to the historic
single-mask path.

numpy is SOFT-imported (mirrors :mod:`detection`); without it the helpers
return ``None`` and the DB degrades rather than raising. Tests force the
fallback with ``reference.np = None``.
"""

from dataclasses import dataclass

from .constants import (
    EMPTY_REF,
    NUMBER_BAND_ROWS,
    UPPER_REGION_END,
    ALPHA_OPAQUE_MIN,
    NUMBER_DETECT_ROWS,
    NUMBER_DETECT_WHITE,
    NUMBER_DETECT_MIN_PX,
)

try:  # pragma: no cover - exercised on machines with numpy
    import numpy as np
except Exception:  # pragma: no cover
    np = None


# Downscale grid edge for the unknown-item signature (4x4 luminance grid over
# the number-free upper region).
_SIG_GRID = 4
# Quantisation step (0..255 -> coarse buckets) so tiny noise does not change the
# signature: two captures of the SAME unknown item hash to the same tuple.
_SIG_QUANT = 16


@dataclass(frozen=True)
class ItemReference:
    """An immutable recognition template for one item.

    :ivar name: item name (icon basename).
    :ivar ref_rgb: ``(32, 32, 3)`` float32 RGB icon composited over EMPTY_REF.
    :ivar weight_mask: ``(32, 32)`` float32 the BAND mask -- solidly-opaque alpha
        (0..1) with the number band (``NUMBER_BAND_ROWS``) zeroed. The per-pixel
        match weight for a slot that CARRIES a stack number (digits excluded).
    :ivar mask_sum: ``weight_mask.sum()`` (the BAND distance normaliser).
    :ivar full_mask: ``(32, 32)`` float32 the FULL mask -- the SAME solidly-opaque
        alpha but WITHOUT the number band zeroed (the whole item silhouette). The
        per-pixel match weight for a slot with NO stack number (scores the extra
        central rows too -> a wider confidence margin).
    :ivar full_mask_sum: ``full_mask.sum()`` (the FULL distance normaliser).
    :ivar alpha: ``(32, 32)`` float32 the icon's FULL alpha in 0..1 (un-eroded,
        number band NOT zeroed). Distinct from both masks; the matcher never uses
        it, but it lets a faithful synthetic test re-composite the exact icon over
        any background (``icon*alpha + bg*(1-alpha)``) without colour-keying.
    """

    name: str
    ref_rgb: 'np.ndarray'
    weight_mask: 'np.ndarray'
    mask_sum: float
    full_mask: 'np.ndarray'
    full_mask_sum: float
    alpha: 'np.ndarray'


def composite_over(rgba, bg=EMPTY_REF):
    """Alpha-composite an ``(H, W, 4)`` RGBA icon over a flat ``bg`` colour.

    Returns ``(H, W, 3)`` float32 RGB: ``icon_rgb*a + bg*(1-a)`` with ``a`` the
    normalised alpha. ``None`` if numpy is missing or input is not RGBA.
    """
    if np is None or rgba is None or getattr(rgba, 'ndim', 0) != 3 \
            or rgba.shape[2] != 4:
        return None
    arr = rgba.astype(np.float32)
    rgb = arr[:, :, :3]
    alpha = (arr[:, :, 3:4]) / 255.0
    background = np.array(bg, dtype=np.float32).reshape(1, 1, 3)
    return rgb * alpha + background * (1.0 - alpha)


def number_band_zeroed_mask(alpha):
    """Build the weight mask from an alpha channel with rows 14..24 zeroed.

    :param alpha: ``(H, W)`` or ``(H, W, 1)`` uint8/float alpha (0..255).
    :return: ``(H, W)`` float32 in 0..1 with ``NUMBER_BAND_ROWS`` set to 0, or
        ``None`` if numpy is missing / input malformed.
    """
    if np is None or alpha is None:
        return None
    a = np.asarray(alpha, dtype=np.float32)
    if a.ndim == 3:
        a = a[:, :, 0]
    if a.ndim != 2:
        return None
    mask = a / 255.0
    mask = mask.copy()  # immutable input -> never mutate the caller's array
    rows = [r for r in NUMBER_BAND_ROWS if 0 <= r < mask.shape[0]]
    if rows:
        mask[rows[0]:rows[-1] + 1, :] = 0.0
    return mask


def _near_white_count_rows(slot_rgb):
    """Count near-white pixels in the digit rows of one ``(H, W, 3)`` RGB slot.

    A pixel is "near-white" when ``min(R, G, B) > NUMBER_DETECT_WHITE`` (a digit
    stroke; any coloured icon pixel has at least one low channel). Counts over
    ``NUMBER_DETECT_ROWS`` (the lower-half digit band). Returns an int (0 if
    numpy is missing / the slot is malformed -> treated as "no number").
    """
    if np is None or slot_rgb is None:
        return 0
    arr = np.asarray(slot_rgb, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[2] != 3:
        return 0
    rows = [r for r in NUMBER_DETECT_ROWS if 0 <= r < arr.shape[0]]
    if not rows:
        return 0
    band = arr[rows[0]:rows[-1] + 1, :, :]
    mins = band.min(axis=2)
    return int((mins > NUMBER_DETECT_WHITE).sum())


def slot_has_number(slot_rgb):
    """True iff one slot carries a printed stack number (selects BAND vs FULL).

    Cheap per-slot probe: enough near-white pixels in the digit rows
    (:func:`_near_white_count_rows` >= ``NUMBER_DETECT_MIN_PX``). SAFE-by-design
    (see constants): a false positive only forgoes the FULL-mask margin bonus, a
    false negative is practically impossible. Never raises; ``False`` when numpy
    is missing.
    """
    return _near_white_count_rows(slot_rgb) >= NUMBER_DETECT_MIN_PX


def slots_have_numbers(slots_stack):
    """Vectorised :func:`slot_has_number` over an ``(M, H, W, 3)`` slot stack.

    Returns a length-M list of bools (one per slot, in stack order) so the
    page-vectorised matcher can pick the FULL/BAND mask per slot in one shot.
    ``None`` if numpy is missing or the stack shape is wrong (caller then treats
    every slot as numbered = today's BAND behaviour -> safe, no item lost).
    """
    if np is None or slots_stack is None:
        return None
    arr = np.asarray(slots_stack, dtype=np.float32)
    if arr.ndim != 4 or arr.shape[3] != 3:
        return None
    rows = [r for r in NUMBER_DETECT_ROWS if 0 <= r < arr.shape[1]]
    if not rows:
        return [False] * arr.shape[0]
    band = arr[:, rows[0]:rows[-1] + 1, :, :]          # (M, R, W, 3)
    mins = band.min(axis=3)                             # (M, R, W)
    counts = (mins > NUMBER_DETECT_WHITE).sum(axis=(1, 2))
    return [bool(c >= NUMBER_DETECT_MIN_PX) for c in counts]


def build_reference(name, rgba):
    """Build an :class:`ItemReference` from a 32x32 RGBA icon (BOTH masks).

    Composites over EMPTY_REF, then builds the two adaptive masks from the icon's
    alpha ERODED to solidly-opaque pixels (alpha >= ALPHA_OPAQUE_MIN, so glow
    cannot bleed through anti-aliased edges into the match score):

      * ``full_mask`` -- the whole solidly-opaque silhouette (number band KEPT),
        used for a slot WITHOUT a stack number (wider margin).
      * ``weight_mask`` (BAND) -- ``full_mask`` with ``NUMBER_BAND_ROWS`` zeroed,
        used for a slot WITH a stack number (digits excluded -- unchanged
        behaviour).

    The two differ ONLY in the number band (BAND = FULL with those rows zeroed),
    so the numbered-slot match is byte-identical to the historic single-mask
    path. Returns ``None`` (caller skips the icon, logged upstream) if numpy is
    missing, the icon is not RGBA, or the opaque silhouette is empty.
    """
    if np is None or rgba is None or getattr(rgba, 'ndim', 0) != 3 \
            or rgba.shape[2] != 4:
        return None
    ref_rgb = composite_over(rgba, EMPTY_REF)
    if ref_rgb is None:
        return None
    alpha = (rgba[:, :, 3].astype(np.float32)) / 255.0
    # FULL mask: the normalised alpha ERODED to solidly-opaque pixels
    # (alpha >= ALPHA_OPAQUE_MIN; partial-alpha edges are where glow bleeds). The
    # number band is KEPT here -- this is the whole silhouette weight.
    full_mask = np.where(alpha >= ALPHA_OPAQUE_MIN, alpha, 0.0).astype(np.float32)
    full_mask_sum = float(full_mask.sum())
    if full_mask_sum <= 0.0:
        return None
    # BAND mask: the SAME mask with the number-band rows zeroed -- so it differs
    # from FULL ONLY inside NUMBER_BAND_ROWS. This is byte-identical to the
    # historic single mask (number_band_zeroed_mask -> erode), so a numbered slot
    # matches exactly as before.
    weight_mask = full_mask.copy()
    rows = [r for r in NUMBER_BAND_ROWS if 0 <= r < weight_mask.shape[0]]
    if rows:
        weight_mask[rows[0]:rows[-1] + 1, :] = 0.0
    mask_sum = float(weight_mask.sum())
    if mask_sum <= 0.0:
        return None
    return ItemReference(
        name=name,
        ref_rgb=np.ascontiguousarray(ref_rgb, dtype=np.float32),
        weight_mask=np.ascontiguousarray(weight_mask, dtype=np.float32),
        mask_sum=mask_sum,
        full_mask=np.ascontiguousarray(full_mask, dtype=np.float32),
        full_mask_sum=full_mask_sum,
        alpha=np.ascontiguousarray(alpha, dtype=np.float32),
    )


def signature_of(slot_rgb, weight_mask):
    """Compact, glow-/number-robust descriptor of a slot's masked content.

    Deterministic fixed-length tuple used to track an UNKNOWN item across scans
    without a name. Built only from masked pixels of the number-free upper
    region (rows 0..UPPER_REGION_END-1), so glow and stack digits do not affect
    it. Layout: ``(mean_r, mean_g, mean_b, *flattened 4x4 luminance grid)``,
    each value quantised to coarse buckets.

    :param slot_rgb: ``(32, 32, 3)`` float32 RGB slot.
    :param weight_mask: ``(32, 32)`` float32 mask (alpha, number band already
        zeroed). For unknown items the item's own alpha is unavailable, so the
        scanner passes a generic "upper opaque" mask; any mask works.
    :return: a tuple of ints, or ``None`` if numpy missing / shapes wrong.
    """
    if np is None or slot_rgb is None or weight_mask is None:
        return None
    if getattr(slot_rgb, 'ndim', 0) != 3 or slot_rgb.shape[2] != 3:
        return None
    end = min(UPPER_REGION_END, slot_rgb.shape[0])
    upper = slot_rgb[:end, :, :].astype(np.float32)
    wmask = np.asarray(weight_mask, dtype=np.float32)[:end, :]
    total = float(wmask.sum())
    if total <= 0.0:
        return None
    w3 = wmask[:, :, None]
    mean_rgb = (upper * w3).sum(axis=(0, 1)) / total

    # Downscaled masked-luminance grid over the upper region. We pool the upper
    # region into a _SIG_GRID x _SIG_GRID grid; each cell = masked-mean luma.
    luma = (0.299 * upper[:, :, 0] + 0.587 * upper[:, :, 1]
            + 0.114 * upper[:, :, 2])
    grid = _pool_masked(luma, wmask, _SIG_GRID, _SIG_GRID)

    values = list(mean_rgb) + list(grid.reshape(-1))
    return tuple(int(round(v / _SIG_QUANT)) for v in values)


def _pool_masked(values, mask, rows_out, cols_out):
    """Average-pool ``values`` weighted by ``mask`` into a small grid.

    Returns a ``(rows_out, cols_out)`` float32 array of masked means (0 where a
    cell has no mass). Deterministic, numpy-only.
    """
    h, w = values.shape
    out = np.zeros((rows_out, cols_out), dtype=np.float32)
    for ri in range(rows_out):
        y0 = (ri * h) // rows_out
        y1 = max(y0 + 1, ((ri + 1) * h) // rows_out)
        for ci in range(cols_out):
            x0 = (ci * w) // cols_out
            x1 = max(x0 + 1, ((ci + 1) * w) // cols_out)
            cell_m = mask[y0:y1, x0:x1]
            denom = float(cell_m.sum())
            if denom > 0.0:
                out[ri, ci] = float((values[y0:y1, x0:x1] * cell_m).sum()
                                    / denom)
    return out
