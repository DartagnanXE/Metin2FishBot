"""Shared result DTOs for the inventory engine.

Kept tiny and import-light (pure stdlib) so they can be imported by both
:mod:`inventory.itemdb` and :mod:`inventory.scanner` without a cycle, and so
they stay testable headless. Frozen dataclasses per the repo's immutability
style (new objects, never mutate).
"""

from dataclasses import dataclass
from typing import Optional, Tuple, Dict

from .constants import KEY_ITEMS


# Slot states.
STATE_EMPTY = 'empty'
STATE_ITEM = 'item'
STATE_UNKNOWN = 'unknown'


@dataclass(frozen=True)
class SlotResult:
    """Recognition result for a single inventory slot (immutable).

    :ivar state: one of ``'empty'`` / ``'item'`` / ``'unknown'``.
    :ivar name: matched item name (only for ``'item'``; else ``None``).
    :ivar distance: best masked match distance (0..255; ``inf`` if no DB).
    :ivar margin: 2nd-best distance minus best distance (confidence; 0 if <2
        references).
    :ivar signature: compact descriptor for tracking an unknown item across
        scans (only for ``'unknown'``; else ``None``).
    :ivar page: page label this slot belongs to (``'I'``..``'IV'`` or ``None``).
    :ivar row: slot row (0..ROWS-1).
    :ivar col: slot column (0..COLS-1).
    """

    state: str
    name: Optional[str]
    distance: float
    margin: float
    signature: Optional[Tuple]
    page: Optional[str]
    row: int
    col: int


@dataclass(frozen=True)
class InventoryMap:
    """Immutable snapshot of a full I->IV inventory scan.

    :ivar pages: mapping page label -> tuple of 45 :class:`SlotResult`
        (row-major). A page absent from the scan is simply not a key.
    """

    pages: Dict[str, Tuple[SlotResult, ...]]

    def items(self):
        """All slots classified as a known item, across every page."""
        return [r for r in self._all() if r.state == STATE_ITEM]

    def find(self, name):
        """All item slots whose name equals ``name`` (across pages)."""
        return [r for r in self._all()
                if r.state == STATE_ITEM and r.name == name]

    def count(self, name):
        """Number of slots holding the item ``name``."""
        return len(self.find(name))

    def unknowns(self):
        """All occupied-but-unrecognised slots."""
        return [r for r in self._all() if r.state == STATE_UNKNOWN]

    def tracked(self, names=KEY_ITEMS):
        """Map each tracked item name that has >=1 hit -> its slots.

        Only names actually present in the scan appear as keys (an item with no
        slot is simply omitted), so ``tracked()`` is directly iterable for a
        "found at" report. Pure Python (built on :meth:`find`); the default set
        is the KEY_ITEMS the bot remembers until a future handler acts on them.

        :param names: iterable of item names to look up (default KEY_ITEMS).
        :return: ``{name: [SlotResult, ...]}`` for names with at least one hit.
        """
        result = {}
        for name in names:
            hits = self.find(name)
            if hits:
                result[name] = hits
        return result

    def locations(self, name):
        """``[(page, row, col), ...]`` for every slot holding ``name``.

        Page order then row-major (mirrors :meth:`find`). The seam a future
        move/use/delete handler consumes to act on an item by coordinate.
        """
        return [(r.page, r.row, r.col) for r in self.find(name)]

    def _all(self):
        """Flatten all page result tuples in page order, then row-major."""
        out = []
        for page in self.pages:
            out.extend(self.pages[page])
        return out
