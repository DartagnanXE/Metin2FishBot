# -*- coding: utf-8 -*-
"""Tests fuer den v1.3-Event-Flow im Puzzle-Bot (Spiel SELBST starten/neu oeffnen).

Deckt ab:
  * ``_open_puzzle_game`` -- Strg+E -> Eventuebersicht -> FISCHPUZZLESPIEL-Label
    per NCC finden -> auf den NAMEN klicken (nicht "Ansehen") -> Brett-offen
    verifizieren. Erkennung VOR Aktion: ohne Label/Header KEIN Blind-Klick.
  * Restart-Refill in State 4: leere Standard-Boxen -> ESC + Spiel neu oeffnen
    (state=0); bleibt es nach dem Reopen-Cap leer -> harter Stop "Boxen leer".
  * Selbststart in ``runHack``: Brett zu (calib not ok) -> Spiel oeffnen statt
    hartem Stop; erst nach GAME_OPEN_MAX_TRIES Fehlversuchen Stop.

Headless: die NCC-Pipeline (seher.flow) und calibration werden gemockt, kein
Fenster/keine echten Tasten (conftest stubbt pydirectinput/win32).
"""

import types
import unittest
from unittest import mock

import puzzle


def _bare(**attrs):
    b = puzzle.PuzzleBot.__new__(puzzle.PuzzleBot)
    b.state = 0
    b.botting = True
    b.board_size = puzzle.PuzzleBot.PUZZLE_WINDOW_SIZE
    b.puzzle_offset = puzzle.PuzzleBot.PUZZLE_WINDOW_POSITION
    b.wincap = type('W', (), {
        'offset_x': 100, 'offset_y': 50, 'hwnd': 1234,
        'get_screenshot': staticmethod(lambda: 'SHOT')})()
    # get_image wird in den Flow-Tests nicht inhaltlich gebraucht (calibration
    # ist gemockt) -> Dummy-Frame, damit der reale Crop nicht auf 'SHOT' laeuft.
    b.get_image = lambda: 'CROP'
    b._empty_getpiece_streak = 0
    b._box_reopen_tries = 0
    b._game_open_tries = 0
    b._awaiting_deluxe = False
    b._deluxe_miss_streak = 0
    b._deluxe_disabled = False
    for k, v in attrs.items():
        setattr(b, k, v)
    return b


def _calib(ok):
    return types.SimpleNamespace(ok=ok, reasons=[], details={})


