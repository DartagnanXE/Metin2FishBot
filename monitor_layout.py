# -*- coding: utf-8 -*-
"""Monitor-Erkennung + Fenster-Kachelung fuer Multiclient (1-4 Clients).

Anforderung: Der Bot erkennt die Monitore, verteilt bis zu 4 Metin2-Clients
NEBENEINANDER auf dem Monitor der WAHL des Nutzers; sind MEHR als die gewaehlte
Zahl Clients offen, wird MARKIERT, welche tatsaechlich gesteuert werden.

Trennung fuer Testbarkeit:
  * REINE Geometrie/Auswahl (``tile_layout``, ``choose_clients``) -- keine win32,
    voll unit-testbar.
  * Duenne win32-Huelle (``enumerate_monitors``, ``move_window``,
    ``mark_window_title``) -- I/O, am echten Desktop verifizierbar.

Fenstergroesse ist FIX (Client 800x600 = aussen ~816x639, siehe
windowcapture.BORDER/TITLEBAR) -- die Detection-Templates sind darauf kalibriert,
daher wird NICHT skaliert, sondern positioniert.
"""

# Aussenmasse eines 800x600-Client-Fensters (Client + 2*BORDER, + TITLEBAR+BORDER).
DEFAULT_WIN_W = 816
DEFAULT_WIN_H = 639


def _grid_candidates(n):
    """Alle (cols, rows)-Raster, die n Fenster fassen (cols 1..n)."""
    out = []
    for cols in range(1, n + 1):
        rows = (n + cols - 1) // cols      # ceil(n/cols)
        out.append((cols, rows))
    return out


def tile_layout(mon_x, mon_y, mon_w, mon_h, n,
                win_w=DEFAULT_WIN_W, win_h=DEFAULT_WIN_H):
    """Kachel-Positionen fuer ``n`` Fenster im Monitor-(Arbeits-)Bereich.

    Waehlt das Raster, das (a) moeglichst NEBENEINANDER ist (viele Spalten) und
    (b) wenn moeglich UEBERLAPPUNGSFREI passt. Passt nichts vollstaendig, wird
    das flaechen-beste Raster genommen und ``fits=False`` gemeldet (Overlap; der
    Aufruferschicht kann warnen -- Capture funktioniert per GetWindowDC auch bei
    Verdeckung, aber click-to-activate ist bei Overlap weniger sauber).

    :return: dict ``{positions:[(x,y),...], cols, rows, fits, win_w, win_h}``.
    """
    n = max(1, int(n))
    fitting = []
    all_cands = []
    for cols, rows in _grid_candidates(n):
        need_w = cols * win_w
        need_h = rows * win_h
        fits = need_w <= mon_w and need_h <= mon_h
        # Score: passend bevorzugt; dann mehr Spalten (nebeneinander); dann
        # weniger Ueberlauf.
        overflow = max(0, need_w - mon_w) + max(0, need_h - mon_h)
        all_cands.append((fits, cols, rows, overflow))
        if fits:
            fitting.append((cols, rows))

    if fitting:
        # Unter den passenden: die mit den MEISTEN Spalten (max nebeneinander).
        cols, rows = max(fitting, key=lambda cr: cr[0])
        fits = True
    else:
        # Keins passt -> geringster Ueberlauf, dann mehr Spalten.
        best = min(all_cands, key=lambda c: (c[3], -c[1]))
        cols, rows = best[1], best[2]
        fits = False

    positions = []
    # Bei Nicht-Passen die Schrittweite auf den Monitor zwingen (gleichmaessige
    # Verteilung mit minimalem Overlap) statt aus dem Bildschirm zu laufen.
    if fits:
        step_x, step_y = win_w, win_h
    else:
        step_x = (mon_w - win_w) // (cols - 1) if cols > 1 else 0
        step_y = (mon_h - win_h) // (rows - 1) if rows > 1 else 0
        step_x = max(0, step_x)
        step_y = max(0, step_y)
    for i in range(n):
        r, c = divmod(i, cols)
        positions.append((mon_x + c * step_x, mon_y + r * step_y))
    return {'positions': positions, 'cols': cols, 'rows': rows,
            'fits': fits, 'win_w': win_w, 'win_h': win_h}


