"""Opt-in real FITS/real-model acceptance through the local AI GUI menu.

No inference, worker, catalogue, or viewer is mocked. Each requested model reads
the same original linear FITS, writes into a fresh task folder, and is opened in
the native before/after viewer. --output must name a new folder whose parent
already exists. The default timeout requests safe cooperative cancellation.

Example: python tests/gui_ai_restore.py --input M27_linear.fits --output QA/run-001
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

TASKS = ("denoise", "background", "deblur", "starless")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Original linear mono/RGB FITS stack")
    parser.add_argument("--output", type=Path, required=True, help="New acceptance folder under an existing parent")
    parser.add_argument("--tasks", nargs="+", choices=TASKS, default=list(TASKS))
    parser.add_argument("--strength", type=float, default=.5, help="Model blend from 0 to 1, default .5")
    parser.add_argument("--timeout", type=int, default=600, help="Seconds per task before cooperative cancellation")
    options = parser.parse_args()
    if not math.isfinite(options.strength) or not 0 <= options.strength <= 1:
        parser.error("--strength must be a finite number from 0 to 1")
    if options.timeout < 1:
        parser.error("--timeout must be positive")
    if len(set(options.tasks)) != len(options.tasks):
        parser.error("--tasks must not repeat a task")
    source = options.input.resolve(strict=True)
    destination = options.output.resolve()
    if not source.is_file() or source.suffix.lower() not in {".fit", ".fits", ".fts"}:
        parser.error("--input must be a FITS file, not a JPEG or TIFF preview")
    if not destination.parent.is_dir():
        parser.error("The parent of --output must already exist")
    if destination.exists():
        parser.error("--output must be a new folder")
    destination.mkdir()
    os.environ["FORGEPIX_SETTINGS_FILE"] = str(destination / "settings.ini")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root), str(root / "core")]

    import numpy as np
    import tifffile
    from astropy.io import fits
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
    from ui.ai_restore_dialog import AIRestoreDialog
    from ui.components import CompareSlider
    from ui.main_window import MainWindow
    from ui.settings_io import app_settings
    from ui.theme import THEME
    import ai_restore

    original_stat = source.stat()
    original_hash = digest(source)
    source_pixels = ai_restore.read_source(source)
    source_header = fits.getheader(source)
    report = {
        "source": str(source), "source_sha256": original_hash,
        "source_size": original_stat.st_size, "source_mtime_ns": original_stat.st_mtime_ns,
        "source_shape": list(source_pixels.shape),
        "source_range": [float(source_pixels.min()), float(source_pixels.max())],
        "source_finite": bool(np.isfinite(source_pixels).all()),
        "source_header": {key: source_header.get(key) for key in
                          ("INSTRUME", "FILTER", "EXPTIME", "BAYERPAT", "FPLINEAR", "FPDOMAIN")},
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "worktree": subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).splitlines(),
        "python": sys.version, "strength": options.strength, "timeout_seconds_per_task": options.timeout,
        "model_directory": str(ai_restore.default_model_dir()),
        "models": ai_restore.list_models(), "tasks": [], "errors": [],
        "limitations": ["This acceptance verifies execution and file integrity, not scientific model quality.",
                        "Before and after share one source-derived display stretch; images remain model estimates."],
    }

    def save_report():
        (destination / "gui-ai-report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    app = QApplication([])
    for name in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf", "seguiemj.ttf"):
        font = Path("C:/Windows/Fonts") / name
        if font.is_file():
            QFontDatabase.addApplicationFont(str(font))
    app.setStyleSheet(THEME)
    settings = app_settings()
    settings.setValue("check_updates", "0")
    settings.setValue("language", "de")
    settings.sync()
    window = MainWindow()
    window._choose_module(1)
    window.resize(1280, 800)
    window.show()
    app.processEvents()
    report["parent_size"] = [window.width(), window.height()]
    started_all = time.monotonic()
    active_task = None

    def error_box():
        modal = app.activeModalWidget()
        if isinstance(modal, QMessageBox):
            message = modal.text() + (" " + modal.informativeText() if modal.informativeText() else "")
            (active_task["errors"] if active_task is not None else report["errors"]).append(message)
            modal.reject()

    error_timer = QTimer()
    error_timer.timeout.connect(error_box)
    error_timer.start(100)

    def validate_output(task_report, path, task_folder):
        output = Path(path).resolve(strict=True)
        if task_folder not in output.parents or output == source:
            raise ValueError("The model result escaped the fresh task folder")
        tiff_pixels = tifffile.imread(output)
        fits_path = output.with_suffix(".fits")
        with fits.open(fits_path, memmap=False) as hdus:
            saved_fits = hdus[0].data
            expected = np.moveaxis(tiff_pixels, -1, 0) if tiff_pixels.ndim == 3 else tiff_pixels
            np.testing.assert_array_equal(saved_fits, expected)
            task_report["fits_header"] = {key: hdus[0].header.get(key) for key in
                                          ("FPLINEAR", "FPDOMAIN", "FPQUAL", "FPAITASK", "FPAIMOD")}
        if tiff_pixels.dtype != np.float32 or tiff_pixels.shape != source_pixels.shape:
            raise ValueError("The result does not preserve shape and Float32 pixels")
        if not np.isfinite(tiff_pixels).all():
            raise ValueError("The result contains nonfinite pixels")
        core_report = json.loads((output.parent / "ai_report.json").read_text(encoding="utf-8"))
        if core_report["source"]["sha256"] != original_hash:
            raise ValueError("The core processed a different source file")
        if core_report["task"] != task_report["task"]:
            raise ValueError("The selected GUI function did not match the executed model task")
        if core_report["strength"] != task_report["actual_strength"]:
            raise ValueError("The GUI did not forward the selected strength")
        task_report.update(result_path=str(output), shape=list(tiff_pixels.shape), dtype=str(tiff_pixels.dtype),
                           range=[float(tiff_pixels.min()), float(tiff_pixels.max())],
                           finite=True, fits_tiff_equal=True, core_report=core_report,
                           outputs=[{"path": str(p), "size": p.stat().st_size, "sha256": digest(p)}
                                    for p in sorted(output.parent.iterdir()) if p.is_file()])
        if task_report["task"] == "starless":
            residual = tifffile.imread(output.parent / "stars_residual_32bit.tif")
            residual_fits = fits.getdata(output.parent / "stars_residual_32bit.fits")
            expected = np.moveaxis(residual, -1, 0) if residual.ndim == 3 else residual
            np.testing.assert_array_equal(residual_fits, expected)
            np.testing.assert_allclose(tiff_pixels.astype(np.float64) + residual, source_pixels,
                                       rtol=2e-6, atol=2e-6)
            task_report["residual_fits_tiff_equal"] = True
            task_report["reconstruction_max_error"] = float(np.max(
                np.abs(tiff_pixels.astype(np.float64) + residual - source_pixels)))

    try:
        for task in options.tasks:
            task_folder = destination / task
            task_folder.mkdir()
            task_report = {"task": task, "errors": [], "log": [], "timed_out": False,
                           "worker_started": False, "result_path": None}
            report["tasks"].append(task_report)
            active_task = task_report
            window.result_path = str(source)
            window.before_path = None
            window._set_preview(str(source))
            app.processEvents()
            window.grab().save(str(task_folder / "source.png"))
            elapsed_start = time.monotonic()
            timer = QTimer()
            timer.setSingleShot(True)

            def timeout():
                task_report["timed_out"] = True
                task_report["errors"].append("Task exceeded timeout; requested cooperative cancellation")
                save_report()
                dialog = getattr(window, "_ai_restore_dialog", None)
                if dialog is not None:
                    dialog.cancel_and_close()

            timer.timeout.connect(timeout)

            def configure():
                dialog = app.activeModalWidget()
                if not isinstance(dialog, AIRestoreDialog):
                    task_report["errors"].append("The Astro menu did not open AIRestoreDialog")
                    if isinstance(dialog, QDialog):
                        dialog.reject()
                    return
                try:
                    dialog.source.setText(str(source))
                    dialog.task.setCurrentIndex(dialog.task.findData(task))
                    dialog.destination.setText(str(task_folder))
                    dialog.strength.setValue(options.strength * 100)
                    task_report["actual_strength"] = dialog.strength.value() / 100
                    dialog.confirm.setChecked(True)
                    app.processEvents()
                    dialog.grab().save(str(task_folder / "configured.png"))
                    task_report["dialog_size"] = [dialog.width(), dialog.height()]
                    task_report["model"] = dialog.selected_model()
                    if not dialog.run_button.isEnabled():
                        raise RuntimeError(dialog.model_status.text() or "The GUI rejected the required inputs")
                    elapsed_start_nonlocal[0] = time.monotonic()
                    dialog.run_button.click()
                    worker = dialog.worker
                    if worker is None:
                        raise RuntimeError("The GUI did not create its model worker")
                    task_report["worker_started"] = True
                    task_report["worker_class"] = type(worker).__name__
                    task_report["worker_request"] = worker.request
                    worker.message.connect(task_report["log"].append)

                    def completed():
                        timer.stop()
                        task_report["processing_seconds"] = round(time.monotonic() - elapsed_start_nonlocal[0], 3)
                        task_report["feedback"] = dialog.feedback.text()
                        task_report["worker_finished"] = not dialog.is_running()
                        try:
                            if task_report["timed_out"] or not dialog.result_path:
                                raise RuntimeError(dialog.feedback.text() or "The model produced no result")
                            if dialog.previews is None or not dialog.compare_button.isEnabled():
                                raise RuntimeError(dialog.feedback.text() or "Linked comparison previews are missing")
                            task_report["linked_preview"] = dialog.previews
                            validate_output(task_report, dialog.result_path, task_folder)
                            app.processEvents()
                            dialog.grab().save(str(task_folder / "completed-dialog.png"))
                            dialog.compare_button.click()
                        except Exception as exc:
                            task_report["errors"].append(type(exc).__name__ + ": " + str(exc))
                            dialog.reject()
                        save_report()

                    worker.finished.connect(completed)
                    timer.start(options.timeout * 1000)
                    save_report()
                except Exception as exc:
                    task_report["errors"].append(type(exc).__name__ + ": " + str(exc))
                    dialog.reject()

            elapsed_start_nonlocal = [elapsed_start]
            QTimer.singleShot(0, configure)
            window.ai_restore_action.trigger()
            timer.stop()
            task_report["elapsed_seconds"] = round(time.monotonic() - elapsed_start, 3)
            task_report["gui_result_path"] = window.result_path
            if task_report["result_path"]:
                if window.result_path != task_report["result_path"]:
                    task_report["errors"].append("The main window did not adopt the completed result")
                app.processEvents()
                window.grab().save(str(task_folder / "after.png"))
                compare = getattr(window, "_cmp_dlg", None)
                if compare is not None and compare.isVisible():
                    slider = compare.findChild(CompareSlider)
                    task_report["native_comparison_opened"] = bool(
                        slider is not None and not slider.before.isNull() and not slider.after.isNull())
                    compare.grab().save(str(task_folder / "before-after.png"))
                    compare.close()
                else:
                    task_report["native_comparison_opened"] = False
                if not task_report["native_comparison_opened"]:
                    task_report["errors"].append("Native before/after viewer did not load both images")
            (task_folder / "worker.log").write_text("\n".join(task_report["log"]), encoding="utf-8")
            save_report()
    except Exception as exc:
        report["errors"].append(type(exc).__name__ + ": " + str(exc))
    finally:
        error_timer.stop()
        current_stat = source.stat()
        report["original_unchanged"] = (
            current_stat.st_size == original_stat.st_size and current_stat.st_mtime_ns == original_stat.st_mtime_ns
            and digest(source) == original_hash)
        if not report["original_unchanged"]:
            report["errors"].append("The original FITS changed during the acceptance run")
        report["elapsed_seconds"] = round(time.monotonic() - started_all, 3)
        report["passed"] = (not report["errors"] and len(report["tasks"]) == len(options.tasks)
                            and all(task["worker_started"] and task.get("worker_finished")
                                    and not task["errors"] for task in report["tasks"]))
        save_report()
        window.close()
    print(destination / "gui-ai-report.json", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
