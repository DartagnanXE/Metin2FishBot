"""Pure Erkennung des Start-/End-Flows (Eventuebersicht -> Spiel -> OK).

Alle Elemente werden positionsunabhaengig per Template-NCC im Vollbild
gesucht (Fenster wandern). Kalibriert + verifiziert in
tools_seher/calibrate_flow.py: Self-Match 1.0, Busy-Varianten >=0.9999,
Negativ-Fixtures <=0.71. WICHTIG: das Event-Listen-Label traegt den
Plate-Rahmen im Template, weil der reine Schriftzug auch die
Fenstertitel "Seherwettstreit" matchen wuerde.
"""
import os

import cv2
import numpy as np

from seher import geometry as G
from seher.detect import _resource_dir, _roi, find_anchor

# 0.82: schlechtester False-Positive der Kalibrierung war 0.71 (Ja-Knopf auf
# dem Info-Fenster) -> 0.82 haelt +0.11 Abstand UND gibt Spielraum fuer
# Client-Rendering-Unterschiede (andere AA/Patch-Version => echte Treffer
# koennen statt 1.0 mal ~0.85 liefern). Per diagnose() ist jeder Knapp-
# daneben-Fall im Log sichtbar und gezielt nachjustierbar.
FLOW_NCC_MIN = 0.82
ROW_TOLERANCE_PX = 12

_cache = {}


def _tpl(name):
    if name not in _cache:
        path = os.path.join(_resource_dir(), name + '.png')
        _cache[name] = cv2.imread(path, cv2.IMREAD_COLOR)
    return _cache[name]


def find(bgr, name, thresh=FLOW_NCC_MIN):
    """Bestes Vorkommen des Templates. -> (ok, (x, y), ncc)."""
    tpl = _tpl(name)
    if tpl is None or bgr is None:
        return (False, (0, 0), 0.0)
    if bgr.shape[0] < tpl.shape[0] or bgr.shape[1] < tpl.shape[1]:
        return (False, (0, 0), 0.0)
    res = cv2.matchTemplate(bgr, tpl, cv2.TM_CCOEFF_NORMED)
    _mn, mx, _ml, loc = cv2.minMaxLoc(res)
    return (mx >= thresh, (int(loc[0]), int(loc[1])), float(mx))


def center(name, pos):
    """Klick-Zentrum eines gefundenen Templates."""
    tpl = _tpl(name)
    h, w = tpl.shape[:2]
    return (pos[0] + w // 2, pos[1] + h // 2)


def find_click(bgr, name, thresh=FLOW_NCC_MIN):
    """Wie find(), liefert aber direkt das Klick-Zentrum."""
    ok, pos, ncc = find(bgr, name, thresh)
    return (ok, center(name, pos) if ok else (0, 0), ncc)


def find_ansehen_for_seher(bgr):
    """Sucht die Seherwettstreit-Zeile in der Eventuebersicht und das
    zugehoerige "Ansehen" (es kann mehrere Events mit je eigenem
    "Ansehen" geben -> Zeilen-Matching ueber die Mittelpunkts-Hoehe).

    -> (ok, klick_zentrum, debug_dict)
    """
    dbg = {}
    ok_l, pos_l, ncc_l = find(bgr, 'flow_seher_label')
    dbg['label_ncc'] = round(ncc_l, 4)
    if not ok_l:
        return (False, (0, 0), dbg)
    lab = _tpl('flow_seher_label')
    label_cy = pos_l[1] + lab.shape[0] // 2
    ans = _tpl('flow_ansehen')
    res = cv2.matchTemplate(bgr, ans, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(res >= FLOW_NCC_MIN)
    best = None
    for y, x in zip(ys.tolist(), xs.tolist()):
        cy = y + ans.shape[0] // 2
        if abs(cy - label_cy) <= ROW_TOLERANCE_PX:
            ncc = float(res[y, x])
            if best is None or ncc > best[2]:
                best = (x, y, ncc)
    dbg['candidates'] = len(ys)
    if best is None:
        return (False, (0, 0), dbg)
    dbg['ansehen_ncc'] = round(best[2], 4)
    return (True, center('flow_ansehen', (best[0], best[1])), dbg)


def looks_like_game(bgr):
    """True, wenn der Anker-Treffer das SPIELFENSTER ist (nicht das
    gleichbetitelte Info-Fenster): die 4 weissen Gegner-Rueckseiten-Slots
    muessen hell sein ODER ein rotes Kreuz tragen."""
    ok, anchor, _ncc = find_anchor(bgr)
    if not ok:
        return False
    good = 0
    for sx, sy in G.OPP_WHITE_SLOTS:
        # _roi clampt an den Bildrand -- ein roher Negativ-Index wuerde bei
        # einem Fenster nahe der linken Bildkante vom RECHTEN Rand lesen!
        roi = _roi(bgr, anchor, sx, sy, G.CARD_W, G.CARD_H)
        if roi.size == 0:
            continue
        b = roi.astype(np.int16)
        bright = float(b.mean()) > 140
        red = int(((b[:, :, 2] > 140) & (b[:, :, 1] < 90)
                   & (b[:, :, 0] < 90)).sum()) >= G.CROSS_RED_MIN
        if bright or red:
            good += 1
    return good >= 3


ALL_FLOW_TEMPLATES = (
    'flow_event_title', 'flow_seher_label', 'flow_ansehen', 'flow_start_btn',
    'flow_ja_btn', 'flow_reward_ok', 'flow_menu_charwechsel',
    'flow_menu_beenden')


def scan_state(bgr):
    """Debug-Uebersicht: welche Flow-Elemente sind gerade sichtbar."""
    out = {}
    for name in ('flow_event_title', 'flow_seher_label', 'flow_start_btn',
                 'flow_ja_btn', 'flow_reward_ok', 'flow_menu_charwechsel'):
        ok, _pos, ncc = find(bgr, name)
        out[name] = round(ncc, 3) if ok else 0.0
    out['game'] = looks_like_game(bgr)
    return out


def diagnose(bgr):
    """ROHE Best-NCC ALLER Flow-Templates (auch unter der Schwelle!) +
    Anker/Spielfeld. Macht jeden Flow-Fehler selbst-diagnostizierbar: ein
    Wert knapp unter der Schwelle (z.B. Start-Knopf 0.83) zeigt einen
    Client-Rendering-Unterschied; alle Werte niedrig zeigen, dass der
    erwartete Bildschirm gar nicht da ist (Klick verschluckt / falsches
    Fenster). Threshold zum Vergleich: FLOW_NCC_MIN."""
    out = {'_thresh': FLOW_NCC_MIN}
    for name in ALL_FLOW_TEMPLATES:
        tpl = _tpl(name)
        if tpl is None or bgr is None \
                or bgr.shape[0] < tpl.shape[0] or bgr.shape[1] < tpl.shape[1]:
            out[name] = -1.0
            continue
        res = cv2.matchTemplate(bgr, tpl, cv2.TM_CCOEFF_NORMED)
        out[name] = round(float(res.max()), 3)
    aok, _apos, ancc = find_anchor(bgr)
    out['anchor'] = round(ancc, 3)
    out['game'] = looks_like_game(bgr)
    return out
