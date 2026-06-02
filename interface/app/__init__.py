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

# Das frueher hier inline definierte Modul-Surface (Imports, Konstanten, reine
# Helfer) lebt jetzt in ``interface.app._common`` und wird per ``*`` re-exportiert
# -- so bleibt JEDER Name (ctk/t/log/Farben/RAIL_ORDER/_probe_game/...) sowohl im
# Orchestrator als auch in jedem Mixin verfuegbar, und ``interface.app.RAIL_ORDER``
# /``_hms``/``_probe_game`` (von GUI-Smoke + Tests importiert) bleiben erreichbar.
from interface.app import _common
from interface.app._common import *  # noqa: F401,F403
from interface.app._common import (  # explizit fuer Linter + lokale Nutzung
    cfgmod, ctk, log, set_lang, t, tray, time, BG, DANGER, DANGER_HOVER,
    INK, PANEL_DARK, RAIL_BG, RAIL_GLYPHS, RAIL_HOVER, RAIL_ORDER, STRIP_BG,
    TEAL, TEAL_BRIGHT, TEAL_HOVER, TEAL_SOFT, TEXT, TEXT_FAINT, TEXT_MUTED,
    Tooltip, ICON_FILE, resource_path, os)

# Cohesive method groups live in sibling mixin modules; ``App`` inherits them all
# (see the bases below). Each mixin star-imports ``_common`` so every
# ``self``-free name resolves exactly as in the original single-file module.
from interface.app.footer import FooterMixin
from interface.app.key_capture import KeyCaptureMixin
from interface.app.views_roadmap import RoadmapViewMixin
from interface.app.window_picker import WindowPickerMixin
from interface.app.config_widgets import ConfigWidgetsMixin
from interface.app.views_run import FishingPuzzleConsoleViewsMixin
from interface.app.views_inventory import InventoryViewMixin
from interface.app.views_ranking import RankingViewMixin
from interface.app.builders import RowBuildersMixin
from interface.app.run_control import RunControlMixin
from interface.app.detection import DetectionMixin
from interface.app.settings_effects import SettingsEffectsMixin
from interface.app.lifecycle import LifecycleMixin
from interface.app.update_banner import UpdateBannerMixin
from interface.app.views_settings import SettingsViewMixin
from interface.app.shell import ShellMixin

# BotController lives in its own module (logically separate from the window) and
# is re-exported here so ``from interface.app import BotController`` is unchanged.
from interface.app.controller import BotController


class App(
    ShellMixin,
    SettingsViewMixin,
    UpdateBannerMixin,
    LifecycleMixin,
    SettingsEffectsMixin,
    DetectionMixin,
    RunControlMixin,
    RowBuildersMixin,
    RankingViewMixin,
    InventoryViewMixin,
    FishingPuzzleConsoleViewsMixin,
    ConfigWidgetsMixin,
    WindowPickerMixin,
    RoadmapViewMixin,
    KeyCaptureMixin,
    FooterMixin,
    ctk.CTk,
):
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
        # Inventar-Scan: LAUFZEIT-Zustand (nicht persistiert, wie _chosen_hwnd) --
        # die differentielle Erinnerung ist also pro Sitzung, was korrekt ist.
        self._inv_scanning = False         # Re-Entrancy-Sperre fuer den Scan
        self._inv_last_map = None          # letzte InventoryMap (Diff-Basis)
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
        # Statistik-Default: hack.py ersetzt das durch die geladene stats.json
        # (app._stats). Hier ein sicherer Default, damit der Ranking-Tab auch
        # ausserhalb von hack.py (z.B. Tests, Standalone) nie auf ein fehlendes
        # Attribut laeuft. Caches fuer HWID/Bann-Status ebenfalls vorinitialisiert.
        self._stats = None
        self._hwid_cache = None
        self._ranking_banned = False
        # Optional final-flush hook for persistent stats. hack.py owns stats.json
        # and registers a callable here so EVERY exit path (window close, tray
        # quit, timer auto-close, update-restart) flushes accrued runtime to disk
        # -- otherwise runtime since the last catch/solve (e.g. an idle-running
        # session, or a hard exit for auto-update) would be lost. None in tests/
        # standalone -> the flush is simply skipped. Must never raise.
        self._stats_save_hook = None

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

        # Ranking-Status (_ranking_banned) bereits oben vorinitialisiert.
        self._telemetry_thread = None

        # Onboarding (erster Start: Name + GDPR-Opt-in) NACH dem Aufbau planen.
        # Streng defensiv -- ein Fehler hier darf den Start nie kippen.
        self.after(700, self._maybe_onboard)
        # Telemetrie-Sender (opt-in, Daemon-Thread) ~1.5s nach Start anwerfen.
        self.after(1500, self._start_telemetry)

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

    def _solver_label_for(self, solver_mode):
        return self._solver_v2l.get(
            solver_mode, self._solver_v2l[cfgmod.SOLVER_MODES[0]])

    def _detect_label_for(self, detection_mode):
        return self._detect_v2l.get(
            detection_mode, self._detect_v2l[cfgmod.DETECTION_MODES[0]])


# Public surface of the package. ``App``/``BotController`` are defined/re-exported
# above; the module constants + pure helpers come in via ``from _common import *``
# (so ``interface.app.RAIL_ORDER`` / ``_hms`` / ``_probe_game`` etc. stay importable
# exactly as when this was a single module -- relied on by the GUI-smoke + tests).
__all__ = ['App', 'BotController'] + list(getattr(_common, '__all__', []))
