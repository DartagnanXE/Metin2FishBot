# -*- coding: utf-8 -*-
"""Ranking tab body (its OWN module so app.py does not grow further).

Renders three blocks:
  * STATS -- the four local counters from :mod:`stats` (live, read from
    ``app._stats``).
  * EVENT STATUS -- the current fish-event state from
    :func:`event_window.status` (active / minutes-left / warn / tz-unavailable).
  * LEADERBOARD -- daily + all-time, fetched on a WORKER thread via
    ``telemetry.client.fetch_leaderboard`` and marshalled back with
    ``app.after(0, ...)`` (the worker NEVER touches Tk). A Refresh button +
    auto-fetch on first show. Telemetry-off / banned states show a clear notice
    instead of the board.

Defensive throughout: every render path is wrapped; a missing widget or a bad
snapshot can never crash the UI. All strings via ``i18n.t`` (EN/DE parity).
"""

import threading
from datetime import datetime

import customtkinter as ctk

from i18n import t
from interface import config as cfgmod
from interface.widgets import (PANEL, PANEL_LIGHT, TEAL, TEAL_BRIGHT, TEAL_SOFT,
                               TEXT, TEXT_FAINT, TEXT_MUTED)

try:
    import event_window
except Exception:                       # pragma: no cover - defensive
    event_window = None

try:
    import stats as statsmod
except Exception:                       # pragma: no cover
    statsmod = None


def _hms(total_seconds):
    """Seconds -> 'HH:MM:SS' (clamped >= 0). Never raises."""
    try:
        total = max(0, int(total_seconds))
    except Exception:
        return '00:00:00'
    return '{:02d}:{:02d}:{:02d}'.format(
        total // 3600, (total % 3600) // 60, total % 60)


def build_ranking_view(app, parent):
    """Build the ranking view into ``parent`` and return the frame.

    Stores live-update handles on ``app`` (``_rank_stats_labels``,
    ``_rank_event_label``, ``_rank_board_body``, ``_rank_notice``). Never raises.
    """
    view = parent
    try:
        view.grid_columnconfigure(0, weight=1)

        # -- Stats card --------------------------------------------------
        stats_card = _card(view, t('ui.stats_title'))
        stats_card.grid(row=1, column=0, sticky='ew', pady=(0, 8))
        body = stats_card.body
        body.grid_columnconfigure(1, weight=1)
        app._rank_stats_labels = {}
        rows = (('catches', 'ui.stats_catches'),
                ('puzzles', 'ui.stats_puzzles'),
                ('fishing_time', 'ui.stats_fishing_time'),
                ('puzzler_time', 'ui.stats_puzzler_time'))
        for i, (keyname, label_key) in enumerate(rows):
            ctk.CTkLabel(body, text=t(label_key), anchor='w',
                         text_color=TEXT_MUTED,
                         font=ctk.CTkFont(size=11)).grid(
                row=i, column=0, sticky='w', pady=1)
            val = ctk.CTkLabel(body, text='-', anchor='e', text_color=TEAL,
                               font=ctk.CTkFont(size=13, weight='bold'))
            val.grid(row=i, column=1, sticky='e', pady=1)
            app._rank_stats_labels[keyname] = val

        # -- Event status card -------------------------------------------
        event_card = _card(view, t('ui.event_status_title'))
        event_card.grid(row=2, column=0, sticky='ew', pady=(0, 8))
        app._rank_event_label = ctk.CTkLabel(
            event_card.body, text='-', anchor='w', justify='left',
            text_color=TEXT, wraplength=340, font=ctk.CTkFont(size=11))
        app._rank_event_label.grid(row=0, column=0, sticky='w')

        # -- Leaderboard card --------------------------------------------
        board_card = _card(view, t('ui.leaderboard_title'))
        board_card.grid(row=3, column=0, sticky='ew', pady=(0, 4))
        head = ctk.CTkFrame(board_card.body, fg_color='transparent')
        head.grid(row=0, column=0, sticky='ew')
        head.grid_columnconfigure(0, weight=1)
        app._rank_refresh_btn = ctk.CTkButton(
            head, text=t('ui.leaderboard_refresh'), width=110, height=28,
            corner_radius=8, fg_color=PANEL_LIGHT, hover_color=TEAL_SOFT,
            text_color=TEXT, font=ctk.CTkFont(size=11),
            command=lambda: refresh_leaderboard(app))
        app._rank_refresh_btn.grid(row=0, column=1, sticky='e')

        # Notice line (telemetry-off / banned / fetch-failed / loading).
        app._rank_notice = ctk.CTkLabel(
            board_card.body, text='', anchor='w', justify='left',
            text_color=TEXT_FAINT, wraplength=340, font=ctk.CTkFont(size=11))
        app._rank_notice.grid(row=1, column=0, sticky='w', pady=(4, 2))

        # Board body (rows of rank/player/catches).
        app._rank_board_body = ctk.CTkFrame(board_card.body,
                                            fg_color='transparent')
        app._rank_board_body.grid(row=2, column=0, sticky='ew', pady=(2, 0))
        app._rank_board_body.grid_columnconfigure(1, weight=1)

        # Initial render of stats + event; auto-fetch leaderboard once.
        render_stats(app, getattr(app, '_stats', None))
        render_event_status(app, _current_status(app))
        refresh_leaderboard(app)
    except Exception:
        pass
    return view


def _card(parent, title):
    """A titled panel card (mirrors interface.widgets.Section shape minimally)."""
    card = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=10)
    card.grid_columnconfigure(0, weight=1)
    ctk.CTkLabel(card, text=title, anchor='w', text_color=TEXT_FAINT,
                 font=ctk.CTkFont(size=11, weight='bold')).grid(
        row=0, column=0, sticky='w', padx=12, pady=(8, 2))
    body = ctk.CTkFrame(card, fg_color='transparent')
    body.grid(row=1, column=0, sticky='ew', padx=12, pady=(0, 10))
    body.grid_columnconfigure(0, weight=1)
    card.body = body
    return card


