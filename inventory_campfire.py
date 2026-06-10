# -*- coding: utf-8 -*-
"""Lagerfeuer-Braten -- place a campfire and grill the CAMPFIRE-marked fish.

This is the live-wire behind the "Inventar managen" apply for fish the user put
in the CAMPFIRE state: it drops the Lagerfeuer tool from the inventory, finds the
fire's WORLD position by recognising its on-screen "Lagerfeuer" label, and then
click-drags every campfire-marked fish slot onto the fire.

DESIGN (mirrors :mod:`interface.refill`): the PURE brain + image primitives live
here, free of any live dependency, so the whole flow is unit-tested headless by
INJECTING the input/capture/scan APIs. The two genuinely live things -- the
``pydirectinput`` actions and the :class:`~windowcapture.WindowCapture` frame --
are passed in by :mod:`interface.inventory_campfire_runner` (the only win32 shell).
Like the rest of the project, every function is DEFENSIVE: it logs + returns a
status, it never raises into the bot/UI.

THE SIGNATURE (hard-calibrated; do NOT re-derive -- see
``tools/extract_campfire_template.py`` and ``FischOCR/Lagerfeuer markeirung/``):

  * The placed campfire is signposted by a SCREEN-ALIGNED green text label
    "Lagerfeuer" (it does NOT rotate with the dock camera) rendered in the game's
    fixed pixel font, so the green glyph run is byte-stable: 47x11 px, ~112 green
    pixels, every time, wherever the object sits.
  * Recognition = a GREEN-prefiltered masked NCC of that glyph (the bundled
    ``campfire_templates/lagerfeuer_mask.png``) over the whole captured frame.
    Measured peak: 0.99-1.0 on a real campfire vs <= 0.53 on any non-campfire
    fishing frame, so :data:`LABEL_MATCH_THRESHOLD` = 0.80 separates them with a
    wide margin.
  * The FIRE world point (where a fish must be dropped -- the red placement
    circle's centre) sits a steady :data:`FIRE_OFFSET_FROM_LABEL_TL` = (20, 21)
    px from the matched label's TOP-LEFT, in every reference.

CAPTURE CONVENTION (verified): the captured frame is the SAME 802x632 window the
reference shots are; screenshot pixel == game/world pixel directly (no offset).
A label found at screenshot ``(x, y)`` is dragged to as ``world + window_offset``
exactly like every other click in the bot (fishingbot/puzzle/refill add
``wincap.offset_x/y``).
"""

from inventory.constants import DEFAULT_CALIBRATION, INPUT_SETTLE_S
from inventory.grid import lattice_from_calibration

try:  # pragma: no cover - numpy present in production
    import numpy as _np
except Exception:  # pragma: no cover
    _np = None

try:  # pragma: no cover - cv2 present in production
    import cv2 as _cv
except Exception:  # pragma: no cover
    _cv = None

try:  # pragma: no cover - PIL present in production
    from PIL import Image as _Image
except Exception:  # pragma: no cover
    _Image = None

from respath import resource_path

# Diagnose-Logging (soft) -- macht das Braten in der Live-Console sichtbar; ein
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


# -- hard-calibrated constants (see module docstring / extractor) -----------

#: Bundled green-glyph mask of the "Lagerfeuer" label (1-bit; ink = text).
LABEL_TEMPLATE_PATH = 'campfire_templates/lagerfeuer_mask.png'

#: The fixed glyph size of the label in the game's pixel font (w, h).
LABEL_GLYPH_SIZE = (47, 11)

#: Masked-NCC peak at/above which the "Lagerfeuer" label counts as FOUND. Real
#: campfire references peak 0.99-1.0; the busiest non-campfire fishing frame
#: peaks <= 0.53 -- 0.80 sits in the gap with a wide margin both ways.
LABEL_MATCH_THRESHOLD = 0.80

#: Offset (dx, dy) from the matched label's TOP-LEFT to the FIRE world point (the
#: red placement-circle centre) -- where a fish is dropped. Steady in every shot.
FIRE_OFFSET_FROM_LABEL_TL = (20, 21)

