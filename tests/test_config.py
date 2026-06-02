"""Tests fuer die Konfigurations-Persistenz (interface/config.py).

Spec REDESIGN_SPEC.md Sec.9: Pflichttest 'Config-Persistenz'. Reine stdlib,
headless (interface/__init__ importiert nur stdlib-config, kein customtkinter).
"""

import os
import tempfile
import unittest

from interface import config


class TestDefaultsAndValidate(unittest.TestCase):
    def test_validate_defaults(self):
        cfg = config.validate(config.DEFAULTS)
        self.assertEqual(cfg['mode'], 'fishing')
        self.assertEqual(cfg['puzzle']['detection_mode'], 'default')
        self.assertEqual(cfg['puzzle']['color_mode'], 'single')
        self.assertEqual(cfg['puzzle']['solver_mode'], 'standard')
        self.assertEqual(cfg['fishing']['bait_time'], 2.0)

    def test_validate_never_raises_on_garbage(self):
        for junk in (None, 42, 'x', [], {'mode': object()}):
            cfg = config.validate(junk)
            self.assertIn('fishing', cfg)
            self.assertIn('puzzle', cfg)

    def test_validate_does_not_mutate_input(self):
        src = {'fishing': {'bait_time': 5.0}}
        before = repr(src)
        config.validate(src)
        self.assertEqual(repr(src), before)


class TestClamping(unittest.TestCase):
    def _bait(self, value):
        cfg = config.validate({'fishing': {'bait_time': value}})
        return cfg['fishing']['bait_time']

    def test_delay_clamped_high(self):
        self.assertEqual(self._bait(99), config.DELAY_MAX)

    def test_delay_clamped_low(self):
        self.assertEqual(self._bait(0.0), config.DELAY_MIN)

    def test_delay_nonnumeric_falls_back(self):
        self.assertEqual(self._bait('abc'), 2.0)

    def test_all_three_timings(self):
        cfg = config.validate({'fishing': {
            'bait_time': 100, 'throw_time': -5, 'start_game_time': 'x'}})
        f = cfg['fishing']
        self.assertEqual(f['bait_time'], config.DELAY_MAX)
        self.assertEqual(f['throw_time'], config.DELAY_MIN)
        self.assertEqual(f['start_game_time'], 2.0)


class TestEnumCoercion(unittest.TestCase):
    def test_bad_enums_become_defaults(self):
        cfg = config.validate({
            'mode': 'zzz',
            'puzzle': {'detection_mode': 'x', 'color_mode': 'y',
                       'solver_mode': 'q', 'color_patch': 4}})
        self.assertEqual(cfg['mode'], 'fishing')
        self.assertEqual(cfg['puzzle']['detection_mode'], 'default')
        self.assertEqual(cfg['puzzle']['color_mode'], 'single')
        self.assertEqual(cfg['puzzle']['solver_mode'], 'standard')
        self.assertEqual(cfg['puzzle']['color_patch'], 3)

    def test_valid_enums_kept(self):
        cfg = config.validate({
            'mode': 'puzzle',
            'puzzle': {'detection_mode': 'mark', 'color_mode': 'multi',
                       'solver_mode': 'trained', 'color_patch': 5}})
        self.assertEqual(cfg['mode'], 'puzzle')
        self.assertEqual(cfg['puzzle']['detection_mode'], 'mark')
        self.assertEqual(cfg['puzzle']['color_mode'], 'multi')
        self.assertEqual(cfg['puzzle']['solver_mode'], 'trained')
        self.assertEqual(cfg['puzzle']['color_patch'], 5)


class TestGoldenTunaAction(unittest.TestCase):
    def _action(self, value):
        cfg = config.validate({'fishing': {'golden_tuna_action': value}})
        return cfg['fishing']['golden_tuna_action']

    def test_default_is_three(self):
        cfg = config.validate(config.DEFAULTS)
        self.assertEqual(cfg['fishing']['golden_tuna_action'], 3)

    def test_valid_values_kept(self):
        self.assertEqual(self._action(1), 1)
        self.assertEqual(self._action(2), 2)
        self.assertEqual(self._action(3), 3)

    def test_invalid_enum_falls_back_to_default(self):
        for bad in (0, 4, 5, -1):
            self.assertEqual(self._action(bad), 3)

    def test_non_int_falls_back_to_default(self):
        for bad in ('x', None, [], {}):
            self.assertEqual(self._action(bad), 3)

    def test_numeric_string_coerced(self):
        self.assertEqual(self._action('1'), 1)


