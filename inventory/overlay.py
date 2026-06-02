"""Human-review overlay: draw slot boxes + labels on a captured page.

Used by the real-screenshot smoke test to emit a labelled PNG a human can eye.
Each slot box is drawn and labelled with the item name + distance/margin (or
EMPTY / UNKNOWN). cv2 is the preferred renderer, PIL the fallback; both are
SOFT-imported and every entry point swallows errors and returns ``False``
rather than raising (a failed overlay must never break a scan or a test).
"""

from .types import STATE_EMPTY, STATE_ITEM, STATE_UNKNOWN

try:  # pragma: no cover - exercised on machines with numpy
    import numpy as np
except Exception:  # pragma: no cover
    np = None

try:  # pragma: no cover
    import cv2 as cv
except Exception:  # pragma: no cover
    cv = None

try:  # pragma: no cover
    from PIL import Image as _Image, ImageDraw as _ImageDraw
except Exception:  # pragma: no cover
    _Image = None
    _ImageDraw = None


# BGR colours per state (cv2 draws in BGR; the PIL path converts).
_COLORS_BGR = {
    STATE_ITEM: (60, 200, 60),       # green
    STATE_UNKNOWN: (60, 60, 220),    # red
    STATE_EMPTY: (120, 120, 120),    # grey
}


def _label_for(result):
    """Short overlay label for a slot result."""
    if result.state == STATE_ITEM:
        return '{} d{:.0f} m{:.0f}'.format(result.name or '?',
                                           result.distance, result.margin)
    if result.state == STATE_UNKNOWN:
        return '?'
    return ''


def render_overlay(image_bgr, results, lattice):
    """Return a COPY of ``image_bgr`` with slot boxes + labels drawn (BGR).

    Returns ``None`` if numpy/cv2 are missing or the inputs are unusable (the
    caller treats that as "no overlay"). Never mutates the input image.
    """
    if np is None or cv is None or image_bgr is None:
        return None
    try:
        canvas = np.ascontiguousarray(np.asarray(image_bgr)).copy()
        for r in results:
            x, y, w, h = lattice.slot_box(r.row, r.col)
            color = _COLORS_BGR.get(r.state, (200, 200, 200))
            cv.rectangle(canvas, (x, y), (x + w, y + h), color, 1)
            label = _label_for(r)
            if label:
                cv.putText(canvas, label, (x + 1, y + h - 2),
                           cv.FONT_HERSHEY_PLAIN, 0.5, color, 1, cv.LINE_AA)
        return canvas
    except Exception:
        return None


def save_overlay(path, image_bgr, results, lattice):
    """Render + write a labelled overlay PNG. Returns True on success.

    Tries cv2 first (BGR write), then PIL (RGB). Never raises -- any failure
    (missing deps, bad path) returns ``False``.
    """
    canvas = render_overlay(image_bgr, results, lattice)
    if canvas is not None and cv is not None:
        try:
            return bool(cv.imwrite(path, canvas))
        except Exception:
            pass
    # PIL fallback: draw directly in RGB.
    if np is not None and _Image is not None and _ImageDraw is not None \
            and image_bgr is not None:
        try:
            rgb = np.ascontiguousarray(np.asarray(image_bgr)[:, :, ::-1])
            img = _Image.fromarray(rgb.astype('uint8'), 'RGB')
            draw = _ImageDraw.Draw(img)
            for r in results:
                x, y, w, h = lattice.slot_box(r.row, r.col)
                bgr = _COLORS_BGR.get(r.state, (200, 200, 200))
                rgb_color = (bgr[2], bgr[1], bgr[0])
                draw.rectangle([x, y, x + w, y + h], outline=rgb_color)
                label = _label_for(r)
                if label:
                    draw.text((x + 1, y + 1), label, fill=rgb_color)
            img.save(path)
            return True
        except Exception:
            return False
    return False
