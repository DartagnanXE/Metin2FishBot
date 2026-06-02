# -*- coding: utf-8 -*-
"""Tests for the Run-1 config additions (interface/config.py).

Covers: mount defaults + key validation; event-window defaults + HH:MM/weekday/
warn validation with clamp/fallback on garbage; telemetry defaults (off, url
placeholders, interval clamp, consented); username default + cap; to_values
gains -MOUNT-/-MOUNTKEY- and golden-tuna stays untouched; immutability +
never-raises preserved. Pure stdlib, headless (interface/__init__ is stdlib).
"""

import unittest

from interface import config


class TestMount(unittest.TestCase):
    def test_mount_defaults(self):
        cfg = config.validate(config.DEFAULTS)
        self.assertFalse(cfg['fishing']['mount_enabled'])
        self.assertEqual(cfg['fishing']['mount_key'], '3')

    def test_mount_key_validated_like_bait(self):
        # Invalid token -> default '3'; single char kept (lowercased).
        cfg = config.validate({'fishing': {'mount_key': 'notakey'}})
        self.assertEqual(cfg['fishing']['mount_key'], '3')
        cfg2 = config.validate({'fishing': {'mount_key': 'G'}})
        self.assertEqual(cfg2['fishing']['mount_key'], 'g')

    def test_mount_enabled_coerced_bool(self):
        cfg = config.validate({'fishing': {'mount_enabled': 1}})
        self.assertIs(cfg['fishing']['mount_enabled'], True)


class TestToValuesMount(unittest.TestCase):
    def test_to_values_has_mount_keys(self):
        v = config.to_values(config.DEFAULTS)
        self.assertIn('-MOUNT-', v)
        self.assertIn('-MOUNTKEY-', v)
        self.assertIs(v['-MOUNT-'], False)
        self.assertEqual(v['-MOUNTKEY-'], '3')

    def test_to_values_mount_reflects_config(self):
        v = config.to_values({'fishing': {'mount_enabled': True,
                                          'mount_key': 'r'}})
        self.assertIs(v['-MOUNT-'], True)
        self.assertEqual(v['-MOUNTKEY-'], 'r')

    def test_golden_tuna_untouched(self):
        v = config.to_values(config.DEFAULTS)
        self.assertEqual(v['-GOLDENTUNA-'], 3)
        # And the frozen fishing keys still all present.
        for k in ('-ENDTIMEP-', '-ENDTIME-', '-BAITTIME-', '-THROWTIME-',
                  '-STARTGAME-', '-GOLDENTUNA-'):
            self.assertIn(k, v)


class TestEvents(unittest.TestCase):
    def test_event_defaults(self):
        cfg = config.validate(config.DEFAULTS)
        ev = cfg['events']
        self.assertEqual(len(ev['windows']), 2)
        self.assertEqual(ev['windows'][0],
                         {'weekday': 6, 'start': '12:00', 'end': '16:00'})
        self.assertEqual(ev['windows'][1],
                         {'weekday': 2, 'start': '00:00', 'end': '12:00'})
        self.assertEqual(ev['warn_minutes'], 0)
        self.assertEqual(ev['timezone'], 'Europe/Berlin')

    def test_hhmm_validation_fallback(self):
        cfg = config.validate({'events': {'windows': [
            {'weekday': 6, 'start': '99:99', 'end': 'xx'}]}})
        w0 = cfg['events']['windows'][0]
        # bad fields fall back to that window's defaults
        self.assertEqual(w0['start'], '12:00')
        self.assertEqual(w0['end'], '16:00')

    def test_hhmm_normalised_zero_padded(self):
        cfg = config.validate({'events': {'windows': [
            {'weekday': 1, 'start': '9:5', 'end': '7:0'}]}})
        w0 = cfg['events']['windows'][0]
        self.assertEqual(w0['weekday'], 1)
        self.assertEqual(w0['start'], '09:05')
        self.assertEqual(w0['end'], '07:00')

    def test_weekday_validation_fallback(self):
        cfg = config.validate({'events': {'windows': [
            {'weekday': 99, 'start': '08:00', 'end': '10:00'}]}})
        w0 = cfg['events']['windows'][0]
        self.assertEqual(w0['weekday'], 6)   # falls back to default window 0
        self.assertEqual(w0['start'], '08:00')

    def test_warn_minutes_clamped(self):
        hi = config.validate({'events': {'warn_minutes': 99999}})
        self.assertEqual(hi['events']['warn_minutes'], config.EVENT_WARN_MIN_MAX)
        lo = config.validate({'events': {'warn_minutes': -10}})
        self.assertEqual(lo['events']['warn_minutes'], 0)
        bad = config.validate({'events': {'warn_minutes': 'abc'}})
        self.assertEqual(bad['events']['warn_minutes'], 0)

    def test_always_two_windows_even_if_one_given(self):
        cfg = config.validate({'events': {'windows': [
            {'weekday': 0, 'start': '01:00', 'end': '02:00'}]}})
        self.assertEqual(len(cfg['events']['windows']), 2)
        # second window restored from defaults
        self.assertEqual(cfg['events']['windows'][1]['weekday'], 2)

    def test_garbage_windows_become_defaults(self):
        cfg = config.validate({'events': {'windows': 'not a list'}})
        self.assertEqual(len(cfg['events']['windows']), 2)
        self.assertEqual(cfg['events']['windows'][0]['weekday'], 6)


