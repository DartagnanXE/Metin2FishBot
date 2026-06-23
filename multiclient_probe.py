# -*- coding: utf-8 -*-
"""Multiclient-Machbarkeits-Probe (Plan 2: Background-Input ohne Inject).

EIGENSTAENDIGES Diagnose-Tool -- fasst den Bot NICHT an. Klaert vor jedem
Refactor die zwei teuren Unbekannten fuer "4 Clients parallel ohne Injection":

  1. INPUT  -- Reagiert ein NICHT-fokussierter Metin2-Client auf PostMessage-
               Klicks? (Kernfrage von Plan 2 / "kein Fenster-Flackern".)
  2. CAPTURE-- Liefert die ECHTE Capture-Methode des Bots (GetWindowDC+BitBlt,
               siehe windowcapture.py) auch dann gueltige Pixel, wenn das
               Fenster VERDECKT im Hintergrund liegt? (Nur fuer Single-Monitor
               relevant; mit 2. Monitor egal.)

Laeuft auf WINDOWS (py multiclient_probe.py ...). Braucht pywin32 (hat der Bot
schon) fuer Capture; Input geht ueber reines ctypes (keine Installation).

NUTZUNG (siehe --help):
  py multiclient_probe.py list
  py multiclient_probe.py capture <hwnd_hex> [label]
  py multiclient_probe.py click   <hwnd_hex> <client_x> <client_y>

TYPISCHER ABLAUF:
  1) Genau EINEN Metin2-Client im FENSTERMODUS starten.
  2) `list` -> HWND des Clients ablesen (hex, z.B. 0x004213A0).
  3) `capture <hwnd>` -> probe_capture_visible.png pruefen (zeigt es den Client?).
  4) Ein anderes Fenster TEILWEISE ueber den Client legen, dann
     `capture <hwnd> occluded` -> probe_capture_occluded.png vs. visible
     vergleichen: noch der Client zu sehen oder schwarz?  -> Capture-Antwort.
  5) Im Client eine Stelle mit SICHTBARER Klick-Reaktion merken (z.B. ein
     Button). Aus dem capture-PNG die CLIENT-Pixelkoordinaten ablesen.
  6) Ein anderes Fenster fokussieren (Client NICHT mehr aktiv!), dann
     `click <hwnd> <x> <y>` -> der Client wird waehrend des Countdowns NICHT
     fokussiert; zuschauen, welche der 4 Strategien eine Reaktion ausloest.
     -> Input-Antwort.
"""

import ctypes
import sys
import time
from ctypes import wintypes

user32 = ctypes.WinDLL('user32', use_last_error=True)

# -- Win32-Message-Konstanten --------------------------------------------------
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
MK_LBUTTON = 0x0001


def _lparam(x, y):
    """Packt Client-Koordinaten in den lParam einer Maus-Message."""
    return (int(y) & 0xFFFF) << 16 | (int(x) & 0xFFFF)


def _post(hwnd, msg, wparam, lparam):
    return user32.PostMessageW(wintypes.HWND(hwnd), msg,
                               wintypes.WPARAM(wparam), wintypes.LPARAM(lparam))


def _send(hwnd, msg, wparam, lparam):
    return user32.SendMessageW(wintypes.HWND(hwnd), msg,
                               wintypes.WPARAM(wparam), wintypes.LPARAM(lparam))


# =============================================================================
# list -- sichtbare Fenster auflisten
# =============================================================================
def cmd_list():
    """Listet alle sichtbaren Fenster mit Titel + HWND (hex) + Client-Groesse."""
    EnumWindowsProc = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    rows = []

    def cb(hwnd, _l):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        if not title:
            return True
        rect = wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rect))
        cw, ch = rect.right - rect.left, rect.bottom - rect.top
        rows.append((hwnd, cw, ch, title))
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    print(f'{"HWND":>12}  {"Client":>11}  Titel')
    print('-' * 70)
    for hwnd, cw, ch, title in rows:
        print(f'{hex(hwnd):>12}  {cw:>4}x{ch:<5} {title[:48]}')
    print('\nMetin2-Client suchen (Client meist 800x600). Dessen HWND fuer die '
          'naechsten Schritte verwenden.')


