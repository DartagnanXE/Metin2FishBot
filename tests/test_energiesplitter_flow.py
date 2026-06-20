"""Headless-Tests fuer den EnergiesplitterBot-Kern (Eigentuemer D), Umbau 2026-06-16.

Spiegelt das Stub-Muster aus ``tests/test_puzzle_hardening.py``: die Windows-
only Treiber (``pydirectinput``/``win32*``) UND die Schwester-Module von Agent A
(``detect``/``geometry``) werden VOR dem Bot-Import gestubbt, damit die reine
State-Machine-/Gate-/Safety-Logik gegen den ECHTEN Bot-Code laeuft.

YANG spielt KEINE Rolle mehr (kein Preis, kein Kontostand, kein gold_guard).

Schwerpunkt (CONTRACT §2/§7):
  * Phase-0-GATE blockt ohne Assets -> KEINE Maus-/Tasten-Aktion (mock-assert);
    armed = assets_ready + 800x600 + grid_present (OHNE Yang).
  * Aktion 1: ``stack_count`` mal 200er-Stack kaufen -> Auto-Stop.
  * Aktion 2: Dolche sequenziell verarbeiten (Drag pro Dolch).
  * Safety-Stops feuern: max_actions, consecutive_unverified.
  * Modus-Auswahl (hammer/dagger) verzweigt korrekt.
  * Kein rightClick/click/drag/keyDown solange dry_run or not armed.
  * Erkennung-vor-Aktion intakt (drag_unsafe, Slot-Klassifikation).
"""

import os
import sys
import types
import unittest
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
  sys.path.insert(0, _REPO_ROOT)


# -- Eingabe-/Capture-Stubs (zaehlen die Aufrufe) ---------------------------
_INPUT_CALLS = {'click': 0, 'right': 0, 'keyDown': 0, 'keyUp': 0,
                'mouseDown': 0, 'mouseUp': 0, 'moveTo': 0}


def _reset_input():
  for k in _INPUT_CALLS:
    _INPUT_CALLS[k] = 0


def _install_stubs():
  pdi = types.ModuleType('pydirectinput')
  pdi.PAUSE = 0

  def _click(*a, **k):
    if k.get('button') == 'right':
      _INPUT_CALLS['right'] += 1
    else:
      _INPUT_CALLS['click'] += 1

  pdi.click = _click
  pdi.moveTo = lambda *a, **k: _INPUT_CALLS.__setitem__('moveTo', _INPUT_CALLS['moveTo'] + 1)
  pdi.press = lambda *a, **k: None
  pdi.keyDown = lambda *a, **k: _INPUT_CALLS.__setitem__('keyDown', _INPUT_CALLS['keyDown'] + 1)
  pdi.keyUp = lambda *a, **k: _INPUT_CALLS.__setitem__('keyUp', _INPUT_CALLS['keyUp'] + 1)
  pdi.mouseDown = lambda *a, **k: _INPUT_CALLS.__setitem__('mouseDown', _INPUT_CALLS['mouseDown'] + 1)
  pdi.mouseUp = lambda *a, **k: _INPUT_CALLS.__setitem__('mouseUp', _INPUT_CALLS['mouseUp'] + 1)
  sys.modules['pydirectinput'] = pdi
  for name in ('win32gui', 'win32ui', 'win32con', 'win32api'):
    sys.modules.setdefault(name, types.ModuleType(name))


_install_stubs()

import energiesplitter.bot as esbot_mod          # noqa: E402
from energiesplitter.bot import (                 # noqa: E402
    EnergiesplitterBot, MODE_HAMMER, MODE_DAGGER)


# -- Fakes fuer Fenster + Agent-A-Detektoren --------------------------------
class _FakeWincap:
  offset_x = 0
  offset_y = 0

  def __init__(self, *a, **k):
    self._shot = object()  # opaker Marker; Detektoren sind gestubbt

  def get_screenshot(self):
    return self._shot


def _values(**over):
  base = {
      '-ES_STACK_COUNT-': 1, '-ES_FREISCHALTEN-': False,
      '-ES_DAGGERS_PER_ROUND-': 1,
      '-ES_MOUSE_PAUSE-': 0.05, '-ES_KB_PAUSE-': 0.10,
      '-ES_SPEED-': 'fast', '-ES_JITTER-': 0.15,
      '-ES_BIRDSEYE-': True,
      '-ES_MAX_ACTIONS-': 0, '-ES_UNVERIF_STOP-': 3, '-ES_DRY_RUN-': True,
  }
  base.update(over)
  return base


def _make_bot(mode=MODE_HAMMER, values=None, with_window=True):
  bot = EnergiesplitterBot()
  bot.mode = mode
  cap = _FakeWincap if with_window else None
  with mock.patch.object(esbot_mod, '_WindowCapture', cap):
    bot.set_to_begin(values if values is not None else _values())
  return bot


def _arm(bot):
  """Schaltet den Bot kuenstlich scharf (Phase-0 erfuellt + dry_run aus),
  um die scharfen Pfade zu testen. In Produktion macht das phase0_gate()."""
  bot.armed = True
  bot.dry_run = False


def _fake_modules(grid=True):
  """Fakes fuer detect/geometry, mit denen das GATE gruen werden kann."""
  fake_detect = types.SimpleNamespace(
      assets_ready=lambda mode: (True, []),
      grid_present=lambda: grid)
  fake_geo = types.SimpleNamespace(is_calibrated=lambda w: True)
  return fake_detect, fake_geo


class TestSetToBeginFreeze(unittest.TestCase):
  def test_resets_state_and_counters(self):
    bot = _make_bot()
    self.assertEqual(bot.state, EnergiesplitterBot.ST_INIT)
    for attr in ('gekauft', 'hammer_remaining', 'splitter_summe',
                 'actions_done', 'consecutive_unverified'):
      self.assertEqual(getattr(bot, attr), 0)

  def test_max_actions_zero_means_unlimited(self):
    # 0 = UNBEGRENZT: KEINE Auto-Ableitung mehr (frueher max(50, 3*stack_count)
    # -> schnitt den open-ended Dolch-Lauf nach ~50 Aktionen ab). Der Lauf endet
    # natuerlich bei Hammer-Erschoepfung; max_actions bleibt 0.
    bot = _make_bot(values=_values(**{'-ES_STACK_COUNT-': 100,
                                      '-ES_MAX_ACTIONS-': 0}))
    self.assertEqual(bot.max_actions, 0)

  def test_explicit_cap_kept(self):
    bot = _make_bot(values=_values(**{'-ES_MAX_ACTIONS-': 7}))
    self.assertEqual(bot.max_actions, 7)

  def test_zero_cap_never_hits(self):
    # Backstop darf bei 0 (unbegrenzt) NIE feuern -- auch bei vielen Aktionen.
    bot = _make_bot(values=_values(**{'-ES_MAX_ACTIONS-': 0}))
    _arm(bot)
    bot.actions_done = 100000
    bot.botting = True
    self.assertFalse(bot._action_cap_hit())
    self.assertTrue(bot.botting)

  def test_freezes_new_keys(self):
    bot = _make_bot(values=_values(**{'-ES_STACK_COUNT-': 3,
                                      '-ES_DAGGERS_PER_ROUND-': 4}))
    self.assertEqual(bot.stack_count, 3)
    self.assertEqual(bot.daggers_per_round, 4)

  def test_idempotent(self):
    bot = _make_bot()
    bot.gekauft = 50
    bot.state = EnergiesplitterBot.ST_BUY_LOOP
    with mock.patch.object(esbot_mod, '_WindowCapture', _FakeWincap):
      bot.set_to_begin(_values())
    self.assertEqual(bot.gekauft, 0)
    self.assertEqual(bot.state, EnergiesplitterBot.ST_INIT)


