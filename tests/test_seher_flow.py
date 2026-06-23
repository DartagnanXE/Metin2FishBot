# -*- coding: utf-8 -*-
"""Tests fuer den Seherwettstreit-Start-/End-Flow + Session-Loop.

Fixtures: echte 800x600-Screenshots aller Flow-Zustaende (Eventuebersicht
einzeln/mehrzeilig, Info-Fenster sauber/verdeckt, Teilnahme-Dialog,
Belohnungs-Popup, ESC-Menue) -- Fenster jeweils an anderen Positionen.
"""
import os

import numpy as np
import pytest
from PIL import Image

from seher import detect, flow, geometry as G

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')


def _load(name):
    rgb = np.asarray(Image.open(os.path.join(FIX, name)).convert('RGB'))
    return rgb[:, :, ::-1].copy()


@pytest.fixture(scope='module')
def fx():
    names = ['seher_flow_overview_single.png', 'seher_flow_overview_multi.png',
             'seher_flow_info.png', 'seher_flow_info_busy.png',
             'seher_flow_confirm.png', 'seher_flow_confirm_busy.png',
             'seher_flow_reward.png', 'seher_flow_escmenu.png',
             'seher_start.png']
    return {n: _load(n) for n in names}


# -- Template-Findung (saubere + verdeckte Varianten) -----------------------

@pytest.mark.parametrize('tpl,pos_fixture,neg_fixture', [
    ('flow_event_title', 'seher_flow_overview_multi.png', 'seher_flow_info.png'),
    ('flow_seher_label', 'seher_flow_overview_multi.png', 'seher_flow_info.png'),
    ('flow_start_btn', 'seher_flow_info_busy.png', 'seher_flow_overview_single.png'),
    ('flow_ja_btn', 'seher_flow_confirm_busy.png', 'seher_flow_info.png'),
    ('flow_reward_ok', 'seher_flow_reward.png', 'seher_flow_overview_single.png'),
    ('flow_menu_charwechsel', 'seher_flow_escmenu.png', 'seher_flow_overview_single.png'),
    ('flow_menu_beenden', 'seher_flow_escmenu.png', 'seher_flow_overview_single.png'),
])
def test_flow_templates(fx, tpl, pos_fixture, neg_fixture):
    ok, _pos, ncc = flow.find(fx[pos_fixture], tpl)
    assert ok and ncc > 0.95
    ok_n, _p, ncc_n = flow.find(fx[neg_fixture], tpl)
    assert not ok_n, f'{tpl} false-positive ncc={ncc_n}'


def test_seher_click_targets_name_field_multi(fx):
    """User-bestaetigt (2026-06-11): geklickt wird das SEHERWETTSTREIT-
    NAMENSFELD, NICHT der Ansehen-Knopf. In der 3-Event-Uebersicht muss der
    Klick auf dem Namensfeld der ersten Zeile liegen (links, ~x476/y146),
    NICHT in der Ansehen-Spalte (x>580)."""
    ok, pt, dbg = flow.find_seher_click(fx['seher_flow_overview_multi.png'])
    assert ok, dbg
    assert abs(pt[1] - 146) <= 5          # Zeile 1
    assert 430 <= pt[0] <= 520            # Namensfeld, NICHT Ansehen (>580)
    # Klickpunkt liegt im gematchten Label-Bereich (= auf dem Plate)
    lok, lpos, _ = flow.find(fx['seher_flow_overview_multi.png'],
                             'flow_seher_label')
    lt = flow._tpl('flow_seher_label')
    assert lpos[0] <= pt[0] <= lpos[0] + lt.shape[1]


def test_seher_click_targets_name_field_single(fx):
    ok, pt, dbg = flow.find_seher_click(fx['seher_flow_overview_single.png'])
    assert ok, dbg
    assert 340 <= pt[0] <= 440            # Namensfeld
    assert abs(pt[1] - 146) <= 5


def test_seher_click_blocked_without_overview(fx):
    # Fehlklick-Schutz: kein Eventuebersicht-Titel -> kein Klick.
    ok, _pt, dbg = flow.find_seher_click(fx['seher_flow_info.png'])
    assert not ok
    for n in ('seher_flow_confirm.png', 'seher_start.png',
              'seher_flow_reward.png'):
        ok2, _p, _d = flow.find_seher_click(fx[n])
        assert not ok2, n


