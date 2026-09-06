"""Registration must follow faint stars, not fixed Bayer sensor defects."""
from pathlib import Path
import sys
import unittest

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import astro


class FloatStarRegistration(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(409637)
        self.shape = (384, 512)
        stars = []
        while len(stars) < 70:
            xy = rng.uniform([35, 35], [477, 349])
            if all(np.linalg.norm(xy - other) > 14 for other in stars):
                stars.append(xy)
        self.stars = np.asarray(stars)
        self.peaks = rng.uniform(.001, .004, len(stars))
        self.defects = rng.integers([20, 20], [492, 364], size=(90, 2))

    def render(self, positions=None, seed=1, defects=True, sigma=1.4):
        positions = self.stars if positions is None else positions
        rng = np.random.default_rng(seed)
        raw = rng.normal(.03, .00001, self.shape).astype(np.float32)
        for (x, y), peak in zip(positions, self.peaks):
            ix, iy = int(x), int(y)
            yy, xx = np.mgrid[iy - 6:iy + 8, ix - 6:ix + 8]
            raw[iy - 6:iy + 8, ix - 6:ix + 8] += peak * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma ** 2))
        if defects:
            for x, y in self.defects:
                raw[y, x] = .95
        return astro._gray(astro.debayer_float(raw, "RGGB"))

    def test_faint_cfa_stars_override_fixed_sensor_defects(self):
        reference = self.render()
        image = self.render(self.stars + [7.4, -5.7], seed=2)
        unchanged = image.copy()
        matrix = astro._estimate_star_shift(reference, image)
        self.assertIsNotNone(matrix)
        np.testing.assert_allclose(matrix[:, 2], [-7.4, 5.7], atol=.3)
        np.testing.assert_array_equal(image, unchanged)

    def test_true_unshifted_faint_stars_remain_valid(self):
        matrix = astro._estimate_star_shift(self.render(), self.render(seed=2))
        self.assertIsNotNone(matrix)
        np.testing.assert_allclose(matrix, [[1, 0, 0], [0, 1, 0]], atol=.1)

    def test_undersampled_stars_with_measured_wings_survive_sensor_rejection(self):
        reference = self.render(sigma=.8)
        image = self.render(self.stars + [7.4, -5.7], seed=2, sigma=.8)
        matrix = astro._estimate_star_shift(reference, image)
        self.assertIsNotNone(matrix)
        np.testing.assert_allclose(matrix[:, 2], [-7.4, 5.7], atol=.3)

    def test_meridian_flip_cannot_pass_as_identity_in_shift_mode(self):
        positions = np.array(self.shape[::-1]) - 1 - self.stars
        self.assertIsNone(astro._estimate_star_shift(self.render(), self.render(positions, seed=2)))

    def test_rotate_mode_recovers_meridian_flip_with_sensor_defects(self):
        positions = np.array(self.shape[::-1]) - 1 - self.stars
        matrix = astro._estimate_star_transform_robust(self.render(), self.render(positions, seed=2))
        self.assertIsNotNone(matrix)
        mapped = positions @ matrix[:, :2].T + matrix[:, 2]
        self.assertLess(float(np.median(np.linalg.norm(mapped - self.stars, axis=1))), .3)
        np.testing.assert_allclose(matrix[:, :2], -np.eye(2), atol=.003)

    def test_registration_retains_signed_and_hdr_dynamic_ranges(self):
        reference, image = self.render(defects=False), self.render(self.stars + [4.2, 3.6], defects=False, seed=2)
        for scale, bias in ((1., -.1), (1e6, -1e5), (1e-5, 0.)):
            with self.subTest(scale=scale, bias=bias):
                matrix = astro._estimate_star_shift(reference * scale + bias, image * scale + bias)
                self.assertIsNotNone(matrix)
                np.testing.assert_allclose(matrix[:, 2], [-4.2, -3.6], atol=.3)

    def test_defects_alone_are_not_a_star_registration(self):
        raw = np.full(self.shape, .03, np.float32)
        for x, y in self.defects:
            raw[y, x] = .95
        image = astro._gray(astro.debayer_float(raw, "RGGB"))
        self.assertIsNone(astro._estimate_star_shift(image, image))

    def test_feature_fallback_cannot_restore_defect_only_identity(self):
        raw = np.full(self.shape, .03, np.float32)
        for x, y in self.defects:
            raw[y, x] = .95
        image = astro._gray(astro.debayer_float(raw, "RGGB"))
        self.assertIsNone(astro._estimate_rotation(image, image))

    def test_feature_fallback_does_not_match_fixed_defects_over_drifted_stars(self):
        matrix = astro._estimate_rotation(self.render(), self.render(self.stars + [7.4, -5.7], seed=2))
        if matrix is not None:
            np.testing.assert_allclose(matrix[:, 2], [-7.4, 5.7], atol=.3)

    def test_feature_fallback_accepts_real_unshifted_stars(self):
        matrix = astro._estimate_rotation(self.render(), self.render(seed=2))
        self.assertIsNotNone(matrix)
        np.testing.assert_allclose(matrix, [[1, 0, 0], [0, 1, 0]], atol=.1)

    def test_blank_and_nonfinite_fields_do_not_produce_stars(self):
        for image in (np.zeros((32, 40), np.float32), np.full((32, 40), -14., np.float32),
                      np.full((32, 40), np.nan, np.float32)):
            self.assertEqual(astro._star_centroids(image).shape, (0, 2))


if __name__ == "__main__":
    unittest.main()