class TestPhase0Gate(unittest.TestCase):
  def test_missing_modules_block(self):
    bot = _make_bot()
    armed, missing = bot.phase0_gate()
    self.assertFalse(armed)
    self.assertTrue(missing)

  def test_all_present_arms(self):
    bot = _make_bot()
    fake_detect, fake_geo = _fake_modules()
    with mock.patch.object(esbot_mod, '_detect', fake_detect), \
         mock.patch.object(esbot_mod, '_geometry', fake_geo):
      armed, missing = bot.phase0_gate()
    self.assertTrue(armed, missing)
    self.assertEqual(missing, [])

  def test_assets_missing_listed(self):
    bot = _make_bot()
    fake_detect = types.SimpleNamespace(
        assets_ready=lambda mode: (False, ['item:hammer', 'npc:alchemist']),
        grid_present=lambda: True)
    fake_geo = types.SimpleNamespace(is_calibrated=lambda w: True)
    with mock.patch.object(esbot_mod, '_detect', fake_detect), \
         mock.patch.object(esbot_mod, '_geometry', fake_geo):
      armed, missing = bot.phase0_gate()
    self.assertFalse(armed)
    self.assertIn('item:hammer', missing)

  def test_uncalibrated_blocks(self):
    bot = _make_bot()
    fake_detect = types.SimpleNamespace(assets_ready=lambda mode: (True, []),
                                        grid_present=lambda: True)
    fake_geo = types.SimpleNamespace(is_calibrated=lambda w: False)
    with mock.patch.object(esbot_mod, '_detect', fake_detect), \
         mock.patch.object(esbot_mod, '_geometry', fake_geo):
      armed, missing = bot.phase0_gate()
    self.assertFalse(armed)
    self.assertIn('calibration:800x600', missing)

  def test_grid_missing_blocks(self):
    # Fenster + Assets OK, aber Inventar-Raster nicht aufloesbar -> rot.
    bot = _make_bot()
    fake_detect, fake_geo = _fake_modules(grid=False)
    with mock.patch.object(esbot_mod, '_detect', fake_detect), \
         mock.patch.object(esbot_mod, '_geometry', fake_geo):
      armed, missing = bot.phase0_gate()
    self.assertFalse(armed)
    self.assertIn('grid_calibration', missing)

  def test_grid_check_never_raises(self):
    bot = _make_bot()
    def _boom():
      raise RuntimeError('grid kaputt')
    fake_detect = types.SimpleNamespace(assets_ready=lambda mode: (True, []),
                                        grid_present=_boom)
    fake_geo = types.SimpleNamespace(is_calibrated=lambda w: True)
    with mock.patch.object(esbot_mod, '_detect', fake_detect), \
         mock.patch.object(esbot_mod, '_geometry', fake_geo):
      armed, missing = bot.phase0_gate()
    self.assertFalse(armed)
    self.assertIn('grid_calibration', missing)

  def test_gate_has_no_yang_path(self):
    # Es gibt KEINE Yang-/gold_reader-Vorbedingung mehr -> mit den drei realen
    # Saeulen (assets+800x600+grid) wird das Gate gruen, ohne irgendein Yang-Stub.
    bot = _make_bot()
    fake_detect, fake_geo = _fake_modules()
    with mock.patch.object(esbot_mod, '_detect', fake_detect), \
         mock.patch.object(esbot_mod, '_geometry', fake_geo):
      armed, missing = bot.phase0_gate()
    self.assertTrue(armed, missing)


class TestGateBlocksAllInput(unittest.TestCase):
  """KEIN rightClick/click/drag/keyDown solange dry_run or not armed."""

  def test_dry_run_tick_no_input(self):
    _reset_input()
    bot = _make_bot()
    bot.botting = True
    self.assertTrue(bot.dry_run or not bot.armed)
    bot.runHack()
    self.assertFalse(bot.botting)  # Selbst-Stop
    self.assertEqual(bot.state, EnergiesplitterBot.ST_STOP)
    self.assertEqual(sum(_INPUT_CALLS.values()), 0, _INPUT_CALLS)

  def test_dagger_dry_run_no_input(self):
    _reset_input()
    bot = _make_bot(mode=MODE_DAGGER)
    bot.botting = True
    bot.runHack()
    self.assertFalse(bot.botting)
    self.assertEqual(sum(_INPUT_CALLS.values()), 0, _INPUT_CALLS)

  def test_armed_but_dry_run_still_blocks(self):
    _reset_input()
    bot = _make_bot()
    bot.armed = True       # Assets da ...
    bot.dry_run = True     # ... aber noch nicht entsichert
    bot.botting = True
    bot.runHack()
    self.assertFalse(bot.botting)
    self.assertEqual(sum(_INPUT_CALLS.values()), 0, _INPUT_CALLS)

  def test_guarded_helpers_no_op_when_blocked(self):
    _reset_input()
    bot = _make_bot()
    # dry_run=True -> jede Eingabe muss No-Op sein.
    self.assertFalse(bot._right_click(10, 10))
    self.assertFalse(bot._left_click(10, 10))
    self.assertFalse(bot._press_key('g'))
    self.assertFalse(bot._drag(1, 1, 2, 2))
    self.assertFalse(bot._two_click_move(1, 1, 2, 2))   # Zwei-Klick auch gate-geschuetzt
    self.assertEqual(sum(_INPUT_CALLS.values()), 0, _INPUT_CALLS)


class TestNoWindowStop(unittest.TestCase):
  def test_no_window_stops_without_input(self):
    _reset_input()
    bot = _make_bot(with_window=False)
    bot.armed = True
    bot.dry_run = False
    bot.botting = True
    bot.runHack()
    self.assertFalse(bot.botting)
    self.assertEqual(bot._stop_reason, 'no_window')
    self.assertEqual(sum(_INPUT_CALLS.values()), 0)


class TestAbort(unittest.TestCase):
  def test_abort_fn_reads_signal(self):
    bot = _make_bot()
    self.assertFalse(bot.abort_fn())
    bot.stop_signal = types.SimpleNamespace(stopped=True)
    self.assertTrue(bot.abort_fn())

  def test_abort_stops_before_input(self):
    _reset_input()
    bot = _make_bot()
    _arm(bot)
    bot.stop_signal = types.SimpleNamespace(stopped=True)
    bot.botting = True
    bot.runHack()
    self.assertFalse(bot.botting)
    self.assertEqual(sum(_INPUT_CALLS.values()), 0)


class TestActionCap(unittest.TestCase):
  def test_max_actions_stops(self):
    bot = _make_bot()
    _arm(bot)
    bot.max_actions = 2
    bot.actions_done = 2
    bot.botting = True
    self.assertTrue(bot._action_cap_hit())
    self.assertFalse(bot.botting)
    self.assertEqual(bot._stop_reason, 'max_actions')

  def test_below_cap_continues(self):
    bot = _make_bot()
    _arm(bot)
    bot.max_actions = 5
    bot.actions_done = 2
    bot.botting = True
    self.assertFalse(bot._action_cap_hit())
    self.assertTrue(bot.botting)


class TestConsecutiveUnverified(unittest.TestCase):
  def test_stops_after_n(self):
    bot = _make_bot()
    _arm(bot)
    bot.consecutive_unverified_stop = 3
    bot.consecutive_unverified = 0
    bot.botting = True
    self.assertFalse(bot._note_unverified())  # 1
    self.assertFalse(bot._note_unverified())  # 2
    self.assertTrue(bot._note_unverified())   # 3 -> Stop
    self.assertFalse(bot.botting)
    self.assertEqual(bot._stop_reason, 'consecutive_unverified')


class TestModeBranch(unittest.TestCase):
  """runHack verzweigt nach self.mode (armed -> echter Tick-Pfad)."""

  def test_hammer_branch_called(self):
    bot = _make_bot(mode=MODE_HAMMER)
    _arm(bot)
    bot.botting = True
    with mock.patch.object(bot, '_tick_hammer') as h, \
         mock.patch.object(bot, '_tick_dagger') as d:
      bot.runHack()
    self.assertTrue(h.called)
    self.assertFalse(d.called)

  def test_dagger_branch_called(self):
    bot = _make_bot(mode=MODE_DAGGER)
    _arm(bot)
    bot.botting = True
    with mock.patch.object(bot, '_tick_hammer') as h, \
         mock.patch.object(bot, '_tick_dagger') as d:
      bot.runHack()
    self.assertTrue(d.called)
    self.assertFalse(h.called)


