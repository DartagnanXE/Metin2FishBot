# -*- coding: utf-8 -*-
"""Run-1 QA: config + i18n parity REGRESSION guard.

A focused lock on the Run-1 invariants so a future edit cannot silently:
  * flip a privacy/opt-in default (telemetry must stay OFF, username empty,
    consent unset) or change the byte-stable fishing defaults (mount OFF, key
    '3', golden-tuna 3);
  * drop one of the two default event windows or move the Berlin timezone;
  * de-sync the client/server numeric caps;
  * ship a Run-1 i18n key that is missing a language or whose EN/DE
    placeholders differ (which would raise / leak a brace at format time).

Pure stdlib; headless.
"""

import string
import unittest

from interface import config
from i18n_data import TRANSLATIONS
import i18n


# Every Run-1 i18n key (mount / events / golden-tuna / ranking / leaderboard /
# onboarding / telemetry settings). Locked so a rename/removal is caught.
RUN1_KEYS = (
    # mount
    'ui.group_mount', 'ui.mount_enabled', 'ui.mount_enabled_sub',
    'ui.mount_key', 'ui.mount_key_sub', 'ui.mount_help',
    # events
    'ui.group_events', 'ui.events_help', 'ui.events_window1',
    'ui.events_window2', 'ui.events_start', 'ui.events_end',
    'ui.events_warn_minutes',
    'ui.weekday_mon', 'ui.weekday_tue', 'ui.weekday_wed', 'ui.weekday_thu',
    'ui.weekday_fri', 'ui.weekday_sat', 'ui.weekday_sun',
    # golden tuna
    'ui.golden_tuna_action', 'ui.golden_tuna_verified',
    'fishing.golden_tuna_clicked',
    # ranking / leaderboard
    'ui.view_ranking', 'ui.ranking_sub', 'ui.stats_title', 'ui.stats_catches',
    'ui.stats_puzzles', 'ui.stats_fishing_time', 'ui.stats_puzzler_time',
    'ui.event_status_title', 'ui.event_active_now', 'ui.event_inactive',
    'ui.event_status_unknown', 'ui.leaderboard_title', 'ui.leaderboard_rank',
    'ui.leaderboard_player', 'ui.leaderboard_catches', 'ui.leaderboard_your_rank',
    'ui.leaderboard_refresh', 'ui.leaderboard_loading',
    'ui.leaderboard_fetch_failed', 'ui.leaderboard_empty',
    'ui.ranking_telemetry_off', 'ui.ranking_banned',
)


def _placeholders(text):
    names = set()
    for _lit, field, _spec, _conv in string.Formatter().parse(text):
        if field:
            names.add(field)
    return names


class TestPrivacyDefaultsLocked(unittest.TestCase):
    def setUp(self):
        self.cfg = config.validate(config.DEFAULTS)

    def test_telemetry_off_and_unconsented(self):
        tel = self.cfg['telemetry']
        self.assertFalse(tel['enabled'])
        self.assertFalse(tel['consented'])

    def test_username_empty_by_default(self):
        self.assertEqual(self.cfg['username'], '')

    def test_placeholder_urls_are_https(self):
        tel = self.cfg['telemetry']
        self.assertTrue(tel['submit_url'].startswith('https://'))
        self.assertTrue(tel['leaderboard_url'].startswith('https://'))

    def test_interval_default(self):
        self.assertEqual(self.cfg['telemetry']['interval_s'],
                         config.TELEMETRY_INTERVAL_DEFAULT)


class TestByteStableFishingDefaults(unittest.TestCase):
    def setUp(self):
        self.cfg = config.validate(config.DEFAULTS)

    def test_mount_off_and_key_three(self):
        self.assertFalse(self.cfg['fishing']['mount_enabled'])
        self.assertEqual(self.cfg['fishing']['mount_key'], '3')

    def test_golden_tuna_default_three(self):
        self.assertEqual(self.cfg['fishing']['golden_tuna_action'], 3)

    def test_to_values_mount_defaults_byte_stable(self):
        v = config.to_values(config.DEFAULTS)
        self.assertIs(v['-MOUNT-'], False)
        self.assertEqual(v['-MOUNTKEY-'], '3')
        self.assertEqual(v['-GOLDENTUNA-'], 3)


class TestEventDefaultsLocked(unittest.TestCase):
    def setUp(self):
        self.ev = config.validate(config.DEFAULTS)['events']

    def test_exactly_two_windows(self):
        self.assertEqual(len(self.ev['windows']), 2)

    def test_window_contents(self):
        self.assertEqual(self.ev['windows'][0],
                         {'weekday': 6, 'start': '12:00', 'end': '16:00'})
        self.assertEqual(self.ev['windows'][1],
                         {'weekday': 2, 'start': '00:00', 'end': '12:00'})

    def test_warn_off_and_berlin_tz(self):
        self.assertEqual(self.ev['warn_minutes'], 0)
        self.assertEqual(self.ev['timezone'], 'Europe/Berlin')


class TestCapsSynced(unittest.TestCase):
    def test_client_server_caps_match_config(self):
        from telemetry import payload
        self.assertEqual(config.USERNAME_MAXLEN, payload.USERNAME_MAXLEN)
        self.assertEqual(config.STATS_MAX_COUNT, payload._MAX_COUNT)
        self.assertEqual(config.STATS_MAX_RUNTIME_S, payload._MAX_RUNTIME_S)


class TestRun1I18nParity(unittest.TestCase):
    def test_all_run1_keys_present(self):
        missing = [k for k in RUN1_KEYS if k not in TRANSLATIONS]
        self.assertEqual(missing, [], 'missing Run-1 i18n keys: {}'.format(
            missing))

    def test_both_languages_non_empty(self):
        for key in RUN1_KEYS:
            entry = TRANSLATIONS[key]
            self.assertTrue(str(entry['en']).strip(), 'empty en: ' + key)
            self.assertTrue(str(entry['de']).strip(), 'empty de: ' + key)

    def test_placeholders_match_per_key(self):
        for key in RUN1_KEYS:
            entry = TRANSLATIONS[key]
            self.assertEqual(
                _placeholders(entry['en']), _placeholders(entry['de']),
                'placeholder mismatch: ' + key)

    def test_event_active_now_has_minutes_placeholder(self):
        # The one Run-1 UI string with a runtime value must keep {minutes}.
        for lang in ('en', 'de'):
            self.assertIn('minutes',
                          _placeholders(TRANSLATIONS['ui.event_active_now'][lang]))

    def test_golden_tuna_clicked_log_placeholders(self):
        # The log line carries field/x/y in BOTH languages.
        for lang in ('en', 'de'):
            ph = _placeholders(TRANSLATIONS['fishing.golden_tuna_clicked'][lang])
            self.assertEqual(ph, {'field', 'x', 'y'})

    def test_renders_de_for_a_sample_key(self):
        try:
            i18n.set_lang('de')
            self.assertEqual(i18n.t('ui.view_ranking'), 'Rangliste')
        finally:
            i18n.set_lang('en')


if __name__ == '__main__':
    unittest.main()
