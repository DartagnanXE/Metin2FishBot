# -*- coding: utf-8 -*-
"""Tests fuer das Puzzle-Box-Nachlegen (opt-in).

Deckt die Entscheidungs-/Orchestrierungs-Schicht ab, die puzzle.py auf das
getestete ``interface.refill`` aufsetzt:
  * ``refill.box_refill_due`` -- reine Trigger-Entscheidung (Streak + Cap).
  * ``PuzzleBot._box_refill_active`` -- Schalter/Engine/Capture-Gate.
  * ``PuzzleBot._maybe_refill_standard_box`` -- Streak-Schwelle -> Standard-Box.
  * ``PuzzleBot._maybe_refill_deluxe_box`` -- Deluxe-Whitelist (nie vertauscht).
  * ``PuzzleBot._refill_box`` -- Inventar-offen-Gate, Cap, dragged/empty/error.

Headless: bare ``__new__``-Instanz + Mocks (kein Fenster/Input), genau wie
test_puzzle_glue.
"""

import unittest
from unittest import mock

import puzzle
from interface import refill


class _FakeSig:
    stopped = False

    def wait(self, seconds):
        return True


def _bare(**attrs):
    b = puzzle.PuzzleBot.__new__(puzzle.PuzzleBot)
    b.state = 4
    b.botting = True
    b.wincap = type('W', (), {'offset_x': 0, 'offset_y': 0,
                              'get_screenshot': lambda self=None: None})()
    b.box_refill_enabled = True
    b.box_refill_db = None
    b.box_refill_calib = None
    b.inventory_hotkey = 'i'
    b.stop_signal = _FakeSig()
    b._empty_getpiece_streak = 0
    b._box_refill_count = 0
    b.solver_mode = 'trained'
    for k, v in attrs.items():
        setattr(b, k, v)
    return b


class BoxRefillDueTest(unittest.TestCase):
    def test_due_at_threshold(self):
        self.assertTrue(refill.box_refill_due(3, min_streak=3, done=0, max_done=20))

    def test_not_due_below_threshold(self):
        self.assertFalse(refill.box_refill_due(2, min_streak=3, done=0, max_done=20))

    def test_not_due_at_cap(self):
        self.assertFalse(refill.box_refill_due(9, min_streak=3, done=20, max_done=20))

    def test_junk_inputs_never_due(self):
        self.assertFalse(refill.box_refill_due(None, min_streak=3, done=0, max_done=20))


class BoxRefillActiveTest(unittest.TestCase):
    def test_inactive_when_disabled(self):
        b = _bare(box_refill_enabled=False)
        self.assertFalse(b._box_refill_active())

    def test_inactive_without_wincap(self):
        b = _bare(wincap=None)
        self.assertFalse(b._box_refill_active())

    def test_active_when_enabled(self):
        b = _bare()
        # Nur True, wenn die Engine importiert werden konnte (in der Testumgebung
        # mit numpy/PIL der Fall).
        self.assertEqual(b._box_refill_active(), refill is not None)


class StandardTriggerTest(unittest.TestCase):
    def test_no_refill_below_streak(self):
        # Streak unter der Schwelle (BOX_EMPTY_STREAK) -> kein Nachlegen.
        b = _bare(_empty_getpiece_streak=puzzle.BOX_EMPTY_STREAK - 1)
        with mock.patch.object(puzzle.PuzzleBot, '_refill_box',
                               return_value=True) as rb:
            self.assertFalse(b._maybe_refill_standard_box())
        rb.assert_not_called()

    def test_refill_at_streak_uses_standard_names_and_slot(self):
        b = _bare(_empty_getpiece_streak=puzzle.BOX_EMPTY_STREAK)
        with mock.patch.object(puzzle.PuzzleBot, 'standard_box_screen_point',
                               return_value=(503, 328)), \
             mock.patch.object(puzzle.PuzzleBot, '_refill_box',
                               return_value=True) as rb:
            self.assertTrue(b._maybe_refill_standard_box())
        rb.assert_called_once_with(refill.BOX_STD_NAMES, (503, 328), 'standard')

    def test_disabled_short_circuits(self):
        b = _bare(box_refill_enabled=False, _empty_getpiece_streak=9)
        with mock.patch.object(puzzle.PuzzleBot, '_refill_box') as rb:
            self.assertFalse(b._maybe_refill_standard_box())
        rb.assert_not_called()


class DeluxeTriggerTest(unittest.TestCase):
    def test_deluxe_uses_deluxe_names_and_slot(self):
        b = _bare()
        with mock.patch.object(puzzle.PuzzleBot, 'deluxe_box_screen_point',
                               return_value=(503, 271)), \
             mock.patch.object(puzzle.PuzzleBot, '_refill_box',
                               return_value=True) as rb:
            self.assertTrue(b._maybe_refill_deluxe_box())
        rb.assert_called_once_with(refill.BOX_DELUXE_NAMES, (503, 271), 'deluxe',
                                   stop_on_empty=False)

    def test_deluxe_respects_cap(self):
        b = _bare(_box_refill_count=puzzle.BOX_REFILL_MAX)
        with mock.patch.object(puzzle.PuzzleBot, '_refill_box') as rb:
            self.assertFalse(b._maybe_refill_deluxe_box())
        rb.assert_not_called()