class TestHammerStateFlow(unittest.TestCase):
  """Erste Hammer-Schritte: INIT -> INVENTORY_BASE -> Stop bei fehlendem
  Item-Template bzw. keinem Platz -- jeweils OHNE Maus-Aktion."""

  def test_init_transitions_to_inventory(self):
    bot = _make_bot(mode=MODE_HAMMER, values=_values(**{'-ES_STACK_COUNT-': 3}))
    _arm(bot)
    bot.botting = True
    bot.runHack()  # INIT -> INVENTORY_BASE
    self.assertEqual(bot.state, EnergiesplitterBot.ST_INVENTORY_BASE)
    self.assertEqual(bot.hammer_remaining, bot.stack_count)

  def test_item_template_missing_stops(self):
    _reset_input()
    bot = _make_bot(mode=MODE_HAMMER)
    _arm(bot)
    bot.state = EnergiesplitterBot.ST_INVENTORY_BASE
    bot.botting = True
    bot._ensure_inventory_open = lambda: True   # Offen-Check separat getestet
    bot._item_template_ready = lambda item: False
    bot.runHack()
    self.assertFalse(bot.botting)
    self.assertEqual(bot._stop_reason, 'item_template_missing')
    self.assertEqual(sum(_INPUT_CALLS.values()), 0)

  def test_no_space_stops(self):
    _reset_input()
    bot = _make_bot(mode=MODE_HAMMER)
    _arm(bot)
    bot.state = EnergiesplitterBot.ST_INVENTORY_BASE
    bot.botting = True
    bot._ensure_inventory_open = lambda: True   # Offen-Check separat getestet
    bot._item_template_ready = lambda item: True
    bot._free_slot_count = lambda: 0
    bot.runHack()
    self.assertFalse(bot.botting)
    self.assertEqual(bot._stop_reason, 'no_space')
    self.assertEqual(sum(_INPUT_CALLS.values()), 0)


class TestHammerBuyXStacks(unittest.TestCase):
  """Aktion 1: stack_count mal einen 200er-Stack kaufen -> Auto-Stop."""

  def _buy_bot(self, stack_count=3):
    bot = _make_bot(mode=MODE_HAMMER,
                    values=_values(**{'-ES_STACK_COUNT-': stack_count}))
    _arm(bot)
    bot.state = EnergiesplitterBot.ST_BUY_LOOP
    bot._hammer_slot = (100, 90)
    bot.botting = True
    bot._free_slot_count = lambda: 10
    bot._locate_shop_item = lambda item: (100, 90)
    bot._bag_count_measurable = lambda: False  # Re-Read traegt nicht -> True
    return bot

  def test_three_stacks_three_buys_then_stop(self):
    _reset_input()
    bot = self._buy_bot(stack_count=3)
    # Jeder Buy-Step kauft genau 1 Stack (Re-Read verifiziert via not-messbar).
    for _ in range(20):
      if not bot.botting:
        break
      bot.runHack()
    self.assertFalse(bot.botting)
    self.assertEqual(bot._stop_reason, 'done')
    self.assertEqual(bot.gekauft, 3)
    self.assertEqual(_INPUT_CALLS['right'], 3)

  def test_check_done_stops_at_target(self):
    bot = self._buy_bot(stack_count=2)
    bot.gekauft = 2
    bot.state = EnergiesplitterBot.ST_CHECK_DONE
    bot.runHack()
    self.assertFalse(bot.botting)
    self.assertEqual(bot._stop_reason, 'done')

  def test_measurable_requires_growth(self):
    # Bag messbar -> Kauf nur verifiziert, wenn der Hammer-Bestand wuchs.
    _reset_input()
    bot = self._buy_bot(stack_count=1)
    bot.consecutive_unverified_stop = 1
    bot._bag_count_measurable = lambda: True
    bot._count_hammers = lambda: 0   # waechst NIE -> unverifiziert
    bot.runHack()
    self.assertEqual(bot.gekauft, 0)
    self.assertNotEqual(bot.state, EnergiesplitterBot.ST_CHECK_DONE)

  def test_relocate_used_each_buy(self):
    _reset_input()
    bot = self._buy_bot(stack_count=1)
    seen = {}
    bot._locate_shop_item = lambda item: (seen.__setitem__('item', item)
                                          or (200, 50))
    bot.runHack()
    self.assertEqual(seen['item'], 'hammer')
    self.assertEqual(bot._hammer_slot, (200, 50))
    self.assertEqual(_INPUT_CALLS['right'], 1)
    self.assertEqual(bot.gekauft, 1)

  def test_relocate_miss_falls_back_to_cached(self):
    _reset_input()
    bot = self._buy_bot(stack_count=1)
    bot._hammer_slot = (100, 90)
    bot._locate_shop_item = lambda item: None  # Re-Lokalisierung scheitert
    bot.runHack()
    self.assertEqual(_INPUT_CALLS['right'], 1)
    self.assertEqual(bot.gekauft, 1)

  def test_no_slot_at_all_stops_without_input(self):
    _reset_input()
    bot = self._buy_bot(stack_count=1)
    bot._hammer_slot = None
    bot._locate_shop_item = lambda item: None
    bot.runHack()
    self.assertFalse(bot.botting)
    self.assertEqual(bot._stop_reason, 'item_not_in_shop')
    self.assertEqual(_INPUT_CALLS['right'], 0)

  def test_max_actions_still_caps_buys(self):
    # max_actions greift weiter (OCR-unabhaengiger Backstop).
    _reset_input()
    bot = self._buy_bot(stack_count=100)
    bot.max_actions = 2
    bot.actions_done = 2
    bot.runHack()
    self.assertFalse(bot.botting)
    self.assertEqual(bot._stop_reason, 'max_actions')
    self.assertEqual(_INPUT_CALLS['right'], 0)


class TestArmedPurchaseDoesInput(unittest.TestCase):
  """Gegenprobe: bei echtem GATE-gruen + verifiziertem Kauf wird der
  Rechtsklick tatsaechlich ausgeloest (Gate sperrt NICHT faelschlich)."""

  def test_verified_hammer_buy(self):
    _reset_input()
    bot = _make_bot(mode=MODE_HAMMER,
                    values=_values(**{'-ES_STACK_COUNT-': 1}))
    _arm(bot)
    bot.state = EnergiesplitterBot.ST_BUY_LOOP
    bot._hammer_slot = (100, 90)
    bot.botting = True
    bot._free_slot_count = lambda: 5
    bot._locate_shop_item = lambda item: (100, 90)
    bot._bag_count_measurable = lambda: False
    bot.runHack()
    self.assertEqual(_INPUT_CALLS['right'], 1)
    self.assertEqual(bot.gekauft, 1)
    self.assertEqual(bot.state, EnergiesplitterBot.ST_CHECK_DONE)


class TestScharfSwitch(unittest.TestCase):
  """Bewusster 'scharf'-Schalter = Umkehrung von dry_run (EINE Wahrheit)."""

  def test_default_not_scharf(self):
    bot = _make_bot()
    self.assertTrue(bot.dry_run)
    self.assertFalse(bot.scharf)

  def test_scharf_setter_clears_dry_run(self):
    bot = _make_bot()
    bot.scharf = True
    self.assertFalse(bot.dry_run)
    self.assertTrue(bot.scharf)

  def test_not_scharf_blocks_all_input(self):
    _reset_input()
    bot = _make_bot()
    bot.armed = True
    bot.scharf = False        # = dry_run True
    bot.botting = True
    bot.runHack()
    self.assertFalse(bot.botting)
    self.assertEqual(sum(_INPUT_CALLS.values()), 0, _INPUT_CALLS)


