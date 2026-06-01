"""Single-Window-UI fuer den Metin2 Fishing Bot (CustomTkinter, "Cockpit Sidebar").

Layout (Blueprint variant3_final.html, in CTk uebersetzt):
  * Kompaktes, FIXES Fenster (~470px breit) -- DARK + Teal, KEIN Scrollen.
  * Schmale LINKE Icon-Rail (Fishing / Puzzle / Console / Settings) als einzige
    Navigation; sie tauscht den Hauptbereich. Fishing XOR Puzzle ist der aktive
    Lauf-Modus (aktives Item hervorgehoben + kleiner Lauf-Punkt beim Botten).
  * TOP-LEFT: App-Logo (musketier.ico), minimaler Fenster-Schliessen-Button
    rechts, dezenter EN|DE-Umschalter oben rechts.
  * TOP-STRIP = Kommandozentrale: grosser START/STOP-Hero (teal "Start", rot
    "Stop - Fishing"/"Stop - Puzzle" mit aktivem Modus) mit dem LIVE-Lauf-Timer
    direkt LINKS davon (zaehlt herunter bei Zeitlimit, sonst hoch).
  * Metin2-Erkennung: klein UNTEN-RECHTS; blendet sich aus, sobald das Spiel bei
    800x600 gefunden ist -- zeigt sonst "Suche Metin2 (800x600)...".
  * FOOTER UNTEN-LINKS: dezente Versionsanzeige "v1.0.x" (faint, kein Kasten),
    wird bei Update zur teal "Update"-Pille; Klick oeffnet das Repo/Update.
  * "?"-Hilfe-Tooltips neben nicht-offensichtlichen Steuerungen.

Die Bot-Steuerung haengt in :class:`BotController`; das Modul kennt die Bots nur
als injizierte Instanzen und liest/schreibt Optionen ueber :mod:`interface.config`.

UI-Strings ENGLISCH (via i18n t()), Kommentare deutsch (Spec).
"""

import copy
import os
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
    'roadmap': '\U0001F5FA',   # Landkarte (geplante Features)
    'settings': '⚙',      # Zahnrad
}
# Reihenfolge in der Rail: Fishing, Puzzle, Console, Roadmap, [Spacer], Settings.
RAIL_ORDER = ('fishing', 'puzzle', 'console', 'roadmap', 'settings')


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


class BotController:
    """Haelt Laufzustand, Modus und die beiden Bot-Instanzen.

    Schnittstelle, gegen die ``hack.py`` verdrahtet: ``mode``/``running`` lesen,
    ``fishbot``/``puzzlebot`` ansprechen, ``collect_values()`` /
    ``current_config()`` fuer die Optionen. Die UI ruft ``on_start_stop`` beim
    Button-Klick. Einstellungen werden bei jeder Aenderung (entprellt)
    gespeichert.
    """

    def __init__(self, app, fishbot, puzzlebot, cfg):
        self.app = app
        self.fishbot = fishbot
        self.puzzlebot = puzzlebot
        self._cfg = cfgmod.validate(cfg)
        self.mode = self._cfg['mode']
        self.running = False
        self.on_start = None
        self.on_stop = None
        self._save_job = None

    # -- Konfigurationszugriff -------------------------------------------

    def current_config(self):
        return cfgmod.validate(self._cfg)

    def update_config(self, section, key, value):
        """Setzt einen Wert (immutabel), loggt ihn und plant ein Auto-Speichern."""
        new_cfg = copy.deepcopy(self._cfg)
        new_cfg.setdefault(section, {})[key] = value
        self._cfg = cfgmod.validate(new_cfg)
        # Hinweis: ``key`` ist hier ALSO der positionelle 1. Parameter von t()
        # -- die Format-Felder daher als Dict uebergeben (sonst Namenskollision
        # ``t() got multiple values for argument 'key'``), damit JEDE
        # Einstellungsaenderung sauber durchlaeuft (statt im Tk-Callback zu
        # crashen und das Auto-Speichern zu ueberspringen).
        log.event('-', t('ui.setting_changed').format(
            section=section, key=key, value=value))
        self._schedule_save()
        return self._cfg

    def set_mode(self, mode):
        if mode in cfgmod.APP_MODES and not self.running:
            self.mode = mode
            new_cfg = copy.deepcopy(self._cfg)
            new_cfg['mode'] = mode
            self._cfg = cfgmod.validate(new_cfg)
            log.event('-', t('ui.mode_switched', mode=mode))
            self._schedule_save()

    def collect_values(self):
        return cfgmod.to_values(self._cfg)

    def set_language(self, lang):
        """Speichert die gewaehlte UI-Sprache ('en'/'de') in der Config."""
        new_cfg = copy.deepcopy(self._cfg)
        new_cfg['language'] = lang
        self._cfg = cfgmod.validate(new_cfg)
        self._schedule_save()

    def reset_to_defaults(self):
        """Setzt ALLES auf die Auslieferungs-Standardwerte (Item K).

        Nur im Leerlauf erlaubt (laeuft der Bot -> ``False``, kein Effekt). Baut
        die Config frisch aus ``merge_defaults({})`` -> validiert -> speichert
        sofort. Immutabel (neues Dict). Der Aufrufer (UI) wendet die Defaults
        danach auf alle Widgets an (Neuaufbau). Gibt ``True`` bei Erfolg.
        """
        if self.running:
            return False
        self._cfg = cfgmod.validate(cfgmod.merge_defaults({}))
        self.mode = self._cfg['mode']
        cfgmod.save(self._cfg)
        log.event('-', t('ui.reset_done_log'))
        return True

    # -- Auto-Speichern (entprellt) --------------------------------------

    def _schedule_save(self):
        """Plant ein Speichern in ~0.7s; weitere Aenderungen verschieben es.

        Schuetzt vor Datenverlust bei Absturz (statt nur beim Schliessen). Der
        Aufruf laeuft im GUI-Thread (after); faellt auf Sofort-Speichern zurueck,
        falls kein Scheduler verfuegbar ist.
        """
        try:
            if self._save_job is not None:
                self.app.after_cancel(self._save_job)
            self._save_job = self.app.after(700, self._do_save)
        except Exception:
            self._do_save()

    def _do_save(self):
        self._save_job = None
        try:
            cfgmod.save(self._cfg)
            log.event('-', t('ui.settings_saved'))
            self.app.flash_saved()
        except Exception:
            pass

    # -- Start/Stop -------------------------------------------------------

    def on_start_stop(self):
        try:
            if self.running:
                log.section(t('ui.stop_pressed_manual'))
                self.set_running(False)
                # Mehrfenster-Wahl (Item N) nur fuer den aktiven Lauf gueltig ->
                # beim Stop die Praeferenz loeschen, damit Leerlauf-Captures
                # wieder byte-identisch FindWindow nutzen.
                self.app._clear_preferred_hwnd()
                if callable(self.on_stop):
                    self.on_stop()
            else:
                log.section(t('ui.start_pressed', mode=self.mode))
                # Vom Nutzer gewaehltes Ziel-HWND (Item N) VOR dem Start setzen,
                # damit WindowCapture(...) es trifft. Ohne Wahl -> None ->
                # FindWindow-Pfad (byte-identisch zu frueher).
                self.app._apply_preferred_hwnd()
                if callable(self.on_start):
                    self.on_start()
                else:
                    self._fallback_start()
                self.set_running(True)
        except Exception as exc:
            self.set_running(False)
            # Spielfenster-nicht-gefunden ist ein NORMALER Fall (Spiel nicht offen)
            # -> klar im UI melden, KEIN alarmierender Traceback (windowcapture +
            # fishingbot haben den Grund schon geloggt). Andere Fehler: voll loggen.
            msg = str(exc)
            no_window = ('nicht gefunden' in msg or 'not found' in msg.lower())
            if no_window:
                log.event('-', t('ui.start_aborted_no_window'))
            else:
                log.error(t('ui.start_stop_toggle_failed'), exc=exc)
            self.app.notify_start_failed(no_window)

    def _fallback_start(self):
        values = self.collect_values()
        if self.mode == 'fishing':
            self.fishbot.set_to_begin(values)
            self.fishbot.botting = True
            self.puzzlebot.botting = False
        else:
            self.puzzlebot.set_to_begin(values)
            self.puzzlebot.botting = True
            self.fishbot.botting = False

    def set_running(self, running):
        self.running = bool(running)
        if not self.running:
            self.fishbot.botting = False
            self.puzzlebot.botting = False
        self.app.sync_controls()


