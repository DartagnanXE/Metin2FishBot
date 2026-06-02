"""Tests for the inventory reference builder and asset normalization.

Pure-constant assertions run without numpy; array assertions are guarded with
``@skipUnless(np is not None)`` so the suite never breaks in a lean env.
"""

import unittest

from inventory import constants
from inventory import assets
from inventory import reference

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None


class TestConstants(unittest.TestCase):
    """Pure-Python constant checks (no numpy needed)."""

    def test_slot_and_grid_geometry(self):
        self.assertEqual(constants.SLOT_PX, 32)
        self.assertEqual(constants.COLS, 5)
        self.assertEqual(constants.ROWS, 9)
        self.assertEqual(constants.SLOTS_PER_PAGE, 45)
        self.assertEqual(constants.PAGES, ('I', 'II', 'III', 'IV'))

    def test_number_band_is_rows_14_to_24_inclusive(self):
        self.assertEqual(list(constants.NUMBER_BAND_ROWS),
                         list(range(14, 25)))
        self.assertEqual(constants.UPPER_REGION_END, 14)

    def test_colour_refs(self):
        self.assertEqual(constants.EMPTY_REF, (5, 7, 3))
        self.assertEqual(constants.GLOW_REF, (176, 177, 203))

    def test_slot_indices_row_major_45(self):
        idx = constants.slot_indices()
        self.assertEqual(len(idx), 45)
        self.assertEqual(idx[0], (0, 0))
        self.assertEqual(idx[1], (0, 1))      # column advances first
        self.assertEqual(idx[5], (1, 0))      # then the row
        self.assertEqual(idx[-1], (8, 4))

    def test_default_calibration_shape(self):
        calib = constants.DEFAULT_CALIBRATION
        self.assertIn('grid', calib)
        self.assertIn('tabs', calib)
        self.assertEqual(set(calib['tabs']), {'I', 'II', 'III', 'IV'})
        self.assertEqual(calib['grid']['cols'], 5)
        self.assertEqual(calib['grid']['rows'], 9)


@unittest.skipUnless(np is not None, 'numpy required')
class TestNumberBandMask(unittest.TestCase):
    def test_band_rows_zeroed_full_alpha(self):
        alpha = np.full((32, 32), 255, dtype=np.uint8)
        mask = reference.number_band_zeroed_mask(alpha)
        # Rows 14..24 inclusive must be exactly 0.
        self.assertTrue(np.all(mask[14:25, :] == 0.0))
        # Every other row stays at full weight (1.0).
        self.assertTrue(np.all(mask[:14, :] == 1.0))
        self.assertTrue(np.all(mask[25:, :] == 1.0))

    def test_mask_equals_alpha_outside_band(self):
        rng = np.random.RandomState(1)
        alpha = rng.randint(0, 256, size=(32, 32)).astype(np.uint8)
        mask = reference.number_band_zeroed_mask(alpha)
        expected = alpha.astype(np.float32) / 255.0
        # Outside the band: mask == alpha/255.
        self.assertTrue(np.allclose(mask[:14, :], expected[:14, :]))
        self.assertTrue(np.allclose(mask[25:, :], expected[25:, :]))
        # Inside the band: zero regardless of alpha.
        self.assertTrue(np.all(mask[14:25, :] == 0.0))

    def test_input_alpha_not_mutated(self):
        alpha = np.full((32, 32), 200, dtype=np.uint8)
        snapshot = alpha.copy()
        reference.number_band_zeroed_mask(alpha)
        self.assertTrue(np.array_equal(alpha, snapshot))


@unittest.skipUnless(np is not None, 'numpy required')
class TestComposite(unittest.TestCase):
    def test_transparent_pixels_become_empty_ref(self):
        icon = np.zeros((32, 32, 4), dtype=np.uint8)
        icon[..., :3] = 200          # bright RGB ...
        icon[..., 3] = 0             # ... but fully transparent
        rgb = reference.composite_over(icon, constants.EMPTY_REF)
        for ch in range(3):
            self.assertTrue(np.allclose(rgb[..., ch], constants.EMPTY_REF[ch]))

    def test_opaque_pixels_keep_icon_colour(self):
        icon = np.zeros((32, 32, 4), dtype=np.uint8)
        icon[..., 0] = 100
        icon[..., 1] = 150
        icon[..., 2] = 50
        icon[..., 3] = 255           # fully opaque
        rgb = reference.composite_over(icon, constants.EMPTY_REF)
        self.assertTrue(np.allclose(rgb[..., 0], 100))
        self.assertTrue(np.allclose(rgb[..., 1], 150))
        self.assertTrue(np.allclose(rgb[..., 2], 50))