class TestDaggerSequential(unittest.TestCase):
  """Aktion 2: Dolche werden EINZELN NACHEINANDER verarbeitet (1 Drag je Dolch)."""

  def test_buy_one_queues_landing_slot(self):
    _reset_input()
    bot = _make_bot(mode=MODE_DAGGER,
                    values=_values(**{'-ES_DAGGERS_PER_ROUND-': 1}))
    _arm(bot)
    bot.state = EnergiesplitterBot.ST_BUY_ONE_DOLCH
    bot.botting = True
    bot.hammer_remaining = 5
    bot._round_to_buy = 1
    bot._dagger_queue = []
    bot._has_free_slot = lambda: True
    bot._locate_shop_item = lambda item: (300, 200)
    bot._inventory_signature = lambda: object()
    bot._diff_landing_slot = lambda a, b: (7, 7)
    bot.runHack()
    self.assertEqual(bot._dolche_gekauft, 1)
    # Nach dem (einzigen) Kauf der Runde -> Verarbeitung begonnen (erster Dolch).
    self.assertEqual(bot.state, EnergiesplitterBot.ST_PROCESS_DRAG)
    self.assertEqual(bot._dolch_inv_slot, (7, 7))
    self.assertEqual(_INPUT_CALLS['right'], 1)

  def test_two_per_round_buys_two_before_processing(self):
    _reset_input()
    bot = _make_bot(mode=MODE_DAGGER,
                    values=_values(**{'-ES_DAGGERS_PER_ROUND-': 2}))
    _arm(bot)
    bot.state = EnergiesplitterBot.ST_BUY_ONE_DOLCH
    bot.botting = True
    bot.hammer_remaining = 5
    bot._round_to_buy = 2
    bot._dagger_queue = []
    bot._has_free_slot = lambda: True
    slots = [(7, 7), (8, 8)]
    bot._locate_shop_item = lambda item: (300, 200)
    bot._inventory_signature = lambda: object()
    bot._diff_landing_slot = lambda a, b: slots.pop(0)
    bot.runHack()   # kauft Dolch 1 (round_to_buy 2->1), bleibt im BUY-State
    self.assertEqual(bot.state, EnergiesplitterBot.ST_BUY_ONE_DOLCH)
    self.assertEqual(bot._round_to_buy, 1)
    bot.runHack()   # kauft Dolch 2 (round_to_buy 1->0) -> Verarbeitung beginnt
    self.assertEqual(bot.state, EnergiesplitterBot.ST_PROCESS_DRAG)
    self.assertEqual(bot._dolche_gekauft, 2)
    self.assertEqual(len(bot._dagger_queue), 1)  # 1 verarbeitet, 1 wartet
    self.assertEqual(_INPUT_CALLS['right'], 2)

  def test_full_bag_processes_queued_daggers_instead_of_stopping(self):
    # Regression (User-Log 2026-06-20): Tasche voll bei 11/20 -> frueher
    # 'buy_unverified'-Stop. Jetzt: schon gekaufte Dolche werden verarbeitet
    # (Zerlegen schafft Platz), KEIN Stop, KEIN weiterer Kauf-Rechtsklick.
    _reset_input()
    bot = _make_bot(mode=MODE_DAGGER,
                    values=_values(**{'-ES_DAGGERS_PER_ROUND-': 20}))
    _arm(bot)
    bot.state = EnergiesplitterBot.ST_BUY_ONE_DOLCH
    bot.botting = True
    bot.hammer_remaining = 6
    bot._round_to_buy = 9                 # wollte noch 9 kaufen ...
    bot._dagger_queue = [(7, 7), (8, 8)]  # ... hat aber schon 2 gekauft
    bot._has_free_slot = lambda: False    # Tasche voll
    bot.runHack()
    self.assertTrue(bot.botting)          # NICHT gestoppt
    self.assertEqual(bot.state, EnergiesplitterBot.ST_PROCESS_DRAG)
    self.assertEqual(bot._round_to_buy, 0)
    self.assertEqual(_INPUT_CALLS['right'], 0)  # kein weiterer Kauf-Klick

  def test_full_bag_empty_queue_stops_no_space(self):
    # Tasche von Anfang an voll UND nichts gekauft -> ehrlicher no_space-Stop.
    _reset_input()
    bot = _make_bot(mode=MODE_DAGGER)
    _arm(bot)
    bot.state = EnergiesplitterBot.ST_BUY_ONE_DOLCH
    bot.botting = True
    bot.hammer_remaining = 6
    bot._round_to_buy = 5
    bot._dagger_queue = []
    bot._has_free_slot = lambda: False
    bot.runHack()
    self.assertFalse(bot.botting)
    self.assertEqual(bot._stop_reason, 'no_space')
    self.assertEqual(_INPUT_CALLS['right'], 0)

  def test_confirm_dismantle_clicks_ja(self):
    # Der Hammer->Dolch-Drag oeffnet 'Moechtest du das wirklich zerlegen?' ->
    # 'Ja' muss linksgeklickt werden (sonst bleibt der Dolch unverarbeitet).
    _reset_input()
    bot = _make_bot(mode=MODE_DAGGER)
    _arm(bot)
    fake = types.SimpleNamespace(
        dismantle_confirm_present=lambda bgr: (True, (361, 354)))
    with mock.patch.object(esbot_mod, '_detect', fake):
      handled = bot._confirm_dismantle_if_present()
    self.assertTrue(handled)
    self.assertEqual(_INPUT_CALLS['click'], 1)        # 'Ja' linksgeklickt

  def test_confirm_dismantle_noop_when_absent(self):
    _reset_input()
    bot = _make_bot(mode=MODE_DAGGER)
    _arm(bot)
    fake = types.SimpleNamespace(
        dismantle_confirm_present=lambda bgr: (False, None))
    with mock.patch.object(esbot_mod, '_detect', fake):
      self.assertFalse(bot._confirm_dismantle_if_present())
    self.assertEqual(_INPUT_CALLS['click'], 0)

  def test_process_drag_clicks_dismantle_ja_then_verifies(self):
    # Voller Pfad: ST_PROCESS_DRAG zieht den Hammer auf den Dolch, klickt 'Ja'
    # im Zerlege-Dialog und geht erst dann in die Verifikation.
    _reset_input()
    bot = _make_bot(mode=MODE_DAGGER)
    _arm(bot)
    bot.state = EnergiesplitterBot.ST_PROCESS_DRAG
    bot.botting = True
    bot._dolch_inv_slot = (5, 5)
    bot._classified_hammer_slot = lambda: (1, 1)
    bot._slot_is = lambda item, slot: True
    bot._count_hammers = lambda: 4
    bot._shot = lambda: object()
    confirmed = {'n': 0}
    def _confirm():
      confirmed['n'] += 1
      return True
    bot._confirm_dismantle_if_present = _confirm
    bot.runHack()
    self.assertEqual(confirmed['n'], 1)               # 'Ja' wurde versucht
    self.assertEqual(bot.state, EnergiesplitterBot.ST_VERIFY_PROCESS)

  def test_process_uses_two_click_not_drag(self):
    # Verarbeitung = ZWEI Linksklicks (Hammer aufnehmen + auf Dolch setzen),
    # KEIN Drag (kein mouseDown/mouseUp). Slot->Slot in der Tasche.
    _reset_input()
    bot = _make_bot(mode=MODE_DAGGER)
    _arm(bot)
    bot.state = EnergiesplitterBot.ST_PROCESS_DRAG
    bot.botting = True
    bot._dolch_inv_slot = (5, 5)
    bot._classified_hammer_slot = lambda: (1, 1)
    bot._slot_is = lambda item, slot: True
    bot._count_hammers = lambda: 4
    bot._shot = lambda: object()
    bot._confirm_dismantle_if_present = lambda: False   # kein Extra-Klick
    bot.runHack()
    self.assertEqual(_INPUT_CALLS['click'], 2)          # aufnehmen + setzen
    self.assertEqual(_INPUT_CALLS['mouseDown'], 0)      # KEIN Drag
    self.assertEqual(_INPUT_CALLS['mouseUp'], 0)
    self.assertEqual(bot.state, EnergiesplitterBot.ST_VERIFY_PROCESS)

  def test_batch_round_no_false_drift_stop(self):
    # Regression (User-Log 2026-06-20): bei daggers_per_round=20 stoppte der Bot
    # nach dem 1. Verarbeiten ('kauft 20, verarbeitet 1, stoppt'). Ursache war der
    # Anti-Drift-Riegel (gekauft - summe > 2): 20 - 1 = 19 > 2 -> Stop. Jetzt
    # entfernt -> die Runde laeuft weiter (naechster Dolch der Queue).
    bot = _make_bot(mode=MODE_DAGGER)
    _arm(bot)
    bot._dolche_gekauft = 20            # 20 in dieser Runde gekauft (Batch)
    bot.splitter_summe = 0
    bot.hammer_remaining = 20
    bot._dagger_queue = [(i, i) for i in range(2, 21)]  # 19 weitere warten
    bot._before_proc = object()
    bot._dolch_inv_slot = (1, 1)
    bot.state = EnergiesplitterBot.ST_VERIFY_PROCESS
    bot.botting = True
    bot._shot = lambda: object()
    bot.verify_process = lambda a, b: 1   # Verarbeitung verifiziert
    bot.runHack()
    self.assertTrue(bot.botting)                          # NICHT gestoppt
    self.assertNotEqual(getattr(bot, '_stop_reason', None), 'process_unverified')
    self.assertEqual(bot.splitter_summe, 1)
    self.assertEqual(bot.state, EnergiesplitterBot.ST_PROCESS_DRAG)  # naechster Dolch
    self.assertEqual(len(bot._dagger_queue), 18)

  def test_drag_records_hammer_count_before(self):
    _reset_input()
    bot = _make_bot(mode=MODE_DAGGER)
    _arm(bot)
    bot.state = EnergiesplitterBot.ST_PROCESS_DRAG
    bot.botting = True
    bot._dolch_inv_slot = (5, 5)
    bot._classified_hammer_slot = lambda: (1, 1)
    bot._slot_is = lambda item, slot: True
    bot._count_hammers = lambda: 4
    bot._shot = lambda: object()
    bot.runHack()
    self.assertEqual(bot._hammer_count_before_proc, 4)
    self.assertEqual(bot.state, EnergiesplitterBot.ST_VERIFY_PROCESS)

  def test_drag_unsafe_stops_without_drag(self):
    _reset_input()
    bot = _make_bot(mode=MODE_DAGGER)
    _arm(bot)
    bot.state = EnergiesplitterBot.ST_PROCESS_DRAG
    bot.botting = True
    bot._dolch_inv_slot = (5, 5)
    bot._classified_hammer_slot = lambda: None   # Quelle NICHT als Hammer erkannt
    bot.runHack()
    self.assertFalse(bot.botting)
    self.assertEqual(bot._stop_reason, 'drag_unsafe')
    self.assertEqual(_INPUT_CALLS['mouseDown'], 0)
    self.assertEqual(_INPUT_CALLS['moveTo'], 0)

  def test_verified_process_continues_queue(self):
    # Verifiziert -> dekrementiert, naechster Dolch der Runde wird verarbeitet.
    bot = _make_bot(mode=MODE_DAGGER)
    _arm(bot)
    bot.hammer_remaining = 3
    bot.splitter_summe = 0
    bot._dolche_gekauft = 2
    bot._dagger_queue = [(9, 9)]   # noch ein Dolch wartet
    bot._before_proc = object()
    bot.state = EnergiesplitterBot.ST_VERIFY_PROCESS
    bot.botting = True
    bot._shot = lambda: object()
    bot.verify_process = lambda a, b: 1
    bot.runHack()
    self.assertEqual(bot.splitter_summe, 1)
    self.assertEqual(bot.hammer_remaining, 2)
    self.assertEqual(bot._dolch_inv_slot, (9, 9))
    self.assertEqual(bot.state, EnergiesplitterBot.ST_PROCESS_DRAG)

  def test_verified_process_empty_queue_rescans(self):
    bot = _make_bot(mode=MODE_DAGGER)
    _arm(bot)
    bot.hammer_remaining = 3
    bot.splitter_summe = 0
    bot._dolche_gekauft = 1
    bot._dagger_queue = []          # Runde fertig
    bot._before_proc = object()
    bot.state = EnergiesplitterBot.ST_VERIFY_PROCESS
    bot.botting = True
    bot._shot = lambda: object()
    bot.verify_process = lambda a, b: 1
    bot.runHack()
    self.assertEqual(bot.state, EnergiesplitterBot.ST_RESCAN)

  def test_no_growth_no_decrement_then_stop(self):
    bot = _make_bot(mode=MODE_DAGGER)
    _arm(bot)
    bot.hammer_remaining = 3
    bot.splitter_summe = 0
    bot.consecutive_unverified_stop = 1
    bot._before_proc = object()
    bot.state = EnergiesplitterBot.ST_VERIFY_PROCESS
    bot.botting = True
    bot._shot = lambda: object()
    bot.verify_process = lambda a, b: 0   # KEIN Beleg
    bot.runHack()
    self.assertEqual(bot.hammer_remaining, 3)
    self.assertFalse(bot.botting)

  def test_rescan_stops_when_no_hammers(self):
    bot = _make_bot(mode=MODE_DAGGER)
    _arm(bot)
    bot.state = EnergiesplitterBot.ST_RESCAN
    bot.botting = True
    bot._count_hammers = lambda: 0
    bot.runHack()
    self.assertFalse(bot.botting)
    self.assertEqual(bot._stop_reason, 'done')

  def test_rescan_next_round_reopens_shop_via_npc(self):
    # Nach einer Runde ist der Laden GESCHLOSSEN (fuer den Drag) -> die naechste
    # Runde muss den NPC erneut ansprechen + Laden neu oeffnen, also zurueck zu
    # ST_APPROACH_NPC (nicht direkt ST_LOCATE_DOLCH auf geschlossenem Laden).
    bot = _make_bot(mode=MODE_DAGGER)
    _arm(bot)
    bot.state = EnergiesplitterBot.ST_RESCAN
    bot.botting = True
    bot._count_hammers = lambda: 5
    bot.runHack()
    self.assertEqual(bot.state, EnergiesplitterBot.ST_APPROACH_NPC)

  def test_inventory_base_no_hammers_stops(self):
    bot = _make_bot(mode=MODE_DAGGER)
    _arm(bot)
    bot.state = EnergiesplitterBot.ST_INVENTORY_BASE
    bot.botting = True
    bot._ensure_inventory_open = lambda: True   # Offen-Check separat getestet
    bot._item_template_ready = lambda item: True
    bot._count_hammers = lambda: 0
    bot.runHack()
    self.assertFalse(bot.botting)
    self.assertEqual(bot._stop_reason, 'done')