def choose_clients(windows, n, preferred_hwnds=None):
    """Waehlt bis zu ``n`` Clients aus ``windows`` (deterministisch).

    :param windows: Liste von Dicts mit mind. ``'hwnd'`` (z.B. aus
        ``windowcapture.enumerate_game_windows``); Reihenfolge = Stabilitaet.
    :param n: gewuenschte Client-Zahl (1-4 typ.).
    :param preferred_hwnds: optionale HWNDs, die zuerst gewaehlt werden (z.B. die
        vom Nutzer im Picker bestaetigten).
    :return: dict ``{chosen:[w,...], unused:[w,...]}`` -- ``unused`` sind die zu
        markierenden ueberzaehligen Fenster.
    """
    n = max(0, int(n))
    windows = list(windows or [])
    preferred = list(preferred_hwnds or [])
    by_hwnd = {w.get('hwnd'): w for w in windows}

    chosen = []
    seen = set()
    # 1) bevorzugte zuerst (in angegebener Reihenfolge), nur wenn noch vorhanden.
    for h in preferred:
        w = by_hwnd.get(h)
        if w is not None and h not in seen and len(chosen) < n:
            chosen.append(w)
            seen.add(h)
    # 2) restliche in stabiler Eingabereihenfolge auffuellen.
    for w in windows:
        h = w.get('hwnd')
        if h not in seen and len(chosen) < n:
            chosen.append(w)
            seen.add(h)
    unused = [w for w in windows if w.get('hwnd') not in seen]
    return {'chosen': chosen, 'unused': unused}


# =============================================================================
# Duenne win32-Huelle (I/O) -- am echten Desktop verifizierbar
# =============================================================================
def enumerate_monitors():
    """Liste der Monitore als ``{index, x, y, w, h, primary, name}`` (Arbeitsbereich).

    Nutzt die Work-Area (ohne Taskleiste). Wirft NIE -> ``[]`` bei Fehler/headless.
    """
    try:
        import win32api
        import win32con
        out = []
        for i, mon in enumerate(win32api.EnumDisplayMonitors()):
            hmon = mon[0]
            info = win32api.GetMonitorInfo(hmon)
            wx0, wy0, wx1, wy1 = info['Work']      # Arbeitsbereich
            mx0, my0, mx1, my1 = info['Monitor']
            out.append({
                'index': i,
                'x': wx0, 'y': wy0, 'w': wx1 - wx0, 'h': wy1 - wy0,
                'primary': bool(info.get('Flags', 0) & win32con.MONITORINFOF_PRIMARY),
                'name': info.get('Device', f'\\\\.\\DISPLAY{i + 1}'),
                'full': (mx0, my0, mx1 - mx0, my1 - my0),
            })
        return out
    except Exception:
        return []


def move_window(hwnd, x, y, w=None, h=None):
    """Verschiebt (und optional resized) ein Fenster OHNE Fokus zu stehlen.

    Setzt die Client-Groesse auf 800x600 via ``windowcapture.set_client_size``,
    wenn ``w/h`` None sind. Wirft NIE -> ``False`` bei Fehler.
    """
    try:
        import win32gui
        import win32con
        if w is not None and h is not None:
            win32gui.SetWindowPos(hwnd, 0, int(x), int(y), int(w), int(h),
                                  win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
        else:
            win32gui.SetWindowPos(hwnd, 0, int(x), int(y), 0, 0,
                                  win32con.SWP_NOSIZE | win32con.SWP_NOZORDER
                                  | win32con.SWP_NOACTIVATE)
        return True
    except Exception:
        return False


def mark_window_title(hwnd, label):
    """Markiert ein Fenster sichtbar per Titel-Praefix (z.B. ``[M2FB#1] METIN2``).

    Dient dazu, bei MEHR offenen Clients als gesteuert kenntlich zu machen,
    welche der Bot nutzt (chosen) bzw. ignoriert (unused -> z.B. ``[frei]``).
    Wirft NIE -> ``False`` bei Fehler.
    """
    try:
        import win32gui
        cur = win32gui.GetWindowText(hwnd)
        base = cur.split('] ', 1)[-1] if cur.startswith('[') else cur
        win32gui.SetWindowText(hwnd, f'{label} {base}' if label else base)
        return True
    except Exception:
        return False
