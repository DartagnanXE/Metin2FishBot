# -*- coding: utf-8 -*-
"""Reine Logik-Schicht fuer die Multiclient-Einstellungen (1-4 Clients).

Toolkit-frei und headless-testbar -- KEIN ``customtkinter``, KEIN ``win32``.
Haelt das Slot-Modell, den count-Clamp, die (De)Serialisierung in/aus
``config['multiclient']``, immutable Updates, Dedup, Validierung und die
Ableitung der Launcher-Specs ``[(hwnd, mode), ...]`` (vgl. :mod:`launcher`).

Alle Updates sind **immutable**: sie liefern neue Listen/Slots, mutieren nie das
Original (Coding-Style-Regel). Die Mode-Tokens spiegeln ``launcher.VALID_MODES``;
der Energiesplitter-Submodus (Hammer/Dolch) wird erst im Worker aus der Basis-
Config abgeleitet, der Slot-Modus bleibt schlicht ``'energiesplitter'``.
"""

from dataclasses import dataclass

# -- Eine einzige Wahrheit (deckungsgleich mit launcher.VALID_MODES) ----------
MODES = ('fischen', 'puzzle', 'seher', 'energiesplitter')
DEFAULT_MODE = 'fischen'
MIN_CLIENTS = 1
MAX_CLIENTS = 4


@dataclass(frozen=True)
class ClientSlot:
    """Ein Client-Slot: welcher Modus + welches markierte Fenster (HWND).

    ``hwnd is None`` heisst *unmarkiert* -- der Nutzer hat das Fenster noch nicht
    per Klick-Erfassung zugeordnet. Ein unmarkierter aktiver Slot ist nicht
    startbereit (siehe :func:`validate`).
    """
    mode: str = DEFAULT_MODE
    hwnd: 'int | None' = None


def clamp_count(n):
    """Beliebigen Wert defensiv auf ``[MIN_CLIENTS, MAX_CLIENTS]`` klemmen.

    Nicht-numerische Eingaben -> ``MIN_CLIENTS`` (fail-safe, nie Exception)."""
    try:
        v = int(n)
    except (TypeError, ValueError):
        return MIN_CLIENTS
    return max(MIN_CLIENTS, min(MAX_CLIENTS, v))


def normalize_mode(mode):
    """Unbekannte/ungueltige Modi -> ``DEFAULT_MODE`` (fail-safe)."""
    return mode if mode in MODES else DEFAULT_MODE


def set_count(slots, count):
    """Slot-Liste immutable auf ``count`` (geklemmt) bringen.

    Wachsen -> mit Default-Slots auffuellen; Schrumpfen -> Praefix behalten."""
    n = clamp_count(count)
    cur = list(slots)
    if len(cur) >= n:
        return cur[:n]
    return cur + [ClientSlot() for _ in range(n - len(cur))]


def set_mode(slots, idx, mode):
    """Modus von Slot ``idx`` immutable setzen (ungueltiger Index -> no-op)."""
    if idx < 0 or idx >= len(slots):
        return list(slots)
    out = list(slots)
    out[idx] = ClientSlot(mode=normalize_mode(mode), hwnd=out[idx].hwnd)
    return out


def assign_hwnd(slots, idx, hwnd):
    """HWND an Slot ``idx`` zuweisen; dasselbe HWND anderswo loeschen.

    Garantiert die Invariante *ein Fenster = ein Client* (Erfolgskriterium 3).
    Immutable; ungueltiger Index -> unveraenderte Kopie."""
    if idx < 0 or idx >= len(slots):
        return list(slots)
    out = []
    for i, s in enumerate(slots):
        if i == idx:
            out.append(ClientSlot(mode=s.mode, hwnd=hwnd))
        elif s.hwnd == hwnd:
            out.append(ClientSlot(mode=s.mode, hwnd=None))  # Duplikat freigeben
        else:
            out.append(s)
    return out


def config_from_slots(slots, count, auto_restart=False):
    """Slots -> serialisierbares ``config['multiclient']``-Dict."""
    return {
        'count': clamp_count(count),
        'auto_restart': bool(auto_restart),
        'clients': [{'mode': normalize_mode(s.mode), 'hwnd': s.hwnd}
                    for s in slots],
    }


