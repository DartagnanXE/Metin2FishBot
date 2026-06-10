"""Live-Runner fuer den Seherwettstreit-Autoplayer.

Spielt EIN Spiel (9 Runden, bzw. die Restrunden bei Uebernahme eines
laufenden Spiels) gegen den Spiel-Computer und trackt ALLES mit, was
erkennbar ist (Debug-Konsole + JSONL-Protokoll fuer spaetere Auswertung
der KI-Zufaelligkeit).

Ablauf pro Runde (Erkennungsmethoden benchmark-belegt, tools_seher/):
1. Vorzustand sichern: Kreuz-Zaehler beider Gegner-Reihen + Score-Crops.
2. Karte klicken (Klick-Quittung: "Du legst"-Slot aendert sich; Retry).
3. Auswertung abwarten: neues Kreuz in einer GEGNER-Reihe (liefert
   zugleich die Farbe der Gegnerkarte).
4. Resultat per Score-Box-Bilddiff: Gegner-Box geaendert -> Niederlage,
   eigene -> Sieg, keine -> Remis (kein OCR noetig).
5. Spielende: Fenster (Anker) verschwindet -> Spiel beendet, Bilanz.

Reihenfolge der eigenen Karten ist mathematisch beweisbar egal (gegen
einen Zufallsgegner bei verdeckter Wahl hat JEDE Strategie denselben
Erwartungswert) -- waehlbar ist sie trotzdem (Tracking-Vielfalt).

Zusaetzlich: run_seher_session() spielt in DAUERSCHLEIFE -- startet jedes
Spiel selbst (Strg+E -> Eventuebersicht -> Seherwettstreit-Zeile ->
Ansehen -> Start -> Ja), holt die Belohnung ab (OK-Knopf) und stoppt
nach X Spielen / bei leerem Vorrat / per Stop -- optional gefolgt von
Charakterwechsel oder Client-Beenden (ESC-Menue). Jeder Flow-Schritt hat
einen erwarteten Bildzustand; passt er nicht -> Debug-Frame als PNG +
harter Stopp (keine blinden Klicks).
"""
import json
import random
import time
from dataclasses import dataclass, field

import constants
from debuglog import log
from i18n import t
from interface.config.paths import sibling_path
from seher import detect, geometry as G

# -- soft imports (live deps; module stays importable headless) -------------
try:  # pragma: no cover - nur auf dem Windows-Build vorhanden
    import pydirectinput
except Exception:  # pragma: no cover
    pydirectinput = None

try:  # pragma: no cover
    from windowcapture import WindowCapture
except Exception:  # pragma: no cover
    WindowCapture = None


RESULTS_FILENAME = 'seherwettstreit_results.jsonl'

# Timing (Sekunden). Auswertung dauert laut Nutzer ~3-4 s.
# Pacing (User-Spez): 4 s Kadenz zwischen den Zuegen (sichtbarer Timer im
# Bot), 0.75 s Render-Floor zwischen allen Flow-Schritten -- dazwischen
# bleibt alles event-getrieben (weiter, SOBALD der Folgezustand erkannt ist).
MOVE_PACE_S = 4.0
FLOW_PACE_S = 0.75
POLL_S = 0.15
CLICK_CONFIRM_S = 2.5
CLICK_RETRIES = 3
RESOLVE_TIMEOUT_S = 10.0
SCORE_SETTLE_S = 0.45
WINDOW_FIND_S = 10.0
WINDOW_GONE_S = 20.0

# "Du legst"-Slot (rechtes Panel, unten) als Klick-Quittung.
PLAYED_ME_ROI = (145, 240, 64, 52)


@dataclass
class RoundRecord:
    round_no: int
    card: int
    opp_color: str = ''      # 'schwarz' | 'weiss' | '?'
    result: str = ''         # 'sieg' | 'niederlage' | 'remis' | 'unklar'
    click_retries: int = 0
    t_click_s: float = 0.0
    t_resolve_s: float = 0.0
    anchor_ncc: float = 0.0
    cross_px: int = 0
    message_px: int = 0


@dataclass
class GameResult:
    ok: bool = False
    error: str = ''
    aborted: bool = False
    takeover_cards: int = 0
    order: str = ''
    rounds: list = field(default_factory=list)
    points_me: int = 0
    points_opp: int = 0
    coins: int = 0
    window_gone: bool = False
    duration_s: float = 0.0