#: Tools/baits that are NEVER grilled even if somehow marked CAMPFIRE. The
#: campfire itself is the TOOL we cook WITH; Worm + any bait/koeder item are
#: consumables you fish with. Belt-and-suspenders on top of the per-item gate in
#: :func:`interface.inventory_manage.allowed_states` (which already forbids the
#: CAMPFIRE state for these), so a stale/forced state can never burn a bait.
NON_BURNABLE_NAMES = frozenset({
    'Lagerfeuer', 'Worm', 'Bait', 'Koeder', 'Köder',
    'Fischpuzzlebox', 'Fischpuzzlebox_Deluxe',
})

#: Item name of the placeable campfire tool in the inventory (icon stem).
CAMPFIRE_ITEM_NAME = 'Lagerfeuer'

#: Inventory pages in scan order (matches the rest of the engine).
PAGE_ORDER = ('I', 'II', 'III', 'IV')


# -- timing (seconds; tunable on the live window) ---------------------------

#: Hold time for the bird's-eye-view key ("G") after placing the campfire, so the
#: top-down camera settles before scanning for the label. RISK SPOT: this is a
#: real key-HOLD that moves the CAMERA, not just a wait -- at 0.05s the top-down
#: view may not flip, so if campfire stops finding the "Lagerfeuer" label this is
#: the FIRST knob to raise (kept as its OWN value, not tied to INPUT_SETTLE_S).
BIRDS_EYE_HOLD_S = 0.05

#: Settle after the place double-click, before pressing the bird's-eye key.
PLACE_SETTLE_S = INPUT_SETTLE_S

#: Settle after a camera-rotate key ("E") press, before re-scanning.
ROTATE_SETTLE_S = INPUT_SETTLE_S

#: How many camera rotations to try while hunting for the label before giving up.
MAX_ROTATE_ATTEMPTS = 8

#: Settle after a fish drag onto the fire, before the next one.
GRILL_SETTLE_S = INPUT_SETTLE_S


def _flog(state, key, **fmt):
    """Loggt ein Lagerfeuer-Event (falls debuglog da). Wirft nie."""
    if log is None:
        return
    try:
        log.event(state, _t(key, **fmt))
    except Exception:
        pass


# -- green prefilter + template loading -------------------------------------

def green_text_mask(rgb):
    """Boolean->uint8 mask of the green "Lagerfeuer" label pixels in an RGB frame.

    EXACTLY the threshold the bundled template was cut with
    (``tools/extract_campfire_template.py``): green dominant, clearly above blue,
    not bluish/whitish. Returns a ``(H, W)`` uint8 array (1 = green text), or
    ``None`` when numpy is missing / the frame is unusable. Never raises.
    """
    if _np is None or rgb is None:
        return None
    try:
        a = _np.asarray(rgb)
        if a.ndim != 3 or a.shape[2] < 3:
            return None
        a = a[:, :, :3].astype(_np.int32)
        r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
        mask = (g > 110) & (g - b > 50) & (g >= r) & (r > 40)
        return mask.astype(_np.uint8)
    except Exception:
        return None


def load_label_template():
    """Load the bundled "Lagerfeuer" glyph mask as a ``(11, 47)`` uint8 (0/1).

    Resolved via :func:`respath.resource_path` so it works from source AND from
    the packed --onefile EXE (the PNG is bundled under ``campfire_templates/``).
    Returns ``None`` (logged) when PIL/numpy is missing or the file is unreadable
    -- the caller then reports "label unavailable" rather than crashing. Never
    raises.
    """
    if _np is None or _Image is None:
        _flog('-', 'campfire.template_unavailable')
        return None
    path = resource_path(LABEL_TEMPLATE_PATH)
    try:
        with _Image.open(path) as img:
            arr = _np.asarray(img.convert('L'), dtype=_np.uint8)
        return (arr > 127).astype(_np.uint8)
    except Exception as exc:
        _flog('-', 'campfire.template_load_failed', detail=str(exc)[:120])
        return None