def _raw(cfg):
    mc = cfg.get('multiclient') if isinstance(cfg, dict) else None
    return mc if isinstance(mc, dict) else {}


def slots_from_config(cfg):
    """``config['multiclient']`` -> Liste von :class:`ClientSlot`.

    Fehlt die Sektion -> genau ein Default-Slot (Single-Client, byte-identisch).
    Modi werden normalisiert, HWNDs defensiv als ``int|None`` uebernommen."""
    raw = _raw(cfg)
    clients = raw.get('clients')
    if not isinstance(clients, list) or not clients:
        return [ClientSlot()]
    out = []
    for entry in clients:
        if not isinstance(entry, dict):
            out.append(ClientSlot())
            continue
        hwnd = entry.get('hwnd')
        try:
            hwnd = int(hwnd) if hwnd is not None else None
        except (TypeError, ValueError):
            hwnd = None
        out.append(ClientSlot(mode=normalize_mode(entry.get('mode')), hwnd=hwnd))
    return out


def _norm_hwnd(hwnd):
    try:
        return int(hwnd) if hwnd is not None else None
    except (TypeError, ValueError):
        return None


def normalize_config(raw):
    """Roh-``multiclient``-Dict saeubern, OHNE die Client-Liste aufzufuellen.

    Fuer die Config-Validierung (:mod:`interface.config.validate`): klemmt
    ``count``, normalisiert vorhandene Eintraege (Modus + ``hwnd`` als int|None)
    und laesst eine leere Liste leer (= Single-Client-Default, byte-identisch).
    Muell-Eingaben -> sicheres Minimal-Dict."""
    if not isinstance(raw, dict):
        return {'count': MIN_CLIENTS, 'auto_restart': False, 'clients': []}
    clients_raw = raw.get('clients')
    clients = []
    if isinstance(clients_raw, list):
        for entry in clients_raw:
            if isinstance(entry, dict):
                clients.append({'mode': normalize_mode(entry.get('mode')),
                                'hwnd': _norm_hwnd(entry.get('hwnd'))})
            else:
                clients.append({'mode': DEFAULT_MODE, 'hwnd': None})
    return {
        'count': clamp_count(raw.get('count', MIN_CLIENTS)),
        'auto_restart': bool(raw.get('auto_restart', False)),
        'clients': clients,
    }


def count_from_config(cfg):
    """Geklemmte Client-Anzahl aus der Config (fehlt -> ``MIN_CLIENTS``)."""
    return clamp_count(_raw(cfg).get('count', MIN_CLIENTS))


def _active(slots, count):
    """Die ersten ``count`` (geklemmten) Slots = die aktiven."""
    return list(slots)[:clamp_count(count)]


def validate(slots, count):
    """Liste menschenlesbarer Probleme der aktiven Slots (leer = startbereit).

    Meldet (a) unmarkierte aktive Slots und (b) doppelt belegte Fenster. Nur die
    ersten ``count`` Slots werden geprueft -- inaktive Slots sind egal."""
    active = _active(slots, count)
    problems = []
    seen = {}
    for i, s in enumerate(active):
        n = i + 1
        if s.hwnd is None:
            problems.append('Client {}: kein Fenster markiert.'.format(n))
            continue
        if s.hwnd in seen:
            problems.append(
                'Client {} und {} nutzen dasselbe Fenster.'.format(seen[s.hwnd], n))
        else:
            seen[s.hwnd] = n
    return problems


def is_ready(slots, count):
    """True, wenn alle aktiven Slots markiert + eindeutig sind."""
    return not validate(slots, count)


def specs_from_slots(slots, count):
    """Launcher-Specs ``[(hwnd, mode), ...]`` aus den aktiven, markierten Slots.

    Unmarkierte Slots werden uebersprungen (sie haben kein Ziel-Fenster)."""
    out = []
    for s in _active(slots, count):
        if s.hwnd is not None:
            out.append((s.hwnd, normalize_mode(s.mode)))
    return out