def results_path():
    return sibling_path(RESULTS_FILENAME)


def _append_jsonl(record):
    try:
        with open(results_path(), 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + '\n')
    except Exception as exc:
        log.error(t('seher.results_write_failed'), exc=exc)


def _order_cards(order):
    cards = list(range(9))
    if order == 'desc':
        cards.reverse()
    elif order == 'random':
        random.shuffle(cards)
    return cards


def _wait(abort_fn, seconds):
    """Abbrechbarer Sleep (5-ms-Slices)."""
    end = time.time() + seconds
    while time.time() < end:
        if abort_fn():
            return False
        time.sleep(0.005)
    return True


def run_seher_game(cfg, *, abort_fn=None, order='desc', debug=True,
                   wincap=None, on_tick=None):
    """Spielt das offene Seherwettstreit-Spiel zu Ende. Blockiert.

    on_tick(phase, remaining): Live-Timer-Callback ('zug' mit Rest-
    sekunden der 4-s-Kadenz, 'auswertung' waehrend der Erkennung,
    'idle' am Ende). Wird vom Worker-Thread gerufen.
    """
    from seher import flow
    abort_fn = abort_fn or (lambda: False)

    def tick(phase, remaining=None):
        if on_tick is not None:
            try:
                on_tick(phase, remaining)
            except Exception:
                pass
    t0 = time.time()
    res = GameResult(order=order)

    if pydirectinput is None or WindowCapture is None:
        res.error = 'deps'
        log.event('-', t('seher.deps_missing'))
        return res
    pydirectinput.PAUSE = 0.05  # reiner Maus-Flow (Regel: Maus 0.05)

    if wincap is None:
        try:
            wincap = WindowCapture(constants.GAME_NAME)
        except Exception as exc:
            res.error = 'window'
            log.error(t('seher.no_game_window'), exc=exc)
            return res

    def frame():
        return wincap.get_screenshot()

    def screen_xy(anchor, rel_x, rel_y):
        return (wincap.offset_x + anchor[0] + rel_x,
                wincap.offset_y + anchor[1] + rel_y)

    # -- 1. Spielfenster finden (Anker UND Spielfeld-Validierung: das
    # Info-Fenster traegt denselben Titel!) ---------------------------------
    obs = None
    img = None
    deadline = time.time() + WINDOW_FIND_S
    while time.time() < deadline and not abort_fn():
        img = frame()
        obs = detect.observe(img)
        if obs.ok and flow.looks_like_game(img):
            break
        obs = None
        time.sleep(POLL_S)
    if obs is None or not obs.ok:
        res.error = 'seher_window'
        log.event('-', t('seher.window_not_found'))
        try:
            _log_diagnosis(wincap, 'spielfenster', img)
        except Exception:
            pass
        return res

    log.event('0', t('seher.window_found', x=obs.anchor[0], y=obs.anchor[1],
                     ncc='{:.3f}'.format(obs.ncc)))

    played = set(obs.my_crossed)
    res.takeover_cards = len(played)
    if played:
        log.event('-', t('seher.takeover', n=len(played),
                         cards=','.join(str(c) for c in sorted(played))))
    deck = [c for c in _order_cards(order) if c not in played]
    last_click_ts = 0.0

    # -- 2. Runden spielen -------------------------------------------------
    for card in deck:
        if abort_fn():
            res.aborted = True
            break
        # 4-s-Kadenz seit dem letzten Zug (sichtbarer Countdown); die
        # Auswertung selbst wurde bereits event-getrieben erkannt.
        wait_until = last_click_ts + MOVE_PACE_S
        while not abort_fn():
            remaining = wait_until - time.time()
            if remaining <= 0:
                break
            tick('zug', max(0.0, remaining))
            time.sleep(min(0.1, remaining))
        tick('zug', 0.0)
        if abort_fn():
            res.aborted = True
            break
        round_no = 9 - len(deck) + deck.index(card) + 1
        rec = RoundRecord(round_no=round_no, card=card)

        img = frame()
        obs = detect.observe(img)
        if not obs.ok:
            log.event('-', t('seher.window_lost', round=round_no))
            res.window_gone = True
            break
        rec.anchor_ncc = obs.ncc
        pre_b = obs.opp_black_crossed
        pre_w = obs.opp_white_crossed
        pre_score_opp = detect.score_crop(img, obs.anchor, 'opp')
        pre_score_me = detect.score_crop(img, obs.anchor, 'me')
        x, y, w, h = PLAYED_ME_ROI
        pre_played = img[obs.anchor[1] + y:obs.anchor[1] + y + h,
                         obs.anchor[0] + x:obs.anchor[0] + x + w].copy()

        # -- Klick mit Quittung + Retry --------------------------------
        t_click = time.time()
        last_click_ts = t_click
        confirmed = False
        for attempt in range(1, CLICK_RETRIES + 1):
            rec.click_retries = attempt
            cx, cy = G.click_center_of_value(card)
            sx, sy = screen_xy(obs.anchor, cx, cy)
            if debug:
                log.event('0', t('seher.click', card=card, x=sx, y=sy,
                                 attempt=attempt))
            pydirectinput.click(sx, sy)
            try:
                pydirectinput.moveTo(wincap.offset_x + PARK_POINT[0],
                                     wincap.offset_y + PARK_POINT[1])
            except Exception:
                pass
            confirm_end = time.time() + CLICK_CONFIRM_S
            while time.time() < confirm_end and not abort_fn():
                img2 = frame()
                o2 = detect.observe(img2)
                if not o2.ok:
                    break
                cur_played = img2[o2.anchor[1] + y:o2.anchor[1] + y + h,
                                  o2.anchor[0] + x:o2.anchor[0] + x + w]
                if (card in o2.my_crossed
                        or detect.crops_differ(pre_played, cur_played)
                        or o2.opp_black_crossed + o2.opp_white_crossed
                        > pre_b + pre_w):
                    confirmed = True
                    break
                time.sleep(POLL_S)
            if confirmed or abort_fn():
                break
        rec.t_click_s = round(time.time() - t_click, 3)
        if abort_fn():
            res.aborted = True
            res.rounds.append(rec.__dict__)
            break
        if not confirmed:
            log.event('-', t('seher.click_unconfirmed', card=card))

        # -- Auswertung abwarten: neues Kreuz beim Gegner ----------------
        t_res = time.time()
        color = '?'
        resolved = False
        while time.time() - t_res < RESOLVE_TIMEOUT_S and not abort_fn():
            tick('auswertung')
            img3 = frame()
            o3 = detect.observe(img3)
            if not o3.ok:
                res.window_gone = True
                break
            if o3.opp_black_crossed > pre_b:
                color, resolved = 'schwarz', True
            elif o3.opp_white_crossed > pre_w:
                color, resolved = 'weiss', True
            if resolved:
                rec.cross_px = o3.cross_counts.get(card, 0)
                rec.message_px = o3.message_px
                break
            time.sleep(POLL_S)
        rec.opp_color = color
        rec.t_resolve_s = round(time.time() - t_res, 3)
        if not resolved:
            rec.result = 'unklar'
            res.rounds.append(rec.__dict__)
            if res.window_gone or abort_fn():
                res.aborted = res.aborted or abort_fn()
                break
            log.event('-', t('seher.resolve_timeout', round=round_no))
            continue

        # -- Resultat via Score-Diff (nach kurzem Settle) ----------------
        if not _wait(abort_fn, SCORE_SETTLE_S):
            res.aborted = True
            res.rounds.append(rec.__dict__)
            break
        img4 = frame()
        o4 = detect.observe(img4)
        if o4.ok:
            opp_chg = detect.crops_differ(
                pre_score_opp, detect.score_crop(img4, o4.anchor, 'opp'))
            me_chg = detect.crops_differ(
                pre_score_me, detect.score_crop(img4, o4.anchor, 'me'))
            if me_chg and not opp_chg:
                rec.result = 'sieg'
                res.points_me += 1
            elif opp_chg and not me_chg:
                rec.result = 'niederlage'
                res.points_opp += 1
            elif not opp_chg and not me_chg:
                rec.result = 'remis'
            else:
                rec.result = 'unklar'
        else:
            rec.result = 'unklar'
            res.window_gone = True

        res.rounds.append(rec.__dict__)
        log.event('+' if rec.result == 'sieg' else
                  '-' if rec.result == 'niederlage' else '0',
                  t('seher.round_done', round=round_no, card=card,
                    color=color, result=rec.result,
                    score='{}:{}'.format(res.points_me, res.points_opp)))
        if res.window_gone:
            break

    # -- 3. Spielende: Fenster verschwindet --------------------------------
    if not res.aborted and not res.window_gone:
        deadline = time.time() + WINDOW_GONE_S
        while time.time() < deadline and not abort_fn():
            o = detect.observe(frame())
            if not o.ok:
                res.window_gone = True
                break
            time.sleep(2 * POLL_S)

    tick('idle')
    res.coins = res.points_me + max(res.points_me - res.points_opp, 0)
    res.duration_s = round(time.time() - t0, 2)
    res.ok = not res.aborted and res.error == ''

    record = dict(res.__dict__)
    record['ts'] = time.time()
    _append_jsonl(record)
    log.event('+' if res.points_me > res.points_opp else '0',
              t('seher.game_done', p=res.points_me, g=res.points_opp,
                coins=res.coins, secs=res.duration_s,
                gone='ja' if res.window_gone else 'nein'))
    return res


