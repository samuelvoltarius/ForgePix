"""Independent TAN/WCS fixtures and rejection controls for native hinted solving."""
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import astrometry
from constants import ForgePixFehler
from gaia_lokal import Katalog


def fixture(seed=41823, angle=43, parity=-1, ra=299.9, dec=22.7, center_offset=True):
    rng = np.random.default_rng(seed)
    shape = (512, 768)
    points = []
    while len(points) < 90:
        point = rng.uniform([35, 35], [733, 477])
        if not points or np.min(np.linalg.norm(np.asarray(points) - point, axis=1)) > 20:
            points.append(point)
    points = np.asarray(points)
    reference = WCS(naxis=2)
    reference.wcs.crpix = [384.5, 256.5]
    reference.wcs.crval = [ra, dec]
    reference.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    reference.wcs.radesys = "ICRS"
    theta = np.radians(angle)
    rotation = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
    reference.wcs.cd = rotation @ np.diag([parity, 1]) * (3.6 / 3600)
    lon, lat = reference.pixel_to_world_values(points[:, 0], points[:, 1])
    catalog = Katalog(lon, lat, np.linspace(8, 14, len(points)), np.full(len(points), .7))
    hints = {"ra": (ra + (.03 if center_offset else 0)) % 360,
             "dec": dec - (.025 if center_offset else 0), "pixelscale_arcsec": 3.6}
    measured = points + rng.normal(0, .04, points.shape)
    return points, measured, shape, catalog, hints, reference


