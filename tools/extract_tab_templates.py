# -*- coding: utf-8 -*-
"""Extract the four INACTIVE inventory-tab templates -> inventory_tab_templates/.

The open-state probe (:mod:`inventory.open_probe`) decides "inventory open?" by
matching a small patch around each page tab (I..IV) against its INACTIVE-state
template: one tab is always ACTIVE (highlighted, so it does NOT match), the
other three match pixel-perfectly whenever the inventory is open -- and nothing
in the 3D landscape ever matches even one (measured: closest landscape patch
MAD ~26 vs. accept threshold 8, over a 73k-placement sweep).

Because every tab can be the active one, each tab needs its OWN inactive
template. Sources (both verified live captures):

  * tab I   -- a capture with page II active (e.g. itemwegwerfmeldung.png),
  * tabs II/III/IV -- a capture with page I active (the user's calibration
    screenshot; page I is active in virtually every reference shot).

A source image is treated as a FULL-WINDOW capture (Windows titlebar included,
client offset +1/+31) when it is taller than 615 px, else as a bare CLIENT
capture -- the same two flavours every reference shot in this repo comes in.

Usage:
    python tools/extract_tab_templates.py <shot_pageII_active> <shot_pageI_active>

Writes inventory_tab_templates/tab_{I,II,III,IV}.png (RGB, 38x18 each).
"""

import os
import sys

import numpy as np
from PIL import Image

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from inventory.constants import DEFAULT_CALIBRATION  # noqa: E402
from inventory.open_probe import (  # noqa: E402
    TAB_PATCH_BOX, TEMPLATE_DIR, template_filename,
)


def _load_client(path):
    """Load ``path`` as an RGB client-area array (strip a full-window border)."""
    img = np.asarray(Image.open(path).convert('RGB'))
    if img.shape[0] > 615:  # full-window capture: 1px border + ~31px titlebar
        img = img[31:, 1:]
    return img


def _patch(img, center):
    x0, x1, y0, y1 = TAB_PATCH_BOX
    cx, cy = int(center[0]), int(center[1])
    return img[cy + y0:cy + y1, cx + x0:cx + x1]


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    src_for_i = _load_client(argv[1])      # page II active -> tab I inactive
    src_for_rest = _load_client(argv[2])   # page I active -> II/III/IV inactive
    tabs = DEFAULT_CALIBRATION['tabs']
    out_dir = os.path.join(_REPO, TEMPLATE_DIR)
    os.makedirs(out_dir, exist_ok=True)
    for label, src in (('I', src_for_i), ('II', src_for_rest),
                       ('III', src_for_rest), ('IV', src_for_rest)):
        patch = _patch(src, tabs[label])
        out = os.path.join(out_dir, template_filename(label))
        Image.fromarray(patch).save(out)
        print('wrote', out, patch.shape)
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