# ===========================================================================
# Session-Loop: Spiele in Dauerschleife starten, spielen, Belohnung abholen
# ===========================================================================

FLOW_STEP_TIMEOUT_S = 6.0
GAME_APPEAR_TIMEOUT_S = 12.0
REWARD_WAIT_S = 10.0
CTRL_E_RETRIES = 3
CLICK_FLOW_RETRIES = 3   # verschluckte Klicks abfangen (DirectInput-Lektion)


@dataclass
class SessionResult:
    games_played: int = 0
    total_coins: int = 0
    stopped_reason: str = ''     # 'abort'|'max_games'|'depleted'|Fehlercode
    after_action: str = ''
    after_action_done: bool = False
    error_step: str = ''
    duration_s: float = 0.0


def _press_ctrl_e():
    """Strg+E mit expliziten Holds. DirectInput verschluckt Modifier-Combos
    bei zu kurzem Tastendruck (Lektion v1.1.1/.2 -- der erste Strg+E im
    Live-Log von 23:30 wurde gedroppt). Darum jede Phase mit eigenem Hold."""
    old = pydirectinput.PAUSE
    pydirectinput.PAUSE = 0.1
    try:
        pydirectinput.keyDown('ctrl')
        time.sleep(0.06)
        pydirectinput.keyDown('e')
        time.sleep(0.06)
        pydirectinput.keyUp('e')
        time.sleep(0.06)
        pydirectinput.keyUp('ctrl')
    finally:
        pydirectinput.PAUSE = old
    time.sleep(FLOW_PACE_S)