def _grab(hwnd):
    """Fotografiert hwnd mit der ECHTEN Bot-Methode. Liefert BGR-Array o. None."""
    import windowcapture as wc
    title = _window_title(hwnd)
    wc.set_preferred_hwnd(hwnd)
    try:
        return wc.WindowCapture(title or '').get_screenshot()
    except Exception as exc:
        print(f'     (Capture-Fehler: {exc})')
        return None
    finally:
        wc.clear_preferred_hwnd()


# =============================================================================
# capture -- echte Bot-Methode (GetWindowDC+BitBlt) gegen Occlusion testen
# =============================================================================
def cmd_capture(hwnd, label):
    """Fotografiert das Fenster mit der ECHTEN Capture-Methode des Bots.

    Nutzt windowcapture.WindowCapture (set_preferred_hwnd), damit exakt das
    getestet wird, was der Bot live tut. Speichert PNG + meldet die mittlere
    Helligkeit: ~0 (schwarz) bedeutet, dass GetWindowDC+BitBlt bei diesem
    (DirectX-)Fenster im Hintergrund KEINE Pixel liefert -> Single-Monitor-
    Background scheidet aus (2. Monitor noetig).
    """
    try:
        import cv2
    except Exception as exc:
        print(f'FEHLER: Import fehlgeschlagen ({exc}). Auf Windows mit dem '
              'Bot-venv ausfuehren (pywin32 + opencv).')
        return

    img = _grab(hwnd)
    if img is None:
        print('FEHLER beim Capture (siehe oben).')
        return

    mean = float(img.mean())
    path = f'probe_capture_{label}.png'
    cv2.imwrite(path, img)
    print(f'Gespeichert: {path}  ({img.shape[1]}x{img.shape[0]}, '
          f'mittlere Helligkeit {mean:.1f}/255)')
    if mean < 3.0:
        print('  -> FAST SCHWARZ: Capture liefert im aktuellen Zustand keine '
              'Pixel. Bei occluded == Plan-2-Single-Monitor problematisch.')
    else:
        print('  -> Inhalt vorhanden. PNG oeffnen und pruefen: zeigt es den '
              'Client (auch wenn verdeckt)?')


# =============================================================================
# click -- 4 PostMessage/SendMessage-Strategien gegen Hintergrund-Fenster
# =============================================================================
def cmd_click(hwnd, x, y):
    """Feuert nacheinander 4 Klick-Strategien auf das (nicht-fokussierte) Fenster.

    Zwischen den Strategien je 1.6s Pause + Konsolen-Ausgabe, damit zuordenbar
    ist, WELCHE eine Reaktion ausloest. Der Client darf waehrenddessen NICHT
    fokussiert sein -- genau das ist der Test.
    """
    title = _window_title(hwnd)
    print(f'Ziel: {hex(hwnd)}  "{title}"  Client-Klick @ ({x},{y})')
    print('JETZT ein ANDERES Fenster anklicken, damit der Client den Fokus '
          'verliert. Start in 4s ...')
    for s in (4, 3, 2, 1):
        print(f'  {s}', end=' ', flush=True)
        time.sleep(1.0)
    print('\nFeuere Strategien -- auf Reaktion im Client achten:\n')

    lp = _lparam(x, y)
    child = _child_at(hwnd, x, y)

    _strategy('S1 PostMessage move+down+up -> Hauptfenster',
              lambda: _click_seq(_post, hwnd, lp))
    _strategy('S2 SendMessage  move+down+up -> Hauptfenster (synchron)',
              lambda: _click_seq(_send, hwnd, lp))
    if child and child != hwnd:
        _strategy(f'S3 PostMessage move+down+up -> Kindfenster {hex(child)}',
                  lambda: _click_seq(_post, child, lp))
    else:
        print('S3 uebersprungen (kein separates Kindfenster an der Stelle).')
    _strategy('S4 PostMessage Doppelklick (WM_LBUTTONDBLCLK) -> Hauptfenster',
              lambda: _dblclick_seq(hwnd, lp))

    print('\nFertig. Hat EINE Strategie reagiert -> Plan 2 (Input) ist machbar; '
          'merke dir welche. Keine -> Plan 1 (Time-Multiplex).')


