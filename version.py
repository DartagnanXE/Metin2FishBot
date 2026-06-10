# -*- coding: utf-8 -*-
"""Single source of truth for the application version.

Imported by:
  * updater.py        -> compares this against the latest GitHub release tag
  * Metin2FishBot.spec / Metin2FishBot_onefile.spec -> PE version resource
  * interface/app.py  -> startup update check

Keep this file dependency-free (stdlib only, no imports) so the PyInstaller
spec can import it during the build without pulling in the GUI stack, and so
``config``/``debuglog``-style headless tests can import it freely.
"""

__version__ = '1.2.1'


def version_tuple(text=__version__):
    """Parse a dotted version string into an int-tuple for comparison.

    Strips a leading 'v'/'V' and any pre-release/build suffix after the
    numeric core (e.g. ``'v1.0.4-beta'`` -> ``(1, 0, 4)``). Non-numeric trailing
    parts are ignored. Never raises -> returns ``(0,)`` on total garbage so
    comparisons are always safe.
    """
    try:
        core = str(text).strip().lstrip('vV')
        # Cut at the first char that is neither a digit nor a dot (handles
        # '-beta', '+build', ' (rc1)' and similar suffixes).
        cleaned = []
        for ch in core:
            if ch.isdigit() or ch == '.':
                cleaned.append(ch)
            else:
                break
        parts = [int(p) for p in ''.join(cleaned).split('.') if p != '']
        return tuple(parts) if parts else (0,)
    except Exception:
        return (0,)
