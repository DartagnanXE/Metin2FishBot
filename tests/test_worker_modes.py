# -*- coding: utf-8 -*-
"""Build-Schritt 6/6b: headless Modus-Schleifen (worker_modes) fuer ALLE Modi.

Voll gemockt -- kein echtes Spiel, keine CTk-App, keine realen Bots. Prueft:
Dispatch (fischen/puzzle/energiesplitter/seher), den gemeinsamen Tick-Treiber
(laeuft bis botting/ipc-Stop, beendet das StopSignal) und die Bot-Verdrahtung
(Backends + Instanz-Attribute) je Modus.
"""

import sys
import types
import unittest
from unittest import mock

import worker_modes


class FakeIpc:
    def __init__(self, stop_after=None):
        self._calls = 0
        self._stop_after = stop_after   # None = nie; int = ab N-tem stop_requested
        self.acquired = []
        self.released = []

    def stop_requested(self):
        self._calls += 1
        if self._stop_after is not None and self._calls >= self._stop_after:
            return True
        return False

    def acquire(self, idx, holds_button):
        self.acquired.append((idx, holds_button))

    def release(self, idx):
        self.released.append(idx)


class _Args:
    client = 0
    hwnd = 4242


class FakeBot:
    def __init__(self, stop_sig, ticks=3):
        self.stop_signal = stop_sig
        self.botting = True
        self._ticks = ticks
        self.ran = 0

    def runHack(self):
        self.ran += 1
        if self.ran >= self._ticks:
            self.botting = False


class TestRunFishingLoop(unittest.TestCase):
    def test_ticks_until_botting_false_and_stops_signal(self):
        ipc = FakeIpc()
        captured = {}

        def build(cfg, cursor, *, stop_sig):
            captured['cfg'] = cfg
            captured['cursor'] = cursor
            captured['sig'] = stop_sig
            return FakeBot(stop_sig, ticks=3)

        bot = worker_modes.run_fishing(
            cursor='CUR', ipc=ipc, args=_Args(), sleep=lambda s: None,
            build_bot=build, config_load=lambda: {'fishing': {}})

        self.assertEqual(bot.ran, 3)              # tickt bis botting False
        self.assertFalse(bot.botting)
        self.assertEqual(captured['cursor'], 'CUR')
        self.assertTrue(captured['sig'].stopped)  # StopSignal im finally beendet

    def test_ipc_stop_breaks_loop(self):
        ipc = FakeIpc(stop_after=2)

        def build(cfg, cursor, *, stop_sig):
            return FakeBot(stop_sig, ticks=99)

        bot = worker_modes.run_fishing(
            cursor=None, ipc=ipc, args=_Args(), sleep=lambda s: None,
            build_bot=build, config_load=lambda: {})
        self.assertLessEqual(bot.ran, 1)
        self.assertTrue(bot.stop_signal.stopped)


class TestRunPuzzleLoop(unittest.TestCase):
    def test_ticks_until_botting_false(self):
        ipc = FakeIpc()

        def build(cfg, cursor, *, stop_sig):
            return FakeBot(stop_sig, ticks=2)

        bot = worker_modes.run_puzzle(
            cursor='CUR', ipc=ipc, args=_Args(), sleep=lambda s: None,
            build_bot=build, config_load=lambda: {'puzzle': {}})
        self.assertEqual(bot.ran, 2)
        self.assertTrue(bot.stop_signal.stopped)


class TestRunEnergiesplitterLoop(unittest.TestCase):
    def test_ticks_and_passes_sub_mode_to_builder(self):
        ipc = FakeIpc()
        seen = {}

        def build(cfg, cursor, sub_mode, *, stop_sig):
            seen['sub'] = sub_mode
            return FakeBot(stop_sig, ticks=1)

        bot = worker_modes.run_energiesplitter(
            'dagger', cursor='CUR', ipc=ipc, args=_Args(), sleep=lambda s: None,
            build_bot=build, config_load=lambda: {})
        self.assertEqual(bot.ran, 1)
        self.assertEqual(seen['sub'], 'dagger')
        self.assertTrue(bot.stop_signal.stopped)


