# -*- coding: utf-8 -*-
"""Run-1 QA: ranking-tab DATA handling (interface/ranking_view.py).

The ranking view is mostly Tk, but its data-shaping + branching logic is pure
and load-bearing, so we test it WITHOUT a Tk root by:
  * driving the real ``refresh_leaderboard`` / ``_on_board`` branches with a
    fake ``app`` (a plain object) and patching only the three Tk-touching sinks
    (``_set_notice`` / ``_clear_board`` / ``_render_board``) to record calls;
  * exercising ``_hms`` directly.

Asserted behaviour:
  * banned state -> the banned notice, board cleared, NO network worker spawned;
  * telemetry OFF -> the telemetry-off notice, board cleared, no worker;
  * opt-in ON -> a loading notice + a worker thread is started;
  * ``_on_board`` accepts {'all':[...]} / {'daily':[...]} / flat {'entries':[...]}
    and ignores non-dict / empty payloads with the right notice;
  * a row's catches read from 'fishing_catches' or legacy 'catches', rank from
    'rank' (fallback to position), and the user's own row is detected for the
    "your rank" notice;
  * ``_hms`` formats seconds as HH:MM:SS and clamps garbage/negatives.

Headless: ranking_view imports under py.exe (customtkinter present); we never
construct widgets.
"""

import threading
import unittest
from unittest import mock

from interface import ranking_view as rv


class _FakeBody:
    """Stand-in for the Tk board frame: only winfo_children() is used here."""

    def winfo_children(self):
        return []


class _FakeController:
    def __init__(self, cfg):
        self._cfg = cfg

    def current_config(self):
        return self._cfg


class _FakeApp:
    """Minimal stand-in for the CTk app the view reads from."""

    def __init__(self, cfg, banned=False):
        self.controller = _FakeController(cfg)
        self._ranking_banned = banned
        self._stats = {'fishing_catches': 1, 'puzzles_solved': 0,
                       'fishing_runtime_s': 0.0, 'puzzler_runtime_s': 0.0}
        self.after_calls = []

    def after(self, delay, fn):
        # Run synchronously so worker results are observable in-test.
        self.after_calls.append(delay)
        fn()


def _cfg(enabled=False, username='', leaderboard_url='https://x/leaderboard'):
    return {
        'telemetry': {'enabled': enabled, 'leaderboard_url': leaderboard_url},
        'username': username,
        'events': {'windows': [], 'warn_minutes': 0},
    }