def _click_seq(fn, hwnd, lp):
    fn(hwnd, WM_MOUSEMOVE, 0, lp)
    time.sleep(0.02)
    fn(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lp)
    time.sleep(0.04)
    fn(hwnd, WM_LBUTTONUP, 0, lp)


def _dblclick_seq(hwnd, lp):
    _post(hwnd, WM_MOUSEMOVE, 0, lp)
    time.sleep(0.02)
    _post(hwnd, WM_LBUTTONDBLCLK, MK_LBUTTON, lp)
    time.sleep(0.04)
    _post(hwnd, WM_LBUTTONUP, 0, lp)


def _strategy(name, fn):
    print(f'  >> {name}')
    try:
        fn()
    except Exception as exc:
        print(f'     (Fehler: {exc})')
    time.sleep(1.6)


# =============================================================================
# autotest -- selbst-beobachtend: Klick -> Screenshot-Diff (keine Augen noetig)
# =============================================================================
def cmd_autotest(hwnd, x, y):
    """Feuert jede Strategie und MISST per Vorher/Nachher-Capture die Reaktion.

    So kann der Test ohne menschliche Beobachtung gefahren werden: aendern sich
    nach einer Strategie die Pixel an/um die Klickstelle, hat der Klick gewirkt.
    Voraussetzung: Capture liefert beim NICHT fokussierten Fenster Pixel (wird
    zuerst geprueft). Schreibt fuer die staerkste Reaktion before/after-PNGs.
    """
    try:
        import cv2  # noqa: F401  (Backend fuer _grab/imwrite)
        import numpy as np
    except Exception as exc:
        print(f'FEHLER: Import fehlgeschlagen ({exc}).')
        return

    print(f'Ziel: {hex(hwnd)}  "{_window_title(hwnd)}"  Klick @ ({x},{y})')
    _focus_away(hwnd)
    fg = user32.GetForegroundWindow()
    state = 'HINTERGRUND' if fg != hwnd else 'VORDERGRUND (!)'
    print(f'Fokus-Status des Clients beim Test: {state} '
          f'(foreground={hex(fg)})')

    base = _grab(hwnd)
    if base is None:
        print('-> Capture liefert beim nicht-fokussierten Fenster NICHTS. '
              'Input-Selbsttest nicht moeglich; manuell mit `click` + Augen.')
        return
    if float(base.mean()) < 3.0:
        print('-> Capture ist SCHWARZ (unfokussiert). Single-Monitor-Background '
              'scheidet aus; fuer den Input-Test 2. Monitor / Augen noetig.')
        return
    print(f'Capture unfokussiert OK (Helligkeit {float(base.mean()):.1f}). '
          'Messe Strategien:\n')

    lp = _lparam(x, y)
    child = _child_at(hwnd, x, y)
    strategies = [
        ('S1 Post move+down+up', lambda: _click_seq(_post, hwnd, lp)),
        ('S2 Send move+down+up', lambda: _click_seq(_send, hwnd, lp)),
    ]
    if child and child != hwnd:
        strategies.append((f'S3 Post -> Kind {hex(child)}',
                           lambda: _click_seq(_post, child, lp)))
    strategies.append(('S4 Post Doppelklick', lambda: _dblclick_seq(hwnd, lp)))

    results = []
    for name, fn in strategies:
        before = _grab(hwnd)
        try:
            fn()
        except Exception as exc:
            print(f'  {name}: Fehler {exc}')
            continue
        time.sleep(0.9)
        after = _grab(hwnd)
        diff = _frame_diff(before, after, np)
        results.append((diff, name, before, after))
        verdict = 'REAKTION' if diff > 1.5 else 'keine'
        print(f'  {name:<26} Pixel-Aenderung {diff:6.2f}  -> {verdict}')

    if results:
        results.sort(reverse=True, key=lambda r: r[0])
        top = results[0]
        cv2.imwrite('probe_autotest_before.png', top[2])
        cv2.imwrite('probe_autotest_after.png', top[3])
        print(f'\nStaerkste: {top[1]} (Diff {top[0]:.2f}). PNGs: '
              'probe_autotest_before/after.png')
        if top[0] > 1.5:
            print('=> Plan 2 (Background-Input) MACHBAR. Strategie merken.')
        else:
            print('=> Keine Strategie reagiert -> Plan 1 (Time-Multiplex).')


