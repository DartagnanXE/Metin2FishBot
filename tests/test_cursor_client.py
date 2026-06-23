# -*- coding: utf-8 -*-
"""T5: CursorClient.burst -- gehaertete Sequenz (Findings #1/#4 + G1/G2) als
Assertions. Voll gemockt, kein echter Cursor/Fenster.
"""

import unittest

import cursor_client as cc


class FakeInput:
    """Protokolliert alle Input-Aufrufe in Reihenfolge."""

    def __init__(self):
        self.log = []
        self.PAUSE = None

    def moveTo(self, x, y):
        self.log.append(('moveTo', x, y))

    def click(self, button='left'):
        self.log.append(('click', button))

    def mouseDown(self, button='left'):
        self.log.append(('mouseDown', button))

    def mouseUp(self, button='left'):
        self.log.append(('mouseUp', button))

    def keyDown(self, k):
        self.log.append(('keyDown', k))

    def keyUp(self, k):
        self.log.append(('keyUp', k))


def _make(inp, foreground_seq, stop_seq=None, acquired=None, released=None):
    """Baut einen CursorClient mit gemockten Abhaengigkeiten.

    foreground_seq: Werte, die foreground_fn nacheinander liefert.
    """
    fg_it = iter(foreground_seq)
    stop_it = iter(stop_seq or [])
    acquired = acquired if acquired is not None else []
    released = released if released is not None else []

    def acquire(idx, holds_button):
        acquired.append((idx, holds_button))

    def release(idx):
        released.append(idx)

    def stop_check():
        try:
            return next(stop_it)
        except StopIteration:
            return False

    return cc.CursorClient(
        idx=0, hwnd=42,
        to_screen=lambda cx, cy: (cx + 1000, cy + 2000),
        acquire=acquire, release=release,
        inp=inp,
        foreground_fn=lambda: next(fg_it),
        activate_fn=lambda hwnd: inp.log.append(('activate', hwnd)),
        stop_check=stop_check,
        sleep=lambda s: None,
        settle_s=0.0, activate_retries=3, mouse_pause=0.15,
        needs_activation=True)


class TestBurstHappyPath(unittest.TestCase):
    def test_click_full_sequence_order(self):
        inp = FakeInput()
        acq, rel = [], []
        c = _make(inp, foreground_seq=[42], acquired=acq, released=rel)
        c.click(100, 200)
        # Erwartete Reihenfolge: neutralize(L,R) -> activate -> [Fokus ok]
        # -> moveTo(screen) -> click -> neutralize(L,R)
        self.assertEqual(inp.log, [
            ('mouseUp', 'left'), ('mouseUp', 'right'),     # Finding #1 Eingang
            ('activate', 42),
            ('moveTo', 1100, 2200), ('click', 'left'),     # to_screen-Konvertierung
            ('mouseUp', 'left'), ('mouseUp', 'right'),     # Finding #1 finally
        ])
        self.assertEqual(acq, [(0, False)])               # Lease genommen
        self.assertEqual(rel, [0])                        # und freigegeben
        self.assertEqual(inp.PAUSE, 0.15)                 # G2 nur in der Lease

    def test_drag_marks_holds_button_and_releases_button(self):
        inp = FakeInput()
        acq = []
        c = _make(inp, foreground_seq=[42], acquired=acq)
        c.drag([(10, 10), (20, 20), (30, 30)])
        self.assertEqual(acq, [(0, True)])                # holds_button=True!
        # mouseDown genau einmal, mouseUp(left) am Drag-Ende UND im finally:
        downs = [e for e in inp.log if e == ('mouseDown', 'left')]
        self.assertEqual(len(downs), 1)
        # letzter Eintrag ist die finally-Neutralisierung
        self.assertEqual(inp.log[-2:], [('mouseUp', 'left'), ('mouseUp', 'right')])


