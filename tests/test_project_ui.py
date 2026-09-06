"""Real project workers, snapshot adoption and coverage-aware display checks."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

import cv2
import numpy as np
import tifffile
from astropy.io import fits
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QPushButton
from project_store import Project, ProjectError, fingerprint, resolve
from ui.main_window import MainWindow
from ui.project_dialog import ProjectHistoryDialog
from ui.project_workflow import _standalone_preview


class ProjectUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for target in ("ui.main_window.MainWindow._restore_settings", "ui.main_window.MainWindow._save_settings",
                       "ui.main_window._UpdateChecker.start"):
            context = patch(target)
            context.start()
            self.addCleanup(context.stop)
        self.window = MainWindow()
        self.addCleanup(self.window.deleteLater)
        self.window._choose_module(1)
        self.window.in_edit.setText(str(self.root))
        self.window.work_edit.setText(str(self.root))
        self.source = self.root / "linear.fits"
        fits.writeto(self.source, np.linspace(.01, .4, 1024, dtype=np.float32).reshape(32, 32))
        self.original = self.source.read_bytes()
        self.window._project = Project.create(self.root / "UI.forgepix", "UI", self.window._project_workspace())

    def tearDown(self):
        self.app.processEvents()

    def test_adoption_saves_history_and_old_selection_does_not_create_fake_steps(self):
        self.window._adopt_result(str(self.source), None)
        first = self.window._project.data["selected_step"]
        second_image = self.root / "processed.tif"
        tifffile.imwrite(second_image, fits.getdata(self.source) + .01)
        self.window._adopt_result(str(second_image), str(self.source))
        self.assertEqual(len(self.window._project.data["steps"]), 2)
        history = ProjectHistoryDialog(self.window._project, self.window._project.check(), self.window)
        self.addCleanup(history.deleteLater)
        self.assertIn("Vorgänger: 1. Bildbearbeitung · linear.fits", history.details.toPlainText())
        self.assertNotIn(first, history.details.toPlainText())
        self.window._open_project_step(first)
        self.assertEqual(Path(self.window.result_path).read_bytes(), self.original)
        self.assertEqual(len(self.window._project.data["steps"]), 2)
        self.assertTrue(self.window.export_btn.isEnabled())
        self.assertFalse(self.window._preview_pix.isNull())
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(Project.open(self.window._project.path).data["selected_step"], first)

    def test_history_disables_changed_saved_result_and_shows_original_status(self):
        self.window._adopt_result(str(self.source), None)
        identifier = self.window._project.data["selected_step"]
        self.source.write_bytes(b"changed")
        checks = self.window._project.check()
        history = ProjectHistoryDialog(self.window._project, checks, self.window)
        self.addCleanup(history.deleteLater)
        self.assertTrue(history.open_button.isEnabled())
        self.assertIn("Original fehlt oder verändert", history.tree.currentItem().text(2))
        archive = resolve(self.window._project.step(identifier)["result"]["path"], self.root)
        archive.unlink()
        changed = ProjectHistoryDialog(self.window._project, self.window._project.check(), self.window)
        self.addCleanup(changed.deleteLater)
        self.assertFalse(changed.open_button.isEnabled())
        self.assertTrue(changed.relocate.isEnabled())

    def test_project_worker_keeps_window_alive_until_its_write_finishes(self):
        release = threading.Event()
        self.window.show()
        def close_attempt():
            self.window.close()
            self.assertTrue(self.window.isVisible())
            release.set()
        QTimer.singleShot(20, close_attempt)
        value = self.window._project_job("Test", lambda: release.wait(2))
        self.assertTrue(value)
        self.assertIsNone(self.window._project_worker)

    def test_reopened_scientific_result_uses_project_copy_export_for_all_export_buttons(self):
        self.window._adopt_result(str(self.source), None)
        identifier = self.window._project.data["selected_step"]
        self.window._open_project_step(identifier)
        with patch.object(self.window, "export_project_result") as scientific_export:
            with patch("ui.export.imread", side_effect=AssertionError("No scientific conversion allowed")):
                self.window.export_result()
                self.window._quick_export("print")
                self.window._quick_export("instagram")
            self.assertEqual(scientific_export.call_count, 3)

    def _saved_ai_fixture(self):
        output = self.root / "ai-output"
        output.mkdir()
        result = output / "result_32bit.tif"
        pixels = fits.getdata(self.source) * np.float32(.98)
        tifffile.imwrite(result, pixels, description=json.dumps({"FPCOV": "coverage.tif"}))
        fits.writeto(result.with_suffix(".fits"), pixels, fits.Header({"FPCOV": "coverage.tif"}))
        tifffile.imwrite(output / "coverage.tif", np.ones(pixels.shape, np.uint8))
        files = [result, result.with_suffix(".fits"), output / "coverage.tif"]
        report = {"schema_version": 1, "task": "denoise", "model_id": "project-export-fixture", "strength": .5,
                  "source": {"path": str(self.source), "sha256": fingerprint(self.source)["sha256"]},
                  "outputs": [path.name for path in files],
                  "output_integrity": [{"name": path.name, **fingerprint(path)} for path in files]}
        (output / "ai_report.json").write_text(json.dumps(report), encoding="utf-8")
        identifier = self.window._project.add_result(result, self.source)
        self.window._open_project_step(identifier)
        self.assertTrue(self.window._is_ai_result_current())
        self.assertIsNotNone(self.window._ai_display_for_current())
        return result, Path(self.window.result_path)

    def test_changed_archived_ai_report_blocks_regular_and_quick_export_before_target_creation(self):
        _, archived = self._saved_ai_fixture()
        report = archived.parent / "ai_report.json"
        original_stat = report.stat()
        report.write_bytes(report.read_bytes().replace(b'"strength": 0.5', b'"strength": 0.6'))
        os.utime(report, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        self.assertEqual(report.stat().st_size, original_stat.st_size)
        with patch("ui.export.tempfile.mkdtemp") as target:
            with patch("ui.export.QFileDialog.getExistingDirectory", return_value=str(self.root)):
                with patch("ui.export.QMessageBox.warning") as warning:
                    self.window.export_result()
                    dialog = self.window._export_dlg
                    try:
                        next(button for button in dialog.findChildren(QPushButton)
                             if button.text() == "Speicherort wählen und exportieren").click()
                        warning.assert_called_once()
                        self.assertIn("Ergebnisdateien wurden verändert", warning.call_args.args[2])
                    finally:
                        dialog.reject()
            with patch("ui.export.QMessageBox.warning") as warning:
                self.window._quick_export("instagram")
                warning.assert_called_once()
                self.assertIn("Ergebnisdateien wurden verändert", warning.call_args.args[2])
            target.assert_not_called()
        self.assertFalse(list(self.root.rglob("export-ai-*")))

    def test_unchanged_archived_ai_group_and_external_current_result_remain_exportable(self):
        external, archived = self._saved_ai_fixture()
        for current, project in ((archived, self.window._project), (external, self.window._project), (external, None)):
            with self.subTest(current=str(current), project=project is not None):
                self.window._project = project
                self.assertTrue(self.window._restore_ai_result_context(current))
                self.window.result_path = str(current)
                exported = Path(self.window._write_ai_export(str(self.root), linear=True, png=True))
                for name in ("result_32bit.tif", "result_32bit.fits", "coverage.tif", "ai_report.json"):
                    self.assertEqual((exported / name).read_bytes(), (current.parent / name).read_bytes())
                self.assertTrue((exported / "display_stretched.png").is_file())

    def test_drizzle_sidecars_and_invalid_channel_pixels_survive_project_roundtrip(self):
        pixels = np.broadcast_to(np.linspace(.01, .25, 48, dtype=np.float32)[None, :, None], (40, 48, 3)).copy()
        mask = np.ones(pixels.shape, np.uint8)
        mask[:12] = 0
        mask[12:20, :, 0] = 0
        pixels[mask == 0] = 0
        names = {"FPCOV": "coverage.tif", "FPDRZCOV": "coverage_channels.tif", "FPDRZWGT": "drizzle_weights.tif"}
        source = self.root / "drizzle.tif"
        tifffile.imwrite(source, pixels, photometric="rgb", description=json.dumps(names))
        tifffile.imwrite(self.root / names["FPCOV"], np.all(mask, axis=-1).astype(np.uint8))
        tifffile.imwrite(self.root / names["FPDRZCOV"], mask, photometric="rgb")
        tifffile.imwrite(self.root / names["FPDRZWGT"], mask.astype(np.float32), photometric="rgb")
        (self.root / "drizzle_report.json").write_text(json.dumps({"scale": 2, "cfa": True}), encoding="utf-8")
        before = source.read_bytes()
        identifier = self.window._project.add_result(source)
        archived = Path(self.window._project.select(identifier)[0])
        for name in [*names.values(), "drizzle_report.json"]:
            self.assertEqual((archived.parent / name).read_bytes(), (self.root / name).read_bytes())
        exported = Path(self.window._project.export_step(identifier, self.root / "drizzle-export"))
        for name in [source.name, *names.values(), "drizzle_report.json"]:
            self.assertEqual((exported / name).read_bytes(), (self.root / name).read_bytes())
        history = ProjectHistoryDialog(self.window._project, self.window._project.check(), self.window)
        self.addCleanup(history.deleteLater)
        self.assertIn("Begleitdatei: coverage_channels.tif · Unverändert", history.details.toPlainText())
        preview = _standalone_preview(str(archived))
        shown = cv2.imread(preview["preview"], cv2.IMREAD_UNCHANGED)[..., ::-1]
        self.assertTrue(np.all(shown[mask == 0] == 0))
        self.assertGreater(float(shown[mask != 0].std()), 25)
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(archived.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
