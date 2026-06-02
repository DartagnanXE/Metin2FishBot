"""Reine Such-/Logging-Primitive fuer das Angeln (ohne FishingBot-Zustand).

Abgespaltene, zustandslose Bausteine von :mod:`fishingbot`:

  * :func:`_flog`              -- defensiver Angel-Event-Log-Shim (debuglog).
  * :func:`_match_template_max` -- robustes ``cv2.matchTemplate`` -> (ok, val, loc).

Bewusst freistehend (kein ``self``), damit der FishingBot-Hauptzustand schlank
bleibt und diese Bausteine isoliert testbar sind. ``debuglog`` wird wie im
restlichen Projekt defensiv (soft) importiert -> der Bot laeuft auch ohne weiter.
"""

import numpy as np
import cv2 as cv
from i18n import t

# Diagnose-Logging (stdlib-only, defensiv) -- macht das Angeln in der Live-
# Console sichtbar. Schlaegt der Import fehl, laeuft der Bot unveraendert weiter.
try:
    from debuglog import log
except Exception:  # pragma: no cover
    log = None


def _flog(state, message, **fields):
    """Loggt ein Angel-Event (falls debuglog verfuegbar). Wirft nie."""
    if log is None:
        return
    try:
        log.event(state, message, **fields)
    except Exception:
        pass


def _match_template_max(haystack, needle):
    """Robustes matchTemplate -> (ok, max_val, max_loc).

    Bringt das Suchbild defensiv auf den Vorlagen-Typ (kontiguierlich, gleiche
    Kanalzahl, Vorlage <= Bild) und faengt JEDEN cv2-Fehler ab -> ok=False statt
    Absturz. So kann ein abweichendes Capture (Form/Typ/DPI-Skalierung) Fishing
    nicht mehr crashen; es wird sauber als 'nicht erkannt' behandelt + geloggt.
    """
    try:
        if haystack is None or needle is None:
            return (False, 0.0, (0, 0))
        img = np.ascontiguousarray(haystack)
        if img.ndim == 2:
            img = cv.cvtColor(img, cv.COLOR_GRAY2BGR)
        elif img.ndim == 3 and img.shape[2] == 4:
            img = cv.cvtColor(img, cv.COLOR_BGRA2BGR)
        if (img.ndim != 3 or needle.ndim != 3
                or img.shape[2] != needle.shape[2]
                or needle.shape[0] > img.shape[0]
                or needle.shape[1] > img.shape[1]):
            _flog('-', t('fishing.match_skipped'),
                  img=str(getattr(img, 'shape', None)),
                  tmpl=str(getattr(needle, 'shape', None)))
            return (False, 0.0, (0, 0))
        result = cv.matchTemplate(img, needle, cv.TM_CCOEFF_NORMED)
        _minv, maxv, _minl, maxl = cv.minMaxLoc(result)
        return (True, float(maxv), maxl)
    except Exception as exc:
        _flog('-', t('fishing.match_error'), detail=str(exc)[:90])
        return (False, 0.0, (0, 0))


__all__ = ['_flog', '_match_template_max']
