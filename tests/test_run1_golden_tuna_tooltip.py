# -*- coding: utf-8 -*-
"""Run-1 QA: the golden-tuna tooltip states ONLY verified facts (no invented %).

The tooltip ``ui.golden_tuna_verified`` is shown next to the golden-tuna action
selector. The hard requirement (and the source comment: "official Metin2 Wiki;
NO invented %") is that it must NOT fabricate exact drop/buff percentages, and
must carry the facts that WERE verified:

  * catchable once per 24 h, cooldown only on a successful catch;
  * the three actions (Release / Slice open / Use as bait) and what each does;
  * Release is the EITHER/OR (rare-fish buff 60 min OR -50% speed 5 min);
  * Slice's loot list incl. the Carbon Fishing Rod (30 days);
  * bait buff lasts only 5 min;
  * an explicit "exact percentages are not published" disclaimer.

We assert the disclaimer is present AND that no bare "NN%" drop/chance figure
appears -- the only allowed numerics are the verified durations/penalty
(24 h, 60 min, 5 min, -50%, 30 days). EN and DE both checked.
"""

import re
import unittest

import i18n
from i18n_data import TRANSLATIONS

KEY = 'ui.golden_tuna_verified'


class TestTooltipExists(unittest.TestCase):
    def test_key_present_both_langs(self):
        self.assertIn(KEY, TRANSLATIONS)
        self.assertTrue(TRANSLATIONS[KEY]['en'].strip())
        self.assertTrue(TRANSLATIONS[KEY]['de'].strip())


class TestVerifiedFactsPresent(unittest.TestCase):
    def setUp(self):
        self.en = TRANSLATIONS[KEY]['en']
        self.de = TRANSLATIONS[KEY]['de']

    def test_cooldown_fact(self):
        self.assertIn('24 h', self.en)
        self.assertIn('cooldown only on a successful catch', self.en)
        self.assertIn('24 h', self.de)

    def test_three_actions_named_en(self):
        for token in ('Release', 'Slice open', 'Use as bait'):
            self.assertIn(token, self.en)

    def test_three_actions_named_de(self):
        for token in ('Freilassen', 'Aufschneiden', 'Als Köder benutzen'):
            self.assertIn(token, self.de)

    def test_release_is_either_or(self):
        self.assertIn('EITHER', self.en)
        self.assertIn('OR', self.en)
        self.assertIn('-50% movement speed', self.en)
        self.assertIn('60 min', self.en)
        self.assertIn('ENTWEDER', self.de)
        self.assertIn('-50% Bewegungstempo', self.de)

    def test_slice_loot_list_with_carbon_rod(self):
        for token in ('Clam', 'White Pearl', 'Blue Pearl', 'Blood-Red Pearl',
                      'Kelpie Chest', 'Carbon Fishing Rod', '30 days'):
            self.assertIn(token, self.en)
        for token in ('Muschel', 'Weiße Perle', 'Karbon-Angel', '30 Tage'):
            self.assertIn(token, self.de)

    def test_bait_buff_is_five_minutes(self):
        self.assertIn('5 min', self.en)
        self.assertIn('5 min', self.de)


class TestNoInventedPercentages(unittest.TestCase):
    """The crux: no fabricated drop/chance percentage may appear.

    The ONLY '%' permitted is the verified -50% movement-speed penalty. Any
    other ``NN%`` would be an invented figure -> fail. Also assert the explicit
    "not published" disclaimer is present so the absence is intentional.
    """

    def setUp(self):
        self.en = TRANSLATIONS[KEY]['en']
        self.de = TRANSLATIONS[KEY]['de']

    def test_disclaimer_present(self):
        self.assertIn('Exact percentages are not published', self.en)
        self.assertIn('Genaue Prozentwerte sind nicht veröffentlicht', self.de)

    def test_only_allowed_percentage_is_minus_fifty(self):
        for text in (self.en, self.de):
            pcts = re.findall(r'-?\d+\s*%', text)
            self.assertEqual(
                pcts, ['-50%'],
                'unexpected percentage(s) {} in {!r}'.format(pcts, text[:40]))

    def test_no_drop_rate_or_chance_number(self):
        # No "NN% chance" / "NN% drop" style fabricated odds in either language.
        for text in (self.en, self.de):
            self.assertIsNone(
                re.search(r'\d+\s*%\s*(chance|drop|Chance|Wahrscheinlichkeit)',
                          text))


class TestRenderThroughI18n(unittest.TestCase):
    """The tooltip renders via i18n.t in both languages and stays plain text."""

    def tearDown(self):
        i18n.set_lang('en')

    def test_renders_en_and_de(self):
        i18n.set_lang('en')
        en = i18n.t(KEY)
        i18n.set_lang('de')
        de = i18n.t(KEY)
        self.assertIn('Golden Tuna', en)
        self.assertIn('Goldener Thunfisch', de)
        self.assertNotEqual(en, de)

    def test_no_format_placeholders_to_leak(self):
        # A static tooltip: no stray {field} braces that could raise/leak.
        self.assertNotIn('{', TRANSLATIONS[KEY]['en'])
        self.assertNotIn('{', TRANSLATIONS[KEY]['de'])


if __name__ == '__main__':
    unittest.main()