def test_looks_like_game_disambiguates_info_window(fx):
    # Info-Fenster traegt denselben Titel -> Anker matcht, Spielfeld nicht.
    ok, _pos, ncc = detect.find_anchor(fx['seher_flow_info.png'])
    assert ok and ncc > 0.99
    assert not flow.looks_like_game(fx['seher_flow_info.png'])
    assert flow.looks_like_game(fx['seher_start.png'])


def test_anchor_absent_on_non_game_states(fx):
    for n in ('seher_flow_reward.png', 'seher_flow_overview_multi.png',
              'seher_flow_escmenu.png'):
        ok, _pos, _ncc = detect.find_anchor(fx[n])
        assert not ok, n


# -- Session-E2E (Fake-Zustandsmaschine ueber echte Fixtures) ----------------

class _SessionPDI:
    PAUSE = 0.1

    def __init__(self, sim):
        self.sim = sim
        self.keys = []
        self._ctrl = False

    def click(self, x, y, button='left'):
        self.sim.on_click(x, y)

    def moveTo(self, x, y):
        pass

    def keyDown(self, k):
        self.keys.append(('down', k))
        if k == 'ctrl':
            self._ctrl = True

    def keyUp(self, k):
        self.keys.append(('up', k))
        # Strg+E wird jetzt via keyDown/keyUp('e') gesendet (gehaerteter
        # _press_ctrl_e) -> beim Loslassen von 'e' mit gehaltenem Ctrl feuern.
        if k == 'e':
            self.sim.on_key('e', ctrl=self._ctrl)
        if k == 'ctrl':
            self._ctrl = False

    def press(self, k):
        self.keys.append(('press', k))
        self.sim.on_key(k, ctrl=self._ctrl)


class _SessionSim:
    """Zustandsmaschine: idle -> overview -> info -> confirm -> game ->
    reward -> idle -> ... ; nach `games_allowed` Starts bleibt das Spiel aus
    (Vorrat leer). ESC im idle oeffnet das Systemmenue."""

    # Klick-Rechtecke (Template-Pos der Fixtures + Groesse)
    RECTS = {
        'seherlabel': (401, 135, 150, 22),    # Namensfeld (overview_multi)
        'start': (370, 426, 65, 18),         # info_busy
        'ja': (340, 305, 45, 17),            # confirm_busy
        'ok': (372, 314, 62, 20),            # reward
        'charwechsel': (350, 316, 100, 15),  # escmenu
    }

    def __init__(self, fx, cross, games_allowed):
        from tests.test_seher_detect import _FakeGame
        self._mk_game = lambda: _FakeGame(
            fx['seher_start.png'], cross,
            ['sieg'] * 5 + ['niederlage'] * 2 + ['remis'] * 2)
        self.fx = fx
        self.games_allowed = games_allowed
        self.state = 'idle'
        self.game = None
        self.char_switched = False
        self.offset_x = 1000
        self.offset_y = 500
        # idle-Frame: Belohnungs-Fixture mit wegretuschiertem Popup
        idle = fx['seher_flow_reward.png'].copy()
        idle[250:350, 280:540] = (40, 60, 45)
        self.idle_frame = idle

    def _hit(self, name, x, y):
        rx, ry, rw, rh = self.RECTS[name]
        return rx - 2 <= x <= rx + rw + 2 and ry - 2 <= y <= ry + rh + 2

    def on_key(self, k, ctrl=False):
        if k == 'e' and self.state == 'idle':
            self.state = 'overview'
        elif k == 'esc':
            # Realverhalten: ESC schliesst erst offene Fenster, das
            # Systemmenue erscheint erst aus dem leeren Zustand.
            if self.state in ('overview', 'info', 'confirm'):
                self.state = 'idle'
            elif self.state == 'idle':
                self.state = 'escmenu'

    def on_click(self, sx, sy):
        x, y = sx - self.offset_x, sy - self.offset_y
        if self.state == 'overview' and self._hit('seherlabel', x, y):
            self.state = 'info'
        elif self.state == 'info' and self._hit('start', x, y):
            self.state = 'confirm'
        elif self.state == 'confirm' and self._hit('ja', x, y):
            if self.games_allowed > 0:
                self.games_allowed -= 1
                self.game = self._mk_game()
                self.state = 'game'
            else:
                self.state = 'info'   # Spiel startet nicht (kein Vorrat)
        elif self.state == 'reward' and self._hit('ok', x, y):
            self.state = 'idle'
        elif self.state == 'escmenu' and self._hit('charwechsel', x, y):
            self.char_switched = True
        elif self.state == 'game':
            self.game.on_click(sx, sy)

    def get_screenshot(self):
        if self.state == 'game':
            frame = self.game.get_screenshot()
            if self.game.over:
                self.state = 'reward'
                return self.fx['seher_flow_reward.png'].copy()
            return frame
        return {
            'idle': self.idle_frame,
            'overview': self.fx['seher_flow_overview_multi.png'],
            'info': self.fx['seher_flow_info_busy.png'],
            'confirm': self.fx['seher_flow_confirm_busy.png'],
            'reward': self.fx['seher_flow_reward.png'],
            'escmenu': self.fx['seher_flow_escmenu.png'],
        }[self.state].copy()