class TestSingleClientLegacyMode(unittest.TestCase):
    """needs_activation=False -> KEINE Aktivierung/Fokus-Gate (legacy-identisch)."""

    def test_no_activation_no_foreground_call(self):
        inp = FakeInput()
        fg_calls = {'n': 0}

        def fg():
            fg_calls['n'] += 1
            return 999          # falscher Fokus -- darf egal sein

        c = cc.CursorClient(
            idx=0, hwnd=42,
            to_screen=lambda cx, cy: (cx, cy),
            acquire=lambda i, h: None, release=lambda i: None,
            inp=inp, foreground_fn=fg, activate_fn=lambda h: inp.log.append('A'),
            stop_check=lambda: False, sleep=lambda s: None,
            needs_activation=False)
        c.click(7, 8)
        # Keine Aktivierung, KEIN Fokus-Check -> trotz "falschem" Fokus klickt er.
        self.assertNotIn('A', inp.log)
        self.assertEqual(fg_calls['n'], 0)
        self.assertEqual(inp.log, [
            ('mouseUp', 'left'), ('mouseUp', 'right'),
            ('moveTo', 7, 8), ('click', 'left'),
            ('mouseUp', 'left'), ('mouseUp', 'right')])


class TestFocusGate(unittest.TestCase):
    def test_retries_until_focus_then_acts(self):
        inp = FakeInput()
        # erst falscher Fokus (99), dann korrekt (42) -> 2. Versuch klappt.
        c = _make(inp, foreground_seq=[99, 42])
        c.click(0, 0)
        activates = [e for e in inp.log if e[0] == 'activate']
        self.assertEqual(len(activates), 2)               # ein Retry
        self.assertIn(('click', 'left'), inp.log)         # Aktion lief

    def test_focus_never_acquired_raises_but_releases_and_neutralizes(self):
        inp = FakeInput()
        rel = []
        c = _make(inp, foreground_seq=[99, 99, 99], released=rel)
        with self.assertRaises(cc.FocusNotAcquired):
            c.click(0, 0)
        # Trotz Fehler: Lease freigegeben + Tasten geloest (finally).
        self.assertEqual(rel, [0])
        self.assertEqual(inp.log[-2:], [('mouseUp', 'left'), ('mouseUp', 'right')])
        # KEIN echter Klick gelandet (Fokus nie da):
        self.assertNotIn(('click', 'left'), inp.log)


class TestStopAbort(unittest.TestCase):
    def test_stop_aborts_loop_and_cleans_up(self):
        inp = FakeInput()
        rel = []
        # Fokus ok; stop_check liefert True beim ersten Aktions-Schritt.
        c = _make(inp, foreground_seq=[42], stop_seq=[True], released=rel)
        with self.assertRaises(cc.BurstAborted):
            c.click(5, 5)
        # moveTo/click NICHT ausgefuehrt (Stop vor 1. Schritt):
        self.assertNotIn(('moveTo', 1005, 2005), inp.log)
        # aber Tasten geloest + Lease frei (finally):
        self.assertEqual(rel, [0])
        self.assertEqual(inp.log[-2:], [('mouseUp', 'left'), ('mouseUp', 'right')])

    def test_key_with_hold(self):
        inp = FakeInput()
        c = _make(inp, foreground_seq=[42])
        c.key('e', hold_s=0.1)
        self.assertIn(('keyDown', 'e'), inp.log)
        self.assertIn(('keyUp', 'e'), inp.log)
        self.assertLess(inp.log.index(('keyDown', 'e')),
                        inp.log.index(('keyUp', 'e')))


class TestLeasedInputBackend(unittest.TestCase):
    """LeasedInput erfuellt das Bot-Backend-Protokoll via Lease-Bursts."""

    def _backend(self, inp, acquired, released):
        cur = cc.CursorClient(
            idx=0, hwnd=42, to_screen=lambda x, y: (x, y),
            acquire=lambda i, h: acquired.append((i, h)),
            release=lambda i: released.append(i),
            inp=inp, foreground_fn=lambda: 42,
            activate_fn=lambda h: inp.log.append('A'),
            stop_check=lambda: False, sleep=lambda s: None,
            settle_s=0.0, needs_activation=True)
        return cc.LeasedInput(cur)

    def test_click_is_one_lease_burst_screen_coords(self):
        inp = FakeInput()
        acq, rel = [], []
        be = self._backend(inp, acq, rel)
        be.click(300, 400, button='right')
        self.assertEqual(acq, [(0, False)])           # genau ein Lease
        self.assertEqual(rel, [0])
        self.assertIn(('moveTo', 300, 400), inp.log)  # identity to_screen
        self.assertIn(('click', 'right'), inp.log)
        self.assertIn('A', inp.log)                   # click-to-activate (multi)

    def test_key_is_one_lease_burst(self):
        inp = FakeInput()
        acq, rel = [], []
        be = self._backend(inp, acq, rel)
        be.key('e')
        self.assertEqual(acq, [(0, False)])           # keyDown+keyUp in EINEM Lease
        self.assertEqual(rel, [0])
        self.assertIn(('keyDown', 'e'), inp.log)
        self.assertIn(('keyUp', 'e'), inp.log)

    def test_set_pause_propagates_to_cursor(self):
        inp = FakeInput()
        be = self._backend(inp, [], [])
        be.set_pause(0.1)
        self.assertEqual(be._c.mouse_pause, 0.1)


