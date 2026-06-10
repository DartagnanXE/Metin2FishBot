# -*- coding: utf-8 -*-
"""Wegwerfen / fallen lassen -- drop every REMOVE-marked item into the world.

This is the live-wire behind the "Inventar managen" apply for items the user put
in the REMOVE state: it click-drags each removed item's slot OUT of the bag, into
the WORLD just left of the inventory panel, and confirms the "Moechtest du X
fallen lassen?" dialog that pops up by clicking its "Ja" button.

DESIGN (mirrors :mod:`inventory_campfire`): the PURE brain + coordinate maths
live here, free of any live dependency, so the whole flow is unit-tested headless
by INJECTING the input/capture/scan APIs. The two genuinely live things -- the
``pydirectinput`` actions and the :class:`~windowcapture.WindowCapture` frame --
are passed in by :mod:`interface.inventory_discard_runner` (the only win32 shell).
Like the rest of the project, every function is DEFENSIVE: it logs + returns a
status, it never raises into the bot/UI.

MECHANIC (verified in-game by the user): a REMOVE-marked item is dragged from its
slot to a point in the world LEFT of the panel; Metin2 then shows a centred
"Moechtest du X fallen lassen?" dialog whose "Ja" button is clicked to confirm.

GEOMETRY (measured, engine/client pixels -- screenshot pixel == game pixel, no
offset; ``offset`` adds the window origin exactly like every other bot click):

  * The drop target sits LEFT of the panel at ``(origin_x - 32, origin_y +
    SLOT_PX//2)`` -- the panel's left edge is ~``origin_x - 7``, so ``-32`` lands
    safely in the water/world, vertically level with the first slot row.
  * The "Ja" button of the centred confirm dialog sits at
    ``(client_w//2 - 48, client_h//2 + 16)`` -- on the measured 800x600 client
    that is ``(352, 316)``.

This module deliberately keeps its OWN copies of :func:`drag` + :func:`_slot_screen`
(mirrors of :mod:`inventory_campfire`, NOT imported from it) so the discard flow
shares no code with the grill flow and the two stay disjoint.
"""

from inventory.constants import DEFAULT_CALIBRATION, SLOT_PX, INPUT_SETTLE_S
from inventory.grid import lattice_from_calibration

# Diagnose-Logging (soft) -- macht das Wegwerfen in der Live-Console sichtbar; ein
# fehlender/kaputter Logger darf den Ablauf nie stoppen (Projekt-Disziplin).
try:  # pragma: no cover - reiner Fallback
    from debuglog import log
except Exception:  # pragma: no cover
    log = None

try:  # pragma: no cover - i18n immer da, aber defensiv
    from i18n import t as _t
except Exception:  # pragma: no cover
    def _t(key, **fmt):
        return key


# -- denylist (NEVER dropped, even if somehow marked REMOVE) -----------------

#: Tools/baits/boxes that are NEVER thrown away even if somehow marked REMOVE.
#: Same idea/denylist as :data:`inventory_campfire.NON_BURNABLE_NAMES`: the
#: campfire is the TOOL you cook with, Worm + any bait/koeder is what you fish
#: with, and the puzzle boxes are valuable -- none must ever be dropped. Belt-
#: and-suspenders on top of the per-item gate in
#: :func:`interface.inventory_manage.allowed_states` (FIXED_KEEP items can not be
#: cycled to REMOVE at all), so a stale/forced state can never drop a tool.
NON_DISCARDABLE_NAMES = frozenset({
    'Lagerfeuer', 'Worm', 'Bait', 'Koeder', 'Köder',
    'Fischpuzzlebox', 'Fischpuzzlebox_Deluxe',
})

#: Inventory pages in scan order (matches the rest of the engine).
PAGE_ORDER = ('I', 'II', 'III', 'IV')

