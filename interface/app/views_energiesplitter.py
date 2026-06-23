# -*- coding: utf-8 -*-
"""EnergiesplitterViewMixin -- der Energiesplitter-Reiter (EINE Ansicht, ZWEI
Aktionen), nach dem Umbau 2026-06-16.

Aktion 1 ("Hammer kaufen") kauft am Alchemisten ``stack_count`` (X) mal einen
200er-Hammer-Stack; Aktion 2 ("Dolche verarbeiten") kauft am Waffenhaendler
``daggers_per_round`` Dolche pro Runde und verarbeitet sie EINZELN NACHEINANDER
zu Energiesplittern (1 Drag eines Hammer-Stacks auf einen Dolch = 1 Hammer +
1 Dolch). Beide laufen ueber den ``run_loop``-Bot-Tick (wie ``fishbot``/
``puzzlebot``) -- KEIN eigener Worker-Thread: Der Start setzt ueber
``controller.set_mode(...)`` den aktiven Modus und ruft
``controller.on_start_stop()``; der RunLoop ruft danach pro Tick
``esbot.runHack()``.

YANG spielt KEINE Rolle mehr (kein Preis, kein Kontostand, kein Yang-Rechner).
Die Ansicht ist SCROLLBAR (``CTkScrollableFrame``), damit bei vielen Feldern der
untere Teil (Scharf/Live) erreichbar bleibt. Alle Labels + Dropdown-Werte +
Tooltips sind deutsch.
"""

from interface.app._common import *  # noqa: F401,F403

# Modus-Werte (Contract §0): EIN Reiter, zwei Start-Aktionen -> zwei APP_MODES.
ES_MODE_HAMMER = 'energiesplitter_hammer'
ES_MODE_DAGGER = 'energiesplitter_dagger'


