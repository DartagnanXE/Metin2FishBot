"""Wiederverwendbare CustomTkinter-Widgets fuer das Bot-UI (Teal/Dark).

Reine Praesentations-Bausteine ohne Geschaeftslogik. Wird ausschliesslich vom
GUI-Prozess importiert; ``customtkinter`` ist daher eine harte Abhaengigkeit
dieses Moduls (nicht der headless getesteten config-/debuglog-Module).

Wichtig (V1.0): Das Segment-Control (:class:`Segmented`) ist BEWUSST aus echten
``CTkButton``s gebaut statt aus ``CTkSegmentedButton`` -- letzteres rendert auf
manchen Windows/DPI-Setups nur seinen grauen Hintergrund OHNE die Knoepfe (der
Bug aus V0). Eigene Buttons rendern garantiert.

UI-Strings ENGLISCH (Spec). Kommentare deutsch.
"""

import os
import tkinter as tk

import customtkinter as ctk

from respath import resource_path


# -- Teal/Dark-Farbpalette (eine Wahrheit, von app.py mitgenutzt) -----------

TEAL = '#14b8a6'          # Primaer-Akzent (START/aktiv)
TEAL_HOVER = '#0d9488'    # Hover des Akzents
TEAL_DARK = '#0f766e'     # gedimmter Akzent / Raender
DANGER = '#ef4444'        # STOP
DANGER_HOVER = '#dc2626'
BG = '#0b1220'            # Fensterhintergrund (sehr dunkel)
PANEL = '#111c2e'         # Karten-/Sektionshintergrund
PANEL_LIGHT = '#16233a'   # leicht hellere Flaeche (Eingaben/Segmente)
PANEL_HOVER = '#1c2c46'   # Hover inaktiver Segmente
TEXT = '#e2e8f0'          # Haupttext
TEXT_MUTED = '#94a3b8'    # sekundaerer Text
LIVE_GREEN = '#22c55e'    # "live"-Punkt
INK = '#06231f'           # dunkler Text auf Teal (guter Kontrast)

# -- Cockpit-Sidebar-Tokens (opake Naeherungen der Mockup-rgba-Werte) -------
# CTk braucht opake Hex-Farben (kein rgba); die folgenden Werte bilden die
# halbtransparenten Mockup-Toene auf dem dunklen Untergrund nach.
RAIL_BG = '#0c1119'        # Icon-Rail Hintergrund
RAIL_HOVER = '#161f2e'     # Rail-Item Hover
STRIP_BG = '#121a26'       # Command-Strip Hintergrund
PANEL_DARK = '#0e141d'     # Titelleiste / Footer
TEAL_BRIGHT = '#2dd4bf'    # aktiver Rail-/Timer-Akzent
TEAL_SOFT = '#15302c'      # opakes ~12%-Teal (aktives Rail-Fill)
TEXT_FAINT = '#677890'     # sehr gedaempfter Text (Rail idle, Timer-Label)
AMBER = '#f59e0b'          # Detection "searching" / notify_stop
DANGER_SOFT = '#3a1620'    # Hover des Close-X


class Section(ctk.CTkFrame):
    """Abgesetzte Karte mit Titelzeile; nimmt beliebigen Inhalt auf.

    Kinder werden ueber ``section.body`` (ein CTkFrame) eingehaengt.
    """

    def __init__(self, master, title, **kwargs):
        super().__init__(master, fg_color=PANEL, corner_radius=12, **kwargs)
        self.grid_columnconfigure(0, weight=1)

        self._title = ctk.CTkLabel(
            self, text=title, anchor='w',
            font=ctk.CTkFont(size=14, weight='bold'), text_color=TEAL)
        self._title.grid(row=0, column=0, sticky='ew', padx=14, pady=(8, 2))

        self.body = ctk.CTkFrame(self, fg_color='transparent')
        self.body.grid(row=1, column=0, sticky='nsew', padx=10, pady=(0, 8))
        self.body.grid_columnconfigure(0, weight=1)


