# -*- coding: utf-8 -*-
"""Headless Modus-Schleifen fuer den Multiclient-Worker (Build-Schritt 6/6b).

``worker.Deps.run_mode`` delegiert hierher. Angebunden sind ALLE Modi:

  * **fischen**          -> ``FishingBot`` (set_input_backend + set_refill_backend)
  * **puzzle**           -> ``PuzzleBot``  (puzzle.set_input_backend)
  * **energiesplitter**  -> ``EnergiesplitterBot`` (energiesplitter.bot.set_input_backend)
  * **seher**            -> ``run_seher_session`` (seher_runner.set_input_backend)

Kein CTk, kein ``RunLoop``: jeder Treiber baut GENAU EINEN Bot ohne GUI, spiegelt
die Instanz-Verdrahtung aus ``run_loop.on_start`` (der jeweilige Zweig) und tickt
``runHack`` bis Stop (Seher spielt stattdessen ueber ``abort_fn``). Stop kommt vom
Broker/Supervisor ueber ``ipc.stop_requested()``; ein Bridge-Thread spiegelt das in
das interruptible :class:`stop_signal.StopSignal`, damit eine laufende (blockierende)
Heavy-Op (Refill/Inventar) in <1 Slice abbricht.

Multiclient-Eingabe: pro Worker EIN ``CursorClient`` (Lease) -> die Tick-Modi
fahren ihn ueber ein ``LeasedPydirectinput`` (pydirectinput-API-Shim, der jeden
Klick/Akkord/Drag zu EINEM Lease-Burst buendelt). Fischen nutzt zusaetzlich das
schmale ``LeasedInput``-Backend + ``LeasedScreenCursor`` fuers Koeder-Nachlegen.

Alle schweren Abhaengigkeiten sind injizierbar (``build_bot``/``config_load``/
``sleep``/``run_session``) -> die Schleifen-Logik ist ohne echtes Spiel/CTk
unit-testbar.
"""

import importlib
import threading
import time

import cursor_client
import stop_signal as _stopsig
from interface.config import io as _cfgio

#: Tick-Abstand der headless Tick-Schleifen (wie run_loop.TICK_MS = 10 ms).
TICK_S = 0.01
#: Poll-Abstand des ipc->StopSignal-Bridge-Threads.
STOP_BRIDGE_POLL_S = 0.02


def run_mode(mode, ipc, args, *, deps=None):
    """Dispatch nach Modus. Baut den lease-gebundenen Cursor (EIN Cursor/Worker).

    Alle Modi liefern Bildschirm-Koordinaten -> identity-``to_screen``
    (``make_leased_cursor``). Dieselbe Lease serialisiert Kern-Aktionen UND
    Refill-/Drag-Bursts.
    """
    cursor = cursor_client.make_leased_cursor(
        args.client, args.hwnd, ipc.acquire, ipc.release,
        stop_check=ipc.stop_requested)
    if mode == 'fischen':
        return run_fishing(cursor, ipc, args)
    if mode == 'puzzle':
        return run_puzzle(cursor, ipc, args)
    if mode == 'energiesplitter':
        return run_energiesplitter(None, cursor, ipc, args)
    if mode == 'seher':
        return run_seher(cursor, ipc, args)
    raise NotImplementedError('run_mode: Modus %r unbekannt' % (mode,))


# -- gemeinsamer Tick-Treiber (fischen/puzzle/energiesplitter) ----------------

def _drive_tick_bot(bot, ipc, stop_sig, args, sleep):
    """Headless Tick-Schleife bis Stop. Gibt den Bot zurueck (Tests).

    Bridge: ipc-Stop (Broker/F6) -> interruptibles StopSignal, damit eine laufende
    Heavy-Op (Inventar/Refill -- blockiert die Tick-Schleife) sofort abbricht.
    """
    bridge_stop = threading.Event()
    bridge = threading.Thread(
        target=_stop_bridge, args=(ipc, stop_sig, bridge_stop),
        daemon=True, name=f'stop-bridge-{getattr(args, "client", "?")}')
    bridge.start()
    try:
        while not ipc.stop_requested() and getattr(bot, 'botting', False):
            bot.runHack()
            if ipc.stop_requested():
                break
            sleep(TICK_S)
    finally:
        stop_sig.request_stop()      # laufende/naechste Heavy-Op sauber beenden
        bridge_stop.set()
    return bot


def _stop_bridge(ipc, stop_sig, bridge_stop):
    """Spiegelt ``ipc.stop_requested()`` in das StopSignal (Daemon)."""
    while not bridge_stop.is_set():
        try:
            if ipc.stop_requested():
                stop_sig.request_stop()
                return
        except Exception:            # pragma: no cover - defensiv
            return
        bridge_stop.wait(STOP_BRIDGE_POLL_S)


# -- Fischen ------------------------------------------------------------------