class OpenPuzzleGameTest(unittest.TestCase):
    """_open_puzzle_game: erst Uebersicht, dann NAMENSFELD klicken, verifizieren."""

    def test_board_already_open_is_noop_true(self):
        b = _bare()
        with mock.patch.object(puzzle.calibration, 'validate_puzzle_region',
                               return_value=_calib(True)), \
             mock.patch.object(puzzle, 'pydirectinput') as pdi:
            self.assertTrue(b._open_puzzle_game())
            pdi.click.assert_not_called()   # schon offen -> kein Strg+E/Klick

    def test_force_ignores_board_open_shortcut(self):
        # DER FIX: board_open meldet True (verbrauchtes/leeres Brett nach ESC),
        # aber force=True -> NICHT kurzschliessen, sondern den Eventlisten-
        # Neustart erzwingen (sonst der v1.3.0-Bug: Reopen lief nie). Es MUSS
        # also Strg+E versucht/geklickt werden, obwohl board_open True ist.
        b = _bare()
        st = {'clicked': False}

        def find(frame, name, thresh=0.0):
            if name == 'flow_event_title':
                # Uebersicht offen bis zum Klick auf den Button, danach ZU
                # (Spiel gestartet) -> erst dann gilt der Reopen als Erfolg.
                return (not st['clicked'], (497, 83),
                        0.2 if st['clicked'] else 0.99)
            if name == 'flow_fisch_label':
                return (True, (300, 108), 0.97)
            return (False, (0, 0), 0.0)

        flow = types.SimpleNamespace(
            find=find, center=lambda name, pos: (pos[0] + 75, pos[1] + 11),
            diagnose=lambda img: {})
        with mock.patch.object(puzzle, '_flow', flow), \
             mock.patch.object(puzzle.calibration, 'validate_puzzle_region',
                               return_value=_calib(True)), \
             mock.patch.object(puzzle, 'pydirectinput') as pdi, \
             mock.patch.object(puzzle, 'sleep', lambda *_a: None):
            pdi.click.side_effect = lambda *a, **k: st.update(clicked=True)
            ok = b._open_puzzle_game(force=True)
        self.assertTrue(ok)
        pdi.click.assert_called_once()   # trotz board_open=True NICHT kurzgeschl.

    def test_non_force_board_open_still_shortcuts(self):
        # Gegenprobe: OHNE force bleibt der Kurzschluss (Selbststart-Semantik).
        b = _bare()
        with mock.patch.object(puzzle.calibration, 'validate_puzzle_region',
                               return_value=_calib(True)), \
             mock.patch.object(puzzle, 'pydirectinput') as pdi:
            self.assertTrue(b._open_puzzle_game(force=False))
            pdi.click.assert_not_called()

    def test_title_and_label_found_clicks_name_center(self):
        # Uebersicht offen (title NCC ok) + Label gefunden bei (300,108) -> Klick
        # aufs Template-ZENTRUM (+wincap-Rand); nach dem Klick ist die Uebersicht
        # ZU und das Brett offen -> Erfolg.
        b = _bare()
        st = {'clicked': False}
        calib_seq = [_calib(False),  # _board_open() im Vorlauf: noch zu
                     _calib(True)]   # nach Klick: offen

        def find(frame, name, thresh=0.0):
            if name == 'flow_event_title':
                return (not st['clicked'], (497, 83),
                        0.2 if st['clicked'] else 0.99)
            if name == 'flow_fisch_label':
                return (True, (300, 108), 0.97)
            return (False, (0, 0), 0.0)

        flow = types.SimpleNamespace(
            find=find,
            center=lambda name, pos: (pos[0] + 75, pos[1] + 11),  # 150x22 -> +75,+11
            diagnose=lambda img: {})
        with mock.patch.object(puzzle, '_flow', flow), \
             mock.patch.object(puzzle.calibration, 'validate_puzzle_region',
                               side_effect=calib_seq), \
             mock.patch.object(puzzle, 'pydirectinput') as pdi, \
             mock.patch.object(puzzle, 'sleep', lambda *_a: None):
            pdi.click.side_effect = lambda *a, **k: st.update(clicked=True)
            ok = b._open_puzzle_game()
        self.assertTrue(ok)
        pdi.click.assert_called_once()
        _args, kwargs = pdi.click.call_args
        # Klick = Label-Zentrum (300+75, 108+11) + wincap (100,50) = (475,169).
        self.assertEqual(kwargs.get('x'), 300 + 75 + 100)
        self.assertEqual(kwargs.get('y'), 108 + 11 + 50)
        # NICHT in der "Ansehen"-Spalte (die liegt deutlich weiter rechts).
        self.assertLess(kwargs.get('x'), 600)

    def test_overview_stays_open_is_miss_not_false_ok(self):
        # REGRESSION (Live-Bug 2026-06-20): der Klick passierte, aber die
        # Uebersicht blieb offen (Fehlklick auf "Name" statt den Button) ->
        # das strukturelle board_open meldete faelschlich "offen" => falsches
        # REOPEN_OK. Erfolg MUSS jetzt board_open UND Uebersicht-ZU verlangen
        # -> hier bleibt die Uebersicht offen => Miss (False), kein REOPEN_OK.
        b = _bare()
        clock = {'t': 1000.0}

        def faketime():
            clock['t'] += 0.5
            return clock['t']

        def find(frame, name, thresh=0.0):
            if name == 'flow_event_title':
                return (True, (497, 83), 0.99)   # Uebersicht bleibt OFFEN
            if name == 'flow_fisch_label':
                return (True, (300, 108), 0.97)
            return (False, (0, 0), 0.0)

        flow = types.SimpleNamespace(
            find=find, center=lambda name, pos: (pos[0] + 75, pos[1] + 11),
            diagnose=lambda img: {})
        with mock.patch.object(puzzle, '_flow', flow), \
             mock.patch.object(puzzle.calibration, 'validate_puzzle_region',
                               return_value=_calib(True)), \
             mock.patch.object(puzzle, 'pydirectinput') as pdi, \
             mock.patch.object(puzzle, 'time', faketime), \
             mock.patch.object(puzzle, 'sleep', lambda *_a: None):
            ok = b._open_puzzle_game(force=True)
        self.assertFalse(ok)             # Uebersicht offen -> KEIN Erfolg
        pdi.click.assert_called_once()   # geklickt wurde trotzdem

    def test_label_missing_no_blind_click(self):
        # Uebersicht offen, aber Label NICHT gefunden -> KEIN Klick, False.
        b = _bare()

        def find(frame, name, thresh=0.0):
            if name == 'flow_event_title':
                return (True, (497, 83), 0.99)
            return (False, (0, 0), 0.40)   # Label unter Schwelle

        flow = types.SimpleNamespace(find=find, center=lambda n, p: (0, 0),
                                     diagnose=lambda img: {})
        with mock.patch.object(puzzle, '_flow', flow), \
             mock.patch.object(puzzle.calibration, 'validate_puzzle_region',
                               return_value=_calib(False)), \
             mock.patch.object(puzzle, 'pydirectinput') as pdi, \
             mock.patch.object(puzzle, 'sleep', lambda *_a: None):
            ok = b._open_puzzle_game()
        self.assertFalse(ok)
        pdi.click.assert_not_called()

    def test_overview_never_opens_returns_false(self):
        # Strg+E bringt die Uebersicht nie -> nach Retries False, KEIN Label-Klick.
        b = _bare()
        flow = types.SimpleNamespace(
            find=lambda frame, name, thresh=0.0: (False, (0, 0), 0.1),
            center=lambda n, p: (0, 0), diagnose=lambda img: {})
        with mock.patch.object(puzzle, '_flow', flow), \
             mock.patch.object(puzzle.calibration, 'validate_puzzle_region',
                               return_value=_calib(False)), \
             mock.patch.object(puzzle, 'pydirectinput') as pdi, \
             mock.patch.object(puzzle, 'sleep', lambda *_a: None):
            ok = b._open_puzzle_game()
        self.assertFalse(ok)
        pdi.click.assert_not_called()      # nie blind aufs Label geklickt
        self.assertTrue(pdi.keyDown.called)  # aber Strg+E wurde versucht

    def test_label_guard_no_overview_no_click(self):
        # _find_fisch_label: Label matcht, aber Header NICHT -> kein Klick
        # (Fenstertitel-Fehlmatch-Schutz, Seher-Doppel-Guard).
        b = _bare()

        def find(frame, name, thresh=0.0):
            if name == 'flow_fisch_label':
                return (True, (300, 108), 0.95)
            return (False, (0, 0), 0.2)   # title NICHT da

        flow = types.SimpleNamespace(find=find,
                                     center=lambda n, p: (375, 119))
        with mock.patch.object(puzzle, '_flow', flow):
            ok, pt, dbg = b._find_fisch_label('SHOT')
        self.assertFalse(ok)
        self.assertTrue(dbg.get('no_overview'))


