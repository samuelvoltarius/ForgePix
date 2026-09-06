"""Recorded acquisition differences must fail before pixel arithmetic."""
import sys
from pathlib import Path
import tempfile
import unittest
import numpy as np
from astropy.io import fits
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import calibration_metadata as metadata
from constants import ForgePixFehler


class CalibrationMetadata(unittest.TestCase):
    def test_known_sensor_and_flat_filter_mismatches(self):
        with tempfile.TemporaryDirectory() as folder:
            light = Path(folder) / "light.fit"
            master = Path(folder) / "master.fit"
            header = fits.Header({"INSTRUME": "ZWO ASI294MC Pro", "GAIN": 131,
                "XBINNING": 1, "YBINNING": 1, "FILTER": "SII OIII", "EXPTIME": 300,
                "CCD-TEMP": -10, "BAYERPAT": "RGGB", "READMODE": "normal"})
            fits.writeto(light, np.ones((8, 8), np.uint16), header)
            for key, value, kind in (("INSTRUME", "Different camera", "dark"),
                                    ("GAIN", 120, "dark"), ("XBINNING", 2, "flat"),
                                    ("FILTER", "Ha OIII", "flat"), ("BAYERPAT", "BGGR", "dark"),
                                    ("CCD-TEMP", 0, "dark"), ("READMODE", "high gain", "bias")):
                with self.subTest(key=key):
                    other = header.copy()
                    other[key] = value
                    fits.writeto(master, np.ones((8, 8), np.uint16), other, overwrite=True)
                    with self.assertRaises(ForgePixFehler):
                        metadata.validate([light], {kind: [master]})

    def test_exposure_scaling_is_explicit_and_unknown_fields_stay_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            light, dark = Path(folder) / "light.fit", Path(folder) / "dark.fit"
            fits.writeto(light, np.ones((8, 8), np.uint16), fits.Header({"EXPTIME": 300}))
            fits.writeto(dark, np.ones((8, 8), np.uint16), fits.Header({"EXPTIME": 60}))
            with self.assertRaisesRegex(ForgePixFehler, "Belichtungszeit"):
                metadata.validate([light], {"dark": [dark]})
            report = metadata.validate([light], {"dark": [dark]}, scale_dark=True)
            self.assertIn("Kamera", report["missing_metadata"])
            self.assertEqual(report["fits_lights_checked"], 1)

    def test_all_lights_checked_against_calibration(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder) / f"{i}.fit" for i in range(3)]
            for path, exp in zip(paths, (300, 60, 300)):
                fits.writeto(path, np.ones((8, 8), np.uint16), fits.Header({"EXPTIME": exp}))
            with self.assertRaisesRegex(ForgePixFehler, "Belichtungszeit"):
                metadata.validate(paths[:2], {"dark": paths[2:]})

    def test_broadband_camera_alias_case_and_whitespace(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder) / f"{i}.fit" for i in range(2)]
            for path, camera in zip(paths, ("ZWO ASI294MC Pro", "zwo  asi294mc pro")):
                fits.writeto(path, np.ones((8, 8), np.uint16), fits.Header({"INSTRUME": camera}))
            metadata.validate(paths[:1], {"flat": paths[1:]})
