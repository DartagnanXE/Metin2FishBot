# -*- coding: utf-8 -*-
"""Tests fuer das Erkennungs-Framework (energiesplitter/detect.py + geometry.py).

Headless mit ECHTEM cv2/numpy gegen die 26 echten Fixtures. Geprueft wird:

  * **Geometrie** 802x632 -> 800x600 (Client-Normierung, Kalibrier-Gate).
  * **NCC-Wortbild-Framework** (``match_word``/``find_npc_name``/``find_shop_item``):
    Treffer bei ECHTEN Bildern (Template aus einem Fixture extrahiert, in einem
    ANDEREN wiedergefunden), kein Treffer bei leerer/falscher Szene.
  * **Selektions-Ring**: Treffer am echten roten Ring, KEIN Treffer bei
    HP-Leiste / leerer Wiese / NPC-loser Szene (Ring-Form-Test).
  * **Phase-0-Gate** (``assets_ready``): meldet die noch fehlenden Assets
    (Wortbild-Templates, Item-Icons) ehrlich als ``missing``. YANG spielt keine
    Rolle mehr (kein Gold-Reader, keine Yang-Ziffern).
  * **NotReady-Pfade**: asset-gebundene Detektoren (``dialog_state``/``shop_open``/
    ``panel_is_bag``) liefern sauber None/False, solange ihre Marker-Templates
    fehlen; werden echte Marker-Templates injiziert, diskriminieren sie korrekt.

Die win32/pydirectinput-Abhaengigkeit fehlt hier bewusst: detect.py/geometry.py
sind REIN (nur numpy/cv2 + Datei-Lesen) und brauchen kein Stubbing.
"""

import os
import sys
import unittest

import cv2

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from energiesplitter import detect as d      # noqa: E402
from energiesplitter import geometry as geo  # noqa: E402
from energiesplitter import calibration as cal  # noqa: E402

_FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    'fixtures', 'energiesplitter')


def _load(group, name):
    path = os.path.join(_FIX, group, name)
    img = cv2.imread(path)
    assert img is not None, 'fixture missing: %s' % path
    return img


def _alch_name_template():
    """Extrahiert ein tight 'Alchemist'-Wortbild aus einem echten Bild.

    Steht stellvertretend fuer das P0.2-Template ``npc_alchemist`` -> beweist das
    Gruen+NCC-Framework gegen echte Bilder, ohne ein Asset zu erfinden.
    """
    img = _load('Alchemist', 'metin2client_BlRGzUUM3w.png')
    client = geo.to_client(img)
    # 'Alchemist'-Schriftzug oben-mitte (an der Gruen-Maske lokalisiert).
    gm = d._green_mask(client[104:122, 352:404])
    import numpy as np
    ys, xs = np.where(gm > 0)
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    return client[104 + y0 - 1:104 + y1 + 2, 352 + x0 - 1:352 + x1 + 2]


def _laden_header_template():
    """Extrahiert das weisse 'Laden'-Header-Wort aus dem Alchemist-Shop."""
    img = _load('Einkauf_Hammer', 'shop_alchemist.png')
    client = geo.to_client(img)
    return client[22:40, 455:510]


# ---------------------------------------------------------------------------
class TestGeometry(unittest.TestCase):

    def test_to_client_normalises_802x632(self):
        img = _load('Alchemist', 'metin2client_BlRGzUUM3w.png')
        self.assertEqual(img.shape[:2], (geo.RAW_H, geo.RAW_W))
        client = geo.to_client(img)
        self.assertEqual(client.shape[:2], (geo.GAME_H, geo.GAME_W))

    def test_to_client_passthrough_when_already_client(self):
        import numpy as np
        already = np.zeros((geo.GAME_H, geo.GAME_W, 3), dtype=np.uint8)
        out = geo.to_client(already)
        self.assertEqual(out.shape[:2], (geo.GAME_H, geo.GAME_W))

    def test_to_client_defensive_on_none_and_tiny(self):
        import numpy as np
        self.assertIsNone(geo.to_client(None))
        tiny = np.zeros((10, 10, 3), dtype=np.uint8)
        self.assertEqual(geo.to_client(tiny).shape[:2], (10, 10))  # unveraendert

    def test_crop_clamps_and_rejects_empty(self):
        img = _load('Alchemist', 'metin2client_BlRGzUUM3w.png')
        client = geo.to_client(img)
        sub = geo.crop(client, (0, 0, 50, 50))
        self.assertEqual(sub.shape[:2], (50, 50))
        self.assertIsNone(geo.crop(client, (0, 0, 0, 0)))
        self.assertIsNone(geo.crop(None, (0, 0, 10, 10)))

    def test_is_calibrated_true_for_800x600_and_tolerant(self):
        class W:
            hwnd = None
        w = W(); w.w = 800; w.h = 600
        self.assertTrue(geo.is_calibrated(w))
        w.w = 800 + geo.GAME_SIZE_TOLERANCE; w.h = 600
        self.assertTrue(geo.is_calibrated(w))

    def test_is_calibrated_false_when_off_or_missing(self):
        class W:
            hwnd = None
        w = W(); w.w = 1024; w.h = 768
        self.assertFalse(geo.is_calibrated(w))
        self.assertFalse(geo.is_calibrated(object()))  # keine w/h-Attribute


