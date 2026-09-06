"""Real Qt worker lifecycle, catalogue provenance and exclusive output files."""
import os
import sys
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtTest import QTest
import gaia_lokal
from ui.catalogue_dialog import CatalogueDialog


class CatalogueUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.cancel_and_close()
            self.wait_for(lambda: not dialog.is_running())
            dialog.deleteLater()
        self.app.processEvents()
        self.folder.cleanup()

    def dialog(self, **kwargs):
        dialog = CatalogueDialog(**kwargs)
        self.dialogs.append(dialog)
        return dialog

    def wait_for(self, predicate, timeout=5):
        end = time.monotonic() + timeout
        while not predicate() and time.monotonic() < end:
            QTest.qWait(10)
        self.assertTrue(predicate(), "Qt worker did not finish within test deadline")

    @staticmethod
    def catalogue(ra=10.):
        return gaia_lokal.Katalog([ra], [20.], [12.], [.5], metadata={
            "catalogue": "gaiadr3.gaia_source", "reference_epoch_jyear": 2016.,
            "proper_motion_applied": False, "fields": [{"ra_deg": ra, "radius_deg": 1.}]})

    def test_loading_legacy_catalogue_keeps_unknown_epoch_and_source(self):
        path = self.root / "old.npz"
        gaia_lokal.Katalog([10.], [20.], [12.], [.5]).speichern(path)
        before = path.read_bytes()
        dialog = self.dialog(catalogue_path=str(path))
        self.wait_for(lambda: not dialog.is_running())
        self.assertEqual(dialog.selected_path, str(path.resolve()))
        self.assertEqual(len(dialog.catalogue), 1)
        self.assertIn("unbekannt", dialog.metadata_text.text())
        self.assertIn("Vollständigkeit nicht geprüft", dialog.metadata_text.text())
        self.assertTrue(dialog.use_button.isEnabled())
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(path.read_bytes(), before)

    def test_download_is_async_bounded_and_saved_with_epoch(self):
        path = self.root / "new.npz"
        calls = []
        gui_thread = threading.get_ident()
        def download(**kwargs):
            calls.append((threading.get_ident(), kwargs))
            return self.catalogue()
        dialog = self.dialog(ra=300.17904, dec=22.795087, radius_deg=1.05)
        dialog.output.setText(str(path))
        with patch.object(gaia_lokal, "herunterladen", side_effect=download):
            dialog.start_download()
            self.assertTrue(dialog.is_running())
            self.assertFalse(dialog.use_button.isEnabled())
            self.wait_for(lambda: not dialog.is_running())
        self.assertNotEqual(calls[0][0], gui_thread)
        args = calls[0][1]
        self.assertAlmostEqual(args["ra"], 300.17904)
        self.assertAlmostEqual(args["dec"], 22.795087)
        self.assertEqual(args["radius_grad"], 1.05)
        self.assertEqual(args["grenze"], 20000)
        self.assertEqual(args["timeout"], 120)
        self.assertIsInstance(args["cancel"], threading.Event)
        saved = gaia_lokal.Katalog.laden(path, log=lambda *args: None)
        self.assertEqual(saved.metadata["reference_epoch_jyear"], 2016.)
        self.assertIn("J2016", dialog.metadata_text.text())
        self.assertIn("Eigenbewegung nicht fortgeschrieben", dialog.metadata_text.text())
        self.assertEqual(dialog.selected_path, str(path.resolve()))
        self.assertTrue(dialog.use_button.isEnabled())

    def test_existing_output_is_refused_without_network_or_overwrite(self):
        path = self.root / "existing.npz"
        path.write_bytes(b"source must survive")
        dialog = self.dialog()
        dialog.output.setText(str(path))
        with patch.object(gaia_lokal, "herunterladen") as download:
            dialog.start_download()
            download.assert_not_called()
        self.assertFalse(dialog.is_running())
        self.assertFalse(dialog.use_button.isEnabled())
        self.assertEqual(path.read_bytes(), b"source must survive")

    def test_close_requests_cancel_but_retains_thread_until_it_finishes(self):
        path = self.root / "cancelled.npz"
        started, may_finish = threading.Event(), threading.Event()
        def download(**kwargs):
            started.set()
            kwargs["cancel"].wait(3)
            may_finish.wait(3)
            raise gaia_lokal.ForgePixFehler("Vorgang abgebrochen.")
        dialog = self.dialog()
        dialog.output.setText(str(path))
        dialog.show()
        with patch.object(gaia_lokal, "herunterladen", side_effect=download):
            dialog.start_download()
            self.wait_for(started.is_set)
            dialog.cancel_and_close()
            self.assertTrue(dialog.is_running())
            self.assertTrue(dialog.isVisible())
            self.assertTrue(dialog.worker.cancel_event.is_set())
            may_finish.set()
            self.wait_for(lambda: not dialog.is_running())
        self.assertFalse(dialog.isVisible())
        self.assertIsNone(dialog.selected_path)
        self.assertFalse(path.exists())

    def test_merge_writes_new_file_and_preserves_loaded_original(self):
        original, output = self.root / "original.npz", self.root / "extended.npz"
        self.catalogue().speichern(original)
        before = original.read_bytes()
        dialog = self.dialog(catalogue_path=str(original))
        self.wait_for(lambda: not dialog.is_running())
        dialog.output.setText(str(output))
        dialog.merge.setChecked(True)
        with patch.object(gaia_lokal, "herunterladen", return_value=self.catalogue(11.)):
            dialog.start_download()
            self.wait_for(lambda: not dialog.is_running())
        self.assertEqual(len(dialog.catalogue), 2)
        self.assertEqual(len(dialog.catalogue.metadata["fields"]), 2)
        self.assertEqual(original.read_bytes(), before)
        self.assertEqual(len(gaia_lokal.Katalog.laden(output, log=lambda *args: None)), 2)

    def test_failed_download_never_appears_as_a_new_success(self):
        original, output = self.root / "original.npz", self.root / "failed.npz"
        self.catalogue().speichern(original)
        before = original.read_bytes()
        dialog = self.dialog(catalogue_path=str(original))
        self.wait_for(lambda: not dialog.is_running())
        dialog.output.setText(str(output))
        with patch.object(gaia_lokal, "herunterladen", side_effect=gaia_lokal.ForgePixFehler("ESA Zeitlimit")):
            dialog.start_download()
            self.wait_for(lambda: not dialog.is_running())
        self.assertIn("Zeitlimit", dialog.feedback.text())
        self.assertEqual(dialog.selected_path, str(original.resolve()))
        self.assertFalse(output.exists())
        self.assertEqual(original.read_bytes(), before)

    def test_bad_replacement_catalogue_clears_old_selection_and_merge(self):
        original = self.root / "original.npz"
        self.catalogue().speichern(original)
        dialog = self.dialog(catalogue_path=str(original))
        self.wait_for(lambda: not dialog.is_running())
        dialog.merge.setChecked(True)
        dialog.load_path(str(self.root / "missing.npz"))
        self.wait_for(lambda: not dialog.is_running())
        self.assertIsNone(dialog.selected_path)
        self.assertFalse(dialog.use_button.isEnabled())
        self.assertFalse(dialog.merge.isEnabled())
        self.assertFalse(dialog.merge.isChecked())


if __name__ == "__main__":
    unittest.main()