class TestMergePartial(unittest.TestCase):
    def test_partial_keeps_other_defaults(self):
        cfg = config.merge_defaults({'puzzle': {'color_mode': 'multi'}})
        self.assertEqual(cfg['puzzle']['color_mode'], 'multi')
        self.assertEqual(cfg['puzzle']['detection_mode'], 'default')
        self.assertEqual(cfg['fishing']['bait_time'], 2.0)


class TestMarkOffsetValidation(unittest.TestCase):
    def test_valid_pair(self):
        cfg = config.validate({'puzzle': {'mark_offset': [12, 34]}})
        self.assertEqual(cfg['puzzle']['mark_offset'], [12, 34])

    def test_invalid_offsets_become_none(self):
        for bad in ('foo', [1], [1, 2, 3]):
            cfg = config.validate({'puzzle': {'mark_offset': bad}})
            self.assertIsNone(cfg['puzzle']['mark_offset'])


class TestMarkSizeValidation(unittest.TestCase):
    def test_default_is_none(self):
        cfg = config.validate(config.DEFAULTS)
        self.assertIsNone(cfg['puzzle']['mark_size'])

    def test_valid_pair(self):
        cfg = config.validate({'puzzle': {'mark_size': [300, 200]}})
        self.assertEqual(cfg['puzzle']['mark_size'], [300, 200])

    def test_float_pair_coerced_to_int(self):
        cfg = config.validate({'puzzle': {'mark_size': [260.0, 170.0]}})
        self.assertEqual(cfg['puzzle']['mark_size'], [260, 170])

    def test_non_positive_becomes_none(self):
        for bad in ([0, 5], [5, 0], [-1, 10], [10, -1]):
            cfg = config.validate({'puzzle': {'mark_size': bad}})
            self.assertIsNone(cfg['puzzle']['mark_size'])

    def test_garbage_becomes_none(self):
        for bad in ('x', [1], [1, 2, 3], 42, {}, ['a', 'b']):
            cfg = config.validate({'puzzle': {'mark_size': bad}})
            self.assertIsNone(cfg['puzzle']['mark_size'])


class TestMarkKeypointsValidation(unittest.TestCase):
    def test_default_is_empty_dict(self):
        cfg = config.validate(config.DEFAULTS)
        self.assertEqual(cfg['puzzle']['mark_keypoints'], {})

    def test_valid_subset_kept(self):
        cfg = config.validate({'puzzle': {'mark_keypoints': {
            'color': [110, 150], 'confirm': [100, 90]}}})
        self.assertEqual(cfg['puzzle']['mark_keypoints'],
                         {'color': [110, 150], 'confirm': [100, 90]})

    def test_all_known_keys_kept(self):
        cfg = config.validate({'puzzle': {'mark_keypoints': {
            'color': [1, 2], 'getpiece': [3, 4],
            'confirm': [5, 6], 'cake': [7, 8]}}})
        self.assertEqual(cfg['puzzle']['mark_keypoints'], {
            'color': [1, 2], 'getpiece': [3, 4],
            'confirm': [5, 6], 'cake': [7, 8]})

    def test_float_values_coerced_to_int(self):
        cfg = config.validate({'puzzle': {'mark_keypoints': {
            'color': [110.0, 150.0]}}})
        self.assertEqual(cfg['puzzle']['mark_keypoints'], {'color': [110, 150]})

    def test_unknown_keys_discarded(self):
        cfg = config.validate({'puzzle': {'mark_keypoints': {
            'color': [1, 2], 'bogus': [9, 9], 'grid': [0, 0]}}})
        self.assertEqual(cfg['puzzle']['mark_keypoints'], {'color': [1, 2]})

    def test_malformed_values_discarded(self):
        cfg = config.validate({'puzzle': {'mark_keypoints': {
            'color': 'nope', 'getpiece': [1], 'confirm': [1, 2, 3],
            'cake': [5, 7]}}})
        self.assertEqual(cfg['puzzle']['mark_keypoints'], {'cake': [5, 7]})

    def test_garbage_becomes_empty_dict(self):
        for bad in (None, 'x', 42, [], [1, 2]):
            cfg = config.validate({'puzzle': {'mark_keypoints': bad}})
            self.assertEqual(cfg['puzzle']['mark_keypoints'], {})

    def test_does_not_mutate_input(self):
        src = {'puzzle': {'mark_keypoints': {'color': [1, 2], 'bogus': [3, 4]}}}
        before = repr(src)
        config.validate(src)
        self.assertEqual(repr(src), before)