def _frame_diff(a, b, np):
    """Mittlere absolute Pixel-Differenz zweier Frames (0..255). Robust b. Shape."""
    if a is None or b is None or a.shape != b.shape:
        return 0.0
    return float(np.abs(a.astype('int16') - b.astype('int16')).mean())


def _focus_away(hwnd):
    """Schiebt den Fokus WEG vom Client, damit der Test 'Hintergrund' misst.

    Versucht das Konsolenfenster nach vorn; klappt das nicht (Fokus-Steal-
    Regeln), das erste sichtbare Fremdfenster. Wirft nie.
    """
    try:
        kernel32 = ctypes.WinDLL('kernel32')
        con = kernel32.GetConsoleWindow()
        if con and con != hwnd:
            user32.SetForegroundWindow(wintypes.HWND(con))
            time.sleep(0.2)
        if user32.GetForegroundWindow() != hwnd:
            return
        # Fallback: irgendein anderes sichtbares Fenster nach vorn.
        EnumWindowsProc = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        picked = []

        def cb(h, _l):
            if h != hwnd and user32.IsWindowVisible(h) \
                    and user32.GetWindowTextLengthW(h) > 0:
                picked.append(h)
                return False
            return True

        user32.EnumWindows(EnumWindowsProc(cb), 0)
        if picked:
            user32.SetForegroundWindow(wintypes.HWND(picked[0]))
            time.sleep(0.2)
    except Exception:
        pass


