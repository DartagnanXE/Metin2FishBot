"""Laden/Speichern der Konfiguration + Ableitung des Fishing-``values``-Dicts.

Bewusst NUR Python-Standardbibliothek (``json``), damit dieses Modul auch ohne
GUI-Toolkit ueberall importier- und testbar bleibt und aus der gepackten ``.exe``
heraus funktioniert.

Die ``config.json`` liegt neben der EXE. Sie haelt ALLE UI-Optionen
(Modus, Fishing-Timings, Puzzle-Detection/Color/Solver, Log-Sichtbarkeit).

Grundregeln:
  * Laden wirft NIE -- fehlende/kaputte Datei -> Defaults.
  * Unbekannte/fehlende Schluessel werden mit Defaults gefuellt (Vorwaerts-/
    Rueckwaertskompatibilitaet zu alten config.json-Dateien).
"""

import json

from .defaults import DEFAULT_CONFIG_PATH, DEFAULTS
from .validate import validate


def load(path=DEFAULT_CONFIG_PATH):
    """Laedt und validiert die Konfiguration. Wirft NIE.

    Fehlende oder fehlerhafte Datei -> validierte Defaults (es wird nichts auf
    die Platte geschrieben; das uebernimmt erst :func:`save`).
    """
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            raw = json.loads(handle.read())
    except (OSError, ValueError):
        return validate(DEFAULTS)
    except Exception:
        return validate(DEFAULTS)
    return validate(raw)


def save(cfg, path=DEFAULT_CONFIG_PATH):
    """Schreibt die (validierte) Konfiguration als JSON. Wirft NIE.

    Gibt ``True`` bei Erfolg, sonst ``False`` (Aufrufer darf den Rueckgabewert
    ignorieren -- ein Speicherfehler darf den Bot nicht stoppen).
    """
    try:
        normalized = validate(cfg)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(json.dumps(normalized, indent=2, ensure_ascii=False))
        return True
    except Exception:
        return False


def to_values(cfg):
    """Baut den Fishing-``values``-Dict (frozen keys) aus der Konfiguration.

    Liefert exakt die Schluessel, die ``FishingBot.set_to_begin(values)`` liest
    (und die ``PuzzleBot.set_to_begin`` ignoriert). So bleibt die Wertekompati-
    bilitaet zu beiden Bots gewahrt, ohne FreeSimpleGUI.
    """
    normalized = validate(cfg)
    fishing = normalized['fishing']
    return {
        '-ENDTIMEP-': bool(fishing['stop_after_enabled']),
        '-ENDTIME-': str(fishing['stop_after_minutes']),
        '-BAITTIME-': float(fishing['bait_time']),
        '-THROWTIME-': float(fishing['throw_time']),
        '-STARTGAME-': float(fishing['start_game_time']),
        '-GOLDENTUNA-': int(fishing['golden_tuna_action']),
        # Mount-Animation-Cancel: an/aus + Taste -- vom FishingBot wie die
        # uebrigen frozen keys gelesen (Default AUS/'3' -> byte-stabil).
        '-MOUNT-': bool(fishing['mount_enabled']),
        '-MOUNTKEY-': str(fishing['mount_key']),
    }


__all__ = ['load', 'save', 'to_values']
