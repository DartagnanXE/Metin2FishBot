# -*- coding: utf-8 -*-
"""Shared module-level surface for the ``interface.app`` package.

Holds the imports, constants and pure helper functions that USED to live at the
top of the old single-file ``interface/app.py``. Both the orchestrator
(:mod:`interface.app`) and every mixin module star-import from here, so each
method body resolves module-level names (``ctk``, ``t``, ``log``, the colour
constants, ``RAIL_ORDER``, ``_probe_game`` ...) exactly as it did when all the
code shared one module namespace -- which is what keeps the split
behaviour-preserving.

``__all__`` explicitly lists the underscore helpers/constants so ``import *``
re-exports them (they are part of the public ``interface.app`` surface that the
GUI-smoke and characterization tests import).
"""

import copy
import os
import threading
import time

import customtkinter as ctk

from debuglog import log
from i18n import get_lang, set_lang, t
from interface import config as cfgmod
from interface import tray
from interface.log_panel import LogPanel
from interface.widgets import (AMBER, BG, DANGER, DANGER_HOVER, DANGER_SOFT,
                               INK, LIVE_GREEN, PANEL, PANEL_DARK, PANEL_HOVER,
                               PANEL_LIGHT, RAIL_BG, RAIL_HOVER, STRIP_BG, TEAL,
                               TEAL_BRIGHT, TEAL_DARK, TEAL_HOVER, TEAL_SOFT,
                               TEXT, TEXT_FAINT, TEXT_MUTED, InfoBadge,
                               LabeledSlider, Section, Segmented, SegmentedRow,
                               Tooltip)
from respath import resource_path

ICON_FILE = 'musketier.ico'
REFERENCE_IMAGE = 'images/calibration_reference.png'
# Etwas groesseres Referenzbild im Detection-"?" (passt zur 320px-Referenz des
# Mark-Overlays) -- macht die 24 Raster- + 4 Sonderpunkte besser lesbar.
REFERENCE_IMAGE_SIZE = (320, 209)

# Puzzle-Methode: config-Werte ('standard'/'trained') <-> Uebersetzungs-Keys.
# Die ANZEIGE-Labels sind sprachabhaengig -> werden LIVE pro Aufbau via
# _solver_pairs() uebersetzt (KEINE eingefrorene Modul-Konstante -- sonst wuerde
# ein Sprachwechsel die Labels nicht aktualisieren).
SOLVER_MODE_KEYS = (('standard', 'ui.solver_label_default'),
                    ('trained', 'ui.solver_label_trained'))

# Detection-Modus: config-Werte ('default'/'auto'/'mark') <-> Uebersetzungs-Keys.
# Der INTERNE Enum-Wert bleibt 'mark' (kein config/Test-Churn); NUR das angezeigte
# Label wechselt ('Manual'/'Manuell'). Wie bei der Puzzle-Methode werden die
# Labels LIVE pro Aufbau via _detection_pairs() uebersetzt (Sprachwechsel-fest).
DETECTION_MODE_KEYS = (('default', 'ui.detection_label_default'),
                       ('auto', 'ui.detection_label_auto'),
                       ('mark', 'ui.detection_label_manual'))

# Glyphen der Rail-Items (Unicode, keine neuen Assets). Faellt eine Emoji-Glyphe
# auf der Zielschrift schlecht, ist das fuer ein Laien-Tool akzeptabel.
RAIL_GLYPHS = {
    'fishing': '\U0001F3A3',   # Angel
    'puzzle': '\U0001F9E9',    # Puzzleteil
    'console': '>_',
    'inventory': '\U0001F392',  # Rucksack (Inventar-Scan)
    'ranking': '\U0001F3C6',   # Pokal (Rangliste/Stats/Events)
    'roadmap': '\U0001F5FA',   # Landkarte (geplante Features)
    'settings': '⚙',      # Zahnrad
}
# Reihenfolge in der Rail: Fishing, Puzzle, Console, Inventory, Ranking,
# Roadmap, [Spacer], Settings.
RAIL_ORDER = ('fishing', 'puzzle', 'console', 'inventory', 'ranking',
              'roadmap', 'settings')

# Key-Capture: which -> (config-section, config-key). Macht den Tasten-Aufnahme-
# Fluss generisch; bait/cast verhalten sich byte-identisch wie zuvor, der
# Inventar-Hotkey + die Mount-Taste haengen sich ueber denselben Pfad ein.
WHICH_TO_CFG = {
    'bait': ('fishing', 'bait_key'),
    'cast': ('fishing', 'cast_key'),
    'inventory': ('inventory', 'hotkey'),
    'mount': ('fishing', 'mount_key'),
}


def _solver_pairs():
    """Aktuelle (value, label)-Paare der Puzzle-Methode (live uebersetzt)."""
    return tuple((value, t(key)) for value, key in SOLVER_MODE_KEYS)


def _detection_pairs():
    """Aktuelle (value, label)-Paare des Detection-Modus (live uebersetzt)."""
    return tuple((value, t(key)) for value, key in DETECTION_MODE_KEYS)