def _build_fishing_bot(cfg, cursor, *, stop_sig):
    """Baut + verdrahtet einen headless ``FishingBot`` (Spiegel von
    ``run_loop.on_start`` fishing-Zweig, ohne CTk/Controller)."""
    import fishingbot
    bot = fishingbot.FishingBot()
    # Beide Lease-Backends teilen sich DENSELBEN Cursor (eine Lease):
    #   * Kern-Loop (click/key)         -> LeasedInput
    #   * Koeder-Nachlegen (Drag)       -> LeasedScreenCursor
    fishingbot.set_input_backend(cursor_client.LeasedInput(cursor))
    fishingbot.set_refill_backend(cursor_client.LeasedScreenCursor(cursor))

    values = _cfgio.to_values(cfg)
    fish = cfg.get('fishing', {}) if isinstance(cfg, dict) else {}
    bot.bait_key = fish.get('bait_key', '2')
    bot.cast_key = fish.get('cast_key', '1')
    bot.mount_key = fish.get('mount_key', '3')
    bot.whitelist_enabled = bool(fish.get('whitelist_enabled', False))
    # whitelist_states bleibt Klassen-Default (None) -> es wird alles geangelt.
    bot.bait_refill_enabled = bool(fish.get('bait_refill_enabled', False))
    bot.bait_refill_db = None        # None -> die Refill-Engine baut die DB selbst
    bot.bait_refill_calib = None     # Engine-Default (DEFAULT_CALIBRATION)
    inv = cfg.get('inventory', {}) if isinstance(cfg, dict) else {}
    bot.inventory_hotkey = inv.get('hotkey', 'i')
    bot.stop_signal = stop_sig
    bot.set_to_begin(values)         # erzeugt wincap (preferred_hwnd ist gesetzt)
    bot.botting = True
    return bot


def run_fishing(cursor, ipc, args, *, sleep=None, build_bot=None,
                config_load=None):
    """Headless Fishing-Tick-Schleife bis Stop. Gibt den Bot zurueck (Tests)."""
    sleep = sleep or time.sleep
    cfg = (config_load or _cfgio.load)()
    stop_sig = _stopsig.StopSignal()
    builder = build_bot or _build_fishing_bot
    bot = builder(cfg, cursor, stop_sig=stop_sig)
    return _drive_tick_bot(bot, ipc, stop_sig, args, sleep)


# -- Puzzle -------------------------------------------------------------------

def _build_puzzle_bot(cfg, cursor, *, stop_sig):
    """Baut + verdrahtet einen headless ``PuzzleBot`` (Spiegel von
    ``run_loop.on_start`` puzzle-Zweig + ``apply_puzzle_config``).

    Board-Offset: der Default-Erkennungsmodus nutzt den Klassen-Default-Offset
    (kein ``inject_offset`` noetig). Die ``auto``/``mark``-Modi (Screenshot- bzw.
    Kalibrier-abhaengig) sind ein Live-Folgeschritt.
    """
    import puzzle
    puzzle.set_input_backend(cursor_client.LeasedPydirectinput(cursor))
    bot = puzzle.PuzzleBot()
    puz = cfg.get('puzzle', {}) if isinstance(cfg, dict) else {}
    bot.color_mode = puz.get('color_mode', 'single')
    bot.color_patch = puz.get('color_patch', 3)
    bot.solver_mode = puz.get('solver_mode', 'standard')
    bot.step_delay = puz.get('step_delay', 0.1)
    bot.force_deluxe = puz.get('force_deluxe', False)
    bot.verify_placements = puz.get('verify_placements', True)
    bot.board_plausibility = puz.get('board_plausibility', True)
    bot.color_stat = puz.get('color_stat', 'mean')
    bot.stop_signal = stop_sig
    bot.set_to_begin(_cfgio.to_values(cfg))
    bot.botting = True
    return bot


def run_puzzle(cursor, ipc, args, *, sleep=None, build_bot=None,
               config_load=None):
    """Headless Puzzle-Tick-Schleife bis Stop. Gibt den Bot zurueck (Tests)."""
    sleep = sleep or time.sleep
    cfg = (config_load or _cfgio.load)()
    stop_sig = _stopsig.StopSignal()
    builder = build_bot or _build_puzzle_bot
    bot = builder(cfg, cursor, stop_sig=stop_sig)
    return _drive_tick_bot(bot, ipc, stop_sig, args, sleep)


# -- Energiesplitter ----------------------------------------------------------

