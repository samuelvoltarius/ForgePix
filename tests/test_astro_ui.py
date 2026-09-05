"""The beginner Astro path must honor calibration without enabling comet mode."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
import unittest
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