class LabeledSlider(ctk.CTkFrame):
    """Beschrifteter Schieberegler mit Live-Wertanzeige (0.1-20.0, Schritt 0.1)."""

    def __init__(self, master, label, from_=0.1, to=20.0, step=0.1,
                 default=2.0, unit='s', command=None, **kwargs):
        super().__init__(master, fg_color='transparent', **kwargs)
        self.grid_columnconfigure(0, weight=1)

        self._unit = unit
        self._step = step
        self._command = command

        steps = max(1, int(round((to - from_) / step)))

        header = ctk.CTkFrame(self, fg_color='transparent')
        header.grid(row=0, column=0, sticky='ew')
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(header, text=label, anchor='w',
                     text_color=TEXT).grid(row=0, column=0, sticky='w')
        self._value_label = ctk.CTkLabel(
            header, text='', anchor='e', text_color=TEAL,
            font=ctk.CTkFont(size=13, weight='bold'))
        self._value_label.grid(row=0, column=1, sticky='e')

        self._slider = ctk.CTkSlider(
            self, from_=from_, to=to, number_of_steps=steps,
            progress_color=TEAL, button_color=TEAL,
            button_hover_color=TEAL_HOVER, command=self._on_change)
        self._slider.grid(row=1, column=0, sticky='ew', pady=(2, 0))

        self.set(default)

    def _on_change(self, _raw):
        value = self.get()
        self._value_label.configure(text='{:.1f}{}'.format(value, self._unit))
        if self._command is not None:
            try:
                self._command(value)
            except Exception:
                pass

    def get(self):
        return round(float(self._slider.get()), 1)

    def set(self, value):
        try:
            self._slider.set(float(value))
        except (TypeError, ValueError):
            self._slider.set(0.1)
        self._value_label.configure(
            text='{:.1f}{}'.format(self.get(), self._unit))

    def set_enabled(self, enabled):
        self._slider.configure(state='normal' if enabled else 'disabled')


class Segmented(ctk.CTkFrame):
    """Robustes Segment-Control aus echten Buttons (rendert IMMER).

    Ersetzt ``CTkSegmentedButton`` (das auf manchen Setups leer blieb). ``get()``/
    ``set(value)`` lesen/setzen die Auswahl; ``command`` wird bei Klick mit dem
    gewaehlten String gerufen. Genau eine Option ist aktiv (teal hervorgehoben).
    """

    def __init__(self, master, values, default=None, command=None, height=34,
                 **kwargs):
        super().__init__(master, fg_color=PANEL_LIGHT, corner_radius=9, **kwargs)
        self._command = command
        self._values = [str(v) for v in values]
        self._value = (default if default in self._values
                       else (self._values[0] if self._values else ''))
        self._buttons = {}
        self._enabled = True

        for i, val in enumerate(self._values):
            self.grid_columnconfigure(i, weight=1)
            btn = ctk.CTkButton(
                self, text=val, height=height, corner_radius=7,
                fg_color='transparent', text_color=TEXT_MUTED,
                hover_color=PANEL_HOVER,
                font=ctk.CTkFont(size=13, weight='bold'),
                command=lambda v=val: self._select(v))
            btn.grid(row=0, column=i, sticky='ew', padx=3, pady=3)
            self._buttons[val] = btn

        self._refresh()

    def _select(self, val):
        if not self._enabled:
            return
        self._value = val
        self._refresh()
        if self._command is not None:
            try:
                self._command(val)
            except Exception:
                pass

    def _refresh(self):
        for val, btn in self._buttons.items():
            if val == self._value:
                btn.configure(fg_color=TEAL, text_color=INK,
                              hover_color=TEAL_HOVER)
            else:
                btn.configure(fg_color='transparent', text_color=TEXT_MUTED,
                              hover_color=PANEL_HOVER)

    def get(self):
        return self._value

    def set(self, value):
        value = str(value)
        if value in self._buttons:
            self._value = value
            self._refresh()

    def set_enabled(self, enabled):
        self._enabled = bool(enabled)
        for btn in self._buttons.values():
            btn.configure(state='normal' if enabled else 'disabled')
        self._refresh()