# ---------------------------------------------------------------------------
class TestAssetsGate(unittest.TestCase):
    """Asset-Lieferung: Item-/NPC-Templates + Shop-Anker liegen vor ->
    ``assets_ready`` ist fuer beide Modi GRUEN (``missing == []``). YANG spielt
    keine Rolle mehr -> keine ``yang_digits``-Luecke. Das Phase-0-Gate KANN damit
    gruen werden (die restliche Absicherung leistet die Grid-/Fenster-
    Kalibrierung + die Backstops im Bot)."""

    def test_hammer_item_and_npc_present(self):
        # Die in CALIBRATION.md gemessenen Live-Templates sind gebundelt.
        self.assertTrue(d.item_template_available('hammer'))
        ready, missing = d.assets_ready('hammer')
        self.assertNotIn('item:hammer', missing)
        self.assertNotIn('npc:alchemist', missing)

    def test_hammer_gate_green_assets_complete(self):
        ready, missing = d.assets_ready('hammer')
        self.assertEqual(missing, [])
        self.assertTrue(ready)

    def test_no_yang_digits_in_missing(self):
        # YANG entfernt -> assets_ready meldet niemals 'yang_digits'.
        for mode in ('hammer', 'dagger'):
            _ready, missing = d.assets_ready(mode)
            self.assertNotIn('yang_digits', missing)

    def test_dagger_includes_dolch_and_waffenhaendler(self):
        self.assertTrue(d.item_template_available('dolch'))
        ready, missing = d.assets_ready('dagger')
        self.assertNotIn('item:dolch', missing)
        self.assertNotIn('npc:waffenhaendler', missing)
        self.assertEqual(missing, [])
        self.assertTrue(ready)

    def test_grid_present(self):
        # Der GATE-Grid-Check (ersetzt gold_reader._grid_present) loest auf.
        self.assertTrue(d.grid_present())

    def test_unknown_mode_rejected(self):
        ready, missing = d.assets_ready('bogus')
        self.assertFalse(ready)
        self.assertEqual(missing, ['mode:bogus'])


