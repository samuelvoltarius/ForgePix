"""Local model GUI opt-in, worker lifecycle, and safe cancellation contracts."""
import os
import io
import json
import runpy
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from contextlib import redirect_stdout, redirect_stderr

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

import numpy as np
import tifffile
from PySide6.QtWidgets import QApplication, QDialog
from ui.ai_restore_dialog import AIRestoreDialog, _execution_feedback


class AIRestoreUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.settings = patch.dict(os.environ, {"FORGEPIX_SETTINGS_FILE": str(self.root / "settings.ini")})
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.source = self.root / "linear.tif"
        tifffile.imwrite(self.source, np.full((16, 16), .04, np.float32))
        self.original = self.source.read_bytes()
        self.api = SimpleNamespace(list_models=Mock(return_value=[{
            "id": "test-denoise", "task": "denoise", "available": True,
            "status": "experimental", "release_approved": False}]), run_file=Mock(),
            read_source=lambda path: tifffile.imread(path))
        self.module_patch = patch.dict(sys.modules, {"ai_restore": self.api})
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        self.dialogs = []
        self.addCleanup(self.close_dialogs)

    def close_dialogs(self):
        for dialog in self.dialogs:
            dialog.reject()
            self.wait_until(lambda: not dialog.is_running())
            dialog.deleteLater()
        self.app.processEvents()

    def wait_until(self, condition, timeout=3):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertTrue(condition(), "GUI worker did not finish in time")

    def dialog(self):
        dialog = AIRestoreDialog(source=str(self.source))
        self.dialogs.append(dialog)
        return dialog

    def test_missing_models_are_visible_without_enabling_processing(self):
        self.api.list_models.return_value = []
        dialog = self.dialog()
        self.assertEqual(dialog.task.count(), 4)
        dialog.confirm.setChecked(True)
        self.assertFalse(dialog.run_button.isEnabled())
        self.assertIn("kein verwendbares lokales Modell", dialog.model_status.text())
        dialog.start()
        self.api.run_file.assert_not_called()

    def test_opt_in_and_linear_file_extension_are_required(self):
        dialog = self.dialog()
        self.assertFalse(dialog.run_button.isEnabled())
        self.assertEqual(dialog.strength.value(), 50)
        self.assertEqual(dialog.device.currentData(), "auto")
        self.assertEqual([dialog.device.itemData(i) for i in range(dialog.device.count())], ["auto", "cpu"])
        dialog.confirm.setChecked(True)
        self.assertTrue(dialog.run_button.isEnabled())
        preview = self.root / "preview.jpg"
        preview.write_bytes(b"preview")
        dialog.source.setText(str(preview))
        self.assertFalse(dialog.run_button.isEnabled())
        dialog.source.setText(str(self.source))
        dialog.task.setCurrentIndex(dialog.task.findData("starless"))
        self.assertFalse(dialog.run_button.isEnabled())

    def test_real_worker_passes_request_and_exposes_separate_result(self):
        destination = self.root / "new-result"
        destination.mkdir()
        result = destination / "result_32bit.tif"

        def process(**request):
            self.assertIsInstance(request["cancel"], threading.Event)
            self.assertEqual(request["source"], str(self.source))
            self.assertEqual(request["model_id"], "test-denoise")
            self.assertEqual(request["strength"], .5)
            self.assertEqual(request["device"], "auto")
            self.assertTrue(request["allow_experimental"])
            request["progress"](1, 2)
            request["log"]("Testmodell verarbeitet das Bild.")
            tifffile.imwrite(result, np.full((16, 16), .039, np.float32))
            request["progress"](2, 2)
            return str(result)

        self.api.run_file.side_effect = process
        dialog = self.dialog()
        dialog.confirm.setChecked(True)
        dialog.start()
        self.assertTrue(dialog.is_running())
        self.assertFalse(dialog.run_button.isEnabled())
        self.wait_until(lambda: not dialog.is_running())
        self.assertEqual(dialog.result_path, str(result))
        self.assertFalse(dialog.result_actions.isHidden())
        self.assertEqual(self.source.read_bytes(), self.original)
        dialog.finish_with_result(True)
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertTrue(dialog.show_comparison)
        self.assertEqual(dialog.source_path, str(self.source))

    def test_cpu_device_is_forwarded_locked_and_completed_backend_is_shown(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        result = self.root / "result_32bit.tif"
        execution = {"requested_device": "cpu", "provider": "CPUExecutionProvider",
                     "applied": True, "fallback_used": False, "fallback_reasons": [],
                     "gpu_execution_verified": False}

        def process(**request):
            self.assertEqual(request["device"], "cpu")
            entered.set()
            release.wait(2)
            tifffile.imwrite(result, np.full((16, 16), .039, np.float32))
            (self.root / "ai_report.json").write_text(json.dumps({"execution": execution}), encoding="utf-8")
            return str(result)

        self.api.run_file.side_effect = process
        dialog = self.dialog()
        dialog.device.setCurrentIndex(dialog.device.findData("cpu"))
        dialog.confirm.setChecked(True)
        dialog.start()
        self.wait_until(entered.is_set)
        self.assertFalse(dialog.device.isEnabled())
        release.set()
        self.wait_until(lambda: not dialog.is_running())
        self.assertTrue(dialog.device.isEnabled())
        self.assertEqual(dialog.execution, execution)
        self.assertIn("Mit Prozessor berechnet.", dialog.feedback.text())

    def test_backend_feedback_uses_execution_record_not_available_gpu_list(self):
        fallback = {"provider": "CPUExecutionProvider", "applied": True,
                    "fallback_used": True, "registered_providers": ["DmlExecutionProvider"],
                    "available_providers": ["DmlExecutionProvider", "CPUExecutionProvider"]}
        self.assertIn("Grafikbeschleunigung war nicht verfügbar", _execution_feedback(fallback))
        self.assertEqual(_execution_feedback({"provider": "DmlExecutionProvider", "applied": True,
                                             "gpu_execution_verified": False}), "Rechenbackend: DirectML.")
        self.assertIn("kein Modell ausgeführt", _execution_feedback({"applied": False,
                                                                     "provider": "DmlExecutionProvider"}))
        self.assertIn("nicht angegeben", _execution_feedback(None))

    def test_cli_device_choices_are_forwarded_and_invalid_device_is_rejected(self):
        entrypoint = Path(__file__).resolve().parents[1] / "focus_stack_gui.py"
        command = [str(entrypoint), "--ai-restore", "--input", str(self.source),
                   "--model", "test-denoise", "--experimental"]
        self.api.run_file.return_value = "result.tif"
        for device in (None, "cpu", "gpu", "cuda", "directml", "coreml"):
            arguments = command + (["--device", device] if device else [])
            with self.subTest(device=device), patch.object(sys, "argv", arguments), redirect_stdout(io.StringIO()):
                runpy.run_path(str(entrypoint), run_name="__main__")
            self.assertEqual(self.api.run_file.call_args.kwargs["device"], device or "auto")
        self.api.run_file.reset_mock()
        with patch.object(sys, "argv", command + ["--device", "invalid"]), redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit) as error:
            runpy.run_path(str(entrypoint), run_name="__main__")
        self.assertEqual(error.exception.code, 2)
        self.api.run_file.assert_not_called()

    def test_close_cancels_and_retains_worker_until_finished(self):
        entered = threading.Event()

        def process(**request):
            entered.set()
            request["cancel"].wait(2)
            if request["cancel"].is_set():
                raise RuntimeError("KI-Verarbeitung abgebrochen.")
            raise RuntimeError("Test cancellation timeout")

        self.api.run_file.side_effect = process
        dialog = self.dialog()
        dialog.confirm.setChecked(True)
        dialog.show()
        dialog.start()
        self.wait_until(entered.is_set)
        worker = dialog.worker
        dialog.reject()
        self.assertIs(dialog.worker, worker)
        self.assertTrue(worker.cancel_event.is_set())
        self.assertTrue(dialog.isVisible())
        self.wait_until(lambda: not dialog.is_running())
        self.assertFalse(dialog.isVisible())
        self.assertIsNone(dialog.result_path)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_failure_keeps_dialog_usable(self):
        self.api.run_file.side_effect = RuntimeError("Modell ist beschädigt.")
        dialog = self.dialog()
        dialog.confirm.setChecked(True)
        dialog.start()
        self.wait_until(lambda: not dialog.is_running())
        self.assertIn("Modell ist beschädigt", dialog.feedback.text())
        self.assertTrue(dialog.run_button.isEnabled())
        self.assertIsNone(dialog.result_path)

    def test_changed_model_directory_requires_catalogue_refresh(self):
        dialog = self.dialog()
        dialog.confirm.setChecked(True)
        dialog.model_directory.setText(str(self.root))
        self.assertFalse(dialog.run_button.isEnabled())
        dialog.reload_models()
        self.api.list_models.assert_called_with(str(self.root))
        self.assertTrue(dialog.run_button.isEnabled())

    def test_astro_action_is_available_without_enabling_automatic_inference(self):
        from ui.main_window import MainWindow
        with patch.object(MainWindow, "_restore_settings"), \
             patch.object(MainWindow, "_save_settings"), \
             patch("ui.main_window._UpdateChecker.start"):
            window = MainWindow()
            try:
                window._choose_module(1)
                self.assertTrue(window.ai_restore_action.isVisible())
                self.assertTrue(window.ai_restore_action.isEnabled())
                args = window._build_args(auto=True)
                self.assertNotIn("--ai-restore", args)
                self.api.run_file.assert_not_called()
                window._choose_module(0)
                self.assertFalse(window.ai_restore_action.isVisible())
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_main_window_close_waits_for_cooperative_model_cancellation(self):
        from ui.main_window import MainWindow
        entered = threading.Event()

        def process(**request):
            entered.set()
            request["cancel"].wait(2)
            raise RuntimeError("KI-Verarbeitung abgebrochen.")

        self.api.run_file.side_effect = process
        with patch.object(MainWindow, "_restore_settings"), \
             patch.object(MainWindow, "_save_settings"), \
             patch("ui.main_window._UpdateChecker.start"):
            window = MainWindow()
            try:
                dialog = self.dialog()
                window._ai_restore_dialog = dialog
                window.show()
                dialog.show()
                dialog.confirm.setChecked(True)
                dialog.start()
                self.wait_until(entered.is_set)
                window.close()
                self.assertTrue(window.isVisible())
                self.assertTrue(dialog.worker.cancel_event.is_set())
                self.wait_until(lambda: not dialog.is_running())
                self.wait_until(lambda: not window.isVisible())
            finally:
                window._ai_restore_dialog = None
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
