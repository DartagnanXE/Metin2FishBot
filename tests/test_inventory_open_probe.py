# -*- coding: utf-8 -*-
"""Tests for the inventory open-state probe (inventory.open_probe).

Covers the three layers:

  * probe_open decision logic on synthetic canvases (templates stamped at the
    calibration tab positions; one tab "active" = overwritten -> still open;
    two distorted -> closed; landscape/zeros -> closed),
  * ensure_inventory_open orchestration (press only when closed, toggle
    semantics, tooltip self-heal, abort after max presses, probe-unavailable
    ``None`` passthrough),
  * REAL captures (skipUnless, like test_inventory_smoke_real): the open
    reference shots -- including the page-II-active one -- must read OPEN, the
    closed fishing shots must read CLOSED.
"""

import os
import unittest

try:
    import numpy as np
except Exception:                       # pragma: no cover
    np = None

try:
    from PIL import Image
except Exception:                       # pragma: no cover
    Image = None

from inventory import open_probe
from inventory.constants import DEFAULT_CALIBRATION, PAGES

try:
    from tests._inv_synth import stamp_open_tabs
except Exception:                       # pragma: no cover - direct invocation
    from _inv_synth import stamp_open_tabs

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Real reference captures (open). Outside-repo shots skip when absent.
_OPEN_SHOTS = {
    'page_I_active_calib': os.path.join(
        _REPO_ROOT, 'FischOCR', 'inventar_offen_seiteI_kalibrierung.png'),
    'page_II_active': os.path.join(_REPO_ROOT, '..', 'itemwegwerfmeldung.png'),
    'no_glow': os.path.join(_REPO_ROOT, '..', 'FischOhneLeuchten.png'),
    'glow': os.path.join(_REPO_ROOT, '..', 'FischLeuchten.png'),
}

#: Real fishing captures (inventory CLOSED) -- strong negatives.
_CLOSED_SHOTS = {
    'fishing_lachs': os.path.join(_REPO_ROOT, 'FischOCR', 'Lachs.png'),
    'fishing_thunfisch': os.path.join(_REPO_ROOT, 'FischOCR', 'thunfisch.png'),
}


def _load_client_bgr(path):
    """Load a reference shot as a BGR client-area array (strip full-window)."""
    img = np.asarray(Image.open(path).convert('RGB'))
    if img.shape[0] > 615:  # full-window capture: 1px border + ~31px titlebar
        img = img[31:, 1:]
    return img[:, :, ::-1].copy()


def _open_canvas():
    """A synthetic full-size BGR frame that probes OPEN (all 4 tabs stamped)."""
    return stamp_open_tabs(np.zeros((601, 800, 3), dtype=np.uint8))


def _cover_tab(frame, label, value=200):
    """Overwrite one tab's patch (simulates the ACTIVE highlight / a tooltip).

    Covers EXACTLY the patch box (no padding): a wider cover would bleed into
    the +-shift search window of the NEIGHBOURING tab (39px pitch vs 38px
    patch) and distort that tab too -- the real active highlight also only
    recolours the tab's own face.
    """
    x0, x1, y0, y1 = open_probe.TAB_PATCH_BOX
    cx, cy = DEFAULT_CALIBRATION['tabs'][label]
    frame[cy + y0:cy + y1, cx + x0:cx + x1] = value
    return frame


@unittest.skipUnless(np is not None and Image is not None,
                     'numpy/PIL required')
class TestProbeOpenDecision(unittest.TestCase):
    def test_templates_load_and_match_their_own_canvas(self):
        templates = open_probe.load_tab_templates()
        self.assertIsNotNone(templates)
        self.assertEqual(set(templates), set(PAGES))
        res = open_probe.probe_open(_open_canvas(), DEFAULT_CALIBRATION)
        self.assertIsNotNone(res)
        is_open, matches, dists = res
        self.assertTrue(is_open)
        self.assertEqual(matches, 4)
        for label in PAGES:
            self.assertLessEqual(dists[label], open_probe.TAB_MATCH_MAD_MAX)

    def test_one_active_tab_still_open(self):
        # Live reality: ONE tab is always highlighted and does not match its
        # inactive template -> 3 matches is the open maximum and must pass.
        for label in PAGES:
            frame = _cover_tab(_open_canvas(), label)
            res = open_probe.probe_open(frame, DEFAULT_CALIBRATION)
            self.assertTrue(res[0], 'active tab %s broke the probe' % label)
            self.assertEqual(res[1], 3)

    def test_two_distorted_tabs_read_closed(self):
        # Active tab + e.g. a tooltip over a second tab -> below OPEN_MIN_MATCHES.
        frame = _cover_tab(_cover_tab(_open_canvas(), 'I'), 'III')
        res = open_probe.probe_open(frame, DEFAULT_CALIBRATION)
        self.assertFalse(res[0])
        self.assertEqual(res[1], 2)

    def test_blank_frame_reads_closed(self):
        res = open_probe.probe_open(
            np.zeros((601, 800, 3), dtype=np.uint8), DEFAULT_CALIBRATION)
        self.assertFalse(res[0])
        self.assertEqual(res[1], 0)

    def test_small_frame_reads_closed_not_crash(self):
        # Tabs off-image -> worst distance everywhere -> closed, never a raise.
        res = open_probe.probe_open(
            np.zeros((100, 100, 3), dtype=np.uint8), DEFAULT_CALIBRATION)
        self.assertFalse(res[0])

    def test_none_frame_is_unavailable(self):
        self.assertIsNone(open_probe.probe_open(None, DEFAULT_CALIBRATION))

    def test_shift_tolerance(self):
        # A +-2px client offset between sessions must still match (shift search).
        frame = np.zeros((601, 800, 3), dtype=np.uint8)
        x0, x1, y0, y1 = open_probe.TAB_PATCH_BOX
        templates = open_probe.load_tab_templates()
        for label, tmpl in templates.items():
            cx, cy = DEFAULT_CALIBRATION['tabs'][label]
            frame[cy + y0 + 2:cy + y1 + 2,
                  cx + x0 - 2:cx + x1 - 2] = tmpl.astype('uint8')
        res = open_probe.probe_open(frame, DEFAULT_CALIBRATION)
        self.assertTrue(res[0])
        self.assertEqual(res[1], 4)


