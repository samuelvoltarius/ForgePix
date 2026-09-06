import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np
import tifffile
from astropy.io import fits

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import astro
import channels
from constants import ForgePixFehler


class FloatFits(unittest.TestCase):
    def test_signed_high_range_and_tiny_values_roundtrip(self):
        rgb = np.random.default_rng(9).uniform(-.2, 4, (20, 24, 3)).astype(np.float32)
        rgb[5, 5] = [1e-8, 2e-8, 3e-8]
        with tempfile.TemporaryDirectory() as folder:
            for kind in ("mono", "rgb"):
                data = rgb[..., 0] if kind == "mono" else np.moveaxis(rgb, -1, 0)
                path = Path(folder) / (kind + ".fits")
                fits.writeto(path, data)
                read = astro._read_float(str(path))
                expected = np.repeat(data[..., None], 3, -1) if kind == "mono" else rgb[..., ::-1]
                np.testing.assert_array_equal(read, expected)

    def test_integer_scaling_does_not_depend_on_hot_pixel(self):
        with tempfile.TemporaryDirectory() as folder:
            for peak in (100, 300, 60000):
                raw = np.full((16, 16), 100, np.uint16)
                raw[5, 5] = peak
                path = Path(folder) / (str(peak) + ".fit")
                fits.writeto(path, raw)
                self.assertAlmostEqual(float(astro._read_float(str(path))[0, 0, 0]), 100 / 65535, places=8)

    def test_float_bayer_all_patterns_offsets_and_measured_samples(self):
        with tempfile.TemporaryDirectory() as folder:
            for pattern in astro._BAYER2CV:
                for x, y in ((0, 0), (1, 0), (0, 1), (1, 1)):
                    tile = np.roll(np.array(list(pattern)).reshape(2, 2), (-y, -x), (0, 1))
                    levels = {"R": 2.01, "G": .00000002, "B": .00000003}
                    raw = np.empty((18, 20), np.float32)
                    for i in range(2):
                        for j in range(2):
                            raw[i::2, j::2] = levels[tile[i, j]]
                    path = Path(folder) / "cfa.fit"
                    fits.writeto(path, raw, fits.Header({"BAYERPAT": pattern, "XBAYROFF": x,
                                                        "YBAYROFF": y}), overwrite=True)
                    for result in (astro._read_float(str(path)), astro.read_calibrated(str(path))):
                        for c, name in enumerate("BGR"):
                            np.testing.assert_allclose(result[..., c], levels[name], rtol=2e-7, atol=0)
                    # Real sensor samples must not be modified by interpolation.
                    raw += np.random.default_rng(8).uniform(0, .01, raw.shape).astype(np.float32)
                    result = astro.debayer_float(raw, pattern, x, y)
                    for i in range(2):
                        for j in range(2):
                            c = "BGR".index(tile[i, j])
                            np.testing.assert_array_equal(result[i::2, j::2, c], raw[i::2, j::2])