class NativeAstrometryTests(unittest.TestCase):
    def solve(self, measured, shape, catalog, hints):
        return astrometry.solve_positions(measured, shape, catalog, hints, log=lambda *_: None)

    def test_rotation_parity_and_meridian_flip(self):
        for angle, parity in ((43, -1), (223, -1), (-76, 1)):
            with self.subTest(angle=angle, parity=parity):
                points, measured, shape, catalog, hints, reference = fixture(angle=angle, parity=parity)
                result = self.solve(measured, shape, catalog, hints)
                self.assertEqual(result.report["parity"], parity)
                self.assertGreaterEqual(result.report["validation_matches"], 24)
                self.assertLess(result.report["validation_rms_px"], .12)
                # Compare an independent grid, including points never used as stars.
                x, y = np.meshgrid(np.linspace(0, 767, 6), np.linspace(0, 511, 5))
                sky = reference.pixel_to_world(x, y)
                actual = np.stack(result.wcs.world_to_pixel(sky), axis=-1)
                self.assertLess(np.max(np.linalg.norm(actual - np.stack((x, y), axis=-1), axis=-1)), .12)

    def test_ra_wrap_and_high_declination(self):
        for ra, dec in ((359.99, 5), (.02, 83)):
            with self.subTest(ra=ra, dec=dec):
                _, measured, shape, catalog, hints, reference = fixture(ra=ra, dec=dec)
                result = self.solve(measured, shape, catalog, hints)
                truth = reference.pixel_to_world(383.5, 255.5)
                actual = result.wcs.pixel_to_world(383.5, 255.5)
                self.assertLess(actual.separation(truth).arcsec, .15)

    def test_holdout_never_refits_or_rescues_a_failed_solution(self):
        _, measured, shape, catalog, hints, _ = fixture()
        measured[::3] += [18., -13.]
        with self.assertRaisesRegex(ForgePixFehler, "unabhängige Prüfsterne"):
            self.solve(measured, shape, catalog, hints)

    def test_unrelated_field_rejected(self):
        _, measured, shape, catalog, hints, _ = fixture()
        rng = np.random.default_rng(90731)
        measured = rng.uniform([25, 25], [743, 487], measured.shape)
        with self.assertRaises(ForgePixFehler):
            self.solve(measured, shape, catalog, hints)

    def test_false_detections_and_missing_references(self):
        _, measured, shape, catalog, hints, reference = fixture()
        rng = np.random.default_rng(7115)
        measured[20:30] = rng.uniform([25, 25], [743, 487], (10, 2))
        catalog = Katalog(catalog.ra[5:], catalog.dec[5:], catalog.g_mag[5:], catalog.bp_rp[5:])
        result = self.solve(measured, shape, catalog, hints)
        self.assertGreaterEqual(result.report["validation_matches"], 20)
        self.assertLess(result.wcs.pixel_to_world(383.5, 255.5).separation(reference.pixel_to_world(383.5, 255.5)).arcsec, .2)

    def test_wrong_hint_and_scale_rejected(self):
        _, measured, shape, catalog, hints, _ = fixture()
        for patch in ({"ra": 10}, {"pixelscale_arcsec": 8}, {"fov_width_deg": 12, "pixelscale_arcsec": None}):
            with self.subTest(patch=patch), self.assertRaises(ForgePixFehler):
                self.solve(measured, shape, catalog, dict(hints, **patch))

    def test_insufficient_duplicate_and_collinear_stars_rejected(self):
        _, measured, shape, catalog, hints, _ = fixture()
        for sample in (measured[:20], np.repeat(measured[:3], 20, axis=0),
                       np.column_stack((np.arange(30) * 10 + 35, np.full(30, 100)))):
            with self.subTest(n=len(sample)), self.assertRaises(ForgePixFehler):
                self.solve(sample, shape, catalog, hints)

    def test_nan_complex_outside_and_cancel_rejected(self):
        _, measured, shape, catalog, hints, _ = fixture()
        for bad in (measured * np.nan, measured.astype(complex) + 1j, measured - 1000):
            with self.assertRaises(ForgePixFehler):
                self.solve(bad, shape, catalog, hints)
        with self.assertRaisesRegex(ForgePixFehler, "abgebrochen"):
            astrometry.solve_positions(measured, shape, catalog, hints, cancel=lambda: True)
        for value in (np.complex64(3.6 + 1j), np.bool_(True), np.nan):
            with self.assertRaises(ForgePixFehler):
                self.solve(measured, shape, catalog, dict(hints, pixelscale_arcsec=value))

    def test_float_star_detection_and_separate_fits_preserve_science_pixels(self):
        points, _, shape, catalog, hints, _ = fixture()
        yy, xx = np.mgrid[:shape[0], :shape[1]]
        image = np.full(shape, -.2, np.float32)
        for i, (x, y) in enumerate(points):
            image += np.float32(2. * np.exp(-i / 40)) * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.3 ** 2)).astype(np.float32)
        bgr = np.stack((image * .8, image, image * 1.2), axis=-1)
        original = bgr.copy()
        result = astrometry.solve(bgr, catalog, hints, log=lambda *_: None)
        np.testing.assert_array_equal(original, bgr)
        old = fits.Header({"FILTER": "SII/OIII", "EXPTIME": 300, "CTYPE1": "RA---TAN-SIP", "A_ORDER": 2,
                           "A_2_0": .01, "CRPIX1": 900, "BSCALE": 2, "BZERO": 400, "BAYERPAT": "RGGB",
                           "BUNIT": "ADU", "FPLINEAR": True, "FPDOMAIN": "LINEAR", "FPCOV": "coverage.tif",
                           "FPDRZWGT": "drizzle_weights.tif", "FPAIHASH": "keep-scientific-provenance",
                           "CTYPE1A": "RA---TAN", "PV1_1": .5, "D2IM1.EXTVER": 2})
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "separate-solved.fits"
            astrometry.write_solution_fits(bgr, output, result, header=old)
            with fits.open(output) as hdus:
                np.testing.assert_array_equal(hdus[0].data, bgr[..., ::-1].transpose(2, 0, 1))
                self.assertEqual(hdus[0].header["FILTER"], "SII/OIII")
                self.assertNotIn("A_ORDER", hdus[0].header)
                self.assertNotIn("BAYERPAT", hdus[0].header)
                self.assertNotIn("BZERO", hdus[0].header)
                self.assertNotIn("CTYPE1A", hdus[0].header)
                self.assertNotIn("PV1_1", hdus[0].header)
                self.assertNotIn("D2IM1.EXTVER", hdus[0].header)
                for key in ("BUNIT", "FPLINEAR", "FPDOMAIN", "FPCOV", "FPDRZWGT", "FPAIHASH"):
                    self.assertEqual(hdus[0].header[key], old[key])
                reopened = WCS(hdus[0].header).celestial
                x, y = reopened.world_to_pixel(result.wcs.pixel_to_world(300, 200))
                self.assertAlmostEqual(float(x), 300, places=7)
                self.assertAlmostEqual(float(y), 200, places=7)
            with self.assertRaises(OSError):
                astrometry.write_solution_fits(bgr, output, result)
            mono64 = image.astype(np.float64) + 1e-10
            astrometry.write_solution_fits(mono64, Path(directory) / "double.fits", result)
            np.testing.assert_array_equal(fits.getdata(Path(directory) / "double.fits"), mono64)
        self.assertEqual(old["A_ORDER"], 2)

    def test_focal_and_fov_hint_units(self):
        shape = (512, 768)
        direct = astrometry._hints({"ra": 10, "dec": 20, "fov_width_deg": .768}, shape)
        optical = astrometry._hints({"ra": 10, "dec": 20, "focal": 1000, "pixelsize": 4.63}, shape)
        self.assertAlmostEqual(direct[2] * 3600, 3.6)
        self.assertAlmostEqual(optical[2] * 3600, .9550060529, places=10)


if __name__ == "__main__":
    unittest.main()