def render_stats(app, stats):
    """Write the four counters into the live labels. Never raises."""
    try:
        labels = getattr(app, '_rank_stats_labels', None)
        if not labels:
            return
        s = statsmod.validate(stats) if statsmod else (stats or {})
        labels['catches'].configure(text=str(s.get('fishing_catches', 0)))
        labels['puzzles'].configure(text=str(s.get('puzzles_solved', 0)))
        labels['fishing_time'].configure(
            text=_hms(s.get('fishing_runtime_s', 0)))
        labels['puzzler_time'].configure(
            text=_hms(s.get('puzzler_runtime_s', 0)))
    except Exception:
        pass


def _current_status(app):
    """Compute the current event status snapshot from config. Never raises."""
    try:
        if event_window is None:
            return {'active': False, 'tz_available': False,
                    'minutes_left': None}
        events = app.controller.current_config()['events']
        return event_window.status(datetime.now(), events.get('windows') or (),
                                   events.get('warn_minutes', 0))
    except Exception:
        return {'active': False, 'tz_available': True, 'minutes_left': None}


def render_event_status(app, status):
    """Render the fish-event status line. Never raises."""
    try:
        label = getattr(app, '_rank_event_label', None)
        if label is None:
            return
        status = status or {}
        if not status.get('tz_available', True):
            label.configure(text=t('ui.event_status_unknown'),
                            text_color=TEXT_FAINT)
            return
        if status.get('active'):
            left = status.get('minutes_left')
            label.configure(
                text=t('ui.event_active_now',
                       minutes=(left if left is not None else 0)),
                text_color=TEAL_BRIGHT)
        else:
            label.configure(text=t('ui.event_inactive'), text_color=TEXT_MUTED)
    except Exception:
        pass


