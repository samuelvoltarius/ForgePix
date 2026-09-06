"""Independent Float64 reference checks for Sigma/Winsor TIFF integration."""
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import tifffile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import astro


def batch_reference(frames, masks, method, kappa=2.5, iterations=2):
    """Per-pixel list calculation, separate from the streaming Welford engine."""
    values = np.asarray(frames, dtype=np.float64)
    result = np.zeros(values.shape[1:], dtype=np.float32)
    supported = np.zeros(result.shape, dtype=bool)
    for y, x, channel in np.ndindex(result.shape):
        samples = values[:, y, x, channel][masks[:, y, x]]
        if not samples.size:
            continue
        center = np.mean(samples, dtype=np.float64)
        scatter = np.std(samples, dtype=np.float64, ddof=0)
        low, high = center - kappa * scatter, center + kappa * scatter
        for _ in range(iterations - 1):
            retained = samples[(samples >= low) & (samples <= high)]
            if retained.size:
                center = np.mean(retained, dtype=np.float64)
                scatter = np.std(retained, dtype=np.float64, ddof=0)
                low, high = center - kappa * scatter, center + kappa * scatter
        retained = (np.clip(samples, low, high) if method == "winsor" else
                    samples[(samples >= low) & (samples <= high)])
        if retained.size:
            result[y, x, channel] = np.mean(retained, dtype=np.float64)
            supported[y, x, channel] = True
    return result, supported.all(axis=2)


class StackStatistics(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def write_frames(self, frames, masks=None):
        if masks is None:
            masks = np.ones(np.asarray(frames).shape[:3], dtype=bool)
        paths = []
        for index, (frame, mask) in enumerate(zip(frames, masks)):
            path = self.folder / f"reg_{index:04d}.tif"
            tifffile.imwrite(path, np.asarray(frame, np.float32)[..., ::-1],
                photometric="rgb", metadata=None,
                description="ForgePix registration; coverage=" + path.name + ".coverage.tif")
            tifffile.imwrite(str(path) + ".coverage.tif", mask.astype(np.uint8), metadata=None)
            paths.append(str(path))
        return paths

    def test_identical_arbitrary_signed_hdr_samples_are_bit_exact(self):
        rng = np.random.default_rng(7342189)
        original = rng.uniform(-2., 6., (48, 64, 3)).astype(np.float32)
        original[:4, :16] = rng.uniform(-.04, .15, (4, 16, 3)).astype(np.float32)
        paths = self.write_frames([original] * 7)
        for count in (2, 3, 7):
            for method in ("sigma", "winsor"):
                with self.subTest(count=count, method=method):
                    result, info = astro.stack(paths[:count], method=method,
                        normalize=True, return_info=True, log=lambda *a: None)
                    self.assertEqual(result.dtype, np.float32)
                    np.testing.assert_array_equal(result, original)
                    self.assertTrue(info["coverage"].all())

    def test_identical_extreme_hdr_does_not_overflow_float32_products(self):
        original = np.broadcast_to(np.array([1e25, -2e25, 1e-25], np.float32), (4, 6, 3)).copy()
        paths = self.write_frames([original] * 7)
        for method in ("sigma", "winsor"):
            with self.subTest(method=method), np.errstate(over="raise", invalid="raise"):
                result, info = astro.stack(paths, method=method, normalize=False,
                    return_info=True, log=lambda *a: None)
                np.testing.assert_array_equal(result, original)
                self.assertTrue(info["coverage"].all())

    def test_small_real_scatter_and_outliers_match_centered_batch_reference(self):
        levels = np.array([.1, -.7, 1e5, -1e6, 1e25, 1e-20], np.float32)
        original = np.broadcast_to(levels[None, :, None], (4, 6, 3)).copy()
        unit = 2 * np.spacing(np.abs(original)).astype(np.float64)
        offsets = np.array([-3, -2, -1, 0, 1, 2, 3, 4, 64], np.float64)
        frames = (original.astype(np.float64)[None] + offsets[:, None, None, None] * unit).astype(np.float32)
        masks = np.ones(frames.shape[:3], bool)
        masks[:, 0, 0] = False
        masks[::2, 1, 1] = False
        frames[~masks] = 12345.  # Unsupported placeholders must not affect moments.
        paths = self.write_frames(frames, masks)
        for method in ("sigma", "winsor"):
            with self.subTest(method=method):
                expected, coverage = batch_reference(frames, masks, method)
                result, info = astro.stack(paths, method=method, normalize=False,
                    return_info=True, log=lambda *a: None)
                np.testing.assert_array_equal(result, expected)
                np.testing.assert_array_equal(info["coverage"], coverage)
                # Real scatter remains measurable; no arbitrary noise floor or
                # shortcut that simply returns the first sample may pass.
                self.assertNotEqual(result[2, 0, 0], frames[0, 2, 0, 0])
                self.assertLess(result[2, 0, 0], frames[:, 2, 0, 0].mean(dtype=np.float64))

    def test_empty_refinement_keeps_prior_bounds_and_real_sigma_rejection(self):
        frames = np.full((2, 4, 6, 3), .4, np.float32)
        frames[:, 1, 2, 0] = (.2, .8)
        paths = self.write_frames(frames)
        for method in ("sigma", "winsor"):
            for iterations in (2, 4):
                with self.subTest(method=method, iterations=iterations):
                    expected, coverage = batch_reference(frames,
                        np.ones(frames.shape[:3], bool), method, kappa=.1, iterations=iterations)
                    result, info = astro.stack(paths, method=method, kappa=.1,
                        sigma_iters=iterations, normalize=False, return_info=True, log=lambda *a: None)
                    np.testing.assert_array_equal(result, expected)
                    np.testing.assert_array_equal(info["coverage"], coverage)
                    if method == "sigma":
                        self.assertEqual(result[1, 2, 0], 0)
                        self.assertEqual(np.count_nonzero(~info["coverage"]), 1)
                    else:
                        self.assertEqual(result[1, 2, 0], np.float32(.5))
                        self.assertTrue(info["coverage"].all())

    def test_weighted_identical_frames_and_preview_preserve_float32_contract(self):
        rng = np.random.default_rng(7342191)
        original = rng.uniform(-.04, 2., (24, 32, 3)).astype(np.float32)
        paths = self.write_frames([original] * 3)
        for method in ("sigma", "winsor"):
            previews = []
            result = astro.stack(paths, method=method, weight=True, normalize=True,
                preview_cb=lambda image, i, n: previews.append(image), log=lambda *a: None)
            np.testing.assert_array_equal(result, original)
            self.assertEqual(result.dtype, np.float32)
            self.assertTrue(previews)
            self.assertTrue(all(image.dtype == np.float32 for image in previews))


if __name__ == "__main__":
    unittest.main()