# =============================================================================
# activatetest -- Q1: click-to-activate (Plan 1). Aktiviert ein echter Klick das
# unfokussierte Fenster? Loest die Titelleiste KEINE Spielaktion aus? Wird der
# erste (aktivierende) Client-Klick "gefressen" oder mitverarbeitet?
# =============================================================================
def cmd_activatetest(hwnd, x, y):
    """Misst den click-to-activate-Pfad (echter Cursor) am unfokussierten Fenster.

    Test A (Titelleiste): aktiviert + KEINE Spielaktion erwartet -> die "harmlose
    Aktivierungszone" fuer Tasten-Bursts.
    Test B (Client-Punkt): aktiviert UND wird der Klick verarbeitet (Panel oeffnet)?
      -> wenn ja, genuegt EIN Nutzklick (Aktivierung+Aktion); wenn Fokus kam aber
      keine Aktion, wird der erste Klick von der Aktivierung gefressen.
    Bewegt den ECHTEN Cursor (mouse_event). Wirft nie fatale Fehler.
    """
    try:
        import cv2  # noqa: F401
        import numpy as np
        import win32gui
    except Exception as exc:
        print(f'FEHLER: Import fehlgeschlagen ({exc}).')
        return

    r = win32gui.GetWindowRect(hwnd)
    title_pt = (r[0] + (r[2] - r[0]) // 2, r[1] + 15)   # Titelleiste (~15px)
    client_pt = (r[0] + 8 + x, r[1] + 30 + y)           # Bot-Crop 8/30 + Client
    print(f'Ziel {hex(hwnd)} "{_window_title(hwnd)}"  Fenster-Rect {r}')

    _run_activation_case('A Titelleiste', hwnd, title_pt, np, win32gui,
                         expect='Aktivierung JA, Spielaktion NEIN')
    _run_activation_case('B Client-Punkt', hwnd, client_pt, np, win32gui,
                         expect=f'Client({x},{y}): Aktivierung + ggf. Aktion')

    print('\nDeutung: Test A mit Fokus=JA + diff~0 -> Titelleiste ist die sichere '
          'Aktivierungszone. Test B Fokus=JA + diff hoch -> ein Nutzklick reicht; '
          'Fokus=JA + diff~0 -> erster Klick wird gefressen (Pre-Aktivierung noetig).')


def _run_activation_case(name, hwnd, screen_pt, np, win32gui, expect):
    _focus_away(hwnd)
    _raise_noactivate(hwnd)
    time.sleep(0.25)
    before = _grab(hwnd)
    fg_before = user32.GetForegroundWindow()
    _real_click(screen_pt)
    time.sleep(0.9)
    fg_after = user32.GetForegroundWindow()
    after = _grab(hwnd)
    diff = _frame_diff(before, after, np)
    activated = (fg_after == hwnd and fg_before != hwnd)
    print(f'\n[{name}] erwartet: {expect}')
    print(f'  foreground vorher={hex(fg_before)} nachher={hex(fg_after)} '
          f'-> aktiviert={activated}')
    print(f'  Frame-Diff={diff:.2f} -> {"SPIELAKTION/Reaktion" if diff > 1.5 else "keine sichtbare Aktion"}')


def _raise_noactivate(hwnd):
    """Hebt das Fenster sichtbar nach oben OHNE es zu aktivieren (Z-Order)."""
    try:
        SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = 0x0002, 0x0001, 0x0010
        user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(0), 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    except Exception:
        pass


def _real_click(screen_pt):
    """Echter Links-Klick an Bildschirm-Koordinate (bewegt den globalen Cursor)."""
    try:
        user32.SetCursorPos(int(screen_pt[0]), int(screen_pt[1]))
        time.sleep(0.1)
        user32.mouse_event(0x0002, 0, 0, 0, 0)   # LEFTDOWN
        time.sleep(0.06)
        user32.mouse_event(0x0004, 0, 0, 0, 0)   # LEFTUP
    except Exception as exc:
        print(f'     (real-click Fehler: {exc})')


# =============================================================================
# Helfer
# =============================================================================
def _window_title(hwnd):
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ''
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _child_at(hwnd, x, y):
    """Kindfenster an Client-Punkt (x,y) -- manche UIs hoeren nur dort zu."""
    try:
        pt = wintypes.POINT(int(x), int(y))
        return user32.ChildWindowFromPoint(hwnd, pt) or hwnd
    except Exception:
        return hwnd


def _parse_hwnd(text):
    return int(text, 16) if text.lower().startswith('0x') else int(text)


def main(argv):
    # Windows-Konsole ist oft cp1252 -> ein Fenstertitel mit Sonderzeichen
    # (z.B. Braille/Emoji) wuerde print() mit UnicodeEncodeError crashen.
    # Nicht-codierbare Zeichen ersetzen statt abstuerzen.
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass
    if len(argv) < 2 or argv[1] in ('-h', '--help', 'help'):
        print(__doc__)
        return
    cmd = argv[1]
    try:
        if cmd == 'list':
            cmd_list()
        elif cmd == 'capture':
            hwnd = _parse_hwnd(argv[2])
            label = argv[3] if len(argv) > 3 else 'visible'
            cmd_capture(hwnd, label)
        elif cmd == 'click':
            hwnd = _parse_hwnd(argv[2])
            cmd_click(hwnd, int(argv[3]), int(argv[4]))
        elif cmd == 'autotest':
            hwnd = _parse_hwnd(argv[2])
            cmd_autotest(hwnd, int(argv[3]), int(argv[4]))
        elif cmd == 'activatetest':
            hwnd = _parse_hwnd(argv[2])
            cmd_activatetest(hwnd, int(argv[3]), int(argv[4]))
        else:
            print(f'Unbekanntes Kommando: {cmd}\n')
            print(__doc__)
    except (IndexError, ValueError):
        print('Argument-Fehler. -> py multiclient_probe.py --help')


if __name__ == '__main__':
    main(sys.argv)
