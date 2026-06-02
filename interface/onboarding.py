# -*- coding: utf-8 -*-
"""First-run onboarding: choose a ranking username + GDPR opt-in (UI, small).

Shown ONCE, on the first EXE start where the config has no username yet AND the
telemetry consent was never decided. A themed ``CTkToplevel`` (matching the
existing ``_confirm_dialog`` dark/teal style) asks for a self-chosen username
(length-capped, stripped, with a "no personal data" hint), shows a clear OPT-IN
checkbox (default OFF) + a short privacy note + a "what is sent" summary, and on
Save writes ``username`` + ``telemetry.enabled`` + ``telemetry.consented`` via
``controller.update_config``.

GDPR (load-bearing on a public repo with a German user): telemetry stays OFF
unless the box is ticked; "Skip" still records consent=decided so the dialog
does not reappear, with telemetry OFF. Strictly defensive -- if the dialog fails
to build, no telemetry is enabled and the app simply continues.

All strings via ``i18n.t`` (EN/DE parity). Reuses interface.widgets colors.
"""

import customtkinter as ctk

from i18n import t
from interface import config as cfgmod
from interface.widgets import (BG, INK, PANEL_HOVER, PANEL_LIGHT, TEAL,
                               TEAL_HOVER, TEXT, TEXT_FAINT, TEXT_MUTED)


def needs_onboarding(cfg):
    """True iff the first-run dialog should be shown.

    Condition: no username chosen yet AND telemetry consent never recorded.
    Never raises -> on a malformed cfg returns False (skip the dialog rather
    than risk a crash on startup).
    """
    try:
        username = str(cfg.get('username', '') or '').strip()
        consented = bool(cfg.get('telemetry', {}).get('consented', False))
        return (username == '') and (not consented)
    except Exception:
        return False


def open_onboarding(app, on_done=None):
    """Open the themed first-run dialog. Never raises.

    Writes the chosen ``username`` + ``telemetry.enabled``/``consented`` to the
    config via ``app.controller.update_config`` and then calls
    ``on_done({'username':.., 'telemetry_enabled':..})`` if given. If anything
    fails to build, telemetry is left OFF and the app continues.
    """
    try:
        dlg = ctk.CTkToplevel(app)
        dlg.title(t('ui.onboarding_title'))
        dlg.configure(fg_color=BG)
        dlg.resizable(False, False)
        dlg.geometry('420x430')
        try:
            dlg.transient(app)
        except Exception:
            pass
        dlg.grid_columnconfigure(0, weight=1)

        optin_var = ctk.BooleanVar(value=False)   # GDPR: default OFF

        # -- Title + intro ------------------------------------------------
        ctk.CTkLabel(dlg, text=t('ui.onboarding_title'), text_color=TEXT,
                     font=ctk.CTkFont(size=15, weight='bold')).grid(
            row=0, column=0, sticky='w', padx=18, pady=(16, 2))
        ctk.CTkLabel(dlg, text=t('ui.onboarding_intro'), text_color=TEXT_MUTED,
                     justify='left', wraplength=380,
                     font=ctk.CTkFont(size=11)).grid(
            row=1, column=0, sticky='w', padx=18, pady=(0, 8))

        # -- Username entry + hint ---------------------------------------
        ctk.CTkLabel(dlg, text=t('ui.onboarding_username_label'),
                     text_color=TEXT, anchor='w',
                     font=ctk.CTkFont(size=12, weight='bold')).grid(
            row=2, column=0, sticky='w', padx=18, pady=(0, 2))
        entry = ctk.CTkEntry(dlg, width=384,
                             placeholder_text=t('ui.onboarding_username_label'))
        entry.grid(row=3, column=0, sticky='ew', padx=18)
        ctk.CTkLabel(dlg, text=t('ui.onboarding_username_hint'),
                     text_color=TEXT_FAINT, justify='left', wraplength=380,
                     font=ctk.CTkFont(size=10)).grid(
            row=4, column=0, sticky='w', padx=18, pady=(2, 8))

        # -- Opt-in checkbox (default OFF) -------------------------------
        ctk.CTkCheckBox(
            dlg, text=t('ui.onboarding_optin'), variable=optin_var,
            text_color=TEXT, fg_color=TEAL, hover_color=TEAL_HOVER,
            font=ctk.CTkFont(size=12)).grid(
            row=5, column=0, sticky='w', padx=18, pady=(0, 6))

        # -- Privacy note + what-is-sent ---------------------------------
        ctk.CTkLabel(dlg, text=t('ui.onboarding_privacy'), text_color=TEXT_MUTED,
                     justify='left', wraplength=380,
                     font=ctk.CTkFont(size=10)).grid(
            row=6, column=0, sticky='w', padx=18, pady=(0, 4))
        ctk.CTkLabel(dlg, text=t('ui.onboarding_whatissent'),
                     text_color=TEXT_FAINT, justify='left', wraplength=380,
                     font=ctk.CTkFont(size=10)).grid(
            row=7, column=0, sticky='w', padx=18, pady=(0, 8))

        btns = ctk.CTkFrame(dlg, fg_color='transparent')
        btns.grid(row=8, column=0, sticky='e', padx=18, pady=(0, 14))

        def _finish(enabled):
            username = ''
            try:
                username = entry.get().strip()[:cfgmod.USERNAME_MAXLEN]
            except Exception:
                username = ''
            # Opt-in only counts if the box is ticked AND a username was given.
            telemetry_enabled = bool(enabled) and bool(username)
            try:
                app.controller.update_config('telemetry', 'consented', True)
                app.controller.update_config('telemetry', 'enabled',
                                             telemetry_enabled)
                # username is a top-level key; update_config writes a section,
                # so set it on a copy + revalidate via current_config path.
                app._set_username(username)
            except Exception:
                pass
            _close()
            if callable(on_done):
                try:
                    on_done({'username': username,
                             'telemetry_enabled': telemetry_enabled})
                except Exception:
                    pass

        def _close():
            try:
                dlg.grab_release()
            except Exception:
                pass
            try:
                dlg.destroy()
            except Exception:
                pass

        ctk.CTkButton(
            btns, text=t('ui.onboarding_skip'), width=100, height=32,
            corner_radius=8, fg_color='transparent', hover_color=PANEL_HOVER,
            text_color=TEXT_MUTED, border_width=1, border_color=PANEL_LIGHT,
            command=lambda: _finish(False)).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(
            btns, text=t('ui.onboarding_save'), width=120, height=32,
            corner_radius=8, fg_color=TEAL, hover_color=TEAL_HOVER,
            text_color=INK,
            command=lambda: _finish(optin_var.get())).grid(row=0, column=1)

        dlg.protocol('WM_DELETE_WINDOW', lambda: _finish(False))
        try:
            dlg.after(60, dlg.grab_set)
            dlg.lift()
            entry.focus_set()
        except Exception:
            pass
        return dlg
    except Exception:
        # Build failed -> no telemetry, app continues. Best-effort: still mark
        # consent decided so we do not loop on every start.
        try:
            app.controller.update_config('telemetry', 'consented', True)
        except Exception:
            pass
        return None
