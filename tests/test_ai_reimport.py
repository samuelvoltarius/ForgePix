"""Reopening scientific AI results must never apply the generic ADU export."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

import numpy as np
import tifffile
from astropy.io import fits
from PySide6.QtWidgets import QApplication

from ui.ai_preview import create_previews
from ui.main_window import MainWindow


class AIReimportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "source.fits"
        image = np.linspace(-4, 2200, 256, dtype=np.float32).reshape(16, 16)
        fits.writeto(self.source, image, fits.Header({"BUNIT": "electron/s"}))
        self.output = self.root / "ai-starless-example"
        self.output.mkdir()
        files = []
        for name, role, values in (("result_32bit", "result", image * .95),
                                   ("stars_residual_32bit", "stars_residual", image * .05)):
            header = fits.Header({"CREATOR": "ForgePix", "FPDOMAIN": "LINEAR_AI_ESTIMATE",
                                  "FPAIROLE": role, "FPAIMOD": "own-model", "FPQUAL": "EXPERIMENTAL",
                                  "FPLINEAR": True, "BUNIT": "electron/s", "CRVAL1": 123.4})
            metadata = {"forgepix": True, "domain": "LINEAR_AI_ESTIMATE", "role": role,
                        "linear": True, "status": "experimental", "photometry_validated": False,
                        "fits_header": header.tostring(sep="\n", endcard=False, padding=False)}
            tif_path, fits_path = self.output / (name + ".tif"), self.output / (name + ".fits")
            tifffile.imwrite(tif_path, values, metadata=None, description=json.dumps(metadata))
            fits.writeto(fits_path, values, header)
            files.extend((tif_path, fits_path))
        self.files = files
        self.result = files[0]
        self.report = {"schema_version": 1, "task": "starless", "model_id": "own-model",
                       "status": "experimental", "release_approved": False,
                       "source": {"path": str(self.source), "sha256": self.digest(self.source)},
                       "outputs": [path.name for path in files],
                       "output_integrity": [{"name": path.name, "bytes": path.stat().st_size,
                                             "sha256": self.digest(path)} for path in files]}
        self.write_report()
        self.originals = {path.name: path.read_bytes() for path in [self.source, *files]}
        for name in ("_restore_settings", "_save_settings"):
            patcher = patch.object(MainWindow, name)
            patcher.start()
            self.addCleanup(patcher.stop)
        updater = patch("ui.main_window._UpdateChecker.start")
        updater.start()
        self.addCleanup(updater.stop)

    @staticmethod
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def write_report(self):
        (self.output / "ai_report.json").write_text(json.dumps(self.report), encoding="utf-8")

    def window(self):
        window = MainWindow()
        def dispose():
            window.deleteLater()
            self.app.processEvents()
        self.addCleanup(dispose)
        return window

    def reimport(self, window, path):
        with patch("ui.main_window.QFileDialog.getOpenFileName", return_value=(str(path), "")):
            window.reimport_result()

    def assert_science_export(self, window):
        with patch.object(window, "_export_ai_result") as scientific_dialog:
            window.export_result()
            scientific_dialog.assert_called_once_with()
        destination = Path(window._write_ai_export(str(self.root), linear=True))
        for path in self.files:
            self.assertEqual((destination / path.name).read_bytes(), self.originals[path.name])
        self.assertEqual((destination / "ai_report.json").read_bytes(),
                         (self.output / "ai_report.json").read_bytes())
        data, header = fits.getdata(destination / "result_32bit.fits", header=True)
        self.assertGreater(float(data.max()), 1500)
        self.assertLess(float(data.min()), 0)
        self.assertEqual(header["BUNIT"], "electron/s")
        self.assertEqual(header["CRVAL1"], 123.4)
        self.assertEqual(header["FPQUAL"], "EXPERIMENTAL")

    def test_fresh_window_reimports_tiff_and_fits_and_exports_all_layers_byte_exact(self):
        for selected in self.files:
            with self.subTest(selected=selected.name):
                window = self.window()
                self.reimport(window, selected)
                self.assertTrue(window._is_ai_result_current())
                self.assertTrue(window.export_btn.isEnabled())
                self.assertEqual(Path(window.before_path), self.source)
                self.assertIsNotNone(window._ai_display_for_current())
                self.assert_science_export(window)
        self.assertEqual(self.source.read_bytes(), self.originals[self.source.name])

    def test_valid_existing_display_cache_is_reused(self):
        display = create_previews(self.source, self.result)
        window = self.window()
        with patch("ui.ai_preview.create_previews", side_effect=AssertionError("cache should be reused")):
            self.reimport(window, self.result)
        self.assertEqual(window._ai_display_for_current(), display)

    def test_missing_source_and_previews_keep_scientific_export_available(self):
        self.source.unlink()
        window = self.window()
        self.reimport(window, self.result.with_suffix(".fits"))
        self.assertTrue(window._is_ai_result_current())
        self.assertIsNone(window.before_path)
        self.assertIsNone(window._ai_display_for_current())
        self.assertFalse(window.cmp_btn.isEnabled())
        self.assert_science_export(window)

    def test_changed_source_with_preserved_timestamp_is_not_used_for_comparison(self):
        create_previews(self.source, self.result)
        stamp = self.source.stat()
        fits.writeto(self.source, np.ones((16, 16), np.float32), overwrite=True)
        os.utime(self.source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        window = self.window()
        self.reimport(window, self.result)
        self.assertIsNone(window._ai_display_for_current())
        self.assertIsNone(window.before_path)
        self.assert_science_export(window)

    def test_preview_generation_failure_does_not_block_scientific_export(self):
        window = self.window()
        with patch("ui.ai_preview.create_previews", side_effect=OSError("read-only folder")):
            self.reimport(window, self.result)
        self.assertTrue(window._is_ai_result_current())
        self.assertIsNone(window._ai_display_for_current())
        self.assert_science_export(window)

    def test_unlisted_neighbour_is_not_treated_as_ai_and_clears_old_context(self):
        unrelated = self.output / "unrelated.tif"
        tifffile.imwrite(unrelated, np.ones((16, 16), np.float32))
        window = self.window()
        self.reimport(window, self.result)
        self.reimport(window, unrelated)
        self.assertFalse(window._is_ai_result_current())
        self.assertIsNone(window._ai_display_for_current())
        self.assertIsNone(window.before_path)

    def test_changed_selected_file_is_rejected_before_switching_to_generic_export(self):
        window = self.window()
        window.result_path = str(self.source)
        stamp = self.result.stat()
        with self.result.open("r+b") as stream:
            stream.seek(-4, 2)
            stream.write(b"\0\0\0\0")
        os.utime(self.result, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        with patch("ui.main_window.QMessageBox.warning") as warning:
            self.reimport(window, self.result)
        warning.assert_called_once()
        self.assertEqual(window.result_path, str(self.source))
        self.assertEqual(list(self.root.glob("export-ai-*")), [])

    def test_reimport_hashes_only_selected_output_and_export_detects_changed_sibling(self):
        self.files[-1].unlink()
        window = self.window()
        self.reimport(window, self.result)
        self.assertTrue(window._is_ai_result_current())
        with self.assertRaisesRegex(ValueError, "Ergebnisdateien wurden verändert"):
            window._write_ai_export(str(self.root), linear=True)
        self.assertEqual(list(self.root.glob("export-ai-*")), [])

    def test_marked_ai_without_usable_report_is_rejected_but_unmarked_file_is_accepted(self):
        for suffix in (".tif", ".fits"):
            for value in (None, {"outputs": None}, {"outputs": 4}, {"outputs": [None]}, "broken"):
                with self.subTest(suffix=suffix, report=value):
                    report_path = self.output / "ai_report.json"
                    if value is None:
                        report_path.unlink(missing_ok=True)
                    else:
                        report_path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
                    window = self.window()
                    window.result_path = str(self.source)
                    with patch("ui.main_window.QMessageBox.warning") as warning:
                        self.reimport(window, self.result.with_suffix(suffix))
                    warning.assert_called_once()
                    self.assertEqual(window.result_path, str(self.source))
        unmarked = self.root / "result_32bit.tif"
        tifffile.imwrite(unmarked, np.ones((16, 16), np.float32))
        window = self.window()
        self.reimport(window, unmarked)
        self.assertEqual(window.result_path, str(unmarked))
        self.assertFalse(window._is_ai_result_current())


if __name__ == "__main__":
    unittest.main()