class TestDaggerVerifyByReRead(unittest.TestCase):
  """Grundwahrheit: KEIN Dialog -> verify = Dolch-Slot leer UND Hammer
  dekrementiert (Re-Read), NICHT Splitter-Aussehen."""

  def test_slot_empty_and_hammer_drop_verifies(self):
    bot = _make_bot(mode=MODE_DAGGER)
    _arm(bot)
    bot._dolch_inv_slot = (5, 5)
    bot._hammer_count_before_proc = 3
    fake_detect = types.SimpleNamespace()
    with mock.patch.object(esbot_mod, '_detect', fake_detect):
      bot._slot_is_empty = lambda slot, bgr=None: True
      bot._bag_count_measurable = lambda: True
      bot._count_hammers = lambda: 2   # 3 -> 2 = -1
      out = bot.verify_process(object(), object())
    self.assertEqual(out, 1)

  def test_slot_not_empty_fails(self):
    bot = _make_bot(mode=MODE_DAGGER)
    _arm(bot)
    bot._dolch_inv_slot = (5, 5)
    bot._hammer_count_before_proc = 3
    fake_detect = types.SimpleNamespace()
    with mock.patch.object(esbot_mod, '_detect', fake_detect):
      bot._slot_is_empty = lambda slot, bgr=None: False   # Dolch noch da
      bot._bag_count_measurable = lambda: True
      bot._count_hammers = lambda: 2
      out = bot.verify_process(object(), object())
    self.assertEqual(out, 0)

  def test_hammer_not_dropped_fails_when_measurable(self):
    bot = _make_bot(mode=MODE_DAGGER)
    _arm(bot)
    bot._dolch_inv_slot = (5, 5)
    bot._hammer_count_before_proc = 3
    fake_detect = types.SimpleNamespace()
    with mock.patch.object(esbot_mod, '_detect', fake_detect):
      bot._slot_is_empty = lambda slot, bgr=None: True
      bot._bag_count_measurable = lambda: True
      bot._count_hammers = lambda: 3   # NICHT gesunken
      out = bot.verify_process(object(), object())
    self.assertEqual(out, 0)