def _press_esc():
    old = pydirectinput.PAUSE
    pydirectinput.PAUSE = 0.1
    try:
        pydirectinput.press('esc')
    finally:
        pydirectinput.PAUSE = old
    time.sleep(FLOW_PACE_S)


# Cursor-Parkpunkt (Client-Koordinaten): neutraler Punkt am linken Rand,
# fern aller Flow-Buttons/Karten. Verhindert Hover-Kontamination: ein Button
# unter dem Cursor rendert im Hover-Zustand und matcht sein Template
# schlechter (gleiches Prinzip wie inventory/hover.park_point).
PARK_POINT = (15, 200)


def _park_cursor(wincap):
    """Cursor von allen Buttons/Karten wegbewegen (reiner MOVE, nie Klick)."""
    try:
        pydirectinput.moveTo(wincap.offset_x + PARK_POINT[0],
                             wincap.offset_y + PARK_POINT[1])
    except Exception:
        pass


def _save_debug_frame(img, step):
    """Fehler-Frame als PNG neben die Config legen (Beweisbild, falls der
    Nutzer es doch schicken kann)."""
    try:
        import cv2
        path = sibling_path('seher_debug_{}.png'.format(step))
        cv2.imwrite(path, img)
        log.event('-', t('seher.debug_frame_saved', path=path))
    except Exception:
        pass


