"""Render an :class:`~inventory.types.InventoryMap` to Console / log lines.

PURE (stdlib only): every renderer returns ``list[str]`` and is fully
deterministic, so it is unit-testable on a hand-built ``InventoryMap`` with NO
game and NO numpy. The runner / UI feed the returned lines to ``debuglog`` /
the Console (which already render plain text).

Three renderers:
  * :func:`format_page_grid` -- one page as a header + 9 rows of 5 fixed-width
    cells (``.`` empty, ``?`` unknown, else a short item token).
  * :func:`format_tracked`   -- a "Tracked found at:" summary (one line per
    found tracked item with its page/row/col list) + a "not found" line.
  * :func:`format_full`      -- all present pages' grids followed by the tracked
    summary.

ROADMAP: item HANDLING (move / use / delete) is intentionally OUT of scope. This
module + :meth:`InventoryMap.tracked` / :meth:`InventoryMap.locations` ARE the
seam: a future handler will consume ``tracked()`` / ``locations()`` to ACT on a
key item by coordinate (e.g. drag a Fischpuzzlebox onto the open puzzle, or use
a Worm as bait). Until then we only LOCATE + report.
"""

from typing import List

from .constants import COLS, ROWS, PAGES, KEY_ITEMS
from .types import STATE_EMPTY, STATE_ITEM, STATE_UNKNOWN


# Fixed cell width for the grid dump. A short token must fit; 4 chars + a space
# separator keeps a 5-column row compact yet readable in the Console.
_CELL_W = 4

# Tokens for the non-item slot states.
_TOK_EMPTY = '.'
_TOK_UNKNOWN = '?'
_TOK_MISSING = '-'   # no SlotResult at this (row, col) (defensive)


def short_token(name) -> str:
    """A deterministic <= ``_CELL_W``-char token for an item name.

    Strategy (stable + readable): split on ``_``/space; if there are >= 2 words,
    take the leading letters of the words (an acronym, e.g. 'Fischpuzzlebox' is
    one word -> 'Fisc'; 'Red_Hair_Dye' -> 'RHD'); otherwise take the first
    ``_CELL_W`` characters. Always trimmed to ``_CELL_W``. ``None`` -> '?'.
    """
    if not name:
        return _TOK_UNKNOWN
    words = [w for w in name.replace('_', ' ').split(' ') if w]
    if len(words) >= 2:
        token = ''.join(w[0] for w in words)
    else:
        token = words[0] if words else name
    return token[:_CELL_W]


def _cell(token) -> str:
    """Left-justify a token to the fixed cell width."""
    return token.ljust(_CELL_W)


def _page_slots(inv_map, page):
    """``{(row, col): SlotResult}`` for ``page`` (empty dict if page absent)."""
    by_idx = {}
    for r in inv_map.pages.get(page, ()):  # absent page -> no rows
        by_idx[(r.row, r.col)] = r
    return by_idx


def format_page_grid(inv_map, page) -> List[str]:
    """Render one page: a header line + ``ROWS`` rows of ``COLS`` cells.

    Header: ``Page <label>  (items=.. unknown=..)``. Each grid row is
    ``COLS`` fixed-width cells: ``.`` empty, ``?`` unknown, ``-`` missing, else a
    short item token (see :func:`short_token`). Returns ``1 + ROWS`` lines. A
    page absent from the scan still renders (all cells ``-``) so the dump shape
    is constant.
    """
    by_idx = _page_slots(inv_map, page)
    slots = [by_idx[(r, c)] for r in range(ROWS) for c in range(COLS)
             if (r, c) in by_idx]
    items = sum(1 for s in slots if s.state == STATE_ITEM)
    unknown = sum(1 for s in slots if s.state == STATE_UNKNOWN)

    lines = ['Page {}  (items={} unknown={})'.format(page, items, unknown)]
    for row in range(ROWS):
        cells = []
        for col in range(COLS):
            res = by_idx.get((row, col))
            if res is None:
                tok = _TOK_MISSING
            elif res.state == STATE_EMPTY:
                tok = _TOK_EMPTY
            elif res.state == STATE_UNKNOWN:
                tok = _TOK_UNKNOWN
            else:
                tok = short_token(res.name)
            cells.append(_cell(tok))
        lines.append(' '.join(cells).rstrip())
    return lines


def format_tracked(inv_map, names=KEY_ITEMS) -> List[str]:
    """Render the "Tracked found at:" summary for ``names``.

    One line per FOUND tracked item: ``<name> x<count>: <page>(<row>,<col>),
    ...`` (locations in page-then-row-major order). A trailing ``not found:
    <names>`` line lists the tracked names with zero hits (omitted if all were
    found). Always begins with a ``Tracked found at:`` header so the block is
    recognisable even when nothing was found.
    """
    lines = ['Tracked found at:']
    found_any = False
    missing = []
    for name in names:
        locs = inv_map.locations(name)
        if not locs:
            missing.append(name)
            continue
        found_any = True
        where = ', '.join('{}({},{})'.format(p, r, c) for (p, r, c) in locs)
        lines.append('  {} x{}: {}'.format(name, len(locs), where))
    if not found_any:
        lines.append('  (none)')
    if missing:
        lines.append('  not found: {}'.format(', '.join(missing)))
    return lines


def format_full(inv_map, names=KEY_ITEMS) -> List[str]:
    """Assemble per-page grids (for every present page, in PAGES order) followed
    by the tracked summary. Deterministic -> directly unit-testable.

    Pages are emitted in the canonical I->IV order for the pages actually in the
    scan; a blank separator line is inserted between blocks for readability.
    """
    lines: List[str] = []
    present = [p for p in PAGES if p in inv_map.pages]
    # Include any non-standard page keys too (defensive), after the known ones.
    present += [p for p in inv_map.pages if p not in PAGES]
    for page in present:
        if lines:
            lines.append('')
        lines.extend(format_page_grid(inv_map, page))
    if lines:
        lines.append('')
    lines.extend(format_tracked(inv_map, names))
    return lines