class TestAfkDismissAndNpcClick(unittest.TestCase):
    """AFK-Dialog wird per OK-Klick weggeklickt; NPC wird per LINKSklick MITTIG
    auf den Namen angesprochen (nicht mehr Rechtsklick-Anvisieren)."""

    def test_dismiss_afk_clicks_ok_center(self):
        _reset_input()
        bot = _make_bot(mode=MODE_HAMMER)
        _arm(bot)
        fake = types.SimpleNamespace(
            afk_dialog_present=lambda bgr: (True, (396, 335)))
        with mock.patch.object(esbot_mod, '_detect', fake):
            handled = bot._dismiss_afk_if_present()
        self.assertTrue(handled)
        self.assertEqual(_INPUT_CALLS['click'], 1)   # ein Linksklick (OK)

    def test_dismiss_afk_noop_when_absent(self):
        _reset_input()
        bot = _make_bot(mode=MODE_HAMMER)
        _arm(bot)
        fake = types.SimpleNamespace(
            afk_dialog_present=lambda bgr: (False, None))
        with mock.patch.object(esbot_mod, '_detect', fake):
            self.assertFalse(bot._dismiss_afk_if_present())
        self.assertEqual(_INPUT_CALLS['click'], 0)

    def test_select_npc_left_clicks_name_center(self):
        _reset_input()
        bot = _make_bot(mode=MODE_HAMMER)
        _arm(bot)
        ok = bot._select_npc((487, 291))
        self.assertTrue(ok)
        self.assertEqual(_INPUT_CALLS['click'], 1)   # LINKSklick
        self.assertEqual(_INPUT_CALLS['right'], 0)   # KEIN Rechtsklick mehr

    def test_open_dialog_does_not_hard_stop_without_template(self):
        # Dialog-Template (noch) nicht kalibriert -> dialog_state None -> NICHT
        # hart stoppen, sondern fortfahren (Shop-Schritt verifiziert).
        bot = _make_bot(mode=MODE_HAMMER)
        _arm(bot)
        bot.botting = True
        bot._dialog_state_of = lambda bgr: None
        self.assertTrue(bot._open_dialog((487, 291)))
        self.assertNotEqual(bot._stop_reason, 'dialog_timeout')
        self.assertTrue(bot.botting)


class TestOpenShopViaDialog(unittest.TestCase):
    """'Laden oeffnen' finden -> klicken -> Settle -> weiter (Shop-Verifikation
    macht der Locate-Schritt). Nicht gefunden -> sauberer Stop."""

    def test_clicks_laden_oeffnen_when_found(self):
        _reset_input()
        bot = _make_bot(mode=MODE_HAMMER)
        _arm(bot)
        bot.SHOP_OPEN_SETTLE_S = 0
        fake = types.SimpleNamespace(
            find_dialog_line=lambda bgr, tpl: (True, (400, 285), 0.99))
        with mock.patch.object(esbot_mod, '_detect', fake):
            bot._template = lambda k: object()
            ok = bot.open_shop_via_dialog()
        self.assertTrue(ok)
        self.assertEqual(_INPUT_CALLS['click'], 1)        # Linksklick auf die Zeile
        self.assertNotEqual(bot._stop_reason, 'shop_not_open')

    def test_retries_then_stops_when_laden_oeffnen_absent(self):
        # 'Laden oeffnen' nicht da -> erst mit Renderpause erneut suchen
        # (Dialog evtl. noch am Erscheinen), nach DIALOG_OPEN_MAX_TRIES Stop.
        bot = _make_bot(mode=MODE_HAMMER)
        _arm(bot)
        bot.botting = True
        bot.SHOP_OPEN_SETTLE_S = 0
        bot.DIALOG_SETTLE_S = 0
        bot.DIALOG_OPEN_MAX_TRIES = 3
        fake = types.SimpleNamespace(
            find_dialog_line=lambda bgr, tpl: (False, None, 0.2))
        with mock.patch.object(esbot_mod, '_detect', fake):
            bot._template = lambda k: object()
            results = [bot.open_shop_via_dialog()
                       for _ in range(bot.DIALOG_OPEN_MAX_TRIES)]
        self.assertTrue(all(r is False for r in results))
        self.assertEqual(bot._stop_reason, 'shop_not_open')
        self.assertEqual(bot._dialog_open_tries, 3)

    def test_clicks_after_render_retry(self):
        # Erscheint 'Laden oeffnen' erst beim 2. Versuch -> wird dann geklickt.
        bot = _make_bot(mode=MODE_HAMMER)
        _arm(bot)
        bot.botting = True
        bot.SHOP_OPEN_SETTLE_S = 0
        bot.DIALOG_SETTLE_S = 0
        calls = {'n': 0}
        def _find(bgr, tpl):
            calls['n'] += 1
            return (True, (400, 286), 0.95) if calls['n'] >= 2 else (False, None, 0.2)
        fake = types.SimpleNamespace(find_dialog_line=_find)
        with mock.patch.object(esbot_mod, '_detect', fake):
            bot._template = lambda k: object()
            r1 = bot.open_shop_via_dialog()   # noch nicht da -> retry
            r2 = bot.open_shop_via_dialog()   # jetzt da -> klick
        self.assertFalse(r1)
        self.assertTrue(r2)
        self.assertEqual(bot._dialog_open_tries, 0)   # nach Erfolg zurueckgesetzt


class TestEnsureInventoryOpen(unittest.TestCase):
    """Der Energiesplitter erkennt die Tasche-Offen ueber den eigenen, OFFSET-
    TOLERANTEN ``detect.inventory_open`` (periodische Slot-Struktur) statt blind
    zu scannen. Sonst las er bei geschlossener Tasche 0 freie Plaetze (-> falscher
    no_space). Hier mit gestubbtem Detektor (die echte Bild-Erkennung ist in
    test_energiesplitter_detect + TestInventoryOpenCheck abgedeckt)."""

    def _detect_stub(self, open_seq):
        seq = list(open_seq)
        return types.SimpleNamespace(
            INVENTORY_OPEN_MIN=15.0,
            inventory_open=lambda bgr: (seq.pop(0) if seq else (True, 99.0)))

    def test_open_when_probe_true_proceeds(self):
        bot = _make_bot(mode=MODE_HAMMER)
        _arm(bot)
        bot._shot = lambda: object()
        with mock.patch.object(esbot_mod, '_detect',
                               self._detect_stub([(True, 40.0)])):
            self.assertTrue(bot._ensure_inventory_open())
        self.assertNotEqual(bot._stop_reason, 'inventory_not_open')

    def test_closed_unopenable_stops(self):
        _reset_input()
        bot = _make_bot(mode=MODE_HAMMER)
        _arm(bot)
        bot.botting = True
        bot._shot = lambda: object()
        with mock.patch.object(esbot_mod, '_detect',
                               self._detect_stub([(False, 5.0), (False, 5.0),
                                                  (False, 5.0)])):
            self.assertFalse(bot._ensure_inventory_open())
        self.assertEqual(bot._stop_reason, 'inventory_not_open')
        self.assertFalse(bot.botting)

    def test_probe_unavailable_does_not_block(self):
        # headless / kein Detektor -> nicht blockieren (GATE deckt ab).
        bot = _make_bot(mode=MODE_HAMMER)
        _arm(bot)
        with mock.patch.object(esbot_mod, '_detect', None):
            self.assertTrue(bot._ensure_inventory_open())

    def test_presses_configured_hotkey_when_closed(self):
        # War ZU, nach einem Toggle OFFEN -> genau EINE Taste, kein Stop.
        _reset_input()
        bot = _make_bot(mode=MODE_HAMMER)
        _arm(bot)
        bot.inventory_hotkey = 'i'
        bot._shot = lambda: object()
        with mock.patch.object(esbot_mod, '_detect',
                               self._detect_stub([(False, 5.0), (True, 40.0)])):
            self.assertTrue(bot._ensure_inventory_open())
        self.assertEqual(_INPUT_CALLS['keyDown'], 1)   # genau eine Taste


