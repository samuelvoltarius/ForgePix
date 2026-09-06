"""Actual recipe workers, scientific files and dialog lifecycle acceptance."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

import numpy as np
from astropy.io import fits
from PySide6.QtWidgets import QApplication
from project_store import Project
import recipes
from ui.recipe_dialog import RecipeDialog


class RecipeUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "linear.fits"
        rng = np.random.default_rng(614)
        pixels = rng.normal(.05, .002, (64, 80)).astype(np.float32)
        pixels[30, 30] = 1.1
        pixels[0, 0] = -.01
        fits.writeto(self.source, pixels, fits.Header({"FPLINEAR": True,
            "OBJECT": "Recipe independent fixture", "FILTER": "L", "EXPTIME": 300.0}))
        self.original = self.source.read_bytes()

    def make_dialog(self, **kw):
        dialog = RecipeDialog(source=self.source, **kw)
        dialog.destination.setText(str(self.root))
        self.addCleanup(dialog.deleteLater)
        return dialog

    def recipe(self):
        return {"format": "ForgePixRecipe", "schema_version": 1, "name": "Repeat",
                "steps": [recipes.pin_step("forgepix-background-mono-v2", strength=.25, device="cpu"),
                          recipes.pin_step("forgepix-denoise-mono-v2", strength=.5, device="cpu")]}

    def wait_for(self, predicate, seconds=25):
        end = time.monotonic() + seconds
        while not predicate() and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(.005)
        self.assertTrue(predicate(), "GUI operation timed out")

    def test_recipe_controls_persist_order_parameters_and_require_new_opt_in(self):
        dialog = self.make_dialog()
        dialog.set_recipe(self.recipe())
        self.assertFalse(dialog.run_button.isEnabled())
        dialog.confirm.setChecked(True)
        self.assertTrue(dialog.run_button.isEnabled())
        dialog.tree.setCurrentItem(dialog.tree.topLevelItem(1))
        dialog.strength.setValue(35)
        dialog.up_button.click()
        stored = dialog.recipe()
        self.assertEqual(stored["steps"][0]["task"], "denoise")
        self.assertEqual(stored["steps"][0]["strength"], .35)
        filename = self.root / "Portable.fprecipe"
        with patch("ui.recipe_dialog.QFileDialog.getSaveFileName", return_value=(str(filename), "")):
            dialog.save_button.click()
        dialog.remove_button.click()
        with patch("ui.recipe_dialog.QFileDialog.getOpenFileName", return_value=(str(filename), "")):
            dialog.load_button.click()
        self.assertEqual(dialog.recipe(), stored)
        self.assertFalse(dialog.confirm.isChecked())
        self.assertEqual(dialog.source.text(), str(self.source))

    def test_real_worker_repeats_on_second_fits_and_archives_each_step(self):
        try:
            import onnxruntime  # noqa: F401
        except ImportError:
            self.skipTest("ONNX runtime unavailable")
        project = Project.create(self.root / "Recipe.forgepix", "Recipe", {})
        dialog = self.make_dialog(project=project)
        dialog.set_recipe(self.recipe())
        dialog.confirm.setChecked(True)
        dialog.show()
        self.app.processEvents()
        dialog.run_button.click()
        self.assertTrue(dialog.is_running())
        self.assertFalse(dialog.editor.isEnabled())
        self.wait_for(lambda: not dialog.is_running())
        self.assertEqual(dialog.report["status"], "completed", dialog.feedback.text())
        first_run = dialog.report["run_dir"]
        result = fits.getdata(dialog.result_path)
        self.assertEqual(result.shape, (64, 80))
        self.assertTrue(np.isfinite(result).all())
        header = fits.getheader(dialog.result_path)
        self.assertEqual(header["OBJECT"], "Recipe independent fixture")
        self.assertEqual(header["FILTER"], "L")
        self.assertEqual(header["EXPTIME"], 300.0)
        self.assertEqual(len(project.data["steps"]), 2)
        self.assertEqual(Project.open(project.path).data["selected_step"], dialog.project_step)
        self.assertTrue(dialog.result_button.isEnabled())
        second = self.root / "second.fits"
        fits.writeto(second, fits.getdata(self.source) + .02, fits.getheader(self.source))
        second_original = second.read_bytes()
        dialog.source.setText(str(second))
        dialog.run_button.click()
        self.wait_for(lambda: not dialog.is_running())
        self.assertEqual(dialog.report["status"], "completed", dialog.feedback.text())
        self.assertNotEqual(dialog.report["run_dir"], first_run)
        self.assertEqual(dialog.report["input"]["sha256"], hashlib.sha256(second_original).hexdigest())
        self.assertEqual(second.read_bytes(), second_original)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(len(project.data["steps"]), 4)
        dialog.close()

    def test_validation_error_leaves_no_result_or_stuck_busy_controls(self):
        dialog = self.make_dialog()
        recipe = self.recipe()
        recipe["steps"][1]["model_sha256"] = "0" * 64
        dialog.set_recipe(recipe)
        dialog.confirm.setChecked(True)
        dialog.run_button.click()
        self.wait_for(lambda: not dialog.is_running())
        self.assertIsNone(dialog.result_path)
        self.assertIsNone(dialog.report)
        self.assertTrue(dialog.editor.isEnabled())
        self.assertFalse(dialog.result_button.isEnabled())
        self.assertTrue(dialog.feedback.text())
        self.assertEqual(list(self.root.iterdir()), [self.source])

    def test_later_archive_failure_keeps_new_result_without_selecting_old_step(self):
        project = Project.create(self.root / "Failure.forgepix", "Failure", {})
        dialog = self.make_dialog(project=project)
        dialog.set_recipe(self.recipe())
        dialog.confirm.setChecked(True)
        archive = project.add_result
        calls = []
        def fail_second(*args, **kwargs):
            calls.append(args[0])
            if len(calls) == 2:
                raise OSError("Archive device unavailable")
            return archive(*args, **kwargs)
        with patch.object(project, "add_result", side_effect=fail_second):
            dialog.run_button.click()
            self.wait_for(lambda: not dialog.is_running())
        self.assertEqual(dialog.report["status"], "failed")
        self.assertEqual(len(project.data["steps"]), 1)
        self.assertEqual(dialog.result_path, calls[1])
        self.assertIsNone(dialog.project_step)
        self.assertTrue(Path(dialog.result_path).is_file())
        self.assertEqual(dialog.tree.topLevelItem(1).text(2), "Sicherung fehlgeschlagen")
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_close_waits_for_cooperative_worker_completion(self):
        dialog = self.make_dialog()
        dialog.set_recipe(self.recipe())
        dialog.confirm.setChecked(True)
        dialog.show()

        def running(**request):
            self.assertTrue(request["cancel"].wait(3))
            return {"status": "cancelled", "run_dir": None, "result_path": None, "steps": []}

        with patch("recipes.run_recipe", side_effect=running):
            dialog.run_button.click()
            dialog.close()
            self.assertTrue(dialog.is_running())
            self.assertTrue(dialog.isVisible())
            self.wait_for(lambda: not dialog.is_running())
        self.assertFalse(dialog.isVisible())
        self.assertEqual(dialog.report["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
