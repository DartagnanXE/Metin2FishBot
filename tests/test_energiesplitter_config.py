# -*- coding: utf-8 -*-
"""Tests fuer die reine Energiesplitter-Rechen-Hilfe (energiesplitter/calc.py)
und das Config-Schema (defaults/validate/clamp/enum) nach dem Umbau 2026-06-16.

YANG spielt keine Rolle mehr: kein Preis, kein Floor, kein Spend-Deckel, kein
Yang-Rechner. Aktion 1 = ``stack_count`` (X) 200er-Stacks; Aktion 2 =
``daggers_per_round`` Dolche pro Runde (sequenziell verarbeitet).

Headless, reine stdlib: calc.py ist trivial; das Config-Modul ist toolkit-frei
importierbar.
"""

import unittest

from energiesplitter import calc
from interface import config


# ---------------------------------------------------------------------------
# energiesplitter/calc.py -- clamp_nonneg_int (der einzige verbliebene Helfer)
# ---------------------------------------------------------------------------
class TestClampNonnegInt(unittest.TestCase):
  def test_positive_passthrough(self):
    self.assertEqual(calc.clamp_nonneg_int(5), 5)

  def test_zero_and_negative_become_zero(self):
    for n in (0, -1, -999):
      self.assertEqual(calc.clamp_nonneg_int(n), 0)

  def test_float_truncates(self):
    self.assertEqual(calc.clamp_nonneg_int(3.9), 3)

  def test_garbage_never_raises(self):
    for bad in (None, 'x', [], {}, object()):
      self.assertEqual(calc.clamp_nonneg_int(bad), 0)


# ---------------------------------------------------------------------------
# Config-Schema: defaults / validate / clamp / enum
# ---------------------------------------------------------------------------
class TestEnergiesplitterConfig(unittest.TestCase):
  def test_app_modes_include_es(self):
    self.assertIn('energiesplitter_hammer', config.APP_MODES)
    self.assertIn('energiesplitter_dagger', config.APP_MODES)

  def test_defaults_present(self):
    cfg = config.validate(config.DEFAULTS)
    es = cfg['energiesplitter']
    self.assertEqual(es['hammer']['stack_count'], 1)
    self.assertEqual(es['hammer']['energie_freischalten'], True)
    self.assertEqual(es['dagger']['daggers_per_round'], 20)
    self.assertEqual(es['shared']['speed_profile'], 'fast')
    # Default = SCHARF/Live (dry_run False) -- Tester sollen direkt testen koennen
    # (User-Entscheidung 2026-06-16). Der 'Scharf/Live'-Schalter bleibt erhalten.
    self.assertEqual(es['shared']['dry_run'], False)

  def test_no_yang_keys_remain(self):
    # Yang/gold/price/floor/spend/prefer_stack/process_mode/batch sind ENTFERNT.
    cfg = config.validate(config.DEFAULTS)
    es = cfg['energiesplitter']
    for sub in ('hammer', 'dagger', 'shared'):
      for forbidden in ('price_per_item', 'gold_floor', 'max_gold_spend',
                        'yang_check', 'prefer_stack', 'process_mode',
                        'batch_size', 'hammer_count'):
        self.assertNotIn(forbidden, es[sub], (sub, forbidden))

  def test_modes_validate(self):
    for mode in ('energiesplitter_hammer', 'energiesplitter_dagger'):
      cfg = config.validate({'mode': mode})
      self.assertEqual(cfg['mode'], mode)

  def test_stack_count_clamped(self):
    low = config.validate(
        {'energiesplitter': {'hammer': {'stack_count': 0}}})
    high = config.validate(
        {'energiesplitter': {'hammer': {'stack_count': 999999}}})
    self.assertEqual(low['energiesplitter']['hammer']['stack_count'],
                     config.ES_STACK_MIN)
    self.assertEqual(high['energiesplitter']['hammer']['stack_count'],
                     config.ES_STACK_MAX)

  def test_daggers_per_round_clamped(self):
    low = config.validate(
        {'energiesplitter': {'dagger': {'daggers_per_round': 0}}})
    high = config.validate(
        {'energiesplitter': {'dagger': {'daggers_per_round': 99999}}})
    self.assertEqual(low['energiesplitter']['dagger']['daggers_per_round'],
                     config.ES_DAGGERS_MIN)
    self.assertEqual(high['energiesplitter']['dagger']['daggers_per_round'],
                     config.ES_DAGGERS_MAX)

  def test_process_first_and_proc_delays(self):
    # process_first ist bool; die Verarbeiten-Delays werden auf [0, 3] geklemmt.
    cfg = config.validate({'energiesplitter': {'dagger': {
        'process_first': True, 'process_pickup_s': 99,
        'process_confirm_s': -5}}})
    d = cfg['energiesplitter']['dagger']
    self.assertIs(d['process_first'], True)
    self.assertEqual(d['process_pickup_s'], 3.0)
    self.assertEqual(d['process_confirm_s'], 0.0)

  def test_process_defaults(self):
    es = config.DEFAULTS['energiesplitter']['dagger']
    self.assertIs(es['process_first'], False)
    self.assertEqual(es['process_pickup_s'], 0.15)
    self.assertEqual(es['process_confirm_s'], 0.4)

  def test_pause_clamped(self):
    cfg = config.validate(
        {'energiesplitter': {'shared': {'mouse_pause': 99,
                                        'keyboard_pause': 0.0}}})
    s = cfg['energiesplitter']['shared']
    self.assertEqual(s['mouse_pause'], config.ES_PAUSE_MAX)
    self.assertEqual(s['keyboard_pause'], config.ES_PAUSE_MIN)

  def test_bad_enums_fall_back(self):
    cfg = config.validate({'energiesplitter': {
        'shared': {'speed_profile': 'turbo'}}})
    es = cfg['energiesplitter']
    self.assertEqual(es['shared']['speed_profile'], 'fast')

  def test_garbage_block_yields_defaults(self):
    for junk in (None, 42, 'x', [], {'hammer': 'bad'}):
      cfg = config.validate({'energiesplitter': junk})
      es = cfg['energiesplitter']
      self.assertIn('hammer', es)
      self.assertIn('dagger', es)
      self.assertIn('shared', es)
      self.assertIsInstance(es['hammer']['stack_count'], int)

  def test_validate_does_not_mutate_input(self):
    src = {'energiesplitter': {'hammer': {'stack_count': 5}}}
    before = repr(src)
    config.validate(src)
    self.assertEqual(repr(src), before)


if __name__ == '__main__':
  unittest.main()