class TestRunModeDispatch(unittest.TestCase):
    def _patch_cursor(self):
        return mock.patch.object(worker_modes.cursor_client,
                                 'make_leased_cursor', return_value='LEASED')

    def test_fischen_dispatch(self):
        with self._patch_cursor() as mk, \
             mock.patch.object(worker_modes, 'run_fishing',
                               return_value='BOT') as rf:
            out = worker_modes.run_mode('fischen', FakeIpc(), _Args())
        self.assertEqual(out, 'BOT')
        mk.assert_called_once()
        self.assertEqual(rf.call_args[0][0], 'LEASED')

    def test_puzzle_dispatch(self):
        with self._patch_cursor(), \
             mock.patch.object(worker_modes, 'run_puzzle',
                               return_value='P') as rp:
            out = worker_modes.run_mode('puzzle', FakeIpc(), _Args())
        self.assertEqual(out, 'P')
        self.assertEqual(rp.call_args[0][0], 'LEASED')

    def test_energiesplitter_dispatch(self):
        with self._patch_cursor(), \
             mock.patch.object(worker_modes, 'run_energiesplitter',
                               return_value='E') as re_:
            out = worker_modes.run_mode('energiesplitter', FakeIpc(), _Args())
        self.assertEqual(out, 'E')
        # sub_mode None (aus cfg abgeleitet), Cursor an zweiter Stelle.
        self.assertIsNone(re_.call_args[0][0])
        self.assertEqual(re_.call_args[0][1], 'LEASED')

    def test_seher_dispatch(self):
        with self._patch_cursor(), \
             mock.patch.object(worker_modes, 'run_seher',
                               return_value='S') as rs:
            out = worker_modes.run_mode('seher', FakeIpc(), _Args())
        self.assertEqual(out, 'S')
        self.assertEqual(rs.call_args[0][0], 'LEASED')

    def test_truly_unknown_mode_raises(self):
        with self._patch_cursor():
            with self.assertRaises(NotImplementedError):
                worker_modes.run_mode('does_not_exist', FakeIpc(), _Args())


class TestEsValuesAndSubMode(unittest.TestCase):
    def test_sub_mode_explicit_wins(self):
        self.assertEqual(worker_modes._es_sub_mode({}, 'dagger'), 'dagger')
        self.assertEqual(worker_modes._es_sub_mode({}, 'hammer'), 'hammer')

    def test_sub_mode_from_persisted_cfg(self):
        self.assertEqual(
            worker_modes._es_sub_mode({'mode': 'energiesplitter_dagger'}, None),
            'dagger')
        self.assertEqual(
            worker_modes._es_sub_mode({'mode': 'fishing'}, None), 'hammer')

    def test_es_values_maps_keys(self):
        cfg = {
            'energiesplitter': {
                'hammer': {'stack_count': 3, 'energie_freischalten': True},
                'dagger': {'daggers_per_round': 7, 'buy_mode': 'shop',
                           'buy_delay_s': 0.5, 'process_first': True,
                           'process_pickup_s': 0.2, 'process_confirm_s': 0.6},
                'shared': {'speed_profile': 'fast', 'mouse_pause': 0.04,
                           'keyboard_pause': 0.12, 'max_actions': 500,
                           'consecutive_unverified_stop': 4, 'jitter_pct': 0.1,
                           'dry_run': False},
            }
        }
        with mock.patch.object(worker_modes._cfgio, 'to_values',
                               return_value={}):
            v = worker_modes._es_values(cfg, 'dagger')
        self.assertEqual(v['-ES_MODE-'], 'dagger')
        self.assertEqual(v['-ES_STACK_COUNT-'], 3)
        self.assertTrue(v['-ES_FREISCHALTEN-'])
        self.assertEqual(v['-ES_DAGGERS_PER_ROUND-'], 7)
        self.assertEqual(v['-ES_BUY_MODE-'], 'shop')
        self.assertEqual(v['-ES_BUY_DELAY_S-'], 0.5)
        self.assertTrue(v['-ES_PROCESS_FIRST-'])
        self.assertEqual(v['-ES_PROC_PICKUP_S-'], 0.2)
        self.assertEqual(v['-ES_PROC_CONFIRM_S-'], 0.6)
        self.assertEqual(v['-ES_SPEED-'], 'fast')
        self.assertFalse(v['-ES_DRY_RUN-'])


class _FakeModeModule(types.ModuleType):
    """Gemeinsame Basis fuer gefakte Bot-Module (record set_input_backend)."""
    def __init__(self, name, bot_cls):
        super().__init__(name)
        self.recorded = []
        self.set_input_backend = lambda b: self.recorded.append(b)
        self.BotCls = bot_cls


class _FakeTickBot:
    def __init__(self):
        self.botting = False
        self.set_to_begin_values = None

    def set_to_begin(self, values):
        self.set_to_begin_values = values


