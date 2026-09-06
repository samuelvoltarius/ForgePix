"""Signed/HDR wavelet contracts, with independent reconstruction checks."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import wavelet


class ScientificWaveletTests(unittest.TestCase):
    def test_neutral_float_path_is_exact_and_owns_result(self):
        for dtype in (np.float32, np.float64):
            for channels in (1, 3):
                with self.subTest(dtype=dtype, channels=channels):
                    image = np.tile(np.array([-.2, -0., .5, 300.], dtype=dtype), (17, 9))
                    if channels == 3:
                        image = np.stack((image, image * .4, image * 1.7), axis=-1)
                    image.setflags(write=False)
                    before = image.tobytes()
                    result = wavelet.wavelet_sharpen(image, gains=(1., 1.), denoise=0., levels=4)
                    self.assertEqual(result.dtype, image.dtype)
                    self.assertEqual(result.tobytes(), before)
                    self.assertFalse(np.shares_memory(result, image))
                    result.flat[0] = 9
                    self.assertEqual(image.tobytes(), before)
                    self.assertEqual(wavelet.wavelet_denoise(image, strength=0.).tobytes(), before)

    def test_atrous_reconstructs_signed_hdr_with_native_float_precision(self):
        yy, xx = np.mgrid[:33, :38]
        for dtype, tolerance in ((np.float32, 1e-4), (np.float64, 2e-12)):
            with self.subTest(dtype=dtype):
                image = (-40 + 420 * np.sin(xx / 5.) * np.cos(yy / 7.)).astype(dtype)
                before = image.copy()
                details, remainder = wavelet.atrous(image, levels=4)
                reconstructed = remainder.copy()
                for detail in details:
                    self.assertEqual(detail.dtype, np.dtype(dtype))
                    reconstructed += detail
                self.assertEqual(remainder.dtype, np.dtype(dtype))
                np.testing.assert_allclose(reconstructed, image, rtol=0, atol=tolerance)
                np.testing.assert_array_equal(image, before)

    def test_float64_details_are_not_rounded_to_float32(self):
        yy, xx = np.mgrid[:12, :15]
        image = 1e8 + (np.sin(xx) + np.cos(yy)) * 1e-4
        details, remainder = wavelet.atrous(image, levels=1)
        # Independent direct B3 convolution with symmetric extension matches
        # the documented half-sample symmetric border, without OpenCV calls.
        kernel = np.array([1, 4, 6, 4, 1], np.float64) / 16
        padded = np.pad(image, 2, mode="symmetric")
        smooth = np.zeros_like(image)
        for y in range(5):
            for x in range(5):
                smooth += kernel[y] * kernel[x] * padded[y:y + image.shape[0], x:x + image.shape[1]]
        self.assertGreater(float(np.max(np.abs(details[0]))), 1e-5)
        np.testing.assert_allclose(remainder, smooth, rtol=0, atol=8 * np.spacing(1e8))
        np.testing.assert_allclose(details[0], image - smooth, rtol=0, atol=8 * np.spacing(1e8))
        sharpened = wavelet.wavelet_sharpen(image, gains=(1.5,), denoise=0.)
        self.assertEqual(sharpened.dtype, np.dtype(np.float64))
        self.assertGreater(float(np.max(np.abs(sharpened - image))), 1e-6)

    def test_non_neutral_gain_has_expected_effect_without_clipping_or_input_mutation(self):
        for dtype, tolerance in ((np.float32, 2e-4), (np.float64, 2e-12)):
            for background in (-40., 400.):
                with self.subTest(dtype=dtype, background=background):
                    image = np.full((21, 25), background, dtype=dtype)
                    image[10, 12] += 20
                    before = image.copy()
                    detail, _ = wavelet.atrous(image, levels=1)
                    result = wavelet.wavelet_sharpen(image, gains=(2.,), denoise=0.)
                    np.testing.assert_allclose(result, image + detail[0], rtol=0, atol=tolerance)
                    self.assertGreater(result[10, 12], image[10, 12])
                    self.assertEqual(result.dtype, image.dtype)
                    np.testing.assert_array_equal(image, before)
                    if background < 0:
                        self.assertLess(float(result.max()), 0.)
                    else:
                        self.assertGreater(float(result.min()), 255.)

    def test_bgr_delta_preserves_channel_differences_without_clipping(self):
        yy, xx = np.mgrid[:29, :31]
        base = np.sin(xx) * 3 + np.cos(yy) * 2
        image = np.stack((base - 50, base + 300, base + 700), axis=-1)
        before = image.copy()
        result = wavelet.wavelet_sharpen(image, gains=(1.6, .8), denoise=0.)
        self.assertGreater(float(np.max(np.abs(result - image))), .1)
        np.testing.assert_allclose(result[..., 1] - result[..., 0], image[..., 1] - image[..., 0], rtol=0, atol=1e-12)
        np.testing.assert_allclose(result[..., 2] - result[..., 1], image[..., 2] - image[..., 1], rtol=0, atol=1e-12)
        self.assertLess(float(result[..., 0].max()), 0.)
        self.assertGreater(float(result[..., 1].min()), 255.)
        np.testing.assert_array_equal(image, before)

    def test_denoise_reduces_known_high_frequency_error_on_signed_hdr_background(self):
        yy, xx = np.mgrid[:48, :52]
        alternating = ((xx + yy) % 2) * 2 - 1
        for dtype in (np.float32, np.float64):
            for background in (-12., 500.):
                with self.subTest(dtype=dtype, background=background):
                    image = (background + alternating * .03).astype(dtype)
                    result = wavelet.wavelet_denoise(image, strength=.8, levels=3)
                    self.assertEqual(result.dtype, image.dtype)
                    self.assertTrue(np.isfinite(result).all())
                    self.assertLess(float(np.mean((result - background) ** 2)), float(np.mean((image - background) ** 2)))
                    self.assertAlmostEqual(float(result.mean()), background, delta=1e-4)

    def test_integer_photographic_range_dtype_and_impulse_clipping_are_preserved(self):
        for dtype, maximum in ((np.uint8, 255), (np.uint16, 65535)):
            with self.subTest(dtype=dtype):
                image = np.zeros((21, 25), dtype=dtype)
                image[10, 12] = maximum
                result = wavelet.wavelet_sharpen(image, gains=(2.,), denoise=0.)
                self.assertEqual(result.dtype, image.dtype)
                np.testing.assert_array_equal(result, image)
                flat = np.full((21, 25, 3), maximum // 3, dtype=dtype)
                smooth = wavelet.wavelet_denoise(flat, strength=1.)
                np.testing.assert_array_equal(smooth, flat)

    def test_nonfinite_complex_bad_shape_and_parameters_fail_before_identity(self):
        for image in (np.array([[np.nan]]), np.array([[np.inf]]), np.array([[-np.inf]]),
                      np.array([[1 + 2j]]), np.zeros((2, 2, 4)), np.zeros((0, 4)), np.ones(3)):
            with self.subTest(shape=image.shape, dtype=image.dtype):
                with self.assertRaises(ValueError):
                    wavelet.wavelet_sharpen(image, gains=(1.,), denoise=0.)
        image = np.ones((8, 8), np.float32)
        for kwargs in ({"gains": ()}, {"gains": (float("nan"),)}, {"gains": (1 + 2j,)},
                       {"denoise": float("inf")}, {"denoise": -.1}, {"denoise": np.complex64(1 + 1j)},
                       {"levels": -1}, {"levels": 1.5}, {"levels": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                wavelet.wavelet_sharpen(image, **kwargs)

    def test_finite_overflow_is_reported_instead_of_returning_infinity(self):
        image = np.zeros((8, 8), np.float64)
        image[3, 3] = 1e307
        with self.assertRaises(ValueError):
            wavelet.wavelet_sharpen(image, gains=(100.,), denoise=0.)


if __name__ == "__main__":
    unittest.main()
