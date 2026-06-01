"""Optionaler System-Tray (pystray + Pillow). Strikt defensiv: fehlt pystray,
meldet ``available()`` False und nichts bricht. Kapselt das Icon-Lifecycle in
einem Daemon-Thread (run_detached), Restore/Quit bouncen via ``after`` auf den
GUI-Thread (Tk ist nicht thread-sicher)."""

from respath import resource_path


def available():
    """True, wenn pystray UND PIL importierbar sind. Wirft nie."""
    try:
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401
        return True
    except Exception:
        return False


def make_icon(ico_path, title, on_show, on_quit, show_text, quit_text):
    """Erzeugt (startet NICHT) ein pystray.Icon mit Menue Show/Quit.

    Gibt das Icon-Objekt zurueck oder None bei Fehler. ``on_show``/``on_quit``
    sind parameterlose Callables (der Aufrufer sorgt selbst fuer den
    GUI-Thread-Bounce via app.after)."""
    try:
        import pystray
        from PIL import Image
        image = Image.open(resource_path(ico_path))
        menu = pystray.Menu(
            pystray.MenuItem(show_text, lambda icon, item: on_show(),
                             default=True),
            pystray.MenuItem(quit_text, lambda icon, item: on_quit()),
        )
        return pystray.Icon('metin2fishbot', image, title, menu)
    except Exception:
        return None