# ---------------------------------------------------------------------------
class TestWordMatchFramework(unittest.TestCase):
    """NCC-Wortbild-Framework gegen echte Bilder (Templates zur Laufzeit extrahiert)."""

    def test_find_npc_name_hits_alchemist_across_frames(self):
        tpl = _alch_name_template()
        # Der gleiche In-Game-Schriftzug erscheint (an wandernder Position) in
        # mehreren Alchemist-Bildern -> hoher NCC-Treffer.
        hits = 0
        for name in ('metin2client_Fmx09flgeZ.png', 'metin2client_TYu62EaDYI.png',
                     'metin2client_s4nZUO3m1E.png', 'metin2client_jSBNb1MyFP.png'):
            img = _load('Alchemist', name)
            ok, pt, ncc = d.find_npc_name(img, tpl)
            if ok:
                hits += 1
                self.assertIsNotNone(pt)
                self.assertGreaterEqual(ncc, d.NCC_WORD)
        self.assertGreaterEqual(hits, 3, 'expected the Alchemist name in most frames')

    def test_find_npc_name_no_hit_in_non_alchemist_scene(self):
        tpl = _alch_name_template()
        for name in ('metin2client_2JJQT56i9r.png', 'metin2client_KwAggglQCf.png'):
            img = _load('Waffenschmied', name)
            ok, _pt, ncc = d.find_npc_name(img, tpl)
            self.assertFalse(ok)
            self.assertLess(ncc, d.NCC_WORD)

    def test_find_npc_name_defensive_none_template(self):
        img = _load('Alchemist', 'metin2client_BlRGzUUM3w.png')
        ok, pt, ncc = d.find_npc_name(img, None)
        self.assertFalse(ok)
        self.assertIsNone(pt)

    def test_find_shop_item_hits_real_icon(self):
        img = _load('Einkauf_Hammer', 'shop_alchemist.png')
        client = geo.to_client(img)
        icon = client[80:104, 495:520]  # echtes Shop-Item-Icon (4. Slot)
        ok, pt, ncc = d.find_shop_item(img, icon, roi=(365, 75, 200, 35))
        self.assertTrue(ok)
        self.assertIsNotNone(pt)
        self.assertGreaterEqual(ncc, d.NCC_ITEM)

    def test_find_shop_item_no_hit_in_overworld(self):
        shop = _load('Einkauf_Hammer', 'shop_alchemist.png')
        icon = geo.to_client(shop)[80:104, 495:520]
        overworld = _load('Alchemist', 'metin2client_BlRGzUUM3w.png')
        ok, _pt, ncc = d.find_shop_item(overworld, icon, roi=(365, 75, 200, 35))
        self.assertFalse(ok)
        self.assertLess(ncc, d.NCC_ITEM)

    def test_match_word_defensive_oversized_template(self):
        img = _load('Alchemist', 'metin2client_BlRGzUUM3w.png')
        client = geo.to_client(img)
        import numpy as np
        toobig = np.zeros((client.shape[0] + 10, client.shape[1] + 10, 3),
                          dtype=np.uint8)
        ok, pt, ncc = d.match_word(client, toobig)
        self.assertFalse(ok)
        self.assertIsNone(pt)


# ---------------------------------------------------------------------------
class TestShopDaggerAnchor(unittest.TestCase):
    """Dolch-Shop-Anker GESCHLOSSEN (2026-06-15): der markierte Dolch-Slot liegt
    in der oberen Shop-Reihe; im SAUBEREN (unannotierten) Shop-Screenshot per
    Template-NCC eindeutig bei der kalibrierten Zell-Mitte
    ``calibration.SHOP_DAGGER_ANCHOR`` lokalisierbar (NCC >= 0.70)."""

    def test_anchor_is_set(self):
        self.assertIsNotNone(cal.SHOP_DAGGER_ANCHOR)
        self.assertEqual(cal.SHOP_DAGGER_ANCHOR, (556, 59))

    def test_clean_template_bundled(self):
        # templates/shop_dolch.png ist aus der UNANNOTIERTEN Vorlage gecroppt.
        tpl = d._imread(os.path.join(d._dir(d.TEMPLATE_DIR), 'shop_dolch.png'))
        self.assertIsNotNone(tpl)

    def test_find_dolch_in_clean_shop_at_anchor(self):
        # Erkennung vor Aktion: der Dolch wird im sauberen Shop am Anker gefunden.
        shop = _load('Einkauf_Dolche', 'shop_dolche.png')
        tpl = d.load_template('dolch')
        roi = d.shop_item_roi(cal.SHOP_DAGGER_ANCHOR)
        ok, pt, ncc = d.find_shop_item(shop, tpl, roi)
        self.assertTrue(ok)
        self.assertIsNotNone(pt)
        self.assertGreaterEqual(ncc, d.NCC_ITEM)
        self.assertLessEqual(abs(pt[0] - cal.SHOP_DAGGER_ANCHOR[0]), 12)
        self.assertLessEqual(abs(pt[1] - cal.SHOP_DAGGER_ANCHOR[1]), 12)

    def test_hammer_template_does_not_match_dagger_slot(self):
        # Konfusionsfrei: das Hammer-Template trifft den Dolch-Slot NICHT.
        shop = _load('Einkauf_Dolche', 'shop_dolche.png')
        ham = d.load_template('hammer')
        roi = d.shop_item_roi(cal.SHOP_DAGGER_ANCHOR)
        ok, _pt, ncc = d.find_shop_item(shop, ham, roi)
        self.assertLess(ncc, d.NCC_ITEM)


