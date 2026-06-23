# -*- coding: utf-8 -*-
"""Tests fuer energiesplitter.inventory_pages -- reine Seiten-Logik (headless)."""

from energiesplitter import inventory_pages as ip


class TestNormalizePages:
    def test_passthrough_sorted_unique(self):
        assert ip.normalize_pages([3, 1, 1, 2]) == (1, 2, 3)

    def test_roman_labels(self):
        assert ip.normalize_pages(['I', 'IV']) == (1, 4)

    def test_string_ints(self):
        assert ip.normalize_pages(['2', 4]) == (2, 4)

    def test_empty_falls_back_to_all(self):
        assert ip.normalize_pages([]) == ip.ALL_PAGES
        assert ip.normalize_pages(None) == ip.ALL_PAGES

    def test_garbage_dropped_then_fallback(self):
        assert ip.normalize_pages(['x', 9, None]) == ip.ALL_PAGES  # nichts gueltig
        assert ip.normalize_pages(['x', 2]) == (2,)                # 2 bleibt

    def test_out_of_range_dropped(self):
        assert ip.normalize_pages([0, 1, 5, 4]) == (1, 4)


class TestWorkingPage:
    def test_lowest_enabled(self):
        assert ip.working_page([3, 2, 4]) == 2

    def test_default_when_empty(self):
        assert ip.working_page([]) == 1
        assert ip.working_page(None) == 1


class TestIsAllowed:
    def test_int_and_roman(self):
        en = [1, 3]
        assert ip.is_allowed(1, en) is True
        assert ip.is_allowed('III', en) is True
        assert ip.is_allowed(2, en) is False
        assert ip.is_allowed('IV', en) is False

    def test_invalid_input_false(self):
        assert ip.is_allowed('Z', [1, 2, 3, 4]) is False


class TestTargetTab:
    def test_open_page_allowed_no_switch(self):
        assert ip.target_tab('I', [1, 2]) is None
        assert ip.target_tab('II', [1, 2]) is None

    def test_open_page_blocked_switches_to_working(self):
        # offen=I, aber nur 2+3 erlaubt -> auf die niedrigste erlaubte (II)
        assert ip.target_tab('I', [3, 2]) == 'II'

    def test_unknown_active_switches_to_working(self):
        assert ip.target_tab(None, [4, 3]) == 'III'

    def test_all_enabled_default_never_switches_from_any_real_page(self):
        for r in ('I', 'II', 'III', 'IV'):
            assert ip.target_tab(r, [1, 2, 3, 4]) is None


class TestRomanMapping:
    def test_round_trip(self):
        for p, r in ip.PAGE_TO_ROMAN.items():
            assert ip.ROMAN_TO_PAGE[r] == p
        assert tuple(ip.PAGE_TO_ROMAN) == ip.ALL_PAGES