@unittest.skipUnless(np is not None and Image is not None,
                     'numpy/PIL required')
class TestEnsureInventoryOpen(unittest.TestCase):
    """Orchestration against a tiny toggle simulator of the game."""

    def _game(self, start_open):
        """Returns (state, capture_fn, press_fn, presses) of a toggle 'game'."""
        state = {'open': start_open}
        presses = []
        open_frame = _open_canvas()
        closed_frame = np.zeros((601, 800, 3), dtype=np.uint8)

        def capture():
            return open_frame if state['open'] else closed_frame

        def press():
            presses.append(1)
            state['open'] = not state['open']  # the TOGGLE

        return state, capture, press, presses

    def test_already_open_no_press(self):
        _, capture, press, presses = self._game(start_open=True)
        ok = open_probe.ensure_inventory_open(
            capture, press, DEFAULT_CALIBRATION, sleep_fn=lambda s: None)
        self.assertTrue(ok)
        self.assertEqual(len(presses), 0)   # THE fix: no blind toggle press

    def test_closed_pressed_once(self):
        _, capture, press, presses = self._game(start_open=False)
        ok = open_probe.ensure_inventory_open(
            capture, press, DEFAULT_CALIBRATION, sleep_fn=lambda s: None)
        self.assertTrue(ok)
        self.assertEqual(len(presses), 1)

    def test_tooltip_self_heal(self):
        # Bag OPEN but a tooltip distorts a second tab -> first probe reads
        # closed -> press CLOSES it (clean closed) -> press re-opens (tooltip
        # gone after the cursor park in the real flow) -> verified open.
        state = {'open': True, 'tooltip': True}
        presses = []
        closed_frame = np.zeros((601, 800, 3), dtype=np.uint8)

        def capture():
            if not state['open']:
                return closed_frame
            frame = _open_canvas()
            _cover_tab(frame, 'II')                  # the active tab
            if state['tooltip']:
                _cover_tab(frame, 'IV')              # the tooltip
            return frame

        def press():
            presses.append(1)
            state['open'] = not state['open']
            state['tooltip'] = False                 # cursor moved away

        ok = open_probe.ensure_inventory_open(
            capture, press, DEFAULT_CALIBRATION, sleep_fn=lambda s: None)
        self.assertTrue(ok)
        self.assertEqual(len(presses), 2)

    def test_never_opens_aborts_false(self):
        # The hotkey does nothing (wrong binding / chat focus) -> after
        # MAX_TOGGLE_PRESSES the flow must return False (caller aborts; no
        # tab/drag click may ever fire on a closed bag).
        closed_frame = np.zeros((601, 800, 3), dtype=np.uint8)
        presses = []
        ok = open_probe.ensure_inventory_open(
            lambda: closed_frame, lambda: presses.append(1),
            DEFAULT_CALIBRATION, sleep_fn=lambda s: None)
        self.assertFalse(ok)
        self.assertEqual(len(presses), open_probe.MAX_TOGGLE_PRESSES)

    def test_probe_unavailable_returns_none(self):
        # capture yields None (no frame) -> "cannot tell" -> None, zero presses.
        presses = []
        ok = open_probe.ensure_inventory_open(
            lambda: None, lambda: presses.append(1),
            DEFAULT_CALIBRATION, sleep_fn=lambda s: None)
        self.assertIsNone(ok)
        self.assertEqual(len(presses), 0)

    def test_park_fn_called_and_nonfatal(self):
        parks = []

        def park():
            parks.append(1)
            raise RuntimeError('park down')          # must be swallowed

        _, capture, press, _presses = self._game(start_open=True)
        ok = open_probe.ensure_inventory_open(
            capture, press, DEFAULT_CALIBRATION,
            park_fn=park, sleep_fn=lambda s: None)
        self.assertTrue(ok)
        self.assertEqual(len(parks), 1)


def _shots_present(shots):
    return all(os.path.isfile(p) for p in shots.values())


@unittest.skipUnless(
    np is not None and Image is not None and _shots_present(_OPEN_SHOTS)
    and _shots_present(_CLOSED_SHOTS),
    'real reference shots not present')
class TestProbeOnRealShots(unittest.TestCase):
    def test_open_shots_read_open(self):
        for key, path in _OPEN_SHOTS.items():
            res = open_probe.probe_open(
                _load_client_bgr(path), DEFAULT_CALIBRATION)
            self.assertIsNotNone(res, key)
            self.assertTrue(res[0], '%s must read OPEN, dists=%r'
                            % (key, res[2]))
            # Exactly one ACTIVE tab on a real open shot -> exactly 3 matches.
            self.assertEqual(res[1], 3, key)

    def test_closed_shots_read_closed(self):
        for key, path in _CLOSED_SHOTS.items():
            res = open_probe.probe_open(
                _load_client_bgr(path), DEFAULT_CALIBRATION)
            self.assertIsNotNone(res, key)
            self.assertFalse(res[0], '%s must read CLOSED, dists=%r'
                             % (key, res[2]))
            self.assertEqual(res[1], 0, key)


if __name__ == '__main__':
    unittest.main()
