import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import star_color
import photometric
from constants import ForgePixFehler


def field():
    rng = np.random.default_rng(743)
    y, x = np.mgrid[:220, :260]
    stars = np.zeros((220, 260), np.float64)
    points = [(xx + .27, yy - .18) for yy in (30, 65, 100, 135, 170) for xx in (30, 65, 100, 135, 170, 205)]
    for px, py in points:
        stars += rng.uniform(.2, .6) * np.exp(-((x - px) ** 2 + (y - py) ** 2) / (2 * 1.5 ** 2))
    color = np.array([.6, 1., 1.8])
    sky = np.stack([.01 + x * .0001, .03 + y * .0001, .08 + x * .0002 + y * .0001], axis=-1)
    noise = rng.normal(0, .0001, sky.shape)
    return (stars[..., None] * color + sky + noise).astype(np.float32), np.asarray(points), color


class StellarWhiteBalance(unittest.TestCase):
    def test_recovers_known_gain_despite_colored_sky_gradients(self):
        source, points, color = field()
        before = source.copy()
        out, info = star_color.balance(source, positions=points, return_info=True, log=lambda *a: None)
        self.assertTrue(info["applied"])
        self.assertFalse(info["catalog_calibration"])
        np.testing.assert_allclose(info["gains_bgr"], 1 / color, rtol=.002)
        np.testing.assert_array_equal(source, before)
        self.assertEqual(out.dtype, np.float32)

    def test_float_detector_finds_faint_stars_without_unit_threshold(self):
        source, _, color = field()
        source *= np.float32(1e-5)
        _, info = star_color.balance(source, return_info=True, log=lambda *a: None)
        self.assertTrue(info["applied"])
        self.assertGreaterEqual(info["stars_used"], 20)
        np.testing.assert_allclose(info["gains_bgr"], 1 / color, rtol=.003)

    def test_signed_hdr_and_scale_invariance(self):
        source, points, _ = field()
        source[5, 5] = [-.1, 3., 4.]
        out, info = star_color.balance(source, positions=points, neutralize=False, return_info=True, log=lambda *a: None)
        larger, large_info = star_color.balance(source * 600, positions=points, neutralize=False, return_info=True, log=lambda *a: None)
        self.assertLess(out.min(), 0)
        self.assertGreater(out.max(), 1)
        np.testing.assert_allclose(large_info["gains_bgr"], info["gains_bgr"], rtol=2e-6)
        np.testing.assert_allclose(larger, out * 600, rtol=3e-6, atol=2e-5)

    def test_saturation_references_rejected(self):
        source, points, color = field()
        for px, py in points[:4]:
            x, y = int(round(px)), int(round(py))
            source[y - 2:y + 3, x - 2:x + 3] = 2
        _, info = star_color.balance(source, positions=points, saturation=1.5, return_info=True, log=lambda *a: None)
        self.assertEqual(info["rejected"]["saturation"], 4)
        np.testing.assert_allclose(info["gains_bgr"], 1 / color, rtol=.003)

    def test_atypical_stellar_colors_do_not_dominate_the_fit(self):
        source, points, color = field()
        yy, xx = np.mgrid[:source.shape[0], :source.shape[1]]
        for px, py in points[:4]:
            mask = (xx - px) ** 2 + (yy - py) ** 2 <= 36
            sky = .08 + xx * .0002 + yy * .0001
            source[..., 2][mask] = sky[mask] + 3 * (source[..., 2][mask] - sky[mask])
        _, info = star_color.balance(source, positions=points, return_info=True, log=lambda *a: None)
        self.assertEqual(info["rejected"]["color_outlier"], 4)
        np.testing.assert_allclose(info["gains_bgr"], 1 / color, rtol=.003)

    def test_failed_external_narrowband_does_not_use_broadband_fallback(self):
        source, _, _ = field()
        with patch.object(photometric, "siril_spcc", side_effect=RuntimeError("unavailable")), \
                patch.object(star_color, "balance", side_effect=AssertionError("broadband fallback")):
            out = photometric.run_pcc(source, prefer="siril", narrowband=True, log=lambda *a: None)
        np.testing.assert_array_equal(out, source)

    def test_constant_field_stays_unchanged_without_fallback(self):
        source = np.full((60, 70, 3), [-.1, .04, 3.], np.float32)
        out, info = star_color.balance(source, return_info=True, log=lambda *a: None)
        self.assertFalse(info["applied"])
        np.testing.assert_array_equal(out, source)

    def test_strength_is_exact_linear_blend(self):
        source, points, _ = field()
        full = star_color.balance(source, positions=points, log=lambda *a: None)
        half = star_color.balance(source, .5, positions=points, log=lambda *a: None)
        np.testing.assert_allclose(half, .5 * source + .5 * full, rtol=3e-6, atol=1e-7)

    def test_bad_pixels_or_strength_fail(self):
        source, _, _ = field()
        with self.assertRaises(ForgePixFehler):
            star_color.balance(source, float("nan"))
        source[0, 0, 0] = np.inf
        with self.assertRaises(ForgePixFehler):
            star_color.balance(source)

    def test_nonfinite_catalog_coordinates_are_skipped(self):
        source, points, _ = field()
        rows, rejected = star_color.measure(source, np.concatenate([points, [[np.nan, 1], [np.inf, 2]]]))
        self.assertEqual(rejected["position"], 2)
        self.assertEqual(len(rows), len(points))

    def test_rounded_border_positions_are_rejected_without_truncated_patches(self):
        source = np.ones((100, 100, 3), np.float32)
        rows, rejected = star_color.measure(source, [[84.7, 30], [30, 84.7]])
        self.assertFalse(rows)
        self.assertEqual(rejected["position"], 2)

    def test_four_equal_unsaturated_core_pixels_are_valid_references(self):
        yy, xx = np.mgrid[:220, :260]
        source = np.full((220, 260, 3), .01, np.float64)
        points = [(x + .5, y + .5) for y in (30, 65, 100, 135, 170) for x in (30, 65, 100, 135, 170, 205)]
        color = np.array([.6, 1., 1.8])
        for x, y in points:
            source += .3 * np.exp(-((xx - x)**2 + (yy - y)**2) / (2 * 1.5**2))[..., None] * color
        _, info = star_color.balance(source.astype(np.float32), positions=points, return_info=True, log=lambda *a: None)
        self.assertTrue(info["applied"])
        self.assertEqual(info["stars_used"], len(points))
        np.testing.assert_allclose(info["gains_bgr"], 1 / color, rtol=1e-6)

    def test_auto_is_native_without_solver_or_network(self):
        source, _, _ = field()
        with patch.object(photometric, "siril_available", side_effect=AssertionError("external lookup")), \
                patch.object(photometric, "lokal_pcc", side_effect=AssertionError("catalog lookup")), \
                patch.object(photometric, "gaia_pcc", side_effect=AssertionError("network lookup")):
            out = photometric.run_pcc(source, log=lambda *a: None)
        self.assertEqual(out.shape, source.shape)

    def test_native_narrowband_is_unchanged(self):
        source, _, _ = field()
        out = photometric.run_pcc(source, prefer="auto", narrowband=True, log=lambda *a: None)
        np.testing.assert_array_equal(out, source)

    def test_external_fits_bridge_preserves_signed_hdr(self):
        source = np.linspace(-.1, 3, 180, dtype=np.float32).reshape(6, 10, 3)
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "linear.fits")
            photometric._write_linear_fits(source, path)
            out = photometric._read_fits_bgr(path)
        np.testing.assert_array_equal(out, source)


if __name__ == "__main__":
    unittest.main()