def _fast_timing(monkeypatch, sr):
    monkeypatch.setattr(sr, 'POLL_S', 0.001)
    monkeypatch.setattr(sr, 'STABLE_NEEDED', 1)
    monkeypatch.setattr(sr, 'READY_TIMEOUT_S', 1.0)
    monkeypatch.setattr(sr, 'COMMIT_TIMEOUT_S', 1.0)
    monkeypatch.setattr(sr, 'SCORE_TIMEOUT_S', 1.0)
    monkeypatch.setattr(sr, 'WINDOW_GONE_S', 0.5)
    monkeypatch.setattr(sr, 'FLOW_STEP_TIMEOUT_S', 0.5)
    monkeypatch.setattr(sr, 'GAME_APPEAR_TIMEOUT_S', 0.4)
    monkeypatch.setattr(sr, 'REWARD_WAIT_S', 0.5)
    monkeypatch.setattr(sr, 'FLOW_PACE_S', 0)


def test_session_two_games_then_depleted_char_switch(fx, monkeypatch,
                                                     tmp_path):
    """Voller Ablauf: 2 Spiele starten+spielen+Belohnung, dann Vorrat leer
    -> sauberes Ende + Endaktion Charakterwechsel."""
    import cv2
    from interface import seher_runner as sr
    cross = cv2.imread(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'seher', 'templates', 'cross.png'), cv2.IMREAD_COLOR)
    sim = _SessionSim(fx, cross, games_allowed=2)
    pdi = _SessionPDI(sim)

    monkeypatch.setattr(sr, '_input', pdi)
    monkeypatch.setattr(sr, 'WindowCapture', lambda name: sim)
    _fast_timing(monkeypatch, sr)
    monkeypatch.setattr(sr, 'results_path',
                        lambda: str(tmp_path / 'results.jsonl'))
    monkeypatch.setattr(sr, '_save_debug_frame', lambda img, step: None)

    ses = sr.run_seher_session({}, order='desc', max_games=0,
                               after_action='char')

    assert ses.games_played == 2
    assert ses.stopped_reason == 'depleted'
    assert ses.after_action_done
    assert sim.char_switched
    # Muenzen: 5:2 -> 5 + 3 Bonus = 8 pro Spiel
    assert ses.total_coins == 16


def test_session_max_games_limit(fx, monkeypatch, tmp_path):
    import cv2
    from interface import seher_runner as sr
    cross = cv2.imread(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'seher', 'templates', 'cross.png'), cv2.IMREAD_COLOR)
    sim = _SessionSim(fx, cross, games_allowed=99)
    pdi = _SessionPDI(sim)
    monkeypatch.setattr(sr, '_input', pdi)
    monkeypatch.setattr(sr, 'WindowCapture', lambda name: sim)
    _fast_timing(monkeypatch, sr)
    monkeypatch.setattr(sr, 'results_path',
                        lambda: str(tmp_path / 'results.jsonl'))

    ses = sr.run_seher_session({}, order='asc', max_games=1,
                               after_action='stop')
    assert ses.games_played == 1
    assert ses.stopped_reason == 'max_games'
    assert not ses.after_action_done


