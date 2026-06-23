# -*- coding: utf-8 -*-
"""T9 / G6 (Tripwire): in den auf das Input-Backend umgestellten Bots darf es
KEINE direkte ``pydirectinput``-Maus/Tasten-Aktion mehr geben -- ausser im
zentralen ``_DirectBackend`` (der Naht selbst). Verhindert, dass kuenftiger Code
an der Lease-Serialisierung vorbei klickt (= Cursor-Korruption im Multiclient).

Erweiterbar: weitere Bots in WIRED_FILES aufnehmen, sobald sie (Schritt 6)
angebunden sind.
"""

import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Bots, die bereits auf das Input-Backend umgestellt sind (Multiclient).
WIRED_FILES = ['fishingbot.py', 'puzzle.py', 'energiesplitter/bot.py',
               'interface/seher_runner.py']

# Direkte Eingabe-Aktionen, die durch das Backend laufen MUESSEN.
ACTION_RE = re.compile(
    r'pydirectinput\.(click|keyDown|keyUp|mouseDown|mouseUp|press|typewrite)\s*\(')


def _allowed_block_ranges(lines):
    """Zeilen-Indizes, in denen direkte Eingabe ERLAUBT ist (im _DirectBackend).

    Von ``class _DirectBackend:`` bis zur naechsten Top-Level-Anweisung
    (``_input = ...``).
    """
    start = end = None
    for i, ln in enumerate(lines):
        if ln.startswith('class _DirectBackend:'):
            start = i
        elif start is not None and ln.startswith('_input'):
            end = i
            break
    if start is None:
        return []
    return [(start, end if end is not None else len(lines))]


class TestNoDirectInput(unittest.TestCase):
    def test_wired_bots_route_through_backend(self):
        for rel in WIRED_FILES:
            path = os.path.join(REPO, rel)
            with open(path, encoding='utf-8') as fh:
                lines = fh.read().splitlines()
            allowed = _allowed_block_ranges(lines)
            offenders = []
            for i, ln in enumerate(lines):
                if not ACTION_RE.search(ln):
                    continue
                in_allowed = any(s <= i < e for (s, e) in allowed)
                if not in_allowed:
                    offenders.append(f'{rel}:{i + 1}: {ln.strip()}')
            self.assertEqual(
                offenders, [],
                'Direkte pydirectinput-Aktion ausserhalb _DirectBackend '
                '(muss ueber _input laufen):\n' + '\n'.join(offenders))

    def test_wired_bots_have_backend_hook(self):
        # Sicherheitsnetz: die Naht (set_input_backend) existiert wirklich.
        for rel in WIRED_FILES:
            with open(os.path.join(REPO, rel), encoding='utf-8') as fh:
                src = fh.read()
            self.assertIn('def set_input_backend(', src, rel)
            self.assertIn('_input', src, rel)


if __name__ == '__main__':
    unittest.main()