class TestLeasedScreenCursor(unittest.TestCase):
    """LeasedScreenCursor: refill-Vertrag (moveTo/mouseDown/mouseUp/click) ->
    ein gehaltener Drag wird zu GENAU EINEM holds_button-Lease-Burst gebuendelt."""

    def _dev(self, inp, acquired, released):
        cur = cc.CursorClient(
            idx=0, hwnd=42, to_screen=lambda x, y: (x, y),
            acquire=lambda i, h: acquired.append((i, h)),
            release=lambda i: released.append(i),
            inp=inp, foreground_fn=lambda: 42,
            activate_fn=lambda h: None,
            stop_check=lambda: False, sleep=lambda s: None,
            settle_s=0.0, needs_activation=False)
        return cc.LeasedScreenCursor(cur)

    def test_drag_sequence_is_one_held_burst(self):
        inp = FakeInput()
        acq, rel = [], []
        dev = self._dev(inp, acq, rel)
        # refill.drag-Sequenz: moveTo(start) -> mouseDown -> moveTo(mid/end) -> mouseUp
        dev.moveTo(100, 100)
        dev.mouseDown()
        dev.moveTo(150, 150)
        dev.moveTo(200, 200)
        dev.mouseUp()
        # GENAU EIN Lease, als gehaltener (non-revocable) Drag.
        self.assertEqual(acq, [(0, True)])
        self.assertEqual(rel, [0])
        moves = [e for e in inp.log if e[0] == 'moveTo']
        self.assertEqual(moves, [('moveTo', 100, 100), ('moveTo', 150, 150),
                                 ('moveTo', 200, 200)])
        # Genau EIN mouseDown (der Drag selbst); mouseUp links kommt zusaetzlich
        # aus der Button-Neutralisierung (Eingang + finally, Finding #1) -> nur die
        # Anwesenheit pruefen, nicht die Anzahl.
        self.assertEqual([e for e in inp.log if e[0] == 'mouseDown'],
                         [('mouseDown', 'left')])
        self.assertIn(('mouseUp', 'left'), inp.log)

    def test_click_is_one_normal_burst(self):
        inp = FakeInput()
        acq, rel = [], []
        dev = self._dev(inp, acq, rel)
        dev.click(x=300, y=400, button='left')
        self.assertEqual(acq, [(0, False)])           # KEIN holds_button
        self.assertIn(('moveTo', 300, 400), inp.log)
        self.assertIn(('click', 'left'), inp.log)

    def test_mouseup_without_drag_is_ignored(self):
        inp = FakeInput()
        acq, rel = [], []
        dev = self._dev(inp, acq, rel)
        dev.mouseUp()                                  # kein vorheriger mouseDown
        self.assertEqual(acq, [])                      # kein Lease, kein Crash

    def test_set_pause_propagates(self):
        inp = FakeInput()
        dev = self._dev(inp, [], [])
        dev.set_pause(0.05)
        self.assertEqual(dev._c.mouse_pause, 0.05)