class ChannelWorkflow(unittest.TestCase):
    def test_rgb_file_roundtrip_preserves_range_and_sources(self):
        rgb = np.random.default_rng(1).uniform(-.1, 2, (32, 40, 3)).astype(np.float32)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "linear.fits"
            fits.writeto(source, np.moveaxis(rgb, -1, 0))
            original = source.read_bytes()
            split = Path(channels.split_file(source, log=lambda *a: None))
            paths = {line: split / (line + ".fits") for line in "RGB"}
            first = Path(channels.combine_files(paths, align=False, log=lambda *a: None)).parent
            second = Path(channels.combine_files(paths, align=False, log=lambda *a: None)).parent
            self.assertNotEqual(first, second)
            np.testing.assert_array_equal(tifffile.imread(first / "combined_32bit.tif"), rgb)
            np.testing.assert_array_equal(fits.getdata(first / "combined_32bit.fits"), np.moveaxis(rgb, -1, 0))
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(json.loads((split / "channels.json").read_text())["source"]["sha256"],
                             hashlib.sha256(original).hexdigest())

    def test_sii_oiii_does_not_create_missing_ha(self):
        bgr = np.full((16, 16, 3), (3e-8, 6e-8, 2.5), np.float32)
        planes = channels.extract(bgr, "sv220_sii_oiii_7")
        self.assertEqual(set(planes), {"SII", "OIII"})
        np.testing.assert_array_equal(planes["SII"], bgr[..., 2])
        np.testing.assert_allclose(planes["OIII"], 5e-8)
        result = channels.combine(planes, "SOO")
        np.testing.assert_allclose(result[..., 1], 5e-8)
        np.testing.assert_array_equal(result[..., 2], 2.5)
        with self.assertRaisesRegex(ForgePixFehler, "Ha"):
            channels.combine(planes, "SHO")
        for key in ("quad", "uvir", "sii", "unknown"):
            with self.assertRaises(ForgePixFehler):
                channels.extract(bgr, key)

    def test_coverage_and_estimated_line_identity_survive_tiff_and_fits(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "color.fits"
            fits.writeto(source, np.full((3, 20, 24), .2, np.float32))
            split = Path(channels.split_file(source, "sv220_sii_oiii_7", log=lambda *a: None))
            mask = np.ones((20, 24), np.uint8)
            mask[:, :4] = 0
            tifffile.imwrite(split / "coverage.tif", mask)
            for ext in ("tif", "fits"):
                paths = {key: split / (key + "." + ext) for key in ("SII", "OIII")}
                output = Path(channels.combine_files(paths, "SOO", align=False, log=lambda *a: None)).parent
                np.testing.assert_array_equal(tifffile.imread(output / "coverage.tif"), mask)
                result = tifffile.imread(output / "combined_32bit.tif")
                np.testing.assert_array_equal(result[:, :4], 0)
                report = json.loads((output / "channels.json").read_text())
                self.assertTrue(report["sources"]["SII"]["spectral_estimate"])
                with self.assertRaisesRegex(ForgePixFehler, "zugeordnet"):
                    channels.combine_files({"Ha": paths["SII"], "OIII": paths["OIII"]}, "HOO")
            (split / "coverage.tif").unlink()
            with self.assertRaisesRegex(ForgePixFehler, "Bildabdeckung fehlt"):
                channels.combine_files(paths, "SOO", align=False)

    def test_sho_uses_independent_measured_planes_and_explicit_gains(self):
        planes = {"SII": np.full((16, 16), 2, np.float32), "Ha": np.full((16, 16), .3, np.float32),
                  "OIII": np.full((16, 16), -.1, np.float32)}
        result = channels.combine(planes, "SHO", {"Ha": 2})
        np.testing.assert_array_equal(result[..., 0], planes["OIII"])
        np.testing.assert_array_equal(result[..., 1], planes["Ha"] * 2)
        np.testing.assert_array_equal(result[..., 2], planes["SII"])
        for gains in ({"Ha": np.nan}, {"SII": -1}, {"OIII": 11}):
            with self.assertRaises(ForgePixFehler):
                channels.combine(planes, "SHO", gains)

    def test_raw_cfa_jpeg_wrong_line_and_shape_are_actionable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw = root / "raw.fit"
            fits.writeto(raw, np.ones((20, 20), np.float32), fits.Header({"BAYERPAT": "RGGB"}))
            with self.assertRaisesRegex(ForgePixFehler, "zuerst"):
                channels.split_file(raw)
            with self.assertRaisesRegex(ForgePixFehler, "lineares FITS"):
                channels.read(root / "preview.jpg")
            sii = root / "SII.fit"
            fits.writeto(sii, np.ones((20, 20), np.float32), fits.Header({"FPLINE": "SII"}))
            with self.assertRaisesRegex(ForgePixFehler, "zugeordnet"):
                channels.combine_files({"Ha": sii, "OIII": sii}, "HOO")
            with self.assertRaisesRegex(ForgePixFehler, "gleich große"):
                channels.combine({"Ha": np.ones((20, 20)), "OIII": np.ones((21, 20))}, "HOO")

    def test_real_star_matching_and_uncovered_border(self):
        rng = np.random.default_rng(12)
        ref = np.full((160, 190), .002, np.float32)
        for x, y in rng.integers([20, 20], [170, 140], (60, 2)):
            ref[y, x] += rng.uniform(.2, .9)
        ref = cv2.GaussianBlur(ref, (5, 5), .8)
        moving = cv2.warpAffine(ref, np.array([[1, 0, 7], [0, 1, -4]], np.float32), (190, 160))
        with tempfile.TemporaryDirectory() as folder:
            paths = {"Ha": Path(folder) / "ha.fit", "OIII": Path(folder) / "oxygen.fit"}
            fits.writeto(paths["Ha"], ref)
            fits.writeto(paths["OIII"], moving)
            out = Path(channels.combine_files(paths, "HOO", log=lambda *a: None)).parent
            report = json.loads((out / "channels.json").read_text())
            matrix = np.asarray(report["transforms"]["OIII"])
            self.assertAlmostEqual(matrix[0, 2], -7, delta=.15)
            self.assertAlmostEqual(matrix[1, 2], 4, delta=.15)
            coverage = tifffile.imread(out / "coverage.tif").astype(bool)
            self.assertLess(coverage.mean(), .96)
            result = tifffile.imread(out / "combined_32bit.tif")
            np.testing.assert_array_equal(result[~coverage], 0)
            np.testing.assert_allclose(result[coverage, 0], result[coverage, 1], atol=1e-6)

    def test_native_development_preserves_narrowband_green_and_versions(self):
        import own_astro
        image = np.full((32, 32, 3), (.1, .4, .2), np.float32)
        with patch.object(astro, "color_balance", side_effect=AssertionError("white balance")), \
             patch.object(astro, "remove_green_cast", side_effect=AssertionError("SCNR")):
            result = own_astro.develop(image, background=False, filter_key="sv220_sii_oiii_7", log=lambda *a: None)
            self.assertTrue(np.isfinite(result).all())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "linear.tif"
            tifffile.imwrite(path, image[..., ::-1], photometric="rgb")
            with patch.object(own_astro, "develop", return_value=image):
                first = Path(own_astro.run(str(path)))
                original = first.read_bytes()
                second = Path(own_astro.run(str(path)))
            self.assertNotEqual(first.parent, second.parent)
            self.assertEqual(first.read_bytes(), original)
            with self.assertRaisesRegex(ForgePixFehler, "bereits gestreckt"):
                channels.read(first.parent / "developed_32bit.tif")


class ChannelsUI(unittest.TestCase):
    def test_filter_aware_form_and_required_lines(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from ui.channels_dialog import ChannelsDialog
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "image.fit"
            fits.writeto(path, np.ones((3, 16, 16), np.float32))
            dialog = ChannelsDialog(source=str(path), filter_key="sv220_sii_oiii_7")
            self.assertEqual(dialog.mode.currentData(), "split_dual")
            self.assertIn("SII", dialog.description.text())
            self.assertTrue(dialog.run_button.isEnabled())
            self.assertEqual(dialog.request()["filter_key"], "sv220_sii_oiii_7")
            dialog.mode.setCurrentIndex(dialog.mode.findData("SHO"))
            for key in ("SII", "OIII"):
                dialog.fields[key].setText(str(path))
            self.assertFalse(dialog.run_button.isEnabled())
            dialog.fields["Ha"].setText(str(path))
            self.assertTrue(dialog.run_button.isEnabled())
            self.assertEqual(set(dialog.request()["paths"]), {"SII", "Ha", "OIII"})
            self.assertTrue(dialog.request()["align"])
            dialog.deleteLater()
            app.processEvents()
