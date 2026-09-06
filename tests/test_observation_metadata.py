"""Independent FITS time, provenance, reference-grid and missing-evidence tests."""
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import warnings

import numpy as np
from astropy.io import fits
from astropy.time import Time, TimeDelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
from observation_metadata import apply_to_header, build_metadata, verify_sources


class ObservationMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name).resolve()
        self.counter = 0

    def light(self, *, begin="2025-07-21T22:00:00", exposure=300., update=None, remove=(), dtype=np.uint16):
        self.counter += 1
        path = self.folder / ("light-%d.fits" % self.counter)
        header = fits.Header({"OBJECT": "M27", "FILTER": "L", "INSTRUME": "Actual camera", "TELESCOP": "Actual telescope",
                              "DATE-BEG": begin, "TIMESYS": "UTC", "EXPTIME": exposure, "EXPOSURE": exposure,
                              "RA": 300.17904, "DEC": 22.795087, "FOCALLEN": 1151., "XPIXSZ": 4.63, "YPIXSZ": 4.63,
                              "XBINNING": 1, "YBINNING": 1, "GAIN": 131, "EGAIN": .883, "SATURATE": 65535,
                              "BUNIT": "adu", "IMAGETYP": "Light", "BAYERPAT": "RGGB"})
        header.comments["XPIXSZ"] = "pixel size in microns (with binning)"
        header.comments["YPIXSZ"] = "pixel size in microns (with binning)"
        if update:
            header.update(update)
        for key in ("XPIXSZ", "YPIXSZ"):
            if not header.comments[key]:
                header.comments[key] = "pixel size in microns (with binning)"
        for key in remove:
            header.remove(key, ignore_missing=True)
        fits.writeto(path, np.arange(120, dtype=dtype).reshape(10, 12), header)
        return path

    def test_actual_used_subset_weighted_midpoints_reference_and_tcb(self):
        first = self.light(exposure=20.)
        unused = self.light(begin="2025-07-22T05:00:00", exposure=900., update={"FILTER": "Wrong unused filter"})
        reference = self.light(begin="2025-07-21T22:01:40", exposure=40., update={"RA": 301., "FOCALLEN": 1320.})
        original = {path: path.read_bytes() for path in (first, unused, reference)}
        summary = build_metadata([first, reference], reference)
        self.assertEqual(summary["ncombine"], 2)
        self.assertEqual(summary["constants"]["FILTER"], "L")
        self.assertNotIn("EXPTIME", summary["constants"])
        self.assertEqual(summary["exposure"]["integration_seconds"], 60.)
        expected_offset = (20 * 10 + 40 * 120) / 60
        expected = Time("2025-07-21T22:00:00", scale="utc").tai + TimeDelta(expected_offset, format="sec")
        self.assertLess(abs((Time(summary["timing"]["average_utc"], scale="utc") - expected).sec), 2e-8)
        self.assertAlmostEqual(summary["timing"]["effective_epoch_tcb_jyear"], expected.tcb.jyear, places=11)
        self.assertAlmostEqual(summary["timing"]["span_seconds"], 140., places=8)
        expected_spread = math.sqrt((20 * (10 - expected_offset) ** 2 + 40 * (120 - expected_offset) ** 2) / 60)
        self.assertAlmostEqual(summary["timing"]["midpoint_spread_seconds"], expected_spread, places=8)
        self.assertEqual(summary["reference"]["hints"]["RA"], 301.)
        self.assertEqual(summary["reference"]["hints"]["FOCALLEN"], 1320.)
        self.assertFalse(summary["timing"]["per_pixel_weighting_verified"])
        self.assertEqual(original, {path: path.read_bytes() for path in original})
        self.assertTrue(verify_sources(summary))
        json.dumps(summary, allow_nan=False)

    def test_constant_exposure_is_not_sum_gain_units_or_source_wcs(self):
        first = self.light(update={"CTYPE1": "RA---TAN", "CRVAL1": 222., "FPLINEAR": True, "FPDOMAIN": "LINEAR"})
        second = self.light(begin="2025-07-21T22:06:00")
        summary = build_metadata([first, second], first)
        header = fits.Header({"BUNIT": "relative", "FPLINEAR": True, "FPCOV": "coverage.tif",
                              "CRVAL1": 42., "GAIN": 131, "EGAIN": .883, "SATURATE": 65535, "DATE-OBS": "2000-01-01T00:00:00"})
        before = header.copy()
        result = apply_to_header(header, summary)
        self.assertEqual(result["EXPTIME"], 300.)
        self.assertIn("single-light", result.comments["EXPTIME"])
        self.assertEqual(result["FPTOTEXP"], 600.)
        self.assertEqual(result["NCOMBINE"], 2)
        self.assertEqual(result["BUNIT"], "relative")
        self.assertEqual(result["CRVAL1"], 42.)
        self.assertEqual(result["FPCOV"], "coverage.tif")
        self.assertTrue(result["FPLINEAR"])
        self.assertEqual(header, before)
        for key in ("GAIN", "EGAIN", "SATURATE", "DATE-OBS", "EXPOSURE"):
            self.assertNotIn(key, result)
        fresh = apply_to_header(fits.Header(), summary)
        for key in ("CTYPE1", "CRVAL1", "BUNIT", "FPLINEAR", "FPDOMAIN", "BAYERPAT"):
            self.assertNotIn(key, fresh)
        self.assertEqual(summary["sources"][0]["metadata"]["FPLINEAR"]["value"], True)
        self.assertEqual(summary["sources"][0]["metadata"]["BZERO"]["value"], 32768)
        self.assertEqual(summary["sources"][0]["metadata"]["BITPIX"]["value"], 16)
        self.assertEqual(fresh["FPMHASH"], summary["source_metadata_sha256"])
        with warnings.catch_warnings():
            warnings.simplefilter("error", fits.verify.VerifyWarning)
            reloaded = fits.Header.fromstring(fresh.tostring())
        self.assertEqual(reloaded["FPMHASH"], summary["source_metadata_sha256"])
        self.assertEqual(reloaded.comments["FPTSPR"], fresh.comments["FPTSPR"])

    def test_mixed_and_missing_filters_never_inherit_a_current_setting(self):
        first = self.light()
        missing = self.light(remove=("FILTER",))
        mixed = self.light(update={"FILTER": "SII/OIII"})
        for second, status in ((missing, "missing_or_invalid"), (mixed, "inconsistent")):
            summary = build_metadata([first, second], first)
            self.assertNotIn("FILTER", summary["constants"])
            self.assertEqual(summary["consistency"]["FILTER"]["status"], status)
            self.assertNotIn("FILTER", apply_to_header(fits.Header({"FILTER": "Current equipment guess"}), summary))

    def test_missing_exposure_keeps_only_partial_sum_and_no_full_span_or_epoch(self):
        first = self.light()
        missing = self.light(remove=("EXPTIME", "EXPOSURE"))
        summary = build_metadata([first, missing], first)
        self.assertIsNone(summary["exposure"]["integration_seconds"])
        self.assertEqual(summary["exposure"]["known_subset_seconds"], 300.)
        self.assertEqual(summary["timing"]["known_frames"], 1)
        self.assertFalse(summary["timing"]["complete"])
        self.assertIsNone(summary["timing"]["average_utc"])
        header = apply_to_header(fits.Header({"DATE-AVG": "2025-01-01T00:00:00", "MJD-AVG": 60676., "FPTOTEXP": 900.}), summary)
        self.assertEqual(header["FPNEXP"], 1)
        for key in ("EXPTIME", "FPTOTEXP", "DATE-AVG", "DATE-BEG", "DATE-END", "MJD-AVG"):
            self.assertNotIn(key, header)

    def test_date_obs_semantics_need_comment_or_explicit_override(self):
        source = self.light(update={"DATE-OBS": "2025-07-21T22:00:00"}, remove=("DATE-BEG", "TIMESYS"))
        ambiguous = build_metadata([source], source)
        self.assertEqual(ambiguous["frame_timing"][0]["status"], "ambiguous_date_obs")
        self.assertFalse(ambiguous["timing"]["complete"])
        explicit = build_metadata([source], source, date_obs_is_start=True)
        self.assertTrue(explicit["timing"]["complete"])
        self.assertTrue(explicit["frame_timing"][0]["default_timesys_utc"])
        with fits.open(source, mode="update") as hdus:
            hdus[0].header.comments["DATE-OBS"] = "Image exposure start time"
        declared = build_metadata([source], source)
        self.assertTrue(declared["timing"]["complete"])
        self.assertTrue(declared["frame_timing"][0]["date_obs_start_comment"])
        self.assertEqual(declared["timing"]["average_utc"], "2025-07-21T22:02:30.000000000")

    def test_conflicting_time_aliases_end_average_and_exposure_are_explicit(self):
        base = Time("2025-07-21T22:00:00", scale="utc")
        for patch, expected in (({"MJD-BEG": (base + TimeDelta(2, format="sec")).mjd}, "conflicting_beg_aliases"),
                                ({"DATE-END": "2025-07-21T22:06:00"}, "conflicting_end_and_exposure"),
                                ({"DATE-AVG": "2025-07-21T22:04:00"}, "conflicting_average_and_exposure_midpoint")):
            source = self.light(update=patch)
            summary = build_metadata([source], source)
            self.assertFalse(summary["timing"]["complete"])
            self.assertIn(expected, summary["frame_timing"][0]["reason"])
        source = self.light(update={"EXPOSURE": 299.})
        summary = build_metadata([source], source)
        self.assertIsNone(summary["exposure"]["integration_seconds"])
        self.assertEqual(summary["exposure"]["per_frame"][0]["status"], "conflicting_exposure_keywords")

    def test_matching_mjd_aliases_and_end_only_complete_exposure(self):
        begin = Time("2025-07-21T22:00:00", scale="utc")
        source = self.light(update={"MJD-BEG": begin.mjd, "MJD-END": (begin + TimeDelta(300, format="sec")).mjd,
                                   "MJD-AVG": (begin + TimeDelta(150, format="sec")).mjd})
        self.assertTrue(build_metadata([source], source)["timing"]["complete"])
        ending = self.light(update={"DATE-END": "2025-07-21T22:05:00"}, remove=("DATE-BEG",))
        summary = build_metadata([ending], ending)
        self.assertTrue(summary["timing"]["complete"])
        self.assertEqual(summary["frame_timing"][0]["begin_method"], "DATE/MJD-END minus exposure")
        self.assertEqual(summary["timing"]["begin_utc"], "2025-07-21T22:00:00.000000000")

    def test_leap_second_is_averaged_in_continuous_time_not_utc_mjd(self):
        first = self.light(begin="2016-12-31T23:59:59", exposure=2.)
        second = self.light(begin="2017-01-01T00:00:01", exposure=2.)
        summary = build_metadata([first, second], first)
        self.assertEqual(summary["frame_timing"][0]["midpoint_utc"], "2016-12-31T23:59:60.000000000")
        self.assertEqual(summary["timing"]["average_utc"], "2017-01-01T00:00:00.500000000")
        self.assertAlmostEqual(summary["timing"]["span_seconds"], 5., places=8)
        expected_tcb = Time("2017-01-01T00:00:00.5", scale="utc").tcb.jyear
        self.assertAlmostEqual(summary["timing"]["effective_epoch_tcb_jyear"], expected_tcb, places=11)

    def test_time_scales_convert_but_unsupported_spatial_corrections_stay_unknown(self):
        first = self.light(exposure=10.)
        second = self.light(begin="2025-07-21T22:00:37", exposure=10., update={"TIMESYS": "TAI"})
        summary = build_metadata([first, second], first)
        self.assertEqual(summary["timing"]["average_utc"], "2025-07-21T22:00:05.000000000")
        for patch, status in (({"TIMESYS": "UT1"}, "unsupported_time_scale"),
                              ({"TREFPOS": "BARYCENTER"}, "unsupported_time_reference_position")):
            source = self.light(update=patch)
            summary = build_metadata([source], source)
            self.assertFalse(summary["timing"]["complete"])
            self.assertEqual(summary["frame_timing"][0]["status"], status)

    def test_camera_binning_software_bin_and_drizzle_have_distinct_pixel_semantics(self):
        source = self.light(update={"XPIXSZ": 9.26, "YPIXSZ": 9.26, "XBINNING": 2, "YBINNING": 2})
        summary = build_metadata([source], source, output_bin=2, drizzle_scale=3.)
        expected = math.degrees(math.atan(9.26 / (1000 * 1151))) * 3600 * 2 / 3
        self.assertAlmostEqual(summary["reference"]["output_pixelscale_arcsec"], expected, places=11)
        self.assertEqual(summary["reference"]["pixel_axes"]["X"]["sensor_pixel_size_um"], 4.63)
        header = apply_to_header(fits.Header({"XPIXSZ": 999, "XBINNING": 99}), summary)
        self.assertNotIn("XPIXSZ", header)
        self.assertNotIn("XBINNING", header)
        self.assertEqual(header["FPRXPSZ"], 9.26)
        self.assertEqual(header["FPRXBIN"], 2)
        self.assertEqual(header["FPOBIN"], 2)
        self.assertEqual(header["FPOSCALE"], 3.)
        self.assertAlmostEqual(header["PIXSCALE"], expected, places=11)
        with fits.open(source, mode="update") as hdus:
            for axis in ("X", "Y"):
                hdus[0].header[axis + "PIXSZ"] = (4.63, "unbinned pixel size in microns")
        unbinned = build_metadata([source], source, output_bin=2, drizzle_scale=3.)
        self.assertEqual(unbinned["reference"]["output_pixelscale_arcsec"], summary["reference"]["output_pixelscale_arcsec"])
        with fits.open(source, mode="update") as hdus:
            hdus[0].header.comments["XPIXSZ"] = "pixel size in microns"
        ambiguous = build_metadata([source], source)
        self.assertIsNone(ambiguous["reference"]["output_pixelscale_arcsec"])
        self.assertNotIn("PIXSCALE", apply_to_header(fits.Header({"PIXSCALE": 9.}), ambiguous))

    def test_reference_outside_used_lights_does_not_change_counts_or_acquisition(self):
        source = self.light()
        reference = self.light(begin="2025-08-21T22:00:00", update={"OBJECT": "Different", "FILTER": "R", "FOCALLEN": 2000.})
        summary = build_metadata([source], reference)
        self.assertEqual(summary["ncombine"], 1)
        self.assertEqual(summary["constants"]["OBJECT"], "M27")
        self.assertEqual(summary["constants"]["FILTER"], "L")
        self.assertFalse(summary["reference"]["is_used_light"])
        self.assertEqual(summary["reference"]["hints"]["FOCALLEN"], 2000.)
        self.assertEqual(summary["timing"]["begin_utc"], "2025-07-21T22:00:00.000000000")

    def test_header_hash_detects_changed_metadata_even_with_original_mtime(self):
        source = self.light()
        summary = build_metadata([source], source)
        metadata = summary["sources"][0]
        expected = hashlib.sha256(source.read_bytes()[:metadata["primary_header_bytes"]]).hexdigest()
        self.assertEqual(metadata["primary_header_sha256"], expected)
        stat = source.stat()
        with fits.open(source, mode="update") as hdus:
            hdus[0].header["FILTER"] = "R"
        os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        with self.assertRaisesRegex(ValueError, "changed"):
            verify_sources(summary)
        changed = build_metadata([source], source)
        self.assertNotEqual(changed["source_metadata_sha256"], summary["source_metadata_sha256"])

    def test_duplicate_keywords_invalid_contracts_and_cancellation(self):
        source = self.light()
        for kwargs in ({"date_obs_is_start": "yes"}, {"output_bin": 1.5}, {"output_bin": True},
                       {"drizzle_scale": np.nan}, {"time_tolerance_seconds": 0}, {"combination": ""}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                build_metadata([source], source, **kwargs)
        with self.assertRaises(ValueError):
            build_metadata([source, source], source)
        with self.assertRaises(ValueError):
            build_metadata([], source)
        with fits.open(source, mode="update") as hdus:
            hdus[0].header.append(("DATE-BEG", "2025-07-21T22:03:00"))
        summary = build_metadata([source], source)
        self.assertTrue(summary["sources"][0]["metadata"]["DATE-BEG"]["duplicate"])
        self.assertFalse(summary["timing"]["complete"])
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(InterruptedError):
            build_metadata([source], source, cancel=cancel)
        with self.assertRaises(InterruptedError):
            verify_sources(summary, cancel=cancel)


if __name__ == "__main__":
    unittest.main()