def find_label(frame_rgb, template=None, threshold=LABEL_MATCH_THRESHOLD):
    """Locate the "Lagerfeuer" label in ``frame_rgb`` by green-masked NCC.

    Green-prefilters the frame (:func:`green_text_mask`), then slides the glyph
    mask over it with ``cv2.matchTemplate`` (``TM_CCORR_NORMED`` on the two 0/1
    fields -- the matcher that scored 1.0 on every reference). Returns
    ``(found, score, top_left)``:

      * ``found``    -- ``True`` iff ``score >= threshold``.
      * ``score``    -- the peak correlation (0..1; 0.0 on any failure).
      * ``top_left`` -- ``(x, y)`` of the best match's top-left (the glyph box),
        or ``None`` when nothing could be scored.

    Strictly defensive: missing cv2/numpy, a too-small/empty frame, or no green
    at all -> ``(False, 0.0, None)``. Never raises.
    """
    if _cv is None or _np is None:
        return (False, 0.0, None)
    if template is None:
        template = load_label_template()
    if template is None:
        return (False, 0.0, None)
    gm = green_text_mask(frame_rgb)
    if gm is None:
        return (False, 0.0, None)
    th, tw = template.shape[0], template.shape[1]
    if gm.shape[0] < th or gm.shape[1] < tw:
        return (False, 0.0, None)
    if int(gm.sum()) == 0:
        # No green text anywhere -> definitely no label (cheap early out).
        return (False, 0.0, None)
    try:
        res = _cv.matchTemplate(gm.astype(_np.float32),
                                template.astype(_np.float32),
                                _cv.TM_CCORR_NORMED)
        _mn, mx, _ml, ml = _cv.minMaxLoc(res)
        score = float(mx)
        return (score >= float(threshold), score, (int(ml[0]), int(ml[1])))
    except Exception as exc:
        _flog('-', 'campfire.match_error', detail=str(exc)[:90])
        return (False, 0.0, None)


def fire_point_from_label(top_left):
    """World ``(x, y)`` of the FIRE (drop target) from the label's top-left.

    ``label_top_left + FIRE_OFFSET_FROM_LABEL_TL``. Pure. Returns ``None`` for a
    ``None`` input (no label) so callers can branch cleanly.
    """
    if top_left is None:
        return None
    dx, dy = FIRE_OFFSET_FROM_LABEL_TL
    return (int(top_left[0]) + dx, int(top_left[1]) + dy)


# -- which fish to grill (pure selection) -----------------------------------

def campfire_fish_names(states):
    """Item names the user marked CAMPFIRE, with baits/tools EXCLUDED.

    ``states`` is the inventory-manage map ``{name: KEEP|REMOVE|CAMPFIRE}`` (icon
    stems, e.g. ``'Carp'`` -- the SAME keys :class:`~inventory.types.SlotResult`
    carries). Returns the sorted set of names whose state is CAMPFIRE and which
    are not in :data:`NON_BURNABLE_NAMES` (so Worm / Lagerfeuer / koeder / puzzle
    boxes can never end up on the fire even if forced). Pure; never raises.
    """
    try:
        from interface.inventory_manage import CAMPFIRE
    except Exception:                       # pragma: no cover - standalone
        CAMPFIRE = 2
    out = []
    try:
        for name, state in (states or {}).items():
            if int(state) == CAMPFIRE and name not in NON_BURNABLE_NAMES:
                out.append(name)
    except Exception:
        return []
    return sorted(out)


def fish_slots_to_grill(inv, names, pages=PAGE_ORDER):
    """Every inventory slot holding one of ``names`` (campfire fish), in order.

    Page order I->IV then row-major within a page (the documented inventory
    traversal, same as :func:`interface.refill.find_first`). Each entry is
    ``(page, row, col, name)``. Baits/tools are double-excluded here too, so the
    list is safe to drag onto the fire verbatim. Pure: works on any object
    exposing ``pages -> {page: [SlotResult]}``. Never raises.
    """
    want = {n for n in (names or ()) if n not in NON_BURNABLE_NAMES}
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


