# -*- coding: utf-8 -*-
"""EN/DE parity for the translation table (:mod:`i18n_data`).

``i18n.t`` falls back EN -> key, so a MISSING or empty German string silently
degrades to English. This test makes the parity guarantee explicit:

  * every entry carries BOTH 'en' and 'de', non-empty;
  * the ``{placeholder}`` field names match between EN and DE (so neither
    language raises / leaks a raw brace at format time).

Pure stdlib -> always runnable headless.
"""

import string
import unittest

from i18n_data import TRANSLATIONS


def _placeholders(text):
    """Set of named ``{field}`` placeholders in a format string (ignore text)."""
    names = set()
    for _literal, field, _spec, _conv in string.Formatter().parse(text):
        if field:
            names.add(field)
    return names


class TestI18nParity(unittest.TestCase):
    def test_every_entry_has_both_languages(self):
        for key, entry in TRANSLATIONS.items():
            self.assertIsInstance(entry, dict, key)
            self.assertIn('en', entry, key)
            self.assertIn('de', entry, key)
            self.assertTrue(str(entry['en']).strip(),
                            'empty en for {!r}'.format(key))
            self.assertTrue(str(entry['de']).strip(),
                            'empty de for {!r}'.format(key))

    def test_placeholders_match_between_languages(self):
        for key, entry in TRANSLATIONS.items():
            en_fields = _placeholders(entry['en'])
            de_fields = _placeholders(entry['de'])
            self.assertEqual(
                en_fields, de_fields,
                'placeholder mismatch for {!r}: en={} de={}'.format(
                    key, sorted(en_fields), sorted(de_fields)))


if __name__ == '__main__':
    unittest.main()
