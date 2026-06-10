"""Open-state probe: IS the inventory open? (template match on the page tabs).

THE PROBLEM THIS SOLVES: the inventory hotkey is a TOGGLE. Every live flow
(scan, grill, discard) used to press it blindly -- if the bag was ALREADY open
(very common: the scan deliberately leaves it open) the press CLOSED it, and
every subsequent "click the page tab" landed in the 3D WORLD instead, making
the character walk off ("Bot laeuft los"). The probe answers open/closed
BEFORE anything is pressed or clicked, so the flows only toggle when needed
and ABORT (instead of clicking the landscape) when the bag cannot be verified
open.

HOW: around each of the four page tabs (I..IV, fixed calibration positions --
the same anchor :func:`inventory.grid.active_page` samples) a small patch is
matched against that tab's bundled INACTIVE-state template
(``inventory_tab_templates/tab_*.png``). Exactly one tab is always ACTIVE
(highlighted ~110 brightness units above the others, so it never matches its
inactive template); the other three match near-pixel-perfectly whenever the
inventory is open. Measured on the real captures:

  * open, inactive tab vs its template: MAD 0.0..0.6 (with +-shift search),
  * open, ACTIVE tab vs the inactive template: MAD ~39..53,
  * closed (landscape/dialog shots): MAD 26..69 on EVERY tab; a 73k-placement
    adversarial sweep over the landscape found ZERO spots where even three
    patches match (closest single patch: 26.2).

So "at least 3 of 4 tabs match" separates open from closed with a huge margin
in both directions, independent of WHICH page is active. The accept threshold
(8) sits between 0.6 and 26.2.

Headless-soft like the rest of the engine: numpy/PIL are soft imports, every
public function degrades to a clear "probe unavailable" (``None``) instead of
raising, and the pure decision logic is fully unit-testable on synthetic
canvases.
"""

import os
import time

from .constants import OPEN_SETTLE_S

try:  # pragma: no cover - import guard mirrors inventory.assets
    import numpy as np
except Exception:  # pragma: no cover
    np = None

try:  # pragma: no cover
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None


# -- geometry / decision constants ------------------------------------------

#: Patch box around a tab centre, as (x0, x1, y0, y1) offsets: the 38x18 px
#: region covering the tab button face incl. its roman numeral. Chosen so the
#: existing ``tab_active.offset`` sample point lies inside it.
TAB_PATCH_BOX = (-14, 24, -5, 13)

#: Dense +-px shift search when matching a patch against its template; absorbs
#: the measured per-session client offset (+-1 px between the reference shots,
#: e.g. an 800x600 vs 801x602 client).
TAB_SHIFT_RADIUS = 3

#: Accept threshold for "this tab matches its INACTIVE template" (mean abs diff
#: over the RGB patch, 0..255). Real inactive tabs measure <= 0.6, the active
#: tab >= 39, the closest landscape patch ever found 26.2 -- 8 sits in the gap
#: with a wide margin both ways.
TAB_MATCH_MAD_MAX = 8.0

#: The inventory counts as OPEN when at least this many of the 4 tabs match
#: their inactive template (one is always active -> 3 is the open maximum; a
#: tooltip/cursor overlapping one more tab can drop a true open to 2, which is
#: handled by the press-retry loop in :func:`ensure_inventory_open`, never by
#: loosening this bound -- below 3 the landscape false-open guarantee is gone).
OPEN_MIN_MATCHES = 3

#: Bundled template directory + filenames (added to both .spec data lists).
TEMPLATE_DIR = 'inventory_tab_templates'

#: How often :func:`ensure_inventory_open` may press the toggle before giving
#: up. 2 covers the self-healing case "a tooltip made an OPEN bag look closed":
#: press 1 closes it (probe now cleanly closed), press 2 re-opens it (probe now
#: cleanly open).
MAX_TOGGLE_PRESSES = 2


def template_filename(label):
    """Bundled template filename for tab ``label`` (e.g. ``tab_I.png``)."""
    return 'tab_{}.png'.format(label)


_templates_cache = None


