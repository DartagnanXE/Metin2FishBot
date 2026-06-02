"""Inventory item-recognition engine.

A self-contained, HEADLESS-testable package that recognises which item sits in
each of the 4 pages x 45 slots of the Metin2 inventory. Robust to the lavender
empty-slot GLOW, stack-number digits, per-session grid drift, and unknown
items -- by masked matching (only the item silhouette, number band excluded)
over a small shift search, plus a per-scan auto-grid-alignment fit.

Public surface::

    from inventory import (
        ItemDB, ItemReference, SlotResult, InventoryMap, GridLattice,
        scan_inventory, recognize_page,
        diff_maps, InventoryDiff,             # change-aware diff
        format_full, format_page_grid, format_tracked,  # Console readout
        slot_centres, to_screen,              # hover-sweep geometry
    )

All recognition takes an already-captured image, so it runs with no game / GUI;
production wires ``scan_inventory``'s two callbacks into ``WindowCapture`` +
``pydirectinput`` (see :mod:`interface.inventory_runner`).
"""

from .itemdb import ItemDB
from .reference import ItemReference
from .types import SlotResult, InventoryMap
from .grid import GridLattice
from .scanner import scan_inventory, recognize_page, classify_slot
from .diff import diff_maps, InventoryDiff, Change
from .report import format_full, format_page_grid, format_tracked, short_token
from .hover import slot_centres, to_screen

__all__ = [
    'ItemDB',
    'ItemReference',
    'SlotResult',
    'InventoryMap',
    'GridLattice',
    'scan_inventory',
    'recognize_page',
    'classify_slot',
    # change-aware diff
    'diff_maps',
    'InventoryDiff',
    'Change',
    # Console readout formatters
    'format_full',
    'format_page_grid',
    'format_tracked',
    'short_token',
    # hover-sweep geometry
    'slot_centres',
    'to_screen',
]