class App(ctk.CTk):
    """Das Single-Window in der "Cockpit Sidebar"-Anordnung.

    Aufbau: Titelleiste (Logo + EN|DE + Schliessen) ueber einer Shell aus
    Icon-Rail (links) und Body (Command-Strip + getauschte Ansicht). Footer +
    optionales Update-Banner liegen auf eigenen Grid-Zeilen (ueberleben den
    Sprachwechsel-Neuaufbau).
    """

    def __init__(self, cfg=None, fishbot=None, puzzlebot=None):
        super().__init__()

        self._cfg = cfgmod.validate(cfg if cfg is not None else cfgmod.DEFAULTS)

        if fishbot is None or puzzlebot is None:
            from fishingbot import FishingBot
            from puzzle import PuzzleBot
            fishbot = fishbot or FishingBot()
            puzzlebot = puzzlebot or PuzzleBot()

        self.controller = BotController(self, fishbot, puzzlebot, self._cfg)

        # Gespeicherte Sprache anwenden, BEVOR das UI (mit t()) gebaut wird.
        set_lang(self._cfg['language'])

        ctk.set_appearance_mode('dark')
        ctk.set_widget_scaling(0.85)  # ~15% kompakter
        self.title(t('ui.window_title'))
        # FIXE Groesse -> garantiert KEIN Scrollen (ausser der Roadmap-Info-
        # Liste, die bewusst scrollen darf). Hoehe an die HOECHSTE Steuer-Sicht
        # (Settings: 3 Karten + Overlay-Deckkraft + Reset-Zeile) gekoppelt +
        # kleiner Sicherheitsrand. Die Sichten wurden dichter gesetzt; Fishing/
        # Puzzle verteilen ihre Resthoehe ueber einen flexiblen Zwischenraum,
        # sodass KEINE Sicht leer am Boden wirkt.
        self.geometry('470x608')
        self.resizable(False, False)
        self.configure(fg_color=BG)

        # -- Zustand -----------------------------------------------------
        self._saved_job = None
        self._game_present = False
        self._game_was_present = False     # Latch fuer close-on-metin2
        # Item M: Groessen-Check des gefundenen Metin2-Fensters.
        self._game_hwnd = None
        self._game_size = (0, 0)
        self._game_healthy = False
        # Item N: Mehrfenster-Wahl. RUNTIME-ONLY (nicht in config/to_values).
        # ``_chosen_hwnd`` ist das vom Nutzer gewaehlte Ziel; ``_window_sig``
        # cacht die HWND-Signatur, damit die Picker-UI nur bei Aenderung neu
        # gebaut wird (kein Sekunden-Takt-Flackern).
        self._game_windows = []
        self._chosen_hwnd = None
        self._window_sig = None
        self._run_started_at = 0.0
        self._was_running = False
        self._capturing = None             # (which, button) waehrend Key-Capture
        self._views = {}                   # view-name -> frame
        self._rail_items = {}              # view-name -> CTkButton
        self._rail_dots = {}               # view-name -> Lauf-Punkt-Label
        self._timer_tooltip = None
        self._tray_icon = None
        self._test_window = None           # Fake-"METIN2"-Testfenster (Console)
        self._tray_enabled = (self._cfg['window']['minimize_to_tray']
                              and tray.available())
        # Update-Zustand HIER initialisieren; Banner lebt auf eigener Grid-Zeile
        # (row 2) und ueberlebt so den Sprachwechsel-Neuaufbau.
        self._update_info = None
        self._update_banner = None

        self._set_window_icon()

        # -- Root-Grid: 0 Titelleiste, 1 Shell, 2 Update-Banner, 3 Footer
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)   # Shell waechst

        self._active_view = self._cfg['mode']
        self._build_titlebar()
        self._build_content()
        self._build_footer()       # dezente Versionsanzeige unten links (row 3)
        self._show_view(self._cfg['mode'])

        self._apply_config_to_widgets()
        self._apply_window_prefs()
        self.sync_controls()

        if self._cfg['log']['show_in_ui']:
            self.log_panel.attach()

        self.protocol('WM_DELETE_WINDOW', self._on_close)
        self.bind('<Unmap>', self._on_unmap, add='+')
        # Sofort-Render erzwingen: sonst bleibt das Fenster auf manchen Setups
        # blass/leer, bis ein Event es neu zeichnet (V0-Symptom).
        self.after(60, self._force_render)
        # Spiel-Erkennung starten (Note unten rechts blendet sich aus bei Fund).
        self.after(250, self._poll_game)
        # Live-Lauf-Timer ticken lassen (1x/Sekunde, guenstig, immer aktiv).
        self.after(1000, self._tick_timer)
        # Einmalige, nicht-blockierende Versionspruefung ~1.2s nach Start.
        self.after(1200, self._kick_off_update_check)

    # -- Fenster-Icon / Render -------------------------------------------

    def _set_window_icon(self):
        """Setzt das Musketier-Icon als Fenster-/Taskleisten-Icon.

        CustomTkinter ueberschreibt das Icon ~200ms nach dem Start mit seinem
        eigenen -> wir setzen es danach erneut (bekannter CTk-Workaround).
        """
        ico = resource_path(ICON_FILE)
        if not os.path.exists(ico):
            return
        try:
            self.iconbitmap(ico)
        except Exception:
            pass
        self.after(300, lambda: self._reapply_icon(ico))

    def _reapply_icon(self, ico):
        try:
            self.iconbitmap(ico)
        except Exception:
            pass

    def _force_render(self):
        try:
            self.update_idletasks()
            self.update()
            self.lift()
        except Exception:
            pass

    # -- Titelleiste (Logo + EN|DE + Schliessen) -------------------------

    def _build_titlebar(self):
        """Schmale Titelleiste: Logo + Titel (links), EN|DE + Schliessen (rechts).

        ``self.topbar`` bleibt der Name (``_rebuild_ui`` zerstoert ihn beim
        Sprachwechsel und baut ihn neu).
        """
        bar = ctk.CTkFrame(self, fg_color=PANEL_DARK, corner_radius=0)
        bar.grid(row=0, column=0, sticky='ew')
        bar.grid_columnconfigure(1, weight=1)   # Spacer-Spalte waechst
        self.topbar = bar

        # col 0 -- Logo + Titel.
        ident = ctk.CTkFrame(bar, fg_color='transparent')
        ident.grid(row=0, column=0, sticky='w', padx=(12, 0), pady=7)
        self._place_logo(ident)
        ctk.CTkLabel(ident, text='Metin2 ', text_color=TEXT_MUTED,
                     font=ctk.CTkFont(size=12)).grid(row=0, column=1, sticky='w')
        ctk.CTkLabel(ident, text='Fishing Bot', text_color=TEXT,
                     font=ctk.CTkFont(size=12, weight='bold')).grid(
            row=0, column=2, sticky='w')

        # col 2 -- EN|DE-Umschalter (oben rechts, dezent).
        self._build_lang_toggle(bar).grid(row=0, column=2, sticky='e', padx=4)

        # col 3 -- Schliessen "X" (ASCII-sicher).
        ctk.CTkButton(bar, width=24, height=24, text='X',
                      fg_color='transparent', hover_color=DANGER_SOFT,
                      text_color=TEXT_MUTED, corner_radius=7,
                      font=ctk.CTkFont(size=12, weight='bold'),
                      command=self._on_close).grid(
            row=0, column=3, sticky='e', padx=(0, 10))

    def _place_logo(self, parent):
        """Laedt das musketier.ico als kleines Logo (PIL->CTkImage). Faellt das
        aus, bleibt es text-only -- NIE crashen, KEIN neues Logo erfinden."""
        try:
            from PIL import Image
            path = resource_path(ICON_FILE)
            if os.path.exists(path):
                img = Image.open(path).convert('RGBA')
                self._logo_img = ctk.CTkImage(light_image=img, dark_image=img,
                                              size=(20, 20))
                ctk.CTkLabel(parent, image=self._logo_img, text='').grid(
                    row=0, column=0, sticky='w', padx=(0, 6))
                return
        except Exception:
            pass
        # Fallback: kein Bild -> nur eine schmale Luecke.
        ctk.CTkLabel(parent, text='', width=4).grid(row=0, column=0)

    def _build_lang_toggle(self, parent):
        """Kleiner, dezenter EN/DE-Umschalter: klickbare Mini-Labels (aktiv teal,
        inaktiv grau)."""
        frame = ctk.CTkFrame(parent, fg_color='transparent')
        self._lang_labels = {}
        for col, lang in ((0, 'en'), (2, 'de')):
            lbl = ctk.CTkLabel(frame, text=lang.upper(), width=18,
                               font=ctk.CTkFont(size=11, weight='bold'),
                               cursor='hand2')
            lbl.grid(row=0, column=col)
            lbl.bind('<Button-1>',
                     lambda _e, lng=lang: self._on_lang_change(lng))
            self._lang_labels[lang] = lbl
        ctk.CTkLabel(frame, text='|', text_color=TEXT_MUTED,
                     font=ctk.CTkFont(size=10)).grid(row=0, column=1, padx=1)
        self._refresh_lang_toggle()
        return frame

    def _refresh_lang_toggle(self):
        cur = get_lang()
        for lang, lbl in getattr(self, '_lang_labels', {}).items():
            lbl.configure(text_color=(TEAL if lang == cur else TEXT_MUTED))

    def _on_lang_change(self, lang):
        """Schaltet die Sprache um, speichert sie und rendert das UI neu."""
        if lang == get_lang():
            return
        set_lang(lang)
        self.controller.set_language(lang)
        log.event('-', t('ui.language_changed', lang=lang))
        # Erst NACH dem Callback neu bauen (nicht das klickende Widget zerstoeren).
        self.after(10, self._rebuild_ui)

    def _rebuild_ui(self):
        """Baut Titelleiste + Shell in der aktuellen Sprache neu (Sprachwechsel).

        Der Laufzustand bleibt erhalten (steckt im BotController, nicht in den
        Widgets); die Log-Senke wird sauber ab- und wieder angehaengt. Footer
        (row 3) und Update-Banner (row 2) liegen auf eigenen Zeilen und werden
        NICHT zerstoert -- nur ihre Texte werden aufgefrischt.
        """
        try:
            self.log_panel.detach()
        except Exception:
            pass
        for widget in (getattr(self, 'topbar', None),
                       getattr(self, 'content', None)):
            if widget is not None:
                try:
                    widget.destroy()
                except Exception:
                    pass
        self._build_titlebar()
        self._build_content()
        self._show_view(self._active_view)
        self._apply_config_to_widgets()
        self._apply_window_prefs()
        self.sync_controls()
        if self._cfg['log']['show_in_ui']:
            self.log_panel.attach()
        # Update-Banner liegt auf einer eigenen Grid-Zeile -> NICHT zerstoert;
        # nur seine Texte neu setzen.
        if (getattr(self, '_update_info', None) is not None
                and getattr(self, '_update_banner', None) is not None):
            try:
                self._refresh_update_banner_text()
                self._update_btn.configure(text=t('ui.update_now'))
            except Exception:
                pass
        try:
            self.update_idletasks()
        except Exception:
            pass

    # -- Shell: Rail + Body ----------------------------------------------

    def _build_content(self):
        """Shell (row 1): Icon-Rail (col 0) + Body (col 1).

        ``self.content`` bleibt der Name (``_rebuild_ui`` zerstoert ihn).
        """
        self.content = ctk.CTkFrame(self, fg_color='transparent')
        self.content.grid(row=1, column=0, sticky='nsew')
        self.content.grid_columnconfigure(1, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self._build_rail(self.content)
        self._build_body(self.content)

    def _build_rail(self, parent):
        """Schmale Icon-Rail: Fishing/Puzzle/Console oben, Settings unten."""
        rail = ctk.CTkFrame(parent, width=60, corner_radius=0, fg_color=RAIL_BG)
        rail.grid(row=0, column=0, sticky='ns')
        rail.grid_propagate(False)
        rail.grid_columnconfigure(0, weight=1)
        # Top-Gruppe Fishing/Puzzle/Console/Roadmap (rows 0-3); die Spacer-Zeile
        # (row 4) waechst und drueckt Settings (row 5) nach ganz unten.
        rail.grid_rowconfigure(4, weight=1)

        self._rail_items = {}
        self._rail_dots = {}
        rows = {'fishing': 0, 'puzzle': 1, 'console': 2, 'roadmap': 3,
                'settings': 5}
        tip_keys = {'fishing': 'ui.view_fishing', 'puzzle': 'ui.view_puzzle',
                    'console': 'ui.view_console', 'roadmap': 'ui.view_roadmap',
                    'settings': 'ui.view_settings'}
        for view in RAIL_ORDER:
            btn = ctk.CTkButton(
                rail, text=RAIL_GLYPHS[view], width=42, height=42,
                corner_radius=12, font=ctk.CTkFont(size=18),
                fg_color='transparent', text_color=TEXT_FAINT,
                hover_color=RAIL_HOVER,
                command=lambda v=view: self._show_view(v))
            pad_top = 12 if rows[view] == 0 else 3
            pad_bottom = 10 if view == 'settings' else 3
            btn.grid(row=rows[view], column=0, pady=(pad_top, pad_bottom))
            self._rail_items[view] = btn
            try:
                Tooltip(btn, text=t(tip_keys[view]))
            except Exception:
                pass
            # Kleiner Lauf-Punkt, oben rechts auf dem Button (anfangs versteckt).
            dot = ctk.CTkLabel(btn, text='●', text_color=TEAL_BRIGHT,
                               fg_color='transparent',
                               font=ctk.CTkFont(size=9))
            self._rail_dots[view] = dot

    def _set_rail_active(self, view):
        """Hebt das aktive Rail-Item hervor (teal-Fill), die anderen neutral."""
        for name, btn in self._rail_items.items():
            try:
                if name == view:
                    btn.configure(fg_color=TEAL_SOFT, text_color=TEAL_BRIGHT)
                else:
                    btn.configure(fg_color='transparent',
                                  text_color=TEXT_FAINT)
            except Exception:
                pass

    def _update_running_dots(self, running, mode):
        """Zeigt den Lauf-Punkt auf dem aktiven Modus + Console, sonst versteckt."""
        show = {mode, 'console'} if running else set()
        for name, dot in self._rail_dots.items():
            try:
                if name in show:
                    dot.place(relx=0.72, y=4)
                else:
                    dot.place_forget()
            except Exception:
                pass

    def _build_body(self, parent):
        """Body (col 1): Command-Strip oben, getauschte Ansicht darunter."""
        body = ctk.CTkFrame(parent, fg_color='transparent')
        body.grid(row=0, column=1, sticky='nsew')
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)

        self._build_command_strip(body)

        self.panel_wrap = ctk.CTkFrame(body, fg_color=PANEL, corner_radius=0)
        self.panel_wrap.grid(row=1, column=0, sticky='nsew')
        self.panel_wrap.grid_columnconfigure(0, weight=1)
        self.panel_wrap.grid_rowconfigure(0, weight=1)

        self._views = {}
        self._build_fishing_view(self.panel_wrap)
        self._build_puzzle_view(self.panel_wrap)
        self._build_console_view(self.panel_wrap)
        self._build_roadmap_view(self.panel_wrap)
        self._build_settings_view(self.panel_wrap)

    # -- Command-Strip (Timer + START/STOP-Hero) -------------------------

    def _build_command_strip(self, parent):
        """Oberer Streifen: Lauf-Timer (links) + grosser START/STOP-Hero."""
        strip = ctk.CTkFrame(parent, fg_color=STRIP_BG, corner_radius=0)
        strip.grid(row=0, column=0, sticky='ew')
        strip.grid_columnconfigure(1, weight=1)

        # col 0 -- Timer-Block (Wert + Label).
        timer = ctk.CTkFrame(strip, fg_color='transparent', width=70)
        timer.grid(row=0, column=0, sticky='w', padx=(12, 6), pady=11)
        self.timer_val = ctk.CTkLabel(
            timer, text='00:00:00', text_color=TEXT,
            font=ctk.CTkFont(family='Consolas', size=14, weight='bold'))
        self.timer_val.grid(row=0, column=0)
        self.timer_lbl = ctk.CTkLabel(
            timer, text=t('ui.timer_idle'), text_color=TEXT_FAINT,
            font=ctk.CTkFont(size=9, weight='bold'))
        self.timer_lbl.grid(row=1, column=0)
        try:
            self._timer_tooltip = Tooltip(timer, text=t('ui.timer_tip_idle'))
        except Exception:
            self._timer_tooltip = None

        # col 1 -- Hero (gross, teal -> rot beim Laufen).
        self.hero_btn = ctk.CTkButton(
            strip, height=48, corner_radius=14,
            font=ctk.CTkFont(size=17, weight='bold'),
            fg_color=TEAL, hover_color=TEAL_HOVER, text_color=INK,
            text='▶  ' + t('ui.hero_start'),
            command=self._on_start_stop)
        self.hero_btn.grid(row=0, column=1, sticky='ew', padx=(6, 12), pady=11)

    # -- Ansichts-Kopf + die 4 Ansichten ---------------------------------

    def _view_header(self, parent, title, sub, badge=None):
        """Baut den 'view-head': Titel + dezenter Untertitel + optionale Pille."""
        head = ctk.CTkFrame(parent, fg_color='transparent')
        head.grid(row=0, column=0, sticky='ew', pady=(0, 6))
        head.grid_columnconfigure(2, weight=1)
        ctk.CTkLabel(head, text=title, text_color=TEXT,
                     font=ctk.CTkFont(size=14, weight='bold')).grid(
            row=0, column=0, sticky='w')
        ctk.CTkLabel(head, text=sub, text_color=TEXT_FAINT,
                     font=ctk.CTkFont(size=11)).grid(
            row=0, column=1, sticky='w', padx=(6, 0))
        if badge:
            ctk.CTkLabel(head, text=' ' + badge + ' ', text_color=TEAL_BRIGHT,
                         fg_color=TEAL_SOFT, corner_radius=999,
                         font=ctk.CTkFont(size=9, weight='bold')).grid(
                row=0, column=3, sticky='e')
        return head

    def _new_view(self, name):
        """Erzeugt einen Ansichts-Frame im panel_wrap (gestapelt, anfangs aus)."""
        view = ctk.CTkFrame(self.panel_wrap, fg_color='transparent')
        view.grid(row=0, column=0, sticky='nsew', padx=14, pady=(10, 8))
        view.grid_columnconfigure(0, weight=1)
        self._views[name] = view
        view.grid_remove()
        return view

    def _build_fishing_view(self, _parent):
        view = self._new_view('fishing')
        # Inhalt OBEN gruppiert: KEIN verteilender Zwischenraum -- alle Regler sitzen
        # kompakt am oberen Rand, der Rest-Leerraum sammelt sich ruhig UNTEN (row 2
        # bleibt leer -> kollabiert auf 0). Fenster bleibt fix auf der hoechsten View
        # (Settings) -- kein Springen beim Tab-Wechsel, keine Mittel-Luecke.
        self._view_header(view, t('ui.view_fishing'), t('ui.fishing_sub'),
                          badge=t('ui.badge_primary'))

        # Karte "Timing": die drei Delay-Slider mit ?-Hilfe.
        timing = Section(view, t('ui.delays_seconds'))
        timing.grid(row=1, column=0, sticky='ew', pady=(0, 10))
        tbody = timing.body

        self.bait_slider = LabeledSlider(
            tbody, t('ui.wait_to_put_bait'),
            default=self._cfg['fishing']['bait_time'],
            command=lambda v: self.controller.update_config(
                'fishing', 'bait_time', v))
        self.bait_slider.grid(row=0, column=0, sticky='ew', pady=4)
        InfoBadge(tbody, text=t('ui.bait_delay_help')).grid(
            row=0, column=1, sticky='ne', padx=(4, 0))

        self.throw_slider = LabeledSlider(
            tbody, t('ui.wait_to_throw'),
            default=self._cfg['fishing']['throw_time'],
            command=lambda v: self.controller.update_config(
                'fishing', 'throw_time', v))
        self.throw_slider.grid(row=1, column=0, sticky='ew', pady=4)
        InfoBadge(tbody, text=t('ui.throw_delay_help')).grid(
            row=1, column=1, sticky='ne', padx=(4, 0))

        self.start_slider = LabeledSlider(
            tbody, t('ui.wait_to_start_game'),
            default=self._cfg['fishing']['start_game_time'],
            command=lambda v: self.controller.update_config(
                'fishing', 'start_game_time', v))
        self.start_slider.grid(row=2, column=0, sticky='ew', pady=4)
        InfoBadge(tbody, text=t('ui.start_delay_help')).grid(
            row=2, column=1, sticky='ne', padx=(4, 0))

        # Stop-after-Zeile (Checkbox + Minuten + ?-Hilfe). Sitzt unter dem
        # flexiblen Zwischenraum (row 3).
        stop_row = ctk.CTkFrame(view, fg_color='transparent')
        stop_row.grid(row=3, column=0, sticky='ew', pady=(2, 8))
        stop_row.grid_columnconfigure(0, weight=1)
        self.stop_after_var = ctk.BooleanVar(
            value=self._cfg['fishing']['stop_after_enabled'])
        self.stop_after_chk = ctk.CTkCheckBox(
            stop_row, text=t('ui.stop_after_time_min'),
            variable=self.stop_after_var, text_color=TEXT, fg_color=TEAL,
            hover_color=TEAL_HOVER, command=self._on_stop_after_toggle)
        self.stop_after_chk.grid(row=0, column=0, sticky='w')
        InfoBadge(stop_row, text=t('ui.stop_after_help')).grid(
            row=0, column=1, sticky='e', padx=(4, 4))
        self.stop_after_entry = ctk.CTkEntry(
            stop_row, width=64, justify='center')
        self.stop_after_entry.grid(row=0, column=2, sticky='e')
        self.stop_after_entry.insert(
            0, str(self._cfg['fishing']['stop_after_minutes']))
        self.stop_after_entry.bind('<KeyRelease>', self._on_stop_minutes)

        # Golden-Tuna-Aktion: Labels '1'/'2'/'3' -> int-Werte (byte-stabil).
        self.golden_tuna_seg = SegmentedRow(
            view, label=t('ui.golden_tuna_action'), values=['1', '2', '3'],
            default=str(self._cfg['fishing']['golden_tuna_action']),
            command=self._on_golden_tuna_change,
            info=t('ui.golden_tuna_help'))
        self.golden_tuna_seg.grid(row=4, column=0, sticky='ew', pady=(0, 4))

    def _build_puzzle_view(self, _parent):
        view = self._new_view('puzzle')
        # Inhalt OBEN gruppiert: KEIN verteilender Zwischenraum (row 3 bleibt leer ->
        # kollabiert auf 0). Detection + Solver sitzen kompakt oben, Rest-Leerraum
        # sammelt sich ruhig unten. Fenster bleibt fix (keine Mittel-Luecke).
        self._view_header(view, t('ui.view_puzzle'), t('ui.puzzle_sub'),
                          badge=t('ui.badge_secondary'))

        # Karte "Detection": Detection-Modus + Color-Sampling. Die Modus-Labels
        # ('Default'/'Auto'/'Manual'|'Manuell') sind sprachabhaengig -> ueber
        # value<->label-Dicts gefuehrt (interner Enum bleibt 'mark'). Manuell
        # oeffnet bei Auswahl weiterhin das interaktive Mark-Overlay.
        detect = Section(view, t('ui.board_detection'))
        detect.grid(row=1, column=0, sticky='ew', pady=(0, 8))
        dbody = detect.body
        detection_pairs = _detection_pairs()
        self._detect_v2l = {value: label for value, label in detection_pairs}
        self._detect_l2v = {label: value for value, label in detection_pairs}
        self.detection_seg = SegmentedRow(
            dbody, label='',
            values=[label for _value, label in detection_pairs],
            default=self._detect_label_for(self._cfg['puzzle']['detection_mode']),
            command=self._on_detection_change,
            info=t('ui.detection_help'), info_image=REFERENCE_IMAGE,
            info_image_size=REFERENCE_IMAGE_SIZE)
        self.detection_seg.grid(row=0, column=0, sticky='ew', pady=(0, 6))
        self.color_seg = SegmentedRow(
            dbody, label=t('ui.color_sampling'), values=['Single', 'Multi'],
            default=self._cfg['puzzle']['color_mode'].capitalize(),
            command=self._on_color_change, info=t('ui.color_sampling_help'))
        self.color_seg.grid(row=1, column=0, sticky='ew')

        # Karte "Solver": Puzzle-Methode. (Der frueher hier sitzende "Brettbereich
        # markieren"-Knopf entfaellt -- Manuell oeffnet das Overlay direkt; die
        # "kein markierter Bereich"-Statuszeile entfaellt ebenfalls.)
        solver = Section(view, t('ui.puzzle_method'))
        solver.grid(row=2, column=0, sticky='ew', pady=(0, 8))
        sbody = solver.body
        solver_pairs = _solver_pairs()
        self._solver_v2l = {value: label for value, label in solver_pairs}
        self._solver_l2v = {label: value for value, label in solver_pairs}
        self.solver_seg = SegmentedRow(
            sbody, label='',
            values=[label for _value, label in solver_pairs],
            default=self._solver_label_for(self._cfg['puzzle']['solver_mode']),
            command=self._on_solver_change, info=t('ui.puzzle_method_help'))
        self.solver_seg.grid(row=0, column=0, sticky='ew')

    def _build_console_view(self, _parent):
        view = self._new_view('console')
        view.grid_rowconfigure(1, weight=1)
        self._view_header(view, t('ui.view_console'), t('ui.console_sub'))
        self.log_panel = LogPanel(view)
        self.log_panel.grid(row=1, column=0, sticky='nsew')
        # Winziger, BEWUSST unscheinbarer "Test Window"-Knopf unter dem Log:
        # spawnt das Fake-"METIN2"-Fenster, damit START auch ohne echtes Spiel
        # laeuft. Deutlich kleiner/schlichter als die echten Knoepfe (kein
        # Fill, kleine Schrift, gedaempfte Farben) -- reines Test-Hilfsmittel.
        self.test_window_btn = ctk.CTkButton(
            view, text=t('ui.test_window'), height=22, width=92,
            corner_radius=6, fg_color='transparent', hover_color=PANEL_HOVER,
            text_color=TEXT_FAINT, border_width=1, border_color=PANEL_LIGHT,
            font=ctk.CTkFont(size=10), command=self._on_test_window)
        self.test_window_btn.grid(row=2, column=0, sticky='e', pady=(6, 0))

    # -- Roadmap (read-only, geplante Features; DARF scrollen) ------------

    # Gruppen + ihre Items (Uebersetzungs-Keys). Reine Anzeige -- keine Logik.
    ROADMAP_GROUPS = (
        ('ui.roadmap_group_recognition',
         ('ui.roadmap_rec_inv_pages', 'ui.roadmap_rec_inv_slots',
          'ui.roadmap_rec_key_items', 'ui.roadmap_rec_carbon_rod')),
        ('ui.roadmap_group_automation',
         ('ui.roadmap_auto_bait', 'ui.roadmap_auto_boxes',
          'ui.roadmap_auto_switch', 'ui.roadmap_auto_multiwin')),
        ('ui.roadmap_group_stats',
         ('ui.roadmap_stats_puzzle', 'ui.roadmap_stats_fishing',
          'ui.roadmap_stats_inventory')),
        ('ui.roadmap_group_info',
         ('ui.roadmap_info_tuna', 'ui.roadmap_info_event_end',
          'ui.roadmap_info_calc')),
    )

    def _build_roadmap_view(self, _parent):
        """Baut die Roadmap-Sicht: gruppierte, read-only Liste geplanter Features
        mit dezenten "geplant"-Chips. EINZIGE scrollbare Sicht (Info-Liste, keine
        Steuerung) -- ``CTkScrollableFrame`` faengt ueberlange Inhalte ab."""
        view = self._new_view('roadmap')
        view.grid_rowconfigure(1, weight=1)
        self._view_header(view, t('ui.view_roadmap'), t('ui.roadmap_sub'),
                          badge=t('ui.roadmap_chip'))

        scroller = ctk.CTkScrollableFrame(view, fg_color='transparent')
        scroller.grid(row=1, column=0, sticky='nsew')
        scroller.grid_columnconfigure(0, weight=1)

        for row, (group_key, item_keys) in enumerate(self.ROADMAP_GROUPS):
            card = Section(scroller, t(group_key))
            pad_bottom = 8 if row < len(self.ROADMAP_GROUPS) - 1 else 0
            card.grid(row=row, column=0, sticky='ew', pady=(0, pad_bottom))
            body = card.body
            for i, item_key in enumerate(item_keys):
                self._roadmap_item(body, i, t(item_key))

    def _roadmap_item(self, parent, row, text):
        """Eine Roadmap-Zeile: Item-Text (links, umbrechend) + "geplant"-Chip
        (rechts, kleine Pille). Read-only -- keine Buttons/Commands."""
        line = ctk.CTkFrame(parent, fg_color='transparent')
        line.grid(row=row, column=0, sticky='ew', pady=2)
        line.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(line, text=text, anchor='w', justify='left',
                     text_color=TEXT, font=ctk.CTkFont(size=12),
                     wraplength=300).grid(row=0, column=0, sticky='w')
        ctk.CTkLabel(line, text=' ' + t('ui.roadmap_chip') + ' ',
                     text_color=TEAL_BRIGHT, fg_color=TEAL_SOFT,
                     corner_radius=999,
                     font=ctk.CTkFont(size=9, weight='bold')).grid(
            row=0, column=1, sticky='e', padx=(6, 0))

    def _build_settings_view(self, _parent):
        view = self._new_view('settings')
        self._view_header(view, t('ui.view_settings'), t('ui.settings_sub'))

        # -- Karte "Shutdown" (Settings #3 + #4) ------------------------
        shutdown = Section(view, t('ui.group_shutdown'))
        shutdown.grid(row=1, column=0, sticky='ew', pady=(0, 4))
        sbody = shutdown.body
        self._close_metin2_var = ctk.BooleanVar(
            value=self._cfg['window']['close_on_metin2_close'])
        self._switch_row(
            sbody, 0, t('ui.close_on_metin2'), None, t('ui.close_on_metin2_help'),
            self._close_metin2_var,
            lambda: self._on_window_toggle('close_on_metin2_close',
                                           self._close_metin2_var))
        self._close_timer_var = ctk.BooleanVar(
            value=self._cfg['window']['close_on_timer_expire'])
        self._switch_row(
            sbody, 1, t('ui.close_on_timer'), None, t('ui.close_on_timer_help'),
            self._close_timer_var,
            lambda: self._on_window_toggle('close_on_timer_expire',
                                           self._close_timer_var))

        # -- Karte "Fishing hotkeys" (Settings #5) ----------------------
        hotkeys = Section(view, t('ui.group_hotkeys'))
        hotkeys.grid(row=2, column=0, sticky='ew', pady=(0, 4))
        hbody = hotkeys.body
        hbody.grid_columnconfigure(0, weight=1)
        self.bait_key_btn = self._key_row(
            hbody, 0, t('ui.bait_key'), t('ui.bait_key_sub'),
            t('ui.hotkeys_help'), 'bait',
            self._cfg['fishing']['bait_key'])
        self.cast_key_btn = self._key_row(
            hbody, 1, t('ui.cast_key'), t('ui.cast_key_sub'),
            None, 'cast', self._cfg['fishing']['cast_key'])

        # -- Karte "Window" (Settings #2 + #1) --------------------------
        window = Section(view, t('ui.group_window'))
        window.grid(row=3, column=0, sticky='ew', pady=(0, 2))
        wbody = window.body
        self._always_top_var = ctk.BooleanVar(
            value=self._cfg['window']['always_on_top'])
        self._switch_row(
            wbody, 0, t('ui.always_on_top'), None, t('ui.always_on_top_help'),
            self._always_top_var, self._on_always_top_toggle)
        self._tray_var = ctk.BooleanVar(
            value=self._cfg['window']['minimize_to_tray'])
        tray_ok = tray.available()
        tray_sub = None if tray_ok else t('ui.tray_unavailable')
        self._tray_switch = self._switch_row(
            wbody, 1, t('ui.minimize_to_tray'), tray_sub,
            t('ui.minimize_to_tray_help'), self._tray_var,
            self._on_tray_toggle, return_switch=True)
        if not tray_ok:
            try:
                self._tray_switch.configure(state='disabled')
            except Exception:
                pass

        # Overlay-Deckkraft: kleiner Slider (0.4..1.0) + Live-%-Wert + ?-Hilfe,
        # in die Window-Karte gefaltet (kein eigener Kartenkopf -> balanciert die
        # Settings-Hoehe). Steuert die Transparenz von Mark-/Vorschau-Overlay.
        self._build_opacity_row(wbody, 2)

        # -- Reset-Zeile (Item K) ---------------------------------------
        # Bewusst SEKUNDAER (transparent + duenner Rand, gedaempfte Schrift, klein
        # + rechtsbuendig) -- kein teal/roter Hero-Knopf. "?"-Hilfe links daneben.
        # Setzt nach Bestaetigung ALLES auf die Auslieferungs-Standardwerte; nur
        # im Leerlauf (Idle-Guard im Handler + sync_controls-Sperre).
        reset_row = ctk.CTkFrame(view, fg_color='transparent')
        reset_row.grid(row=4, column=0, sticky='ew', pady=(4, 0))
        reset_row.grid_columnconfigure(0, weight=1)
        InfoBadge(reset_row, text=t('ui.reset_settings_help')).grid(
            row=0, column=1, sticky='e', padx=(0, 6))
        self.reset_btn = ctk.CTkButton(
            reset_row, text=t('ui.reset_settings'), height=28, width=180,
            corner_radius=8, fg_color='transparent', hover_color=DANGER_SOFT,
            text_color=TEXT_MUTED, border_width=1, border_color=TEAL_DARK,
            font=ctk.CTkFont(size=11), command=self._on_reset_settings)
        self.reset_btn.grid(row=0, column=2, sticky='e')

    def _build_opacity_row(self, parent, row):
        """Baut die Overlay-Deckkraft-Zeile (Label + ?-Hilfe + Slider + %-Wert).

        Eigener ``CTkSlider`` statt ``LabeledSlider`` (das ist auf 0.1..20.0/'s'
        festverdrahtet). Bereich 0.4..1.0 in 0.05-Schritten; der Wert wird live
        als Prozent gezeigt und ueber ``_on_opacity_change`` in der Config
        gesichert."""
        frame = ctk.CTkFrame(parent, fg_color='transparent')
        frame.grid(row=row, column=0, sticky='ew', pady=3)
        frame.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(frame, fg_color='transparent')
        head.grid(row=0, column=0, sticky='ew')
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(head, text=t('ui.overlay_opacity'), anchor='w',
                     text_color=TEXT, font=ctk.CTkFont(size=12)).grid(
            row=0, column=0, sticky='w')
        InfoBadge(head, text=t('ui.overlay_opacity_help')).grid(
            row=0, column=1, sticky='e', padx=(4, 4))
        self._opacity_value = ctk.CTkLabel(
            head, text='', anchor='e', text_color=TEAL,
            font=ctk.CTkFont(size=13, weight='bold'))
        self._opacity_value.grid(row=0, column=2, sticky='e')

        lo = cfgmod.OVERLAY_OPACITY_MIN
        hi = cfgmod.OVERLAY_OPACITY_MAX
        steps = max(1, int(round((hi - lo) / 0.05)))
        self._opacity_slider = ctk.CTkSlider(
            frame, from_=lo, to=hi, number_of_steps=steps,
            progress_color=TEAL, button_color=TEAL,
            button_hover_color=TEAL_HOVER, command=self._on_opacity_change)
        self._opacity_slider.grid(row=1, column=0, sticky='ew', pady=(2, 0))
        self._opacity_slider.set(self._overlay_alpha())
        self._refresh_opacity_value()

    def _refresh_opacity_value(self):
        """Schreibt den aktuellen Slider-Wert als Prozent neben das Label."""
        try:
            pct = int(round(float(self._opacity_slider.get()) * 100))
            self._opacity_value.configure(text='{}%'.format(pct))
        except Exception:
            pass

    def _on_opacity_change(self, value):
        """Slider bewegt: Deckkraft (gerundet) in der Config sichern + %-Anzeige."""
        try:
            self._cfg = self.controller.update_config(
                'puzzle', 'overlay_opacity', round(float(value), 2))
        except Exception:
            pass
        self._refresh_opacity_value()

    def _switch_row(self, parent, row, label, sub, help_text, variable,
                    command, return_switch=False):
        """Eine Settings-Zeile: Label(+Untertitel) + ?-Hilfe + CTkSwitch.

        Gibt standardmaessig den Zeilen-Frame zurueck (oder den Switch, wenn
        ``return_switch``)."""
        frame = ctk.CTkFrame(parent, fg_color='transparent')
        frame.grid(row=row, column=0, sticky='ew', pady=3)
        frame.grid_columnconfigure(0, weight=1)
        text_col = ctk.CTkFrame(frame, fg_color='transparent')
        text_col.grid(row=0, column=0, sticky='w')
        ctk.CTkLabel(text_col, text=label, anchor='w', text_color=TEXT,
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, sticky='w')
        if sub:
            ctk.CTkLabel(text_col, text=sub, anchor='w', text_color=TEXT_FAINT,
                         font=ctk.CTkFont(size=10)).grid(
                row=1, column=0, sticky='w')
        if help_text:
            InfoBadge(frame, text=help_text).grid(row=0, column=1, padx=(4, 4))
        switch = ctk.CTkSwitch(
            frame, text='', variable=variable, command=command,
            progress_color=TEAL, button_color=TEXT_FAINT,
            button_hover_color=TEAL_HOVER, width=40)
        switch.grid(row=0, column=2, sticky='e')
        return switch if return_switch else frame

    def _key_row(self, parent, row, label, sub, help_text, which, current):
        """Eine Hotkey-Zeile: Label(+Untertitel) + ?-Hilfe + Key-Capture-Button."""
        frame = ctk.CTkFrame(parent, fg_color='transparent')
        frame.grid(row=row, column=0, sticky='ew', pady=3)
        frame.grid_columnconfigure(0, weight=1)
        text_col = ctk.CTkFrame(frame, fg_color='transparent')
        text_col.grid(row=0, column=0, sticky='w')
        ctk.CTkLabel(text_col, text=label, anchor='w', text_color=TEXT,
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, sticky='w')
        if sub:
            ctk.CTkLabel(text_col, text=sub, anchor='w', text_color=TEXT_FAINT,
                         font=ctk.CTkFont(size=10)).grid(
                row=1, column=0, sticky='w')
        if help_text:
            InfoBadge(frame, text=help_text).grid(row=0, column=1, padx=(4, 4))
        btn = ctk.CTkButton(
            frame, text=str(current).upper(), width=54, height=30,
            corner_radius=8, fg_color=PANEL_LIGHT, hover_color=PANEL_HOVER,
            text_color=TEXT, font=ctk.CTkFont(family='Consolas', size=13,
                                              weight='bold'),
            command=lambda: self._start_key_capture(which))
        btn.grid(row=0, column=2, sticky='e')
        return btn

    # -- View-Umschaltung ------------------------------------------------

    def _show_view(self, view):
        """Tauscht die sichtbare Ansicht + setzt (im Leerlauf) den Lauf-Modus."""
        self._active_view = view
        for name, frame in self._views.items():
            if name == view:
                frame.grid()
            else:
                frame.grid_remove()
        self._set_rail_active(view)
        # XOR-Lauf-Modus: Fishing/Puzzle waehlen (im Leerlauf) setzt den Modus.
        if view in ('fishing', 'puzzle') and not self.controller.running:
            self.controller.set_mode(view)
            self._cfg = self.controller.current_config()
        self.sync_controls()   # Hero-Text + Lauf-Punkte fuer den neuen Modus

    # -- Event-Handler ----------------------------------------------------

    def _on_start_stop(self):
        self.controller.on_start_stop()

    def _on_stop_after_toggle(self):
        self._cfg = self.controller.update_config(
            'fishing', 'stop_after_enabled', bool(self.stop_after_var.get()))

    def _on_stop_minutes(self, _event=None):
        raw = self.stop_after_entry.get().strip()
        try:
            minutes = int(raw) if raw else 0
        except ValueError:
            minutes = 0
        self._cfg = self.controller.update_config(
            'fishing', 'stop_after_minutes', minutes)

    def _on_golden_tuna_change(self, label):
        try:
            action = int(label)
        except (TypeError, ValueError):
            action = 3
        self._cfg = self.controller.update_config(
            'fishing', 'golden_tuna_action', action)

    def _on_detection_change(self, label):
        """Detection-Modus gewaehlt: Wert sichern + passende Sicht-Hilfe zeigen.

        Nur bei echtem NUTZER-Klick aufgerufen (``Segmented._select``); ``set()``
        aus Config-Laden/Sprachwechsel/Startup loest den Command NICHT aus -> kein
        Overlay beim Laden (byte-stabiles Default-Verhalten bleibt erhalten).

          * Default        -> 5s-Vorschau an der FESTEN Standard-Brettlage (270,227),
          * Auto           -> Board automatisch erkennen, DANN 5s-Vorschau am Treffer,
          * Manuell ('mark')-> JEDES Mal das interaktive Mark-Overlay oeffnen.

        Waehrend eines Laufs werden keine Overlays gestartet (die Segmente sind
        dann ohnehin gesperrt). Jeder Vorschau-/Mark-Aufruf ist defensiv -- ein
        Overlay-Fehler darf das Umschalten nie unterbrechen.
        """
        mode = self._detect_l2v.get(label, cfgmod.DETECTION_MODES[0])
        self._cfg = self.controller.update_config('puzzle', 'detection_mode',
                                                  mode)
        if self.controller.running:
            return
        if mode == 'default':
            self._preview_default()
        elif mode == 'auto':
            self._preview_auto()
        elif mode == 'mark':
            self._open_mark_overlay()

    def _overlay_alpha(self):
        """Aktuelle Overlay-Deckkraft aus der Config (defensiv, mit Fallback)."""
        try:
            return float(self._cfg['puzzle']['overlay_opacity'])
        except Exception:
            return cfgmod.DEFAULTS['puzzle']['overlay_opacity']

    def _preview_default(self):
        """Zeigt ~5s die Vorschau an der FESTEN Standard-Brettlage (270,227).

        So prueft der Nutzer, ob sein 800x600-Spielfenster zur Default-Position
        passt. Strikt defensiv: ein Fehler wird geloggt, das Umschalten laeuft
        weiter."""
        try:
            import detection
            import overlay_preview
            overlay_preview.show_preview(
                detection.DEFAULT_OFFSET, board_size=detection.BOARD_SIZE,
                alpha=self._overlay_alpha())
            log.event('-', t('ui.preview_default_shown'))
        except Exception as exc:
            log.error(t('preview.unavailable'), exc=exc)

    def _preview_auto(self):
        """Erkennt das Board automatisch und zeigt dann die 5s-Vorschau am Treffer.

        Ohne echtes Spiel-Fenster (kein Screenshot) wird klar geloggt und
        uebersprungen. Findet die Erkennung nichts Eindeutiges (Fallback auf den
        Default), kommt zusaetzlich ein Hinweis, dass Auto ein echtes Brett am
        Bildschirm braucht -- die Vorschau wird trotzdem am gelieferten Offset
        gezeigt. Strikt defensiv."""
        try:
            import detection
            import overlay_preview
            try:
                from windowcapture import WindowCapture

                import constants
                shot = WindowCapture(constants.GAME_NAME).get_screenshot()
            except Exception:
                log.event('-', t('ui.preview_auto_no_window'))
                return
            offset = detection.resolve_offset(
                'auto', screenshot=shot,
                default_offset=detection.DEFAULT_OFFSET)
            if tuple(offset) == tuple(detection.DEFAULT_OFFSET):
                # Auto fiel auf den Default zurueck -> Erkennung war nicht
                # eindeutig. Vorschau trotzdem zeigen, aber Grund nennen.
                log.event('-', t('ui.preview_auto_failed'))
            overlay_preview.show_preview(
                offset, board_size=detection.BOARD_SIZE,
                alpha=self._overlay_alpha())
        except Exception as exc:
            log.error(t('preview.unavailable'), exc=exc)

    def _open_mark_overlay(self):
        """Oeffnet das interaktive Mark-Overlay (Item E -- jeder Manuell-Wechsel).

        Reine Wiederverwendung von :meth:`_on_mark` (dieselbe Persistenz).
        ``detection_seg.set(<Manuell-Label>)`` dort feuert den Command NICHT
        erneut -> keine Endlosschleife."""
        self._on_mark()

    def _on_color_change(self, label):
        self._cfg = self.controller.update_config(
            'puzzle', 'color_mode', label.lower())

    def _on_solver_change(self, label):
        value = self._solver_l2v.get(label, cfgmod.SOLVER_MODES[0])
        self._cfg = self.controller.update_config('puzzle', 'solver_mode', value)

    def _on_test_window(self):
        """Oeffnet das selbst-enthaltene Fake-"METIN2"-Testfenster (800x600).

        Damit findet ``FindWindow(None,'METIN2')`` ein Ziel und START laeuft
        trocken (Capture/Farb-/Board-Erkennung), ohne das echte Spiel. Strikt
        defensiv: ohne Display/bei Fehler nur ein Log-Hinweis, kein Crash."""
        try:
            from interface import testwindow
            self._test_window = testwindow.open_test_window(self)
            log.event('-', t('ui.test_window_opened'))
        except Exception as exc:
            log.error(t('ui.test_window_failed'), exc=exc)

    def _on_mark(self):
        """Oeffnet das Mark-Overlay (Modul B) und speichert die Kalibrierung.

        Wird ueber die Detection-Auswahl 'Manuell'/'Manual' (Enum 'mark')
        ausgeloest. Das fruehere "kein markierter Bereich"-Statuslabel entfaellt
        (Item J) -- ist das Overlay nicht verfuegbar, geht der Hinweis nur ins
        Log (Fehlerpfad), nicht als Dauer-Hinweis ins UI."""
        try:
            from overlay_mark import pick_offset_interactive
        except Exception as exc:
            log.error(t('ui.mark_overlay_unavailable_log'), exc=exc)
            return
        try:
            result = pick_offset_interactive(alpha=self._overlay_alpha())
        except Exception as exc:
            log.error(t('ui.mark_overlay_failed'), exc=exc)
            result = None
        if result is not None:
            self._persist_mark_result(result)
            self._cfg = self.controller.update_config(
                'puzzle', 'detection_mode', 'mark')
            self.detection_seg.set(self._detect_label_for('mark'))

    def _persist_mark_result(self, result):
        offset = result.get('offset')
        if offset is not None:
            self._cfg = self.controller.update_config(
                'puzzle', 'mark_offset', [int(offset[0]), int(offset[1])])

        size = result.get('size')
        mark_size = None
        if size is not None:
            try:
                mark_size = [int(size[0]), int(size[1])]
            except (TypeError, ValueError, IndexError):
                mark_size = None
        self._cfg = self.controller.update_config(
            'puzzle', 'mark_size', mark_size)

        key_points = result.get('key_points') or {}
        mark_keypoints = {}
        try:
            for name, point in key_points.items():
                mark_keypoints[name] = [int(point[0]), int(point[1])]
        except (TypeError, ValueError, IndexError, AttributeError):
            mark_keypoints = {}
        self._cfg = self.controller.update_config(
            'puzzle', 'mark_keypoints', mark_keypoints)

    # -- Settings: Reset auf Standard (Item K) ---------------------------

    def _on_reset_settings(self):
        """Setzt nach Bestaetigung ALLE Einstellungen auf die Standardwerte.

        Idle-only: laeuft der Bot, kommt nur ein kurzer Hinweis (der Laufzustand
        wird NICHT angetastet). Sonst oeffnet sich ein dunkler Bestaetigungs-
        Dialog (eigenes CTkToplevel, passt zum Theme -- KEIN tkinter.messagebox);
        bestaetigt der Nutzer, baut ``reset_to_defaults`` die Config frisch,
        speichert sie, und das UI wird (mit ggf. gewechselter Sprache) neu
        aufgebaut, sodass alle Widgets sofort die Defaults zeigen. Strikt
        defensiv: scheitert der Dialog-Aufbau, passiert nichts (kein Reset)."""
        if self.controller.running:
            self._flash_note(t('ui.reset_blocked_running'), AMBER)
            return
        self._confirm_dialog(
            title=t('ui.reset_confirm_title'), body=t('ui.reset_confirm_body'),
            ok_text=t('ui.reset_confirm_yes'),
            cancel_text=t('ui.reset_confirm_cancel'),
            on_ok=self._do_reset_settings, danger=True)

    def _do_reset_settings(self):
        """Fuehrt den eigentlichen Reset aus (nach Bestaetigung)."""
        if not self.controller.reset_to_defaults():
            return
        self._cfg = self.controller.current_config()
        # Sprache (kann sich auf Default 'en' geaendert haben) live anwenden +
        # komplettes UI neu aufbauen -> alle Widgets zeigen sofort die Defaults.
        set_lang(self._cfg['language'])
        self.after(10, self._rebuild_ui)
        self.flash_saved()

    def _flash_note(self, text, color):
        """Zeigt kurz (~3 s) eine Meldung in der Detection-Note (Feedback-Slot)."""
        try:
            self.detect_note.configure(text=text, text_color=color)
            if self._saved_job is not None:
                self.after_cancel(self._saved_job)
            self._saved_job = self.after(3000, self._refresh_detect_note)
        except Exception:
            pass

    def _confirm_dialog(self, title, body, ok_text, cancel_text, on_ok,
                        danger=False):
        """Kleiner, dunkler Ja/Nein-Bestaetigungsdialog (eigenes CTkToplevel).

        Passt zum Teal/Dark-Theme (kein graues ``tkinter.messagebox``). Modal
        ueber ``transient`` + ``grab_set``. ``on_ok`` wird nur bei Bestaetigung
        gerufen. Strikt defensiv -- schlaegt der Aufbau fehl, passiert nichts."""
        try:
            dlg = ctk.CTkToplevel(self)
            dlg.title(title)
            dlg.configure(fg_color=BG)
            dlg.resizable(False, False)
            dlg.geometry('340x150')
            try:
                dlg.transient(self)
            except Exception:
                pass
            dlg.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(dlg, text=title, text_color=TEXT,
                         font=ctk.CTkFont(size=14, weight='bold')).grid(
                row=0, column=0, sticky='w', padx=16, pady=(16, 4))
            ctk.CTkLabel(dlg, text=body, text_color=TEXT_MUTED, justify='left',
                         wraplength=300, font=ctk.CTkFont(size=12)).grid(
                row=1, column=0, sticky='w', padx=16, pady=(0, 12))

            btns = ctk.CTkFrame(dlg, fg_color='transparent')
            btns.grid(row=2, column=0, sticky='e', padx=16, pady=(0, 14))

            def _close():
                try:
                    dlg.grab_release()
                except Exception:
                    pass
                try:
                    dlg.destroy()
                except Exception:
                    pass

            def _confirm():
                _close()
                try:
                    on_ok()
                except Exception:
                    pass

            ctk.CTkButton(
                btns, text=cancel_text, width=90, height=30, corner_radius=8,
                fg_color='transparent', hover_color=PANEL_HOVER,
                text_color=TEXT_MUTED, border_width=1, border_color=PANEL_LIGHT,
                command=_close).grid(row=0, column=0, padx=(0, 8))
            ctk.CTkButton(
                btns, text=ok_text, width=110, height=30, corner_radius=8,
                fg_color=(DANGER if danger else TEAL),
                hover_color=(DANGER_HOVER if danger else TEAL_HOVER),
                text_color=('#fff' if danger else INK),
                command=_confirm).grid(row=0, column=1)

            dlg.protocol('WM_DELETE_WINDOW', _close)
            try:
                dlg.after(60, dlg.grab_set)   # nach dem Mappen modal greifen
                dlg.lift()
            except Exception:
                pass
        except Exception:
            pass

    # -- Settings: Laufzeit-Effekte + Tray-Lifecycle ---------------------

    def _on_window_toggle(self, key, variable):
        """Schreibt eine reine window-Bool-Option (close-on-*) in die Config."""
        self._cfg = self.controller.update_config(
            'window', key, bool(variable.get()))

    def _on_always_top_toggle(self):
        on = bool(self._always_top_var.get())
        self._cfg = self.controller.update_config('window', 'always_on_top', on)
        self._apply_always_on_top(on)

    def _on_tray_toggle(self):
        on = bool(self._tray_var.get())
        self._cfg = self.controller.update_config(
            'window', 'minimize_to_tray', on)
        self._tray_enabled = on and tray.available()

    def _apply_always_on_top(self, on):
        try:
            self.attributes('-topmost', bool(on))
        except Exception:
            pass

    def _apply_window_prefs(self):
        """Wendet die gespeicherten Fenster-Optionen an (Startup + Neuaufbau)."""
        try:
            window = self._cfg['window']
            self._apply_always_on_top(window['always_on_top'])
            self._tray_enabled = (window['minimize_to_tray']
                                  and tray.available())
        except Exception:
            pass

    def _on_unmap(self, _event=None):
        """Beim Minimieren ggf. in den Tray statt in die Taskleiste."""
        try:
            if self._tray_enabled and self.state() == 'iconic':
                self._hide_to_tray()
        except Exception:
            pass

    def _hide_to_tray(self):
        """Versteckt das Fenster und zeigt ein Tray-Icon. Strikt defensiv:
        schlaegt etwas fehl, bleibt es ein normales Minimieren (kein Crash)."""
        try:
            if self._tray_icon is not None:
                return
            icon = tray.make_icon(
                ICON_FILE, t('ui.window_title'),
                on_show=lambda: self.after(0, self._restore_from_tray),
                on_quit=lambda: self.after(0, self._on_close),
                show_text=t('ui.tray_show'), quit_text=t('ui.tray_quit'))
            if icon is None:
                return
            self._tray_icon = icon
            self.withdraw()
            icon.run_detached()
        except Exception:
            # Tray-Aufbau gescheitert -> normales Minimieren beibehalten.
            try:
                self.deiconify()
            except Exception:
                pass

    def _restore_from_tray(self):
        """Holt das Fenster aus dem Tray zurueck und stoppt das Icon."""
        try:
            self.deiconify()
            self.lift()
        except Exception:
            pass
        try:
            if self._tray_icon is not None:
                self._tray_icon.stop()
        except Exception:
            pass
        self._tray_icon = None

    # -- Key-Capture (Fishing-Hotkeys) -----------------------------------

    def _start_key_capture(self, which):
        """Startet die Tasten-Aufnahme fuer 'bait'/'cast': Feld -> '...Taste'."""
        try:
            btn = self.bait_key_btn if which == 'bait' else self.cast_key_btn
            self._capturing = (which, btn)
            btn.configure(text=t('ui.key_capture_prompt'), fg_color=TEAL_SOFT,
                          text_color=TEAL_BRIGHT)
            self.bind('<Key>', self._on_key_capture, add='+')
        except Exception:
            self._capturing = None

    def _on_key_capture(self, event):
        """Nimmt einen Tastendruck als Hotkey ab. Esc bricht ab; ungueltige
        Eingaben fallen via _validate_key auf den bisherigen Wert zurueck."""
        if self._capturing is None:
            return
        which, btn = self._capturing
        try:
            keysym = (event.keysym or '').lower()
            if keysym in ('escape',):
                self._end_key_capture(which, btn)
                return
            if keysym == 'space':
                token = 'space'
            elif len(event.char) == 1 and event.char.strip():
                token = event.char.lower()
            elif len(keysym) == 1:
                token = keysym
            else:
                token = keysym
            current = self._cfg['fishing'][which + '_key']
            key = cfgmod._validate_key(token, current)
            self._cfg = self.controller.update_config(
                'fishing', which + '_key', key)
        except Exception:
            pass
        self._end_key_capture(which, btn)

    def _end_key_capture(self, which, btn):
        """Beendet die Aufnahme: Anzeige zuruecksetzen, Binding loesen."""
        try:
            self.unbind('<Key>')
        except Exception:
            pass
        self._capturing = None
        try:
            btn.configure(text=str(self._cfg['fishing'][which + '_key']).upper(),
                          fg_color=PANEL_LIGHT, text_color=TEXT)
        except Exception:
            pass

    # -- Schliessen -------------------------------------------------------

    def _on_close(self):
        try:
            cfgmod.save(self.controller.current_config())
        except Exception:
            pass
        try:
            if self._tray_icon is not None:
                self._tray_icon.stop()
        except Exception:
            pass
        try:
            self.log_panel.detach()
        except Exception:
            pass
        self.destroy()

    # -- UI-Synchronisierung ---------------------------------------------

    def sync_controls(self):
        """Spiegelt den Laufzustand ins UI (Hero, Rail-Punkte, Sperren).

        Waehrend des Laufs: Fishing-/Puzzle-Einstellungen gesperrt, Hero rot
        ('Stop - <Modus>'), Lauf-Punkt auf dem aktiven Modus + Console. Settings
        (App-Praeferenzen) bleiben IMMER aktiv. Wird von set_running,
        _rebuild_ui, __init__ und jedem Tick (sync_button) gerufen.
        """
        running = self.controller.running
        mode = self.controller.mode

        # Lauf-Start fuer den Timer stempeln (false->true-Flanke).
        if running and not self._was_running:
            self._run_started_at = time.time()
        self._was_running = running

        # Hero-Text/Farbe.
        if running:
            key = ('ui.hero_stop_puzzle' if mode == 'puzzle'
                   else 'ui.hero_stop_fishing')
            self.hero_btn.configure(text='■  ' + t(key), fg_color=DANGER,
                                    hover_color=DANGER_HOVER, text_color='#fff')
        else:
            self.hero_btn.configure(text='▶  ' + t('ui.hero_start'),
                                    fg_color=TEAL, hover_color=TEAL_HOVER,
                                    text_color=INK)

        # Rail-Lauf-Punkte.
        self._update_running_dots(running, mode)

        # Fishing-/Puzzle-Steuerungen waehrend des Laufs sperren.
        for slider in (self.bait_slider, self.throw_slider, self.start_slider):
            slider.set_enabled(not running)
        for seg in (self.golden_tuna_seg, self.detection_seg,
                    self.color_seg, self.solver_seg):
            seg.set_enabled(not running)
        state = 'normal' if not running else 'disabled'
        self.stop_after_chk.configure(state=state)
        self.stop_after_entry.configure(state=state)
        # Reset-Knopf (Settings, Item K) nur im Leerlauf -- belt-and-suspenders
        # zum Idle-Guard in _on_reset_settings.
        try:
            self.reset_btn.configure(state=state)
        except Exception:
            pass
        # Settings-Schalter bleiben aktiv (kein Konflikt mit dem Lauf).

    def sync_button(self):
        self.sync_controls()

    # -- Live-Lauf-Timer --------------------------------------------------

    def _tick_timer(self):
        """Aktualisiert die Timer-Anzeige 1x/Sekunde (immer aktiv, guenstig).

        Laeuft der Bot: Countdown der Restzeit (bei Zeitlimit) bzw. Hochzaehlen
        der Laufzeit. Im Leerlauf: Vorschau (Limit-Wert oder 00:00:00). Die
        Anzeige liest DIESELBE Config wie der Bot -- der echte Stop kommt aus
        hack._tick; diese Anzeige ist rein darstellend."""
        try:
            running = self.controller.running
            fishing = self._cfg['fishing']
            limit_on = (fishing['stop_after_enabled']
                        and fishing['stop_after_minutes'] > 0)
            if running:
                elapsed = time.time() - self._run_started_at
                if limit_on:
                    left = max(0, fishing['stop_after_minutes'] * 60 - elapsed)
                    self.timer_val.configure(text=_mmss(left))
                    self.timer_lbl.configure(text=t('ui.timer_left'))
                    self._timer_tip(t('ui.timer_tip_running',
                                      elapsed=_hms(elapsed), left=_mmss(left)))
                else:
                    self.timer_val.configure(text=_hms(elapsed))
                    self.timer_lbl.configure(text=t('ui.timer_elapsed'))
                    self._timer_tip(t('ui.timer_tip_countup',
                                      elapsed=_hms(elapsed)))
            else:
                if limit_on:
                    self.timer_val.configure(
                        text=_mmss(fishing['stop_after_minutes'] * 60))
                    self.timer_lbl.configure(text=t('ui.timer_limit'))
                    self._timer_tip(t('ui.timer_tip_limit',
                                      min=fishing['stop_after_minutes']))
                else:
                    self.timer_val.configure(text='00:00:00')
                    self.timer_lbl.configure(text=t('ui.timer_idle'))
                    self._timer_tip(t('ui.timer_tip_idle'))
        except Exception:
            pass
        try:
            self.after(1000, self._tick_timer)
        except Exception:
            pass

    def _timer_tip(self, text):
        """Setzt den Hover-Text des Timer-Tooltips (ohne Neuaufbau)."""
        try:
            if self._timer_tooltip is not None:
                self._timer_tooltip._text = text
        except Exception:
            pass

    # -- Status-/Detection-Note (unten rechts) ---------------------------

    def flash_saved(self):
        """Zeigt kurz "saved" in der Detection-Note (nur im Ruhezustand)."""
        if self.controller.running:
            return
        try:
            self.detect_note.configure(text=t('ui.status_saved'),
                                       text_color=TEAL)
            if self._saved_job is not None:
                self.after_cancel(self._saved_job)
            self._saved_job = self.after(1200, self._refresh_detect_note)
        except Exception:
            pass

    def _refresh_detect_note(self):
        """Erkennungsnote unten rechts -- 3 Zustaende (Item M):

          * Fenster nicht da        -> amber "Suche Metin2...".
          * da UND ~800x600 (gesund) -> leer + Resize-Knopf versteckt (wie bisher).
          * da, aber falsche Groesse -> amber Warnung mit IST-Groesse + Resize-Knopf.
        """
        self._saved_job = None
        note = getattr(self, 'detect_note', None)
        if note is None:
            return
        try:
            if not self._game_present:
                note.configure(text=t('ui.detect_searching'), text_color=AMBER)
                self._hide_resize_btn()
            elif self._game_healthy:
                note.configure(text='')
                self._hide_resize_btn()
            else:
                w, h = self._game_size
                note.configure(text=t('ui.detect_wrong_size', w=w, h=h),
                               text_color=AMBER)
                self._show_resize_btn()
        except Exception:
            pass

    def _show_resize_btn(self):
        try:
            if getattr(self, 'resize_btn', None) is not None:
                self.resize_btn.grid()
        except Exception:
            pass

    def _hide_resize_btn(self):
        try:
            if getattr(self, 'resize_btn', None) is not None:
                self.resize_btn.grid_remove()
        except Exception:
            pass

    def _poll_game(self):
        """Prueft ~1x/s passiv den Metin2-Fenster-Zustand (rein lesender
        Win32-Check -- kein Anti-Cheat-Trigger): vorhanden? richtige Groesse?
        wie viele? Spiegelt das in die Note/den Resize-Knopf/den Picker und
        beendet die App ggf. (close-on-Metin2)."""
        present, hwnd, w, h, healthy = _probe_game()
        self._game_present = present
        self._game_hwnd = hwnd
        self._game_size = (w, h)
        self._game_healthy = healthy
        self._refresh_window_picker()
        if self._saved_job is None:
            self._refresh_detect_note()
        self._maybe_close_on_metin2()
        try:
            self.after(1000, self._poll_game)
        except Exception:
            pass

    def _maybe_close_on_metin2(self):
        """Settings #3: beendet die App, wenn Metin2 (war da -> weg) schliesst.

        Der ``_game_was_present``-Latch verhindert ein Beenden beim Start, bevor
        Metin2 jemals offen war."""
        try:
            if not self._cfg['window']['close_on_metin2_close']:
                self._game_was_present = (self._game_present
                                          or self._game_was_present)
                return
            if self._game_was_present and not self._game_present:
                log.event('-', t('ui.closing_metin2_gone'))
                self._on_close()
                return
            self._game_was_present = (self._game_present
                                      or self._game_was_present)
        except Exception:
            pass

    def notify_stop(self, reason):
        """Meldet prominent, DASS + WARUM der Bot sich selbst gestoppt hat.

        Steht ~4 s in der Note (rot bei Fehler, sonst amber), danach zurueck auf
        den Ruhestatus. Wird vom Tick gerufen, wenn ein Bot sich selbst beendet
        (Zeitlimit, Fehler, Region-/Truhen-Problem)."""
        try:
            color = (DANGER if reason == t('run.reason_error_see_console')
                     else AMBER)
            self.detect_note.configure(
                text=t('ui.status_stopped', reason=reason), text_color=color)
            if self._saved_job is not None:
                self.after_cancel(self._saved_job)
            self._saved_job = self.after(4000, self._refresh_detect_note)
        except Exception:
            pass

    def notify_start_failed(self, no_window):
        """Meldet prominent (amber, ~5 s), dass der START nicht klappte -- meist
        weil das Metin2-Fenster nicht gefunden wurde (Spiel zuerst starten)."""
        try:
            reason = (t('ui.status_start_no_window') if no_window
                      else t('ui.status_start_failed'))
            self.detect_note.configure(text=reason, text_color=AMBER)
            if self._saved_job is not None:
                self.after_cancel(self._saved_job)
            self._saved_job = self.after(5000, self._refresh_detect_note)
        except Exception:
            pass

    # -- Metin2 auf 800x600 setzen (Item M) ------------------------------

    def _on_resize_game(self):
        """Setzt die CLIENT-Flaeche des gefundenen Metin2-Fensters auf 800x600.

        Nutzt ``windowcapture.set_client_size`` (gemessene Rahmen-Deltas, mit
        Rueckfall auf die festen 8/30-Masse). Strikt defensiv -- ohne gueltiges
        Handle oder bei Fehler nur ein Log-Eintrag, NIE ein Crash. Der naechste
        1s-Poll aktualisiert die Note ohnehin."""
        hwnd = getattr(self, '_game_hwnd', None)
        if not hwnd:
            return
        try:
            import windowcapture
            ok = windowcapture.set_client_size(
                hwnd, TARGET_CLIENT_W, TARGET_CLIENT_H)
        except Exception as exc:
            log.error(t('ui.resize_failed_log'), exc=exc)
            return
        if ok:
            log.event('-', t('ui.resize_done_log'))
            self._hide_resize_btn()
        else:
            log.error(t('ui.resize_failed_log'))

    # -- Mehrfenster-Picker + Ziel-HWND (Item N) -------------------------

    def _refresh_window_picker(self):
        """Aktualisiert die Liste sichtbarer METIN2-Fenster + die Picker-UI.

        <=1 Fenster: ``_chosen_hwnd`` loeschen, Picker-Knopf verstecken ->
        byte-identisch zu frueher (Single-Window). >1: Knopf zeigen. Die UI wird
        NUR bei geaenderter HWND-Signatur angefasst (kein Sekunden-Flackern)."""
        try:
            import constants
            import windowcapture
            windows = windowcapture.enumerate_game_windows(constants.GAME_NAME)
        except Exception:
            windows = []
        self._game_windows = windows
        sig = tuple(w['hwnd'] for w in windows)
        if sig == self._window_sig:
            return
        self._window_sig = sig
        # Gewaehltes Ziel verwerfen, wenn es nicht mehr existiert.
        if self._chosen_hwnd not in sig:
            self._chosen_hwnd = None
        try:
            btn = getattr(self, 'pick_btn', None)
            if btn is None:
                return
            if len(windows) > 1:
                btn.grid()
            else:
                btn.grid_remove()
        except Exception:
            pass

    def _open_window_picker(self):
        """Kleiner Auswahldialog (eigenes CTkToplevel) der gefundenen METIN2-
        Fenster -- je Fenster eine Zeile mit Groesse/Position. Auswahl setzt das
        Ziel-HWND (Item N). Strikt defensiv."""
        windows = list(self._game_windows)
        if len(windows) <= 1:
            return
        try:
            dlg = ctk.CTkToplevel(self)
            dlg.title(t('ui.pick_window_title'))
            dlg.configure(fg_color=BG)
            dlg.resizable(False, False)
            dlg.geometry('360x{}'.format(70 + 40 * len(windows)))
            try:
                dlg.transient(self)
            except Exception:
                pass
            dlg.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(dlg, text=t('ui.pick_window_title'), text_color=TEXT,
                         font=ctk.CTkFont(size=14, weight='bold')).grid(
                row=0, column=0, sticky='w', padx=16, pady=(14, 6))

            def _close():
                try:
                    dlg.grab_release()
                except Exception:
                    pass
                try:
                    dlg.destroy()
                except Exception:
                    pass

            for i, win in enumerate(windows):
                n = i + 1
                row_text = t('ui.pick_window_row', n=n, w=win['w'], h=win['h'],
                             x=win['x'], y=win['y'])

                def _pick(w=win, num=n, dialog_close=_close):
                    dialog_close()
                    self._on_pick_window(w['hwnd'], num, w['w'], w['h'])

                ctk.CTkButton(
                    dlg, text=row_text, height=30, corner_radius=8,
                    fg_color=PANEL_LIGHT, hover_color=PANEL_HOVER,
                    text_color=TEXT, font=ctk.CTkFont(size=12),
                    command=_pick).grid(row=1 + i, column=0, sticky='ew',
                                        padx=16, pady=3)

            dlg.protocol('WM_DELETE_WINDOW', _close)
            try:
                dlg.after(60, dlg.grab_set)
                dlg.lift()
            except Exception:
                pass
        except Exception:
            pass

    def _on_pick_window(self, hwnd, n, w, h):
        """Speichert das gewaehlte Ziel-HWND (runtime-only) + loggt die Wahl."""
        self._chosen_hwnd = hwnd
        log.event('-', t('ui.window_chosen', n=n, w=w, h=h))

    def _apply_preferred_hwnd(self):
        """Reicht das gewaehlte Ziel-HWND an WindowCapture durch (vor Start).

        Ohne Wahl (``None``) -> ``set_preferred_hwnd(None)`` -> FindWindow-Pfad
        (byte-identisch zu frueher). Strikt defensiv."""
        try:
            import windowcapture
            windowcapture.set_preferred_hwnd(self._chosen_hwnd)
        except Exception:
            pass

    def _clear_preferred_hwnd(self):
        """Loescht die WindowCapture-Praeferenz (beim Stop). Strikt defensiv."""
        try:
            import windowcapture
            windowcapture.clear_preferred_hwnd()
        except Exception:
            pass

    # -- Auto-Update (dezentes, schliessbares Banner) --------------------

    def _kick_off_update_check(self):
        """Startet die Hintergrund-Versionspruefung. Wirft NIE; ohne Netz oder
        bei Fehlern passiert einfach nichts (kein Banner). ``updater`` wird hier
        LAZY importiert, damit headless-Tests von :mod:`interface.app` nie das
        Netz-/Updater-Modul benoetigen."""
        try:
            import updater
            from version import __version__
            updater.start_background_check(self._on_update_available,
                                           __version__)
        except Exception:
            pass

    def _on_update_available(self, info):
        """Callback aus dem WORKER-Thread -> SOFORT auf den GUI-Thread bouncen
        (Tk ist nicht thread-sicher; Widget-Aufbau muss im GUI-Thread laufen)."""
        try:
            self.after(0, lambda: self._show_update_banner(info))
        except Exception:
            pass

    def _show_update_banner(self, info):
        """Zeigt das dezente, schliessbare Update-Banner (GUI-Thread). Idempotent:
        mehrfaches Aufrufen ersetzt nur den Text und macht es wieder sichtbar."""
        try:
            self._update_info = info
            if self._update_banner is None:
                self._build_update_banner()
            self._refresh_update_banner_text()
            self._update_btn.configure(state='normal', text=t('ui.update_now'))
            self._update_banner.grid()           # sichtbar machen
            self._highlight_version_update(info)  # Versionsanzeige aufleuchten
            try:
                log.event('-', t('ui.update_found_log',
                                 version=getattr(info, 'tag', '')))
            except Exception:
                pass
        except Exception:
            pass

    def _build_footer(self):
        """Dezente, dauerhaft sichtbare Versionsanzeige unten links (eigene
        Grid-Zeile row 3, unter dem optionalen Update-Banner) + die Detection-
        Note unten rechts (gegenueber). Zeigt normal nur ``vX.Y.Z`` gedaempft;
        liegt ein Update vor, leuchtet die Version teal auf. Klick oeffnet das
        GitHub-Repo (bzw. startet das Update). Einmalig gebaut, vom Sprachwechsel-
        Neuaufbau NICHT zerstoert (daher ueberlebt auch die Detection-Note)."""
        try:
            from version import __version__
            ver = __version__
        except Exception:
            ver = '?'
        self._version_base = 'v' + ver
        self._repo_url = 'https://github.com/DartagnanXE/Metin2FishBot'

        footer = ctk.CTkFrame(self, fg_color=PANEL_DARK, corner_radius=0)
        footer.grid(row=3, column=0, sticky='ew')
        footer.grid_columnconfigure(0, weight=1)
        self.footer = footer

        self._version_label = ctk.CTkLabel(
            footer, text=self._version_base, anchor='w', cursor='hand2',
            text_color=TEXT_MUTED, font=ctk.CTkFont(size=10))
        self._version_label.grid(row=0, column=0, sticky='w', padx=10,
                                 pady=(3, 4))
        self._version_label.bind('<Button-1>', self._on_version_click, add='+')

        # Mehrfenster-Picker-Knopf (Item N): nur sichtbar, wenn >1 METIN2-Fenster
        # offen ist; sonst versteckt (Single-Window = byte-identisch zu frueher).
        self.pick_btn = ctk.CTkButton(
            footer, text=t('ui.pick_window_btn'), height=22, width=110,
            corner_radius=6, fg_color='transparent', hover_color=PANEL_HOVER,
            text_color=TEXT_FAINT, border_width=1, border_color=PANEL_LIGHT,
            font=ctk.CTkFont(size=10), command=self._open_window_picker)
        self.pick_btn.grid(row=0, column=1, sticky='e', padx=(0, 6),
                           pady=(3, 4))
        self.pick_btn.grid_remove()

        # "Auf 800x600 setzen"-Knopf (Item M): nur sichtbar, wenn Metin2 in
        # falscher Groesse gefunden wurde; setzt die Client-Flaeche auf 800x600.
        self.resize_btn = ctk.CTkButton(
            footer, text=t('ui.detect_resize_btn'), height=22, width=120,
            corner_radius=6, fg_color='transparent', hover_color=PANEL_HOVER,
            text_color=AMBER, border_width=1, border_color=TEAL_DARK,
            font=ctk.CTkFont(size=10), command=self._on_resize_game)
        self.resize_btn.grid(row=0, column=2, sticky='e', padx=(0, 6),
                            pady=(3, 4))
        self.resize_btn.grid_remove()

        # Detection-Note (rechts, gegenueber der Versionsanzeige). Doppelt als
        # transienter Feedback-Slot (flash_saved/notify_*). Leer = gesund.
        self.detect_note = ctk.CTkLabel(
            footer, text='', text_color=AMBER, font=ctk.CTkFont(size=11),
            anchor='e')
        self.detect_note.grid(row=0, column=3, sticky='e', padx=8, pady=(3, 4))

        # Hover-Attribution. Bewusst sprachneutral (Eigennamen + URL).
        try:
            Tooltip(self._version_label,
                    text=('Metin2 Fishing Bot · ' + self._version_base
                          + '\nMusketier Software - DartagnanXE'
                          + '\n' + self._repo_url))
        except Exception:
            pass

    def _on_version_click(self, _event=None):
        """Klick auf die Versionsanzeige: liegt ein Update vor -> Update-Flow;
        sonst -> GitHub-Repo (Herkunft/Quellcode) im Browser oeffnen."""
        if getattr(self, '_update_info', None) is not None:
            self._on_update_click()
            return
        try:
            import webbrowser
            webbrowser.open(getattr(self, '_repo_url',
                                    'https://github.com/DartagnanXE/Metin2FishBot'))
        except Exception:
            pass

    def _highlight_version_update(self, info):
        """Laesst die Versionsanzeige unten links dezent teal aufleuchten, sobald
        eine neuere Version vorliegt (Klick -> Update, via _on_version_click)."""
        try:
            tag = getattr(info, 'tag', '') or 'update'
            self._version_label.configure(
                text='▲ ' + self._version_base + ' → ' + tag,
                text_color=TEAL)
        except Exception:
            pass

    def _build_update_banner(self):
        """Baut das Banner als EIGENE Grid-Zeile (row 2) -- nicht in topbar/
        content, damit ein Sprachwechsel-Neuaufbau es nicht zerstoert."""
        bar = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0)
        bar.grid(row=2, column=0, sticky='ew')
        bar.grid_columnconfigure(0, weight=1)
        self._update_label = ctk.CTkLabel(
            bar, text='', anchor='w', text_color=TEXT,
            font=ctk.CTkFont(size=12, weight='bold'))
        self._update_label.grid(row=0, column=0, sticky='w', padx=(14, 8),
                                pady=8)
        self._update_btn = ctk.CTkButton(
            bar, text=t('ui.update_now'), height=28, width=150,
            fg_color=TEAL, hover_color=TEAL_HOVER, text_color=INK,
            corner_radius=8, command=self._on_update_click)
        self._update_btn.grid(row=0, column=1, sticky='e', padx=4, pady=8)
        self._update_dismiss = ctk.CTkButton(
            bar, text='✕', width=28, height=28, fg_color='transparent',
            hover_color=PANEL_HOVER, text_color=TEXT_MUTED,
            command=self._on_update_dismiss)
        self._update_dismiss.grid(row=0, column=2, sticky='e', padx=(0, 10),
                                  pady=8)
        self._update_banner = bar

    def _refresh_update_banner_text(self):
        info = getattr(self, '_update_info', None)
        version = getattr(info, 'tag', '') if info else ''
        try:
            self._update_label.configure(
                text=t('ui.update_available', version=version))
        except Exception:
            pass

    def _on_update_dismiss(self):
        """Blendet das Banner aus (nur ausblenden, Info bleibt) -- die
        Abweisung haelt die Sitzung."""
        try:
            if self._update_banner is not None:
                self._update_banner.grid_remove()
        except Exception:
            pass

    def _on_update_click(self):
        """Verzweigt: onefile -> Download + Selbstersetzung; sonst (onedir/
        Quellcode) -> Releases-Seite oeffnen (onedir-Stub NICHT ueberschreiben)."""
        import updater
        info = getattr(self, '_update_info', None)
        if info is None:
            return
        if not updater.can_self_replace():
            updater.open_releases_page(
                getattr(info, 'page_url', updater.RELEASES_PAGE))
            self._set_update_banner_msg(t('ui.update_open_page'))
            log.event('-', t('ui.update_manual_required'))
            return
        if getattr(info, 'download_url', None) is None:
            # Onefile, aber kein Portable-Asset im Release -> nur Seite oeffnen.
            updater.open_releases_page(
                getattr(info, 'page_url', updater.RELEASES_PAGE))
            self._set_update_banner_msg(t('ui.update_no_asset'))
            return
        self._start_update_download(info)

    def _start_update_download(self, info):
        """Laedt das Portable-Asset in einem EIGENEN Daemon-Thread (die GUI darf
        waehrend des MB-Downloads nie einfrieren); Fortschritt/Ende werden via
        ``after`` zurueck auf den GUI-Thread gespiegelt."""
        import threading

        import updater
        try:
            self._update_btn.configure(state='disabled')
        except Exception:
            pass
        self._set_update_banner_msg(t('ui.update_downloading', pct=0))

        def _progress(done, total):
            if total:
                text = t('ui.update_downloading',
                         pct=int(done * 100 / total))
            else:
                text = t('ui.update_downloading_unknown')
            try:
                self.after(0, lambda: self._set_update_banner_msg(text))
            except Exception:
                pass

        def _worker():
            try:
                path = updater.download_asset(info, progress=_progress)
                self.after(0, lambda: self._finish_update(path))
            except Exception as exc:
                self.after(0, lambda: self._update_failed(exc))

        threading.Thread(target=_worker, name='update-download',
                         daemon=True).start()

    def _finish_update(self, downloaded_path):
        """Schreibt+startet den Selbstersetzungs-.bat und beendet die App hart,
        damit die .exe entsperrt ist und ueberschrieben + neu gestartet werden
        kann."""
        import updater
        try:
            self._set_update_banner_msg(t('ui.update_installing'))
            updater.apply_update_onefile(downloaded_path)
            log.section(t('ui.update_restarting'))
            try:
                cfgmod.save(self.controller.current_config())
            except Exception:
                pass
            try:
                self.log_panel.detach()
            except Exception:
                pass
            self.after(200, self._hard_exit_for_update)
        except Exception as exc:
            self._update_failed(exc)

    def _hard_exit_for_update(self):
        """Garantiert raus: ``os._exit`` haelt keine Tk-/Thread-/after-Reste,
        sodass die .exe-Sperre faellt und der .bat sie kopieren kann."""
        try:
            self.destroy()
        except Exception:
            pass
        os._exit(0)

    def _update_failed(self, exc):
        log.error(t('ui.update_failed_log'), exc=exc)
        self._set_update_banner_msg(t('ui.update_failed'))
        try:
            self._update_btn.configure(state='normal')
        except Exception:
            pass

    def _set_update_banner_msg(self, text):
        try:
            self._update_label.configure(text=text)
        except Exception:
            pass

    # -- Config -> Widgets -----------------------------------------------

    def _apply_config_to_widgets(self):
        fishing = self._cfg['fishing']
        self.bait_slider.set(fishing['bait_time'])
        self.throw_slider.set(fishing['throw_time'])
        self.start_slider.set(fishing['start_game_time'])
        self.stop_after_var.set(fishing['stop_after_enabled'])
        self.stop_after_entry.delete(0, 'end')
        self.stop_after_entry.insert(0, str(fishing['stop_after_minutes']))
        self.golden_tuna_seg.set(str(fishing['golden_tuna_action']))

        puzzle = self._cfg['puzzle']
        self.detection_seg.set(self._detect_label_for(puzzle['detection_mode']))
        self.color_seg.set(puzzle['color_mode'].capitalize())
        self.solver_seg.set(self._solver_label_for(puzzle['solver_mode']))
        try:
            self._opacity_slider.set(puzzle['overlay_opacity'])
            self._refresh_opacity_value()
        except Exception:
            pass

        window = self._cfg['window']
        self._close_metin2_var.set(window['close_on_metin2_close'])
        self._close_timer_var.set(window['close_on_timer_expire'])
        self._always_top_var.set(window['always_on_top'])
        self._tray_var.set(window['minimize_to_tray'])
        try:
            self.bait_key_btn.configure(text=str(fishing['bait_key']).upper())
            self.cast_key_btn.configure(text=str(fishing['cast_key']).upper())
        except Exception:
            pass

    # -- kleine Helfer ----------------------------------------------------

    def _solver_label_for(self, solver_mode):
        return self._solver_v2l.get(
            solver_mode, self._solver_v2l[cfgmod.SOLVER_MODES[0]])

    def _detect_label_for(self, detection_mode):
        return self._detect_v2l.get(
            detection_mode, self._detect_v2l[cfgmod.DETECTION_MODES[0]])
