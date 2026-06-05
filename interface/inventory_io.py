"""Modul-Helfer + Datei-/Console-I/O fuer den Live-Inventar-Scan.

Abgespaltene, abhaengigkeitsarme Schicht von :mod:`interface.inventory_runner`.
Buendelt die kleinen, zustandslosen Bausteine, die der ``_Runner``/
``run_inventory_scan`` nutzt: die DB-Cache-Beschaffung, die Slot-Indizierung,
die Console-/Warn-Sinks, die "ist alles unbekannt"-Heuristik und das defensive
PNG-Schreiben unbekannter Crops.

Die harten Live-Abhaengigkeiten (``cv2``/PIL/``debuglog``) werden SOFT importiert,
damit dieses Modul headless importierbar bleibt -- dieselbe Disziplin wie der
Runner. Tests monkeypatchen diese Namen ueber das RUNNER-Modul (``ir.cv2`` /
``ir._save_bgr_png`` / ``ir._warn``); der Runner re-importiert sie in seinen
Namespace, sodass solche Patches weiterhin greifen.
"""

import os
import sys

from inventory.constants import COLS
from i18n import t

# -- soft imports (live deps; module stays importable headless) -------------
try:  # pragma: no cover
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

try:  # pragma: no cover
    from PIL import Image as _Image
except Exception:  # pragma: no cover
    _Image = None

try:  # pragma: no cover - reiner Fallback
    from debuglog import log
except Exception:  # pragma: no cover
    log = None


# -- module-level ItemDB cache (build the references ONCE, reuse every scan) -
_DB_CACHE = None


def _unknown_crop_dir():
    """Writable, EXE-relative dir for best-effort unknown-item crops.

    Anchored NEXT TO the EXE (frozen) / the repo root (dev) -- NOT cwd-relative.
    In the packaged portable EXE the process cwd is not guaranteed (a foreign
    launcher cwd, or a read-only dir), so a bare ``build/...`` could silently fail
    or land where the user can't find it. This mirrors ``trained_solver._cache_path``
    and the config-next-to-EXE convention so the saved crops sit beside config.json.
    """
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        # interface/ -> repo root.
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, 'inventory_unknowns')


def _get_db():
    """Return the cached bundled :class:`~inventory.itemdb.ItemDB` (build once)."""
    global _DB_CACHE
    if _DB_CACHE is None:
        from inventory.itemdb import ItemDB
        _DB_CACHE = ItemDB.from_bundled()
    return _DB_CACHE


def _slot_no(row, col):
    """1-based human slot index within a page (row-major): ``row*COLS+col+1``."""
    return int(row) * COLS + int(col) + 1


def _default_log_fn(line):
    """Default Console sink: a plain State-'-' event line (best-effort)."""
    if log is None:
        return
    try:
        log.event('-', line)
    except Exception:
        pass


def _warn(key, **fmt):
    """Emit a translated WARNING to the Console/log (best-effort)."""
    if log is None:
        return
    try:
        log.warning(t(key, **fmt))
    except Exception:
        pass


def _save_bgr_png(crop_bgr, path):
    """Write a BGR uint8 crop to ``path`` via cv2 (or PIL fallback). Soft.

    Creates the parent directory on demand (only when an actual write happens),
    so a no-op/stubbed writer leaves NOTHING on disk.
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if cv2 is not None:
            return bool(cv2.imwrite(path, crop_bgr))
        if _Image is not None:
            rgb = crop_bgr[:, :, ::-1]
            _Image.fromarray(rgb.astype('uint8'), 'RGB').save(path)
            return True
    except Exception:
        return False
    return False


# A scan is treated as "inventory not open" (the hotkey toggled it shut) only
# when it found ZERO recognised items AND unknowns fill at least this FRACTION
# of the scanned slots. Rationale: a closed inventory shows the game world behind
# the panel, so the grid reads as a dense field of un-recognisable noise (mostly
# unknown). A genuinely-open but SPARSE inventory (a few items, a few unknowns,
# many empties) has a LOW unknown fraction and must NOT trip this. The threshold
# sits well above any plausible real unknown fraction yet below the near-total
# noise of a closed panel.
NOT_OPEN_UNKNOWN_FRACTION = 0.6


def _is_all_unknown(inv_map):
    """True iff the scan looks like a TOGGLED-SHUT inventory (game world behind).

    Detected when not a single page yields a confident item AND unknowns fill at
    least :data:`NOT_OPEN_UNKNOWN_FRACTION` of the scanned slots. A real but
    sparse open inventory (few items / few unknowns / many empties) has a low
    unknown fraction and is NOT flagged; an empty scan with no pages is.
    """
    if not inv_map.pages:
        return True
    if inv_map.items():
        return False
    total = sum(len(results) for results in inv_map.pages.values())
    if total <= 0:
        return True
    return (len(inv_map.unknowns()) / float(total)) >= NOT_OPEN_UNKNOWN_FRACTION


def _emit_line(sink, line):
    """Push one line to the Console sink, swallowing sink errors."""
    try:
        sink(line)
    except Exception:
        pass