class EnergiesplitterViewMixin:
  def _build_energiesplitter_view(self, _parent):
    """Baut die Energiesplitter-Sicht (zwei Start-Knoepfe + scrollbare Settings)."""
    view = self._new_view('energiesplitter')

    # -- Header (Titel + grosszuegig umbrechender Untertitel + Hilfe-Badge) --
    head = ctk.CTkFrame(view, fg_color='transparent')
    head.grid(row=0, column=0, sticky='ew', pady=(0, 6))
    head.grid_columnconfigure(0, weight=1)
    ctk.CTkLabel(head, text=t('ui.view_energiesplitter'), text_color=TEXT,
                 font=ctk.CTkFont(size=14, weight='bold')).grid(
        row=0, column=0, sticky='w')
    InfoBadge(head, text=t('ui.es_help')).grid(row=0, column=1, sticky='ne',
                                               padx=(6, 0))
    ctk.CTkLabel(head, text=t('ui.energiesplitter_sub'), text_color=TEXT_FAINT,
                 font=ctk.CTkFont(size=12), anchor='w', justify='left',
                 wraplength=460).grid(row=1, column=0, columnspan=2, sticky='w',
                                      pady=(2, 0))

    # -- Die zwei Start/Stop-Knoepfe (Aktion 1 / Aktion 2) ------------------
    btns = ctk.CTkFrame(view, fg_color='transparent')
    btns.grid(row=1, column=0, sticky='ew', pady=(0, 6))
    btns.grid_columnconfigure(0, weight=1)
    btns.grid_columnconfigure(1, weight=1)
    self._es_hammer_btn = ctk.CTkButton(
        btns, text=t('ui.es_hammer_start_btn'), height=44, corner_radius=12,
        font=ctk.CTkFont(size=14, weight='bold'),
        fg_color=TEAL, hover_color=TEAL_HOVER, text_color=INK,
        command=lambda: self._on_es_start_stop('hammer'))
    self._es_hammer_btn.grid(row=0, column=0, sticky='ew', padx=(0, 4))
    self._es_dagger_btn = ctk.CTkButton(
        btns, text=t('ui.es_dagger_start_btn'), height=44, corner_radius=12,
        font=ctk.CTkFont(size=14, weight='bold'),
        fg_color=TEAL, hover_color=TEAL_HOVER, text_color=INK,
        command=lambda: self._on_es_start_stop('dagger'))
    self._es_dagger_btn.grid(row=0, column=1, sticky='ew', padx=(4, 0))

    # -- Scrollbarer Settings-Container -------------------------------------
    scroll = ctk.CTkScrollableFrame(view, fg_color='transparent')
    scroll.grid(row=2, column=0, sticky='nsew', pady=(0, 6))
    scroll.grid_columnconfigure(0, weight=1)
    view.grid_rowconfigure(2, weight=1)

    self._es_widgets = {}
    sec_row = 0

    # -- Section: Hammer kaufen (Aktion 1) ----------------------------------
    sec_h = Section(scroll, t('ui.es_group_hammer'))
    sec_h.grid(row=sec_row, column=0, sticky='ew', pady=(0, 8)); sec_row += 1
    bh = sec_h.body
    bh.grid_columnconfigure(1, weight=1)
    r = 0
    self._es_stack_count_var = ctk.StringVar(value='1')
    r = self._es_row(bh, r, t('ui.es_stack_count_label'),
                     self._es_entry('hammer', 'stack_count',
                                    self._es_stack_count_var, bh))
    self._es_freischalten_var = ctk.BooleanVar(value=True)
    r = self._es_switch(bh, r, t('ui.es_freischalten_label'),
                        'energie_freischalten', self._es_freischalten_var,
                        'hammer')

    # -- Section: Dolche verarbeiten (Aktion 2) -----------------------------
    sec_d = Section(scroll, t('ui.es_group_dagger'))
    sec_d.grid(row=sec_row, column=0, sticky='ew', pady=(0, 8)); sec_row += 1
    bd = sec_d.body
    bd.grid_columnconfigure(1, weight=1)
    r = 0
    self._es_daggers_var = ctk.StringVar(value='20')
    r = self._es_row(bd, r, t('ui.es_daggers_per_round_label'),
                     self._es_entry('dagger', 'daggers_per_round',
                                    self._es_daggers_var, bd))
    # Kauf-Modus: Chat-Quittung lesen vs. rein klickbasiert (Delay).
    self._es_buy_mode_var = ctk.StringVar(value=t('ui.es_buy_mode_chat'))
    r = self._es_row(bd, r, t('ui.es_buy_mode_label'),
                     self._es_optionmenu(
                         'dagger', 'buy_mode', self._es_buy_mode_var,
                         [('chat', t('ui.es_buy_mode_chat')),
                          ('click', t('ui.es_buy_mode_click'))], bd))
    # Kauf-Tempo (Sek. zwischen Kaufklicks / Backoff bei Rate-Limit-Retry).
    self._es_buy_delay_var = ctk.StringVar(value='0.35')
    r = self._es_row(bd, r, t('ui.es_buy_delay_label'),
                     self._es_entry('dagger', 'buy_delay_s',
                                    self._es_buy_delay_var, bd, is_float=True))
    # "Erst verarbeiten" -- vor dem Kauf zuerst die schon auf Seite 1 liegenden
    # Dolche abarbeiten (nur Dolche). Switch + Infotext (InfoBadge).
    self._es_process_first_var = ctk.BooleanVar(value=False)
    pfw = ctk.CTkSwitch(
        bd, text=t('ui.es_process_first_label'),
        variable=self._es_process_first_var,
        command=lambda: self._es_set('dagger', 'process_first',
                                     bool(self._es_process_first_var.get())))
    pfw.grid(row=r, column=0, sticky='w', pady=(6, 0))
    InfoBadge(bd, text=t('ui.es_process_first_help')).grid(
        row=r, column=1, sticky='w', padx=(6, 0), pady=(6, 0))
    self._es_widgets['process_first'] = pfw
    r += 1
    # Verarbeiten-Tempo in Sekunden (Pause Aufnehmen<->Setzen / nach 'Ja').
    self._es_proc_pickup_var = ctk.StringVar(value='0.15')
    r = self._es_row(bd, r, t('ui.es_proc_pickup_label'),
                     self._es_entry('dagger', 'process_pickup_s',
                                    self._es_proc_pickup_var, bd, is_float=True))
    self._es_proc_confirm_var = ctk.StringVar(value='0.4')
    r = self._es_row(bd, r, t('ui.es_proc_confirm_label'),
                     self._es_entry('dagger', 'process_confirm_s',
                                    self._es_proc_confirm_var, bd, is_float=True))

    # -- Section: Sicherheit ------------------------------------------------
    sec_s = Section(scroll, t('ui.es_group_safety'))
    sec_s.grid(row=sec_row, column=0, sticky='ew', pady=(0, 8)); sec_row += 1
    bs = sec_s.body
    bs.grid_columnconfigure(1, weight=1)
    r = 0
    # Scharf / Live (rot) -- Inversion von dry_run. AUS = Simulation.
    # Default AN (dry_run-Default ist jetzt False = Scharf, siehe defaults.py).
    self._es_scharf_var = ctk.BooleanVar(value=True)
    ssw = ctk.CTkSwitch(
        bs, text=t('ui.es_scharf_label'), variable=self._es_scharf_var,
        progress_color=DANGER,
        command=lambda: self._es_set('shared', 'dry_run',
                                     not bool(self._es_scharf_var.get())))
    ssw.grid(row=r, column=0, sticky='w', pady=(6, 0))
    InfoBadge(bs, text=t('ui.es_scharf_help')).grid(
        row=r, column=1, sticky='w', padx=(6, 0), pady=(6, 0))
    self._es_widgets['dry_run'] = ssw
    r += 1
    self._es_max_actions_var = ctk.StringVar(value='0')
    r = self._es_row(bs, r, t('ui.es_max_actions_label'),
                     self._es_entry('shared', 'max_actions',
                                    self._es_max_actions_var, bs))
    self._es_unverif_var = ctk.StringVar(value='3')
    r = self._es_row(bs, r, t('ui.es_unverif_label'),
                     self._es_entry('shared', 'consecutive_unverified_stop',
                                    self._es_unverif_var, bs))

    # -- Section: Erweitert -- nur mit Vorsicht aendern ---------------------
    sec_a = Section(scroll, t('ui.es_group_advanced'))
    sec_a.grid(row=sec_row, column=0, sticky='ew', pady=(0, 8)); sec_row += 1
    ba = sec_a.body
    ba.grid_columnconfigure(1, weight=1)
    r = 0
    ctk.CTkLabel(ba, text=t('ui.es_advanced_warn'), text_color=AMBER,
                 font=ctk.CTkFont(size=11), anchor='w', justify='left',
                 wraplength=440).grid(row=r, column=0, columnspan=2,
                                      sticky='w', pady=(0, 4))
    r += 1
    # Tempo-Profil (deutsche Anzeige-Werte).
    speed_pairs = (('safe', t('ui.es_speed_safe')),
                   ('fast', t('ui.es_speed_fast')))
    self._es_speed_var = ctk.StringVar(value=t('ui.es_speed_fast'))
    r = self._es_row(ba, r, t('ui.es_speed_label'),
                     self._es_optionmenu('shared', 'speed_profile',
                                         self._es_speed_var, speed_pairs, ba))
    self._es_mouse_pause_var = ctk.StringVar(value='0.05')
    r = self._es_row(ba, r, t('ui.es_mouse_pause_label'),
                     self._es_entry('shared', 'mouse_pause',
                                    self._es_mouse_pause_var, ba, is_float=True))
    self._es_kb_pause_var = ctk.StringVar(value='0.10')
    r = self._es_row(ba, r, t('ui.es_kb_pause_label'),
                     self._es_entry('shared', 'keyboard_pause',
                                    self._es_kb_pause_var, ba, is_float=True))
    self._es_jitter_var = ctk.StringVar(value='0.15')
    r = self._es_row(ba, r, t('ui.es_jitter_label'),
                     self._es_entry('shared', 'jitter_pct',
                                    self._es_jitter_var, ba, is_float=True))

    # -- Status-Zeile -------------------------------------------------------
    self._es_status = ctk.CTkLabel(
        view, text=t('ui.es_idle'), anchor='w', text_color=TEXT_FAINT,
        font=ctk.CTkFont(size=11), wraplength=460)
    self._es_status.grid(row=3, column=0, sticky='w', pady=(2, 0))

    # Werte aus der Config in die Widgets spiegeln.
    self._es_load_from_config()
    self._es_sync_buttons()

  # -- Widget-Fabriken ----------------------------------------------------

  def _es_row(self, parent, row, label, widget):
    """Setzt eine Label/Widget-Zeile und liefert die naechste Zeilennummer."""
    ctk.CTkLabel(parent, text=label, text_color=TEXT_FAINT,
                 font=ctk.CTkFont(size=12)).grid(
        row=row, column=0, sticky='w', padx=(0, 8), pady=(6, 0))
    widget.grid(row=row, column=1, sticky='w', pady=(6, 0))
    return row + 1

  def _es_switch(self, parent, row, label, key, var, section):
    """Setzt eine beschriftete Switch-Zeile (Toggle) und liefert die naechste Zeile."""
    sw = ctk.CTkSwitch(
        parent, text=label, variable=var,
        command=lambda: self._es_set(section, key, bool(var.get())))
    sw.grid(row=row, column=0, columnspan=2, sticky='w', pady=(6, 0))
    self._es_widgets[key] = sw
    return row + 1

  def _es_entry(self, section, key, var, parent, on_change=None,
                is_float=False):
    """Erzeugt ein Zahlen-Eingabefeld, das beim Verlassen ``section.key`` setzt."""
    entry = ctk.CTkEntry(parent, textvariable=var, width=110,
                         justify='center')

    def _commit(_event=None):
      self._es_commit_number(section, key, var, is_float)
      if callable(on_change):
        on_change()

    entry.bind('<FocusOut>', _commit)
    entry.bind('<Return>', _commit)
    self._es_widgets[key] = entry
    return entry

  def _es_optionmenu(self, section, key, var, label_pairs, parent):
    """Erzeugt ein OptionMenu (Enum), das ``section.key`` auf den Wert setzt."""
    l2v = {label: value for value, label in label_pairs}
    self._es_widgets.setdefault('_l2v', {})[key] = l2v
    self._es_widgets.setdefault(
        '_v2l', {})[key] = {value: label for value, label in label_pairs}

    def _change(label):
      value = l2v.get(label, label_pairs[0][0])
      self._es_set(section, key, value)

    menu = ctk.CTkOptionMenu(parent, variable=var, width=140,
                             values=[label for _v, label in label_pairs],
                             command=_change)
    self._es_widgets[key] = menu
    return menu

  # -- Persistenz ---------------------------------------------------------

  def _es_sub(self, section):
    """Liefert eine Kopie des energiesplitter-Sub-Dicts (hammer/dagger/shared)."""
    try:
      cfg = self.controller.current_config()
      return dict(cfg.get('energiesplitter', {}).get(section, {}))
    except Exception:
      return {}

  def _es_set(self, section, key, value):
    """Schreibt EINEN Wert ins energiesplitter-Sub-Dict (immutabel + Auto-Save)."""
    try:
      sub = self._es_sub(section)
      sub[key] = value
      self._cfg = self.controller.update_config('energiesplitter', section,
                                                sub)
    except Exception:
      pass

  def _es_commit_number(self, section, key, var, is_float):
    """Liest das Eingabefeld, wandelt in int/float, schreibt + spiegelt zurueck."""
    raw = (var.get() or '').strip()
    try:
      value = float(raw) if is_float else int(float(raw))
    except (TypeError, ValueError):
      cur = self._es_sub(section).get(key)
      if cur is not None:
        var.set(str(cur))
      return
    self._es_set(section, key, value)
    clamped = self._es_sub(section).get(key, value)
    var.set(str(clamped))

  def _es_load_from_config(self):
    """Spiegelt die persistierten Config-Werte in die Widget-Variablen."""
    h = self._es_sub('hammer')
    d = self._es_sub('dagger')
    s = self._es_sub('shared')
    try:
      self._es_stack_count_var.set(str(h.get('stack_count', 1)))
      self._es_freischalten_var.set(bool(h.get('energie_freischalten', True)))
      self._es_daggers_var.set(str(d.get('daggers_per_round', 20)))
      self._es_buy_delay_var.set(str(d.get('buy_delay_s', 0.35)))
      self._es_process_first_var.set(bool(d.get('process_first', False)))
      self._es_proc_pickup_var.set(str(d.get('process_pickup_s', 0.15)))
      self._es_proc_confirm_var.set(str(d.get('process_confirm_s', 0.4)))
      # Kauf-Modus: value -> Label.
      bm2l = self._es_widgets.get('_v2l', {}).get('buy_mode', {})
      self._es_buy_mode_var.set(bm2l.get(str(d.get('buy_mode', 'chat')),
                                         t('ui.es_buy_mode_chat')))
      self._es_max_actions_var.set(str(s.get('max_actions', 0)))
      self._es_unverif_var.set(str(s.get('consecutive_unverified_stop', 3)))
      self._es_mouse_pause_var.set(str(s.get('mouse_pause', 0.05)))
      self._es_kb_pause_var.set(str(s.get('keyboard_pause', 0.10)))
      self._es_jitter_var.set(str(s.get('jitter_pct', 0.15)))
      # Tempo-Profil: value -> deutsches Label.
      v2l = self._es_widgets.get('_v2l', {}).get('speed_profile', {})
      self._es_speed_var.set(v2l.get(str(s.get('speed_profile', 'fast')),
                                     t('ui.es_speed_fast')))
      # Scharf-Schalter = Inversion von dry_run (AN = scharf = dry_run False).
      # Default dry_run = False -> Schalter standardmaessig AN (scharf).
      self._es_scharf_var.set(not bool(s.get('dry_run', False)))
    except Exception:
      pass

  # -- Start/Stop (run_loop-Integration, KEIN eigener Worker-Thread) ------

  def _on_es_start_stop(self, which):
    """Start/Stop fuer Aktion 1 ('hammer') / Aktion 2 ('dagger')."""
    if self.controller.running:
      self.controller.on_start_stop()
      return

    present, _hwnd, _gw, _gh, _healthy = _probe_game()
    if not present:
      log.event('-', t('ui.start_aborted_no_window'))
      try:
        self._es_status.configure(text=t('ui.status_start_no_window'))
      except Exception:
        pass
      return

    mode = ES_MODE_HAMMER if which == 'hammer' else ES_MODE_DAGGER
    try:
      self._apply_preferred_hwnd()
    except Exception:
      pass
    # Pending-Edits vor dem Start committen (FocusOut feuert nicht garantiert).
    self._es_commit_all()
    self.controller.set_mode(mode)
    self._cfg = self.controller.current_config()
    try:
      self._es_status.configure(
          text=t('ui.es_running_hammer', done=0,
                 soll=self._es_sub('hammer').get('stack_count', 0))
          if which == 'hammer'
          else t('ui.es_running_dagger', done=0, rest=0))
    except Exception:
      pass
    log.event('0', t('energiesplitter.started', mode=mode))
    self.controller.on_start_stop()
    self._es_sync_buttons()

  def _es_commit_all(self):
    """Committet alle Zahlen-Eingabefelder (vor dem Start, idempotent)."""
    self._es_commit_number('hammer', 'stack_count', self._es_stack_count_var,
                           False)
    self._es_commit_number('dagger', 'daggers_per_round', self._es_daggers_var,
                           False)
    self._es_commit_number('dagger', 'process_pickup_s',
                           self._es_proc_pickup_var, True)
    self._es_commit_number('dagger', 'process_confirm_s',
                           self._es_proc_confirm_var, True)
    self._es_commit_number('shared', 'max_actions', self._es_max_actions_var,
                           False)
    self._es_commit_number('shared', 'consecutive_unverified_stop',
                           self._es_unverif_var, False)
    self._es_commit_number('shared', 'mouse_pause', self._es_mouse_pause_var,
                           True)
    self._es_commit_number('shared', 'keyboard_pause', self._es_kb_pause_var,
                           True)
    self._es_commit_number('shared', 'jitter_pct', self._es_jitter_var, True)

  def _es_sync_buttons(self):
    """Spiegelt den Laufzustand auf die beiden Start/Stop-Knoepfe.

    Wird aus ``sync_controls`` bei JEDEM Tick (~100x/s) gerufen -> ein
    bedingungsloses ``configure`` pro Tick liess die Knoepfe sichtbar flackern/
    wackeln. Das Aussehen haengt NUR von ``(running, mode)`` ab: solange sich das
    nicht aendert, ist nichts zu tun (Dirty-Check) -> kein Reconfigure-Flicker.
    """
    try:
      running = self.controller.running
      mode = self.controller.mode
    except Exception:
      running, mode = False, ''
    sig = (bool(running), mode)
    if sig == getattr(self, '_es_btn_sig', None):
      return  # Zustand unveraendert -> keine (flackernde) Neukonfiguration
    self._es_btn_sig = sig
    hammer_active = running and mode == ES_MODE_HAMMER
    dagger_active = running and mode == ES_MODE_DAGGER
    other_running = running and mode not in (ES_MODE_HAMMER, ES_MODE_DAGGER)

    def _btn(btn, start_text, active):
      if btn is None:
        return
      try:
        if active:
          btn.configure(text=t('ui.es_stop_btn'), fg_color=DANGER,
                        hover_color=DANGER_HOVER, text_color='#fff',
                        state='normal')
        elif running or other_running:
          btn.configure(text=start_text, fg_color=PANEL_LIGHT,
                        hover_color=PANEL_LIGHT, text_color=TEXT_FAINT,
                        state='disabled')
        else:
          btn.configure(text=start_text, fg_color=TEAL,
                        hover_color=TEAL_HOVER, text_color=INK,
                        state='normal')
      except Exception:
        pass

    _btn(getattr(self, '_es_hammer_btn', None),
         t('ui.es_hammer_start_btn'), hammer_active)
    _btn(getattr(self, '_es_dagger_btn', None),
         t('ui.es_dagger_start_btn'), dagger_active)
