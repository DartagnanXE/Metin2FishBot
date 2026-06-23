"""UI-Paket des Metin2 MultiTool (CustomTkinter, Single-Window).

Ersetzt das fruehere FreeSimpleGUI-Fenster. Oeffentliche Einstiegspunkte:

    from interface import App            # das Single-Window
    from interface import config         # config.json laden/speichern

``App`` und ``BotController`` werden LAZY ueber ``__getattr__`` aufgeloest,
damit dieses Paket auch ohne installiertes ``customtkinter`` importierbar ist
(z.B. fuer die headless laufenden Config-/Solver-Tests und ``py_compile``).
Erst der tatsaechliche Zugriff auf ``interface.App`` zieht das GUI-Toolkit.
"""

from interface import config  # reine stdlib -> immer sicher importierbar


def __getattr__(name):
    # PEP 562: Lazy-Attribute auf Modulebene. Haelt GUI-Importe optional.
    if name in ('App', 'BotController'):
        from interface.app import App, BotController
        return {'App': App, 'BotController': BotController}[name]
    raise AttributeError(
        '{!r} has no attribute {!r}'.format(__name__, name))


__all__ = ['App', 'BotController', 'config']
