# -*- coding: utf-8 -*-
"""Reine Logik fuer die freigegebenen Inventar-Seiten des Energie-Bots (Item 3).

Der Nutzer markiert in den Einstellungen, welche der vier Inventar-Seiten (I-IV)
der Bot nutzen darf. Der Bot fasst NUR markierte Seiten an (Frei-Slot-Suche /
Dolch-Verarbeitung); unmarkierte bleiben unberuehrt -- er "schaut dort nicht
nach". Diese Schicht ist toolkit-/win32-frei und headless-testbar; das echte
Reiter-Umschalten lebt im Bot (``detect.active_page`` + ``INV_TAB_CENTERS``).
"""

#: Die vier Inventar-Seiten als 1..4 <-> roemische Reiter-Labels (wie
#: ``energiesplitter.detect.active_page`` / ``calibration.INV_TAB_CENTERS``).
PAGE_TO_ROMAN = {1: 'I', 2: 'II', 3: 'III', 4: 'IV'}
ROMAN_TO_PAGE = {r: p for p, r in PAGE_TO_ROMAN.items()}
ALL_PAGES = (1, 2, 3, 4)


def normalize_pages(value):
    """Beliebige Eingabe -> sortiertes Tupel eindeutiger Seiten aus ``1..4``.

    Akzeptiert Listen/Tupel/Sets aus ints (oder int-artigen Strings) sowie
    roemische Labels ('I'..'IV'). Leeres/ungueltiges Ergebnis -> ALLE Seiten
    (fail-safe: der Bot hat IMMER mindestens eine erlaubte Seite, nie 'keine')."""
    if value is None:
        return ALL_PAGES
    out = set()
    try:
        items = value if isinstance(value, (list, tuple, set)) else [value]
        for item in items:
            if item in ROMAN_TO_PAGE:            # 'I'..'IV'
                out.add(ROMAN_TO_PAGE[item])
                continue
            try:
                n = int(item)
            except (TypeError, ValueError):
                continue
            if n in PAGE_TO_ROMAN:
                out.add(n)
    except TypeError:
        return ALL_PAGES
    return tuple(sorted(out)) if out else ALL_PAGES


def working_page(enabled):
    """Die Arbeits-Seite = NIEDRIGSTE freigegebene Seite (Default 1).

    Auf ihr fuehrt der Bot seine Frei-Slot-/Lande-Logik aus (frueher fix Seite 1).
    Leeres ``enabled`` -> 1 (fail-safe)."""
    pages = normalize_pages(enabled)
    return pages[0] if pages else 1


def target_tab(active_roman, enabled):
    """Welchen Reiter ('I'..'IV') muss der Bot klicken, um auf eine ERLAUBTE
    Seite zu kommen -- oder ``None``, wenn die offene Seite schon erlaubt ist.

    * offene Seite (``active_roman``) bereits freigegeben -> ``None`` (kein Klick).
    * offene Seite gesperrt ODER unbekannt (``None``) -> Reiter der Arbeits-Seite
      (niedrigste freigegebene). Reiner Entscheid (kein I/O), damit der Bot-Guard
      headless testbar bleibt."""
    if active_roman is not None and is_allowed(active_roman, enabled):
        return None
    return PAGE_TO_ROMAN[working_page(enabled)]


def is_allowed(page_or_roman, enabled):
    """``True``, wenn die Seite (1..4 ODER 'I'..'IV') freigegeben ist."""
    pages = set(normalize_pages(enabled))
    if page_or_roman in ROMAN_TO_PAGE:
        return ROMAN_TO_PAGE[page_or_roman] in pages
    try:
        return int(page_or_roman) in pages
    except (TypeError, ValueError):
        return False