class Tooltip:
    """Hover-Tooltip fuer ein Widget; optional mit Bild (z.B. Referenz).

    Bewusst klassisches ``tk.Toplevel`` (kein CTk) -- das ist fuer kurzlebige
    Tooltips schneller und flackerfrei. Das Bild wird per PIL geladen; fehlt PIL
    oder die Datei, wird nur der Text gezeigt.
    """

    def __init__(self, widget, text='', image_path=None, image_size=(260, 170)):
        self._widget = widget
        self._text = text
        self._image_path = image_path
        self._image_size = image_size
        self._tip = None
        self._photo = None
        widget.bind('<Enter>', self._show, add='+')
        widget.bind('<Leave>', self._hide, add='+')

    def _show(self, _event=None):
        if self._tip is not None or (not self._text and not self._image_path):
            return
        try:
            x = self._widget.winfo_rootx()
            y = (self._widget.winfo_rooty()
                 + self._widget.winfo_height() + 6)
            tip = tk.Toplevel(self._widget)
            tip.wm_overrideredirect(True)
            tip.attributes('-topmost', True)
            tip.configure(bg=TEAL_DARK)            # 1px-Rahmen-Effekt
            inner = tk.Frame(tip, bg=PANEL)
            inner.pack(padx=1, pady=1)
            if self._text:
                tk.Label(inner, text=self._text, bg=PANEL, fg=TEXT,
                         justify='left', font=('Segoe UI', 9),
                         wraplength=320).pack(
                    padx=10, pady=(8, 6 if self._image_path else 8))
            if self._image_path:
                photo = self._load_photo()
                if photo is not None:
                    label = tk.Label(inner, image=photo, bg=PANEL)
                    label.image = photo          # Referenz halten (kein GC)
                    label.pack(padx=10, pady=(0, 10))
            tip.geometry('+{}+{}'.format(x, y))
            self._tip = tip
        except Exception:
            self._tip = None

    def _load_photo(self):
        if self._photo is not None:
            return self._photo
        try:
            from PIL import Image, ImageTk
            path = resource_path(self._image_path)
            if not os.path.exists(path):
                return None
            pil = Image.open(path).convert('RGBA').resize(self._image_size)
            self._photo = ImageTk.PhotoImage(pil)
            return self._photo
        except Exception:
            return None

    def _hide(self, _event=None):
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


class InfoBadge(ctk.CTkLabel):
    """Kleines ``?``-Abzeichen mit Hover-Tooltip (optional Referenzbild)."""

    def __init__(self, master, text='', image_path=None, image_size=(260, 170),
                 **kwargs):
        super().__init__(
            master, text=' ? ', width=22, height=22, corner_radius=11,
            fg_color=PANEL_LIGHT, text_color=TEAL,
            font=ctk.CTkFont(size=12, weight='bold'), **kwargs)
        self._tooltip = Tooltip(self, text=text, image_path=image_path,
                                image_size=image_size)


class SegmentedRow(ctk.CTkFrame):
    """Beschriftete Segment-Auswahl: Label (+ optional ``?``) ueber dem Control.

    ``get()``/``set(value)``/``set_enabled(bool)`` delegieren an das robuste
    :class:`Segmented`. ``info`` (Text) und/oder ``info_image`` (Pfad) erzeugen
    ein ``?``-Badge mit Hover-Hilfe rechts neben dem Label.
    """

    def __init__(self, master, label, values, default=None, command=None,
                 info=None, info_image=None, info_image_size=(260, 170),
                 **kwargs):
        super().__init__(master, fg_color='transparent', **kwargs)
        self.grid_columnconfigure(0, weight=1)

        # Kopfzeile zeigen, sobald es ein Label ODER ein ?-Badge (info/
        # info_image) gibt. Frueher war sie an ``if label:`` gekoppelt -> das
        # Detection-Segment (label='') verlor sein Referenzbild-"?". Spalte 0
        # waechst, daher rastet das Badge auch ohne Label rechts ein.
        if label or info or info_image:
            head = ctk.CTkFrame(self, fg_color='transparent')
            head.grid(row=0, column=0, sticky='ew', pady=(0, 3))
            head.grid_columnconfigure(0, weight=1)
            if label:
                ctk.CTkLabel(head, text=label, anchor='w',
                             text_color=TEXT).grid(row=0, column=0, sticky='w')
            if info or info_image:
                InfoBadge(head, text=info or '', image_path=info_image,
                          image_size=info_image_size).grid(
                    row=0, column=1, sticky='e')

        self._seg = Segmented(self, values=values, default=default,
                              command=command)
        self._seg.grid(row=1, column=0, sticky='ew')

    def get(self):
        return self._seg.get()

    def set(self, value):
        self._seg.set(value)

    def set_enabled(self, enabled):
        self._seg.set_enabled(enabled)