class TestNewSettings(unittest.TestCase):
    def test_hotkey_defaults(self):
        cfg = config.validate(config.DEFAULTS)
        self.assertEqual(cfg['fishing']['bait_key'], '2')
        self.assertEqual(cfg['fishing']['cast_key'], '1')

    def test_hotkey_invalid_falls_back(self):
        cfg = config.validate({'fishing': {'bait_key': 'nope', 'cast_key': ''}})
        self.assertEqual(cfg['fishing']['bait_key'], '2')
        self.assertEqual(cfg['fishing']['cast_key'], '1')

    def test_hotkey_token_and_char_kept_lowercased(self):
        cfg = config.validate({'fishing': {'bait_key': 'F5', 'cast_key': 'Q'}})
        self.assertEqual(cfg['fishing']['bait_key'], 'f5')
        self.assertEqual(cfg['fishing']['cast_key'], 'q')

    def test_window_defaults_present_and_false(self):
        w = config.validate(config.DEFAULTS)['window']
        self.assertEqual(w, {'always_on_top': False, 'minimize_to_tray': False,
                             'close_on_metin2_close': False,
                             'close_on_timer_expire': False})

    def test_window_bools_coerced(self):
        w = config.validate({'window': {'always_on_top': 1,
                                        'minimize_to_tray': 'yes'}})['window']
        self.assertIs(w['always_on_top'], True)
        self.assertIs(w['minimize_to_tray'], True)

    def test_old_config_without_window_merges(self):
        # Alte config.json ohne window/hotkeys -> Defaults aufgefuellt.
        cfg = config.validate({'mode': 'puzzle', 'fishing': {'bait_time': 3.0}})
        self.assertIn('window', cfg)
        self.assertEqual(cfg['fishing']['cast_key'], '1')


class TestInventorySettings(unittest.TestCase):
    """Inventory config section: hotkey + (stubbed) auto-scan toggle."""

    def test_inventory_defaults(self):
        inv = config.validate(config.DEFAULTS)['inventory']
        self.assertEqual(inv['hotkey'], 'i')
        self.assertIs(inv['auto_scan_after_fishing'], False)

    def test_inventory_hotkey_invalid_falls_back(self):
        cfg = config.validate({'inventory': {'hotkey': 'nope'}})
        self.assertEqual(cfg['inventory']['hotkey'], 'i')

    def test_inventory_hotkey_uppercased(self):
        cfg = config.validate({'inventory': {'hotkey': 'I'}})
        self.assertEqual(cfg['inventory']['hotkey'], 'i')

    def test_inventory_auto_scan_bool_coerced(self):
        cfg = config.validate({'inventory': {'auto_scan_after_fishing': 1}})
        self.assertIs(cfg['inventory']['auto_scan_after_fishing'], True)

    def test_old_config_without_inventory_merges(self):
        # Alte config.json ohne inventory -> Default-Sektion aufgefuellt.
        cfg = config.validate({'mode': 'puzzle'})
        self.assertIn('inventory', cfg)
        self.assertEqual(cfg['inventory']['hotkey'], 'i')
        self.assertIs(cfg['inventory']['auto_scan_after_fishing'], False)


