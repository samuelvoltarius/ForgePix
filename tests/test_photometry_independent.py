"""Independent scientific/transaction checks of the read-only FITS adapter.

Fixtures and expected fluxes are created here, without borrowing the detector,
aperture implementation, or other test modules. No network or camera presets.
"""
import csv
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import tifffile
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import photometry_file as pf
from constants import ForgePixFehler
from photometric_catalogue import PhotometricCatalogue


class IndependentPhotometryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name).resolve()
        self.source = self.folder / "linear.fits"
        self.cat_path = self.folder / "field.npz"
        self.variance_path = self.folder / "variance.fits"
        self.xy = np.array([[32.2, 33.3], [94.1, 35.2], [63.3, 91.1]])
        self.ids = np.array([2**62 + 12345, 2**62 + 23457, 2**62 + 34567], dtype=np.int64)
        self.wcs = WCS(naxis=2)
        self.wcs.wcs.crpix = [64.5, 64.5]
        self.wcs.wcs.crval = [300.0, 22.0]
        self.wcs.wcs.cd = np.array([[-.00027, .000012], [.000011, .000271]])
        self.wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
        self.wcs.wcs.radesys = "ICRS"
        yy, xx = np.indices((128, 128), dtype=float)
        # An affine sky is integrated exactly at pixel centres. The compact
        # Gaussian is independently normalized to its discrete all-pixel sum.
        self.image = 35000.0 + .037 * xx - .021 * yy
        self.expected_flux = np.array([1800., 1300., 950.])
        for (x, y), flux in zip(self.xy, self.expected_flux):
            psf = np.exp(-((xx - x)**2 + (yy - y)**2) / (2 * 1.15**2))
            self.image += psf * (flux / psf.sum())
        self.image[0, 0] = -1.234567890123
        self.image[-1, -1] = 45000.12345678901
        self.header = self.wcs.to_header()
        self.header.update({"FPLINEAR": True, "FPDOMAIN": "LINEAR", "BUNIT": "adu",
                            "DATE-AVG": "2025-07-21T22:30:00.000", "TIMESYS": "UTC",
                            "FPCOV": "coverage.tif"})
        self._write_source()
        tifffile.imwrite(self.folder / "coverage.tif", np.ones((128, 128), np.uint8))
        self._write_catalogue()
        fits.writeto(self.variance_path, np.full((128, 128), 9., np.float64), fits.Header({"BUNIT": "adu2"}))

    def _write_source(self, image=None, header=None):
        image = self.image if image is None else image
        data = np.moveaxis(image, -1, 0) if image.ndim == 3 else image
        fits.writeto(self.source, data, self.header if header is None else header, overwrite=True)

    def _write_catalogue(self, wcs=None):
        sky = (self.wcs if wcs is None else wcs).pixel_to_world(self.xy[:, 0], self.xy[:, 1]).icrs
        columns = {"source_id": self.ids, "ra": sky.ra.deg, "dec": sky.dec.deg,
                   "ref_epoch": np.full(3, 2016.), "pmra": np.zeros(3), "pmdec": np.zeros(3)}
        self.cat_path.unlink(missing_ok=True)
        PhotometricCatalogue(columns, metadata={"origin": "independent_analytic_fixture"}).save(self.cat_path)

    def _diagnose(self, **kwargs):
        return pf.diagnose_file(self.source, self.cat_path, self.folder, log=lambda *_: None, **kwargs)

    def test_float64_physical_pixels_fluxes_and_source_bytes_are_preserved(self):
        paths = [self.source, self.cat_path, self.folder / "coverage.tif", self.variance_path]
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        read, _, dtype = pf._read_fits(self.source)
        np.testing.assert_array_equal(read, self.image)
        self.assertEqual(np.dtype(dtype).itemsize, 8)
        result = self._diagnose(saturation=60000., variance_path=self.variance_path)
        report = result["report"]
        rows = report["measurement"]["stars"]
        self.assertEqual(len(rows), 3)
        np.testing.assert_allclose([r["flux"][0] for r in rows], self.expected_flux, rtol=2e-5)
        np.testing.assert_allclose([r["sky_gradient"]["dx"][0] for r in rows], .037, atol=2e-10)
        np.testing.assert_allclose([r["sky_gradient"]["dy"][0] for r in rows], -.021, atol=2e-10)
        self.assertEqual(report["image"]["pixel_normalization"], "none")
        self.assertEqual(report["image"]["unit"], "adu")
        self.assertFalse(report["image_written"])
        self.assertFalse(report["release_approved"])
        self.assertFalse(report["color_calibration_applied"])
        self.assertTrue(all(not r["fit_eligible"] for r in rows))
        self.assertEqual({p.name for p in Path(result["report_path"]).parent.iterdir()},
                         {"photometry_report.json", "stars.csv"})
        for path, digest in before.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_unsigned_bzero_is_storage_not_black_level_or_normalization(self):
        values = np.rint(self.image).clip(0, 65535).astype(np.uint16)
        self._write_source(values)
        read, _, dtype = pf._read_fits(self.source)
        np.testing.assert_array_equal(read, values.astype(np.float64))
        self.assertEqual(dtype, "uint16")
        result = self._diagnose(saturation=65535.)
        self.assertGreater(result["report"]["measurement"]["stars"][0]["flux"][0], 1700.)

    def test_unrepresentable_int64_pixels_are_rejected_without_quantization(self):
        for dtype in (np.int64, np.uint64):
            with self.subTest(dtype=dtype):
                self._write_source(np.full((128, 128), 2**53 + 1, dtype=dtype))
                with self.assertRaises(ForgePixFehler):
                    pf._read_fits(self.source)

    def test_rgb_plane_order_and_variance_channel_units(self):
        factors = np.array([2., 1., .25])
        rgb = self.image[..., None] * factors
        self._write_source(rgb)
        variance = np.broadcast_to(np.array([36., 9., .5625]), rgb.shape)
        fits.writeto(self.variance_path, np.moveaxis(variance, -1, 0), overwrite=True)
        read, _, _ = pf._read_fits(self.source)
        np.testing.assert_array_equal(read, rgb)
        report = self._diagnose(saturation=[120000., 60000., 15000.], variance_path=self.variance_path)["report"]
        self.assertEqual(report["measurement"]["channels"], ["R", "G", "B"])
        for index, row in enumerate(report["measurement"]["stars"]):
            np.testing.assert_allclose(row["flux"], self.expected_flux[index] * factors, rtol=2e-5)
            np.testing.assert_allclose(np.array(row["flux_uncertainty"]) / row["flux_uncertainty"][1], factors, rtol=1e-10)

    def test_ids_above_double_precision_are_exact_in_json_and_csv(self):
        result = self._diagnose()
        report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
        expected = [str(int(value)) for value in self.ids]
        self.assertEqual([row["source_id"] for row in report["measurement"]["stars"]], expected)
        with Path(result["csv_path"]).open(encoding="utf-8", newline="") as stream:
            self.assertEqual([row["source_id"] for row in csv.DictReader(stream)], expected)

    def test_fk5_world_coordinates_are_transformed_from_catalogue_icrs(self):
        self.wcs.wcs.radesys = "FK5"
        self.wcs.wcs.equinox = 1975.
        header = self.header.copy()
        header.update(self.wcs.to_header())
        self._write_source(header=header)
        self._write_catalogue(self.wcs)
        rows = self._diagnose()["report"]["measurement"]["stars"]
        self.assertEqual(len(rows), 3)
        np.testing.assert_allclose([row["position_xy"] for row in rows], self.xy, atol=2e-8)

    def test_missing_or_singular_celestial_wcs_is_rejected(self):
        for header in (fits.Header({"FPLINEAR": True}), self.header.copy()):
            if "CTYPE1" in header:
                for key in list(header):
                    if key.startswith("PC"):
                        del header[key]
                header["CD1_1"] = 0.
                header["CD1_2"] = 0.
                header["CD2_1"] = 0.
                header["CD2_2"] = 0.
            with self.subTest(header=repr(header)):
                self._write_source(header=header)
                with self.assertRaises(ForgePixFehler):
                    self._diagnose()
        self.assertFalse(list(self.folder.glob("stack-photometry-*")))

    def test_date_obs_and_camera_presets_do_not_become_effective_stack_metadata(self):
        header = self.header.copy()
        del header["DATE-AVG"]
        del header["FPLINEAR"]
        del header["FPDOMAIN"]
        header.update({"DATE-OBS": "2025-07-21T21:18:41.508810", "EXPTIME": 300.,
                       "GAIN": 131, "EGAIN": .88302481174469, "OFFSET": 30,
                       "SATURATE": 65535, "FPDRZWGT": "weights.tif", "FPPIXARE": .25})
        self._write_source(header=header)
        tifffile.imwrite(self.folder / "weights.tif", np.full((128, 128), 8.25, np.float32))
        report = self._diagnose()["report"]
        self.assertIsNone(report["epoch"]["jyear"])
        self.assertEqual(report["image"]["linear_evidence"], "unknown")
        self.assertEqual(report["image"]["saturation_source"], "unknown")
        self.assertIsNone(report["image"]["variance_source"])
        self.assertFalse(report["image"]["pixel_area_correction_applied"])
        self.assertEqual(report["image"]["drizzle_output_pixel_area"], .25)
        self.assertEqual(report["measurement"]["uncertainty"]["model"], "sky_mad_only_source_poisson_unknown")
        for row in report["measurement"]["stars"]:
            self.assertFalse(row["position_at_observation_epoch"])
            self.assertIn("saturation_unknown", row["exclusion_reasons"])
            self.assertFalse(row["fit_eligible"])

    def test_average_epoch_uses_tcb_and_disagreement_stays_unknown(self):
        report = pf.observation_epoch(self.header)
        expected = Time(self.header["DATE-AVG"], scale="utc").tcb.jyear
        self.assertEqual(report["time_scale"], "tcb")
        self.assertAlmostEqual(report["jyear"], expected, places=11)
        self.assertEqual(pf.observation_epoch({}, 2025.5)["time_scale"], "tcb")
        conflict = self.header.copy()
        conflict["MJD-AVG"] = Time("2025-07-22", scale="utc").mjd
        self.assertIsNone(pf.observation_epoch(conflict)["jyear"])
        self.assertEqual(pf.observation_epoch(conflict)["status"], "conflicting_average_times")

    def test_ai_nonlinear_and_raw_cfa_sources_cannot_enter_diagnostics(self):
        for update in ({"FPLINEAR": False}, {"FPDOMAIN": "LINEAR_AI_ESTIMATE"},
                       {"FPAITASK": "denoise"}, {"FPCHTYPE": "RESIDUAL"}, {"BAYERPAT": "RGGB"}):
            with self.subTest(update=update):
                header = self.header.copy()
                header.update(update)
                self._write_source(header=header)
                with self.assertRaises(ForgePixFehler):
                    self._diagnose(linear_confirmed=True)
        self.assertFalse(list(self.folder.glob("stack-photometry-*")))

    def test_partial_coverage_excludes_only_affected_star(self):
        mask = np.ones((128, 128), np.uint8)
        mask[33, 32] = 0
        tifffile.imwrite(self.folder / "coverage.tif", mask)
        rows = self._diagnose(saturation=60000., variance_path=self.variance_path)["report"]["measurement"]["stars"]
        self.assertFalse(rows[0]["measured"])
        self.assertIn("incomplete_aperture_coverage", rows[0]["exclusion_reasons"])
        self.assertTrue(all(row["measured"] for row in rows[1:]))

    def test_one_missing_drizzle_channel_is_excluded_from_common_rgb_aperture(self):
        self.header["FPDRZWGT"] = "weights.tif"
        rgb = np.repeat(self.image[..., None], 3, axis=-1)
        self._write_source(rgb)
        weights = np.full(rgb.shape, 8.25, np.float32)
        weights[33, 32, 2] = 0
        tifffile.imwrite(self.folder / "weights.tif", weights, photometric="rgb")
        rows = self._diagnose()["report"]["measurement"]["stars"]
        self.assertFalse(rows[0]["measured"])
        self.assertIn("incomplete_aperture_coverage", rows[0]["exclusion_reasons"])
        self.assertTrue(rows[1]["measured"])

    def test_nonfinite_pixel_and_invalid_variance_are_local_exclusions(self):
        image = self.image.copy()
        image[33, 32] = np.nan
        self._write_source(image)
        variance = fits.getdata(self.variance_path).copy()
        variance[35, 94] = -1
        fits.writeto(self.variance_path, variance, overwrite=True)
        rows = self._diagnose(saturation=60000., variance_path=self.variance_path)["report"]["measurement"]["stars"]
        self.assertIn("nonfinite_aperture", rows[0]["exclusion_reasons"])
        self.assertIn("invalid_aperture_variance", rows[1]["exclusion_reasons"])
        self.assertTrue(rows[2]["measured"])

    def test_mutation_of_any_input_before_publication_leaves_no_report(self):
        original_measure = pf.measure_stars
        for target in (self.source, self.cat_path, self.folder / "coverage.tif", self.variance_path):
            with self.subTest(target=target.name):
                saved = target.read_bytes()
                def changed(*args, **kwargs):
                    result = original_measure(*args, **kwargs)
                    with target.open("ab") as stream:
                        stream.write(b"independent-change")
                    return result
                try:
                    with patch.object(pf, "measure_stars", side_effect=changed):
                        with self.assertRaisesRegex(ForgePixFehler, "verändert"):
                            self._diagnose(saturation=60000., variance_path=self.variance_path)
                    self.assertFalse(list(self.folder.glob("stack-photometry-*")))
                finally:
                    target.write_bytes(saved)

    def test_dependency_change_while_writing_staged_json_cleans_pending_output(self):
        original_dump = pf.json.dump
        target = self.folder / "coverage.tif"
        def changed(*args, **kwargs):
            result = original_dump(*args, **kwargs)
            with target.open("ab") as stream:
                stream.write(b"independent-late-change")
            return result
        with patch.object(pf.json, "dump", side_effect=changed):
            with self.assertRaisesRegex(ForgePixFehler, "verändert"):
                self._diagnose(saturation=60000., variance_path=self.variance_path)
        self.assertFalse(list(self.folder.glob("stack-photometry-*")))


if __name__ == "__main__":
    unittest.main()
