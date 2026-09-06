"""Scientific regressions: signed noise, flat response and isolated sensor defects."""
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from astropy.io import fits

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import astro
from constants import ForgePixFehler
from livestack import LiveStack


class CalibrationPrecision(unittest.TestCase):
    def test_dark_subtraction_retains_zero_mean_noise(self):
        noise = np.random.default_rng(8).uniform(.0001, .01, (50, 100)).astype(np.float32)
        noise = np.concatenate([noise, -noise], axis=0)
        dark = np.full(noise.shape, .2, np.float32)
        light = dark + noise
        corrected = astro.calibrate(light, dark)
        self.assertLess(abs(float(corrected.mean(dtype=np.float64))), 1e-9)
        self.assertLess(float(corrected.min()), -.009)
        self.assertGreater(float(corrected.max()), .009)
        np.testing.assert_array_equal(light, dark + noise)
        np.testing.assert_array_equal(dark, np.float32(.2))

    def test_weak_positive_flat_response_is_not_artificially_floored(self):
        flat = np.tile(np.linspace(.001, 1, 64, dtype=np.float32), (48, 1))
        signal = np.tile(np.linspace(.1, 2, 48, dtype=np.float32)[:, None], (1, 64))
        dark = np.full(flat.shape, .02, np.float32)
        light = signal * (flat / flat.mean(dtype=np.float64)) + dark
        corrected = astro.calibrate(light, dark, flat)
        np.testing.assert_allclose(corrected, signal, rtol=2e-6, atol=2e-6)
        self.assertGreater(float(corrected.max()), 1.9)

    def test_zero_or_negative_flat_pixels_are_actionable(self):
        for value in (0, -.01):
            flat = np.ones((16, 16), np.float32)
            flat[4, 4] = value
            with self.assertRaisesRegex(ForgePixFehler, "nichtpositive Pixel"):
                astro.calibrate(np.ones_like(flat), flat=flat)

    def test_signed_cfa_calibration_survives_cache_and_integration(self):
        raw = np.full((24, 28), .2, np.float32)
        raw[::2, ::2] -= .01
        raw[1::2, 1::2] += .01
        dark = np.full(raw.shape, .2, np.float32)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "Light.fit"
            fits.writeto(source, raw, fits.Header({"BAYERPAT": "RGGB"}))
            image = astro.read_calibrated(str(source), dark)
            cache = Path(folder) / "cache.tif"
            astro._warp_and_save(image, np.eye(2, 3, dtype=np.float32),
                                  (28, 24), str(cache), 1)
            result = astro.stack([str(cache)], method="average", normalize=False, log=lambda *a: None)
            np.testing.assert_allclose(result[..., 2], -.01, atol=2e-8)
            np.testing.assert_allclose(result[..., 0], .01, atol=2e-8)
            np.testing.assert_array_equal(fits.getdata(source), raw)

    def test_no_master_returns_an_independent_signed_copy(self):
        source = np.array([[-.1, 2.2]], np.float32)
        result = astro.calibrate(source)
        np.testing.assert_array_equal(result, source)
        result[:] = 0
        self.assertEqual(float(source[0, 0]), float(np.float32(-.1)))

    def test_banding_correction_does_not_depend_on_positive_pedestal(self):
        source = np.random.default_rng(4).normal(-.1, .001, (80, 100)).astype(np.float32)
        source[::2] += .003
        corrected = astro.fix_banding(source)
        shifted = astro.fix_banding(source + .2) - .2
        np.testing.assert_allclose(corrected, shifted, atol=3e-8)
        self.assertLess(float(corrected.max()), 0)


class CosmeticPrecision(unittest.TestCase):
    def test_defects_removed_without_clipping_or_quantizing_the_local_sky(self):
        for background in (-.2, 2.000013, 2e-8):
            with self.subTest(background=background):
                image = np.full((40, 50, 3), background, np.float32)
                amplitude = max(abs(background), 1e-8) * 5
                image[8, 10] += amplitude
                image[30, 35] -= amplitude
                result = astro.cosmetic_correct(image)
                np.testing.assert_array_equal(result, np.float32(background))
                self.assertNotEqual(float(image[8, 10, 0]), float(result[8, 10, 0]))

    def test_resolved_stellar_psfs_and_flux_preserved(self):
        y, x = np.mgrid[:128, :128]
        sky = np.full((128, 128), .02, np.float32)
        for cx, cy, sigma in ((32, 32, 1.6), (80, 80, 2.5), (35, 95, 3.1)):
            sky += .8 * np.exp(-((x-cx)**2 + (y-cy)**2) / (2*sigma*sigma))
        damaged = sky.copy()
        damaged[15, 15], damaged[112, 112] = 2, -.9
        result = astro.cosmetic_correct(damaged)
        np.testing.assert_array_equal(result, sky)
        self.assertEqual(float(result.sum(dtype=np.float64)), float(sky.sum(dtype=np.float64)))

    def test_strength_zero_preserves_data(self):
        source = np.random.default_rng(1).uniform(-1, 3, (20, 30)).astype(np.float32)
        np.testing.assert_array_equal(astro.cosmetic_correct(source, 0), source)
        for strength in (-1, np.nan, np.inf):
            with self.assertRaises(ForgePixFehler):
                astro.cosmetic_correct(source, strength)


class LiveLinearRange(unittest.TestCase):
    def test_live_output_preserves_signed_and_high_values(self):
        live = LiveStack(registrieren=False, gewichten=False, log=lambda *a: None)
        frame = np.full((20, 24, 3), (-.01, .2, 2.1), np.float32)
        for _ in range(5):
            self.assertTrue(live.hinzufuegen(frame))
        np.testing.assert_allclose(live.ergebnis(), frame, atol=1e-7)
        with tempfile.TemporaryDirectory() as folder:
            checkpoint = str(Path(folder) / "state.npz")
            live.speichern(checkpoint)
            resumed = LiveStack.laden(checkpoint, log=lambda *a: None)
            self.assertIsNotNone(resumed)
            np.testing.assert_array_equal(resumed.ergebnis(), live.ergebnis())


if __name__ == "__main__":
    unittest.main()