class TestOverlayOpacity(unittest.TestCase):
    def _opacity(self, value):
        cfg = config.validate({'puzzle': {'overlay_opacity': value}})
        return cfg['puzzle']['overlay_opacity']

    def test_default_present(self):
        cfg = config.validate(config.DEFAULTS)
        self.assertEqual(cfg['puzzle']['overlay_opacity'], 0.85)

    def test_clamped_high(self):
        self.assertEqual(self._opacity(5.0), config.OVERLAY_OPACITY_MAX)

    def test_clamped_low(self):
        self.assertEqual(self._opacity(0.0), config.OVERLAY_OPACITY_MIN)

    def test_in_range_kept(self):
        self.assertEqual(self._opacity(0.6), 0.6)

    def test_nonnumeric_falls_back_to_default(self):
        for bad in ('x', None, [], {}):
            self.assertEqual(self._opacity(bad), 0.85)

    def test_old_config_without_opacity_backfilled(self):
        # Alte config.json ohne overlay_opacity -> Default aufgefuellt.
        cfg = config.validate({'mode': 'puzzle',
                               'puzzle': {'detection_mode': 'default'}})
        self.assertEqual(cfg['puzzle']['overlay_opacity'], 0.85)

    def test_not_in_to_values(self):
        # overlay_opacity ist ein UI-/Puzzle-Wert, kein Fishing-Bot-Wert.
        v = config.to_values(config.DEFAULTS)
        self.assertNotIn('overlay_opacity', v)
        self.assertNotIn('-OVERLAY-', v)


class TestToValues(unittest.TestCase):
    def test_keys_and_types(self):
        v = config.to_values(config.DEFAULTS)
        self.assertEqual(set(v), {'-ENDTIMEP-', '-ENDTIME-',
                                  '-BAITTIME-', '-THROWTIME-', '-STARTGAME-',
                                  '-GOLDENTUNA-', '-MOUNT-', '-MOUNTKEY-'})
        self.assertIsInstance(v['-ENDTIMEP-'], bool)
        self.assertIsInstance(v['-ENDTIME-'], str)
        self.assertIsInstance(v['-BAITTIME-'], float)
        self.assertIsInstance(v['-THROWTIME-'], float)
        self.assertIsInstance(v['-STARTGAME-'], float)
        self.assertIsInstance(v['-GOLDENTUNA-'], int)
        self.assertIsInstance(v['-MOUNT-'], bool)
        self.assertIsInstance(v['-MOUNTKEY-'], str)

    def test_golden_tuna_carried_as_int(self):
        v = config.to_values({'fishing': {'golden_tuna_action': 1}})
        self.assertEqual(v['-GOLDENTUNA-'], 1)
        self.assertIsInstance(v['-GOLDENTUNA-'], int)


class TestPersistence(unittest.TestCase):
    def test_save_then_load_roundtrip(self):
        cfg = config.validate({
            'mode': 'puzzle',
            'fishing': {'bait_time': 3.5},
            'puzzle': {'detection_mode': 'mark', 'mark_offset': [50, 60],
                       'color_mode': 'multi', 'solver_mode': 'trained'}})
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'config.json')
            self.assertTrue(config.save(cfg, path))
            loaded = config.load(path)
        self.assertEqual(loaded, cfg)

    def test_save_then_load_roundtrip_with_mark_fields(self):
        cfg = config.validate({
            'mode': 'puzzle',
            'puzzle': {'detection_mode': 'mark', 'mark_offset': [50, 60],
                       'mark_size': [300, 200],
                       'mark_keypoints': {'color': [110, 150],
                                          'cake': [120, 90]}}})
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'config.json')
            self.assertTrue(config.save(cfg, path))
            loaded = config.load(path)
        self.assertEqual(loaded, cfg)
        self.assertEqual(loaded['puzzle']['mark_size'], [300, 200])
        self.assertEqual(loaded['puzzle']['mark_keypoints'],
                         {'color': [110, 150], 'cake': [120, 90]})

    def test_old_config_without_mark_fields_backfilled(self):
        """Alte config.json ohne die neuen Felder bleibt nutzbar (Defaults)."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'config.json')
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write('{"version": 1, "mode": "puzzle", '
                         '"puzzle": {"detection_mode": "default"}}')
            loaded = config.load(path)
        self.assertIsNone(loaded['puzzle']['mark_size'])
        self.assertEqual(loaded['puzzle']['mark_keypoints'], {})

    def test_missing_file_returns_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            loaded = config.load(os.path.join(d, 'nope.json'))
        self.assertEqual(loaded, config.validate(config.DEFAULTS))

    def test_corrupt_file_returns_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'config.json')
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write('{ not valid json ')
            loaded = config.load(path)
        self.assertEqual(loaded, config.validate(config.DEFAULTS))


if __name__ == '__main__':
    unittest.main()
