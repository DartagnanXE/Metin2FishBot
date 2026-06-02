"""One-shot dev/build script: populate the bundled inventory-icon database.

Copies every PNG from the source icon folders (``KeyItems/`` + ``FangBilder/``)
into ``Metin2FishBot/inventory_icons/`` and normalises the one 32x34 icon
(Gold_Ring) to 32x32 so the engine can load each as a clean 32x32 RGBA slot via
``resource_path('inventory_icons/<name>.png')``. The .spec ``datas`` then ship
the folder in the build.

NOT a runtime path -- run once at integration::

    py.exe tools/build_icons.py [SRC_DIR ...] [-- DST]

Idempotent: re-running simply re-copies (overwrites) and re-reports the count.
PIL is required (only used at build time, never in the headless engine path).
"""

import os
import sys

try:
    from PIL import Image
except Exception:  # pragma: no cover - build-time only
    Image = None


SLOT_PX = 32

# Source folders, relative to the repo's PARENT (the icons live in the download
# folder next to the repo, per the project layout).
DEFAULT_SOURCES = (
    os.path.join('..', 'KeyItems'),
    os.path.join('..', 'FangBilder'),
)
DEFAULT_DST = 'inventory_icons'


def _repo_root():
    """Absolute path to the Metin2FishBot repo root (parent of tools/)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def collect_sources(sources=DEFAULT_SOURCES):
    """Resolve source folders (relative to the repo root) to existing dirs."""
    root = _repo_root()
    out = []
    for src in sources:
        path = src if os.path.isabs(src) else os.path.normpath(
            os.path.join(root, src))
        if os.path.isdir(path):
            out.append(path)
        else:
            print('skip (not a dir): {}'.format(path))
    return out


def _normalize_to_slot(img):
    """Centre-crop/pad a PIL RGBA image to SLOT_PX x SLOT_PX."""
    img = img.convert('RGBA')
    if img.size == (SLOT_PX, SLOT_PX):
        return img
    canvas = Image.new('RGBA', (SLOT_PX, SLOT_PX), (0, 0, 0, 0))
    w, h = img.size
    # Crop the centre if larger; the paste offset centres a smaller icon.
    left = max(0, (w - SLOT_PX) // 2)
    top = max(0, (h - SLOT_PX) // 2)
    right = left + min(w, SLOT_PX)
    bottom = top + min(h, SLOT_PX)
    cropped = img.crop((left, top, right, bottom))
    cw, ch = cropped.size
    canvas.paste(cropped, ((SLOT_PX - cw) // 2, (SLOT_PX - ch) // 2))
    return canvas


def copy_and_normalize(src, dst_dir):
    """Copy + normalise every PNG in ``src`` into ``dst_dir``. Returns count."""
    count = 0
    for name in sorted(os.listdir(src)):
        if not name.lower().endswith('.png'):
            continue
        src_path = os.path.join(src, name)
        dst_path = os.path.join(dst_dir, name)
        try:
            with Image.open(src_path) as img:
                normalized = _normalize_to_slot(img)
                normalized.save(dst_path)
            count += 1
        except Exception as exc:  # pragma: no cover - build-time robustness
            print('failed: {} ({})'.format(src_path, exc))
    return count


def main(argv=None):
    if Image is None:
        print('PIL (Pillow) is required to build icons. pip install Pillow')
        return 1
    argv = list(sys.argv[1:] if argv is None else argv)
    dst = DEFAULT_DST
    if '--' in argv:
        idx = argv.index('--')
        dst = argv[idx + 1] if idx + 1 < len(argv) else DEFAULT_DST
        argv = argv[:idx]
    sources = argv if argv else list(DEFAULT_SOURCES)

    root = _repo_root()
    dst_dir = dst if os.path.isabs(dst) else os.path.join(root, dst)
    os.makedirs(dst_dir, exist_ok=True)

    total = 0
    for src in collect_sources(sources):
        n = copy_and_normalize(src, dst_dir)
        print('copied {} icon(s) from {}'.format(n, src))
        total += n
    print('done: {} icon(s) in {}'.format(total, dst_dir))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