def load_tab_templates():
    """Load the four bundled inactive-tab templates as BGR float arrays.

    Returns ``{label: (h, w, 3) float32 BGR}`` -- BGR so a patch cut straight
    from a captured frame (the engine-wide BGR convention) compares without a
    per-probe conversion. Cached after the first successful load. ``None`` when
    numpy/PIL is missing or any template file is unreadable (headless dev
    boxes); callers treat that as "probe unavailable", never as open/closed.
    """
    global _templates_cache
    if _templates_cache is not None:
        return _templates_cache
    if np is None or Image is None:
        return None
    try:
        from respath import resource_path
    except Exception:  # pragma: no cover - respath is a tiny pure module
        return None
    out = {}
    try:
        from .constants import PAGES
        for label in PAGES:
            path = resource_path(
                os.path.join(TEMPLATE_DIR, template_filename(label)))
            with Image.open(path) as img:
                rgb = np.asarray(img.convert('RGB'), dtype=np.float32)
            out[label] = rgb[:, :, ::-1].copy()  # store as BGR
    except Exception:
        return None
    _templates_cache = out
    return out


def _best_mad(image, template, cx, cy, radius=TAB_SHIFT_RADIUS):
    """Lowest mean-abs-diff of ``template`` around ``(cx, cy)`` (+-radius).

    255.0 (worst) when every candidate patch is off-image / wrong shape.
    """
    x0, x1, y0, y1 = TAB_PATCH_BOX
    h, w = image.shape[0], image.shape[1]
    best = 255.0
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            ax0, ax1 = cx + x0 + dx, cx + x1 + dx
            ay0, ay1 = cy + y0 + dy, cy + y1 + dy
            if ax0 < 0 or ay0 < 0 or ax1 > w or ay1 > h:
                continue
            patch = np.asarray(image[ay0:ay1, ax0:ax1, :3], dtype=np.float32)
            if patch.shape != template.shape:
                continue
            mad = float(np.abs(patch - template).mean())
            if mad < best:
                best = mad
    return best


def probe_open(image_bgr, calib, templates=None):
    """Decide whether the inventory is open in ``image_bgr``.

    :param image_bgr: a captured client frame (BGR, the engine convention).
    :param calib: the calibration dict (uses ``calib['tabs']``).
    :param templates: preloaded :func:`load_tab_templates` result (optional).
    :return: ``(is_open, matches, dists)`` where ``dists`` maps each tab label
        to its best template MAD -- or ``None`` when the probe is unavailable
        (numpy/PIL/templates missing, or no/empty frame). ``None`` means
        "cannot tell", deliberately distinct from a confident ``False``.
    """
    if np is None or image_bgr is None:
        return None
    templates = templates or load_tab_templates()
    if not templates:
        return None
    img = np.asarray(image_bgr)
    if img.ndim != 3 or img.shape[2] < 3:
        return None
    tabs = (calib or {}).get('tabs', {})
    dists = {}
    for label, template in templates.items():
        center = tabs.get(label)
        if not center:
            return None
        dists[label] = _best_mad(img, template, int(center[0]), int(center[1]))
    matches = sum(1 for d in dists.values() if d <= TAB_MATCH_MAD_MAX)
    return (matches >= OPEN_MIN_MATCHES, matches, dists)


def ensure_inventory_open(capture_fn, press_fn, calib, *,
                          park_fn=None,
                          settle_s=OPEN_SETTLE_S,
                          max_presses=MAX_TOGGLE_PRESSES,
                          sleep_fn=time.sleep):
    """Probe-then-toggle until the inventory is verifiably open.

    The ONE shared open-state flow for scan / grill / discard: probe first and
    press the (toggle!) hotkey ONLY when the bag is closed, re-probing after
    every press. Self-heals the rare ambiguous probe (e.g. a tooltip overlaps a
    tab and a true OPEN reads closed): the first press closes the bag (next
    probe is cleanly closed), the second re-opens it (probe cleanly open).

    :param capture_fn: ``() -> BGR frame | None`` (a fresh capture per probe).
    :param press_fn: ``() -> None`` -- ONE tap of the inventory hotkey.
    :param park_fn: optional ``() -> None`` cursor park executed before every
        capture, so the hardware cursor / a tab tooltip cannot sit on the tab
        row and distort the probe.
    :return: ``True`` (verified open), ``False`` (still closed after
        ``max_presses`` -- caller must ABORT its click flow), or ``None`` when
        the probe is unavailable (caller falls back to the historical blind
        single press; only reachable headless, the live EXE bundles the
        templates).
    """
    for attempt in range(max_presses + 1):
        if park_fn is not None:
            try:
                park_fn()
            except Exception:
                pass
        result = probe_open(capture_fn(), calib)
        if result is None:
            return None
        if result[0]:
            return True
        if attempt < max_presses:
            press_fn()
            sleep_fn(settle_s)
    return False