# ---------------------------------------------------------------------------
class TestSelectionRing(unittest.TestCase):

    def test_ring_present_at_real_ring(self):
        # Echter roter Selektions-Ring (BlRG): Mitte ~ (505, 198). y_min hier 150,
        # weil DIESER Ring hoeher in der Szene liegt als der Default 240
        # (KALIBRIER-BAR -- live re-kalibrieren, P0.6).
        img = _load('Alchemist', 'metin2client_BlRGzUUM3w.png')
        self.assertTrue(d.selection_ring_present(img, (505, 198), y_min=150))

    def test_no_ring_on_hp_bar(self):
        # Die rote HP-Leiste (flach) darf NICHT als Ring durchgehen (FP-Schutz).
        img = _load('Alchemist', 'metin2client_BlRGzUUM3w.png')
        self.assertFalse(d.selection_ring_present(img, (430, 255), y_min=240))

    def test_no_ring_on_empty_grass(self):
        img = _load('Alchemist', 'metin2client_BlRGzUUM3w.png')
        self.assertFalse(d.selection_ring_present(img, (250, 420), y_min=240))

    def test_no_ring_in_npcless_scenes(self):
        for name in ('metin2client_2JJQT56i9r.png', 'metin2client_KwAggglQCf.png',
                     'metin2client_VzkvyxJMNO.png', 'metin2client_jlJmS5asq6.png'):
            img = _load('Waffenschmied', name)
            self.assertFalse(d.selection_ring_present(img, (400, 350)),
                             'false ring in %s' % name)

    def test_ring_defensive_none_near(self):
        img = _load('Alchemist', 'metin2client_BlRGzUUM3w.png')
        self.assertFalse(d.selection_ring_present(img, None))


# ---------------------------------------------------------------------------
class TestAssetBoundDetectorsNotReady(unittest.TestCase):
    """Ohne gebundelte Marker-Templates: sauberes NotReady (None/False), kein Crash."""

    def test_dialog_state_none_without_templates(self):
        img = _load('Einkauf_Hammer', 'erstgespraech1.png')
        self.assertIsNone(d.dialog_state(img))

    def test_shop_open_false_without_templates(self):
        img = _load('Einkauf_Hammer', 'shop_alchemist.png')
        self.assertFalse(d.shop_open(img))

    def test_panel_is_bag_false_without_templates(self):
        img = _load('Einkauf_Dolche', 'Inventar.png')
        self.assertFalse(d.panel_is_bag(img))

    def test_read_shop_stack_stub_none(self):
        # TODO-live-asset (P0.3): Shop-Stack-Digit-Templates fehlen -> None.
        img = _load('Einkauf_Hammer', 'shop_alchemist.png')
        slot = geo.to_client(img)[78:104, 372:400]
        self.assertIsNone(d.read_shop_stack(slot))

    def test_read_splitter_growth_stub_zero(self):
        # TODO-live-asset (P0.5): Splitter-Slot-Crop fehlt -> 0 (kein Zuwachs).
        img = _load('Alchemist', 'metin2client_BlRGzUUM3w.png')
        self.assertEqual(d.read_splitter_growth(img, img), 0)


# ---------------------------------------------------------------------------
class TestShopHeaderDiscriminationWithInjectedTemplate(unittest.TestCase):
    """Beweist: shop_open WIRD korrekt diskriminieren, sobald das Header-Template
    (P0.2) gebundelt ist -- hier via injiziertem ECHTEM 'Laden'-Crop."""

    def setUp(self):
        self._orig = d._load_template
        tpl = _laden_header_template()

        def fake(lang, word):
            if word == 'laden_header' and lang == 'de':
                return tpl
            return None
        d._load_template = fake

    def tearDown(self):
        d._load_template = self._orig

    def test_shop_open_true_in_open_shop(self):
        # Anderes Shop-Bild (Dolch-Shop) traegt denselben 'Laden'-Header.
        img = _load('Einkauf_Dolche', 'shop_dolche.png')
        self.assertTrue(d.shop_open(img))

    def test_shop_open_false_in_overworld(self):
        img = _load('Alchemist', 'metin2client_BlRGzUUM3w.png')
        self.assertFalse(d.shop_open(img))