def test_session_flow_error_stops_hard(fx, monkeypatch, tmp_path):
    """Eventuebersicht erscheint nie -> Fehler-Stopp OHNE Endaktion."""
    from interface import seher_runner as sr

    class _DeadSim:
        offset_x = 0
        offset_y = 0

        def __init__(self, frame):
            self.frame = frame
            self.escmenu_opened = False

        def get_screenshot(self):
            return self.frame.copy()

    class _DeadPDI:
        PAUSE = 0.1

        def click(self, x, y, button='left'):
            pass

        def keyDown(self, k):
            pass

        def keyUp(self, k):
            pass

        def press(self, k):
            pass

        def moveTo(self, x, y):
            pass

    sim = _DeadSim(np.zeros((600, 800, 3), dtype=np.uint8))
    monkeypatch.setattr(sr, '_input', _DeadPDI())
    monkeypatch.setattr(sr, 'WindowCapture', lambda name: sim)
    _fast_timing(monkeypatch, sr)
    monkeypatch.setattr(sr, '_save_debug_frame', lambda img, step: None)

    ses = sr.run_seher_session({}, after_action='char')
    assert ses.stopped_reason == 'fehler'
    assert ses.error_step == 'eventuebersicht'
    assert not ses.after_action_done


def test_looks_like_game_window_at_left_edge_no_wraparound(fx):
    """Fenster fast am linken Bildrand: Slot-Offsets werden negativ.
    Ein roher Negativ-Index wuerde vom RECHTEN Bildrand lesen (NumPy-
    Wraparound) und zufaellig True liefern -- mit Clamping ist das
    Ergebnis deterministisch False (Slots nicht lesbar) und crashfrei."""
    base = fx['seher_start.png']
    shifted = np.zeros_like(base)
    cut = 294                      # Anker rutscht von x=304 auf x=10
    shifted[:, :800 - cut] = base[:, cut:]
    ok, pos, _ncc = detect.find_anchor(shifted)
    assert ok and pos[0] < G.MY_WHITE_SLOTS[0][0] * -1  # Offsets negativ
    assert flow.looks_like_game(shifted) is False
    # und die volle Beobachtung darf ebenfalls nicht crashen
    obs = detect.observe(shifted)
    assert obs.ok


def test_session_recovers_from_dropped_ansehen_click(fx, monkeypatch,
                                                     tmp_path):
    """Kern des 1.2.1-Fixes: Wird der ERSTE Ansehen-Klick von DirectInput
    verschluckt, muss _click_until ihn wiederholen und das Spiel trotzdem
    starten (statt mit 'start_knopf' zu sterben wie im 23:31-Log)."""
    import cv2
    from interface import seher_runner as sr
    cross = cv2.imread(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'seher', 'templates', 'cross.png'), cv2.IMREAD_COLOR)
    sim = _SessionSim(fx, cross, games_allowed=1)

    # Klick-Filter: jeder erste Klick auf ein Flow-Ziel wird "verschluckt".
    dropped = {'count': 0}
    real_on_click = sim.on_click

    def flaky_on_click(sx, sy):
        if sim.state in ('overview', 'info', 'confirm') and dropped['count'] < 1:
            dropped['count'] += 1
            return  # ersten Flow-Klick fallen lassen
        real_on_click(sx, sy)
    sim.on_click = flaky_on_click

    pdi = _SessionPDI(sim)
    monkeypatch.setattr(sr, '_input', pdi)
    monkeypatch.setattr(sr, 'WindowCapture', lambda name: sim)
    _fast_timing(monkeypatch, sr)
    monkeypatch.setattr(sr, 'results_path',
                        lambda: str(tmp_path / 'results.jsonl'))
    monkeypatch.setattr(sr, '_save_debug_frame', lambda img, step: None)

    ses = sr.run_seher_session({}, order='desc', max_games=1,
                               after_action='stop')
    assert dropped['count'] == 1          # ein Klick WURDE verschluckt
    assert ses.games_played == 1          # ... und der Retry hat es gerettet
    assert ses.stopped_reason == 'max_games'
