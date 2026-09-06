"""Hardware changes and catalogue updates must not silently change processing."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from PySide6.QtWidgets import QApplication, QComboBox
from ui.equipment_dialog import EquipmentDialog
from ui.settings_io import SettingsMixin, app_settings


class _FilterSettings(SettingsMixin):
    def __init__(self, keys):
        self.astro_filter = QComboBox()
        for key in keys:
            self.astro_filter.addItem(key, key)

    def _settings_map(self):
        return {}


class EquipmentPersistence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.env = patch.dict(os.environ, {
            "FORGEPIX_SETTINGS_FILE": str(Path(self.folder.name) / "settings.ini")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.widgets = []
        self.addCleanup(self._close_widgets)

    def _close_widgets(self):
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        self.app.processEvents()

    def dialog(self, **kwargs):
        dialog = EquipmentDialog(**kwargs)
        self.widgets.append(dialog)
        return dialog

    def settings_window(self, keys):
        window = _FilterSettings(keys)
        self.widgets.append(window.astro_filter)
        return window

    @staticmethod
    def choose(combo, key):
        combo.setCurrentIndex(next(i for i in range(combo.count())
                                  if combo.itemData(i)[0] == key))

    def test_filter_survives_catalogue_reorder_and_insertion(self):
        before = self.settings_window(["uvir", "sv220_sii_oiii_7", "dual7"])
        before.astro_filter.setCurrentIndex(1)
        before._save_settings()
        after = self.settings_window(["dual7", "new_filter", "uvir", "sv220_sii_oiii_7"])
        after._restore_settings()
        self.assertEqual(after.astro_filter.currentData(), "sv220_sii_oiii_7")
        self.assertEqual(app_settings().value("equipment/filter"), "sv220_sii_oiii_7")
        self.assertFalse(app_settings().contains("astro_filter"))

    def test_legacy_index_migration_uses_historical_order(self):
        settings = app_settings()
        settings.setValue("astro_filter", 20)
        settings.sync()
        window = self.settings_window(["sv220_sii_oiii_7", "dual7", "uvir"])
        window.astro_filter.setCurrentIndex(1)
        window._restore_settings()
        self.assertEqual(window.astro_filter.currentData(), "sv220_sii_oiii_7")
        self.assertEqual(app_settings().value("astro_filter_key"), "sv220_sii_oiii_7")
        self.assertFalse(app_settings().contains("astro_filter"))

    def test_stable_filter_wins_over_stale_index(self):
        settings = app_settings()
        settings.setValue("astro_filter_key", "sv220_sii_oiii_7")
        settings.setValue("astro_filter", 8)  # Old H-alpha/OIII selection.
        settings.sync()
        window = self.settings_window(["dual7", "sv220_sii_oiii_7"])
        window._restore_settings()
        self.assertEqual(window.astro_filter.currentData(), "sv220_sii_oiii_7")

    def test_equipment_saved_filter_is_used_without_legacy_selection(self):
        dialog = self.dialog(initial_filter="sv220_sii_oiii_7")
        dialog.save()
        window = self.settings_window(["dual7", "sv220_sii_oiii_7"])
        window._restore_settings()
        self.assertEqual(window.astro_filter.currentData(), "sv220_sii_oiii_7")

    def test_custom_geometry_clears_only_the_affected_preset(self):
        dialog = self.dialog(initial_filter="sv220_sii_oiii_7")
        for combo, key in ((dialog.camera, "asi294mc"), (dialog.telescope, "rc8"),
                           (dialog.corrector, "red_064")):
            self.choose(combo, key)
            self.assertEqual(combo.currentData()[0], key)
        self.assertIn("f/5.12", dialog.summary.text())
        dialog.values["focal"].setValue(1600)
        self.assertEqual(dialog.telescope.currentData()[0], "manuell")
        self.assertEqual(dialog.camera.currentData()[0], "asi294mc")
        self.assertEqual(dialog.corrector.currentData()[0], "red_064")
        self.assertEqual(dialog.values["aperture"].value(), 203)
        dialog.values["pitch"].setValue(4.5)
        dialog.values["factor"].setValue(.66)
        dialog.save()
        restored = self.dialog()
        for combo in (restored.camera, restored.telescope, restored.corrector):
            self.assertEqual(combo.currentData()[0], "manuell")
        self.assertEqual(restored.values["focal"].value(), 1600)
        self.assertEqual(restored.values["factor"].value(), .66)
        self.assertEqual(restored.values["pitch"].value(), 4.5)
        self.assertEqual(restored.filter.currentData(), "sv220_sii_oiii_7")

    def test_reselecting_telescope_restores_both_preset_values(self):
        dialog = self.dialog()
        self.choose(dialog.telescope, "rc8")
        dialog.values["aperture"].setValue(200)
        dialog.values["focal"].setValue(1000)
        self.choose(dialog.telescope, "rc8")
        self.assertEqual(dialog.telescope.currentData()[0], "rc8")
        self.assertEqual(dialog.values["aperture"].value(), 203)
        self.assertEqual(dialog.values["focal"].value(), 1624)

    def test_existing_mismatched_settings_keep_geometry_but_clear_identity(self):
        settings = app_settings()
        for key, value in {"camera": "asi294mc", "pitch": 4.5,
                           "telescope": "rc8", "aperture": 203, "focal": 1600,
                           "corrector": "red_064", "factor": .63}.items():
            settings.setValue("equipment/" + key, value)
        settings.sync()
        dialog = self.dialog()
        self.assertEqual(dialog.values["focal"].value(), 1600)
        for combo in (dialog.camera, dialog.telescope, dialog.corrector):
            self.assertEqual(combo.currentData()[0], "manuell")
        dialog.reject()
        self.assertEqual(app_settings().value("equipment/telescope"), "rc8")

    def test_malformed_numeric_settings_do_not_break_dialog_start(self):
        settings = app_settings()
        settings.setValue("equipment/focal", "broken")
        settings.setValue("equipment/pitch", "nan")
        settings.setValue("equipment/binning", "inf")
        settings.sync()
        dialog = self.dialog()
        self.assertEqual(dialog.values["focal"].value(), 480)
        self.assertEqual(dialog.values["pitch"].value(), 3.76)
        self.assertEqual(dialog.binning.value(), 1)


if __name__ == "__main__":
    unittest.main()