def _log_diagnosis(wincap, step, img=None):
    """KOMPLETTE Selbstdiagnose in die CONSOLE schreiben (der Nutzer kann
    keine Dateien schicken -> alles muss als Text im Log stehen): rohe
    Best-NCC ALLER Flow-Templates (auch unter der Schwelle), Anker,
    Spielfeld-Check, Cursor-Position. Daraus ist die Ursache eindeutig
    ablesbar:
      - alle Werte niedrig  -> erwarteter Bildschirm gar nicht da
        (Klick verschluckt / falsches/zugedecktes Fenster)
      - EIN Wert knapp unter Schwelle (z.B. start=0.83 < 0.85) -> dein
        Client rendert den Knopf minimal anders -> Schwelle/Template-Sache
    """
    from seher import flow
    if img is None:
        img = wincap.get_screenshot()
    d = flow.diagnose(img)
    parts = ['Anker={anchor} Spielfeld={game}'.format(**d)]
    order = ['flow_event_title', 'flow_seher_label', 'flow_ansehen',
             'flow_start_btn', 'flow_ja_btn', 'flow_reward_ok',
             'flow_menu_charwechsel', 'flow_menu_beenden']
    short = {'flow_event_title': 'eventtitel', 'flow_seher_label': 'seherzeile',
             'flow_ansehen': 'ansehen', 'flow_start_btn': 'start',
             'flow_ja_btn': 'ja', 'flow_reward_ok': 'belohnungOK',
             'flow_menu_charwechsel': 'charwechsel',
             'flow_menu_beenden': 'beenden'}
    parts.append(' '.join('{}={}'.format(short[k], d[k]) for k in order))
    try:
        import win32api
        cx, cy = win32api.GetCursorPos()
        parts.append('Cursor=({},{})'.format(cx, cy))
    except Exception:
        pass
    log.event('-', t('seher.diag', step=step,
                     thresh=flow.FLOW_NCC_MIN, body=' | '.join(parts)))
    _save_debug_frame(img, step)


def _click_until(wincap, abort_fn, locate_fn, expect_fn, timeout, label,
                 retries=CLICK_FLOW_RETRIES):
    """Robuster Flow-Klick: lokalisiert das Ziel (locate_fn(img) -> (ok, pt,
    ncc)), klickt es, wartet auf den erwarteten Folgezustand (expect_fn).
    Bleibt der aus -> erneut lokalisieren+klicken (ein Klick kann von
    DirectInput verschluckt werden). Liefert (ok, letzter_frame).

    Ist der erwartete Folgezustand schon da, wird sofort True geliefert
    (idempotent, falls der vorige Schritt schon durchgriff).
    """
    last = wincap.get_screenshot()
    for attempt in range(1, retries + 1):
        if abort_fn():
            return (False, last)
        img = wincap.get_screenshot()
        if expect_fn(img):
            return (True, img)
        ok, pt, ncc = locate_fn(img)
        if ok:
            log.event('0', t('seher.flow_click', label=label,
                             ncc='{:.2f}'.format(ncc), attempt=attempt))
            _click_screen(wincap, pt)
        else:
            log.event('0', t('seher.flow_target_missing', label=label,
                             attempt=attempt))
            _wait(abort_fn, FLOW_PACE_S)  # kurz warten, evtl. rendert noch
        ok2, img2, _ = _wait_for(wincap, abort_fn, expect_fn, timeout)
        if img2 is not None:
            last = img2
        if ok2:
            return (True, last)
    return (False, last)


def _wait_for(wincap, abort_fn, predicate, timeout):
    """Pollt Frames bis predicate(img) wahr/abort/timeout.

    -> (ok, letzter_frame, ergebnis_von_predicate)
    """
    deadline = time.time() + timeout
    img = None
    while time.time() < deadline:
        if abort_fn():
            return (False, img, None)
        img = wincap.get_screenshot()
        got = predicate(img)
        if got:
            return (True, img, got)
        time.sleep(POLL_S)
    return (False, img, None)


def _click_screen(wincap, point):
    pydirectinput.click(wincap.offset_x + point[0],
                        wincap.offset_y + point[1])
    _park_cursor(wincap)
    time.sleep(FLOW_PACE_S)  # Render-Floor; danach event-getriebenes Warten