class TestBuildPuzzleBotWiring(unittest.TestCase):
    def setUp(self):
        self._saved = sys.modules.get('puzzle')
        fake = _FakeModeModule('puzzle', _FakeTickBot)
        fake.PuzzleBot = _FakeTickBot
        sys.modules['puzzle'] = fake
        self.fake = fake

    def tearDown(self):
        if self._saved is None:
            sys.modules.pop('puzzle', None)
        else:
            sys.modules['puzzle'] = self._saved

    def test_wires_backend_attrs_and_starts(self):
        cfg = {'puzzle': {'color_mode': 'multi', 'solver_mode': 'trained',
                          'step_delay': 0.2, 'force_deluxe': True}}
        with mock.patch.object(worker_modes._cfgio, 'to_values',
                               return_value={'-V-': 1}):
            sig = worker_modes._stopsig.StopSignal()
            bot = worker_modes._build_puzzle_bot(cfg, object(), stop_sig=sig)
        self.assertEqual(len(self.fake.recorded), 1)   # set_input_backend gesetzt
        self.assertEqual(bot.color_mode, 'multi')
        self.assertEqual(bot.solver_mode, 'trained')
        self.assertEqual(bot.step_delay, 0.2)
        self.assertTrue(bot.force_deluxe)
        self.assertIs(bot.stop_signal, sig)
        self.assertEqual(bot.set_to_begin_values, {'-V-': 1})
        self.assertTrue(bot.botting)


class TestBuildEnergiesplitterBotWiring(unittest.TestCase):
    def setUp(self):
        self._saved = sys.modules.get('energiesplitter.bot')
        fake = _FakeModeModule('energiesplitter.bot', _FakeTickBot)
        fake.EnergiesplitterBot = _FakeTickBot
        sys.modules['energiesplitter.bot'] = fake
        self.fake = fake

    def tearDown(self):
        if self._saved is None:
            sys.modules.pop('energiesplitter.bot', None)
        else:
            sys.modules['energiesplitter.bot'] = self._saved

    def test_wires_backend_mode_and_starts(self):
        cfg = {'mode': 'energiesplitter_dagger', 'inventory': {'hotkey': 'k'},
               'energiesplitter': {'hammer': {}, 'dagger': {}, 'shared': {}}}
        with mock.patch.object(worker_modes._cfgio, 'to_values',
                               return_value={}):
            sig = worker_modes._stopsig.StopSignal()
            bot = worker_modes._build_energiesplitter_bot(
                cfg, object(), None, stop_sig=sig)
        self.assertEqual(len(self.fake.recorded), 1)   # set_input_backend gesetzt
        self.assertEqual(bot.mode, 'dagger')           # aus cfg['mode'] abgeleitet
        self.assertEqual(bot.inventory_hotkey, 'k')
        self.assertIs(bot.stop_signal, sig)
        self.assertEqual(bot.set_to_begin_values['-ES_MODE-'], 'dagger')
        self.assertTrue(bot.botting)


class TestRunSeher(unittest.TestCase):
    def setUp(self):
        self._saved = sys.modules.get('interface.seher_runner')
        fake = types.ModuleType('interface.seher_runner')
        self.calls = {}
        fake.set_input_backend = lambda b: self.calls.setdefault('backend', b)

        def _session(cfg, *, abort_fn, order, max_games, after_action):
            self.calls['session'] = dict(
                cfg=cfg, abort_fn=abort_fn, order=order,
                max_games=max_games, after_action=after_action)
            return 'SESSION_RESULT'

        fake.run_seher_session = _session
        sys.modules['interface.seher_runner'] = fake

    def tearDown(self):
        if self._saved is None:
            sys.modules.pop('interface.seher_runner', None)
        else:
            sys.modules['interface.seher_runner'] = self._saved

    def test_sets_backend_and_runs_session_with_abort(self):
        ipc = FakeIpc()
        out = worker_modes.run_seher(
            cursor=object(), ipc=ipc, args=_Args(),
            config_load=lambda: {'k': 1})
        self.assertEqual(out, 'SESSION_RESULT')
        self.assertIn('backend', self.calls)            # set_input_backend gesetzt
        self.assertEqual(self.calls['session']['cfg'], {'k': 1})
        # abort_fn == ipc.stop_requested (Bound-Method: gleicher self+func ->
        # ==, aber NICHT 'is', da jeder Zugriff ein neues Bound-Objekt erzeugt).
        self.assertEqual(self.calls['session']['abort_fn'], ipc.stop_requested)


if __name__ == '__main__':
    unittest.main()