def _es_values(cfg, sub):
    """Baut die ``-ES_*-``-``values`` headless (Spiegel von
    ``run_loop.apply_energiesplitter_config`` -- DORT ist die Quelle der Wahrheit;
    Aenderungen dort hier nachziehen). ``sub`` = ``'hammer'`` | ``'dagger'``.
    """
    values = _cfgio.to_values(cfg)
    es = cfg.get('energiesplitter', {}) if isinstance(cfg, dict) else {}
    hammer = es.get('hammer', {})
    dagger = es.get('dagger', {})
    shared = es.get('shared', {})
    try:
        values['-ES_MODE-'] = 'dagger' if sub == 'dagger' else 'hammer'
        values['-ES_STACK_COUNT-'] = int(hammer.get('stack_count', 1))
        values['-ES_FREISCHALTEN-'] = bool(
            hammer.get('energie_freischalten', False))
        values['-ES_DAGGERS_PER_ROUND-'] = int(
            dagger.get('daggers_per_round', 1))
        values['-ES_BUY_MODE-'] = str(dagger.get('buy_mode', 'chat'))
        values['-ES_BUY_DELAY_S-'] = float(dagger.get('buy_delay_s', 0.35))
        values['-ES_PROCESS_FIRST-'] = bool(dagger.get('process_first', False))
        values['-ES_PROC_PICKUP_S-'] = float(
            dagger.get('process_pickup_s', 0.15))
        values['-ES_PROC_CONFIRM_S-'] = float(
            dagger.get('process_confirm_s', 0.4))
        values['-ES_SPEED-'] = str(shared.get('speed_profile', 'normal'))
        values['-ES_MOUSE_PAUSE-'] = float(shared.get('mouse_pause', 0.05))
        values['-ES_KB_PAUSE-'] = float(shared.get('keyboard_pause', 0.1))
        values['-ES_MAX_ACTIONS-'] = int(shared.get('max_actions', 1000))
        values['-ES_UNVERIF_STOP-'] = int(
            shared.get('consecutive_unverified_stop', 5))
        values['-ES_JITTER-'] = float(shared.get('jitter_pct', 0.15))
        values['-ES_DRY_RUN-'] = bool(shared.get('dry_run', True))
    except Exception:                # pragma: no cover - defensiv (Bot-Defaults)
        pass
    return values


def _es_sub_mode(cfg, sub_mode):
    """Submodus ableiten: explizit > persistierter ``cfg['mode']`` > 'hammer'."""
    if sub_mode in ('hammer', 'dagger'):
        return sub_mode
    persisted = cfg.get('mode') if isinstance(cfg, dict) else None
    return 'dagger' if persisted == 'energiesplitter_dagger' else 'hammer'


def _build_energiesplitter_bot(cfg, cursor, sub_mode, *, stop_sig):
    """Baut + verdrahtet einen headless ``EnergiesplitterBot`` (Spiegel von
    ``run_loop.on_start`` energiesplitter-Zweig)."""
    esmod = importlib.import_module('energiesplitter.bot')
    esmod.set_input_backend(cursor_client.LeasedPydirectinput(cursor))
    bot = esmod.EnergiesplitterBot()
    sub = _es_sub_mode(cfg, sub_mode)
    bot.mode = sub
    bot.stop_signal = stop_sig
    inv = cfg.get('inventory', {}) if isinstance(cfg, dict) else {}
    bot.inventory_hotkey = inv.get('hotkey', 'i')
    bot.set_to_begin(_es_values(cfg, sub))   # friert Config ein, ruft phase0_gate
    bot.botting = True
    return bot


def run_energiesplitter(sub_mode, cursor, ipc, args, *, sleep=None,
                        build_bot=None, config_load=None):
    """Headless Energiesplitter-Tick-Schleife bis Stop. ``sub_mode`` =
    ``'hammer'``/``'dagger'`` oder ``None`` (dann aus ``cfg['mode']`` abgeleitet)."""
    sleep = sleep or time.sleep
    cfg = (config_load or _cfgio.load)()
    stop_sig = _stopsig.StopSignal()
    builder = build_bot or _build_energiesplitter_bot
    bot = builder(cfg, cursor, sub_mode, stop_sig=stop_sig)
    return _drive_tick_bot(bot, ipc, stop_sig, args, sleep)


# -- Seher (eigener Pfad: keine runHack-Tick-Schleife, sondern abort_fn) ------

def run_seher(cursor, ipc, args, *, run_session=None, config_load=None,
              set_backend=None, order='desc', max_games=0, after_action='stop'):
    """Headless Seher-Dauerschleife bis Stop. Der Seher pollt ``abort_fn``
    (= ``ipc.stop_requested``) selbst -> kein StopSignal/Tick-Treiber noetig.
    Gibt das Sessions-Ergebnis zurueck (Tests)."""
    cfg = (config_load or _cfgio.load)()
    sr = importlib.import_module('interface.seher_runner')
    (set_backend or sr.set_input_backend)(
        cursor_client.LeasedPydirectinput(cursor))
    session = run_session or sr.run_seher_session
    return session(cfg, abort_fn=ipc.stop_requested, order=order,
                   max_games=max_games, after_action=after_action)