class RestartRefillState4Test(unittest.TestCase):
    """State-4-Leer-Streak: ESC + Reopen statt Inventar-Nachlegen; Cap -> Stop."""

    def _bot_for_state4(self, **attrs):
        b = _bare(state=4, new_piece=None, _color_read_announced=True,
                  _color_retry_until=0.0, step_delay=0.0, **attrs)
        # State-4 erreicht den Leer-Zweig nur, wenn der Timer abgelaufen ist.
        b.timer_action = 0.0
        return b

    def test_empty_streak_reopens_and_resets(self):
        # Streak erreicht die Schwelle -> ESC + _open_puzzle_game (Erfolg) ->
        # state=0, Streak=0, reopen_tries++.
        b = self._bot_for_state4(
            _empty_getpiece_streak=puzzle.BOX_EMPTY_STREAK - 1)
        with mock.patch.object(puzzle.calibration, 'validate_puzzle_region',
                               return_value=_calib(True)), \
             mock.patch.object(puzzle.PuzzleBot, 'get_new_piece_color',
                               return_value=None), \
             mock.patch.object(puzzle.PuzzleBot, '_press_esc') as esc, \
             mock.patch.object(puzzle.PuzzleBot, '_open_puzzle_game',
                               return_value=True) as opn, \
             mock.patch.object(puzzle, 'sleep', lambda *_a: None):
            b.runHack()
        esc.assert_called_once()
        opn.assert_called_once()
        # Reopen MUSS erzwungen sein (force=True) -> nach dem ESC darf das
        # strukturelle board_open den Neustart nicht kurzschliessen.
        self.assertEqual(opn.call_args.kwargs.get('force'), True)
        self.assertEqual(b.state, 0)
        self.assertEqual(b._empty_getpiece_streak, 0)
        self.assertEqual(b._box_reopen_tries, 1)
        self.assertTrue(b.botting)

    def test_empty_again_after_reopen_cap_stops(self):
        # Reopen-Cap bereits erreicht -> erneuter Leer-Streak -> harter Stop.
        b = self._bot_for_state4(
            _empty_getpiece_streak=puzzle.BOX_EMPTY_STREAK - 1,
            _box_reopen_tries=puzzle.BOX_REOPEN_MAX)
        with mock.patch.object(puzzle.calibration, 'validate_puzzle_region',
                               return_value=_calib(True)), \
             mock.patch.object(puzzle.PuzzleBot, 'get_new_piece_color',
                               return_value=None), \
             mock.patch.object(puzzle.PuzzleBot, '_press_esc') as esc, \
             mock.patch.object(puzzle.PuzzleBot, '_open_puzzle_game') as opn, \
             mock.patch.object(puzzle, 'sleep', lambda *_a: None):
            b.runHack()
        self.assertFalse(b.botting)        # Stop "Boxen leer"
        esc.assert_not_called()            # kein weiterer ESC/Reopen-Loop
        opn.assert_not_called()

    def test_reopen_failure_stops(self):
        # Streak erreicht Schwelle, _open_puzzle_game schlaegt fehl -> Stop.
        b = self._bot_for_state4(
            _empty_getpiece_streak=puzzle.BOX_EMPTY_STREAK - 1)
        with mock.patch.object(puzzle.calibration, 'validate_puzzle_region',
                               return_value=_calib(True)), \
             mock.patch.object(puzzle.PuzzleBot, 'get_new_piece_color',
                               return_value=None), \
             mock.patch.object(puzzle.PuzzleBot, '_press_esc'), \
             mock.patch.object(puzzle.PuzzleBot, '_open_puzzle_game',
                               return_value=False), \
             mock.patch.object(puzzle, 'sleep', lambda *_a: None):
            b.runHack()
        self.assertFalse(b.botting)

    def test_successful_piece_resets_reopen_tries(self):
        # REGRESSION (Bug 2026-06-20): nach 1 produktivem Neustart stoppte der Bot
        # beim naechsten Leerlauf, weil _box_reopen_tries ueber die Session
        # akkumulierte (1 >= BOX_REOPEN_MAX). Ein erfolgreicher Stein-Read MUSS den
        # Zaehler nullen -> produktive Neustarts sind unbegrenzt.
        b = self._bot_for_state4(_box_reopen_tries=1, _empty_getpiece_streak=1)
        # State-4 laeuft (timer_action=0 -> Gate offen), aber der State-5-Body
        # (Board-Read auf dem Dummy-Frame) wird im SELBEN Tick uebersprungen:
        # State 4 setzt timer_action=jetzt -> State-5-Gate (dt > timep) ist mit
        # timep=1.0 zu. Wir pruefen nur den Reset, der in State 4 passiert.
        b.step_delay = 1.0
        with mock.patch.object(puzzle.calibration, 'validate_puzzle_region',
                               return_value=_calib(True)), \
             mock.patch.object(puzzle.PuzzleBot, 'get_new_piece_color',
                               return_value=1), \
             mock.patch.object(puzzle.PuzzleBot, '_register_deluxe_result',
                               return_value=False), \
             mock.patch.object(puzzle, 'sleep', lambda *_a: None):
            b.runHack()
        self.assertEqual(b._box_reopen_tries, 0)   # Reset -> naechster Neustart erlaubt
        self.assertEqual(b._empty_getpiece_streak, 0)
        self.assertEqual(b.state, 5)