class TestWindowFocus(unittest.TestCase):
  """Tasten brauchen FOKUS -- der Bot muss das Spiel-Fenster in den Vordergrund
  holen (sonst landet z.B. die Vogelperspektive 'g' im Bot-Fenster). Genau das
  fehlte -> NPC-Suche drehte sich endlos, weil 'g' nie im Spiel ankam."""

  def test_press_key_focuses_game_first(self):
    bot = _make_bot(mode=MODE_HAMMER)
    _arm(bot)
    bot.wincap.hwnd = 1234
    calls = []
    with mock.patch.object(esbot_mod, '_focus_window',
                           lambda h: calls.append(h) or True):
      ok = bot._press_key('g')
    self.assertTrue(ok)
    self.assertEqual(calls, [1234])      # vor dem Tastendruck fokussiert

  def test_simulation_does_not_focus_or_press(self):
    # Im Simulationsmodus (dry_run) ist _press_key ein No-op -> kein Fokus-Klau.
    bot = _make_bot(mode=MODE_HAMMER)
    bot.armed = True
    bot.dry_run = True
    bot.wincap.hwnd = 1234
    calls = []
    with mock.patch.object(esbot_mod, '_focus_window',
                           lambda h: calls.append(h) or True):
      ok = bot._press_key('g')
    self.assertFalse(ok)
    self.assertEqual(calls, [])

  def test_run_focuses_game_once_at_start(self):
    bot = _make_bot(mode=MODE_HAMMER)
    _arm(bot)
    bot.wincap.hwnd = 4321
    bot.botting = True
    bot.state = EnergiesplitterBot.ST_INIT
    calls = []
    with mock.patch.object(esbot_mod, '_focus_window',
                           lambda h: calls.append(h) or True):
      bot.runHack()                      # erster scharfer Tick (ST_INIT)
    self.assertTrue(bot._did_focus)
    self.assertEqual(calls, [4321])      # genau einmal in den Vordergrund


class TestShopLocateRenderRetry(unittest.TestCase):
  """Shop blendet nach 'Laden oeffnen' ein -> das Item-Suchen wird mehrfach mit
  Renderpause wiederholt, bevor 'nicht im Shop' gemeldet wird (fing den realen
  Tester-Fall ncc=0.547 = Shop noch nicht fertig gerendert)."""

  def test_locate_hammer_retries_then_stops(self):
    bot = _make_bot(mode=MODE_HAMMER)
    _arm(bot)
    bot.SHOP_OPEN_SETTLE_S = 0
    bot.state = EnergiesplitterBot.ST_LOCATE_HAMMER
    bot.botting = True
    bot._locate_shop_item = lambda item: None      # nie gefunden
    with mock.patch.object(esbot_mod, '_detect', types.SimpleNamespace()):
      for _ in range(EnergiesplitterBot.SHOP_LOCATE_MAX_TRIES + 2):
        if not bot.botting:
          break
        bot.runHack()
    self.assertFalse(bot.botting)
    self.assertEqual(bot._stop_reason, 'item_not_in_shop')
    self.assertEqual(bot._shop_locate_tries,
                     EnergiesplitterBot.SHOP_LOCATE_MAX_TRIES)

  def test_locate_hammer_found_after_render(self):
    bot = _make_bot(mode=MODE_HAMMER)
    _arm(bot)
    bot.SHOP_OPEN_SETTLE_S = 0
    bot.state = EnergiesplitterBot.ST_LOCATE_HAMMER
    bot.botting = True
    calls = {'n': 0}
    def _loc(item):
      calls['n'] += 1
      return (425, 121) if calls['n'] >= 3 else None   # erst nach Render da
    bot._locate_shop_item = _loc
    with mock.patch.object(esbot_mod, '_detect', types.SimpleNamespace()):
      for _ in range(5):
        bot.runHack()
        if bot.state == EnergiesplitterBot.ST_BUY_LOOP:
          break
    self.assertEqual(bot.state, EnergiesplitterBot.ST_BUY_LOOP)
    self.assertEqual(bot._hammer_slot, (425, 121))
    self.assertEqual(bot._shop_locate_tries, 0)        # nach Treffer zurueckgesetzt


class TestProcessAllDaggers(unittest.TestCase):
  """Verarbeitung haemmert ALLE sicher erkannten Dolche im Inventar weg
  (gekauft + bereits vorhanden), nicht nur die gekauften Lande-Slots."""

  def test_queue_becomes_all_dolch_slots(self):
    bot = _make_bot(mode=MODE_DAGGER)
    _arm(bot)
    bot.SHOP_OPEN_SETTLE_S = 0
    bot._dagger_queue = [(7, 7)]                 # nur 1 gekaufter Lande-Slot
    # Inventar enthaelt 3 sichere Dolche (gekauft + 2 bereits vorhandene).
    bot._all_dolch_slots = lambda: [(7, 7), (8, 8), (9, 9)]
    bot._start_processing_queue()
    self.assertEqual(bot.state, EnergiesplitterBot.ST_PROCESS_DRAG)
    # 1 sofort verarbeitet (gepoppt) + 2 in der Queue = alle 3 Dolche.
    self.assertEqual(bot._dolch_inv_slot, (7, 7))
    self.assertEqual(bot._dagger_queue, [(8, 8), (9, 9)])

  def test_fallback_to_bought_when_scan_empty(self):
    bot = _make_bot(mode=MODE_DAGGER)
    _arm(bot)
    bot.SHOP_OPEN_SETTLE_S = 0
    bot._dagger_queue = [(5, 5), (6, 6)]
    bot._all_dolch_slots = lambda: []            # Scan faellt aus
    bot._start_processing_queue()
    self.assertEqual(bot.state, EnergiesplitterBot.ST_PROCESS_DRAG)
    self.assertEqual(bot._dolch_inv_slot, (5, 5))
    self.assertEqual(bot._dagger_queue, [(6, 6)])