class RefillBoxOrchestrationTest(unittest.TestCase):
    def test_dragged_increments_count_and_returns_true(self):
        b = _bare()
        with mock.patch.object(puzzle.PuzzleBot,
                               '_ensure_inventory_open_for_refill',
                               return_value=True), \
             mock.patch.object(refill, 'box_refill_from_inventory',
                               return_value='dragged') as rfi:
            ok = b._refill_box(refill.BOX_STD_NAMES, (503, 328), 'standard')
        self.assertTrue(ok)
        self.assertEqual(b._box_refill_count, 1)
        rfi.assert_called_once()
        # Whitelist + Ziel korrekt durchgereicht.
        args, kwargs = rfi.call_args
        self.assertEqual(args[0], refill.BOX_STD_NAMES)
        self.assertEqual(args[1], (503, 328))

    def test_empty_stops_bot(self):
        b = _bare()
        with mock.patch.object(puzzle.PuzzleBot,
                               '_ensure_inventory_open_for_refill',
                               return_value=True), \
             mock.patch.object(refill, 'box_refill_from_inventory',
                               return_value='empty'):
            ok = b._refill_box(refill.BOX_STD_NAMES, (503, 328), 'standard')
        self.assertFalse(ok)
        self.assertFalse(b.botting)
        self.assertEqual(b._box_refill_count, 0)

    def test_empty_with_stop_on_empty_false_keeps_botting(self):
        # Deluxe-Variante: keine Box im Inventar -> Bot laeuft WEITER (nur Deluxe
        # wird vom Aufrufer abgeschaltet), botting bleibt True.
        b = _bare()
        with mock.patch.object(puzzle.PuzzleBot,
                               '_ensure_inventory_open_for_refill',
                               return_value=True), \
             mock.patch.object(refill, 'box_refill_from_inventory',
                               return_value='empty'):
            ok = b._refill_box(refill.BOX_DELUXE_NAMES, (503, 271), 'deluxe',
                               stop_on_empty=False)
        self.assertFalse(ok)
        self.assertTrue(b.botting)   # NICHT gestoppt

    def test_error_continues_without_stop(self):
        b = _bare()
        with mock.patch.object(puzzle.PuzzleBot,
                               '_ensure_inventory_open_for_refill',
                               return_value=True), \
             mock.patch.object(refill, 'box_refill_from_inventory',
                               return_value='error'):
            ok = b._refill_box(refill.BOX_STD_NAMES, (503, 328), 'standard')
        self.assertFalse(ok)
        self.assertTrue(b.botting)   # Fehler stoppt den Bot NICHT

    def test_inventory_not_open_skips_scan(self):
        b = _bare()
        with mock.patch.object(puzzle.PuzzleBot,
                               '_ensure_inventory_open_for_refill',
                               return_value=False), \
             mock.patch.object(refill, 'box_refill_from_inventory') as rfi:
            ok = b._refill_box(refill.BOX_STD_NAMES, (503, 328), 'standard')
        self.assertFalse(ok)
        rfi.assert_not_called()      # kein Blind-Drag ohne offenes Inventar

    def test_cap_blocks_scan(self):
        b = _bare(_box_refill_count=puzzle.BOX_REFILL_MAX)
        with mock.patch.object(puzzle.PuzzleBot,
                               '_ensure_inventory_open_for_refill',
                               return_value=True) as ens, \
             mock.patch.object(refill, 'box_refill_from_inventory') as rfi:
            ok = b._refill_box(refill.BOX_STD_NAMES, (503, 328), 'standard')
        self.assertFalse(ok)
        ens.assert_not_called()
        rfi.assert_not_called()

    def test_inactive_when_disabled(self):
        b = _bare(box_refill_enabled=False)
        with mock.patch.object(refill, 'box_refill_from_inventory') as rfi:
            ok = b._refill_box(refill.BOX_STD_NAMES, (503, 328), 'standard')
        self.assertFalse(ok)
        rfi.assert_not_called()


class EnsureInventoryOpenTest(unittest.TestCase):
    """Der Fokus-Fix: das Inventar-Oeffnen MUSS vor dem Hotkey das Spiel
    fokussieren (sonst geht 'i' ins Leere -> Inventar oeffnet nie), und nur eine
    VERIFIZIERT geschlossene Tasche (res is False) darf das Nachlegen blocken."""

    def _run_with_probe(self, probe_return):
        b = _bare()
        focus = mock.Mock()
        # ensure_inventory_open ruft press_fn EINMAL (simuliert Toggle) und gibt
        # probe_return zurueck -> so pruefen wir, dass der Druck fokussiert wird.
        def fake_ensure(capture_fn, press_fn, calib):
            press_fn()
            return probe_return
        with mock.patch.object(puzzle.PuzzleBot, '_focus_game', focus), \
             mock.patch.object(puzzle, '_open_probe') as op, \
             mock.patch.object(puzzle.pydirectinput, 'press', mock.Mock()) as press:
            op.ensure_inventory_open.side_effect = fake_ensure
            result = b._ensure_inventory_open_for_refill()
        return result, focus, press

    def test_focuses_game_before_pressing_hotkey(self):
        result, focus, press = self._run_with_probe(True)
        self.assertTrue(result)
        focus.assert_called()          # Spiel wurde fokussiert ...
        press.assert_called()          # ... und der Hotkey gedrueckt

    def test_none_probe_proceeds(self):
        # Probe nicht eindeutig (None) -> weiter (lenient wie Energiesplitter).
        result, _focus, _press = self._run_with_probe(None)
        self.assertTrue(result)

    def test_verified_closed_blocks(self):
        # Nur eine verifiziert GESCHLOSSENE Tasche (False) blockt das Nachlegen.
        result, _focus, _press = self._run_with_probe(False)
        self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()
