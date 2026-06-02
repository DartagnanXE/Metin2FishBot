"""Discover and load the bundled item icons (the recognition database).

Icons live flat in ``inventory_icons/`` (one PNG per item; the file's basename
is the item name). They are loaded via :func:`respath.resource_path` so the
engine works both from source and from the PyInstaller --onefile EXE -- exactly
like ``cv.imread(resource_path('images/...'))`` in :mod:`fishingbot`.

PIL is SOFT-imported (mirrors the numpy/cv2 soft imports in :mod:`detection`):
the module stays importable and ``py_compile``-able headless even when PIL is
missing; loaders then return ``None`` and the engine degrades + logs rather
than raising. Tests force the fallback by setting ``assets._Image = None``.

Image convention: :func:`load_icon_rgba` returns an ``(H, W, 4)`` uint8 array
in RGBA order (PIL's native order for ``mode='RGBA'``). The one 32x34 icon
(Gold_Ring) is normalised to 32x32 by :func:`normalize_to_slot`.
"""

import os

from respath import resource_path
from i18n import t
from .constants import SLOT_PX

# Logging weich einbinden -- ein fehlender/kaputter Logger darf das Laden nie
# stoppen (gleiche Disziplin wie windowcapture/detection).
try:  # pragma: no cover - reiner Fallback
    from debuglog import log
except Exception:  # pragma: no cover
    log = None

# numpy/PIL weich einbinden: ohne sie kann nicht geladen werden, aber das Modul
# bleibt importierbar und meldet sauber statt zu werfen.
try:  # pragma: no cover - exercised on machines with numpy
    import numpy as np
except Exception:  # pragma: no cover
    np = None

try:  # pragma: no cover - exercised on machines with PIL
    from PIL import Image as _Image
except Exception:  # pragma: no cover
    _Image = None


# Bundled icon directory (relative; resolved via resource_path). Listed in both
# .spec datas as ('inventory_icons', 'inventory_icons').
ICON_DIR = 'inventory_icons'


def _log(key, **fmt):
    """Log a translated event line (State 0); swallows logger errors.

    ``fmt`` is substituted into the i18n string via :func:`i18n.t` (matching
    :mod:`detection`), so message placeholders like ``{path}`` are filled.
    """
    if log is None:
        return
    try:
        log.event(0, t(key, **fmt))
    except Exception:
        pass


def name_from_path(path):
    """Item name = file basename without extension (e.g. 'Worm.png' -> 'Worm')."""
    return os.path.splitext(os.path.basename(path))[0]


def _icon_dir():
    """Resolve the bundled-icon directory, cwd-independently.

    Prefers :func:`resource_path` (the packed --onefile EXE unpacks the icons
    under ``sys._MEIPASS``). In SOURCE / --onedir mode ``resource_path`` returns
    the bare relative string ``'inventory_icons'``, which would make
    :func:`os.listdir` depend on the process cwd (a foreign launcher cwd yields
    an EMPTY DB). So if the resolved path is not an existing directory, fall
    back to ``<repo-root>/inventory_icons`` derived from THIS file's location
    (``inventory/assets.py`` -> repo root is one level up), which is stable
    regardless of cwd.
    """
    base = resource_path(ICON_DIR)
    if os.path.isdir(base):
        return base
    here = os.path.dirname(os.path.abspath(__file__))
    fallback = os.path.join(os.path.dirname(here), ICON_DIR)
    return fallback if os.path.isdir(fallback) else base


def icon_paths():
    """List resolved paths to every bundled icon PNG, sorted by name.

    Resolves the bundled directory via :func:`_icon_dir` (works from the packed
    EXE AND from a source/--onedir run regardless of cwd). Returns ``[]``
    (logged) when the directory is absent or unreadable -- the engine then has
    an empty DB and reports every slot unknown, but never raises.
    """
    base = _icon_dir()
    try:
        entries = sorted(os.listdir(base))
    except Exception as exc:
        _log('inventory.icons_dir_missing', path=base, detail=str(exc)[:120])
        return []
    paths = [os.path.join(base, name) for name in entries
             if name.lower().endswith('.png')]
    if not paths:
        _log('inventory.icons_dir_empty', path=base)
    return paths


def load_icon_rgba(path):
    """Load a PNG as an ``(H, W, 4)`` uint8 RGBA array, or ``None`` on failure.

    Soft-imports PIL/numpy; if either is missing the load is impossible -> log
    + ``None`` (the caller degrades). Any decode error is caught the same way.
    """
    if _Image is None or np is None:
        _log('inventory.icon_load_no_pil', path=path)
        return None
    try:
        with _Image.open(path) as img:
            rgba = img.convert('RGBA')
            arr = np.asarray(rgba, dtype=np.uint8)
        if arr.ndim != 3 or arr.shape[2] != 4:
            _log('inventory.icon_bad_shape', path=path,
                 shape=str(getattr(arr, 'shape', None)))
            return None
        return arr
    except Exception as exc:
        _log('inventory.icon_load_failed', path=path, detail=str(exc)[:120])
        return None


def normalize_to_slot(rgba):
    """Centre-crop / pad any ``(H, W, 4)`` icon to ``(SLOT_PX, SLOT_PX, 4)``.

    Handles the one 32x34 icon (Gold_Ring) by dropping the extra rows
    symmetrically; smaller icons are zero-padded (transparent) symmetrically.
    Width is normalised the same way. Returns ``None`` if numpy is missing or
    the input is not a 3-D RGBA array.
    """
    if np is None:
        return None
    if rgba is None or getattr(rgba, 'ndim', 0) != 3 or rgba.shape[2] != 4:
        return None
    h, w = rgba.shape[0], rgba.shape[1]
    if h == SLOT_PX and w == SLOT_PX:
        return rgba
    out = np.zeros((SLOT_PX, SLOT_PX, 4), dtype=rgba.dtype)
    # Source crop window (centre) and destination paste window (centre).
    sy, dy, copy_h = _center_span(h, SLOT_PX)
    sx, dx, copy_w = _center_span(w, SLOT_PX)
    out[dy:dy + copy_h, dx:dx + copy_w, :] = \
        rgba[sy:sy + copy_h, sx:sx + copy_w, :]
    return out


def _center_span(src_len, dst_len):
    """Return ``(src_start, dst_start, copy_len)`` to centre-align two lengths.

    If ``src_len > dst_len`` we crop the centre of the source; if smaller we
    paste into the centre of the destination. Symmetric (extra odd pixel goes
    to the lower index, matching the "drop the extra rows symmetrically" spec).
    """
    copy_len = min(src_len, dst_len)
    src_start = (src_len - copy_len) // 2
    dst_start = (dst_len - copy_len) // 2
    return src_start, dst_start, copy_len
