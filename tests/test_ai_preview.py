"""Linked AI display statistics and byte-preserving scientific export checks."""
import json
import hashlib
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

import cv2
import numpy as np
from astropy.io import fits
import tifffile
from ui.ai_preview import create_previews, display_parameters, display_pixels
from ui.export import ExportMixin
from ui.result_view import ResultMixin


class _Export(ExportMixin, ResultMixin):
    pass


class AIPreview(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    @staticmethod
    def record_files(output, files):
        (output / "ai_report.json").write_text(json.dumps({
            "outputs": [path.name for path in files],
            "output_integrity": [{"name": path.name, "bytes": path.stat().st_size,
                                  "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in files],
        }), encoding="utf-8")

    def test_comparison_uses_identical_integer_input_scale_and_display_transform(self):
        source = self.root / "source.fits"
        values = np.arange(256, dtype=np.uint16).reshape(16, 16) + 1600
        fits.writeto(source, values)
        result = self.root / "result_32bit.tif"
        tifffile.imwrite(result, values.astype(np.float32) / 65535)
        before_bytes, after_bytes = source.read_bytes(), result.read_bytes()
        display = create_previews(source, result)
        before = cv2.imread(display["before"], cv2.IMREAD_UNCHANGED)
        after = cv2.imread(display["after"], cv2.IMREAD_UNCHANGED)
        np.testing.assert_array_equal(before, after)
        self.assertGreater(float(before.mean()), 10)
        self.assertEqual(source.read_bytes(), before_bytes)
        self.assertEqual(result.read_bytes(), after_bytes)

    def test_one_source_stretch_preserves_model_brightness_difference(self):
        source = np.linspace(.01, .1, 256, dtype=np.float32).reshape(16, 16)
        parameters = display_parameters(source)
        before = display_pixels(source, parameters)
        after = display_pixels(source + .02, parameters)
        self.assertGreater(float(after.mean()), float(before.mean()) + 10)
        self.assertEqual(parameters["method"], "source_linked_mtf_v1")

    def test_physical_float_values_get_visible_preview_and_unchanged_scientific_export(self):
        source = self.root / "physical.fits"
        image = np.linspace(1500, 2200, 256, dtype=np.float32).reshape(16, 16)
        fits.writeto(source, image)
        output = self.root / "ai-output"
        output.mkdir()
        result = output / "result_32bit.tif"
        tifffile.imwrite(result, image * .95)
        fits.writeto(result.with_suffix(".fits"), image * .95)
        coverage = output / "coverage.tif"
        tifffile.imwrite(coverage, np.ones((16, 16), np.uint8))
        self.record_files(output, [result, result.with_suffix(".fits"), coverage])
        window = _Export()
        window.result_path = window._ai_result_path = str(result)
        window._ai_display = create_previews(source, result)
        exported = Path(window._write_ai_export(str(self.root), linear=True, png=True))
        for name in (result.name, result.with_suffix(".fits").name, "coverage.tif", "ai_report.json"):
            self.assertEqual((exported / name).read_bytes(), (output / name).read_bytes())
        png = cv2.imread(str(exported / "display_stretched.png"), cv2.IMREAD_UNCHANGED)
        self.assertGreater(int(png.max()), int(png.min()) + 100)
        self.assertLess(float(np.mean(png == 255)), .1)
        self.assertEqual(window.result_path, str(result))
        self.assertEqual(window._preview_png(str(source)), window._ai_display["before"])
        self.assertEqual(window._preview_png(str(result)), window._ai_display["after"])

    def test_changed_tiff_cannot_be_copied_with_old_fits_even_if_mtime_is_preserved(self):
        source = self.root / "source.fits"
        image = np.linspace(.01, .1, 256, dtype=np.float32).reshape(16, 16)
        fits.writeto(source, image)
        output = self.root / "ai-output"
        output.mkdir()
        result = output / "result_32bit.tif"
        tifffile.imwrite(result, image)
        fits.writeto(result.with_suffix(".fits"), image)
        self.record_files(output, [result, result.with_suffix(".fits")])
        window = _Export()
        window.result_path = window._ai_result_path = str(result)
        stamp = result.stat()
        tifffile.imwrite(result, image * .5)
        os.utime(result, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        with self.assertRaisesRegex(ValueError, "Ergebnisdateien wurden verändert"):
            window._write_ai_export(str(self.root), linear=True)
        self.assertEqual(list(self.root.glob("export-ai-*")), [])

    def test_old_report_without_integrity_keeps_display_export_but_rejects_scientific_group(self):
        source = self.root / "source.fits"
        image = np.linspace(.01, .1, 256, dtype=np.float32).reshape(16, 16)
        fits.writeto(source, image)
        result = self.root / "result_32bit.tif"
        tifffile.imwrite(result, image)
        fits.writeto(result.with_suffix(".fits"), image)
        (self.root / "ai_report.json").write_text(json.dumps({"outputs": [result.name]}), encoding="utf-8")
        window = _Export()
        window.result_path = window._ai_result_path = str(result)
        window._ai_display = create_previews(source, result)
        with self.assertRaisesRegex(ValueError, "Prüfsummen"):
            window._write_ai_export(str(self.root), linear=True)
        exported = Path(window._write_ai_export(str(self.root), linear=False, png=True))
        self.assertTrue((exported / "display_stretched.png").is_file())

    def test_changed_source_invalidates_both_linked_comparison_images(self):
        source = self.root / "source.fits"
        image = np.linspace(.01, .1, 256, dtype=np.float32).reshape(16, 16)
        fits.writeto(source, image)
        result = self.root / "result_32bit.tif"
        tifffile.imwrite(result, image)
        window = _Export()
        window.result_path = window._ai_result_path = str(result)
        window._ai_display = create_previews(source, result)
        stamp = source.stat()
        os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1_000_000_000))
        self.assertIsNone(window._ai_display_for_current())
        self.assertIsNone(window._preview_png(str(source)))
        self.assertIsNone(window._preview_png(str(result)))

    def test_current_float_result_wins_over_star_residual_sibling(self):
        from ui.main_window import MainWindow
        result = self.root / "selected_linear.tif"
        tifffile.imwrite(self.root / "stars_residual_32bit.tif", np.zeros((4, 4), np.float32))
        tifffile.imwrite(result, np.ones((4, 4), np.float32))
        window = SimpleNamespace(result_path=str(result), _is_ai_result_current=lambda: False)
        self.assertEqual(MainWindow._best_export_file(window, bits=32), str(result))


if __name__ == "__main__":
    unittest.main()
