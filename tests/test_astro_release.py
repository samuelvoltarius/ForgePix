"""Release contracts for FITS ingestion, sensor calibration and linear exports."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import cv2
from astropy.io import fits
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import astro
import astro_input
import focus_cull_stack as pipeline
from constants import imwrite


class AstroRelease(unittest.TestCase):
    def test_calibration_precedes_debayer(self):
        rng = np.random.default_rng(7)
        flat = rng.uniform(.3, .7, (40, 40)).astype(np.float32)
        dark = np.full(flat.shape, .01, np.float32)
        raw = .2 * flat / flat.mean() + dark
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "Light.fit"
            hdu = fits.PrimaryHDU(raw)
            hdu.header["BAYERPAT"] = "RGGB"
            hdu.writeto(p)
            calibrated = astro.read_calibrated(str(p), dark, flat)
            np.testing.assert_allclose(calibrated[2:-2, 2:-2], .2, atol=3e-5)

    def test_monochrome_fits_does_not_invent_colour(self):
        raw = np.random.default_rng(3).uniform(.1, .8, (30, 30)).astype(np.float32)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "mono.fit"
            fits.writeto(p, raw)
            f = astro._read_float(str(p))
            for channel in range(3):
                np.testing.assert_allclose(f[..., channel], raw)

    def test_float_tiff_remains_linear(self):
        import tifffile
        rgb = np.random.default_rng(2).uniform(.05, .8, (20, 20, 3)).astype(np.float32)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "linear.tif"
            tifffile.imwrite(p, rgb, photometric="rgb")
            np.testing.assert_allclose(astro._read_float(str(p)), rgb[..., ::-1], atol=1e-6)

    def test_nested_asiair_uses_only_light_fits(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "Plan" / "Light" / "M27"
            folder.mkdir(parents=True)
            fits.writeto(folder / "Light_1.fit", np.ones((10,10), np.uint16))
            fits.writeto(folder / "Dark_1.fit", np.ones((10,10), np.uint16))
            imwrite(str(folder / "Light_1.jpg"), np.full((10,10,3), 100, np.uint8))
            self.assertEqual(astro_input.series_folders(d), [(str(folder), 1)])
            paths = pipeline._gather_session_paths(str(folder), SimpleNamespace(also=[str(folder)]))
            self.assertEqual(paths, [str(folder / "Light_1.fit")])

    def test_master_preserves_sensor_pixels(self):
        raw = np.random.default_rng(5).uniform(.1,.2,(20,20)).astype(np.float32)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "dark.fit"
            hdu=fits.PrimaryHDU(raw); hdu.header["BAYERPAT"]="RGGB"; hdu.writeto(p)
            np.testing.assert_allclose(astro._master(str(p), raw=True), raw)

    def test_incomplete_fits_can_be_retried(self):
        import livestack
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "Light.fit"
            p.write_bytes(b"SIMPLE")
            state = livestack.LiveStack(registrieren=False, gewichten=False, log=lambda *a: None)
            self.assertFalse(state.hinzufuegen(str(p)))
            fits.writeto(p, np.full((20,20), .2, np.float32), overwrite=True)
            self.assertTrue(state.hinzufuegen(str(p)))
            self.assertEqual(state.n, 1)

    def test_mismatched_calibration_explains_problem(self):
        from constants import ForgePixFehler
        with self.assertRaisesRegex(ForgePixFehler, "Master passt nicht"):
            astro.calibrate(np.zeros((20,20)), np.zeros((10,10)))