# -- live orchestration (deps INJECTED -> headless-testable) ----------------

class CampfireResult:
    """Tiny immutable-ish report of a grill run (what happened, for the Console).

    Not a dataclass to stay import-light + Py-version-proof; treated read-only.

    :ivar status: ``'done'`` / ``'no_campfire_item'`` / ``'label_not_found'`` /
        ``'no_fish'`` / ``'not_open'`` / ``'error'``.
    :ivar grilled: list of ``(page, row, col, name)`` actually dragged.
    :ivar fire_point: the world ``(x, y)`` the fish were dropped on (or ``None``).
    :ivar label_score: the best label match score seen (diagnostic).
    :ivar rotations: how many camera rotations were tried before the label hit.
    """

    __slots__ = ('status', 'grilled', 'fire_point', 'label_score', 'rotations')

    def __init__(self, status, grilled=None, fire_point=None, label_score=0.0,
                 rotations=0):
        self.status = status
        self.grilled = list(grilled or [])
        self.fire_point = fire_point
        self.label_score = float(label_score)
        self.rotations = int(rotations)

    def __repr__(self):
        return ('CampfireResult(status=%r, grilled=%d, fire_point=%r, '
                'score=%.3f, rotations=%d)'
                % (self.status, len(self.grilled), self.fire_point,
                   self.label_score, self.rotations))


def locate_fire(capture_rgb_fn, *, template=None, rotate_fn=None,
                max_attempts=MAX_ROTATE_ATTEMPTS, settle=ROTATE_SETTLE_S,
                sleep=None):
    """Scan for the "Lagerfeuer" label, rotating the camera until it appears.

    ``capture_rgb_fn`` returns the current frame as an RGB array (the runner
    converts the BGR capture once). ``rotate_fn`` rotates the in-game camera (the
    runner presses "E"); called between attempts. Returns
    ``(fire_point, best_score, attempts)`` -- ``fire_point`` is ``None`` if the
    label never cleared the threshold within ``max_attempts``.

    PURE w.r.t. the game: all motion is injected, so this is exercised headless by
    feeding a sequence of synthetic frames. Never raises (a capture/rotate hiccup
    counts as "not this attempt" and the search continues / ends cleanly).
    """
    if sleep is None:
        import time
        sleep = time.sleep
    best = 0.0
    attempts = 0
    # attempt 0 is the initial look; each extra attempt rotates first.
    for i in range(max(1, int(max_attempts))):
        if i > 0 and rotate_fn is not None:
            try:
                rotate_fn()
            except Exception:
                pass
            try:
                sleep(settle)
            except Exception:
                pass
            attempts += 1
        try:
            frame = capture_rgb_fn()
        except Exception:
            frame = None
        found, score, tl = find_label(frame, template=template)
        if score > best:
            best = score
        if found:
            return (fire_point_from_label(tl), score, attempts)
    return (None, best, attempts)


