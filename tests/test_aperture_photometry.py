"""Analytic pixel-integrated stars and independent noise realizations for P0."""
import json
from pathlib import Path
import sys
import threading
import unittest

import numpy as np
from scipy.ndimage import gaussian_filter
from scipy.special import erf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
from aperture_photometry import measure_stars


def gaussian(shape, center, total_flux, sigma=1.2):
    """Analytic integral in each square detector pixel, independent of apertures."""
    x, y = center
    xx, yy = np.arange(shape[1]), np.arange(shape[0])
    px = .5 * (erf((xx + .5 - x) / (np.sqrt(2) * sigma)) - erf((xx - .5 - x) / (np.sqrt(2) * sigma)))
    py = .5 * (erf((yy + .5 - y) / (np.sqrt(2) * sigma)) - erf((yy - .5 - y) / (np.sqrt(2) * sigma)))
    return total_flux * np.outer(py, px)


def scene(center=(48.3, 47.7), shape=(96, 100), flux=1200., sigma=1.2):
    yy, xx = np.indices(shape)
    return -3.5 + .023 * (xx - center[0]) - .017 * (yy - center[1]) + gaussian(shape, center, flux, sigma)


class AperturePhotometryTests(unittest.TestCase):
    def measure(self, image, positions=((48.3, 47.7),), **kwargs):
        options = dict(coverage=True, saturation=1e9, variance=.16)
        options.update(kwargs)
        return measure_stars(image, positions, **options)

    def test_known_rgb_flux_gradient_signed_hdr_and_subpixel_phases(self):
        expected = np.array([1600., 950., 420.])
        phases = [(48., 48.), (48.2, 47.5), (48.75, 47.4)]
        measured = []
        for center in phases:
            yy, xx = np.indices((96, 100))
            bases = np.array([-15., 8., 20000.])
            gradients_x, gradients_y = np.array([.02, -.01, .043]), np.array([-.015, .016, -.027])
            image = np.stack([gaussian((96, 100), center, flux) for flux in expected], axis=-1)
            image += bases + (xx - center[0])[..., None] * gradients_x + (yy - center[1])[..., None] * gradients_y
            original = image.tobytes()
            report = self.measure(image, [center], source_ids=[np.int64(9223372036854775807)])
            row = report["stars"][0]
            self.assertTrue(row["fit_eligible"], row)
            np.testing.assert_allclose(row["flux"], expected, rtol=8e-5)
            np.testing.assert_allclose(row["sky"], bases, atol=1e-7)
            np.testing.assert_allclose(row["sky_gradient"]["dx"], gradients_x, atol=1e-7)
            np.testing.assert_allclose(row["sky_gradient"]["dy"], gradients_y, atol=1e-7)
            self.assertLess(abs(row["aperture_area"] - np.pi * 36), .06)
            self.assertEqual(row["source_id"], "9223372036854775807")
            self.assertEqual(report["channels"], ["R", "G", "B"])
            self.assertEqual(image.tobytes(), original)
            json.dumps(report, allow_nan=False)
            measured.append(row["flux"])
        self.assertLess(np.max(np.ptp(measured, axis=0) / expected), 3e-5)

    def test_unknown_coverage_saturation_and_shot_noise_are_not_fit_candidates(self):
        report = measure_stars(scene(), [(48.3, 47.7)])
        row = report["stars"][0]
        self.assertTrue(row["measured"])
        self.assertFalse(row["fit_eligible"])
        self.assertTrue({"coverage_unknown", "saturation_unknown", "source_poisson_unknown"}.issubset(row["exclusion_reasons"]))
        self.assertFalse(report["uncertainty"]["complete"])
        self.assertFalse(report["uncertainty"]["pixel_covariance_available"])
        self.assertFalse(report["uncertainty"]["source_poisson_included"])

    def test_edges_invalid_positions_and_local_nans_have_explicit_rows(self):
        image = scene()
        image[5, 90] = np.nan  # Does not disqualify an unrelated aperture.
        report = self.measure(image, [(48.3, 47.7), (5., 30.), (np.nan, 20.), (150., 30.)])
        self.assertTrue(report["stars"][0]["fit_eligible"])
        self.assertIn("annulus_outside_image", report["stars"][1]["exclusion_reasons"])
        self.assertIn("invalid_position", report["stars"][2]["exclusion_reasons"])
        self.assertIn("invalid_position", report["stars"][3]["exclusion_reasons"])
        self.assertEqual(report["stars"][2]["position_xy"], [None, 20.])
        image[48, 48] = np.nan
        row = self.measure(image)["stars"][0]
        self.assertFalse(row["measured"])
        self.assertIn("nonfinite_aperture", row["exclusion_reasons"])
        json.dumps(report, allow_nan=False)

    def test_coverage_uses_same_valid_pixels_across_rgb_and_sky_is_not_extrapolated(self):
        rgb = np.repeat(scene()[..., None], 3, axis=2)
        coverage = np.ones_like(rgb, dtype=np.uint8)
        coverage[48, 48, 2] = 0
        row = self.measure(rgb, coverage=coverage)["stars"][0]
        self.assertFalse(row["measured"])
        self.assertIn("incomplete_aperture_coverage", row["exclusion_reasons"])
        coverage[:] = 1
        yy, xx = np.indices(rgb.shape[:2])
        radius = np.hypot(xx - 48.3, yy - 47.7)
        coverage[(radius > 8.5) & (xx < 49)] = 0
        row = self.measure(rgb, coverage=coverage)["stars"][0]
        self.assertFalse(row["measured"])
        self.assertIn("insufficient_sky_support", row["exclusion_reasons"])

    def test_saturation_in_any_channel_and_threshold_equality_are_rejected(self):
        image = np.repeat(scene()[..., None], 3, axis=2)
        image[48, 48, 1] = 450.
        row = self.measure(image, saturation=[600., 450., 800.])["stars"][0]
        self.assertIn("saturated_aperture", row["exclusion_reasons"])
        self.assertFalse(row["measured"])
        self.assertTrue(self.measure(image, saturation=[600., 451., 800.])["stars"][0]["fit_eligible"])

    def test_blends_duplicates_and_large_crowded_catalog_do_not_form_n_squared_report(self):
        points = [(48.3, 47.7), (59., 47.7), (48.3, 47.7)]
        report = self.measure(scene(), points, source_ids=[1, 2, 3])
        self.assertEqual(report["summary"]["exclusions"]["blend"], 3)
        self.assertEqual(report["summary"]["measured"], 0)
        crowded = self.measure(scene(), np.repeat([[48., 48.]], 20000, axis=0))
        self.assertEqual(crowded["summary"]["exclusions"]["blend"], 20000)
        self.assertLess(len(json.dumps(crowded)), 12000000)

    def test_all_neighbors_including_saturated_references_mask_the_sky(self):
        center, neighbor = (48.3, 47.7), (65.3, 47.7)
        image = scene(center=center) + gaussian((96, 100), neighbor, 35000., sigma=1.0)
        report = self.measure(image, [center, neighbor], source_ids=[101, 102], saturation=1000.)
        first, second = report["stars"]
        self.assertTrue(first["fit_eligible"], first)
        self.assertGreater(first["neighbor_masked_sky_pixels"], 0)
        np.testing.assert_allclose(first["flux"], [1200.], rtol=1e-4)
        self.assertIn("saturated_aperture", second["exclusion_reasons"])

    def test_robust_plane_rejects_unlisted_annulus_artifacts(self):
        image = scene()
        for x, y in [(58, 48), (49, 60), (37, 47), (50, 36)]:
            image[y, x] += 1000.
        row = self.measure(image)["stars"][0]
        self.assertTrue(row["fit_eligible"], row)
        self.assertGreaterEqual(row["sky_rejected_pixels"], 4)
        np.testing.assert_allclose(row["flux"], [1200.], rtol=1e-4)

    def test_negative_net_flux_is_reported_without_clipping(self):
        image = scene(flux=-100.)
        row = self.measure(image)["stars"][0]
        self.assertTrue(row["measured"])
        self.assertFalse(row["fit_eligible"])
        self.assertIn("nonpositive_flux", row["exclusion_reasons"])
        np.testing.assert_allclose(row["flux"], [-100.], rtol=1e-4)
        self.assertLess(row["snr"][0], 0)

    def test_variance_units_gain_no_double_count_and_invalid_variance(self):
        image = scene()
        baseline = self.measure(image)["stars"][0]
        both = self.measure(image, gain=2.)["stars"][0]
        self.assertEqual(baseline["flux_uncertainty"], both["flux_uncertainty"])
        scaled = self.measure(image * 17., variance=.16 * 17 ** 2, saturation=1e12)["stars"][0]
        np.testing.assert_allclose(scaled["flux"], np.array(baseline["flux"]) * 17., rtol=1e-12)
        np.testing.assert_allclose(scaled["flux_uncertainty"], np.array(baseline["flux_uncertainty"]) * 17., rtol=1e-12)
        poisson2 = self.measure(image, variance=None, gain=2.)["stars"][0]
        poisson4 = self.measure(image, variance=None, gain=4.)["stars"][0]
        self.assertAlmostEqual(poisson2["flux_uncertainty"][0] / poisson4["flux_uncertainty"][0], np.sqrt(2), places=8)
        variance = np.full(image.shape, .16)
        variance[48, 48] = -1
        self.assertIn("invalid_aperture_variance", self.measure(image, variance=variance)["stars"][0]["exclusion_reasons"])

    def test_independent_noise_monte_carlo_checks_sky_plane_and_aperture_uncertainty(self):
        rng = np.random.default_rng(6204314)
        center = (24.35, 23.7)
        clean = scene(center, shape=(48, 48), flux=220., sigma=.9)
        args = dict(aperture_radius=4., annulus_inner=7., annulus_outer=11., variance=.36)
        reference = self.measure(clean, [center], **args)["stars"][0]["flux"][0]
        measured, predicted = [], []
        for _ in range(128):
            row = self.measure(clean + rng.normal(0, .6, clean.shape), [center], **args)["stars"][0]
            self.assertTrue(row["fit_eligible"], row)
            measured.append(row["flux"][0])
            predicted.append(row["flux_uncertainty"][0])
        ratio = np.std(measured, ddof=1) / np.mean(predicted)
        self.assertGreater(ratio, .80)
        self.assertLess(ratio, 1.20)
        self.assertLess(abs(np.mean(measured) - reference), 3.5 * np.mean(predicted) / np.sqrt(len(measured)))

    def test_correlated_noise_is_explicitly_not_covered_by_diagonal_error(self):
        rng = np.random.default_rng(871932)
        center = (24.35, 23.7)
        clean = scene(center, shape=(48, 48), flux=220., sigma=.9)
        impulse = np.zeros((31, 31))
        impulse[15, 15] = 1
        norm = np.sqrt(np.sum(gaussian_filter(impulse, 1.2, mode="constant") ** 2))
        samples, errors = [], []
        for _ in range(40):
            noise = gaussian_filter(rng.normal(0, .6, clean.shape), 1.2) / norm
            report = self.measure(clean + noise, [center], aperture_radius=4., annulus_inner=7., annulus_outer=11., variance=.36)
            row = report["stars"][0]
            samples.append(row["flux"][0])
            errors.append(row["flux_uncertainty"][0])
            self.assertFalse(report["uncertainty"]["complete"])
            self.assertFalse(row["uncertainty_complete"])
        self.assertGreater(np.std(samples, ddof=1) / np.mean(errors), 2.)

    def test_contract_validation_empty_catalog_and_cooperative_cancellation(self):
        image = scene()
        for kwargs in ({"aperture_radius": True}, {"annulus_inner": 3.}, {"saturation": 0},
                       {"gain": np.inf}, {"coverage": .5}, {"source_ids": [1.0]},
                       {"variance": np.ones((5, 5))}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.measure(image, **kwargs)
        with self.assertRaises(ValueError):
            self.measure(image.astype(complex))
        with self.assertRaises(ValueError):
            self.measure(image, [(1, 2), (3, 4)], source_ids=[1, 1])
        self.assertEqual(self.measure(image, [])["summary"]["positions"], 0)
        cancel = threading.Event()
        cancel.set()
        before = image.tobytes()
        with self.assertRaises(InterruptedError):
            self.measure(image, cancel=cancel)
        count = [0]
        def stopped():
            count[0] += 1
            return count[0] >= 4
        with self.assertRaises(InterruptedError):
            self.measure(image, cancel=stopped)
        self.assertEqual(image.tobytes(), before)

    def test_shared_aperture_annulus_pixels_are_prevented_by_geometry_contract(self):
        # A barely separated pair of mathematical circles still shares detector
        # pixels. Their independent variance sum would miss the cross-covariance.
        with self.assertRaisesRegex(ValueError, "at least 2 pixels"):
            self.measure(scene(), aperture_radius=6., annulus_inner=6.01, annulus_outer=10.)
        self.assertTrue(self.measure(scene(), aperture_radius=6., annulus_inner=8., annulus_outer=13.)["stars"][0]["measured"])

    def test_noiseless_multistar_field_retains_supported_diagnostic_plane(self):
        # Separate RNG/field from the astrometry fixture. Tiny nonzero PSF wings
        # are real signal, even when their residual MAD is much below shot noise.
        rng = np.random.default_rng(5196042)
        shape = (360, 420)
        yy, xx = np.indices(shape)
        centers = np.array([(x + rng.uniform(-.3, .3), y + rng.uniform(-.3, .3))
                            for y in range(35, 330, 37) for x in range(35, 390, 37)])
        fluxes = np.linspace(1., 2.5, len(centers))
        image = .01 + 1e-6 * xx - 2e-6 * yy
        for center, flux in zip(centers, fluxes):
            image += gaussian(shape, center, flux, sigma=1.5)
        report = measure_stars(image, centers)
        self.assertEqual(report["summary"]["measured"], len(centers))
        self.assertEqual(report["summary"]["fit_eligible"], 0)
        measured = [row["flux"][0] for row in report["stars"]]
        np.testing.assert_allclose(measured, fluxes, rtol=.001)
        for row in report["stars"]:
            self.assertGreaterEqual(row["sky_effective_area"], .5 * np.pi * (14 ** 2 - 9 ** 2) - .1)
            if row["sky_clipping_status"] != "converged":
                self.assertIn("sky_clipping_" + row["sky_clipping_status"], row["exclusion_reasons"])


if __name__ == "__main__":
    unittest.main()
