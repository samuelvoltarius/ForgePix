"""Independent area/flux, CFA and native file-pipeline Drizzle regressions."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import tifffile
from astropy.io import fits

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import astro
from constants import ForgePixFehler
from drizzle import DrizzleAccumulator, _intersection_area


IDENTITY = np.array([[1., 0., 0.], [0., 1., 0.]])


class DropGeometry(unittest.TestCase):
    def test_boundary_only_contact_has_zero_coverage_and_corner_triangle_has_exact_area(self):
        # The first diamond touches (1, 1) only despite overlapping both axis
        # bounds. The third cuts a right triangle with legs 1/4 from the unit box.
        touching = np.array([[.75, 1.25], [1.25, .75], [1.75, 1.25], [1.25, 1.75]])
        triangle = np.array([[.75, 1.], [1., .75], [1.25, 1.], [1., 1.25]])
        polygons = np.stack([touching, touching + .01, triangle])
        for oriented in (polygons, polygons[:, ::-1]):
            np.testing.assert_array_equal(_intersection_area(oriented), [0., 0., 1 / 32])

    def test_identity_upsampling_preserves_signed_hdr_and_aperture_flux(self):
        image = np.array([[-300., 1e6, .02], [400., -1e-5, 3.]], np.float32)
        original = image.copy()
        for scale in (1, 2, 3):
            accumulator = DrizzleAccumulator(image.shape, scale=scale, pixfrac=1, channels=1)
            accumulator.add(image, IDENTITY)
            out, weights, coverage = accumulator.finish()
            np.testing.assert_array_equal(out, np.repeat(np.repeat(image, scale, 0), scale, 1))
            np.testing.assert_allclose(weights, 1 / scale ** 2, atol=1e-7)
            self.assertTrue(coverage.all())
            self.assertAlmostEqual(float(out.sum(dtype=np.float64) / scale ** 2), float(image.sum(dtype=np.float64)), places=8)
        np.testing.assert_array_equal(image, original)

    def test_fractional_shift_has_exact_analytic_overlap(self):
        image = np.zeros((7, 7))
        image[3, 3] = 12
        transform = IDENTITY.copy()
        transform[:, 2] = [.25, .4]
        accumulator = DrizzleAccumulator(image.shape, scale=1, pixfrac=1, channels=1)
        accumulator.add(image, transform)
        out, _, _ = accumulator.finish()
        expected = 12 * np.array([[.75 * .6, .25 * .6], [.75 * .4, .25 * .4]])
        np.testing.assert_allclose(out[3:5, 3:5], expected, atol=3e-7)
        self.assertAlmostEqual(float(out.sum()), 12, places=6)
        self.assertAlmostEqual(float(accumulator.flux.sum()), 12, places=12)

    def test_weighted_mean_does_not_confuse_coverage_with_exposure_count(self):
        accumulator = DrizzleAccumulator((3, 4), scale=2, pixfrac=1, channels=1)
        accumulator.add(np.full((3, 4), -4.), IDENTITY, weight=1)
        accumulator.add(np.full((3, 4), 20.), IDENTITY, weight=3)
        out, weights, coverage = accumulator.finish()
        np.testing.assert_allclose(out, 14)
        np.testing.assert_allclose(weights, 1)
        self.assertTrue(coverage.all())

    def test_45_degree_rotation_matches_exact_diamond_area(self):
        image = np.zeros((11, 11))
        image[5, 5] = 1
        angle = np.pi / 4
        linear = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
        centre = np.array([5., 5.])
        matrix = np.c_[linear, centre - linear @ centre]
        accumulator = DrizzleAccumulator(image.shape, scale=1, pixfrac=1, channels=1)
        accumulator.add(image, matrix)
        out, weights, _ = accumulator.finish()
        self.assertAlmostEqual(float(out[5, 5]), 2 * np.sqrt(2) - 2, places=7)
        neighbor = (3 - 2 * np.sqrt(2)) / 4
        np.testing.assert_allclose(out[[4, 5, 5, 6], [5, 4, 6, 5]], neighbor, atol=2e-8)
        np.testing.assert_allclose(weights[3:8, 3:8], 1, atol=1e-7)
        self.assertAlmostEqual(float(accumulator.flux.sum()), 1, places=12)

    def test_90_degree_rotation_is_exact_without_quantization(self):
        image = np.arange(49, dtype=np.float32).reshape(7, 7) - 20
        accumulator = DrizzleAccumulator(image.shape, scale=1, pixfrac=1, channels=1)
        accumulator.add(image, [[0, -1, 6], [1, 0, 0]])
        out, weights, coverage = accumulator.finish()
        np.testing.assert_array_equal(out, np.rot90(image, -1))
        np.testing.assert_array_equal(weights, np.ones_like(weights))
        self.assertTrue(coverage.all())

    def test_affine_jacobian_changes_pixel_brightness_but_preserves_flux(self):
        image = np.zeros((21, 21))
        image[10, 10] = 400
        # Four output reference pixels replace one input pixel. The Jacobian
        # therefore divides their brightness by four rather than creating flux.
        matrix = [[2, 0, -10], [0, 2, -10]]
        accumulator = DrizzleAccumulator(image.shape, scale=2, pixfrac=1, channels=1)
        accumulator.add(image, matrix)
        out, _, _ = accumulator.finish()
        self.assertAlmostEqual(float(out.sum(dtype=np.float64) / 4), 400, places=8)
        self.assertLessEqual(float(out.max()), 100)

    def test_shrunken_drop_fractional_weights_and_holes_are_not_filled(self):
        accumulator = DrizzleAccumulator((5, 5), scale=3, pixfrac=.2, channels=1)
        accumulator.add(np.full((5, 5), -700.), IDENTITY)
        out, weights, valid = accumulator.finish()
        self.assertEqual(int(valid.sum()), 25)
        np.testing.assert_array_equal(out[~valid], 0)
        np.testing.assert_array_equal(weights[~valid], 0)
        np.testing.assert_array_equal(out[valid], -700)
        self.assertAlmostEqual(float(accumulator.weights.sum()), 25, places=10)

    def test_zero_weight_bad_pixels_do_not_contaminate_flux(self):
        image = np.full((5, 5), 8.)
        image[2, 2] = np.nan
        weight = np.ones((5, 5))
        weight[2, 2] = 0
        accumulator = DrizzleAccumulator(image.shape, scale=1, pixfrac=1, channels=1)
        accumulator.add(image, IDENTITY, weight=weight)
        out, weights, valid = accumulator.finish()
        self.assertFalse(valid[2, 2])
        self.assertEqual((out[2, 2], weights[2, 2]), (0, 0))
        np.testing.assert_array_equal(out[valid], 8)
        with self.assertRaisesRegex(ForgePixFehler, "NaN"):
            accumulator.add(image, IDENTITY)

    def test_clipped_edges_lose_only_the_portion_outside_canvas(self):
        accumulator = DrizzleAccumulator((4, 4), scale=1, pixfrac=1, channels=1)
        image = np.zeros((4, 4))
        image[0, 0] = 1
        matrix = IDENTITY.copy()
        matrix[:, 2] = [-.25, -.5]
        accumulator.add(image, matrix)
        self.assertAlmostEqual(float(accumulator.flux.sum()), .75 * .5, places=12)

    def test_smallest_supported_pixfrac_does_not_lose_area_to_cancellation(self):
        angle = .31
        matrix = np.array([[np.cos(angle), -np.sin(angle), .211],
                           [np.sin(angle), np.cos(angle), .319]])
        accumulator = DrizzleAccumulator((2, 2), scale=1, pixfrac=np.finfo(np.float32).eps, channels=1)
        accumulator.add(np.ones((2, 2)), matrix)
        # Three complete tiny drops lie inside; the fourth is wholly outside.
        self.assertAlmostEqual(float(accumulator.weights.sum()), 3., places=7)
        self.assertAlmostEqual(float(accumulator.flux.sum()), 3., places=7)

    def test_invalid_shapes_parameters_transforms_and_weights_are_hard_errors(self):
        for options in ({"scale": 0}, {"scale": 4.1}, {"scale": np.nan}, {"pixfrac": 0},
                        {"pixfrac": 1.01}, {"pixfrac": np.inf}, {"scale": True}):
            with self.subTest(options=options), self.assertRaises(ForgePixFehler):
                DrizzleAccumulator((3, 4), **options)
        accumulator = DrizzleAccumulator((3, 4), channels=1)
        for matrix in (np.eye(3), [[0, 0, 0], [0, 0, 0]], [[np.nan, 0, 0], [0, 1, 0]],
                       IDENTITY.astype(complex) + 1j):
            with self.subTest(matrix=matrix), self.assertRaises(ForgePixFehler):
                DrizzleAccumulator((3, 4), channels=1).add(np.zeros((3, 4)), matrix)
        for weight in (-1, np.inf, np.ones((4, 3)), np.full((3, 4), 1 + 2j)):
            with self.subTest(weight=weight), self.assertRaises(ForgePixFehler):
                DrizzleAccumulator((3, 4), channels=1).add(np.zeros((3, 4)), IDENTITY, weight=weight)
        with self.assertRaisesRegex(ForgePixFehler, "Bildform"):
            DrizzleAccumulator((3, 4), channels=1).add(np.zeros((4, 3)), IDENTITY)
        self.assertFalse(accumulator.add(np.ones((3, 4)), IDENTITY, weight=0))
        with self.assertRaisesRegex(ForgePixFehler, "keine gültigen"):
            accumulator.finish()

    def test_cancelled_partial_frame_cannot_be_finished_or_reused(self):
        cancel = threading.Event()
        calls = []
        def stop_during_frame():
            calls.append(True)
            if len(calls) >= 6:
                cancel.set()
            return cancel.is_set()
        accumulator = DrizzleAccumulator((7, 9), channels=3, cancel=stop_during_frame)
        with self.assertRaisesRegex(ForgePixFehler, "abgebrochen"):
            accumulator.add(np.ones((7, 9, 3)), IDENTITY)
        self.assertTrue(accumulator.weights.any(), "fixture must stop after a channel contribution")
        accumulator.cancel = None
        with self.assertRaisesRegex(ForgePixFehler, "unvollständige Beiträge"):
            accumulator.finish()
        with self.assertRaisesRegex(ForgePixFehler, "nicht weiterverwendet"):
            accumulator.add(np.ones((7, 9, 3)), IDENTITY)


class NativeDrizzlePipeline(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fits(self, name, data, **metadata):
        path = self.root / (name + ".fits")
        fits.writeto(path, np.asarray(data), fits.Header(metadata))
        return str(path)

    def run_drizzle(self, paths, **options):
        return astro.drizzle_stack(paths, log=lambda *parts: None, return_info=True, **options)

    def test_reference_is_identity_even_without_stars_and_mismatches_are_rejected(self):
        first = self.fits("ref", np.full((5, 7), -40., np.float32))
        original = hashlib.sha256(Path(first).read_bytes()).hexdigest()
        out, info = self.run_drizzle([first], scale=2)
        np.testing.assert_array_equal(out, -40)
        self.assertEqual(info["report"]["source_files"], [first])
        self.assertEqual(hashlib.sha256(Path(first).read_bytes()).hexdigest(), original)
        second = self.fits("wrong-shape", np.ones((6, 7), np.float32))
        with self.assertRaisesRegex(ForgePixFehler, "Referenzform"):
            self.run_drizzle([first, second], ref_path=first)

    def test_registration_mode_and_rejected_frame_are_reported_honestly(self):
        paths = [self.fits("frame-%d" % i, np.full((11, 15), i + 1., np.float32)) for i in range(3)]
        with patch.object(astro, "_estimate_star_shift", return_value=None) as shifts, \
                patch.object(astro, "_estimate_star_transform", side_effect=AssertionError("rotation attempted")):
            _, info = self.run_drizzle(paths, ref_path=paths[0], align_mode="shift")
        self.assertEqual(shifts.call_count, 2)
        self.assertEqual(info["report"]["source_files"], [paths[0]])
        self.assertEqual(info["report"]["skipped_files"], paths[1:])

    def test_raw_cfa_dithers_recover_each_channel_without_debayering_samples(self):
        expected = np.array([-30., 80., 220000.], np.float32)  # BGR
        for pattern in ("RGGB", "BGGR", "GRBG", "GBRG"):
            tile = np.array(["BGR".index(c) for c in pattern]).reshape(2, 2)
            # An odd sensor crop offset changes the phase; honor the FITS offset.
            tile = np.roll(tile, (-1, -1), axis=(0, 1))
            colours = tile[np.arange(10)[:, None] % 2, np.arange(12)[None, :] % 2]
            paths = [self.fits(pattern + "-%d" % i, expected[colours], BAYERPAT=pattern,
                               XBAYROFF=1, YBAYROFF=1, EXPTIME=300.) for i in range(4)]
            matrices = [np.array([[1, 0, dx], [0, 1, dy]], float) for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1))]
            out, info = self.run_drizzle(paths, scale=1, pixfrac=1, transforms=matrices)
            np.testing.assert_array_equal(out[1:, 1:], np.broadcast_to(expected, out[1:, 1:].shape))
            self.assertTrue(info["report"]["cfa_preserved"])
            self.assertTrue(info["coverage"][1:, 1:].all())
            np.testing.assert_array_equal(out[~info["coverage_channels"]], 0)

    def test_cfa_calibrates_raw_master_before_drop_and_rejects_unsafe_operations(self):
        source = self.fits("raw", np.full((6, 8), 500., np.float32), BAYERPAT="RGGB")
        out, info = self.run_drizzle([source], scale=1, dark=np.full((6, 8), 520., np.float32),
                                    flat=np.ones((6, 8), np.float32))
        np.testing.assert_array_equal(out[info["coverage_channels"]], -20)
        for options in ({"cosmetic": True}, {"banding": .5}, {"dark": np.ones((6, 8, 3))}):
            with self.subTest(options=options), self.assertRaises(ForgePixFehler):
                self.run_drizzle([source], **options)
        wrong = self.fits("no-cfa", np.ones((6, 8), np.float32))
        with self.assertRaisesRegex(ForgePixFehler, "nicht mischen"):
            self.run_drizzle([source, wrong], ref_path=source)

    def test_declared_input_coverage_is_required_and_excludes_placeholders(self):
        source = self.fits("masked", np.full((5, 7), 25., np.float32), FPCOV="input-coverage.tif")
        with self.assertRaisesRegex(ForgePixFehler, "Eingabeabdeckung fehlt"):
            self.run_drizzle([source])
        mask = np.ones((5, 7), np.uint8)
        mask[2, 3] = 0
        tifffile.imwrite(self.root / "input-coverage.tif", mask, metadata=None)
        out, info = self.run_drizzle([source], scale=1, pixfrac=1)
        self.assertFalse(info["coverage"][2, 3])
        np.testing.assert_array_equal(out[2, 3], 0)

    def test_unequal_exposures_are_not_silently_averaged(self):
        paths = [self.fits("exposure%d" % exposure, np.ones((5, 7), np.float32), EXPTIME=exposure)
                 for exposure in (30, 300)]
        with self.assertRaisesRegex(ForgePixFehler, "Belichtungszeiten"):
            self.run_drizzle(paths, do_register=False)

    def test_display_images_and_known_stretches_are_rejected(self):
        source = self.fits("stretched", np.ones((5, 7), np.float32), FPLINEAR=False)
        with self.assertRaisesRegex(ForgePixFehler, "gestreckt"):
            self.run_drizzle([source])
        for name, pixels, metadata in (("8bit.tif", np.ones((5, 7), np.uint8), {}),
                                       ("stretched.tif", np.ones((5, 7), np.float32), {"linear": False})):
            path = self.root / name
            tifffile.imwrite(path, pixels, metadata=None, description=json.dumps(metadata))
            with self.subTest(name=name), self.assertRaises(ForgePixFehler):
                self.run_drizzle([str(path)])
        with self.assertRaisesRegex(ForgePixFehler, "JPEG"):
            self.run_drizzle([str(self.root / "preview.jpg")])

    def test_tiff_declared_coverage_is_not_lost(self):
        source = self.root / "masked.tif"
        mask = np.ones((5, 7), np.uint8)
        mask[1, 1] = 0
        tifffile.imwrite(self.root / "mask.tif", mask, metadata=None)
        tifffile.imwrite(source, np.full((5, 7, 3), 5., np.float32), photometric="rgb",
                         metadata=None, description=json.dumps({"linear": True, "FPCOV": "mask.tif"}))
        image, info = self.run_drizzle([str(source)], scale=1, pixfrac=1)
        self.assertFalse(info["coverage"][1, 1])
        np.testing.assert_array_equal(image[1, 1], 0)

    def test_native_export_saves_science_and_coverage_in_matching_rgb_order(self):
        import focus_cull_stack
        source = self.fits("raw-export", np.arange(48, dtype=np.float32).reshape(6, 8) - 10,
                           BAYERPAT="RGGB", FILTER="SII/OIII", OBJECT="test", EXPTIME=300)
        image, info = self.run_drizzle([source], scale=1, pixfrac=1)
        args = SimpleNamespace(prefix="", fits_out=True, astro_stretch=False, aufnahmefilter="auto")
        output = Path(focus_cull_stack._astro_write(image, str(self.root / "work"), [source], args, astro,
                                                   drizzle_info=info))
        science_path = next(output.glob("*_astro_linear.fits"))
        science = np.moveaxis(fits.getdata(science_path), 0, -1)
        header = fits.getheader(science_path)
        channels = tifffile.imread(output / header["FPDRZCOV"])
        weights = tifffile.imread(output / header["FPDRZWGT"])
        np.testing.assert_array_equal(science, image[..., ::-1])
        np.testing.assert_array_equal(channels, info["coverage_channels"][..., ::-1])
        np.testing.assert_array_equal(weights, info["weights"][..., ::-1])
        np.testing.assert_array_equal(science[channels == 0], 0)
        self.assertEqual(header["FILTER"], "SII/OIII")
        self.assertEqual(header["NCOMBINE"], 1)
        self.assertNotIn("BAYERPAT", header)
        self.assertEqual(header["FPPIXARE"], 1)
        tiff = next(output.glob("*_astro_linear_32bit.tif"))
        np.testing.assert_array_equal(tifffile.imread(tiff), science)
        with tifffile.TiffFile(tiff) as file:
            self.assertEqual(json.loads(file.pages[0].description)["FPCOV"], "coverage.tif")
        report = json.loads((output / "drizzle_report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["export_channel_order"], "RGB")


if __name__ == "__main__":
    unittest.main()
