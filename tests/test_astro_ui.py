"""The beginner Astro path must honor calibration without enabling comet mode."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow


class AstroUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_normal_astro_honors_calibration_and_cosmetic(self):
        with patch.object(MainWindow, "_restore_settings"), \
             patch.object(MainWindow, "_save_settings"), \
             patch("ui.main_window._UpdateChecker.start"):
            window = MainWindow()
            try:
                window.astro_group.setChecked(True)
                window.astro_komet.setChecked(False)
                window.astro_cosmetic.setChecked(True)
                window.astro_dark.setText("example-dark.fit")
                window.astro_flat.setText("example-flat.fit")
                args = window._common_args(".")
                self.assertIn("--dark", args)
                self.assertIn("example-flat.fit", args)
                self.assertIn("--astro-cosmetic", args)
                self.assertNotIn("--astro-komet", args)
                self.assertIn("--fits-out", args)
            finally:
                window.deleteLater()
                cls = type(self)
                cls.app.processEvents()

    def test_beginner_controls_and_nonoverlapping_expert_layout(self):
        with patch.object(MainWindow, "_restore_settings"), \
             patch.object(MainWindow, "_save_settings"), \
             patch("ui.main_window._UpdateChecker.start"):
            window = MainWindow()
            try:
                window._choose_module(1)
                window.mode_box.setCurrentIndex(0)
                self.assertTrue(window.astro_method.isHidden())
                self.assertFalse(window.astro_dark.isHidden())
                self.assertFalse(window.astro_filter.isHidden())
                window.mode_box.setCurrentIndex(1)
                self.assertFalse(window.astro_method.isHidden())
                layout = window.astro_group.layout()
                occupied = set()
                for index in range(layout.count()):
                    row, col, rows, cols = layout.getItemPosition(index)
                    for r in range(row, row + rows):
                        for c in range(col, col + cols):
                            self.assertNotIn((r, c), occupied, "Astro controls overlap")
                            occupied.add((r, c))
            finally:
                window.deleteLater()
                type(self).app.processEvents()

    def test_real_fits_start_resolves_series_before_processing(self):
        import numpy as np
        from astropy.io import fits
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(MainWindow, "_restore_settings"), \
             patch.object(MainWindow, "_save_settings"), \
             patch("ui.main_window._UpdateChecker.start"):
            series = Path(folder) / "M27"
            series.mkdir()
            fits.writeto(series / "Light.fit", np.ones((20, 20), np.float32))
            window = MainWindow()
            try:
                window._choose_module(1)
                window.in_edit.setText(folder)
                class Resolved(Exception):
                    pass
                with patch.object(window, "_guess_and_apply_module", side_effect=Resolved) as detect:
                    with self.assertRaises(Resolved):
                        window.run(auto=True)
                    detect.assert_called_once_with(str(series))
                self.assertEqual(window.in_edit.text(), str(series))
            finally:
                window.deleteLater()
                type(self).app.processEvents()