class TestInventoryClassification(unittest.TestCase):
    """ECHTE Slot-Klassifikation ueber das kalibrierte Lattice (Glow-aware),
    gegen die User-Grundwahrheit der beiden Inventar-Bilder (CALIBRATION.md §1)."""

    def setUp(self):
        self.alch = _load('.', 'inventar_alchemist.png')
        self.waf = _load('.', 'inventar_waffenhaendler.png')

    def test_slot_is_hammer_and_dolch_groundtruth(self):
        # GT: 18/25/28/29 = Hammer; 19/20/23/24 = Dolch (Alchemist-Bild).
        for s in (18, 25, 28, 29):
            self.assertTrue(d.slot_is(self.alch, s, 'hammer'), 'slot %d' % s)
            self.assertFalse(d.slot_is(self.alch, s, 'dolch'), 'slot %d' % s)
        for s in (19, 20, 23, 24):
            self.assertTrue(d.slot_is(self.alch, s, 'dolch'), 'slot %d' % s)
            self.assertFalse(d.slot_is(self.alch, s, 'hammer'), 'slot %d' % s)

    def test_slot_21_neither_hammer_nor_dolch(self):
        # Slot 21 = Schwert (Fremd-Item) -> keine Fehlklassifikation.
        self.assertFalse(d.slot_is(self.alch, 21, 'hammer'))
        self.assertFalse(d.slot_is(self.alch, 21, 'dolch'))

    def test_slot_is_accepts_pixel_point(self):
        import energiesplitter.calibration as cal
        pt = cal.slot_center(18)
        self.assertTrue(d.slot_is(self.alch, pt, 'hammer'))

    def test_count_item_counts_slots(self):
        # Alchemist-Bild: Haemmer in 18/25/28/29 = 4 Slots; Dolche 19/20/23/24 = 4.
        self.assertEqual(d.count_item(self.alch, 'hammer'), 4)
        self.assertEqual(d.count_item(self.alch, 'dolch'), 4)

    def test_count_item_missing_template_is_zero(self):
        self.assertEqual(d.count_item(self.alch, 'bogus_item'), 0)

    def test_find_inventory_item_returns_pixel_point(self):
        ok, pt = d.find_inventory_item(self.alch, 'hammer')
        self.assertTrue(ok)
        self.assertIsNotNone(pt)
        # Punkt liegt auf einem echten Hammer-Slot-Mittelpunkt (Pixel, nicht Index).
        import energiesplitter.calibration as cal
        self.assertEqual(pt, cal.slot_center(18))

    def test_find_inventory_item_no_template_none(self):
        ok, pt = d.find_inventory_item(self.alch, 'bogus')
        self.assertFalse(ok)
        self.assertIsNone(pt)

    def test_glow_detected_on_fresh_slots(self):
        import energiesplitter.calibration as cal
        client = geo.to_client(self.alch)
        # 25/28/29 leuchten im Alchemist-Bild (frisch gekauft), 18/19 nicht.
        for s in (25, 28, 29):
            cell = d._slot_cell_bgr(client, s)
            self.assertTrue(d._slot_glowing(cell), 'slot %d should glow' % s)
        for s in (18, 19):
            cell = d._slot_cell_bgr(client, s)
            self.assertFalse(d._slot_glowing(cell), 'slot %d should not glow' % s)

    def test_free_slot_count_positive_and_excludes_occupied(self):
        free = d.free_slot_count(self.alch)
        # Es gibt belegte Slots (1..30 teils) und freie -> Zahl plausibel.
        self.assertGreater(free, 0)
        self.assertLessEqual(free, d.MAX_SLOT)

    def test_defensive_none_image(self):
        self.assertEqual(d.count_item(None, 'hammer'), 0)
        self.assertEqual(d.free_slot_count(None), 0)
        self.assertFalse(d.slot_is(None, 18, 'hammer'))
        self.assertEqual(d.find_inventory_item(None, 'hammer'), (False, None))