def _start_flow(wincap, abort_fn):
    """Startet ein neues Spiel: Strg+E -> Eventuebersicht -> Seher-Zeile ->
    Ansehen -> Start -> Ja -> Spielfenster.

    -> ('ok'|'depleted'|Fehler-Step, debug_dict)
    """
    from seher import flow
    dbg = {}

    # Belohnungs-OK einer Vorrunde wegklicken, falls noch offen.
    img = wincap.get_screenshot()
    ok, pt, ncc = flow.find_click(img, 'flow_reward_ok')
    if ok:
        log.event('0', t('seher.flow_reward_ok', ncc='{:.2f}'.format(ncc)))
        _click_screen(wincap, pt)
        _wait_for(wincap, abort_fn,
                  lambda i: not flow.find(i, 'flow_reward_ok')[0], 4.0)

    _park_cursor(wincap)
    # 1. Eventuebersicht oeffnen (Strg+E ist ein Toggle: erst pruefen).
    def overview_visible(i):
        return flow.find(i, 'flow_event_title')[0] or None
    img = wincap.get_screenshot()
    if not overview_visible(img):
        for attempt in range(1, CTRL_E_RETRIES + 1):
            log.event('0', t('seher.flow_ctrl_e', attempt=attempt))
            _press_ctrl_e()
            ok, img, _ = _wait_for(wincap, abort_fn, overview_visible,
                                   FLOW_STEP_TIMEOUT_S)
            if ok:
                break
            if abort_fn():
                return ('abort', dbg)
        else:
            _log_diagnosis(wincap, 'eventuebersicht', img)
            return ('eventuebersicht', dbg)
    if abort_fn():
        return ('abort', dbg)

    # 2. Seherwettstreit-Zeile + zugehoeriges "Ansehen" -> Start-Knopf.
    # Klick mit Retry: ein verschluckter Ansehen-Klick (DirectInput) war die
    # wahrscheinlichste Ursache des 23:31-Fehlers -> jetzt bis 3x.
    def locate_ansehen(i):
        aok, apt, adbg = flow.find_ansehen_for_seher(i)
        dbg.update(adbg)
        return (aok, apt, adbg.get('ansehen_ncc', 0.0))

    # Erst pruefen, dass die Seher-Zeile ueberhaupt da ist (sonst falsches
    # Event/keine Liste -> Abbruch mit voller Diagnose).
    if not flow.find(wincap.get_screenshot(), 'flow_seher_label')[0]:
        _log_diagnosis(wincap, 'seher_zeile')
        return ('seher_zeile', dbg)

    ok, img = _click_until(
        wincap, abort_fn, locate_ansehen,
        lambda i: flow.find(i, 'flow_start_btn')[0] or None,
        FLOW_STEP_TIMEOUT_S, label='ansehen->start')
    if not ok:
        if abort_fn():
            return ('abort', dbg)
        _log_diagnosis(wincap, 'start_knopf', img)
        return ('start_knopf', dbg)

    # 3. Start -> Teilnahme-Dialog (Ja).
    ok, img = _click_until(
        wincap, abort_fn,
        lambda i: flow.find_click(i, 'flow_start_btn'),
        lambda i: flow.find(i, 'flow_ja_btn')[0] or None,
        FLOW_STEP_TIMEOUT_S, label='start->ja')
    if not ok:
        if abort_fn():
            return ('abort', dbg)
        _log_diagnosis(wincap, 'ja_dialog', img)
        return ('ja_dialog', dbg)

    # 4. Ja klicken, bis der Dialog VERSCHWINDET (= Klick registriert).
    # Kommt das Spiel danach nicht, ist das KEIN Klickfehler, sondern
    # Vorrat leer -> sauberes 'depleted' (Schritt 5).
    ok, img = _click_until(
        wincap, abort_fn,
        lambda i: flow.find_click(i, 'flow_ja_btn'),
        lambda i: (flow.looks_like_game(i)
                   or not flow.find(i, 'flow_ja_btn')[0]) or None,
        FLOW_STEP_TIMEOUT_S, label='ja->bestaetigt')
    if not ok:
        if abort_fn():
            return ('abort', dbg)
        _log_diagnosis(wincap, 'ja_klick', img)
        return ('ja_dialog', dbg)

    # 5. Spielfenster muss erscheinen. Wenn nicht: vermutlich keine
    # Tarotsets / kein Yang mehr -> sauberes 'depleted' (keine Stoerung).
    ok, img, _ = _wait_for(
        wincap, abort_fn,
        lambda i: flow.looks_like_game(i) or None,
        GAME_APPEAR_TIMEOUT_S)
    if not ok:
        if abort_fn():
            return ('abort', dbg)
        log.event('-', t('seher.depleted'))
        _log_diagnosis(wincap, 'kein_spielstart', img)
        return ('depleted', dbg)
    return ('ok', dbg)