class TestBuyConfirmAndCloseShop(unittest.TestCase):
  """Kauf-Bestaetigung 'Ja' wird geklickt, wenn der Dialog erscheint; vor dem
  Dolch-Drag wird der Laden geschlossen (ESC)."""

  def test_confirm_buy_clicks_ja(self):
    _reset_input()
    bot = _make_bot(mode=MODE_HAMMER)
    _arm(bot)
    fake = types.SimpleNamespace(
        buy_confirm_present=lambda bgr: (True, (360, 313)))
    with mock.patch.object(esbot_mod, '_detect', fake):
      handled = bot._confirm_buy_if_present()
    self.assertTrue(handled)
    self.assertEqual(_INPUT_CALLS['click'], 1)        # 'Ja' linksgeklickt

  def test_confirm_buy_noop_when_absent(self):
    _reset_input()
    bot = _make_bot(mode=MODE_HAMMER)
    _arm(bot)
    fake = types.SimpleNamespace(
        buy_confirm_present=lambda bgr: (False, None))
    with mock.patch.object(esbot_mod, '_detect', fake):
      self.assertFalse(bot._confirm_buy_if_present())
    self.assertEqual(_INPUT_CALLS['click'], 0)

  def test_close_shop_presses_esc(self):
    _reset_input()
    bot = _make_bot(mode=MODE_HAMMER)
    _arm(bot)
    bot._close_shop()
    self.assertEqual(_INPUT_CALLS['keyDown'], 1)      # ESC gedrueckt
    self.assertEqual(_INPUT_CALLS['keyUp'], 1)

  def test_processing_queue_closes_shop_before_drag(self):
    # _start_processing_queue MUSS vor dem ersten Drag den Laden schliessen.
    _reset_input()
    bot = _make_bot(mode=MODE_DAGGER)
    _arm(bot)
    bot.SHOP_OPEN_SETTLE_S = 0
    bot._dagger_queue = [(5, 5), (6, 6)]
    bot._start_processing_queue()
    self.assertEqual(bot.state, EnergiesplitterBot.ST_PROCESS_DRAG)
    self.assertEqual(_INPUT_CALLS['keyDown'], 1)      # ESC (Laden zu) vor Drag


class TestApproachNpcBirdseyeDrag(unittest.TestCase):
  """NPC ansprechen: ZUERST volle Vogelperspektive per RECHTSKLICK-DRAG (kein 'g'
  mehr), dann Namens-Suche; bei Miss Kamera nachziehen (bounded), dann Stop.
  Die Maustaste wird IMMER wieder geloest (mouseDown==mouseUp)."""

  def _miss_detect(self, hits_on=None, counter=None):
    def _find(bgr, tpl):
      counter['n'] += 1
      if hits_on is not None and counter['n'] >= hits_on:
        return (True, (50, 60), 0.95)
      return (False, None, 0.0)
    return types.SimpleNamespace(find_npc_name=_find)

  def test_first_call_is_birdseye_drag_no_key(self):
    _reset_input()
    bot = _make_bot(mode=MODE_HAMMER)
    _arm(bot)
    bot.NPC_SETTLE_S = 0
    bot._template = lambda k: object()
    counter = {'n': 0}
    with mock.patch.object(esbot_mod, '_detect',
                           self._miss_detect(counter=counter)):
      out = bot.approach_npc('alchemist')      # erster Tick = Vogelperspektive
    self.assertIsNone(out)
    self.assertTrue(bot._did_birdseye)
    self.assertEqual(_INPUT_CALLS['mouseDown'], 1)   # Rechtsklick gedrueckt
    self.assertEqual(_INPUT_CALLS['mouseUp'], 1)     # ... und wieder geloest
    self.assertGreater(_INPUT_CALLS['moveTo'], 1)    # in einem Rutsch gezogen
    self.assertEqual(_INPUT_CALLS['keyDown'], 0)     # KEIN 'g' mehr
    self.assertEqual(counter['n'], 0)                # noch nicht gesucht

  def test_miss_drags_then_stops_cleanly(self):
    _reset_input()
    bot = _make_bot(mode=MODE_HAMMER)
    _arm(bot)
    bot.NPC_SETTLE_S = 0
    bot.botting = True
    bot._template = lambda k: object()
    counter = {'n': 0}
    with mock.patch.object(esbot_mod, '_detect',
                           self._miss_detect(counter=counter)):
      results = [bot.approach_npc('alchemist')
                 for _ in range(EnergiesplitterBot.NPC_MAX_TRIES + 3)]
    self.assertTrue(all(r is None for r in results))
    self.assertEqual(bot._stop_reason, 'npc_not_found')
    self.assertEqual(_INPUT_CALLS['keyDown'], 0)
    # 1x initiale Vogelperspektive + je Miss ein Nachziehen (bis NPC_MAX_TRIES)
    self.assertGreaterEqual(_INPUT_CALLS['mouseDown'],
                            EnergiesplitterBot.NPC_MAX_TRIES + 1)
    # Maustaste NIE haengen geblieben
    self.assertEqual(_INPUT_CALLS['mouseDown'], _INPUT_CALLS['mouseUp'])

  def test_found_after_birdseye_returns_point(self):
    _reset_input()
    bot = _make_bot(mode=MODE_HAMMER)
    _arm(bot)
    bot.NPC_SETTLE_S = 0
    bot.botting = True
    bot._template = lambda k: object()
    counter = {'n': 0}
    pt = None
    with mock.patch.object(esbot_mod, '_detect',
                           self._miss_detect(hits_on=2, counter=counter)):
      for _ in range(EnergiesplitterBot.NPC_MAX_TRIES + 2):
        pt = bot.approach_npc('alchemist')
        if pt is not None:
          break
    self.assertEqual(pt, (50, 60))
    self.assertNotEqual(bot._stop_reason, 'npc_not_found')
    self.assertTrue(bot.botting)
    self.assertEqual(bot._npc_tries, 0)


class TestInventoryOpenCheck(unittest.TestCase):
  """Regression (Live-Bug 2026-06-20): bei vollem/aufgeraeumtem Beutel meldete
  der Bot faelschlich 'inventory_not_open', obwohl das Inventar offen war.
  Ursache: die pixel-genaue Tab-Template-Probe war am Live-Capture zu offset-
  empfindlich. _ensure_inventory_open nutzt jetzt den OFFSET-TOLERANTEN
  detect.inventory_open (periodische 32px-Slot-Struktur, eigene Raster-
  Geometrie)."""

  _FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      'fixtures', 'energiesplitter')

  def _load(self, *parts):
    try:
      import cv2
    except Exception:
      self.skipTest('cv2 nicht verfuegbar')
    path = os.path.join(self._FIX, *parts)
    img = cv2.imread(path)
    if img is None:
      self.skipTest('fixture fehlt: %s' % path)
    return img

  def test_ensure_open_true_on_real_open_inventory(self):
    # End-to-end mit dem ECHTEN Detektor: offenes (volles) Inventar -> offen
    # erkannt, KEIN Stop, KEINE Toggle-Taste (sonst wuerde der Bot es schliessen).
    img = self._load('inventory_open_full_window.png')
    _reset_input()
    bot = _make_bot(mode=MODE_DAGGER)
    _arm(bot)
    bot.botting = True
    bot._shot = lambda: img
    ok = bot._ensure_inventory_open()
    self.assertTrue(ok)
    self.assertTrue(bot.botting)
    self.assertNotEqual(getattr(bot, '_stop_reason', None), 'inventory_not_open')
    self.assertEqual(_INPUT_CALLS['keyDown'], 0)

  def test_ensure_open_toggles_then_succeeds_when_initially_closed(self):
    # Zuerst zu (NPC-Dialog), nach einem Toggle 'offen' -> der Bot drueckt GENAU
    # einmal die Inventar-Taste und faehrt fort (kein Stop).
    closed = self._load('Einkauf_Hammer', 'erstgespraech3.png')
    opened = self._load('inventory_open_full_window.png')
    seq = [closed, opened, opened]
    _reset_input()
    bot = _make_bot(mode=MODE_DAGGER)
    _arm(bot)
    bot.botting = True
    bot._shot = lambda: seq.pop(0) if seq else opened
    ok = bot._ensure_inventory_open()
    self.assertTrue(ok)
    self.assertTrue(bot.botting)
    self.assertEqual(_INPUT_CALLS['keyDown'], 1)     # genau einmal getoggelt

  def test_ensure_open_stops_when_stays_closed(self):
    # Bleibt es nach allen Toggles zu -> sauberer inventory_not_open-Stop.
    closed = self._load('Einkauf_Hammer', 'erstgespraech3.png')
    _reset_input()
    bot = _make_bot(mode=MODE_DAGGER)
    _arm(bot)
    bot.botting = True
    bot._shot = lambda: closed
    ok = bot._ensure_inventory_open()
    self.assertFalse(ok)
    self.assertFalse(bot.botting)
    self.assertEqual(bot._stop_reason, 'inventory_not_open')


if __name__ == '__main__':
  unittest.main()
