"""Turn a raw RGBA icon into a glow-/number-proof :class:`ItemReference`.

The PROVEN recognition recipe (do not re-derive):

1. Composite the icon over the DARK empty-slot background ``EMPTY_REF`` using
   the icon's alpha -> ``ref_rgb`` (float32, RGB, 32x32). We composite over the
   *empty* background (not glow) because the matcher only ever scores masked
   (opaque) pixels, and over those the background contribution is multiplied by
   ``1 - alpha`` ~ 0, so the exact background colour is irrelevant there.
2. ``weight_mask`` = the icon's alpha (0..1) with the stack-number rows
   (``NUMBER_BAND_ROWS``, 14..24) ZEROED. So the mask is "the item silhouette
   minus the number band": comparing only mask>0 pixels ignores the glowing /
   empty background (glow-proof) AND the stack digits (number-proof).

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
    :ivar weight_mask: ``(32, 32)`` float32 alpha in 0..1 with the number band
        zeroed -- the per-pixel match weight.
    :ivar mask_sum: ``weight_mask.sum()`` (the distance normaliser).
    :ivar alpha: ``(32, 32)`` float32 the icon's FULL alpha in 0..1 (number band
        NOT zeroed). Distinct from ``weight_mask``; the matcher never uses it,
        but it lets a faithful synthetic test re-composite the exact icon over
        any background (``icon*alpha + bg*(1-alpha)``) without colour-keying.
    """

    name: str
    ref_rgb: 'np.ndarray'
    weight_mask: 'np.ndarray'
    mask_sum: float
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


def build_reference(name, rgba):
    """Build an :class:`ItemReference` from a 32x32 RGBA icon.

    Composites over EMPTY_REF and builds the weight mask = the number-band-
    zeroed alpha, ERODED to solidly-opaque pixels (alpha >= ALPHA_OPAQUE_MIN) so
    glow cannot bleed through anti-aliased edges into the match score. Returns
    ``None`` (caller skips the icon, logged upstream) if numpy is missing, the
    icon is not RGBA, or the opaque silhouette is empty (mask_sum == 0).
    """
    if np is None or rgba is None or getattr(rgba, 'ndim', 0) != 3 \
            or rgba.shape[2] != 4:
        return None
    ref_rgb = composite_over(rgba, EMPTY_REF)
    weight_mask = number_band_zeroed_mask(rgba[:, :, 3])
    if ref_rgb is None or weight_mask is None:
        return None
    alpha = (rgba[:, :, 3].astype(np.float32)) / 255.0
    # Keep only solidly-opaque pixels; partial-alpha edges are where glow bleeds.
    weight_mask = np.where(alpha >= ALPHA_OPAQUE_MIN, weight_mask, 0.0)
    weight_mask = weight_mask.astype(np.float32)
    mask_sum = float(weight_mask.sum())
    if mask_sum <= 0.0:
        return None
    return ItemReference(
        name=name,
        ref_rgb=np.ascontiguousarray(ref_rgb, dtype=np.float32),
        weight_mask=np.ascontiguousarray(weight_mask, dtype=np.float32),
        mask_sum=mask_sum,
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