class TestHms(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(rv._hms(0), '00:00:00')

    def test_h_m_s(self):
        self.assertEqual(rv._hms(3661), '01:01:01')

    def test_minutes_seconds(self):
        self.assertEqual(rv._hms(125), '00:02:05')

    def test_negative_clamped(self):
        self.assertEqual(rv._hms(-50), '00:00:00')

    def test_garbage_safe(self):
        self.assertEqual(rv._hms('nope'), '00:00:00')

    def test_large_value(self):
        self.assertEqual(rv._hms(36000), '10:00:00')


class TestRefreshGating(unittest.TestCase):
    def setUp(self):
        # Patch the Tk sinks for the whole class; record notices + board clears.
        self.notices = []
        self.cleared = []
        self.rendered = []
        self._p = [
            mock.patch.object(rv, '_set_notice',
                              lambda app, text: self.notices.append(text)),
            mock.patch.object(rv, '_clear_board',
                              lambda app: self.cleared.append(True)),
            mock.patch.object(rv, 'render_stats', lambda app, s: None),
            mock.patch.object(rv, 'render_event_status', lambda app, s: None),
            mock.patch.object(rv, '_current_status', lambda app: {}),
        ]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def test_banned_shows_notice_and_no_worker(self):
        app = _FakeApp(_cfg(enabled=True, username='bob'), banned=True)
        with mock.patch.object(threading, 'Thread',
                               side_effect=AssertionError('no worker')) as th:
            rv.refresh_leaderboard(app)
        self.assertEqual(th.call_count, 0)
        self.assertTrue(self.cleared)
        # The last notice is the banned message.
        from i18n import t
        self.assertIn(t('ui.ranking_banned'), self.notices)

    def test_telemetry_off_shows_notice_and_no_worker(self):
        app = _FakeApp(_cfg(enabled=False))
        with mock.patch.object(threading, 'Thread',
                               side_effect=AssertionError('no worker')) as th:
            rv.refresh_leaderboard(app)
        self.assertEqual(th.call_count, 0)
        from i18n import t
        self.assertIn(t('ui.ranking_telemetry_off'), self.notices)

    def test_opt_in_starts_worker_and_loading_notice(self):
        app = _FakeApp(_cfg(enabled=True, username='bob'))
        started = {}

        class _FakeThread:
            def __init__(self, target=None, name=None, daemon=None):
                started['target'] = target
                started['daemon'] = daemon

            def start(self):
                started['started'] = True

        with mock.patch.object(threading, 'Thread', _FakeThread):
            rv.refresh_leaderboard(app)
        self.assertTrue(started.get('started'))
        self.assertTrue(started.get('daemon'))
        from i18n import t
        self.assertIn(t('ui.leaderboard_loading'), self.notices)


class TestOnBoardShapes(unittest.TestCase):
    def setUp(self):
        self.notices = []
        self.rendered = []
        self._p = [
            mock.patch.object(rv, '_set_notice',
                              lambda app, text: self.notices.append(text)),
            mock.patch.object(rv, '_clear_board', lambda app: None),
            mock.patch.object(
                rv, '_render_board',
                lambda app, entries, username: self.rendered.append(
                    (list(entries), username))),
        ]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def test_all_key_preferred(self):
        rv._on_board(_FakeApp(_cfg()),
                     {'all': [{'username': 'a', 'fishing_catches': 9}],
                      'daily': [{'username': 'd'}]}, 'a')
        self.assertEqual(len(self.rendered), 1)
        entries, user = self.rendered[0]
        self.assertEqual(entries[0]['username'], 'a')
        self.assertEqual(user, 'a')

    def test_daily_key_used_when_no_all(self):
        rv._on_board(_FakeApp(_cfg()),
                     {'daily': [{'username': 'd', 'fishing_catches': 3}]}, '')
        self.assertEqual(self.rendered[0][0][0]['username'], 'd')

    def test_flat_entries_shape(self):
        rv._on_board(_FakeApp(_cfg()),
                     {'entries': [{'username': 'e', 'fishing_catches': 1}]}, '')
        self.assertEqual(self.rendered[0][0][0]['username'], 'e')

    def test_non_dict_payload_failed_notice(self):
        rv._on_board(_FakeApp(_cfg()), None, '')
        from i18n import t
        self.assertIn(t('ui.leaderboard_fetch_failed'), self.notices)
        self.assertEqual(self.rendered, [])

    def test_empty_entries_empty_notice(self):
        rv._on_board(_FakeApp(_cfg()), {'all': []}, '')
        from i18n import t
        self.assertIn(t('ui.leaderboard_empty'), self.notices)
        self.assertEqual(self.rendered, [])


class TestRowExtraction(unittest.TestCase):
    """The per-row field extraction logic inside _render_board, replicated and
    asserted against the real function via a recording _board_row."""

    def setUp(self):
        self.rows = []
        self._p = [
            mock.patch.object(
                rv, '_board_row',
                lambda body, row, rank, name, catches, header=False,
                mine=False: self.rows.append(
                    (row, rank, name, catches, header, mine))),
            mock.patch.object(rv, '_set_notice',
                              lambda app, text: self.notices.append(text)),
        ]
        self.notices = []
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def _app(self):
        app = _FakeApp(_cfg())
        # _render_board clears prior children via winfo_children(); a tiny stub
        # is enough (we never create real widgets).
        app._rank_board_body = _FakeBody()
        return app

    def test_catches_from_fishing_catches(self):
        rv._render_board(self._app(),
                         [{'username': 'a', 'fishing_catches': 42, 'rank': 1}],
                         'a')
        # rows[0] is the header; rows[1] the data row.
        data = self.rows[1]
        self.assertEqual(data[2], 'a')        # name
        self.assertEqual(data[3], '42')       # catches
        self.assertEqual(data[1], '1')        # rank
        self.assertTrue(data[5])              # mine == True (own row)

    def test_catches_legacy_key_fallback(self):
        rv._render_board(self._app(),
                         [{'username': 'b', 'catches': 7}], 'other')
        data = self.rows[1]
        self.assertEqual(data[3], '7')
        self.assertFalse(data[5])             # not the user's row

    def test_rank_falls_back_to_position(self):
        rv._render_board(self._app(),
                         [{'username': 'x'}, {'username': 'y'}], '')
        # Two data rows after the header; ranks default to 1 and 2.
        self.assertEqual(self.rows[1][1], '1')
        self.assertEqual(self.rows[2][1], '2')

    def test_caps_at_ten_rows(self):
        entries = [{'username': 'u{}'.format(i), 'fishing_catches': i}
                   for i in range(50)]
        rv._render_board(self._app(), entries, '')
        # 1 header + 10 data rows max.
        data_rows = [r for r in self.rows if not r[4]]
        self.assertEqual(len(data_rows), 10)

    def test_own_rank_notice_emitted(self):
        rv._render_board(self._app(),
                         [{'username': 'me', 'fishing_catches': 5, 'rank': 3}],
                         'me')
        from i18n import t
        self.assertIn(t('ui.leaderboard_your_rank', rank=3), self.notices)


if __name__ == '__main__':
    unittest.main()