@unittest.skipUnless(np is not None, 'numpy required')
class TestNormalizeToSlot(unittest.TestCase):
    def test_gold_ring_32x34_to_32x32(self):
        path = [p for p in assets.icon_paths()
                if assets.name_from_path(p) == 'Gold_Ring']
        self.assertTrue(path, 'Gold_Ring icon must be bundled')
        rgba = assets.load_icon_rgba(path[0])
        self.assertIsNotNone(rgba)
        norm = assets.normalize_to_slot(rgba)
        self.assertEqual(norm.shape, (32, 32, 4))

    def test_already_32x32_passthrough(self):
        rgba = np.zeros((32, 32, 4), dtype=np.uint8)
        out = assets.normalize_to_slot(rgba)
        self.assertEqual(out.shape, (32, 32, 4))

    def test_taller_icon_centre_cropped(self):
        rgba = np.zeros((34, 32, 4), dtype=np.uint8)
        # Mark the centre rows so we can confirm symmetric crop keeps them.
        rgba[1:33, :, 0] = 123
        out = assets.normalize_to_slot(rgba)
        self.assertEqual(out.shape, (32, 32, 4))
        self.assertTrue(np.all(out[:, :, 0] == 123))


@unittest.skipUnless(np is not None, 'numpy required')
class TestBuildReference(unittest.TestCase):
    def _solid_icon(self, rgb=(80, 120, 160)):
        icon = np.zeros((32, 32, 4), dtype=np.uint8)
        icon[..., 0], icon[..., 1], icon[..., 2] = rgb
        icon[..., 3] = 255
        return icon

    def test_build_shapes_and_masksum(self):
        ref = reference.build_reference('X', self._solid_icon())
        self.assertEqual(ref.ref_rgb.shape, (32, 32, 3))
        self.assertEqual(ref.weight_mask.shape, (32, 32))
        # Fully opaque minus the 11 zeroed band rows -> (32-11)*32 weight.
        self.assertAlmostEqual(ref.mask_sum, (32 - 11) * 32, places=3)

    def test_empty_silhouette_returns_none(self):
        icon = np.zeros((32, 32, 4), dtype=np.uint8)  # alpha all 0
        self.assertIsNone(reference.build_reference('empty', icon))

    def test_band_rows_zeroed_in_built_mask(self):
        ref = reference.build_reference('X', self._solid_icon())
        self.assertTrue(np.all(ref.weight_mask[14:25, :] == 0.0))


@unittest.skipUnless(np is not None, 'numpy required')
class TestSignature(unittest.TestCase):
    def test_signature_is_deterministic(self):
        rng = np.random.RandomState(7)
        slot = rng.uniform(0, 255, size=(32, 32, 3)).astype(np.float32)
        mask = np.ones((32, 32), dtype=np.float32)
        sig1 = reference.signature_of(slot, mask)
        sig2 = reference.signature_of(slot, mask)
        self.assertIsNotNone(sig1)
        self.assertEqual(sig1, sig2)
        self.assertIsInstance(sig1, tuple)

    def test_signature_stable_under_small_noise(self):
        rng = np.random.RandomState(8)
        slot = rng.uniform(40, 60, size=(32, 32, 3)).astype(np.float32)
        mask = np.ones((32, 32), dtype=np.float32)
        sig_a = reference.signature_of(slot, mask)
        noisy = np.clip(slot + rng.normal(0, 2, slot.shape), 0, 255)
        sig_b = reference.signature_of(noisy.astype(np.float32), mask)
        # Coarse quantisation -> tiny noise does not change the signature.
        self.assertEqual(sig_a, sig_b)

    def test_signature_differs_for_different_content(self):
        mask = np.ones((32, 32), dtype=np.float32)
        dark = np.full((32, 32, 3), 10.0, dtype=np.float32)
        bright = np.full((32, 32, 3), 200.0, dtype=np.float32)
        self.assertNotEqual(reference.signature_of(dark, mask),
                            reference.signature_of(bright, mask))


if __name__ == '__main__':
    unittest.main()