#: Offset (dx, dy) in ENGINE/client pixels from the grid ORIGIN to the world drop
#: point left of the panel. ``-32`` clears the panel's left edge (~origin_x-7)
#: into the world; ``SLOT_PX//2`` keeps it level with the first slot row.
DROP_OFFSET_FROM_ORIGIN = (-32, SLOT_PX // 2)

#: Offset (dx, dy) in ENGINE/client pixels from the client CENTRE to the "Ja"
#: button of the centred "fallen lassen?" confirm dialog. Measured on the 800x600
#: client: ``(400-48, 300+16) = (352, 316)``.
CONFIRM_YES_OFFSET_FROM_CENTRE = (-48, 16)


# -- timing (seconds; tunable on the live window) ---------------------------

#: Settle after a discard drag into the world, before clicking the confirm "Ja"
#: (lets Metin2 raise the "fallen lassen?" dialog). RISK SPOT: if items are NOT
#: dropped because "Ja" is clicked before the dialog appears, raise INPUT_SETTLE_S.
DROP_SETTLE_S = INPUT_SETTLE_S

#: Settle after clicking the confirm "Ja", before the next item.
CONFIRM_SETTLE_S = INPUT_SETTLE_S


def _flog(state, key, **fmt):
    """Loggt ein Wegwerf-Event (falls debuglog da). Wirft nie."""
    if log is None:
        return
    try:
        log.event(state, _t(key, **fmt))
    except Exception:
        pass


# -- which items to discard (pure selection) --------------------------------

def discard_item_names(states):
    """Item names the user marked REMOVE, with baits/tools/boxes EXCLUDED.

    ``states`` is the inventory-manage map ``{name: KEEP|REMOVE|CAMPFIRE}`` (icon
    stems, e.g. ``'Carp'`` -- the SAME keys :class:`~inventory.types.SlotResult`
    carries). Returns the sorted set of names whose state is REMOVE and which are
    not in :data:`NON_DISCARDABLE_NAMES` (so Worm / Lagerfeuer / koeder / puzzle
    boxes can never be dropped even if forced). Pure; never raises.
    """
    try:
        from interface.inventory_manage import REMOVE
    except Exception:                       # pragma: no cover - standalone
        REMOVE = 1
    out = []
    try:
        for name, state in (states or {}).items():
            if int(state) == REMOVE and name not in NON_DISCARDABLE_NAMES:
                out.append(name)
    except Exception:
        return []
    return sorted(out)


def item_slots_to_discard(inv, names, pages=PAGE_ORDER):
    """Every inventory slot holding one of ``names`` (removed items), in order.

    Page order I->IV then row-major within a page (the documented inventory
    traversal, same as :func:`inventory_campfire.fish_slots_to_grill`). Each entry
    is ``(page, row, col, name)``. Baits/tools/boxes are double-excluded here too,
    so the list is safe to drop verbatim. Pure: works on any object exposing
    ``pages -> {page: [SlotResult]}``. Never raises.
    """
    want = {n for n in (names or ()) if n not in NON_DISCARDABLE_NAMES}
    out = []
    if not want:
        return out
    try:
        page_map = getattr(inv, 'pages', {}) or {}
        for page in pages:
            slots = page_map.get(page) or ()
            for s in slots:
                if (getattr(s, 'state', None) == 'item'
                        and getattr(s, 'name', None) in want):
                    out.append((page, int(s.row), int(s.col),
                                getattr(s, 'name')))
    except Exception:
        return out
    return out


# -- world / dialog geometry (pure) -----------------------------------------

def drop_point(lattice, offset=(0, 0)):
    """SCREEN ``(x, y)`` of the WORLD drop point left of the panel.

    World point (engine coords) = grid ORIGIN + :data:`DROP_OFFSET_FROM_ORIGIN`
    = ``(origin_x - 32, origin_y + SLOT_PX//2)``; ``offset`` (the window origin)
    is then added exactly like every other bot click. Pure. Returns ``None`` for
    a missing lattice so callers can branch cleanly.
    """
    if lattice is None:
        return None
    try:
        ox, oy = lattice.origin
        dx, dy = DROP_OFFSET_FROM_ORIGIN
        return (int(offset[0]) + int(ox) + dx, int(offset[1]) + int(oy) + dy)
    except Exception:
        return None


def confirm_yes_point(client_w, client_h, offset=(0, 0)):
    """SCREEN ``(x, y)`` of the "Ja" button of the centred confirm dialog.

    The "Moechtest du X fallen lassen?" dialog is centred on the client, so its
    "Ja" sits at ``client_centre + CONFIRM_YES_OFFSET_FROM_CENTRE`` =
    ``(client_w//2 - 48, client_h//2 + 16)``; ``offset`` (the window origin) is
    then added like every other bot click. Measured on the 800x600 client:
    ``(352, 316)`` before offset. Pure; never raises (a bad size -> centre).
    """
    try:
        cw, ch = int(client_w), int(client_h)
    except Exception:
        cw, ch = 0, 0
    dx, dy = CONFIRM_YES_OFFSET_FROM_CENTRE
    return (int(offset[0]) + cw // 2 + dx, int(offset[1]) + ch // 2 + dy)


# -- live orchestration (deps INJECTED -> headless-testable) ----------------

class DiscardResult:
    """Tiny immutable-ish report of a discard run (what happened, for the Console).

    Not a dataclass to stay import-light + Py-version-proof; treated read-only.

    :ivar status: ``'done'`` / ``'no_items'`` / ``'not_open'`` / ``'error'``.
    :ivar dropped: list of ``(page, row, col, name)`` actually dropped.
    :ivar drop_point: the SCREEN ``(x, y)`` the items were dragged to (or ``None``).
    """

    __slots__ = ('status', 'dropped', 'drop_point')

    def __init__(self, status, dropped=None, drop_point=None):
        self.status = status
        self.dropped = list(dropped or [])
        self.drop_point = drop_point

    def __repr__(self):
        return ('DiscardResult(status=%r, dropped=%d, drop_point=%r)'
                % (self.status, len(self.dropped), self.drop_point))


def run_discard(states, *, inp, capture_fn, scan_fn, client_size,
                offset=(0, 0), calib=DEFAULT_CALIBRATION, lattice=None,
                sleep=None):
    """Full discard flow: drag each REMOVE-marked item out + confirm "Ja".

    All live dependencies are INJECTED so the orchestration is headless-testable
    (mirrors :func:`inventory_campfire.run_campfire`):

      * ``inp``         -- input api: ``moveTo``/``mouseDown``/``mouseUp`` (the
        drag) + ``click(x, y)`` (page tab + the confirm "Ja"). pydirectinput in
        production.
      * ``capture_fn``  -- returns the current frame (unused by the pure maths;
        accepted so the runner can wire the same capture seam as the grill and a
        future dialog-verify can use it). May be ``None``.
      * ``scan_fn``     -- returns a fresh inventory map (the runner wires the
        headless scanner); used to LOCATE the removed item slots.
      * ``client_size`` -- ``(client_w, client_h)`` of the captured client, for
        the centred confirm-dialog "Ja" point.
      * ``offset``      -- ``(offset_x, offset_y)`` window origin added to every
        screen click (exactly like the rest of the bot).
      * ``lattice``     -- the LOCKED :class:`~inventory.grid.GridLattice` from
        the runner's one-shot ``auto_align``; when ``None`` we fall back to
        ``lattice_from_calibration(calib)``. Using the locked grid makes the drag
        hit the slot CENTRE (the raw calibration sits ~1 slot too low).

    Returns a :class:`DiscardResult`. STRICTLY defensive: any failure short-
    circuits to a clear status (and the button is released in :func:`drag`'s
    finally), never an exception into the bot/UI.
    """
    if sleep is None:
        import time
        sleep = time.sleep

    names = discard_item_names(states)
    if not names:
        _flog('-', 'discard.no_items')
        return DiscardResult('no_items')

    try:
        ox, oy = int(offset[0]), int(offset[1])
        lat = lattice or lattice_from_calibration(calib)

        # 1) Scan to locate the REMOVE-marked item slots up front.
        inv = scan_fn()
        if inv is None:
            _flog('-', 'discard.scan_failed')
            return DiscardResult('error')

        targets = item_slots_to_discard(inv, names)
        if not targets:
            _flog('-', 'discard.no_items')
            return DiscardResult('no_items')

        try:
            cw, ch = int(client_size[0]), int(client_size[1])
        except Exception:
            cw, ch = 0, 0
        yes_xy = confirm_yes_point(cw, ch, offset=(ox, oy))
        world = drop_point(lat, offset=(ox, oy))
        if world is None:
            _flog('-', 'discard.no_drop_point')
            return DiscardResult('error')

        _flog('0', 'discard.started')

        # 2) Drop each removed item: switch page -> drag slot -> world -> confirm.
        dropped = []
        for (page, row, col, name) in targets:
            _switch_page(inp, calib, ox, oy, page, sleep)
            sx, sy = _slot_screen(row, col, calib, ox, oy, lattice=lat)
            drag(inp, sx, sy, world[0], world[1], sleep=sleep)
            sleep(DROP_SETTLE_S)
            _click(inp, yes_xy[0], yes_xy[1])     # confirm "Ja"
            sleep(CONFIRM_SETTLE_S)
            dropped.append((page, row, col, name))
            _flog('0', 'discard.dropped_one', name=name, page=page,
                  slot=_slot_no(row, col))

        _flog('0', 'discard.done', count=len(dropped))
        return DiscardResult('done', dropped=dropped, drop_point=world)
    except Exception as exc:                # pragma: no cover - last-ditch guard
        _flog('-', 'discard.error', detail=str(exc)[:120])
        return DiscardResult('error')


# -- input primitives (pure given an injected api) --------------------------

def drag(api, x1, y1, x2, y2, steps=12, settle=INPUT_SETTLE_S, sleep=None):
    """Press-hold-move-release drag from ``(x1,y1)`` to ``(x2,y2)``.

    Same contract as :func:`inventory_campfire.drag` (intermediate moves so the
    game registers a real drag, button released in a ``finally`` so a failed drag
    never crashes the loop). Kept here too so the discard flow has no dependency
    on the campfire module. Never raises.
    """
    if sleep is None:
        import time
        sleep = time.sleep
    try:
        api.moveTo(int(x1), int(y1))
        sleep(settle)
        api.mouseDown()
        sleep(settle)
        n = max(1, int(steps))
        for i in range(1, n + 1):
            x = x1 + (x2 - x1) * i // n
            y = y1 + (y2 - y1) * i // n
            api.moveTo(int(x), int(y))
            sleep(settle / n)
        sleep(settle)
    finally:
        try:
            api.mouseUp()
        except Exception:
            pass


def _click(api, x, y):
    """Click ``(x, y)`` via the injected api. Never raises.

    Prefers a real ``click``; falls back to a move + down/up pair so any injected
    api shape works.
    """
    x, y = int(x), int(y)
    try:
        if hasattr(api, 'click'):
            api.click(x=x, y=y)
        else:
            api.moveTo(x, y)
            api.mouseDown()
            api.mouseUp()
    except Exception:
        pass


# -- coordinate helpers (reuse the inventory calibration) -------------------

def _slot_screen(row, col, calib, offset_x, offset_y, lattice=None):
    """Screen centre of inventory slot ``(row, col)`` (grid + offset).

    Mirrors :func:`inventory_campfire._slot_screen` but prefers an injected LOCKED
    :class:`~inventory.grid.GridLattice` (from the runner's ``auto_align``) over
    the raw ``lattice_from_calibration(calib)``: the raw calibration sits ~1 slot
    too low, so using the locked grid makes the drag SOURCE hit the slot centre.
    """
    lat = lattice or lattice_from_calibration(calib)
    ox, oy = lat.origin
    px, py = lat.pitch
    x = ox + col * px + px // 2
    y = oy + row * py + py // 2
    return (int(offset_x + x), int(offset_y + y))


def _switch_page(inp, calib, offset_x, offset_y, page, sleep):
    """Click an inventory page tab (I..IV) via the injected api, then settle.

    No-op when the page has no calibrated tab. Never raises.
    """
    try:
        tabs = (calib or {}).get('tabs') or {}
        pt = tabs.get(page)
        if pt and hasattr(inp, 'click'):
            inp.click(x=int(offset_x + pt[0]), y=int(offset_y + pt[1]))
            sleep(INPUT_SETTLE_S)
    except Exception:
        pass


def _slot_no(row, col):
    """1-based human slot index within a page (row-major). Matches the runner."""
    from inventory.constants import COLS
    return int(row) * COLS + int(col) + 1


__all__ = [
    'NON_DISCARDABLE_NAMES', 'PAGE_ORDER', 'DROP_OFFSET_FROM_ORIGIN',
    'CONFIRM_YES_OFFSET_FROM_CENTRE',
    'discard_item_names', 'item_slots_to_discard', 'drop_point',
    'confirm_yes_point', 'DiscardResult', 'run_discard', 'drag',
]