def _pad2(number):
    return '{:02d}'.format(int(number))


def _hms(total_seconds):
    """Sekunden -> 'HH:MM:SS' (geklemmt auf >= 0)."""
    total = max(0, int(total_seconds))
    return (_pad2(total // 3600) + ':' + _pad2((total % 3600) // 60)
            + ':' + _pad2(total % 60))


def _is_no_window_error(exc):
    """True, wenn ``exc`` ein 'Metin2-Fenster nicht gefunden' ist.

    Spiegelt die Erkennung im Start-Pfad (Controller.on_start_stop) exakt:
    ``WindowCapture`` wirft denselben Text, ob beim Start oder beim Scan."""
    msg = str(exc)
    return ('nicht gefunden' in msg or 'not found' in msg.lower())


def _mmss(total_seconds):
    """Sekunden -> 'MM:SS' (geklemmt auf >= 0)."""
    total = max(0, int(total_seconds))
    return _pad2(total // 60) + ':' + _pad2(total % 60)


# Toleranz fuer den 800x600-Client-Groessen-Check (Item M). Kleine Abweichungen
# (Theme/DPI/Rundung) sollen NICHT als "falsche Groesse" gelten.
GAME_SIZE_TOLERANCE = 8
TARGET_CLIENT_W = 800
TARGET_CLIENT_H = 600


def _probe_game():
    """Sondiert das Spiel-Fenster -> ``(present, hwnd, w, h, healthy)`` (Item M).

    ``present``  -- Fenster ``constants.GAME_NAME`` da + sichtbar (wie der Bot
                    es per ``FindWindow`` findet).
    ``hwnd``     -- dessen Handle (oder ``None``).
    ``w, h``     -- WAHRE Client-Groesse (``GetClientRect``) oder ``(0, 0)``.
    ``healthy``  -- present UND Client ~800x600 (Toleranz ``GAME_SIZE_TOLERANCE``).

    Rein passiver Win32-Read von Fenster-Metadaten -- KEIN Prozessspeicher (kein
    Anti-Cheat-Trigger). Wirft nie (headless / fehlendes win32 -> alles leer)."""
    try:
        import constants
        import win32gui

        import windowcapture
        hwnd = win32gui.FindWindow(None, constants.GAME_NAME)
        if not hwnd or not win32gui.IsWindowVisible(hwnd):
            return (False, None, 0, 0, False)
        size = windowcapture.client_size(hwnd)
        w, h = size if size else (0, 0)
        healthy = (size is not None
                   and abs(w - TARGET_CLIENT_W) <= GAME_SIZE_TOLERANCE
                   and abs(h - TARGET_CLIENT_H) <= GAME_SIZE_TOLERANCE)
        return (True, hwnd, w, h, healthy)
    except Exception:
        return (False, None, 0, 0, False)


def _game_window_present():
    """True, wenn das Spiel-Fenster (``constants.GAME_NAME``) da + sichtbar ist.

    Duenne Huelle um :func:`_probe_game` -- bewusst nur der TITEL-Check (ohne
    Groesse), damit close-on-metin2 (``_maybe_close_on_metin2``) byte-stabil auf
    das Verschwinden des Fensters reagiert, unabhaengig von dessen Groesse."""
    return _probe_game()[0]


# Explicit ``__all__`` so ``from interface.app._common import *`` re-exports the
# leading-underscore helpers/constants too (they are part of the historical
# ``interface.app`` surface used by the GUI-smoke + characterization tests).
__all__ = [
    # third-party / stdlib re-exports used inside method bodies
    'copy', 'os', 'threading', 'time', 'ctk',
    'log', 'get_lang', 'set_lang', 't', 'cfgmod', 'tray', 'LogPanel',
    'resource_path',
    # widget palette + components
    'AMBER', 'BG', 'DANGER', 'DANGER_HOVER', 'DANGER_SOFT', 'INK', 'LIVE_GREEN',
    'PANEL', 'PANEL_DARK', 'PANEL_HOVER', 'PANEL_LIGHT', 'RAIL_BG', 'RAIL_HOVER',
    'STRIP_BG', 'TEAL', 'TEAL_BRIGHT', 'TEAL_DARK', 'TEAL_HOVER', 'TEAL_SOFT',
    'TEXT', 'TEXT_FAINT', 'TEXT_MUTED', 'InfoBadge', 'LabeledSlider', 'Section',
    'Segmented', 'SegmentedRow', 'Tooltip',
    # constants
    'ICON_FILE', 'REFERENCE_IMAGE', 'REFERENCE_IMAGE_SIZE', 'SOLVER_MODE_KEYS',
    'DETECTION_MODE_KEYS', 'RAIL_GLYPHS', 'RAIL_ORDER', 'WHICH_TO_CFG',
    'GAME_SIZE_TOLERANCE', 'TARGET_CLIENT_W', 'TARGET_CLIENT_H',
    # pure helpers
    '_solver_pairs', '_detection_pairs', '_pad2', '_hms', '_is_no_window_error',
    '_mmss', '_probe_game', '_game_window_present',
]
