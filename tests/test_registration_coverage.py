"""Float registration cache and exclusion of unmeasured border pixels."""
import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
import tifffile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import astro
from constants import ForgePixFehler


class RegistrationCoverage(unittest.TestCase):
    def test_registration_does_not_quantize_float_or_clip(self):
        rng = np.random.default_rng(3)
        source = rng.uniform(.001, 1.2, (24, 24, 3)).astype(np.float32)
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "registered.tif")
            astro._warp_and_save(source, None, (24, 24), path, 1)
            np.testing.assert_array_equal(astro._read_float(path), source)
            self.assertEqual(tifffile.imread(path).dtype, np.float32)

    def test_uncovered_borders_are_excluded_by_every_integrator(self):
        source = np.full((24, 24, 3), .234567, np.float32)
        with tempfile.TemporaryDirectory() as folder:
            paths = [str(Path(folder) / f"r{i}.tif") for i in range(2)]
            for path, shift in zip(paths, (3, -3)):
                astro._warp_and_save(source.copy(), np.array([[1., 0, shift], [0, 1, 0]], np.float32),
                                     (24, 24), path, 1)
            for method in ("average", "median", "max", "sigma", "winsor", "linearfit"):
                with self.subTest(method=method):
                    result = astro.stack(paths, method=method, normalize=False, weight=False,
                                         log=lambda *a: None)
                    np.testing.assert_allclose(result, source, atol=1e-6)

    def test_normalization_compares_same_sky_region(self):
        gradient = np.broadcast_to(np.linspace(.05, .7, 32)[None, :, None], (24, 32, 3)).astype(np.float32)
        with tempfile.TemporaryDirectory() as folder:
            paths = [str(Path(folder) / f"r{i}.tif") for i in range(2)]
            for path in paths:
                astro._warp_and_save(gradient.copy(), None, (32, 24), path, 1)
            mask = np.ones((24, 32), np.uint8)
            mask[:, :10] = 0
            tifffile.imwrite(paths[1] + ".coverage.tif", mask)
            result = astro.stack(paths, method="average", normalize=True, weight=False, log=lambda *a: None)
            np.testing.assert_allclose(result, gradient, atol=1e-6)

    def test_missing_coverage_is_an_error(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "registered.tif")
            astro._warp_and_save(np.ones((24, 24, 3), np.float32), None, (24, 24), path, 1)
            Path(path + ".coverage.tif").unlink()
            with self.assertRaisesRegex(ForgePixFehler, "Abdeckung fehlt"):
                astro.stack([path, path], method="average", normalize=False, weight=False, log=lambda *a: None)

    def test_exported_support_excludes_empty_border_but_keeps_measured_zero(self):
        source = np.full((24, 24, 3), .25, np.float32)
        source[12, 12] = 0
        with tempfile.TemporaryDirectory() as folder:
            paths = [str(Path(folder) / f"r{i}.tif") for i in range(3)]
            expected = np.ones(source.shape[:2], bool)
            expected[:, :3] = False
            for path in paths:
                astro._warp_and_save(source.copy(), None, (24, 24), path, 1)
                tifffile.imwrite(path + ".coverage.tif", expected.astype(np.uint8))
            for method in ("average", "median", "max", "sigma", "winsor", "linearfit"):
                with self.subTest(method=method):
                    options = dict(method=method, normalize=False, log=lambda *a: None)
                    legacy = astro.stack(paths, **options)
                    result, info = astro.stack(paths, return_info=True, **options)
                    np.testing.assert_array_equal(result, legacy)
                    np.testing.assert_array_equal(info["coverage"], expected)
                    self.assertTrue(info["coverage"][12, 12])
                    self.assertFalse(info["report"]["variance_available"])
                    self.assertFalse(info["report"]["per_pixel_exposure_available"])

    def test_support_uses_accepted_channels_not_union_of_input_masks(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [str(Path(folder) / f"r{i}.tif") for i in range(2)]
            for path, value in zip(paths, (.2, .8)):
                source = np.full((24, 24, 3), .4, np.float32)
                source[12, 12, 0] = value
                astro._warp_and_save(source, None, (24, 24), path, 1)
            result, info = astro.stack(paths, method="sigma", kappa=.1, sigma_iters=1,
                normalize=False, return_info=True, log=lambda *a: None)
            self.assertEqual(result[12, 12, 0], 0)
            np.testing.assert_allclose(result[12, 12, 1:], .4)
            self.assertFalse(info["coverage"][12, 12])
            self.assertEqual(np.count_nonzero(~info["coverage"]), 1)
