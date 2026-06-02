"""Konfigurations-Persistenz fuer das Metin2-Fishing-Bot-UI.

Bewusst NUR Python-Standardbibliothek (``json``), damit dieses Modul auch ohne
GUI-Toolkit ueberall importier- und testbar bleibt und aus der gepackten ``.exe``
heraus funktioniert.

Die ``config.json`` liegt neben der EXE. Sie haelt ALLE UI-Optionen
(Modus, Fishing-Timings, Puzzle-Detection/Color/Solver, Log-Sichtbarkeit).

Grundregeln:
  * Laden wirft NIE -- fehlende/kaputte Datei -> Defaults.
  * Unbekannte/fehlende Schluessel werden mit Defaults gefuellt (Vorwaerts-/
    Rueckwaertskompatibilitaet zu alten config.json-Dateien).
  * Validierung klemmt Werte in den erlaubten Bereich und ersetzt ungueltige
    Enums durch ihren Default (statt zu werfen).
  * Immutabilitaet: ``merge_defaults``/``validate`` geben NEUE Dicts zurueck und
    veraendern ihre Eingabe nicht.

Dieses Paket ist die Nachfolge-Struktur des frueheren Einzelmoduls
``interface/config.py``. Es ist in drei kohaesive Schichten aufgeteilt --
:mod:`~interface.config.defaults` (Schema/Konstanten),
:mod:`~interface.config.validate` (Validierung/Merge) und
:mod:`~interface.config.io` (Laden/Speichern/values). Dieses ``__init__``
re-exportiert JEDES bisherige Symbol unveraendert, sodass ``from interface import
config`` plus jeder ``config.X``-Zugriff (inkl. des privaten
``config._validate_key``, das ``interface.app.key_capture`` nutzt) byte-identisch
weiterfunktioniert.
"""

# __all__ der Submodule VOR dem Star-Import einsammeln -- der Star-Import bringt
# u.a. die Funktion ``validate`` in den Namespace und wuerde sonst den
# gleichnamigen Submodul-Alias verdecken.
from .defaults import __all__ as _DEFAULTS_ALL
from .validate import __all__ as _VALIDATE_ALL
from .io import __all__ as _IO_ALL

from .defaults import *  # noqa: F401,F403,E402  (re-export: Schema + Konstanten)
from .validate import *  # noqa: F401,F403,E402  (re-export: Validierung/Merge)
from .io import *  # noqa: F401,F403,E402  (re-export: Laden/Speichern/values)

# Star-Import ueberspringt fuehrende-Unterstrich-Namen. ``interface.app.
# key_capture`` importiert aber ``config._validate_key`` direkt -> hier explizit
# re-exportieren, damit der bisherige Aufruf unveraendert aufgeht.
from .validate import _validate_key  # noqa: F401,E402

# __all__ erschoepfend halten (vereint die __all__ der Submodule), damit
# ``from interface.config import *`` exakt das frueher exportierte Set liefert.
__all__ = list(_DEFAULTS_ALL) + list(_VALIDATE_ALL) + list(_IO_ALL)