def refresh_leaderboard(app):
    """Fetch the leaderboard on a worker thread (telemetry/banned states first).

    Telemetry-off or banned -> show a notice and skip the network. Otherwise
    spawn a daemon thread; the result is marshalled back via ``app.after(0)``.
    Never raises.
    """
    try:
        # Always refresh stats + event when the user hits Refresh (cheap).
        render_stats(app, getattr(app, '_stats', None))
        render_event_status(app, _current_status(app))

        cfg = app.controller.current_config()
        telemetry = cfg.get('telemetry', {})
        if getattr(app, '_ranking_banned', False):
            _set_notice(app, t('ui.ranking_banned'))
            _clear_board(app)
            return
        if not telemetry.get('enabled'):
            _set_notice(app, t('ui.ranking_telemetry_off'))
            _clear_board(app)
            return

        url = telemetry.get('leaderboard_url') or cfgmod.DEFAULT_LEADERBOARD_URL
        username = str(cfg.get('username', '') or '')
        _set_notice(app, t('ui.leaderboard_loading'))

        def _worker():
            from telemetry import client
            data = client.fetch_leaderboard(url)
            try:
                app.after(0, lambda: _on_board(app, data, username))
            except Exception:
                pass

        threading.Thread(target=_worker, name='leaderboard-fetch',
                         daemon=True).start()
    except Exception:
        pass


def _on_board(app, data, username):
    """GUI-thread: render fetched leaderboard data (or a failure notice)."""
    try:
        if not isinstance(data, dict):
            _set_notice(app, t('ui.leaderboard_fetch_failed'))
            _clear_board(app)
            return
        # Accept either {'daily':[...], 'all':[...]} or a flat {'entries':[...]}.
        entries = (data.get('all') or data.get('daily')
                   or data.get('entries') or [])
        if not entries:
            _set_notice(app, t('ui.leaderboard_empty'))
            _clear_board(app)
            return
        _set_notice(app, '')
        _render_board(app, entries, username)
    except Exception:
        _set_notice(app, t('ui.leaderboard_fetch_failed'))


def _render_board(app, entries, username):
    """Render up to ~10 leaderboard rows, highlighting the user's own row."""
    try:
        body = getattr(app, '_rank_board_body', None)
        if body is None:
            return
        for child in body.winfo_children():
            child.destroy()
        # Header row.
        _board_row(body, 0, t('ui.leaderboard_rank'), t('ui.leaderboard_player'),
                   t('ui.leaderboard_catches'), header=True)
        own_rank = None
        for i, entry in enumerate(entries[:10], start=1):
            try:
                name = str(entry.get('username', '?'))
                catches = entry.get('fishing_catches', entry.get('catches', 0))
                rank = entry.get('rank', i)
            except Exception:
                continue
            mine = bool(username) and name == username
            if mine:
                own_rank = rank
            _board_row(body, i, str(rank), name, str(catches), mine=mine)
        if own_rank is not None:
            _set_notice(app, t('ui.leaderboard_your_rank', rank=own_rank))
    except Exception:
        pass


def _board_row(body, row, rank, name, catches, header=False, mine=False):
    color = TEAL_BRIGHT if mine else (TEXT_FAINT if header else TEXT)
    weight = 'bold' if (header or mine) else 'normal'
    font = ctk.CTkFont(size=11, weight=weight)
    ctk.CTkLabel(body, text=rank, width=36, anchor='w', text_color=color,
                 font=font).grid(row=row, column=0, sticky='w')
    ctk.CTkLabel(body, text=name, anchor='w', text_color=color,
                 font=font).grid(row=row, column=1, sticky='w', padx=(4, 4))
    ctk.CTkLabel(body, text=catches, anchor='e', text_color=color,
                 font=font).grid(row=row, column=2, sticky='e')


def _clear_board(app):
    try:
        body = getattr(app, '_rank_board_body', None)
        if body is None:
            return
        for child in body.winfo_children():
            child.destroy()
    except Exception:
        pass


def _set_notice(app, text):
    try:
        notice = getattr(app, '_rank_notice', None)
        if notice is not None:
            notice.configure(text=text)
    except Exception:
        pass
