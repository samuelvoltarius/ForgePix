"""Native solve file transactions preserve scientific data and metadata."""
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

import numpy as np
import tifffile
from astropy.io import fits
from PySide6.QtWidgets import QApplication
import astrometry
from astrometry_file import solve_file
from test_astrometry import fixture
from project_store import Project
from ui.astrometry_dialog import AstrometryDialog, header_hints


class AstrometryFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.points, cls.measured, cls.shape, cls.catalogue, cls.hints, _ = fixture()
        cls.solution = astrometry.solve_positions(cls.measured, cls.shape, cls.catalogue,
                                                  cls.hints, log=lambda *_: None)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.catalogue_path = self.root / "catalogue.npz"
        self.catalogue.speichern(self.catalogue_path)
        self.source = self.root / "original.fits"
        yy, xx = np.indices(self.shape)
        data = np.full(self.shape, .025, np.float64)
        for index, (x, y) in enumerate(self.points):
            data += (.16 - index * .001) * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.5 ** 2))
        data[0, 0] = -1e-10
        data[-1, -1] = 1.123456789012
        self.data = data
        header = fits.Header({"FPLINEAR": True, "FPDOMAIN": "LINEAR", "BUNIT": "electron",
                              "FILTER": "L", "EXPTIME": 300.0, "FPCOV": "coverage.tif",
                              "FPDRZWGT": "weights.tif", "FPPIXARE": .25})
        fits.writeto(self.source, data, header)
        tifffile.imwrite(self.root / "coverage.tif", np.ones(self.shape, np.uint8))
        tifffile.imwrite(self.root / "weights.tif", np.full(self.shape, 8.25, np.float32))
        self.original = self.source.read_bytes()

    def test_float64_units_coverage_and_project_roundtrip_are_preserved(self):
        with patch("astrometry.solve", return_value=self.solution):
            result = solve_file(self.source, self.catalogue_path, self.hints, self.root, log=lambda *_: None)
        path = Path(result["result_path"])
        self.assertTrue(np.array_equal(fits.getdata(path), self.data))
        self.assertEqual(fits.getdata(path).dtype.itemsize, 8)
        header = fits.getheader(path)
        self.assertEqual(header["BUNIT"], "electron")
        self.assertEqual(header["FPPIXARE"], .25)
        self.assertEqual(header["FPDOMAIN"], "LINEAR")
        for name in ("coverage.tif", "weights.tif"):
            self.assertEqual((path.parent / name).read_bytes(), (self.root / name).read_bytes())
        project = Project.create(self.root / "Astrometry.forgepix", "Astrometry", {})
        identifier = project.add_result(path, self.source)
        export = Path(project.export_step(identifier, self.root / "Export"))
        self.assertEqual((export / "solved.fits").read_bytes(), path.read_bytes())
        self.assertTrue((export / "astrometry_report.json").is_file())
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_unsigned_physical_values_are_not_normalized_by_wcs_export(self):
        data = np.arange(np.prod(self.shape), dtype=np.uint32).reshape(self.shape)
        fits.writeto(self.source, data, fits.Header({"BUNIT": "adu", "FPLINEAR": True}), overwrite=True)
        with patch("astrometry.solve", return_value=self.solution):
            result = solve_file(self.source, self.catalogue_path, self.hints, self.root, log=lambda *_: None)
        np.testing.assert_array_equal(fits.getdata(result["result_path"]), data)
        self.assertEqual(fits.getdata(result["result_path"]).dtype.kind, "u")
        self.assertEqual(fits.getheader(result["result_path"])["BUNIT"], "adu")

    def test_ai_estimate_keeps_verified_provenance_after_solve_and_project_reopen(self):
        import ai_restore
        import json
        from ui.main_window import MainWindow
        from ui.export import _verified_ai_files
        restored = Path(ai_restore.run_file(self.source, "forgepix-denoise-mono-v2", self.root,
            strength=.25, device="cpu", allow_experimental=True, log=lambda *_: None)).with_suffix(".fits")
        original_ai_report = json.loads((restored.parent / "ai_report.json").read_text(encoding="utf-8"))
        with patch("astrometry.solve", return_value=self.solution):
            result = solve_file(restored, self.catalogue_path, self.hints, self.root, log=lambda *_: None)
        solved = Path(result["result_path"])
        np.testing.assert_array_equal(fits.getdata(solved), fits.getdata(restored))
        self.assertEqual(fits.getheader(solved)["FPDOMAIN"], "LINEAR_AI_ESTIMATE")
        self.assertEqual(result["report"]["source_processing_reports"]["ai_report.json"], original_ai_report)
        derived = json.loads((solved.parent / "ai_report.json").read_text(encoding="utf-8"))
        self.assertEqual(derived["model_sha256"], original_ai_report["model_sha256"])
        self.assertFalse(derived["postprocessing"][-1]["model_executed_again"])
        for target in ("ui.main_window.MainWindow._restore_settings", "ui.main_window.MainWindow._save_settings",
                       "ui.main_window._UpdateChecker.start"):
            context = patch(target)
            context.start()
            self.addCleanup(context.stop)
        window = MainWindow()
        self.addCleanup(window.deleteLater)
        window._project = Project.create(self.root / "AI-Solve.forgepix", "AI-Solve", {})
        identifier = window._project.add_result(solved, restored)
        window._open_project_step(identifier)
        self.assertTrue(window._is_ai_result_current())
        archived = Path(window.result_path)
        _verified_ai_files(archived)
        report_path = archived.parent / "astrometry_report.json"
        report_path.write_text(report_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
        with self.assertRaises(ValueError):
            _verified_ai_files(archived)

    def test_source_change_and_incomplete_coverage_never_publish_a_result(self):
        def changed(*args, **kwargs):
            with fits.open(self.source, mode="update", memmap=False) as hdus:
                hdus[0].data[3, 3] += .1
            return self.solution
        with patch("astrometry.solve", side_effect=changed):
            with self.assertRaisesRegex(Exception, "verändert"):
                solve_file(self.source, self.catalogue_path, self.hints, self.root, log=lambda *_: None)
        self.assertFalse(list(self.root.glob("*stack-astrometry*")))
        coverage = np.ones(self.shape, np.uint8)
        coverage[0, 0] = 0
        tifffile.imwrite(self.root / "coverage.tif", coverage)
        with self.assertRaisesRegex(Exception, "unbedeckte"):
            solve_file(self.source, self.catalogue_path, self.hints, self.root, log=lambda *_: None)
        self.assertFalse(list(self.root.glob("*stack-astrometry*")))

    def test_raw_cfa_and_precancelled_run_leave_no_output(self):
        with fits.open(self.source, mode="update") as hdus:
            hdus[0].header["BAYERPAT"] = "RGGB"
        with self.assertRaisesRegex(Exception, "Bayer"):
            solve_file(self.source, self.catalogue_path, self.hints, self.root, log=lambda *_: None)
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Exception):
            solve_file(self.source, self.catalogue_path, self.hints, self.root, cancel=cancel)
        self.assertFalse(list(self.root.glob("*stack-astrometry*")))

    def test_real_gui_solves_and_returns_an_unmodified_fits(self):
        dialog = AstrometryDialog(source=self.source, catalogue=self.catalogue_path)
        self.addCleanup(dialog.deleteLater)
        self.assertFalse(dialog.run_button.isEnabled())  # No silently invented hints.
        dialog.ra.setText(str(self.hints["ra"]))
        dialog.dec.setText(str(self.hints["dec"]))
        dialog.scale.setText("3,6")
        dialog.destination.setText(str(self.root))
        dialog.run_button.click()
        self.assertTrue(dialog.is_running())
        end = time.monotonic() + 30
        while dialog.is_running() and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(.01)
        self.assertFalse(dialog.is_running())
        self.assertIsNotNone(dialog.result_path, dialog.feedback.text())
        self.assertGreaterEqual(dialog.result_report["solution"]["validation_matches"], 8)
        np.testing.assert_array_equal(fits.getdata(dialog.result_path), self.data)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_header_hints_do_not_substitute_equipment_for_missing_metadata(self):
        self.assertEqual(header_hints(self.source), {})
        with fits.open(self.source, mode="update") as hdus:
            hdus[0].header.update(OBJCTRA="20 00 42", OBJCTDEC="+22 47 42", XPIXSZ=4.63, FOCALLEN=1151)
        values = header_hints(self.source)
        self.assertAlmostEqual(values["ra"], 300.175)
        self.assertAlmostEqual(values["dec"], 22.795)
        self.assertAlmostEqual(values["pixelscale_arcsec"], .82973, places=4)


if __name__ == "__main__":
    unittest.main()