def _do_after_action(wincap, abort_fn, action):
    """ESC-Menue: Charakter wechseln oder Spiel beenden."""
    from seher import flow
    name = ('flow_menu_charwechsel' if action == 'char'
            else 'flow_menu_beenden')
    # ESC schliesst in Metin2 erst OFFENE Fenster (Info/Uebersicht/...);
    # das Systemmenue kommt erst, wenn nichts mehr offen ist -> mehrere
    # Versuche, jeder ESC raeumt eine Ebene weg.
    for attempt in range(1, 5):
        _press_esc()
        ok, img, _ = _wait_for(
            wincap, abort_fn,
            lambda i: flow.find(i, name)[0] or None, 2.5)
        if ok:
            ok2, pt, ncc = flow.find_click(img, name)
            _click_screen(wincap, pt)
            log.event('+', t('seher.after_done', action=action,
                             ncc='{:.2f}'.format(ncc)))
            return True
        # ESC kann auch ein offenes Fenster geschlossen haben -> retry
    _save_debug_frame(wincap.get_screenshot(), 'esc_menue')
    log.event('-', t('seher.after_failed', action=action))
    return False


def run_seher_session(cfg, *, abort_fn=None, order='desc', max_games=0,
                      after_action='stop', on_game_done=None, on_tick=None):
    """Dauerschleife: Spiele starten + spielen, bis Stop/Limit/Vorrat-Ende.

    after_action: 'stop' | 'char' | 'client' -- ausgefuehrt bei regulaerem
    Ende (Limit erreicht oder Vorrat leer), NICHT bei Fehlern/Abbruch.
    """
    abort_fn = abort_fn or (lambda: False)
    t0 = time.time()
    ses = SessionResult(after_action=after_action)

    if pydirectinput is None or WindowCapture is None:
        ses.stopped_reason = 'deps'
        log.event('-', t('seher.deps_missing'))
        return ses
    try:
        wincap = WindowCapture(constants.GAME_NAME)
    except Exception as exc:
        ses.stopped_reason = 'window'
        log.error(t('seher.no_game_window'), exc=exc)
        return ses

    from seher import flow
    while not abort_fn():
        # Laeuft bereits ein Spiel (Takeover), direkt spielen; sonst starten.
        img = wincap.get_screenshot()
        if not flow.looks_like_game(img):
            state, dbg = _start_flow(wincap, abort_fn)
            if state == 'abort':
                ses.stopped_reason = 'abort'
                break
            if state == 'depleted':
                ses.stopped_reason = 'depleted'
                log.event('-', t('seher.depleted'))
                break
            if state != 'ok':
                ses.stopped_reason = 'fehler'
                ses.error_step = state
                log.event('-', t('seher.flow_error', step=state,
                                 dbg=str(dbg)))
                ses.duration_s = round(time.time() - t0, 2)
                return ses  # Fehler: HART stoppen, keine After-Action

        res = run_seher_game(cfg, abort_fn=abort_fn, order=order,
                             wincap=wincap, on_tick=on_tick)
        if res.error:
            ses.stopped_reason = 'fehler'
            ses.error_step = 'spiel_' + res.error
            ses.duration_s = round(time.time() - t0, 2)
            return ses
        ses.games_played += 1
        ses.total_coins += res.coins
        if on_game_done is not None:
            try:
                on_game_done(ses, res)
            except Exception:
                pass
        if res.aborted or abort_fn():
            ses.stopped_reason = 'abort'
            break

        # Belohnungs-Popup abwarten + OK druecken.
        ok, img, _ = _wait_for(
            wincap, abort_fn,
            lambda i: flow.find(i, 'flow_reward_ok')[0] or None,
            REWARD_WAIT_S)
        if ok:
            ok2, pt, ncc = flow.find_click(img, 'flow_reward_ok')
            log.event('+', t('seher.flow_reward_ok',
                             ncc='{:.2f}'.format(ncc)))
            _click_screen(wincap, pt)
            _wait_for(wincap, abort_fn,
                      lambda i: not flow.find(i, 'flow_reward_ok')[0], 4.0)
        else:
            log.event('-', t('seher.reward_not_seen'))

        if max_games and ses.games_played >= max_games:
            ses.stopped_reason = 'max_games'
            break

    if not ses.stopped_reason:
        ses.stopped_reason = 'abort'
    if (ses.stopped_reason in ('max_games', 'depleted')
            and after_action in ('char', 'client') and not abort_fn()):
        ses.after_action_done = _do_after_action(wincap, abort_fn,
                                                 after_action)
    ses.duration_s = round(time.time() - t0, 2)
    log.event('+', t('seher.session_done', n=ses.games_played,
                     coins=ses.total_coins, reason=ses.stopped_reason,
                     secs=ses.duration_s))
    return ses
