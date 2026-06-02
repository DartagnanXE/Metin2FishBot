"""Shared synthetic-slot/page factory for the inventory engine tests.

Builds slots the way the real game shows them so the matcher/scanner tests
exercise the full pipeline (BGR uint8 in, like a captured frame):

* composite a reference icon over the DARK empty background OR the lavender
  GLOW background,
* optionally stamp a fake white stack-number block into the number band
  (rows 14..24),
* optionally apply a small integer shift + gaussian noise.

numpy/PIL are soft-imported; helpers return ``None`` when numpy is missing so
the test files can ``skipUnless`` cleanly in a lean environment.
"""

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

from inventory.constants import (
    SLOT_PX,
    COLS,
    ROWS,
    EMPTY_REF,
    GLOW_REF,
)
from inventory.reference import composite_over


def _rgb_to_bgr(rgb):
    """RGB float/array -> contiguous BGR uint8 (what a capture would yield)."""
    arr = np.clip(np.asarray(rgb, dtype=np.float32), 0, 255)
    return np.ascontiguousarray(arr[:, :, ::-1].astype(np.uint8))


def synth_slot(ref, glow=False, number=False, shift=(0, 0), noise=0.0,
               seed=0):
    """Synthesize a 32x32 BGR uint8 slot from an :class:`ItemReference`.

    :param ref: the source reference (provides the RGB composite + mask).
    :param glow: composite the icon over GLOW instead of EMPTY background.
    :param number: stamp a fake white digit block into rows 14..24.
    :param shift: integer ``(dy, dx)`` roll applied to the whole slot.
    :param noise: stddev of additive gaussian noise (0 = none).
    :param seed: RNG seed for reproducible noise.
    :return: ``(32, 32, 3)`` BGR uint8, or ``None`` if numpy missing.
    """
    if np is None or ref is None:
        return None
    bg = GLOW_REF if glow else EMPTY_REF
    # Re-composite the EXACT icon over the chosen background from the icon's true
    # alpha: rgb = icon_rgb*a + bg*(1-a). ref.ref_rgb already equals
    # icon_rgb*a + EMPTY*(1-a), so swapping the background is just
    #   rgb = ref.ref_rgb + (bg - EMPTY) * (1 - a)
    # using the FULL alpha (ref.alpha; number band NOT zeroed). This preserves
    # opaque dark icon pixels that happen to equal EMPTY_REF -- they keep their
    # icon colour instead of being repainted as background (the old colour-keyed
    # reconstruction wrongly lavender-washed ~6% of opaque pixels under glow).
    bg_arr = np.array(bg, dtype=np.float32).reshape(1, 1, 3)
    empty_arr = np.array(EMPTY_REF, dtype=np.float32).reshape(1, 1, 3)
    one_minus_a = (1.0 - ref.alpha)[:, :, None]
    rgb = (ref.ref_rgb + (bg_arr - empty_arr) * one_minus_a).astype(np.float32)

    if number:
        rgb[14:25, 9:23, :] = 245.0  # fake white digits in the number band

    if shift != (0, 0):
        rgb = np.roll(rgb, shift=shift, axis=(0, 1))

    if noise and noise > 0.0:
        rng = np.random.RandomState(seed)
        rgb = rgb + rng.normal(0.0, noise, rgb.shape).astype(np.float32)

    return _rgb_to_bgr(rgb)


def empty_slot(glow=False):
    """A 32x32 BGR uint8 empty slot (dark, or uniform glow)."""
    if np is None:
        return None
    bg = GLOW_REF if glow else EMPTY_REF
    rgb = np.tile(np.array(bg, dtype=np.float32), (SLOT_PX, SLOT_PX, 1))
    return _rgb_to_bgr(rgb)


def synth_page(layout, origin=(2, 2), pitch=(SLOT_PX, SLOT_PX),
               canvas_pad=4):
    """Assemble a full BGR page image from a 45-entry ``layout``.

    :param layout: list of 45 cell specs in row-major order. Each cell is
        either ``None`` (empty dark slot) or a dict
        ``{'ref':, 'glow':, 'number':, 'shift':, 'noise':}`` passed to
        :func:`synth_slot` (only ``ref`` is required).
    :param origin: ``(x, y)`` of the top-left slot inside the canvas.
    :param pitch: ``(px, py)`` slot pitch.
    :param canvas_pad: extra pixels of dark border around the grid.
    :return: ``(H, W, 3)`` BGR uint8 page, plus the ``(origin, pitch)`` used.
    """
    if np is None:
        return None, None
    ox, oy = origin
    px, py = pitch
    width = ox + (COLS - 1) * px + SLOT_PX + canvas_pad
    height = oy + (ROWS - 1) * py + SLOT_PX + canvas_pad
    page = np.tile(np.array(EMPTY_REF, dtype=np.uint8)[::-1],
                   (height, width, 1)).copy()  # dark BGR canvas
    idx = 0
    for row in range(ROWS):
        for col in range(COLS):
            spec = layout[idx] if idx < len(layout) else None
            idx += 1
            if spec is None:
                cell = empty_slot(glow=False)
            elif isinstance(spec, dict) and spec.get('ref') is None:
                cell = empty_slot(glow=bool(spec.get('glow')))
            else:
                cell = synth_slot(
                    spec['ref'],
                    glow=bool(spec.get('glow')),
                    number=bool(spec.get('number')),
                    shift=spec.get('shift', (0, 0)),
                    noise=float(spec.get('noise', 0.0)),
                    seed=int(spec.get('seed', 0)),
                )
            x = ox + col * px
            y = oy + row * py
            page[y:y + SLOT_PX, x:x + SLOT_PX, :] = cell
    return page, (origin, pitch)