class TestTelemetry(unittest.TestCase):
    def test_telemetry_defaults_off(self):
        cfg = config.validate(config.DEFAULTS)
        tel = cfg['telemetry']
        self.assertFalse(tel['enabled'])
        self.assertFalse(tel['consented'])
        self.assertEqual(tel['interval_s'], config.TELEMETRY_INTERVAL_DEFAULT)
        self.assertTrue(tel['submit_url'].startswith('https://'))
        self.assertTrue(tel['leaderboard_url'].startswith('https://'))

    def test_interval_clamped(self):
        hi = config.validate({'telemetry': {'interval_s': 999999}})
        self.assertEqual(hi['telemetry']['interval_s'],
                         config.TELEMETRY_INTERVAL_MAX)
        lo = config.validate({'telemetry': {'interval_s': 1}})
        self.assertEqual(lo['telemetry']['interval_s'],
                         config.TELEMETRY_INTERVAL_MIN)

    def test_bad_url_falls_back(self):
        cfg = config.validate({'telemetry': {'submit_url': 'ftp://evil'}})
        self.assertEqual(cfg['telemetry']['submit_url'],
                         config.DEFAULT_SUBMIT_URL)

    def test_plaintext_http_url_rejected(self):
        # HTTPS is mandatory for telemetry (username + HWID + stats on the wire);
        # a plaintext http:// endpoint must fall back to the HTTPS default so we
        # never transmit in cleartext, even if a config is hand-edited.
        for bad in ('http://my.host/submit', 'HTTP://my.host/submit',
                    '  http://my.host/submit  '):
            cfg = config.validate({'telemetry': {'submit_url': bad}})
            self.assertEqual(cfg['telemetry']['submit_url'],
                             config.DEFAULT_SUBMIT_URL)
            self.assertTrue(
                cfg['telemetry']['submit_url'].startswith('https://'))

    def test_https_url_kept(self):
        cfg = config.validate(
            {'telemetry': {'submit_url': 'https://my.host/submit'}})
        self.assertEqual(cfg['telemetry']['submit_url'],
                         'https://my.host/submit')

    def test_consent_flags_coerced(self):
        cfg = config.validate({'telemetry': {'enabled': 1, 'consented': 1}})
        self.assertIs(cfg['telemetry']['enabled'], True)
        self.assertIs(cfg['telemetry']['consented'], True)


class TestUsername(unittest.TestCase):
    def test_default_empty(self):
        self.assertEqual(config.validate(config.DEFAULTS)['username'], '')

    def test_stripped_and_capped(self):
        long = 'x' * 100
        cfg = config.validate({'username': '  ' + long + '  '})
        self.assertEqual(len(cfg['username']), config.USERNAME_MAXLEN)

    def test_non_string_username_safe(self):
        cfg = config.validate({'username': 12345})
        self.assertEqual(cfg['username'], '12345')


class TestImmutabilityAndSafety(unittest.TestCase):
    def test_validate_never_raises_with_new_sections(self):
        for junk in (None, 42, {'events': object()}, {'telemetry': 5},
                     {'fishing': {'mount_key': object()}}):
            cfg = config.validate(junk)
            self.assertIn('events', cfg)
            self.assertIn('telemetry', cfg)

    def test_does_not_mutate_input(self):
        src = {'events': {'warn_minutes': 5}, 'username': 'bob'}
        before = repr(src)
        config.validate(src)
        self.assertEqual(repr(src), before)

    def test_merge_defaults_roundtrip(self):
        merged = config.merge_defaults({})
        cfg = config.validate(merged)
        self.assertIn('mount_enabled', cfg['fishing'])
        self.assertIn('windows', cfg['events'])


if __name__ == '__main__':
    unittest.main()