class TestCursorClientChord(unittest.TestCase):
    """CursorClient.chord: eine keyDown/keyUp-Sequenz (z.B. Ctrl+E) = EIN
    gehaltener (non-revocable) Burst, Reihenfolge erhalten."""

    def test_chord_is_one_held_burst_in_order(self):
        inp = FakeInput()
        acq, rel = [], []
        c = _make(inp, foreground_seq=[42], acquired=acq, released=rel)
        c.chord([('down', 'ctrl'), ('down', 'e'), ('up', 'e'), ('up', 'ctrl')])
        self.assertEqual(acq, [(0, True)])     # genau ein Lease, holds_button
        self.assertEqual(rel, [0])
        keys = [e for e in inp.log if e[0] in ('keyDown', 'keyUp')]
        self.assertEqual(keys, [('keyDown', 'ctrl'), ('keyDown', 'e'),
                                ('keyUp', 'e'), ('keyUp', 'ctrl')])


class TestLeasedPydirectinput(unittest.TestCase):
    """LeasedPydirectinput: pydirectinput-API-Shim -> Drag + Tasten-Akkord je
    EIN Lease-Burst; PAUSE als Attribut; press = ein key-Burst."""

    def _dev(self, inp, acquired, released):
        cur = cc.CursorClient(
            idx=0, hwnd=42, to_screen=lambda x, y: (x, y),
            acquire=lambda i, h: acquired.append((i, h)),
            release=lambda i: released.append(i),
            inp=inp, foreground_fn=lambda: 42, activate_fn=lambda h: None,
            stop_check=lambda: False, sleep=lambda s: None,
            settle_s=0.0, needs_activation=False)
        return cc.LeasedPydirectinput(cur)

    def test_chord_bundled_into_one_held_burst(self):
        inp = FakeInput()
        acq, rel = [], []
        dev = self._dev(inp, acq, rel)
        # Ctrl+E (Vogelperspektive), wie es puzzle/seher erzeugen.
        dev.keyDown('ctrl')
        dev.keyDown('e')
        dev.keyUp('e')
        dev.keyUp('ctrl')
        self.assertEqual(acq, [(0, True)])     # GENAU ein Lease, gehalten
        self.assertEqual(rel, [0])
        keys = [e for e in inp.log if e[0] in ('keyDown', 'keyUp')]
        self.assertEqual(keys, [('keyDown', 'ctrl'), ('keyDown', 'e'),
                                ('keyUp', 'e'), ('keyUp', 'ctrl')])

    def test_press_is_one_key_burst(self):
        inp = FakeInput()
        acq, rel = [], []
        dev = self._dev(inp, acq, rel)
        dev.press('esc')
        self.assertEqual(acq, [(0, False)])    # Einzel-Tap, kein holds_button
        self.assertEqual([e for e in inp.log if e[0] in ('keyDown', 'keyUp')],
                         [('keyDown', 'esc'), ('keyUp', 'esc')])

    def test_pause_attribute_round_trips_to_cursor(self):
        inp = FakeInput()
        dev = self._dev(inp, [], [])
        dev.PAUSE = 0.1
        self.assertEqual(dev._c.mouse_pause, 0.1)
        self.assertEqual(dev.PAUSE, 0.1)
        dev.PAUSE = None                       # defensiv -> 0.0
        self.assertEqual(dev._c.mouse_pause, 0.0)

    def test_inherits_drag_bundling(self):
        inp = FakeInput()
        acq, rel = [], []
        dev = self._dev(inp, acq, rel)
        dev.moveTo(10, 10)
        dev.mouseDown(button='right')
        dev.moveTo(20, 30)
        dev.mouseUp(button='right')
        self.assertEqual(acq, [(0, True)])     # ein gehaltener Drag-Burst
        self.assertEqual([e for e in inp.log if e[0] == 'mouseDown'],
                         [('mouseDown', 'right')])

    def test_keyup_without_keydown_is_defensive_tap(self):
        inp = FakeInput()
        acq, rel = [], []
        dev = self._dev(inp, acq, rel)
        dev.keyUp('e')                          # kein vorheriges keyDown
        self.assertEqual(acq, [(0, False)])     # als Einzel-Tap ausgefuehrt
        self.assertEqual([e for e in inp.log if e[0] in ('keyDown', 'keyUp')],
                         [('keyDown', 'e'), ('keyUp', 'e')])


if __name__ == '__main__':
    unittest.main()
