"""Change-aware diff between two :class:`~inventory.types.InventoryMap`s.

PURE (stdlib only): no numpy / PIL / win32, so it is fully unit-testable on
hand-built maps with no game. It compares a PREVIOUS inventory snapshot against
a NEW one and classifies every slot that differs, so a re-scan only has to ACT
on what actually changed -- unchanged slots (including long-standing UNKNOWNs)
are silent and never spam the log.

WHY a fingerprint (not the name): a slot's occupant must be tracked even when it
is UNKNOWN (no name). The :func:`_fingerprint` collapses a
:class:`~inventory.types.SlotResult` to a small hashable identity that works for
all three states:

  * ``'item'``    -> ``('item', name)``      (a known item is identified by name)
  * ``'unknown'`` -> ``('unknown', signature)`` (the stable per-unknown
    descriptor proven across scans by
    ``test_inventory_scanner.TestSignatureStability``)
  * ``'empty'``   -> ``('empty', None)``

Classification per slot key ``(page, row, col)`` present in EITHER map:

  * prev empty/absent, new occupied            -> APPEARED
  * both occupied, fingerprint differs          -> CHANGED
  * prev occupied, new empty/absent             -> VANISHED
  * fingerprint unchanged                        -> SILENT (in no list)

``new_unknown`` is the subset of ``appeared + changed`` whose NEW occupant is
UNKNOWN -- i.e. an occupant that newly appeared (or changed identity) and is not
recognised. That is the ONLY set the runner warns about (exactly once each).

``previous_map=None`` (first scan of a session) => every occupied slot is
APPEARED and ``new_unknown`` still lists the newly-seen unknowns; the runner
SUPPRESSES the warning on that first scan (there was no prior baseline, so
nothing is genuinely "newly appeared" to the user). This module reports the
facts; the suppression policy lives in the runner.

This module is the seam a future auto-handler also consumes (act on
``appeared`` / ``changed`` key items by coordinate).
"""

from dataclasses import dataclass
from typing import Optional, Tuple

from .types import (
    SlotResult,
    STATE_ITEM,
    STATE_UNKNOWN,
)


@dataclass(frozen=True)
class Change:
    """One per-slot change between two scans (immutable).

    :ivar page: page label of the slot (``'I'``..``'IV'``).
    :ivar row: slot row (0..ROWS-1).
    :ivar col: slot column (0..COLS-1).
    :ivar prev: the previous :class:`SlotResult` at this slot (``None`` if the
        slot was absent from the previous map).
    :ivar new: the new :class:`SlotResult` at this slot (``None`` if the slot is
        absent from the new map, i.e. a VANISHED slot).
    """

    page: str
    row: int
    col: int
    prev: Optional[SlotResult]
    new: Optional[SlotResult]


@dataclass(frozen=True)
class InventoryDiff:
    """The full classified delta between a previous and a new scan (immutable).

    Each field is a tuple of :class:`Change` (page-then-row-major order). A slot
    whose fingerprint is unchanged appears in NONE of them.

    :ivar appeared: slots that went empty/absent -> occupied.
    :ivar changed: slots occupied in both scans but with a different occupant
        (different item name, or a different unknown signature).
    :ivar vanished: slots that went occupied -> empty/absent.
    :ivar new_unknown: the subset of ``appeared + changed`` whose NEW occupant is
        UNKNOWN (newly-appeared-or-changed-to unrecognised). The only set the
        runner warns about.
    """

    appeared: Tuple[Change, ...]
    changed: Tuple[Change, ...]
    vanished: Tuple[Change, ...]
    new_unknown: Tuple[Change, ...]


def _occupied(state) -> bool:
    """True iff a slot state counts as holding something (item or unknown)."""
    return state in (STATE_ITEM, STATE_UNKNOWN)


def _fingerprint(result):
    """Hashable identity of a slot occupant; ``None`` for empty/absent.

    ``('item', name)`` / ``('unknown', signature)`` / ``('empty', None)``. An
    absent slot (``result is None``) is treated like empty. Two scans of the
    SAME occupant produce the SAME fingerprint (a known item by name, an unknown
    by its stable signature), so an unchanged slot is detected as unchanged.
    """
    if result is None:
        return ('empty', None)
    if result.state == STATE_ITEM:
        return ('item', result.name)
    if result.state == STATE_UNKNOWN:
        return ('unknown', result.signature)
    return ('empty', None)


def _slot_index(inv_map):
    """``{(page, row, col): SlotResult}`` over every slot of a map.

    ``inv_map`` may be ``None`` (treated as an empty inventory) so the very first
    scan of a session diffs cleanly against "nothing".
    """
    index = {}
    if inv_map is None:
        return index
    for page, results in inv_map.pages.items():
        for r in results:
            index[(page, r.row, r.col)] = r
    return index


def diff_maps(previous_map, new_map):
    """Classify the per-slot delta from ``previous_map`` to ``new_map``.

    :param previous_map: the prior :class:`InventoryMap`, or ``None`` for the
        first scan of a session (then every occupied slot is APPEARED).
    :param new_map: the freshly scanned :class:`InventoryMap`.
    :return: an :class:`InventoryDiff`. Slots whose fingerprint is unchanged are
        in no list (the silence rule). ``new_unknown`` lists the appeared/changed
        slots whose new occupant is UNKNOWN.

    Order: keys are visited page-then-row-major (the union of both maps' slot
    keys, sorted by the new map's page order first for stability), so the result
    tuples are deterministic.
    """
    prev_index = _slot_index(previous_map)
    new_index = _slot_index(new_map)

    appeared = []
    changed = []
    vanished = []
    new_unknown = []

    for key in _ordered_keys(previous_map, new_map, prev_index, new_index):
        page, row, col = key
        prev = prev_index.get(key)
        new = new_index.get(key)
        prev_occ = _occupied(prev.state) if prev is not None else False
        new_occ = _occupied(new.state) if new is not None else False

        if not prev_occ and new_occ:
            ch = Change(page=page, row=row, col=col, prev=prev, new=new)
            appeared.append(ch)
            if new.state == STATE_UNKNOWN:
                new_unknown.append(ch)
        elif prev_occ and not new_occ:
            vanished.append(Change(page=page, row=row, col=col,
                                   prev=prev, new=new))
        elif prev_occ and new_occ:
            if _fingerprint(prev) != _fingerprint(new):
                ch = Change(page=page, row=row, col=col, prev=prev, new=new)
                changed.append(ch)
                if new.state == STATE_UNKNOWN:
                    new_unknown.append(ch)
        # both empty/absent -> nothing; same-fingerprint occupied -> silent.

    return InventoryDiff(
        appeared=tuple(appeared),
        changed=tuple(changed),
        vanished=tuple(vanished),
        new_unknown=tuple(new_unknown),
    )


def _ordered_keys(previous_map, new_map, prev_index, new_index):
    """Deterministic page-then-row-major union of both maps' slot keys.

    Pages are ordered by their appearance in the NEW map first, then any pages
    only in the previous map, so VANISHED-page slots still surface in a stable
    spot. Within a page, row-major.
    """
    page_order = []
    seen = set()
    for src in (new_map, previous_map):
        if src is None:
            continue
        for page in src.pages:
            if page not in seen:
                seen.add(page)
                page_order.append(page)

    all_keys = set(prev_index) | set(new_index)
    page_rank = {p: i for i, p in enumerate(page_order)}
    return sorted(
        all_keys,
        key=lambda k: (page_rank.get(k[0], len(page_rank)), k[1], k[2]),
    )