class TestInventorySignatureDiff(unittest.TestCase):
    """Signatur + Lande-Slot-Diff fuer die Kauf-Verifikation."""

    def test_signature_lists_occupied_slots(self):
        img = _load('.', 'inventar_alchemist.png')
        sig = d.inventory_signature(img)
        self.assertIsInstance(sig, tuple)
        labels = dict(sig)
        self.assertEqual(labels.get(18), 'hammer')
        self.assertEqual(labels.get(19), 'dolch')

    def test_diff_landing_slot_detects_single_new_slot(self):
        before = ((18, 'hammer'),)
        after = ((18, 'hammer'), (25, 'glow'))
        import energiesplitter.calibration as cal
        self.assertEqual(d.diff_landing_slot(before, after), cal.slot_center(25))

    def test_diff_landing_slot_ambiguous_none(self):
        before = ((18, 'hammer'),)
        after = ((18, 'hammer'), (25, 'glow'), (26, 'glow'))
        self.assertIsNone(d.diff_landing_slot(before, after))

    def test_diff_landing_slot_no_change_none(self):
        sig = ((18, 'hammer'),)
        self.assertIsNone(d.diff_landing_slot(sig, sig))

    def test_diff_defensive_non_tuple(self):
        self.assertIsNone(d.diff_landing_slot(None, None))


class TestSlotEmpty(unittest.TestCase):
    """slot_is_empty: Drag-Erfolgs-Beleg (Dolch-Slot leer nach Verarbeitung)."""

    def test_occupied_slot_not_empty(self):
        img = _load('.', 'inventar_alchemist.png')
        self.assertFalse(d.slot_is_empty(img, 18))   # Hammer
        self.assertFalse(d.slot_is_empty(img, 19))   # Dolch

    def test_glowing_slot_not_empty(self):
        img = _load('.', 'inventar_alchemist.png')
        self.assertFalse(d.slot_is_empty(img, 25))   # frisch gekauft (leuchtet)

    def test_defensive_none(self):
        self.assertFalse(d.slot_is_empty(None, 18))
        img = _load('.', 'inventar_alchemist.png')
        self.assertFalse(d.slot_is_empty(img, None))


class TestLoadTemplate(unittest.TestCase):

    def test_load_item_template(self):
        self.assertIsNotNone(d.load_template('hammer'))
        self.assertIsNotNone(d.load_template('dolch'))

    def test_load_npc_template(self):
        self.assertIsNotNone(d.load_template('alchemist'))
        self.assertIsNotNone(d.load_template('waffenhaendler'))

    def test_load_unknown_none(self):
        self.assertIsNone(d.load_template('does_not_exist'))

    def test_load_npc_prefix_tolerated(self):
        # Robustheit: ein versehentlich 'npc_'-praefixierter Schluessel (das
        # npc/-Verzeichnis liefert _npc_path schon) muss DENNOCH laden -- sonst
        # liefert find_npc_name still ncc=0.0 (= der "NPC nicht gefunden"-Bug
        # trotz vorhandener Vorlage).
        self.assertIsNotNone(d.load_template('npc_alchemist'))
        self.assertIsNotNone(d.load_template('npc_waffenhaendler'))


class TestNpcFoundAcrossAllPerspectives(unittest.TestCase):
    """Der NPC-Name muss in ALLEN gelieferten Perspektiven gefunden werden
    (8 Alchemist + 9 Waffenschmied). 'Mit allen Bildern validiert'-Garantie:
    schlaegt ein Kamerawinkel durch, faellt dieser Test um. Deckt die drei real
    aufgetretenen Fehler ab: (1) Template lud nicht ('npc_'-Prefix -> None ->
    ncc=0.0), (2) Suchfenster (ROI) schnitt Rand-NPCs ab, (3) Erkennung selbst.
    Nutzt die GEBUNDELTEN Templates + die Default-ROI (keine Test-Sonderwerte)."""

    def _assert_all(self, group, npc_key):
        tpl = d.load_template(npc_key)
        self.assertIsNotNone(tpl, 'Template fehlt: %s' % npc_key)
        folder = os.path.join(_FIX, group)
        names = sorted(n for n in os.listdir(folder)
                       if n.lower().endswith('.png'))
        self.assertGreaterEqual(len(names), 8, 'zu wenig Fixtures: %s' % group)
        misses = []
        for name in names:
            img = _load(group, name)
            ok, pt, ncc = d.find_npc_name(img, tpl)
            if not ok or pt is None:
                misses.append('%s (ncc=%.3f)' % (name, ncc))
        self.assertEqual(misses, [],
                         '%s in diesen Perspektiven NICHT gefunden: %s'
                         % (npc_key, misses))

    def test_alchemist_all_perspectives(self):
        self._assert_all('Alchemist', 'alchemist')

    def test_waffenhaendler_all_perspectives(self):
        self._assert_all('Waffenschmied', 'waffenhaendler')


if __name__ == '__main__':
    unittest.main()
