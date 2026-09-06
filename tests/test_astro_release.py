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
    def test_sii_oiii_preview_keeps_green_signal(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            image = np.zeros((16, 16, 3), np.float32)
            image[..., 0] = .2
            image[..., 1] = .4
            image[..., 2] = .1
            args = SimpleNamespace(prefix="", fits_out=True, astro_stretch=False,
                                   aufnahmefilter="sv220_sii_oiii_7")
            with patch.object(astro, "color_balance", side_effect=AssertionError("white balance")), \
                 patch.object(astro, "remove_green_cast", side_effect=AssertionError("SCNR")):
                result = pipeline._astro_write(image, folder, ["Light.fit"], args, astro)
            with fits.open(Path(result) / "Light_astro_linear.fits") as hdus:
                np.testing.assert_array_equal(hdus[0].data, np.moveaxis(image[..., ::-1], -1, 0))
            self.assertEqual(fits.getheader(Path(result) / "Light_astro_linear.fits")["IMAGETYP"],
                             "MASTER LIGHT")

    def test_repeated_export_folders_are_not_reimported_as_lights(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            generated = root / "stack-abcd"
            generated.mkdir()
            fits.writeto(generated / "Light_astro_linear.fits", np.ones((8, 8), np.float32))
            fits.writeto(root / "output.fits", np.ones((8, 8), np.float32),
                         fits.Header({"IMAGETYP": "MASTER LIGHT"}))
            fits.writeto(root / "Light.fit", np.ones((8, 8), np.float32))
            self.assertEqual(astro_input.series_folders(folder), [(folder, 1)])

    def test_export_failure_preserves_existing_results_and_propagates(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            old = Path(folder) / "stack"
            old.mkdir()
            original = old / "original.fit"
            original.write_bytes(b"preserve me")
            args = SimpleNamespace(prefix="", fits_out=True)
            image = np.full((12, 12, 3), .2, np.float32)
            with patch("tifffile.imwrite", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(RuntimeError, "32-bit-TIFF"):
                    pipeline._astro_write(image, folder, ["Light.fit"], args, astro)
            self.assertEqual(original.read_bytes(), b"preserve me")
            with patch.object(fits.PrimaryHDU, "writeto", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(RuntimeError, "FITS konnte"):
                    pipeline._astro_write(image, folder, ["Light.fit"], args, astro)
            self.assertEqual(original.read_bytes(), b"preserve me")

    def test_bias_flat_mismatch_is_not_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            flat_path, bias_path = Path(folder) / "flat.fit", Path(folder) / "bias.fit"
            fits.writeto(flat_path, np.ones((12, 12), np.float32))
            fits.writeto(bias_path, np.ones((6, 6), np.float32))
            args = SimpleNamespace(no_auto_calib=True, dark=None,
                                   flat=str(flat_path), bias=str(bias_path))
            with self.assertRaisesRegex(ValueError, "unterschiedliche Bildgrößen"):
                pipeline._load_astro_calibration(folder, args, [])

    def test_calibration_directory_prefers_fits_and_rejects_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            args = SimpleNamespace(no_auto_calib=True, dark=folder, flat=None, bias=None)
            with self.assertRaisesRegex(ValueError, "Keine Kalibrierbilder"):
                pipeline._load_astro_calibration(folder, args, [])
            fits.writeto(Path(folder) / "dark.fit", np.full((12, 12), .02, np.float32))
            cv2.imwrite(str(Path(folder) / "dark.jpg"), np.full((6, 6, 3), 255, np.uint8))
            dark, _, _ = pipeline._load_astro_calibration(folder, args, [])
            self.assertEqual(dark.shape, (12, 12))
            np.testing.assert_allclose(dark, .02)

    def test_invalid_fits_calibration_pixels_are_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "bad.fit"
            for value in (np.nan, np.inf, -np.inf):
                raw = np.ones((12, 12), np.float32)
                raw[4, 4] = value
                fits.writeto(p, raw, overwrite=True)
                with self.assertRaisesRegex(ValueError, "FITS-Sensordaten"):
                    astro._master(str(p), raw=True)
                with self.assertRaisesRegex(ValueError, "FITS-Sensordaten"):
                    astro.read_calibrated(str(p))
            fits.PrimaryHDU().writeto(p, overwrite=True)
            with self.assertRaisesRegex(ValueError, "primären HDU"):
                astro.read_calibrated(str(p))

    def test_known_filter_overrides_dualband_filename_and_flag(self):
        import filters
        from unittest.mock import patch
        args = SimpleNamespace(dualband=True)
        sii = filters.hole("sv220_sii_oiii_7")
        with patch.object(pipeline, "_detect_dualband", return_value=True) as detect:
            self.assertFalse(pipeline._use_ha_oiii_preview(args, ["HaOIII.fit"], sii))
            self.assertFalse(pipeline._use_ha_oiii_preview(args, [], filters.hole("uvir")))
            self.assertTrue(pipeline._use_ha_oiii_preview(args, [], filters.hole("dual7")))
            detect.assert_not_called()
        with self.assertRaises(ValueError):
            pipeline._dualband_view(np.zeros((8, 8, 3), np.float32), "hoo", astro, sii)

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

    def test_invalid_masters_fail_instead_of_poisoning_stack(self):
        from constants import ForgePixFehler
        light = np.full((8, 8), .2, np.float32)
        for master in (np.full_like(light, np.nan), np.full_like(light, np.inf)):
            with self.assertRaisesRegex(ForgePixFehler, "Dark-Master"):
                astro.calibrate(light, dark=master)
            with self.assertRaisesRegex(ForgePixFehler, "Flat-Master"):
                astro.calibrate(light, flat=master)
        with self.assertRaisesRegex(ForgePixFehler, "Flat-Master ist leer"):
            astro.calibrate(light, flat=np.zeros_like(light))

    def test_unsigned_calibration_does_not_wrap_and_preserves_sources(self):
        light = np.full((8, 8), 10, np.uint16)
        dark = np.full_like(light, 20)
        result = astro.calibrate(light, dark=dark)
        np.testing.assert_array_equal(result, -10)
        np.testing.assert_array_equal(light, 10)
        np.testing.assert_array_equal(dark, 20)