class SelbststartTest(unittest.TestCase):
    """runHack: Brett zu -> Spiel oeffnen (nicht hart stoppen)."""

    def test_board_closed_opens_game_not_stop(self):
        b = _bare(state=0, step_delay=0.0)
        b.timer_action = 0.0
        with mock.patch.object(puzzle.calibration, 'validate_puzzle_region',
                               return_value=_calib(False)), \
             mock.patch.object(puzzle.PuzzleBot, 'get_image',
                               return_value='CROP'), \
             mock.patch.object(puzzle.PuzzleBot, '_open_puzzle_game',
                               return_value=True) as opn, \
             mock.patch.object(puzzle, 'sleep', lambda *_a: None):
            b.runHack()
        opn.assert_called_once()
        self.assertTrue(b.botting)          # NICHT gestoppt
        self.assertEqual(b._game_open_tries, 0)  # Erfolg -> Zaehler genullt

    def test_board_closed_open_fails_increments_tries(self):
        b = _bare(state=0, step_delay=0.0)
        b.timer_action = 0.0
        with mock.patch.object(puzzle.calibration, 'validate_puzzle_region',
                               return_value=_calib(False)), \
             mock.patch.object(puzzle.PuzzleBot, 'get_image',
                               return_value='CROP'), \
             mock.patch.object(puzzle.PuzzleBot, '_open_puzzle_game',
                               return_value=False), \
             mock.patch.object(puzzle, 'sleep', lambda *_a: None):
            b.runHack()
        self.assertTrue(b.botting)          # noch nicht am Cap -> kein Stop
        self.assertEqual(b._game_open_tries, 1)

    def test_open_cap_reached_stops(self):
        b = _bare(state=0, step_delay=0.0,
                  _game_open_tries=puzzle.GAME_OPEN_MAX_TRIES)
        b.timer_action = 0.0
        with mock.patch.object(puzzle.calibration, 'validate_puzzle_region',
                               return_value=_calib(False)), \
             mock.patch.object(puzzle.PuzzleBot, 'get_image',
                               return_value='CROP'), \
             mock.patch.object(puzzle.PuzzleBot, '_open_puzzle_game') as opn:
            b.runHack()
        self.assertFalse(b.botting)         # Cap erreicht -> sauberer Stop
        opn.assert_not_called()


if __name__ == '__main__':
    unittest.main()
