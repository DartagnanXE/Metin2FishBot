"""Hover-clear cursor sweep -- the PURE part (no win32 / input).

WHY a hover sweep: a freshly-caught item GLOWS (its slot background is recoloured
lavender) until the mouse hovers it; hovering every slot of the open page clears
the glow, leaving the ~100%-recognised no-glow state. So before classifying a
page the scanner sweeps the cursor over all 45 slot centres (see
:mod:`inventory.scanner` / :mod:`interface.inventory_runner`).

This module is the deterministic, fully unit-testable core: it turns a locked
:class:`~inventory.grid.GridLattice` into the exact ordered list of slot-centre
points the cursor should visit, and offers the pure screen-mapping transform.
The live wrapper in :mod:`interface.inventory_runner` feeds :func:`slot_centres`
/ :func:`to_screen` straight to ``pydirectinput.moveTo`` -- so the ONLY non-pure
part (the actual cursor move) lives there, and the geometry stays headless.

Hover order is BOUSTROPHEDON (serpentine) row-major: row 0 left->right, row 1
right->left, row 2 left->right, ... This visits all 45 centres with 44 short
single-step hops and NO long carriage-return jumps back to the left edge, which
keeps the real sweep faster and less jittery than naive row-major.

Pure Python only (no numpy/cv2/PIL) so it is ALWAYS importable + testable
headless, matching :mod:`inventory.constants` / :mod:`geometry`.
"""

from typing import List, Tuple

from .constants import COLS, ROWS, SLOT_PX


# Slot CENTRE offset from the slot-box top-left corner. GridLattice.slot_box
# returns (ox+col*px, oy+row*py, 32, 32); the centre is half a slot in on each
# axis. 16 == SLOT_PX // 2.
_HALF = SLOT_PX // 2


def slot_centres(lattice) -> List[Tuple[int, int]]:
    """Ordered slot-box centres for the hover sweep (serpentine row-major).

    Returns the 45 ``(x, y)`` integer centre points of ``lattice`` (a
    :class:`~inventory.grid.GridLattice`) in BOUSTROPHEDON order: even rows
    left->right, odd rows right->left. The centre of slot ``(row, col)`` is
    ``lattice.slot_box(row, col)`` shifted by ``(+SLOT_PX//2, +SLOT_PX//2)``.

    Deterministic + pure -> the first centre for origin ``(2, 2)`` pitch
    ``(32, 32)`` is ``(18, 18)`` and the sequence serpentines from there.

    :param lattice: a locked grid lattice exposing ``slot_box(row, col)``.
    :return: ``[(x, y), ...]`` of length ``ROWS * COLS`` (45).
    """
    points: List[Tuple[int, int]] = []
    for row in range(ROWS):
        cols = range(COLS) if row % 2 == 0 else range(COLS - 1, -1, -1)
        for col in cols:
            box = lattice.slot_box(row, col)
            points.append((int(box[0]) + _HALF, int(box[1]) + _HALF))
    return points


def park_point(lattice) -> Tuple[int, int]:
    """An engine-space point clear of ALL slots, to park the cursor after a sweep.

    After the serpentine sweep the cursor rests on the LAST visited centre (a real
    slot), and the de-glowed re-capture happens with it parked there. If the OS
    includes the hardware cursor (or a tooltip it triggers) in the screenshot, that
    one slot could be occluded on the classified frame. Parking the cursor below
    the grid (one full pitch under the bottom-left slot's box) before the
    re-capture keeps it off every slot. Pure + deterministic so it is testable; the
    live wrapper maps it via :func:`to_screen` and moves there once.

    :param lattice: the locked grid lattice exposing ``slot_box(row, col)``.
    :return: an ``(x, y)`` engine-space point one pitch below the bottom row.
    """
    box = lattice.slot_box(ROWS - 1, 0)
    pitch_y = int(lattice.pitch[1])
    # Bottom-left slot's lower edge, then a full pitch further down -> clear of the
    # grid yet still near it (a small, safe MOVE, never a click).
    return (int(box[0]) + _HALF, int(box[1]) + SLOT_PX + pitch_y)


def to_screen(centres, offset) -> List[Tuple[int, int]]:
    """Shift engine-space centre points into absolute SCREEN coordinates.

    ``screen = engine + offset`` per the verified capture convention
    (``screen_x = engine_x + wincap.offset_x``; equivalently
    ``wincap.get_screen_position``). Pure so the screen mapping is testable
    without a real window; the live wrapper passes
    ``(wincap.offset_x, wincap.offset_y)``.

    :param centres: ``[(x, y), ...]`` engine-space points (e.g. from
        :func:`slot_centres`).
    :param offset: ``(offset_x, offset_y)`` to add to every point.
    :return: a NEW list of shifted ``(x, y)`` integer points (input unchanged).
    """
    ox, oy = int(offset[0]), int(offset[1])
    return [(int(x) + ox, int(y) + oy) for (x, y) in centres]