def run_campfire(states, *, inp, capture_rgb_fn, scan_fn, offset=(0, 0),
                 calib=DEFAULT_CALIBRATION, sleep=None, template=None,
                 birds_eye_key='g', rotate_key='e', lattice=None):
    """Full grill flow: place the campfire, find the fire, drag the fish on.

    All live dependencies are INJECTED so the orchestration is headless-testable
    (mirrors :func:`interface.refill.refill_from_inventory`):

      * ``inp``            -- input api: ``moveTo``/``mouseDown``/``mouseUp`` (the
        drag) + ``doubleClick(x, y)`` (place the tool) + ``keyDown``/``keyUp``
        (bird's-eye hold, camera rotate). pydirectinput in production.
      * ``capture_rgb_fn`` -- returns the current frame as an RGB array.
      * ``scan_fn``        -- returns a fresh inventory map (the runner wires the
        headless scanner); used to LOCATE the campfire tool + the fish slots.
      * ``offset``         -- ``(offset_x, offset_y)`` window origin added to every
        world click (exactly like the rest of the bot).
      * ``lattice``        -- optional locked :class:`inventory.grid.GridLattice`
        (from :func:`inventory.grid.auto_align`) the runner pre-locks ONCE on the
        live window. Threaded into EVERY slot-coordinate call (the tool double-
        click + every fish drag SOURCE) so they hit the SAME grid recognition uses
        -- the user's bag sits ~1 slot above the bundled DEFAULT_CALIBRATION, so
        the un-aligned calib alone grabs one slot too low + off-centre. ``None``
        falls back to the calibration lattice (the historical headless behaviour).

    Returns a :class:`CampfireResult`. STRICTLY defensive: any failure short-
    circuits to a clear status (and the button is released in :func:`drag`'s
    finally), never an exception into the bot/UI.
    """
    if sleep is None:
        import time
        sleep = time.sleep

    fish_names = campfire_fish_names(states)
    if not fish_names:
        _flog('-', 'campfire.no_fish_marked')
        return CampfireResult('no_fish')

    try:
        ox, oy = int(offset[0]), int(offset[1])

        # 1) Scan to locate the Lagerfeuer TOOL + the marked fish slots up front.
        inv = scan_fn()
        if inv is None:
            _flog('-', 'campfire.scan_failed')
            return CampfireResult('error')

        tool = _find_item_slot(inv, CAMPFIRE_ITEM_NAME, calib, ox, oy,
                               lattice=lattice)
        if tool is None:
            _flog('-', 'campfire.no_campfire_item')
            return CampfireResult('no_campfire_item')

        targets = fish_slots_to_grill(inv, fish_names)
        if not targets:
            _flog('-', 'campfire.no_fish')
            return CampfireResult('no_fish')

        # 2) Place the campfire: DOUBLE-CLICK its inventory slot.
        tool_page, tool_xy = tool
        _switch_page(inp, calib, ox, oy, tool_page, sleep)
        _double_click(inp, tool_xy[0], tool_xy[1])
        sleep(PLACE_SETTLE_S)

        # 3) Bird's-eye view: HOLD the configured key (~1 s) so the top-down
        #    camera settles, then look for the label.
        _hold_key(inp, birds_eye_key, BIRDS_EYE_HOLD_S, sleep)

        # 4) Locate the fire by its label, rotating the camera ("E") until found.
        fire, score, rotations = locate_fire(
            capture_rgb_fn, template=template,
            rotate_fn=lambda: _tap_key(inp, rotate_key), sleep=sleep)
        if fire is None:
            _flog('-', 'campfire.label_not_found', score=round(score, 3),
                  attempts=rotations)
            return CampfireResult('label_not_found', label_score=score,
                                  rotations=rotations)
        fire_screen = (ox + fire[0], oy + fire[1])
        _flog('0', 'campfire.fire_located', x=fire[0], y=fire[1],
              score=round(score, 3))

        # 5) Grill: drag each campfire fish from its slot onto the fire.
        grilled = []
        for (page, row, col, name) in targets:
            _switch_page(inp, calib, ox, oy, page, sleep)
            fx, fy = _slot_screen(row, col, calib, ox, oy, lattice=lattice)
            drag(inp, fx, fy, fire_screen[0], fire_screen[1], sleep=sleep)
            sleep(GRILL_SETTLE_S)
            grilled.append((page, row, col, name))
            _flog('0', 'campfire.grilled_one', name=name, page=page,
                  slot=_slot_no(row, col))

        _flog('0', 'campfire.done', count=len(grilled))
        return CampfireResult('done', grilled=grilled, fire_point=fire,
                              label_score=score, rotations=rotations)
    except Exception as exc:                # pragma: no cover - last-ditch guard
        _flog('-', 'campfire.error', detail=str(exc)[:120])
        return CampfireResult('error')


# -- input primitives (pure given an injected api) --------------------------

def drag(api, x1, y1, x2, y2, steps=12, settle=INPUT_SETTLE_S, sleep=None):
    """Press-hold-move-release drag from ``(x1,y1)`` to ``(x2,y2)``.

    Same contract as :func:`interface.refill.drag` (intermediate moves so the game
    registers a real drag, button released in a ``finally`` so a failed drag never
    crashes the loop). Kept here too so the campfire flow has no hard dependency
    on the refill module. Never raises.
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


def _double_click(api, x, y):
    """Double-click ``(x, y)`` to place/use an inventory item. Never raises.

    Prefers a real ``doubleClick``; falls back to two ``click``s, then to a
    down/up pair, so any injected api shape works.
    """
    x, y = int(x), int(y)
    try:
        if hasattr(api, 'doubleClick'):
            api.doubleClick(x=x, y=y)
        elif hasattr(api, 'click'):
            api.click(x=x, y=y)
            api.click(x=x, y=y)
        else:
            api.moveTo(x, y)
            api.mouseDown()
            api.mouseUp()
            api.mouseDown()
            api.mouseUp()
    except Exception:
        pass


def _hold_key(api, key, hold_s, sleep):
    """Press + hold ``key`` for ``hold_s`` seconds, then release. Never raises."""
    try:
        api.keyDown(key)
    except Exception:
        pass
    try:
        sleep(hold_s)
    except Exception:
        pass
    try:
        api.keyUp(key)
    except Exception:
        pass


def _tap_key(api, key):
    """Tap ``key`` (down+up). Never raises."""
    try:
        api.keyDown(key)
        api.keyUp(key)
    except Exception:
        pass


# -- coordinate helpers (reuse the inventory calibration) -------------------

def _slot_screen(row, col, calib, offset_x, offset_y, lattice=None):
    """Screen centre of inventory slot ``(row, col)`` (grid + offset).

    Same maths as :func:`interface.refill.inventory_slot_screen` so the campfire
    drag source tracks the user's own inventory calibration.

    GRID SOURCE: when a locked ``lattice`` (an :class:`inventory.grid.GridLattice`
    from :func:`inventory.grid.auto_align`) is passed, its origin/pitch are used --
    so the drag SOURCE + the campfire PARK hit the SAME grid the recognition locked
    onto (the user's window sits ~1 slot above the bundled DEFAULT_CALIBRATION, so
    the raw calib alone grabs one slot too low + misses the slot centre). With
    ``lattice=None`` it falls back to :func:`lattice_from_calibration` -- the
    historical behaviour, kept byte-identical for headless tests that pass no
    locked grid.
    """
    lat = lattice if lattice is not None else lattice_from_calibration(calib)
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


def _find_item_slot(inv, name, calib, offset_x, offset_y, lattice=None):
    """First slot holding ``name`` -> ``(page, (screen_x, screen_y))`` or ``None``.

    Page order I->IV then row-major. Pure (uses :func:`_slot_screen`); the seam
    that turns the located Lagerfeuer tool into a click point. The optional locked
    ``lattice`` is forwarded so the tool double-click lands on the SAME grid the
    fish drags do (see :func:`_slot_screen`). Never raises.
    """
    try:
        page_map = getattr(inv, 'pages', {}) or {}
        for page in PAGE_ORDER:
            for s in (page_map.get(page) or ()):
                if (getattr(s, 'state', None) == 'item'
                        and getattr(s, 'name', None) == name):
                    xy = _slot_screen(int(s.row), int(s.col), calib,
                                      offset_x, offset_y, lattice=lattice)
                    return (page, xy)
    except Exception:
        return None
    return None


def _slot_no(row, col):
    """1-based human slot index within a page (row-major). Matches the runner."""
    from inventory.constants import COLS
    return int(row) * COLS + int(col) + 1


__all__ = [
    'LABEL_TEMPLATE_PATH', 'LABEL_GLYPH_SIZE', 'LABEL_MATCH_THRESHOLD',
    'FIRE_OFFSET_FROM_LABEL_TL', 'NON_BURNABLE_NAMES', 'CAMPFIRE_ITEM_NAME',
    'PAGE_ORDER',
    'green_text_mask', 'load_label_template', 'find_label',
    'fire_point_from_label', 'campfire_fish_names', 'fish_slots_to_grill',
    'CampfireResult', 'locate_fire', 'run_campfire', 'drag',
]
